"""
设备管理 API — 基于凭证表的 SSH 远程连接
"""
import re
import json
import threading
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from datetime import datetime

from backend.database import get_db
from backend.models import Device, Credential

import logging
log = logging.getLogger("aoni-backend")

router = APIRouter(prefix="/api", tags=["devices"])


# ============================================================
#  凭证管理
# ============================================================

class CredentialCreate(BaseModel):
    name: str
    type: str = "ssh_key"  # ssh_key / password
    ssh_username: str
    ssh_port: int = 22
    ssh_key_path: str = ""
    password: str = ""
    description: str = ""


class CredentialUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    ssh_username: str | None = None
    ssh_port: int | None = None
    ssh_key_path: str | None = None
    password: str | None = None
    description: str | None = None


def _cred_to_dict(c: Credential) -> dict:
    return {
        "id": c.id, "name": c.name, "type": c.type,
        "ssh_username": c.ssh_username, "ssh_port": c.ssh_port or 22,
        "ssh_key_path": c.ssh_key_path or "",
        "password": "***" if c.password else "",
        "description": c.description or "",
    }


@router.get("/credentials")
def api_list_credentials(db: Session = Depends(get_db)):
    creds = db.execute(select(Credential).order_by(Credential.id)).scalars().all()
    return [_cred_to_dict(c) for c in creds]


