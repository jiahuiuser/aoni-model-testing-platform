"""
设备管理 API — 基于凭证表的 SSH 远程连接
"""
import re
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from datetime import datetime

from backend.database import get_db
from backend.models import Device, Credential

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


@router.post("/devices")
def api_create_device(data: DeviceCreate, db: Session = Depends(get_db)):
    d = Device(**data.model_dump())
    db.add(d)
    db.commit()
    db.refresh(d)
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
    db.commit()
    d = db.execute(select(Device).options(joinedload(Device.credential)).where(Device.id == d.id)).unique().scalar()
    return _device_to_dict(d)


@router.delete("/devices/{device_id}")
def api_delete_device(device_id: int, db: Session = Depends(get_db)):
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "设备不存在")
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
            "type": c.type,
            "key_path": c.ssh_key_path,
            "password": c.password,
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


@router.post("/devices/{device_id}/check")
def api_check_device(device_id: int, db: Session = Depends(get_db)):
    """全面检测设备状态"""
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
        if gpu["ok"] and gpu["stdout"]:
            detail["gpu_info"] = gpu["stdout"]
            detail["gpu_count"] = len([l for l in gpu["stdout"].split("\n") if l.strip()])

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

    # 3. GPU
    gpu = _ssh_cmd("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null")
    if gpu["ok"] and gpu["stdout"]:
        detail["gpu_info"] = gpu["stdout"]
        detail["gpu_count"] = len([l for l in gpu["stdout"].split("\n") if l.strip()])
    else:
        teg = _ssh_cmd("cat /proc/device-tree/model 2>/dev/null; tegrastats --interval 100 --count 1 2>/dev/null | head -2", 15)
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
    """一键诊断设备环境健康度 (Device Doctor)"""
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

    return {
        "device_id": d.id,
        "device_name": d.name,
        "chip_name": driver.chip_name,
        "chip_type": chip_type,
        "score": score,
        "items": items
    }
