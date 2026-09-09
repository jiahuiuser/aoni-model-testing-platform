"""
镜像部署服务 — 真实 docker pull / 离线导入 + 批量设备分发 + 部署日志(脱敏)

线程安全约定:
- 每个部署线程使用独立的 session_factory() 短生命周期 session（沿用 _mt_log 模式）,
  避免跨线程共享 Session 导致 SQLite "database is locked"。
"""
import re
import threading
from datetime import datetime

from backend.database import session_factory
from backend.models import DockerImage, Device, DeviceImageBinding, ImageDeployLog

# 并发部署线程池上限（每设备一个线程，控制总量）
_DEPLOY_SEMAPHORE = threading.Semaphore(8)


# ---------- 日志脱敏 ----------

# 匹配常见凭据形态: key=value / key: value / Bearer xxx / docker login -p 密码
_SECRET_PATTERNS = [
    (re.compile(r"(?i)(password[=:]\s*)[^\s\'\"]+"), r"\1***"),
    (re.compile(r"(?i)(passwd[=:]\s*)[^\s\'\"]+"), r"\1***"),
    (re.compile(r"(?i)(secret[=:]\s*)[^\s\'\"]+"), r"\1***"),
    (re.compile(r"(?i)(token[=:]\s*)[^\s\'\"]+"), r"\1***"),
    (re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s]+"), r"\1***"),
    (re.compile(r"(?i)\b(ak|sk)\s*[:=]\s*[A-Za-z0-9][A-Za-z0-9/+=_-]{10,}"), r"\1=***"),
    # docker login / sshpass / curl -u 风格: -p <密码> / --password <密码> / -u user:pwd
    (re.compile(r"(?i)(\s-p\s+)(\S+)"), r"\1***"),
    (re.compile(r"(?i)(\s--password(?:=|\s+))(\S+)"), r"\1***"),
    (re.compile(r"(?i)(\s-u\s+)(\S+:\S+)"), r"\1***"),
]


def sanitize_text(text: str) -> str:
    """日志脱敏: 把命令/输出中的敏感凭据替换为 ***"""
    if not text:
        return text
    out = text
    for pat, repl in _SECRET_PATTERNS:
        out = pat.sub(repl, out)
    return out


def _deploy_log(db, image_id: int, device_id: int | None, binding_id: int | None, level: str, message: str):
    """写部署日志（自动脱敏 + 裁剪长度）"""
    msg = sanitize_text(str(message))
    if len(msg) > 5000:
        msg = msg[:5000] + " ...(截断)"
    db.add(ImageDeployLog(
        image_id=image_id, device_id=device_id, binding_id=binding_id,
        level=level, message=msg,
    ))
    db.commit()


def _update_binding(db, binding_id: int, status: str | None = None, message: str | None = None, set_pulled: bool = False):
    """更新绑定状态（message 自动脱敏并裁剪）"""
    b = db.query(DeviceImageBinding).filter(DeviceImageBinding.id == binding_id).first()
    if not b:
        return
    if status:
        b.status = status
    if message is not None:
        m = sanitize_text(str(message))
        if len(m) > 2000:
            m = m[:2000] + "..."
        b.message = m
    if set_pulled:
        b.pulled_at = datetime.utcnow()
    db.commit()


def _build_pull_command(image: DockerImage) -> str:
    """根据镜像来源构造目标机上执行的拉取命令"""
    pull_cmd = (image.pull_command or "").strip()
    if pull_cmd:
        # 优先使用登录后获取的完整 pull 命令
        return pull_cmd
    # 兜底: 用 image_tag 直接 pull
    tag = (image.image_tag or "").strip()
    return f"docker pull {tag}"


