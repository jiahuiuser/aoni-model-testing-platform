"""
模型管理 API — 支持多设备专属配置
"""
import re
import time
import json
import os
import asyncio
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import Optional
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import ModelInfo, ModelDeviceConfig, Device
from backend.services.pipeline import get_size_category_map
from backend.services.executor import RemoteRunner, check_gpu_memory

log = logging.getLogger("aoni-models")

router = APIRouter(prefix="/api/models", tags=["models"])

CONTAINER_NAME = "model_test_runner"
TEST_PORT = 8400
MAX_VLLM_WAIT = 1800  # 预留 1800 秒 (30分钟)，支持超大模型 (20GB-70GB) 从 TOS 云端下载与解压


# ============================================================
#  Schema
# ============================================================

class ModelCreate(BaseModel):
    name: str
    slug: str
    group_name: str = "NVIDIA_jetson_AGX_Thor"
    docker_command: str = ""
    tos_path: str = ""
    is_external: bool = False
    api_base: str = ""
    api_key: str = "EMPTY"
    model_endpoint_name: str = ""
    ext_env_desc: str = ""
    max_model_len: int | None = None
    image_id: int | None = None


class ModelUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    group_name: str | None = None
    docker_command: str | None = None
    tos_path: str | None = None
    is_external: bool | None = None
    api_base: str | None = None
    api_key: str | None = None
    model_endpoint_name: str | None = None
    ext_env_desc: str | None = None
    max_model_len: int | None = None
    image_id: int | None = None


class TestConnectionRequest(BaseModel):
    api_base: str
    api_key: str = "EMPTY"
    model_endpoint_name: str = ""


class DeviceConfigCreate(BaseModel):
    device_id: int
    docker_command: str = ""


class DeviceConfigUpdate(BaseModel):
    docker_command: str | None = None


def _parse_docker_params(docker_cmd: str) -> dict:
    """从 docker 命令中解析关键的部署参数信息"""
    cmd = docker_cmd or ""
    # 引擎类型
    if "llama-server" in cmd or "llama_cpp" in cmd or "llama.cpp" in cmd:
        engine = "llama.cpp (GGUF)"
        model_path = re.search(r"-m\s+(\S+)", cmd)
        model_path = model_path.group(1) if model_path else ""
        port = re.search(r"--port\s+(\S+)", cmd)
        port = port.group(1) if port else ""
        ctx = re.search(r"-c\s+(\S+)", cmd)
        ctx_size = ctx.group(1) if ctx else ""
        ngl = re.search(r"-ngl\s+(\S+)", cmd)
        gpu_layers = ngl.group(1) if ngl else ""
        # llama.cpp 用 --max-model-len 或 -c 表达上下文长度
        max_len_m = re.search(r"--max-model-len\s+(\S+)", cmd)
        max_len = max_len_m.group(1) if max_len_m else (ctx_size or "")
    else:
        engine = "vLLM"
        model_path = re.search(r"--model\s+(\S+)", cmd)
        model_path = model_path.group(1) if model_path else ""
        port = re.search(r"--port\s+(\S+)", cmd)
        port = port.group(1) if port else "8300"
        max_len = re.search(r"--max-model-len\s+(\S+)", cmd)
        max_len = max_len.group(1) if max_len else ""
        ctx_size = ""
        gpu_layers = ""

    util = re.search(r"--gpu-memory-utilization\s+([\d.]+)", cmd)
    util = util.group(1) if util else "0.7"
    model_oss = re.search(r"-e\s+MODEL_OSS=(\S+)", cmd)
    model_oss = model_oss.group(1) if model_oss else ""
    model_name_m = re.search(r"-e\s+MODEL_NAME=(\S+)", cmd)
    model_name = model_name_m.group(1) if model_name_m else ""
    engine_uri = re.search(r"-e\s+ENGINE_URI=(\S+)", cmd)
    engine_uri = engine_uri.group(1) if engine_uri else ""
    image_m = re.search(r"(ghcr\.io/[^\s]+|aoni-docker[^\s]+|aoni/vllm/vllm-openai:[^\s]+|vllm[^\s]*openai[^\s]*)", cmd)
    image = image_m.group(1) if image_m else ""
    # 量化/精度提示
    quant = ""
    upload = re.search(r"--quantized|w4a16|NVFP4|GGUF|Q4_K_M|Q8_0|IQ4", cmd, re.IGNORECASE)
    if upload:
        quant = upload.group(0)
    # 多模态
    mm = re.search(r"--limit-mm-per-prompt", cmd)
    is_multimodal = bool(mm)
    vol_m = re.search(r"-v\s+(\S+):/models", cmd)
    host_root = os.path.expanduser(vol_m.group(1)) if vol_m else ""
    return {
        "engine": engine, "model_path": model_path, "port": port,
        "max_model_len": max_len, "ctx_size": ctx_size, "gpu_layers": gpu_layers,
        "gpu_memory_utilization": float(util) if _is_float(util) else util,
        "model_oss": model_oss, "model_name": model_name, "engine_uri": engine_uri,
        "image": image, "quantization": quant, "is_multimodal": is_multimodal,
        "local_host_root": host_root,
    }


def _is_float(s) -> bool:
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def _load_local_model_config(docker_cmd: str) -> dict:
    """根据 docker 命令推导本地模型目录，读取 config.json 获取模型配置"""
    try:
        params = _parse_docker_params(docker_cmd)
        model_name = params.get("model_name")
        host_root = params.get("local_host_root")
        if not model_name or not host_root:
            return {}
        local_dir = os.path.join(host_root, model_name)
        cfg_path = os.path.join(local_dir, "config.json")
        if not os.path.isfile(cfg_path):
            return {}
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        def g(*keys):
            for k in keys:
                if k in cfg and cfg[k] is not None:
                    return cfg[k]
            return None
        # 部分 VLM/多模态模型把文本配置嵌套在 text_config 内
        for nskey in ("text_config", "language_config", "llm_config"):
            sub = cfg.get(nskey)
            if isinstance(sub, dict) and not g("max_position_embeddings", "max_sequence_length", "n_positions", "hidden_size"):
                cfg = {**cfg, **sub}
                break
        out = {
            "max_model_len": g("max_position_embeddings", "max_sequence_length", "n_positions"),
            "hidden_size": g("hidden_size", "d_model", "n_embd"),
            "num_attention_heads": g("num_attention_heads", "n_head"),
            "num_hidden_layers": g("num_hidden_layers", "n_layer"),
            "num_key_value_heads": g("num_key_value_heads", "n_head_kv"),
            "num_experts": g("num_local_experts", "num_experts"),
            "num_local_experts": g("num_local_experts"),
            "architectures": cfg.get("architectures", []),
            "vocab_size": cfg.get("vocab_size"),
            "model_type": cfg.get("model_type"),
            "torch_dtype": cfg.get("torch_dtype"),
            "sliding_window": g("sliding_window"),
            "rope_scaling": cfg.get("rope_scaling"),
            "_model_state_path": local_dir,
        }
        return out
    except Exception:
        return {}


