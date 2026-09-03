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
                _update_binding(db, binding_id, "failed", output)
                _deploy_log(db, image_id, device_id, binding_id, "ERROR", f"[{device.name}({device.host})] 拉取失败: {output}")
        except Exception as e:
            try:
                _update_binding(db, binding_id, "failed", f"内部错误: {e}")
                _deploy_log(db, image_id, device_id, binding_id, "ERROR", f"内部错误: {e}")
            except Exception:
                pass
        finally:
            db.close()


def deploy_image_to_devices(image_id: int, device_ids: list[int]) -> list[int]:
    """批量部署: 为每个设备创建绑定并起后台线程执行 docker pull, 返回 binding_id 列表"""
    db = session_factory()
    binding_ids = []
    threads = []
    try:
        image = db.query(DockerImage).filter(DockerImage.id == image_id).first()
        if not image:
            return []
        for did in device_ids:
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