def _deploy_one(image_id: int, device_id: int, binding_id: int):
    """在单个设备上执行 docker pull（独立线程 + 独立 session）"""
    with _DEPLOY_SEMAPHORE:
        db = session_factory()
        try:
            image = db.query(DockerImage).filter(DockerImage.id == image_id).first()
            device = db.query(Device).filter(Device.id == device_id).first()
            if not image or not device:
                _update_binding(db, binding_id, "failed", "镜像或设备不存在")
                return

            from backend.services.executor import RemoteRunner
            runner = RemoteRunner(device=device)

            # ── 镜像已存在检测: 已在目标机器上时跳过拉取（避免 registry 凭证过期等无关失败） ──
            try:
                chk = runner.run_shell(
                    f"docker image inspect {image.image_tag} --format '{{{{.Id}}}}' 2>/dev/null",
                    timeout=15,
                )
                if (chk.stdout or "").strip():
                    msg = f"镜像已存在于 [{device.name}({device.host})]，跳过拉取"
                    _update_binding(db, binding_id, "ready", msg, set_pulled=True)
                    _deploy_log(db, image_id, device_id, binding_id, "INFO", msg)
                    img = db.query(DockerImage).filter(DockerImage.id == image_id).first()
                    if img:
                        img.pulled = True
                        img.pulled_at = datetime.utcnow()
                        img.status = "deployed"
                        db.commit()
                    return
            except Exception:
                pass

            pull_cmd = _build_pull_command(image)
            _update_binding(db, binding_id, "pulling", f"开始拉取: {pull_cmd}")
            _deploy_log(db, image_id, device_id, binding_id, "INFO", f"[{device.name}({device.host})] 执行: {pull_cmd}")

            try:
                res = runner.run_shell(pull_cmd, timeout=3600)
                output = (res.stdout or "") + ("\n" + res.stderr if getattr(res, "stderr", None) else "")
                output = output.strip() or "(无输出)"
                ok = getattr(res, "returncode", 0) == 0
            except Exception as e:  # SSH 连接失败等
                output = f"执行异常: {e}"
                ok = False

            if ok:
                _update_binding(db, binding_id, "ready", output, set_pulled=True)
                _deploy_log(db, image_id, device_id, binding_id, "INFO", f"[{device.name}({device.host})] 拉取成功")
                # 更新镜像级拉取标记
                img = db.query(DockerImage).filter(DockerImage.id == image_id).first()
                if img:
                    img.pulled = True
                    img.pulled_at = datetime.utcnow()
                    img.status = "deployed"
                    db.commit()
            else:
                # 认证类失败给出可操作提示
                hint = ""
                low = output.lower()
                if "unauthorized" in low or "authentication required" in low or "token" in low and "expired" in low:
                    hint = (f"\n\n提示: 目标机器访问 registry 需要登录且凭证已失效，"
                            f"请先在 [{device.name}({device.host})] 上执行 docker login 后重试。")
                elif "unknown manifest" in low or "not found" in low or "pull access denied" in low:
                    hint = "\n\n提示: 镜像不存在或无权限访问，请检查 image tag 是否正确。"
                _update_binding(db, binding_id, "failed", output + hint)
                _deploy_log(db, image_id, device_id, binding_id, "ERROR", f"[{device.name}({device.host})] 拉取失败: {output}{hint}")
        except Exception as e:
            try:
                _update_binding(db, binding_id, "failed", f"内部错误: {e}")
                _deploy_log(db, image_id, device_id, binding_id, "ERROR", f"内部错误: {e}")
            except Exception:
                pass
        finally:
            db.close()