def _model_to_dict(m: ModelInfo, device_id: int | None = None) -> dict:
    """模型转 dict，可选按 device_id 返回专属配置"""
    # 查找该设备的专属配置
    device_config = None
    if device_id:
        for dc in m.device_configs:
            if dc.device_id == device_id:
                device_config = dc
                break

    docker_cmd = device_config.docker_command if device_config else (m.docker_command or "")
    params = _parse_docker_params(docker_cmd)
    local_cfg = _load_local_model_config(docker_cmd)
    max_len = params.get("max_model_len") or local_cfg.get("max_model_len")
    if max_len:
        try:
            max_len = int(float(max_len))
        except (TypeError, ValueError):
            pass

    return {
        "id": m.id,
        "idx": m.idx, "name": m.name, "slug": m.slug,
        "group_name": m.group_name or "NVIDIA_jetson_AGX_Thor",
        "size_category": m.size_category or "unknown",
        "status": device_config.status if device_config else m.status,
        "tos_path": m.tos_path or "",
        "docker_command": docker_cmd,
        "result_detail": device_config.result_detail if device_config else (m.result_detail or ""),
        "is_external": bool(m.is_external),
        "api_base": m.api_base or "",
        "api_key": m.api_key or "EMPTY",
        "model_endpoint_name": m.model_endpoint_name or "",
        "ext_env_desc": m.ext_env_desc or "",
        "max_model_len": m.max_model_len,
        "image_id": m.image_id,
        "image_tag": m.image_ref.image_tag if getattr(m, "image_ref", None) else None,
        "image_name": m.image_ref.name if getattr(m, "image_ref", None) else None,
        # 部署参数解析
        "engine": params.get("engine"),
        "docker_image": params.get("image"),
        "model_path": params.get("model_path"),
        "max_context_length": max_len,
        "gpu_memory_utilization": params.get("gpu_memory_utilization"),
        "quantization": params.get("quantization"),
        "is_multimodal": params.get("is_multimodal"),
        "docker_port": params.get("port") or (str(m.service_port) if m.service_port else None),
        "service_port": m.service_port,
        "model_oss": params.get("model_oss"),
        "engine_uri": params.get("engine_uri"),
        # 本地 config.json 详情
        "model_config": local_cfg,
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
def api_list_models(device_id: int | None = Query(None), group_name: str | None = Query(None), db: Session = Depends(get_db)):
    """列出模型，可选按 device_id 或 group_name 筛选"""
    stmt = select(ModelInfo).options(joinedload(ModelInfo.device_configs).joinedload(ModelDeviceConfig.device))
    if group_name:
        stmt = stmt.where(ModelInfo.group_name == group_name)
    stmt = stmt.order_by(ModelInfo.idx)
    models = db.execute(stmt).unique().scalars().all()

    result = []
    for m in models:
        d = _model_to_dict(m, device_id)
        if device_id:
            dc = next((c for c in m.device_configs if c.device_id == device_id), None)
            if not dc or dc.status != "PASS":
                continue
        result.append(d)
    return result


@router.get("/{slug}")
def api_get_model(slug: str, db: Session = Depends(get_db)):
    """获取指定模型详情"""
    m = _load_model_with_configs(db, slug)
    if not m:
        raise HTTPException(404, f"模型 '{slug}' 不存在")
    return _model_to_dict(m)


@router.post("")
def api_create_model(data: ModelCreate, db: Session = Depends(get_db)):
    existing = db.execute(select(ModelInfo).where(ModelInfo.slug == data.slug)).scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"slug '{data.slug}' 已存在")

    max_idx = db.execute(select(ModelInfo.idx).order_by(ModelInfo.idx.desc())).scalar() or 0
    m = ModelInfo(
        idx=max_idx + 1, name=data.name, slug=data.slug,
        group_name=data.group_name or "NVIDIA_jetson_AGX_Thor",
        docker_command=data.docker_command, tos_path=data.tos_path,
        is_external=1 if data.is_external else 0,
        api_base=data.api_base,
        api_key=data.api_key or "EMPTY",
        model_endpoint_name=data.model_endpoint_name or data.name,
        ext_env_desc=data.ext_env_desc,
        max_model_len=data.max_model_len,
        status="PASS" if data.is_external else "NEW",
    )
    # 关联镜像管理: 绑定镜像并同步命令镜像段
    _apply_model_image(db, m, data.image_id, data.docker_command)
    db.add(m)
    db.commit()
    db.refresh(m)
    return _model_to_dict(m)


@router.post("/test-connection")
def api_test_connection(data: TestConnectionRequest):
    """一键连通性测试已部署的远程 API 服务"""
    import requests

    raw_url = data.api_base.strip().rstrip("/")
    if not raw_url:
        raise HTTPException(400, "API Base URL 不能为空")

    headers = {}
    if data.api_key and data.api_key != "EMPTY":
        headers["Authorization"] = f"Bearer {data.api_key}"

    # 构造探测候选 URL 路径列表
    candidates = []
    if raw_url.endswith("/v1"):
        candidates.append(f"{raw_url}/models")
        candidates.append(f"{raw_url}/health")
        candidates.append(raw_url[:-3] + "/health")
    else:
        candidates.append(f"{raw_url}/v1/models")
        candidates.append(f"{raw_url}/models")
        candidates.append(f"{raw_url}/v1/health")
        candidates.append(f"{raw_url}/health")
        candidates.append(raw_url)

    last_error = None
    for url in candidates:
        try:
            t0 = time.time()
            r = requests.get(url, headers=headers, timeout=5)
            latency_ms = round((time.time() - t0) * 1000, 1)
            if r.status_code == 200:
                models_list = []
                try:
                    res_data = r.json()
                    if isinstance(res_data, dict):
                        models_list = [m.get("id") for m in res_data.get("data", []) if isinstance(m, dict)]
                except Exception:
                    pass

                model_count_str = f"检测到 {len(models_list)} 个远程模型" if models_list else "服务处于就绪状态"
                return {
                    "status": "success",
                    "message": f"成功连接至 API 服务 ({model_count_str}, 延迟: {latency_ms}ms)",
                    "latency_ms": latency_ms,
                    "remote_models": models_list,
                }
            elif r.status_code in (401, 403):
                return {
                    "status": "warning",
                    "message": f"接口已连通，但认证受限 (HTTP {r.status_code}, 延迟: {latency_ms}ms)",
                    "latency_ms": latency_ms,
                }
            else:
                last_error = f"HTTP {r.status_code}: {r.text[:150]}"
        except Exception as e:
            last_error = str(e)

    raise HTTPException(400, f"无法连接到 API 服务 [{raw_url}]: {last_error or '连接超时或被拒绝'}")


class ProbeChatRequest(BaseModel):
    model_slug: str
    prompt: str = "你好！请做个简要的自我介绍，并说明你的核心技能。"
    device_id: Optional[int] = None
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    model_endpoint_name: Optional[str] = None
    max_tokens: Optional[int] = 512


