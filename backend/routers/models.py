"""
模型管理 API — 支持多设备专属配置
"""
import re
import time
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import ModelInfo, ModelDeviceConfig, Device
from backend.services.pipeline import get_size_category_map
from backend.services.executor import RemoteRunner

router = APIRouter(prefix="/api/models", tags=["models"])

CONTAINER_NAME = "model_test_runner"
TEST_PORT = 8400
MAX_VLLM_WAIT = 300  # 缩短轮询超时到 5 分钟


# ============================================================
#  Schema
# ============================================================

class ModelCreate(BaseModel):
    name: str
    slug: str
    docker_command: str = ""
    tos_path: str = ""


class ModelUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    docker_command: str | None = None
    tos_path: str | None = None


class DeviceConfigCreate(BaseModel):
    device_id: int
    docker_command: str = ""


class DeviceConfigUpdate(BaseModel):
    docker_command: str | None = None


def _model_to_dict(m: ModelInfo, device_id: int | None = None) -> dict:
    """模型转 dict，可选按 device_id 返回专属配置"""
    # 查找该设备的专属配置
    device_config = None
    if device_id:
        for dc in m.device_configs:
            if dc.device_id == device_id:
                device_config = dc
                break

    return {
        "id": m.id,
        "idx": m.idx, "name": m.name, "slug": m.slug,
        "size_category": m.size_category or "unknown",
        "status": device_config.status if device_config else m.status,
        "tos_path": m.tos_path or "",
        "docker_command": device_config.docker_command if device_config else (m.docker_command or ""),
        "result_detail": device_config.result_detail if device_config else (m.result_detail or ""),
        "device_configs": [
            {
                "id": dc.id,
                "device_id": dc.device_id,
                "device_name": dc.device.name if dc.device else "",
                "docker_command": dc.docker_command or "",
                "status": dc.status,
                "result_detail": dc.result_detail or "",
                "tested_at": dc.tested_at.isoformat() if dc.tested_at else None,
            }
            for dc in m.device_configs
        ],
    }


def _load_model_with_configs(db: Session, slug: str) -> ModelInfo | None:
    """加载模型及其所有设备配置"""
    return db.execute(
        select(ModelInfo)
        .options(joinedload(ModelInfo.device_configs).joinedload(ModelDeviceConfig.device))
        .where(ModelInfo.slug == slug)
    ).unique().scalar_one_or_none()


# ============================================================
#  CRUD
# ============================================================

@router.get("")
def api_list_models(device_id: int | None = Query(None), db: Session = Depends(get_db)):
    """列出模型，可选按 device_id 筛选（只返回该设备上 PASS 的模型）"""
    models = db.execute(
        select(ModelInfo)
        .options(joinedload(ModelInfo.device_configs).joinedload(ModelDeviceConfig.device))
        .order_by(ModelInfo.idx)
    ).unique().scalars().all()

    result = []
    for m in models:
        d = _model_to_dict(m, device_id)
        # 如果指定了 device_id，只返回该设备上有配置且 PASS 的模型
        if device_id:
            dc = next((c for c in m.device_configs if c.device_id == device_id), None)
            if not dc or dc.status != "PASS":
                continue
        result.append(d)
    return result