def deploy_image_to_devices(image_id: int, device_ids: list[int]) -> list[int]:
    """批量部署: 每台设备复用唯一绑定行(upsert), 起后台线程执行 docker pull, 返回 binding_id 列表

    绑定行代表该设备上的"当前状态", 重复下发覆盖同一行而不是新增行;
    完整下发历史由 ImageDeployLog 追加记录。"""
    db = session_factory()
    binding_ids = []
    threads = []
    try:
        image = db.query(DockerImage).filter(DockerImage.id == image_id).first()
        if not image:
            return []
        for did in device_ids:
            b = db.query(DeviceImageBinding).filter(
                DeviceImageBinding.image_id == image_id,
                DeviceImageBinding.device_id == did,
            ).first()
            if b and b.status in ("pending", "pulling"):
                _deploy_log(db, image_id, did, b.id, "INFO", "该设备已有部署任务进行中，本次下发已跳过")
                continue
            if b:
                b.status = "pending"
                b.message = None
                b.pulled_at = None
                db.commit()
                db.refresh(b)
            else:
                b = DeviceImageBinding(image_id=image_id, device_id=did, status="pending")
                db.add(b)
                db.commit()
                db.refresh(b)
            binding_ids.append(b.id)
            _deploy_log(db, image_id, did, b.id, "INFO", f"已创建部署任务 (设备ID={did})")
    finally:
        db.close()

    for i, bid in enumerate(binding_ids):
        t = threading.Thread(target=_deploy_one, args=(image_id, device_ids[i], bid), daemon=True)
        t.start()
        threads.append(t)
    return binding_ids


def sync_from_devices(devices: list) -> dict:
    """扫描各设备上实际存在的 docker 镜像，将对应用镜像标记为'已在该设备下发'。

    用于纠正平台下发状态与实际设备镜像不一致的问题（例如镜像早已手动 pull 到设备，
    但从未走平台下发流程，导致平台显示'未下发'）。
    """
    from backend.services.executor import RemoteRunner
    found = []      # (image_tag, device_name)
    errors = {}


    for dev in devices:
        runner = RemoteRunner(dev)
        tags = set()
        try:
            res = runner.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"], timeout=30)
            if res.returncode != 0 or not res.stdout:
                # 本机非 root/docker 组时重试 sudo
                res2 = runner.run(["sudo", "-n", "docker", "images", "--format", "{{.Repository}}:{{.Tag}}"], timeout=30)
                if res2.returncode == 0 and res2.stdout:
                    res = res2
                else:
                    err = (res.stderr or "").strip() or (res2.stderr or "").strip() or "无法执行 docker images"
                    errors[dev.name] = err[:120]
                    continue
            for line in res.stdout.strip().splitlines():
                line = line.strip()
                if line and "<none>" not in line:
                    tags.add(line)
        except Exception as e:
            errors[dev.name] = str(e)[:120]
            continue

        if not tags:
            continue

        db = session_factory()
        try:
            images = db.query(DockerImage).all()
            for img in images:
                if img.image_tag and img.image_tag in tags:
                    existing = db.query(DeviceImageBinding).filter(
                        DeviceImageBinding.image_id == img.id,
                        DeviceImageBinding.device_id == dev.id,
                    ).first()
                    if existing:
                        if existing.status != "ready":
                            existing.status = "ready"
                            existing.pulled_at = None
                    else:
                        db.add(DeviceImageBinding(
                            image_id=img.id, device_id=dev.id,
                            status="ready", pulled_at=None,
                        ))
                    found.append((img.image_tag, dev.name))
            db.commit()
        finally:
            db.close()

    return {"found": found, "errors": errors}


def list_deploy_logs(image_id: int, device_id: int | None = None, limit: int = 200):
    """查询部署历史日志（后台查看）"""
    db = session_factory()
    try:
        q = db.query(ImageDeployLog).filter(ImageDeployLog.image_id == image_id)
        if device_id:
            q = q.filter(ImageDeployLog.device_id == device_id)
        return q.order_by(ImageDeployLog.id.desc()).limit(limit).all()
    finally:
        db.close()


def list_bindings(image_id: int):
    """查询镜像的设备绑定与部署状态"""
    db = session_factory()
    try:
        return db.query(DeviceImageBinding).filter(
            DeviceImageBinding.image_id == image_id
        ).order_by(DeviceImageBinding.id.desc()).all()
    finally:
        db.close()