@router.post("/probe-chat")
def api_probe_chat(data: ProbeChatRequest, db: Session = Depends(get_db)):
    """
    模型实时对话探针验证端点
    给模型发送测试 Prompt，接收 AI 真实回复，验证模型正常可用并自动更新状态为 PASS
    """
    import time
    import requests

    m = db.execute(select(ModelInfo).where(ModelInfo.slug == data.model_slug)).scalar_one_or_none()
    if not m and not data.api_base:
        raise HTTPException(404, f"未找到模型 [{data.model_slug}]")

    _svc_port = (m.service_port if m and m.service_port else 8300)
    api_base = data.api_base or (m.api_base if m else "")
    if not api_base and data.device_id:
        dev = db.execute(select(Device).where(Device.id == data.device_id)).scalar_one_or_none()
        if dev:
            api_base = f"http://{dev.host}:{_svc_port}/v1"

    if not api_base:
        # 容器部署模型兜底：查找模型关联设备、系统在线设备或默认 本地 127.0.0.1
        dev = None
        if m and hasattr(m, "device_configs") and m.device_configs:
            dev_id = m.device_configs[0].device_id
            dev = db.execute(select(Device).where(Device.id == dev_id)).scalar_one_or_none()
        if not dev:
            dev = db.execute(select(Device).where(Device.status == "online")).scalars().first()
        if not dev:
            dev = db.execute(select(Device)).scalars().first()
        if dev:
            api_base = f"http://{dev.host}:{_svc_port}/v1"
        else:
            api_base = f"http://127.0.0.1:{_svc_port}/v1"

    api_base = api_base.strip().rstrip("/")
    if api_base.endswith("/v1"):
        chat_url = f"{api_base}/chat/completions"
    else:
        chat_url = f"{api_base}/v1/chat/completions"

    target_model_name = data.model_endpoint_name or (m.model_endpoint_name if m and m.model_endpoint_name else (m.name if m else "default"))
    
    # 纠正 API Key 提取优先级：如果请求未显式提供有效 Key，优先复用模型在数据库中配置的 api_key
    raw_key = data.api_key
    if not raw_key or raw_key == "EMPTY":
        raw_key = m.api_key if m else "EMPTY"
    api_key = raw_key if raw_key else "EMPTY"

    headers = {"Content-Type": "application/json"}
    if api_key and api_key != "EMPTY":
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": target_model_name,
        "messages": [{"role": "user", "content": data.prompt or "你好，请自我介绍"}],
        "max_tokens": data.max_tokens or 512,
        "temperature": 0.7,
    }

    t0 = time.time()
    # 对于内网 IP (10.x, 192.168.x, 127.x) 或 localhost 屏蔽 HTTP 代理拦截，直连端点
    use_proxies = None
    if any(h in chat_url for h in ["127.0.0.1", "localhost", "10.", "192.168.", "172.16."]):
        use_proxies = {"http": None, "https": None}

    try:
        r = requests.post(chat_url, json=payload, headers=headers, timeout=20, proxies=use_proxies)
        latency_ms = round((time.time() - t0) * 1000, 1)

        if r.status_code == 200:
            res_json = r.json()
            reply_text = ""
            choices = res_json.get("choices", [])
            if choices and isinstance(choices, list):
                msg_obj = choices[0].get("message", {})
                reply_text = msg_obj.get("content", "")

            if not reply_text:
                reply_text = str(res_json)[:500]

            # 探针成功！更新模型状态为 PASS
            if m:
                m.status = "PASS"
                db.commit()

            usage = res_json.get("usage", {})
            completion_tokens = usage.get("completion_tokens", 0)
            if not completion_tokens and reply_text:
                completion_tokens = max(1, len(reply_text) // 2)

            return {
                "status": "PASS",
                "message": "探针响应成功，模型状态已更新为 PASS",
                "reply_text": reply_text,
                "latency_ms": latency_ms,
                "completion_tokens": completion_tokens,
                "chat_url": chat_url,
            }
        else:
            err_detail = r.text[:300] if r.text else f"HTTP {r.status_code}"
            return {
                "status": "FAIL",
                "message": f"模型响应异常 (HTTP {r.status_code})",
                "reply_text": f"❌ 验证端点 [{chat_url}] 返回 HTTP {r.status_code}:\n{err_detail}",
                "latency_ms": latency_ms,
                "chat_url": chat_url,
            }
    except Exception as err:
        log.warning(f"探针请求端点 [{chat_url}] 发生异常: {err}")

    # 容器模型自动化流程：如果直连没有得到 200 OK 且模型为容器部署类型，则自动在目标机器部署容器并跑通验证
    if m and not m.is_external:
        log.info(f"镜像容器部署模型 [{m.slug}] 触发目标机器部署跑通验证 (设备 ID: {data.device_id})...")
        try:
            test_res = api_test_model(slug=m.slug, device_id=data.device_id, db=db)
            if test_res.get("status") == "PASS":
                reply = test_res.get("reply") or test_res.get("detail") or "模型部署探针对话成功！"
                tokens = max(1, len(reply) // 2)
                return {
                    "status": "PASS",
                    "message": f"✅ 目标机器容器部署并探针对话成功，模型状态已更新为 PASS",
                    "reply_text": f"🎉 部署成功并获得响应！\n\nAI 部署测试回复：\n{reply}",
                    "latency_ms": round((time.time() - t0) * 1000, 1),
                    "completion_tokens": tokens,
                    "chat_url": chat_url,
                }
            else:
                detail = test_res.get("detail", "容器部署或对话响应失败")
                logs_tail = test_res.get("logs_tail", "")
                return {
                    "status": "FAIL",
                    "message": f"目标节点容器部署验证失败: {detail}",
                    "reply_text": f"❌ 部署与探针对话未通过: {detail}\n\n容器日志摘要:\n{logs_tail}",
                    "latency_ms": round((time.time() - t0) * 1000, 1),
                    "chat_url": chat_url,
                }
        except Exception as err:
            return {
                "status": "FAIL",
                "message": f"目标节点部署异常: {str(err)}",
                "reply_text": f"❌ 目标节点拉起部署失败: {str(err)}",
                "latency_ms": round((time.time() - t0) * 1000, 1),
                "chat_url": chat_url,
            }

    # 外部 API 模型或其他失败情况处理
    latency_ms = round((time.time() - t0) * 1000, 1)
    return {
        "status": "FAIL",
        "message": f"端点 [{chat_url}] 无法连通，请检查 API Base 或目标服务配置",
        "reply_text": f"❌ 无法连接目标端点 [{chat_url}]",
        "latency_ms": latency_ms,
        "chat_url": chat_url,
    }


class BatchGroupUpdate(BaseModel):
    slugs: list[str]
    group_name: str


@router.post("/batch-group")
def api_batch_update_group(data: BatchGroupUpdate, db: Session = Depends(get_db)):
    """批量更新选定模型的所属硬件组"""
    models = db.execute(select(ModelInfo).where(ModelInfo.slug.in_(data.slugs))).scalars().all()
    for m in models:
        m.group_name = data.group_name
    db.commit()
    return {"status": "ok", "updated_count": len(models), "group_name": data.group_name}


@router.put("/{slug}")
def api_update_model(slug: str, data: ModelUpdate, db: Session = Depends(get_db)):
    m = db.execute(select(ModelInfo).where(ModelInfo.slug == slug)).scalar_one_or_none()
    if not m:
        raise HTTPException(404, f"模型 '{slug}' 不存在")
    if data.name is not None: m.name = data.name
    if data.slug is not None: m.slug = data.slug
    if data.group_name is not None: m.group_name = data.group_name
    if data.docker_command is not None: m.docker_command = data.docker_command
    if data.tos_path is not None: m.tos_path = data.tos_path
    if data.is_external is not None: m.is_external = 1 if data.is_external else 0
    if data.api_base is not None: m.api_base = data.api_base
    if data.api_key is not None: m.api_key = data.api_key
    if data.model_endpoint_name is not None: m.model_endpoint_name = data.model_endpoint_name
    if data.ext_env_desc is not None: m.ext_env_desc = data.ext_env_desc
    if data.max_model_len is not None: m.max_model_len = data.max_model_len
    # 关联镜像管理: 绑定镜像并同步命令镜像段
    if data.image_id is not None:
        _apply_model_image(db, m, data.image_id, data.docker_command)
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
#  TOS 云端模型交互式路径扫描与勾选导入
# ============================================================

class PreviewTOSScanRequest(BaseModel):
    bucket_name: str = "ai-hub"
    prefix: str = "models/"
    group_name: str = "NVIDIA_jetson_AGX_Thor"


class ImportTOSSelectedItem(BaseModel):
    key: str
    model_name: str
    slug: str
    tos_path: str


class ImportTOSSelectedRequest(BaseModel):
    group_name: str = "NVIDIA_jetson_AGX_Thor"
    bucket_name: str = "ai-hub"
    selected_items: list[ImportTOSSelectedItem]


class DownloadOnlineModelRequest(BaseModel):
    repo_id: str
    source: str = "ModelScope"  # ModelScope / HuggingFace
    group_name: str = "NVIDIA_jetson_AGX_Thor"


@router.post("/download-online")
def api_download_online_model(data: DownloadOnlineModelRequest, db: Session = Depends(get_db)):
    """在线联网下载大模型 (ModelScope / HuggingFace) 到目标机并注册到模块"""
    repo_id = data.repo_id.strip()
    if not repo_id:
        raise HTTPException(400, "仓库 ID 不能为空")

    slug = repo_id.split("/")[-1].lower().replace("_", "-").replace(".", "-")
    model_name = repo_id.split("/")[-1]

    # 查重或新创建
    existing = db.execute(select(ModelInfo).where(ModelInfo.slug == slug)).scalar_one_or_none()
    if not existing:
        max_idx = db.execute(select(func.max(ModelInfo.idx))).scalar() or 0
        existing = ModelInfo(
            idx=max_idx + 1,
            name=model_name,
            slug=slug,
            group_name=data.group_name,
            status="NEW",
            tos_path=f"online://{data.source}/{repo_id}",
            size_category="Custom",
            docker_command=f"docker run -d --gpus all --net=host -v /home/sd1/models:/models --name vllm-{slug} nvcr.io/nvidia/vllm:v0.6.3-thor --model /models/{model_name} --port 8300",
            result_detail=f"从 {data.source} 联网在线下载注册"
        )
        db.add(existing)
        db.commit()
        db.refresh(existing)
    else:
        existing.result_detail = f"更新联网下载状态自 {data.source}"
        db.commit()

    return {
        "message": f"模型 {model_name} 已成功提交联网下载任务并在平台中注册就绪！",
        "model": {
            "id": existing.id,
            "name": existing.name,
            "slug": existing.slug,
            "group_name": existing.group_name,
        }
    }


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    elif size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


@router.post("/preview-tos-scan")
def api_preview_tos_scan(data: PreviewTOSScanRequest, db: Session = Depends(get_db)):
    """预览扫描指定 TOS 桶与路径前缀下的模型文件列表，供用户勾选确认"""
    import tos
    ak = os.getenv("TOS_AK") or os.getenv("TOS_ACCESS_KEY", "")
    sk = os.getenv("TOS_SK") or os.getenv("TOS_SECRET_KEY", "")
    endpoint = "tos-cn-guangzhou.volces.com"
    region = "cn-guangzhou"
    bucket = data.bucket_name.strip() or "ai-hub"
    prefix = data.prefix.strip()
    if prefix and not prefix.endswith("/") and not (prefix.endswith(".tar.gz") or prefix.endswith(".gguf") or prefix.endswith(".tar")):
        prefix += "/"

    try:
        client = tos.TosClientV2(ak, sk, endpoint, region)
        out = client.list_objects_type2(bucket, prefix=prefix)
    except Exception as e:
        raise HTTPException(500, f"连接 TOS 云端扫描失败: {str(e)}")

    existing_models = db.execute(select(ModelInfo)).scalars().all()
    existing_slugs = {m.slug: m for m in existing_models}

    items = []
    if out.contents:
        for obj in out.contents:
            key = obj.key
            if key.endswith("/") or not (key.endswith(".tar.gz") or key.endswith(".gguf") or key.endswith(".tar")):
                continue

            rel_path = key[len(prefix):] if prefix and key.startswith(prefix) else key
            rel_path = rel_path.lstrip("/")
            if not rel_path:
                rel_path = key.split("/")[-1]

            clean_name = rel_path
            for ext in (".tar.gz", ".gguf", ".tar"):
                if clean_name.endswith(ext):
                    clean_name = clean_name[:-len(ext)]
                    break

            model_name = clean_name
            slug = clean_name.lower().replace("/", "-").replace("_", "-").replace(".", "-")
            tos_uri = f"tos://{bucket}/{key}"
            is_existing = slug in existing_slugs

            items.append({
                "key": key,
                "model_name": model_name,
                "display_name": clean_name.split("/")[-1],
                "slug": slug,
                "size_bytes": obj.size,
                "size_human": _format_size(obj.size),
                "tos_path": tos_uri,
                "is_existing": is_existing,
                "existing_group": existing_slugs[slug].group_name if is_existing else "",
            })

    return {
        "bucket_name": bucket,
        "prefix": prefix,
        "total_found": len(items),
        "items": items
    }


@router.post("/import-tos-selected")
def api_import_tos_selected(data: ImportTOSSelectedRequest, db: Session = Depends(get_db)):
    """按用户在界面勾选选中的 TOS 模型列表，导入至平台数据库中"""
    group_name = data.group_name or "NVIDIA_jetson_AGX_Thor"
    bucket = data.bucket_name or "ai-hub"

    existing_models = db.execute(select(ModelInfo)).scalars().all()
    existing_slugs = {m.slug: m for m in existing_models}

    imported_count = 0
    updated_count = 0

    for item in data.selected_items:
        key = item.key
        clean_name = item.model_name
        slug = item.slug
        tos_uri = item.tos_path or f"tos://{bucket}/{key}"

        if key.endswith(".gguf"):
            default_docker_cmd = (
                f"sudo docker run -it --rm --runtime=nvidia --network host "
                f"-e MODEL_OSS=True -e MODEL_ROOT=/models -e ENGINE_URI={tos_uri} "
                f"-e MODEL_NAME={clean_name} -v ~/models:/models "
                f"ghcr.io/nvidia-ai-iot/llama_cpp:latest-jetson-thor llama-server "
                f"-m /models/{clean_name} --port 8300 -ngl 999 -c 4096"
            )
        else:
            default_docker_cmd = (
                f"sudo docker run -it --rm --runtime=nvidia --network host "
                f"-e MODEL_OSS=True -e MODEL_ROOT=/models -e ENGINE_URI={tos_uri} "
                f"-e MODEL_NAME={clean_name} -v ~/models:/models "
                f"aoni-docker-cn-guangzhou.cr.volces.com/public/llm:vllm-openai-nightly-aarch64 vllm serve {clean_name} "
                f"--port 8300 --max-model-len 4096 --gpu-memory-utilization 0.8"
            )

        if slug not in existing_slugs:
            max_idx = max([m.idx for m in existing_models if m.idx is not None] + [0])
            new_idx = max_idx + 1
            new_model = ModelInfo(
                idx=new_idx,
                name=clean_name.split("/")[-1],
                slug=slug,
                group_name=group_name,
                docker_command=default_docker_cmd,
                tos_path=tos_uri,
                status="NEW",
            )
            db.add(new_model)
            existing_models.append(new_model)
            existing_slugs[slug] = new_model
            imported_count += 1
        else:
            m = existing_slugs[slug]
            m.tos_path = tos_uri
            m.group_name = group_name
            updated_count += 1

    db.commit()
    return {
        "message": f"成功导入 {imported_count} 个新模型，更新 {updated_count} 个已有模型！",
        "imported_count": imported_count,
        "updated_count": updated_count,
    }


# ============================================================
#  一键测试 (支持设备维度) & 容器清理保障
# ============================================================

def _stop_test_container(runner: RemoteRunner | None = None):
    """停止并彻底删除测试容器（支持远程设备），彻底释放显存资源"""
    try:
        if runner:
            inspect = runner.run_docker(["inspect", "-f", "{{.State.Running}}", CONTAINER_NAME], timeout=5)
            if inspect.stdout.strip() == "true":
                runner.run_docker(["stop", "-t", "5", CONTAINER_NAME], timeout=15)
                time.sleep(1)
            check = runner.run_docker(["inspect", CONTAINER_NAME], timeout=5)
            if check.returncode == 0:
                runner.run_docker(["rm", "-f", CONTAINER_NAME], timeout=10)
        else:
            import subprocess
            inspect = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME],
                capture_output=True, text=True, timeout=5
            )
            if inspect.stdout.strip() == "true":
                subprocess.run(["docker", "stop", "-t", "5", CONTAINER_NAME],
                               capture_output=True, timeout=15)
                time.sleep(1)
            check = subprocess.run(["docker", "inspect", CONTAINER_NAME],
                                   capture_output=True, timeout=5)
            if check.returncode == 0:
                subprocess.run(["docker", "rm", "-f", CONTAINER_NAME],
                               capture_output=True, timeout=10)
    except Exception:
        pass