@router.post("/credentials")
def api_create_credential(data: CredentialCreate, db: Session = Depends(get_db)):
    c = Credential(**data.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return _cred_to_dict(c)


@router.put("/credentials/{cred_id}")
def api_update_credential(cred_id: int, data: CredentialUpdate, db: Session = Depends(get_db)):
    c = db.get(Credential, cred_id)
    if not c:
        raise HTTPException(404, "凭证不存在")
    for field in ("name", "type", "ssh_username", "ssh_port", "ssh_key_path", "description"):
        val = getattr(data, field, None)
        if val is not None:
            setattr(c, field, val)
    if data.password and data.password != "***":
        c.password = data.password
    db.commit()
    return _cred_to_dict(c)


@router.delete("/credentials/{cred_id}")
def api_delete_credential(cred_id: int, db: Session = Depends(get_db)):
    c = db.get(Credential, cred_id)
    if not c:
        raise HTTPException(404, "凭证不存在")
    db.delete(c)
    db.commit()
    return {"status": "deleted"}


# ============================================================
#  设备管理
# ============================================================

class DeviceCreate(BaseModel):
    name: str
    host: str
    device_type: str = "jetson"
    chip_type: str = "nvidia_thor"
    port: int = 8800
    credential_id: int | None = None
    cpu_cores: int | None = None
    memory_gb: float | None = None
    gpu_info: str | None = None
    gpu_count: int | None = None
    description: str = ""
    # 便捷密码字段：填了会自动创建/复用 password 凭证并绑定
    ssh_username: str | None = None
    ssh_password: str | None = None
    ssh_port: int = 22


def _get_or_none(data, field: str):
    """字段存在且非 None 时返回值，否则 None"""
    if field in data.model_fields_set:
        return getattr(data, field, None)
    return None


class DeviceUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    device_type: str | None = None
    chip_type: str | None = None
    port: int | None = None
    credential_id: int | None = None
    cpu_cores: int | None = None
    memory_gb: float | None = None
    gpu_info: str | None = None
    gpu_count: int | None = None
    description: str | None = None
    # 便捷密码字段
    ssh_username: str | None = None
    ssh_password: str | None = None
    ssh_port: int | None = None


def _resolve_device_credential(db: Session, device: Device, data) -> None:
    """若提供了 ssh_username/ssh_password，自动创建或复用 password 凭证并绑定到设备"""
    ssh_username = getattr(data, "ssh_username", None)
    ssh_password = getattr(data, "ssh_password", None)
    ssh_port = getattr(data, "ssh_port", 22) or 22

    if not ssh_username or not ssh_password:
        return  # 未填密码则不处理

    if device.credential and device.credential.type == "password":
        # 复用/更新已有密码凭证
        c = device.credential
        c.ssh_username = ssh_username
        c.ssh_port = ssh_port
        c.password = ssh_password
    else:
        # 查找该 host 是否已有 password 凭证，否则新建
        existing = db.execute(
            select(Credential).where(
                Credential.type == "password",
                Credential.ssh_username == ssh_username,
            )
        ).scalars().first()
        if existing:
            c = existing
        else:
            c = Credential(
                name=f"{ssh_username}@{device.host or 'device'}-自动",
                type="password",
                ssh_username=ssh_username,
                ssh_port=ssh_port,
                password=ssh_password,
                description="设备表单自动创建的密码凭证",
            )
            db.add(c)
            db.flush()
    device.credential_id = c.id


def _device_to_dict(d: Device) -> dict:
    return {
        "id": d.id, "name": d.name, "host": d.host,
        "device_type": d.device_type,
        "chip_type": getattr(d, "chip_type", "nvidia_thor") or "nvidia_thor",
        "port": d.port,
        "credential_id": d.credential_id,
        "credential_name": d.credential.name if d.credential else "",
        "credential_type": d.credential.type if d.credential else "",
        "cpu_cores": d.cpu_cores, "memory_gb": d.memory_gb,
        "gpu_info": d.gpu_info, "gpu_count": d.gpu_count,
        "status": d.status,
        "description": d.description,
        "last_checked_at": d.last_checked_at.isoformat() if d.last_checked_at else None,
        "last_check_detail": d.last_check_detail,
    }


@router.get("/devices")
def api_list_devices(db: Session = Depends(get_db)):
    devices = db.execute(
        select(Device).options(joinedload(Device.credential)).order_by(Device.id)
    ).unique().scalars().all()
    return [_device_to_dict(d) for d in devices]


@router.get("/devices/{device_id}")
def api_get_device(device_id: int, db: Session = Depends(get_db)):
    d = db.execute(select(Device).options(joinedload(Device.credential)).where(Device.id == device_id)).unique().scalar_one_or_none()
    if not d:
        raise HTTPException(404, "设备不存在")
    return _device_to_dict(d)


def _trigger_bg_check(device_id: int):
    """后台线程立即体检一次设备（新建/编辑后调用，避免状态滞后）"""
    def _run():
        try:
            from backend.database import session_factory
            with session_factory() as sdb:
                run_device_check(sdb, device_id)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


@router.post("/devices")
def api_create_device(data: DeviceCreate, db: Session = Depends(get_db)):
    fields = data.model_dump()
    # 排除便捷 SSH 字段（它们不落在 devices 表，单独处理为凭证）
    for k in ("ssh_username", "ssh_password", "ssh_port"):
        fields.pop(k, None)
    d = Device(**fields)
    db.add(d)
    db.commit()
    db.refresh(d)
    # 若填了密码，自动创建/复用凭证并绑定
    _resolve_device_credential(db, d, data)
    db.commit()
    # 立即触发一次体检，避免新设备默认"在线"误导
    _trigger_bg_check(d.id)
    # 重新加载关联
    d = db.execute(select(Device).options(joinedload(Device.credential)).where(Device.id == d.id)).unique().scalar()
    return _device_to_dict(d)


@router.put("/devices/{device_id}")
def api_update_device(device_id: int, data: DeviceUpdate, db: Session = Depends(get_db)):
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "设备不存在")
    for field in ("name", "host", "device_type", "port", "credential_id",
                  "cpu_cores", "memory_gb", "gpu_info", "gpu_count", "description"):
        val = getattr(data, field, None)
        if val is not None:
            setattr(d, field, val)
    # 便捷密码字段：更新设备自身属性（若填了密码）
    ssh_username = _get_or_none(data, "ssh_username")
    ssh_password = _get_or_none(data, "ssh_password")
    ssh_port = _get_or_none(data, "ssh_port")
    # 更新到已绑定凭证或创建新凭证
    if ssh_username is not None or ssh_password is not None:
        # 构建一个伪 data 供 _resolve 使用（合并当前值 + 新值）
        from types import SimpleNamespace
        merged = SimpleNamespace(
            ssh_username=ssh_username if ssh_username is not None else (d.credential.ssh_username if d.credential else None),
            ssh_password=ssh_password,
            ssh_port=ssh_port if ssh_port is not None else (d.credential.ssh_port if d.credential else 22),
        )
        if merged.ssh_username and merged.ssh_password:
            _resolve_device_credential(db, d, merged)
    db.commit()
    # 地址或凭证可能变了，立即重新体检
    _trigger_bg_check(d.id)
    d = db.execute(select(Device).options(joinedload(Device.credential)).where(Device.id == d.id)).unique().scalar()
    return _device_to_dict(d)


