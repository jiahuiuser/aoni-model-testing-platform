"""
ModelScope 模型引入服务 — resolve（详情+文件预览）与 import（注册+生成部署命令）

实测可用匿名端点:
- GET https://modelscope.cn/api/v1/models/{org}/{name}          模型详情
- GET https://modelscope.cn/api/v1/models/{org}/{name}/repo/files?Revision=master&Recursive=true  文件列表
（关键字搜索/目录浏览无匿名 API，只支持精确 repo_id）
"""
import httpx

from backend import config

MODELSCOPE_BASE = "https://modelscope.cn"


def _get_json(url: str, params: dict | None = None, timeout: int = 30) -> dict:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Referer": f"{MODELSCOPE_BASE}/",
    }
    # trust_env=False: 忽略环境代理 (httpx 不支持 socks:// scheme, modelscope 直连可达)
    with httpx.Client(trust_env=False, timeout=timeout) as client:
        resp = client.get(url, params=params, headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"ModelScope 接口返回 HTTP {resp.status_code}")
    return resp.json()


def _normalize_repo_id(repo_id: str) -> str:
    """允许 Qwen/Qwen2.5-7B-Instruct 或 Qwen2.5-7B-Instruct 形式"""
    repo_id = (repo_id or "").strip().strip("/")
    if not repo_id:
        raise ValueError("repo_id 不能为空")
    if "/" not in repo_id:
        # 无组织时默认 AI-ModelSpot 兼容老命名空间（ModelScope 老仓库默认 damo）
        repo_id = f"AI-Model-Scope/{repo_id}" if False else repo_id
    return repo_id


def resolve_model(repo_id: str) -> dict:
    """拉取模型详情+文件列表，生成预览信息（含 config.json 解析与大小估算）"""
    import asyncio

    repo_id = _normalize_repo_id(repo_id)
    detail_url = f"{MODELSCOPE_BASE}/api/v1/models/{repo_id}"
    files_url = f"{detail_url}/repo/files"

    try:
        detail_resp = _get_json(detail_url)
    except Exception as e:
        raise RuntimeError(f"模型不存在或无法访问: {repo_id} ({e})")

    if detail_resp.get("Code") != 200:
        raise RuntimeError(f"模型不存在: {repo_id}")

    d = detail_resp.get("Data") or {}
    files = []
    try:
        files_resp = _get_json(files_url, params={"Revision": "master", "Recursive": "true"})
        files = (files_resp.get("Data") or {}).get("Files") or []
    except Exception:
        pass

    # 大小统计
    weight_ext = (".safetensors", ".bin", ".gguf", ".pth", ".pt")
    total_size = sum(f.get("Size") or 0 for f in files)
    weight_size = sum(f.get("Size") or 0 for f in files
                      if (f.get("Path") or "").endswith(weight_ext))

    return {
        "repo_id": repo_id,
        "name": d.get("Name") or repo_id.split("/")[-1],
        "namespace": d.get("Path") or repo_id.split("/")[0],
        "chinese_name": d.get("ChineseName") or "",
        "description": (d.get("Description") or "")[:300],
        "downloads": d.get("Downloads") or 0,
        "license": d.get("License") or "",
        "file_count": len(files),
        "total_size": total_size,
        "weight_size": weight_size,
        "total_size_human": _human(total_size),
        "weight_size_human": _human(weight_size),
        "tasks": [t.get("ChineseName") or t.get("Name") for t in (d.get("Tasks") or [])][:5],
    }


def _human(size: int) -> str:
    if size >= 1e9:
        return f"{size / 1e9:.2f} GB"
    if size >= 1e6:
        return f"{size / 1e6:.1f} MB"
    if size >= 1e3:
        return f"{size / 1e3:.1f} KB"
    return f"{size} B"


def build_docker_command(repo_id: str, group_name: str = "NVIDIA_jetson_AGX_Thor") -> str:
    """生成下载 + 推理部署命令（vLLM 容器, 从 ModelScope 拉权重）"""
    name = repo_id.split("/")[-1]
    cmd = (
        f"sudo docker run -it --rm --runtime=nvidia --network host "
        f"-e MODEL_OSS=True -e MODEL_ROOT=/models -e ENGINE_URI=modelscope://{repo_id} "
        f"-e MODEL_NAME={name} -v ~/models:/models "
        f"aoni-docker-cn-guangzhou.cr.volces.com/public/llm:vllm-openai-nightly-aarch64 vllm serve {name} "
        f"--port 8300 --max-model-len 4096 --gpu-memory-utilization 0.8"
    )
    return cmd