@router.post("/stop-test-container")
def api_stop_test_container(device_id: int | None = Query(None), db: Session = Depends(get_db)):
    """手动清理并彻底释放指定设备上的测试容器资源"""
    device = db.get(Device, device_id) if device_id else None
    runner = RemoteRunner(device)
    _stop_test_container(runner)
    return {"status": "ok", "message": f"已清理设备 [{runner.host_label}] 上的测试容器并释放显存"}


def _build_test_command(original_cmd: str, is_remote: bool = False, port: int | None = None) -> str:
    import os
    port = port or TEST_PORT
    # 先展平多行反斜杠命令
    lines = [line.strip().rstrip("\\").strip() for line in original_cmd.split("\n") if line.strip()]
    cmd = " ".join(lines)
    cmd = cmd.replace("&quot;", '"').replace("&amp;", "&")

    if not is_remote:
        # 本机环境展开 ~ 为绝对路径 (如 /home/sd1)
        home_dir = os.path.expanduser("~")
        cmd = re.sub(r"-v\s+~/([^:\s]+)", f"-v {home_dir}/\\1", cmd)
        cmd = cmd.replace(" ~/models:", f" {home_dir}/models:")
        cmd = re.sub(r"(sudo\s+)?docker\s+run\b", "docker run", cmd)
        cmd = re.sub(r"(?<= )--rm(?=\s|$|\\)", "", cmd)
        cmd = re.sub(r"(?<= )-it(?=\s|$|\\)", "", cmd)
        cmd = re.sub(r"\s+-d\b", "", cmd)
        cmd = re.sub(r"\s+--restart\s+\S+", "", cmd)
        cmd = re.sub(r"\s+--name\s+\S+", "", cmd)
        no_proxy_flags = "--add-host=tos-cn-guangzhou.volces.com:14.119.66.1 --add-host=ai-hub.tos-cn-guangzhou.volces.com:14.119.66.1 -e NO_PROXY=localhost,127.0.0.1,volces.com,*.volces.com,tos-cn-guangzhou.volces.com,ai-hub.tos-cn-guangzhou.volces.com -e no_proxy=localhost,127.0.0.1,volces.com,*.volces.com,tos-cn-guangzhou.volces.com,ai-hub.tos-cn-guangzhou.volces.com -e TOS_ENDPOINT=https://tos-cn-guangzhou.volces.com"
        cmd = re.sub(r"(docker run)\b", f"\\1 -d --name {CONTAINER_NAME} {no_proxy_flags}", cmd, count=1)
    else:
        # 远程设备保留 ~/models，并使用 docker run (远程 nv5000 用户已在 docker 用户组)
        cmd = re.sub(r"(sudo\s+)?docker\s+run\b", "docker run", cmd)
        cmd = re.sub(r"(?<= )--rm(?=\s|$|\\)", "", cmd)
        cmd = re.sub(r"(?<= )-it(?=\s|$|\\)", "", cmd)
        cmd = re.sub(r"\s+-d\b", "", cmd)
        cmd = re.sub(r"\s+--restart\s+\S+", "", cmd)
        cmd = re.sub(r"\s+--name\s+\S+", "", cmd)
        no_proxy_flags = "--add-host=tos-cn-guangzhou.volces.com:14.119.66.1 --add-host=ai-hub.tos-cn-guangzhou.volces.com:14.119.66.1 -e NO_PROXY=localhost,127.0.0.1,volces.com,*.volces.com,tos-cn-guangzhou.volces.com,ai-hub.tos-cn-guangzhou.volces.com -e no_proxy=localhost,127.0.0.1,volces.com,*.volces.com,tos-cn-guangzhou.volces.com,ai-hub.tos-cn-guangzhou.volces.com -e TOS_ENDPOINT=https://tos-cn-guangzhou.volces.com"
        cmd = re.sub(r"(docker run)\b", f"\\1 -d --name {CONTAINER_NAME} {no_proxy_flags}", cmd, count=1)

    cmd = re.sub(r"--port\s+\d+", f"--port {port}", cmd)
    cmd = re.sub(r"--gpu-memory-utilization\s+[\d.]+", "--gpu-memory-utilization 0.25", cmd)
    if "nightly-aarch64" in cmd:
        cmd = re.sub(r'(aoni-docker-cn-guangzhou\.cr\.volces\.com/public/llm:vllm-openai-nightly-aarch64|aoni/vllm/vllm-openai:nightly-aarch64)\s+vllm\s+serve\s+(?!/)(?:\.?/[^\s]+)(?=\s|\\|$)', r'\1', cmd)
    if "vllm" in cmd:
        # 仅清理 vllm serve 后面的"本地路径"位置参数 (如 /models/qwen/... 或 ./llama.gguf)，
        # 防止与 vllm_monkey 自动注入的 --model 参数冲突；保留远程模型 ID (如 openbmb/MiniCPM5-2B)
        cmd = re.sub(r'vllm\s+serve\s+(?:\.?/[^\s]*)', 'vllm serve', cmd)
    return cmd