@router.delete("/devices/{device_id}")
def api_delete_device(device_id: int, db: Session = Depends(get_db)):
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "设备不存在")
    # 显式清理该设备的模型-设备配置，避免删除后残留孤立的 PASS/FAIL 记录
    from backend.models import ModelDeviceConfig, Task
    db.execute(
        ModelDeviceConfig.__table__.delete().where(ModelDeviceConfig.device_id == device_id)
    )
    # 解除指向该设备的任务/模型运行引用
    db.execute(Task.__table__.update().where(Task.device_id == device_id).values(device_id=None))
    db.delete(d)
    db.commit()
    return {"status": "deleted"}


# ============================================================
#  健康检查
# ============================================================

def _get_ssh_from_device(d: Device) -> dict | None:
    """从设备的 credential 关联获取 SSH 连接信息"""
    if d.credential:
        c = d.credential
        return {
            "username": c.ssh_username,
            "ssh_port": c.ssh_port or 22,
            "key_path": c.ssh_key_path,
            "password": c.password,
            "type": c.type,
        }
    return None


def _ssh_run(ssh_info: dict, host: str, cmd: str, timeout: int = 15) -> dict:
    """通过 SSH 在远程设备执行命令"""
    import subprocess
    try:
        if ssh_info["type"] == "ssh_key":
            ssh_cmd = [
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=10",
                "-i", ssh_info["key_path"],
                "-p", str(ssh_info["ssh_port"]),
                f"{ssh_info['username']}@{host}", cmd
            ]
        else:
            ssh_cmd = [
                "sshpass", "-p", ssh_info["password"],
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=10",
                "-p", str(ssh_info["ssh_port"]),
                f"{ssh_info['username']}@{host}", cmd
            ]
        res = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)
        return {"ok": res.returncode == 0, "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(), "rc": res.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "SSH 超时", "rc": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "rc": -1}


def _local_run(cmd: str, timeout: int = 15) -> dict:
    import subprocess
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"ok": res.returncode == 0, "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(), "rc": res.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "超时", "rc": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "rc": -1}


def _parse_free_output(stdout: str) -> dict:
    result = {}
    for line in stdout.split("\n"):
        if line.startswith("Mem:"):
            parts = line.split()
            if len(parts) >= 7:
                result["total"] = parts[1]
                result["used"] = parts[2]
                result["available"] = parts[6]
    return result


def _parse_mxsmi(out: str) -> dict:
    """解析 mx-smi --show-memory 输出（沐曦 GPU），返回 {gpu_info, gpu_count}，失败返回 {}"""
    if not out:
        return {}
    names = re.findall(r"GPU#\d+\s+(\S+)", out)
    if not names:
        return {}
    total_kb = used_kb = 0
    m = re.search(r"vis_vram total\s*:\s*(\d+)\s*KB", out)
    if m:
        total_kb = int(m.group(1))
    m = re.search(r"vis_vram used\s*:\s*(\d+)\s*KB", out)
    if m:
        used_kb = int(m.group(1))
    if total_kb <= 0:
        return {}
    info = f"{names[0]}, {total_kb/1024/1024:.0f} GiB"
    if used_kb:
        info = f"{names[0]}, {used_kb/1024/1024:.1f}/{total_kb/1024/1024:.0f} GiB"
    return {"gpu_info": info, "gpu_count": len(names)}


@router.post("/devices/{device_id}/check")
def api_check_device(device_id: int, db: Session = Depends(get_db)):
    """全面检测设备状态（手动触发；后台定时采集也调用本函数）"""
    return run_device_check(db, device_id)


def run_device_check(db: Session, device_id: int) -> dict:
    """执行单台设备的全面检测并落库，返回 {status, detail}"""
    d = db.execute(
        select(Device).options(joinedload(Device.credential)).where(Device.id == device_id)
    ).unique().scalar()
    if not d:
        raise HTTPException(404, "设备不存在")

    ssh_info = _get_ssh_from_device(d)
    detail = {
        "ssh_ok": False, "docker_ok": False, "gpu_info": "", "gpu_count": 0,
        "memory": {}, "disk": {}, "cpu_cores": 0, "vllm": "", "errors": [],
    }

    # ========== 本机设备 ==========
    if not ssh_info:
        detail["ssh_ok"] = True  # 本机进程直连访问
        import requests
        try:
            r = requests.get(f"http://{d.host}:{d.port}/api/health", timeout=5)
            detail["platform_api"] = "ok" if r.status_code == 200 else f"HTTP {r.status_code}"
        except Exception as e:
            detail["platform_api"] = str(e)

        res = _local_run("docker ps --format '{{.Names}}' 2>/dev/null | head -10")
        if res["ok"]:
            detail["docker_ok"] = True
            detail["docker_containers"] = [x for x in res["stdout"].split("\n") if x.strip()]

        gpu = _local_run("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null")
        mx = _parse_mxsmi(_local_run("mx-smi --show-memory 2>/dev/null").get("stdout") or "")
        if gpu["ok"] and gpu["stdout"]:
            detail["gpu_info"] = gpu["stdout"]
            detail["gpu_count"] = len([l for l in gpu["stdout"].split("\n") if l.strip()])
        elif mx:
            detail["gpu_info"] = mx["gpu_info"]
            detail["gpu_count"] = mx["gpu_count"]

        mem = _local_run("LC_ALL=C free -h")
        if mem["ok"]:
            detail["memory"] = _parse_free_output(mem["stdout"])

        disk = _local_run("LC_ALL=C df -h / | tail -1")
        if disk["ok"]:
            parts = disk["stdout"].split()
            if len(parts) >= 5:
                detail["disk"] = {"total": parts[1], "used": parts[2], "available": parts[3], "use_pct": parts[4]}

        cpu = _local_run("nproc")
        if cpu["ok"] and cpu["stdout"]:
            detail["cpu_cores"] = int(cpu["stdout"].strip())

        _update_device_info(d, detail, db)
        return {"status": d.status, "detail": detail}

    # ========== 远程设备 SSH 检测 ==========
    def _ssh_cmd(cmd, timeout=10):
        return _ssh_run(ssh_info, d.host, cmd, timeout)

    # 1. SSH 连接
    ssh_test = _ssh_cmd("echo OK", 10)
    if not ssh_test["ok"]:
        detail["errors"].append(f"SSH连接失败: {ssh_test['stderr']}")
        d.status = "offline"
        d.last_checked_at = datetime.utcnow()
        d.last_check_detail = detail
        db.commit()
        return {"status": "offline", "detail": detail}
    detail["ssh_ok"] = True

    # 2. Docker
    docker_check = _ssh_cmd("sudo docker ps --format '{{.Names}}' 2>/dev/null | head -10", 10)
    if docker_check["ok"]:
        detail["docker_ok"] = True
        detail["docker_containers"] = [x for x in docker_check["stdout"].split("\n") if x.strip()]
    else:
        detail["errors"].append(f"Docker: {docker_check['stderr'][:100]}")

    # 3. GPU (NVIDIA → MetaX 沐曦 → 设备型号回退)
    gpu = _ssh_cmd("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null")
    if gpu["ok"] and gpu["stdout"]:
        detail["gpu_info"] = gpu["stdout"]
        detail["gpu_count"] = len([l for l in gpu["stdout"].split("\n") if l.strip()])
    else:
        mx = _parse_mxsmi(_ssh_cmd("mx-smi --show-memory 2>/dev/null", 15).get("stdout") or "")
        if mx:
            detail["gpu_info"] = mx["gpu_info"]
            detail["gpu_count"] = mx["gpu_count"]
        else:
            # 注. tegrastats 不支持 --count 参数会报错，这里只取设备型号（echo 补换行避免拼接）
            teg = _ssh_cmd("echo \"$(cat /proc/device-tree/model 2>/dev/null)\"", 15)
            if teg["ok"] and teg["stdout"]:
                detail["gpu_info"] = teg["stdout"]

    # 4. 内存
    mem = _ssh_cmd("LC_ALL=C free -h", 10)
    if mem["ok"]:
        detail["memory"] = _parse_free_output(mem["stdout"])

    # 5. 磁盘
    disk = _ssh_cmd("LC_ALL=C df -h / | tail -1", 10)
    if disk["ok"]:
        parts = disk["stdout"].split()
        if len(parts) >= 5:
            detail["disk"] = {"total": parts[1], "used": parts[2], "available": parts[3], "use_pct": parts[4]}

    # 6. CPU
    cpu = _ssh_cmd("nproc", 10)
    if cpu["ok"] and cpu["stdout"]:
        detail["cpu_cores"] = int(cpu["stdout"].strip())

    # 7. vLLM
    vllm = _ssh_cmd("pip show vllm 2>/dev/null | grep Version | awk '{print $2}'", 10)
    if vllm["ok"] and vllm["stdout"]:
        detail["vllm"] = vllm["stdout"].strip()

    # 8. 平台 API
    import requests
    try:
        r = requests.get(f"http://{d.host}:{d.port}/api/health", timeout=5)
        detail["platform_api"] = "ok" if r.status_code == 200 else f"HTTP {r.status_code}"
    except Exception as e:
        detail["platform_api"] = str(e)

    _update_device_info(d, detail, db)
    return {"status": d.status, "detail": detail}


def _update_device_info(d: Device, detail: dict, db: Session):
    """更新设备资源信息到数据库"""
    d.status = "online"
    d.last_checked_at = datetime.utcnow()
    d.last_check_detail = detail
    if detail.get("gpu_info"):
        d.gpu_info = detail["gpu_info"]
    if detail.get("gpu_count"):
        d.gpu_count = detail["gpu_count"]
    if detail.get("cpu_cores"):
        d.cpu_cores = detail["cpu_cores"]
    mem = detail.get("memory", {})
    if mem.get("total"):
        try:
            d.memory_gb = float(mem["total"].replace("Gi", "").replace("G", ""))
        except (ValueError, AttributeError):
            pass
    db.commit()


@router.post("/devices/{device_id}/doctor")
def api_doctor_device(device_id: int, db: Session = Depends(get_db)):
    """一键诊断设备环境健康度 (Device Doctor，融合资源快照采集)"""
    from backend.services.executor import RemoteRunner
    from backend.services.hardware import get_hardware_driver

    d = db.execute(
        select(Device).options(joinedload(Device.credential)).where(Device.id == device_id)
    ).unique().scalar()
    if not d:
        raise HTTPException(404, "设备不存在")

    runner = RemoteRunner(d)
    chip_type = getattr(d, "chip_type", "nvidia_thor") or "nvidia_thor"
    driver = get_hardware_driver(chip_type)

    items = []

    # 1. SSH 远程连通性与凭证
    if runner.is_remote:
        ssh_res = runner.run_shell("echo SSH_OK", timeout=8)
        if ssh_res.returncode == 0 and "SSH_OK" in ssh_res.stdout:
            items.append({
                "id": "ssh", "title": "SSH 远程网络连通性", "ok": True,
                "detail": f"凭证 [{d.credential.name}] 验证通过，已建立连通 ({d.host}:{d.credential.ssh_port or 22})",
                "remediation": None
            })
        else:
            items.append({
                "id": "ssh", "title": "SSH 远程网络连通性", "ok": False,
                "detail": f"无法建立 SSH 连接: {ssh_res.stderr or '连接超时/拒绝'}",
                "remediation": f"请排查目标 IP ({d.host})、端口 ({d.credential.ssh_port or 22})、密码/密钥及 sshpass 依赖:\nsudo apt-get install -y sshpass && ssh-keyscan -H {d.host} >> ~/.ssh/known_hosts"
            })
    else:
        items.append({
            "id": "ssh", "title": "节点访问模式", "ok": True,
            "detail": "本机直接访问模式", "remediation": None
        })

    # 2. Docker 服务与权限
    dock_res = runner.run_docker(["ps", "--format", "{{.Names}}"], timeout=8)
    if dock_res.returncode == 0:
        items.append({
            "id": "docker", "title": "Docker 守护进程与免 sudo 权限", "ok": True,
            "detail": "Docker 守护进程运行正常，已具备容器调度权限",
            "remediation": None
        })
    else:
        err_msg = dock_res.stderr or dock_res.stdout
        items.append({
            "id": "docker", "title": "Docker 守护进程与免 sudo 权限", "ok": False,
            "detail": f"Docker 指令无法正常运行: {err_msg[:120]}",
            "remediation": "请确保目标节点已启动 Docker 守护进程，并将 SSH 登录账号加进 docker 用户组:\nsudo usermod -aG docker $USER && sudo systemctl restart docker"
        })

    # 3. 芯片驱动与算力硬件识别
    chip_check = driver.run_doctor_check(runner)
    items.append({
        "id": "chip", "title": f"算力芯片与驱动 ({driver.chip_name})",
        "ok": chip_check["ok"],
        "detail": chip_check["detail"],
        "remediation": chip_check.get("remediation")
    })

    # 4. 磁盘挂载点空间
    avail_gb = runner.get_available_disk_gb()
    if avail_gb >= 30.0:
        items.append({
            "id": "disk", "title": "模型挂载点磁盘剩余空间", "ok": True,
            "detail": f"宿主机可用磁盘空间充裕 ({avail_gb:.1f} GB ≥ 30 GB)",
            "remediation": None
        })
    elif avail_gb >= 15.0:
        items.append({
            "id": "disk", "title": "模型挂载点磁盘剩余空间", "ok": True,
            "detail": f"宿主机可用磁盘空间预警 ({avail_gb:.1f} GB < 30 GB)，可能影响大模型加载",
            "remediation": "建议清理宿主机 /models 或 /tmp 下无用的权重镜像压缩文件:\nsudo rm -rf /tmp/vllm_* /models/*.tar.gz"
        })
    else:
        items.append({
            "id": "disk", "title": "模型挂载点磁盘剩余空间", "ok": False,
            "detail": f"磁盘空间极度匮乏 (仅剩余 {avail_gb:.1f} GB < 15 GB)，任务将无法正常解压模型",
            "remediation": "请清理宿主机磁盘以释放至少 30 GB 空间:\nsudo docker system prune -af && sudo rm -rf ~/.cache/huggingface"
        })

    # 5. 默认压测端口 8300
    port_res = runner.run_shell("netstat -tuln 2>/dev/null || ss -tuln 2>/dev/null", timeout=5)
    if ":8300 " in port_res.stdout:
        items.append({
            "id": "port", "title": "测试端口 (8300) 状态", "ok": True,
            "detail": "端口 8300 当前被占用（有正在运行的推理引擎容器）",
            "remediation": None
        })
    else:
        items.append({
            "id": "port", "title": "测试端口 (8300) 状态", "ok": True,
            "detail": "端口 8300 空闲就绪",
            "remediation": None
        })

    passed_count = sum(1 for it in items if it["ok"])
    score = int(passed_count / len(items) * 100)

    # 融合资源快照采集 (复用健康检查逻辑，本机/远程通吃)
    resource = _collect_resource_detail(d, runner)
    _update_device_info(d, resource, db)

    return {
        "device_id": d.id,
        "device_name": d.name,
        "chip_name": driver.chip_name,
        "chip_type": chip_type,
        "score": score,
        "items": items,
        "resource": resource
    }


def _runner_run(runner, cmd: str, timeout: int = 10) -> str:
    """通过 RemoteRunner 执行命令并返回 stdout"""
    try:
        res = runner.run_shell(cmd, timeout=timeout)
        return (res.stdout or "").strip()
    except Exception:
        return ""


def _collect_resource_detail(d: Device, runner) -> dict:
    """采集设备资源快照 (SSH/Docker/GPU/内存/磁盘/CPU/vLLM/平台API)，兼容本机与远程"""
    import requests as _requests
    ssh_info = _get_ssh_from_device(d)
    run = lambda cmd, t=10: _runner_run(runner, cmd, t)

    detail = {
        "ssh_ok": False, "docker_ok": False, "gpu_info": "", "gpu_count": 0,
        "memory": {}, "disk": {}, "cpu_cores": 0, "vllm": "", "errors": [],
    }

    if not ssh_info:
        detail["ssh_ok"] = True  # 本机
        try:
            r = _requests.get(f"http://{d.host}:{d.port}/api/health", timeout=5)
            detail["platform_api"] = "ok" if r.status_code == 200 else f"HTTP {r.status_code}"
        except Exception as e:
            detail["platform_api"] = str(e)
    else:
        ssh_test = _ssh_run(ssh_info, d.host, "echo OK", 10)
        if not ssh_test["ok"]:
            detail["errors"].append(f"SSH连接失败: {ssh_test['stderr']}")
        else:
            detail["ssh_ok"] = True
        try:
            r = _requests.get(f"http://{d.host}:{d.port}/api/health", timeout=5)
            detail["platform_api"] = "ok" if r.status_code == 200 else f"HTTP {r.status_code}"
        except Exception as e:
            detail["platform_api"] = str(e)

    # Docker 容器列表
    dock = run("docker ps --format '{{.Names}}' 2>/dev/null | head -10")
    if dock:
        detail["docker_ok"] = True
        detail["docker_containers"] = [x for x in dock.split("\n") if x.strip()]

    # GPU (NVIDIA → MetaX 沐曦 → 设备型号回退)
    gpu = run("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null")
    mx = _parse_mxsmi(run("mx-smi --show-memory 2>/dev/null", 15))
    if gpu:
        detail["gpu_info"] = gpu
        detail["gpu_count"] = len([l for l in gpu.split("\n") if l.strip()])
    elif mx:
        detail["gpu_info"] = mx["gpu_info"]
        detail["gpu_count"] = mx["gpu_count"]
    else:
        # 注. tegrastats 不支持 --count 参数会报错，这里只取设备型号（echo 补换行避免拼接）
        teg = run("echo \"$(cat /proc/device-tree/model 2>/dev/null)\"", 15)
        if teg:
            detail["gpu_info"] = teg

    # 内存
    mem = run("LC_ALL=C free -h")
    if mem:
        detail["memory"] = _parse_free_output(mem)

    # 磁盘
    disk = run("LC_ALL=C df -h / | tail -1")
    if disk:
        parts = disk.split()
        if len(parts) >= 5:
            detail["disk"] = {"total": parts[1], "used": parts[2], "available": parts[3], "use_pct": parts[4]}

    # CPU
    cpu = run("nproc")
    if cpu and cpu.isdigit():
        detail["cpu_cores"] = int(cpu)

    # vLLM 版本
    vllm = run("pip show vllm 2>/dev/null | grep Version | awk '{print $2}'")
    if vllm:
        detail["vllm"] = vllm

    return detail


# ==================== 后台定时采集 ====================

_DEVICE_COLLECT_INTERVAL = 60          # 采集间隔（秒）
_device_collect_started = False        # 防止重复启动
_device_collecting = False             # 防止上一轮未完成时重叠执行


def _device_collect_loop():
    """后台线程: 周期性采集全部设备的资源快照并落库"""
    global _device_collecting
    import time
    import traceback

    while True:
        time.sleep(_DEVICE_COLLECT_INTERVAL)
        if _device_collecting:
            continue
        _device_collecting = True
        t0 = time.time()
        try:
            from backend.database import session_factory
            with session_factory() as db:
                device_ids = db.execute(select(Device.id)).scalars().all()
            for did in device_ids:
                try:
                    from backend.database import session_factory as _sf
                    with _sf() as sdb:
                        run_device_check(sdb, did)
                except Exception:
                    log.warning(f"设备[{did}]定时采集失败: {traceback.format_exc()[-300:]}")
            log.info(f"设备定时采集完成: {len(device_ids)} 台, 耗时 {time.time()-t0:.1f}s")
        except Exception:
            log.error(f"设备定时采集异常: {traceback.format_exc()[-300:]}")
        finally:
            _device_collecting = False


def start_device_collect_if_needed():
    """启动后台定时采集线程（幂等）"""
    global _device_collect_started
    if _device_collect_started:
        return
    _device_collect_started = True
    t = threading.Thread(target=_device_collect_loop, daemon=True, name="device-collector")
    t.start()
    log.info("设备定时采集线程已启动 (每 60 秒一轮)")