@router.post("")
def api_create_model(data: ModelCreate, db: Session = Depends(get_db)):
    existing = db.execute(select(ModelInfo).where(ModelInfo.slug == data.slug)).scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"slug '{data.slug}' 已存在")

    max_idx = db.execute(select(ModelInfo.idx).order_by(ModelInfo.idx.desc())).scalar() or 0
    m = ModelInfo(
        idx=max_idx + 1, name=data.name, slug=data.slug,
        docker_command=data.docker_command, tos_path=data.tos_path,
        status="NEW",
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _model_to_dict(m)


@router.put("/{slug}")
def api_update_model(slug: str, data: ModelUpdate, db: Session = Depends(get_db)):
    m = db.execute(select(ModelInfo).where(ModelInfo.slug == slug)).scalar_one_or_none()
    if not m:
        raise HTTPException(404, f"模型 '{slug}' 不存在")
    if data.name is not None: m.name = data.name
    if data.slug is not None: m.slug = data.slug
    if data.docker_command is not None: m.docker_command = data.docker_command
    if data.tos_path is not None: m.tos_path = data.tos_path
    db.commit()
    db.refresh(m)
    return _model_to_dict(m)


@router.delete("/{slug}")
def api_delete_model(slug: str, db: Session = Depends(get_db)):
    m = db.execute(select(ModelInfo).where(ModelInfo.slug == slug)).scalar_one_or_none()
    if not m:
        raise HTTPException(404, f"模型 '{slug}' 不存在")
    db.delete(m)
    db.commit()
    return {"status": "deleted", "slug": slug}


# ============================================================
#  设备专属配置 CRUD
# ============================================================

@router.get("/{slug}/device-configs")
def api_list_device_configs(slug: str, db: Session = Depends(get_db)):
    """获取模型的所有设备配置"""
    m = _load_model_with_configs(db, slug)
    if not m:
        raise HTTPException(404, f"模型 '{slug}' 不存在")
    return [
        {
            "id": dc.id, "device_id": dc.device_id,
            "device_name": dc.device.name if dc.device else "",
            "docker_command": dc.docker_command or "",
            "status": dc.status,
            "result_detail": dc.result_detail or "",
            "tested_at": dc.tested_at.isoformat() if dc.tested_at else None,
        }
        for dc in m.device_configs
    ]


@router.post("/{slug}/device-configs")
def api_create_device_config(slug: str, data: DeviceConfigCreate, db: Session = Depends(get_db)):
    """为模型添加设备专属配置"""
    m = db.execute(select(ModelInfo).where(ModelInfo.slug == slug)).scalar_one_or_none()
    if not m:
        raise HTTPException(404, f"模型 '{slug}' 不存在")

    device = db.get(Device, data.device_id)
    if not device:
        raise HTTPException(404, "设备不存在")

    # 检查是否已存在
    existing = db.execute(
        select(ModelDeviceConfig).where(
            ModelDeviceConfig.model_id == m.id,
            ModelDeviceConfig.device_id == data.device_id
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "该设备已存在配置，请使用编辑")

    dc = ModelDeviceConfig(
        model_id=m.id, device_id=data.device_id,
        docker_command=data.docker_command, status="NEW",
    )
    db.add(dc)
    db.commit()
    db.refresh(dc)
    # 重新加载
    m = _load_model_with_configs(db, slug)
    return _model_to_dict(m)


@router.put("/{slug}/device-configs/{config_id}")
def api_update_device_config(slug: str, config_id: int, data: DeviceConfigUpdate, db: Session = Depends(get_db)):
    """更新设备专属配置"""
    dc = db.get(ModelDeviceConfig, config_id)
    if not dc:
        raise HTTPException(404, "配置不存在")
    if data.docker_command is not None:
        dc.docker_command = data.docker_command
    db.commit()
    m = _load_model_with_configs(db, slug)
    return _model_to_dict(m)


@router.delete("/{slug}/device-configs/{config_id}")
def api_delete_device_config(slug: str, config_id: int, db: Session = Depends(get_db)):
    """删除设备专属配置"""
    dc = db.get(ModelDeviceConfig, config_id)
    if not dc:
        raise HTTPException(404, "配置不存在")
    db.delete(dc)
    db.commit()
    return {"status": "deleted"}


# ============================================================
#  一键测试 (支持设备维度)
# ============================================================

def _stop_test_container(runner: RemoteRunner | None = None):
    """停止测试容器（支持远程）"""
    try:
        if runner:
            inspect = runner.run_docker(["inspect", "-f", "{{.State.Running}}", CONTAINER_NAME], timeout=5)
            if inspect.stdout.strip() == "true":
                runner.run_docker(["stop", "-t", "15", CONTAINER_NAME], timeout=30)
                time.sleep(1)
            check = runner.run_docker(["inspect", CONTAINER_NAME], timeout=5)
            if check.returncode == 0:
                runner.run_docker(["rm", "-f", CONTAINER_NAME], timeout=10)
        else:
            import subprocess
            inspect = subprocess.run(
                ["sudo", "docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME],
                capture_output=True, text=True, timeout=5
            )
            if inspect.stdout.strip() == "true":
                subprocess.run(["sudo", "docker", "stop", "-t", "15", CONTAINER_NAME],
                               capture_output=True, timeout=30)
                time.sleep(1)
            check = subprocess.run(["sudo", "docker", "inspect", CONTAINER_NAME],
                                   capture_output=True, timeout=5)
            if check.returncode == 0:
                subprocess.run(["sudo", "docker", "rm", "-f", CONTAINER_NAME],
                               capture_output=True, timeout=10)
    except Exception:
        pass


def _build_test_command(original_cmd: str) -> str:
    cmd = original_cmd.strip()
    cmd = cmd.replace("&quot;", '"').replace("&amp;", "&")
    cmd = re.sub(r"(sudo\s+)?docker\s+run\b", "sudo docker run", cmd)
    cmd = re.sub(r"(?<= )--rm(?=\s|$|\\)", "", cmd)
    cmd = re.sub(r"(?<= )-it(?=\s|$|\\)", "", cmd)
    cmd = re.sub(r"\s+-d\b", "", cmd)
    cmd = re.sub(r"\s+--restart\s+\S+", "", cmd)
    cmd = re.sub(r"\s+--name\s+\S+", "", cmd)
    cmd = re.sub(r"(sudo docker run)\b", f"\\1 -d --name {CONTAINER_NAME}", cmd, count=1)
    cmd = re.sub(r"--port\s+\d+", f"--port {TEST_PORT}", cmd)
    cmd = re.sub(r"--gpu-memory-utilization\s+[\d.]+", "--gpu-memory-utilization 0.25", cmd)
    if "nightly-aarch64" in cmd:
        cmd = re.sub(r'(aoni/vllm/vllm-openai:nightly-aarch64\s+)vllm\s+serve\s+\S+(?=\s|\\|$)', r'\1', cmd)
    return cmd


@router.post("/{slug}/test")
def api_test_model(slug: str, device_id: int | None = Query(None), db: Session = Depends(get_db)):
    """一键测试模型，支持本地和远程设备"""
    m = db.execute(
        select(ModelInfo)
        .options(joinedload(ModelInfo.device_configs).joinedload(ModelDeviceConfig.device))
        .where(ModelInfo.slug == slug)
    ).unique().scalar_one_or_none()
    if not m:
        raise HTTPException(404, f"模型 '{slug}' 不存在")

    # 确定设备
    device = None
    target_device_config = None
    docker_cmd = m.docker_command or ""

    if device_id:
        device = db.get(Device, device_id)
        if not device:
            raise HTTPException(404, "设备不存在")
        target_device_config = next((dc for dc in m.device_configs if dc.device_id == device_id), None)
        if target_device_config and target_device_config.docker_command:
            docker_cmd = target_device_config.docker_command
        else:
            if not target_device_config:
                target_device_config = ModelDeviceConfig(
                    model_id=m.id, device_id=device_id,
                    docker_command=docker_cmd, status="NEW",
                )
                db.add(target_device_config)
                db.commit()
                db.refresh(target_device_config)

    if not docker_cmd:
        raise HTTPException(400, "模型未配置 Docker 命令")

    runner = RemoteRunner(device)
    host_label = runner.host_label
    api_host = runner.api_host

    # 1. 清理旧容器
    _stop_test_container(runner)
    if not runner.is_remote:
        try:
            import subprocess
            subprocess.run(["sudo", "sysctl", "-w", "vm.drop_caches=3"], capture_output=True, timeout=5)
        except Exception:
            pass
    time.sleep(2)

    # 2. 启动容器
    test_cmd = _build_test_command(docker_cmd)
    res = runner.run_shell(test_cmd, timeout=300)
    if res.returncode != 0:
        error_msg = f"容器启动失败 [{host_label}]: {res.stderr[:200]}"
        _update_test_result(m, target_device_config, "FAIL", error_msg, db)
        return {"status": "FAIL", "detail": error_msg, "docker_command": test_cmd}

    container_id = res.stdout.strip()[:12]

    # 3. 等待 vLLM（通过 runner 检查远程容器状态）
    import requests
    url = f"http://{api_host}:{TEST_PORT}/v1/models"
    deadline = time.time() + MAX_VLLM_WAIT
    vllm_ready = False
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                vllm_ready = True
                break
        except Exception:
            pass

        # 每 30 秒检查远程容器状态
        if attempt % 6 == 0:
            try:
                check = runner.run_docker(
                    ["inspect", "-f", "{{.State.Status}}", CONTAINER_NAME], timeout=5)
                status = check.stdout.strip()
                if status not in ("running", "created"):
                    _stop_test_container(runner)
                    logs = runner.run_docker(["logs", "--tail", "10", CONTAINER_NAME], timeout=10)
                    err_detail = f"容器异常退出 [{host_label}] (状态: {status})"
                    if logs.stdout or logs.stderr:
                        err_detail += f" 日志: {(logs.stdout + logs.stderr)[:200]}"
                    _update_test_result(m, target_device_config, "FAIL", err_detail, db)
                    return {"status": "FAIL", "detail": err_detail, "docker_command": test_cmd, "container_id": container_id}
            except Exception:
                pass
        time.sleep(5)

    if not vllm_ready:
        _stop_test_container(runner)
        _update_test_result(m, target_device_config, "FAIL", f"vLLM 启动超时 [{host_label}] ({MAX_VLLM_WAIT}s)", db)
        return {"status": "FAIL", "detail": f"vLLM 启动超时 ({MAX_VLLM_WAIT}s)", "docker_command": test_cmd, "container_id": container_id}

    # 4. 提取 MODEL_NAME
    model_name_match = re.search(r"-e MODEL_NAME=([^ \n\\]+)", docker_cmd)
    model_name = model_name_match.group(1).strip() if model_name_match else m.name

    # 5. 对话测试
    chat_url = f"http://{api_host}:{TEST_PORT}/v1/chat/completions"
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "你好，请用一句话介绍你自己。"}],
        "max_tokens": 100, "temperature": 0,
    }
    try:
        r = requests.post(chat_url, json=payload, timeout=120)
        if r.status_code == 200:
            data = r.json()
            reply = data["choices"][0]["message"].get("content", "").strip()
            reasoning = data["choices"][0]["message"].get("reasoning", "")
            _update_test_result(m, target_device_config, "PASS", f"PASS [{host_label}]: {reply[:200]}", db)
            _stop_test_container(runner)
            return {
                "status": "PASS", "reply": reply,
                "reasoning": reasoning[:200] if reasoning else "",
                "model": model_name, "docker_command": test_cmd, "container_id": container_id,
                "device_name": device.name if device else "本机",
            }
        else:
            _stop_test_container(runner)
            error_msg = f"对话请求失败 [{host_label}] HTTP {r.status_code}: {r.text[:200]}"
            _update_test_result(m, target_device_config, "FAIL", error_msg, db)
            return {"status": "FAIL", "detail": error_msg}
    except requests.exceptions.Timeout:
        _stop_test_container(runner)
        _update_test_result(m, target_device_config, "FAIL", f"对话请求超时 [{host_label}]", db)
        return {"status": "FAIL", "detail": "对话请求超时"}
    except Exception as e:
        _stop_test_container(runner)
        _update_test_result(m, target_device_config, "FAIL", f"对话异常 [{host_label}]: {str(e)[:200]}", db)
        return {"status": "FAIL", "detail": str(e)[:200]}


def _update_test_result(model: ModelInfo, device_config: ModelDeviceConfig | None,
                        status: str, detail: str, db: Session):
    """更新测试结果：同时更新设备配置（如有）和模型默认状态"""
    if device_config:
        device_config.status = status
        device_config.result_detail = detail
        device_config.tested_at = datetime.utcnow()
    else:
        model.status = status
        model.result_detail = detail
    db.commit()