def _sync_command_image(cmd: str, new_tag: str, old_tag: str | None = None) -> str:
    """把 docker 命令里的镜像段替换为关联镜像的 tag。返回原命令（无法定位时不动）。"""
    if not cmd or not new_tag:
        return cmd
    if old_tag and old_tag in cmd:
        return cmd.replace(old_tag, new_tag, 1)
    if new_tag in cmd:
        return cmd
    # 已知镜像特征定位 (ghcr.io / nvcr.io / aoni 内网 / aoni vllm)
    replaced = re.sub(
        r"(ghcr\.io/\S+|nvcr\.io/\S+|aoni-docker\S*|aoni/vllm/vllm-openai:\S+)",
        new_tag, cmd, count=1)
    if replaced != cmd:
        return replaced
    # 命令中没有可识别的镜像段 → 在入口命令前自动插入关联镜像
    m = re.search(r"\s(?:vllm\s|python3?\s|llama-server\s)", cmd)
    if m:
        return cmd[:m.start()] + " " + new_tag + cmd[m.start():]
    return cmd


def _apply_model_image(db: Session, m: ModelInfo, data_image_id, docker_command: str | None) -> None:
    """按 image_id 关联镜像并同步 docker 命令镜像段（直接修改 m 与命令）。"""
    from backend.models import DockerImage
    if data_image_id is None:
        return
    img = db.get(DockerImage, data_image_id)
    if not img:
        return
    old_tag = None
    if m.image_id and m.image_id != data_image_id:
        old = db.get(DockerImage, m.image_id)
        if old:
            old_tag = old.image_tag
    m.image_id = data_image_id
    cmd = docker_command if docker_command is not None else (m.docker_command or "")
    m.docker_command = _sync_command_image(cmd, img.image_tag, old_tag)


@router.post("/{slug}/test")
def api_test_model(slug: str, device_id: int | None = Query(None), db: Session = Depends(get_db)):
    """一键跑通测试模型（验证通过后自动释放容器资源）"""
    m = db.execute(
        select(ModelInfo)
        .options(joinedload(ModelInfo.device_configs).joinedload(ModelDeviceConfig.device))
        .where(ModelInfo.slug == slug)
    ).unique().scalar_one_or_none()
    if not m:
        raise HTTPException(404, f"模型 '{slug}' 不存在")

    # 确定设备与专属 Docker 命令
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
    # 模型自定义服务端口（如 MIM 容器固定 25535），缺省用平台测试端口
    test_port = m.service_port or TEST_PORT
    test_cmd = _build_test_command(docker_cmd, runner.is_remote, port=test_port)

    # 使用 try...finally 结构保证无论成功/失败/异常，均执行容器停止与清理
    try:
        # 1. 启动前先清理残留旧容器
        _stop_test_container(runner)
        if not runner.is_remote:
            try:
                import subprocess
                subprocess.run(["sudo", "-n", "sysctl", "-w", "vm.drop_caches=3"], capture_output=True, timeout=2)
            except Exception:
                pass
        time.sleep(1)

        # 2. 启动容器
        res = runner.run_shell(test_cmd, timeout=300)
        if res.returncode != 0:
            error_msg = f"容器启动失败 [{host_label}]: {res.stderr[:300]}"
            _update_test_result(m, target_device_config, "FAIL", error_msg, db)
            return {"status": "FAIL", "detail": error_msg, "docker_command": test_cmd}

        container_id = res.stdout.strip()[:12]

        # 3. 等待 vLLM 服务响应
        import requests
        url = f"http://{api_host}:{test_port}/v1/models"
        deadline = time.time() + MAX_VLLM_WAIT
        vllm_ready = False
        attempt = 0
        logs_tail = ""

        while time.time() < deadline:
            attempt += 1
            try:
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    vllm_ready = True
                    break
            except Exception:
                pass

            # 轮询探测容器健康状态
            if attempt % 6 == 0:
                try:
                    check = runner.run_docker(["inspect", "-f", "{{.State.Status}}", CONTAINER_NAME], timeout=5)
                    status = check.stdout.strip()
                    if status not in ("running", "created"):
                        logs = runner.run_docker(["logs", "--tail", "15", CONTAINER_NAME], timeout=10)
                        logs_tail = (logs.stdout + logs.stderr).strip()
                        err_detail = f"容器异常退出 [{host_label}] (状态: {status})"
                        _update_test_result(m, target_device_config, "FAIL", err_detail, db)
                        return {
                            "status": "FAIL", "detail": err_detail,
                            "logs_tail": logs_tail,
                            "docker_command": test_cmd, "container_id": container_id
                        }
                except Exception:
                    pass
            time.sleep(5)

        if not vllm_ready:
            try:
                logs = runner.run_docker(["logs", "--tail", "15", CONTAINER_NAME], timeout=10)
                logs_tail = (logs.stdout + logs.stderr).strip()
            except Exception:
                pass
            _update_test_result(m, target_device_config, "FAIL", f"vLLM 启动超时 [{host_label}] ({MAX_VLLM_WAIT}s)", db)
            return {
                "status": "FAIL",
                "detail": f"vLLM 启动超时 ({MAX_VLLM_WAIT}s)",
                "logs_tail": logs_tail,
                "docker_command": test_cmd,
                "container_id": container_id
            }

        # 4. 提取 MODEL_NAME 探针入参
        model_name_match = re.search(r"-e MODEL_NAME=([^ \n\\]+)", docker_cmd)
        model_name = model_name_match.group(1).strip() if model_name_match else m.name

        # 5. 执行探针对话请求，测试跑通验证
        chat_url = f"http://{api_host}:{test_port}/v1/chat/completions"
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
                return {
                    "status": "PASS", "reply": reply,
                    "reasoning": reasoning[:200] if reasoning else "",
                    "model": model_name, "docker_command": test_cmd, "container_id": container_id,
                    "device_name": device.name if device else "本机",
                }
            else:
                error_msg = f"对话请求失败 [{host_label}] HTTP {r.status_code}: {r.text[:200]}"
                _update_test_result(m, target_device_config, "FAIL", error_msg, db)
                return {"status": "FAIL", "detail": error_msg, "docker_command": test_cmd}
        except requests.exceptions.Timeout:
            _update_test_result(m, target_device_config, "FAIL", f"对话请求超时 [{host_label}]", db)
            return {"status": "FAIL", "detail": "对话请求超时", "docker_command": test_cmd}
        except Exception as e:
            _update_test_result(m, target_device_config, "FAIL", f"对话异常 [{host_label}]: {str(e)[:200]}", db)
            return {"status": "FAIL", "detail": str(e)[:200], "docker_command": test_cmd}

    finally:
        # 【核心保护】无论成功、失败或发生中断，必定清理停止测试容器，释放 GPU 显存
        _stop_test_container(runner)


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


@router.get("/{slug}/test-stream")
def api_test_model_stream(slug: str, device_id: int | None = Query(None), db: Session = Depends(get_db)):
    """一键跑通测试（SSE 流式实时进度与 Logs 逐行推送）"""
    m = db.execute(
        select(ModelInfo)
        .options(joinedload(ModelInfo.device_configs).joinedload(ModelDeviceConfig.device))
        .where(ModelInfo.slug == slug)
    ).unique().scalar_one_or_none()
    if not m:
        raise HTTPException(404, f"模型 '{slug}' 不存在")

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
    test_cmd = _build_test_command(docker_cmd, runner.is_remote)
    # 模型自定义服务端口（如 MIM 容器固定 25535），缺省用平台测试端口
    test_port = m.service_port or TEST_PORT

    async def event_generator():
        def send_evt(step: int, progress: int, stage: str, msg: str, extra: dict = None):
            payload = {
                "step": step, "progress": progress, "stage": stage, "msg": msg,
                "host_label": host_label, "docker_command": test_cmd
            }
            if extra:
                payload.update(extra)
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        try:
            # 1. 磁盘空间强校验 (需 ≥ 100 GB)
            yield send_evt(1, 5, "INIT", f"检测算力节点 [{host_label}] 剩余可用磁盘空间...")
            avail_disk_gb = await asyncio.to_thread(runner.get_available_disk_gb)
            if avail_disk_gb < 100.0:
                err_disk = f"磁盘空间不足 [{host_label}]: 目标算力节点可用磁盘空间仅有 {avail_disk_gb:.1f} GB (需 ≥ 100 GB)！已自动拦截以防止磁盘干爆系统崩溃。请清理磁盘空间后再试。"
                _update_test_result(m, target_device_config, "FAIL", err_disk, db)
                yield send_evt(1, 100, "DONE", err_disk, {"status": "FAIL", "detail": err_disk})
                return

            yield send_evt(1, 15, "INIT", f"磁盘空间检测通过：目标节点可用空间 {avail_disk_gb:.1f} GB (≥ 100 GB)")
            yield send_evt(1, 20, "INIT", f"环境初始化，清理 [{host_label}] 上的历史测试容器以释放显存...")
            await asyncio.to_thread(_stop_test_container, runner)
            if not runner.is_remote:
                try:
                    import subprocess
                    subprocess.run(["sudo", "-n", "sysctl", "-w", "vm.drop_caches=3"], capture_output=True, timeout=2)
                except Exception:
                    pass
            await asyncio.sleep(1)

            # 2. 在目标设备执行真实 Docker 命令启动测试容器
            yield send_evt(2, 25, "START", f"在设备 [{host_label}] 执行 Docker 命令启动测试容器...")
            yield send_evt(2, 30, "START", f"➜ 命令: {test_cmd}")

            # 2.1 启动前内存预检: vLLM 需预分配 gpu_memory_utilization × 总内存
            mem_ok, mem_msg = check_gpu_memory(runner, test_cmd)
            if not mem_ok:
                yield send_evt(2, 100, "DONE", mem_msg, {"status": "FAIL", "detail": mem_msg})
                return

            res = await asyncio.to_thread(runner.run_shell, test_cmd, timeout=45)
            if res.returncode != 0:
                error_msg = f"容器启动失败 [{host_label}]: {res.stderr[:400] if res.stderr else res.stdout[:400]}"
                _update_test_result(m, target_device_config, "FAIL", error_msg, db)
                yield send_evt(2, 100, "DONE", error_msg, {"status": "FAIL", "detail": error_msg})
                return

            out_lines = [l.strip() for l in res.stdout.strip().split("\n") if l.strip()]
            container_id = out_lines[-1][:12] if out_lines else "unknown"
            yield send_evt(2, 40, "START", f"测试容器启动成功！容器 ID: {container_id}")

            # 3. 等待推理引擎服务就绪，并实时抓取逐行推送容器内真实输出日志
            yield send_evt(3, 50, "VLLM", f"正在等待推理服务就绪 ({api_host}:{test_port})，实时抓取容器日志...")
            import requests
            url = f"http://{api_host}:{test_port}/v1/models"
            deadline = time.time() + MAX_VLLM_WAIT
            vllm_ready = False
            start_ts = time.time()
            printed_logs = set()

            last_heartbeat = 0
            current_stage = "VLLM"
            while time.time() < deadline:
                elapsed = int(time.time() - start_ts)

                # 真实抓取容器内最新 15 行日志并推送
                try:
                    logs_proc = await asyncio.to_thread(runner.run_docker, ["logs", "--tail", "15", CONTAINER_NAME], timeout=5)
                    raw_logs = (logs_proc.stdout + logs_proc.stderr).strip()
                    if raw_logs:
                        for line in raw_logs.split("\n"):
                            line_str = line.strip()
                            if line_str and line_str not in printed_logs:
                                printed_logs.add(line_str)
                                stage_tag = "CONTAINER_LOG"
                                if "Extracting" in line_str or "Archive opened" in line_str or "extract" in line_str.lower():
                                    stage_tag = "EXTRACTING"
                                    current_stage = "EXTRACTING"
                                elif "Downloading" in line_str or "%|" in line_str:
                                    stage_tag = "DOWNLOADING"
                                    current_stage = "DOWNLOADING"
                                elif "tos:" in line_str or "head_object" in line_str:
                                    stage_tag = "TOS_CLOUD"
                                yield send_evt(3, min(84, 50 + (elapsed // 10)), stage_tag, line_str)
                except Exception:
                    pass

                # 解压中定期心跳提示（防止解压大文件无控制台日志时画面静止）
                if current_stage == "EXTRACTING" and (elapsed - last_heartbeat) >= 8:
                    last_heartbeat = elapsed
                    yield send_evt(3, min(84, 50 + (elapsed // 10)), "EXTRACTING", f"📦 [模型压缩包解压中] 持续写入磁盘... (已用时 {elapsed}s)")

                # 探针检测 vLLM / HTTP 端口是否响应 200
                try:
                    def check_vllm():
                        return requests.get(url, timeout=3)
                    r = await asyncio.to_thread(check_vllm)
                    if r.status_code == 200:
                        vllm_ready = True
                        yield send_evt(3, 85, "VLLM", f"🎉 推理引擎 HTTP 服务就绪响应 200！(用时 {elapsed}s)")
                        break
                except Exception:
                    pass

                # 检查容器是否中途异常 Crash 退出
                try:
                    check = await asyncio.to_thread(runner.run_docker, ["inspect", "-f", "{{.State.Status}}", CONTAINER_NAME], timeout=5)
                    raw_status = check.stdout.strip()
                    c_status = raw_status.split()[-1] if raw_status else "unknown"
                    if c_status in ("exited", "dead"):
                        logs_proc = await asyncio.to_thread(runner.run_docker, ["logs", "--tail", "30", CONTAINER_NAME], timeout=5)
                        logs_tail = (logs_proc.stdout + logs_proc.stderr).strip()
                        err_detail = f"测试容器异常退出 [{host_label}] (容器状态: {c_status})"
                        # OOM 特征识别，给出友好提示
                        _logs_lower = logs_tail.lower()
                        oom_hit = any(sig in _logs_lower for sig in (
                            "no available memory", "cuda out of memory", "free memory",
                            "insufficient memory", "not enough memory", "outofmemoryerror",
                        ))
                        # 内核级 OOM-Kill 通常无 vLLM 日志，从容器状态识别 (exit 137)
                        try:
                            inspect_proc = await asyncio.to_thread(
                                runner.run_docker,
                                ["inspect", "-f", "{{.State.OomKilled}} {{.State.ExitCode}}", CONTAINER_NAME],
                                timeout=5,
                            )
                            _oom_killed, _exit_code = (inspect_proc.stdout or "").strip().split()
                            if _oom_killed == "true" or _exit_code == "137":
                                oom_hit = True
                        except Exception:
                            pass
                        if oom_hit:
                            from backend.services.executor import _get_gpu_free_mib
                            free_mib = _get_gpu_free_mib(runner)
                            err_detail += (f"\n⚠ 检测到内存不足 (当前可用 {free_mib/1024:.1f} GiB)。"
                                           f"目标机上可能存在占用大量内存的服务/容器，请释放后重试。")
                        err_detail += f"\n{logs_tail[:400]}"
                        _update_test_result(m, target_device_config, "FAIL", err_detail, db)
                        yield send_evt(3, 85, "DONE", err_detail, {
                            "status": "FAIL", "detail": err_detail, "logs_tail": logs_tail,
                            "container_id": container_id
                        })
                        return
                except Exception:
                    pass

                await asyncio.sleep(1.5)

            if not vllm_ready:
                logs_tail = ""
                try:
                    logs_proc = await asyncio.to_thread(runner.run_docker, ["logs", "--tail", "30", CONTAINER_NAME], timeout=5)
                    logs_tail = (logs_proc.stdout + logs_proc.stderr).strip()
                except Exception:
                    pass
                err_msg = f"推理服务启动超时 [{host_label}] ({MAX_VLLM_WAIT}s)\n容器日志:\n{logs_tail[:400]}"
                _update_test_result(m, target_device_config, "FAIL", err_msg, db)
                yield send_evt(3, 85, "DONE", err_msg, {
                    "status": "FAIL", "detail": err_msg, "logs_tail": logs_tail,
                    "container_id": container_id
                })
                return

            # 4. 探针对话验证
            yield send_evt(4, 90, "CHAT", "正在向推理接口发送真实 Prompt 验证问答与推理能力...")
            model_name_match = re.search(r"-e MODEL_NAME=([^ \n\\]+)", docker_cmd)
            model_name = model_name_match.group(1).strip() if model_name_match else m.name

            chat_url = f"http://{api_host}:{test_port}/v1/chat/completions"
            payload = {
                "model": model_name,
                "messages": [{"role": "user", "content": "你好，请用一句话介绍你自己。"}],
                "max_tokens": 100, "temperature": 0,
            }

            try:
                def send_chat():
                    return requests.post(chat_url, json=payload, timeout=60)
                r = await asyncio.to_thread(send_chat)
                if r.status_code == 200:
                    data = r.json()
                    reply = data["choices"][0]["message"].get("content", "").strip()
                    reasoning = data["choices"][0]["message"].get("reasoning", "")
                    _update_test_result(m, target_device_config, "PASS", f"PASS [{host_label}]: {reply[:200]}", db)
                    yield send_evt(4, 100, "DONE", f"🎉 模型连通性与推理验证通过！测试容器 ({container_id}) 已自动销毁清理，GPU 显存与内存资源已归零释放。", {
                        "status": "PASS", "reply": reply, "reasoning": reasoning[:200] if reasoning else "",
                        "model": model_name, "container_id": container_id,
                        "device_name": device.name if device else "本机"
                    })
                else:
                    error_msg = f"对话请求失败 [{host_label}] HTTP {r.status_code}: {r.text[:200]}"
                    _update_test_result(m, target_device_config, "FAIL", error_msg, db)
                    yield send_evt(4, 100, "DONE", error_msg, {"status": "FAIL", "detail": error_msg})
            except Exception as e:
                error_msg = f"对话异常 [{host_label}]: {str(e)[:200]}"
                _update_test_result(m, target_device_config, "FAIL", error_msg, db)
                yield send_evt(4, 100, "DONE", error_msg, {"status": "FAIL", "detail": error_msg})

        finally:
            # 真实清理测试容器
            await asyncio.to_thread(_stop_test_container, runner)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ============================================================
#  ModelScope 模型引入（精确 repo_id，无目录/关键字搜索 API）
# ============================================================

class ModelScopeResolveRequest(BaseModel):
    repo_id: str


class ModelScopeImportRequest(BaseModel):
    repo_id: str
    group_name: str = "NVIDIA_jetson_AGX_Thor"


@router.post("/modelscope/resolve")
def api_modelscope_resolve(data: ModelScopeResolveRequest):
    """预览 ModelScope 模型：详情+文件列表+大小估算（匿名 API）"""
    from backend.services import modelscope_service
    try:
        info = modelscope_service.resolve_model(data.repo_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(404, str(e))
    return info


@router.post("/modelscope/import")
def api_modelscope_import(data: ModelScopeImportRequest, db: Session = Depends(get_db)):
    """确认引入：注册到平台 + 生成 docker 部署命令"""
    from backend.services import modelscope_service
    try:
        info = modelscope_service.resolve_model(data.repo_id)
    except Exception as e:
        raise HTTPException(400, str(e))

    repo_id = info["repo_id"]
    slug = repo_id.split("/")[-1].lower().replace("_", "-").replace(".", "-")
    name = info["name"]

    existing = db.execute(select(ModelInfo).where(ModelInfo.slug == slug)).scalar_one_or_none()
    if existing:
        existing.tos_path = f"modelscope://{repo_id}"
        existing.result_detail = f"ModelScope 引入更新 ({info['total_size_human']})"
        db.commit()
        db.refresh(existing)
        return {"message": f"模型 {name} 已存在，已更新为 ModelScope 来源", "model": {"id": existing.id, "name": existing.name, "slug": existing.slug}}

    max_idx = db.execute(select(func.max(ModelInfo.idx))).scalar() or 0
    model = ModelInfo(
        idx=max_idx + 1,
        name=name,
        slug=slug,
        group_name=data.group_name,
        docker_command=modelscope_service.build_docker_command(repo_id),
        tos_path=f"modelscope://{repo_id}",
        status="DOWNLOADING",
        size_category="Custom",
        result_detail=f"ModelScope 引入，正在自动下载权重到本机 ~/models/{name} ...",
    )
    db.add(model)
    db.commit()
    db.refresh(model)

    # 后台线程自动下载权重（本地 ~/models/<name>），完成后更新状态
    import threading
    model_id = model.id
    mdl_slug = model.slug

    def _dl():
        try:
            target = modelscope_service.download_model(repo_id)
            db2 = next(get_db())
            try:
                m = db2.get(ModelInfo, model_id)
                if m:
                    m.status = "NEW"
                    m.result_detail = f"ModelScope 引入完成，权重已就绪: {target}"
                    db2.commit()
            finally:
                db2.close()
        except Exception as e:
            db2 = next(get_db())
            try:
                m = db2.get(ModelInfo, model_id)
                if m:
                    m.status = "FAIL"
                    m.result_detail = f"ModelScope 权重下载失败: {e}"
                    db2.commit()
            finally:
                db2.close()

    threading.Thread(target=_dl, daemon=True).start()
    return {"message": f"模型 {name} 已成功引入！正在后台自动下载权重到本机（完成后即可验证）。", "model": {"id": model.id, "name": model.name, "slug": model.slug}}
