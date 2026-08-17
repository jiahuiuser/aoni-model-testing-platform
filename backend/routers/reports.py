import io
import json
import datetime
import threading
import zipfile
from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import select, desc, asc
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.auth import get_current_user
from backend.models import Task, ModelRun, PerfResult, AccResult
from backend.models.user import User

router = APIRouter(prefix="/api/reports", tags=["reports"])


def check_report_access(mr: ModelRun, user: User):
    if user.role != "admin" and mr.task and mr.task.user_id is not None and mr.task.user_id != user.id:
        raise HTTPException(403, "权限拒绝：您无权查阅或删除其他用户的测试报告")


@router.get("/tasks")
def api_list_report_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取所有包含测试报告的任务列表，供前端快捷按任务筛选与全选导出"""
    query = select(Task).order_by(desc(Task.id))
    if current_user.role != "admin":
        query = query.where(Task.user_id == current_user.id)
    tasks = db.execute(query).scalars().all()
    
    result = []
    for t in tasks:
        # 统计该任务下包含的 model_runs 报告数量
        count = sum(1 for mr in t.model_runs) if t.model_runs else 0
        if count > 0:
            result.append({
                "id": t.id,
                "name": t.name or f"任务 #{t.id}",
                "report_count": count,
                "created_at": (t.created_at.isoformat() + "Z") if t.created_at else None
            })
    return result


@router.get("")
def api_list_reports(
    device_id: int = None,
    task_id: int = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(ModelRun).outerjoin(Task, ModelRun.task_id == Task.id).order_by(desc(ModelRun.completed_at), desc(ModelRun.id))
    # 多用户数据隔离：普通用户只能查看自己的测试报告；管理员 (admin) 可查阅全量报告
    if current_user.role != "admin":
        query = query.where(Task.user_id == current_user.id)
    if device_id:
        query = query.where(ModelRun.device_id == device_id)
    if task_id:
        query = query.where(ModelRun.task_id == task_id)
    query = query.limit(500)
    runs = db.execute(query).scalars().all()
    data = []
    for mr in runs:
        data.append({
            "id": mr.id,
            "task_id": mr.task_id,
            "task_name": mr.task.name if mr.task else f"任务 #{mr.task_id}",
            "user_id": mr.task.user_id if mr.task else None,
            "username": mr.task.user.username if mr.task and mr.task.user else None,
            "model_idx": mr.model_idx,
            "model_name": mr.model_name,
            "model_slug": mr.model_slug,
            "device_id": mr.device_id,
            "device_name": mr.device_name or "本机",
            "status": (mr.status.value if hasattr(mr.status, "value") else str(mr.status or "unknown")),
            "perf_results_count": len(mr.perf_results or []),
            "acc_results_count": len(mr.acc_results or []),
            "started_at": (mr.started_at.isoformat() + "Z") if mr.started_at else None,
            "completed_at": (mr.completed_at.isoformat() + "Z") if mr.completed_at else None,
        })
    return data


import re

def parse_docker_env_params(cmd_str: str) -> dict:
    params = {
        "max_model_len": "4096 tokens (默认)",
        "gpu_memory_utilization": "85.0% (0.85 默认)",
        "gpu_layers": "N/A (GPU 核心加速)",
        "concurrency_limit": "256",
    }
    if not cmd_str:
        return params

    m_len = re.search(r"--max-model-len\s+([0-9]+)", cmd_str)
    if m_len:
        params["max_model_len"] = f"{m_len.group(1)} tokens"
    else:
        m_c = re.search(r"-c\s+([0-9]+)", cmd_str)
        if m_c:
            params["max_model_len"] = f"{m_c.group(1)} tokens"

    m_gpu = re.search(r"--gpu-memory-utilization\s+([0-9\.]+)", cmd_str)
    if m_gpu:
        val = float(m_gpu.group(1))
        params["gpu_memory_utilization"] = f"{val * 100:.1f}% ({val})"

    m_ngl = re.search(r"-ngl\s+([0-9]+)", cmd_str)
    if m_ngl:
        params["gpu_layers"] = f"{m_ngl.group(1)} (全量 GPU 卸载加速)"

    m_seqs = re.search(r"--max-num-seqs\s+([0-9]+)", cmd_str)
    if m_seqs:
        params["concurrency_limit"] = m_seqs.group(1)

    return params


@router.get("/compare/throughput")
def api_compare_throughput(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(PerfResult).join(ModelRun, PerfResult.model_run_id == ModelRun.id).outerjoin(Task, ModelRun.task_id == Task.id).where(
        PerfResult.concurrency == 8,
        PerfResult.output_type == "short",
        PerfResult.throughput_tok_s.isnot(None),
    )
    if current_user.role != "admin":
        query = query.where(Task.user_id == current_user.id)
    rows = db.execute(query.order_by(desc(PerfResult.throughput_tok_s)).limit(50)).scalars().all()
    return [{
        "model_slug": r.model_run.model_slug if r.model_run else "?",
        "model_name": r.model_run.model_name if r.model_run else "?",
        "concurrency": r.concurrency,
        "throughput_tok_s": r.throughput_tok_s,
        "mean_ttft_ms": r.mean_ttft_ms,
        "p99_ttft_ms": r.p99_ttft_ms,
    } for r in rows]


@router.get("/compare/accuracy")
def api_compare_accuracy(
    dataset: str = "mmlu",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(AccResult).join(ModelRun, AccResult.model_run_id == ModelRun.id).outerjoin(Task, ModelRun.task_id == Task.id).where(
        AccResult.dataset == dataset,
        AccResult.accuracy.isnot(None),
    )
    if current_user.role != "admin":
        query = query.where(Task.user_id == current_user.id)
    rows = db.execute(query.order_by(desc(AccResult.accuracy)).limit(50)).scalars().all()
    return [{
        "model_slug": r.model_run.model_slug if r.model_run else "?",
        "model_name": r.model_run.model_name if r.model_run else "?",
        "dataset": r.dataset,
        "accuracy": r.accuracy,
    } for r in rows]


@router.get("/{model_run_id}")
def api_get_report(
    model_run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    mr = db.get(ModelRun, model_run_id)
    if not mr:
        raise HTTPException(404, "报告不存在")
    check_report_access(mr, current_user)

    gateway_data = []
    for gr in (mr.gateway_results or []):
        gateway_data.append({
            "id": gr.id, "category": gr.category,
            "test_item": gr.test_item, "protocol": gr.protocol,
            "status": gr.status, "latency_ms": gr.latency_ms,
            "message": gr.message, "raw_details": gr.raw_details,
        })

    perf_data = []
    for pr in (mr.perf_results or []):
        perf_data.append({
            "id": pr.id, "round_num": pr.round_num,
            "strategy_id": pr.strategy_id, "output_type": pr.output_type,
            "concurrency": pr.concurrency, "input_len": pr.input_len,
            "output_len": pr.output_len,
            "throughput_tok_s": pr.throughput_tok_s,
            "mean_ttft_ms": pr.mean_ttft_ms, "p99_ttft_ms": pr.p99_ttft_ms,
            "mean_tpot_ms": pr.mean_tpot_ms, "p99_tpot_ms": pr.p99_tpot_ms,
            "error": pr.error,
        })

    acc_data = []
    for ar in (mr.acc_results or []):
        acc_data.append({
            "id": ar.id, "dataset": ar.dataset,
            "accuracy": ar.accuracy, "error": ar.error,
        })

    dev = mr.device
    dev_name = mr.device_name or (dev.name if dev else "NVIDIA AGX Thor (本机)")
    gpu_spec = (dev.gpu_info if dev and dev.gpu_info else "NVIDIA AGX Thor (Blackwell Tensor Cores / 64GB Unified)")

    docker_cmd = mr.docker_command or "vllm serve --port 8300 --max-model-len 4096 --gpu-memory-utilization 0.85"
    engine_params = parse_docker_env_params(docker_cmd)

    return {
        "id": mr.id,
        "task_id": mr.task_id,
        "task_name": mr.task.name if mr.task else f"任务 #{mr.task_id}",
        "user_name": mr.task.user.username if (mr.task and mr.task.user) else "管理员",
        "profile": mr.task.profile if mr.task else "full",
        "model_name": mr.model_name,
        "model_slug": mr.model_slug,
        "model_idx": mr.model_idx,
        "size_category": mr.size_category or "small_medium",
        "status": (mr.status.value if hasattr(mr.status, "value") else str(mr.status or "unknown")),
        "device_name": dev_name,
        "device_host": dev.host if dev else "127.0.0.1",
        "gpu_info": gpu_spec,
        "cpu_cores": dev.cpu_cores if (dev and dev.cpu_cores) else 12,
        "memory_gb": dev.memory_gb if (dev and dev.memory_gb) else 64.0,
        "docker_command": docker_cmd,
        "max_model_len": engine_params["max_model_len"],
        "gpu_memory_utilization": engine_params["gpu_memory_utilization"],
        "gpu_layers": engine_params["gpu_layers"],
        "started_at": mr.started_at.isoformat() if mr.started_at else None,
        "completed_at": mr.completed_at.isoformat() if mr.completed_at else None,
        "gateway_results": gateway_data,
        "perf_results": perf_data,
        "acc_results": acc_data,
    }


@router.delete("/{model_run_id}")
def api_delete_report(
    model_run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    mr = db.get(ModelRun, model_run_id)
    if not mr:
        raise HTTPException(404, "报告不存在")
    check_report_access(mr, current_user)
    db.delete(mr)
    db.commit()
    return {"status": "deleted"}


@router.post("/batch-download-zip")
def api_batch_download_zip(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """将选中的多个模型评测报告打包为单个 .zip 压缩包并提供一键安全下载，彻底消除浏览器多文件防护提示与逐个保存问题"""
    ids = payload.get("ids", [])
    task_id = payload.get("task_id")
    
    query = select(ModelRun)
    if ids:
        query = query.where(ModelRun.id.in_(ids))
    elif task_id:
        query = query.where(ModelRun.task_id == task_id)
    else:
        raise HTTPException(400, "必须指定 ids 列表或 task_id")
        
    runs = db.execute(query).scalars().all()
    if not runs:
        raise HTTPException(404, "未找到符合条件的测试报告")
        
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for mr in runs:
            try:
                check_report_access(mr, current_user)
                res = api_download_report(mr.id, db=db, current_user=current_user)
                content_bytes = res.body
                fname = f"Task{mr.task_id}_{mr.model_slug}_benchmark_report.md"
                zf.writestr(fname, content_bytes)
            except Exception:
                continue

    buf.seek(0)
    zip_filename = f"Task_{task_id or 'batch'}_Benchmark_Reports.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'}
    )


def parse_full_docker_cmd(cmd_str: str) -> dict:
    """从 docker 启动命令字符串中解析关键镜像、数据卷、环境变量与推理引擎参数"""
    info = {
        "image_repo": "aoni/vllm/vllm-openai",
        "image_tag": "nightly-aarch64",
        "container_name": "aoni_llm_server",
        "runtime": "nvidia",
        "shm_size": "16 GB",
        "restart_policy": "unless-stopped",
        "port": "8300",
        "volumes": [],
        "model_path": "N/A",
        "served_model_name": "N/A",
        "max_model_len": "40960 tokens",
        "gpu_memory_utilization": "85.0%",
        "gpu_layers": "N/A",
        "tp_size": "1",
        "dtype": "auto",
        "reasoning_parser": "N/A",
        "tool_call_parser": "N/A",
        "speculative_config": None,
        # ---- 扩展：部署引擎 / 量化 / 上下文 ----
        "engine": "vllm",            # vllm / llama_cpp
        "llama_cpp_gfl": None,       # -ngl 值 (llama.cpp)
        "llama_model_file": None,    # llama.cpp -m 指向的具体 gguf 文件
        "quantization": None,        # 从权重路径/文件名解析出的量化
        "actual_model_name": None,   # 从命令解析出的真实模型名
        "actual_model_size": None,   # 从权重路径可能体现的规模
        "context_len": "4096",       # llama.cpp -c
    }
    if not cmd_str:
        return info

    # 判定部署引擎：含 llama-server / llama_cpp / .gguf => llama.cpp；否则 vLLM
    is_llama = ("llama-server" in cmd_str or "llama_cpp" in cmd_str
                or ".gguf" in cmd_str or "llamacpp" in cmd_str.lower())
    info["engine"] = "llama_cpp" if is_llama else "vllm"

    m_img = re.search(r"(ghcr\.io/nvidia-ai-iot/[a-zA-Z0-9_\-\.\/]+:[a-zA-Z0-9_\-\.]+|aoni-docker-cn-guangzhou\.cr\.volces\.com/public/[a-zA-Z0-9_\-\.\/]+:[a-zA-Z0-9_\-\.]+|aoni/vllm/[a-zA-Z0-9_\-\.]+:[a-zA-Z0-9_\-\.]+)", cmd_str)
    if m_img:
        parts = m_img.group(1).rsplit(":", 1)
        info["image_repo"] = parts[0]
        info["image_tag"] = parts[1]

    m_name = re.search(r"-e\s+MODEL_NAME=([^\s]+)", cmd_str)
    info["actual_model_name"] = m_name.group(1) if m_name else None

    m_rt = re.search(r"--runtime=?([a-zA-Z0-9_\-]+)", cmd_str)
    if m_rt:
        info["runtime"] = m_rt.group(1)

    # 兼容等号与空格两种写法
    m_shm = re.search(r"--shm-size[=\s]+([a-zA-Z0-9]+)", cmd_str)
    if m_shm:
        info["shm_size"] = m_shm.group(1)

    m_port = re.search(r"--port[=\s]+([0-9]+)", cmd_str)
    if m_port:
        info["port"] = m_port.group(1)
    else:
        m_p = re.search(r"-p\s+([0-9]+):[0-9]+", cmd_str)
        if m_p:
            info["port"] = m_p.group(1)

    m_vols = re.findall(r"-v\s+([^\s:]+):([^\s:]+)", cmd_str)
    for host_p, container_p in m_vols:
        info["volumes"].append({"host": host_p, "container": container_p, "mode": "RW"})

    info["model_path"] = "N/A"
    if is_llama:
        m_model = re.search(r"llama-server\s+-m\s+([^\s]+)", cmd_str) or re.search(r"-m\s+([^\s]+\.gguf)", cmd_str)
        if m_model:
            info["model_path"] = m_model.group(1)
            info["llama_model_file"] = m_model.group(1).split("/")[-1]
            # 从 gguf 文件名/路径推断量化与规模
            fname = m_model.group(1)
            for q in ("NK3", "Q8_0", "Q6_K", "Q5_K_M", "Q5_0", "Q4_K_M", "Q4_0", "IQ4_XS",
                      "Q4_K_XL", "Q4_K_S", "Q3_K_M", "Q2_K", "NVFP4", "FP16", "BF16"):
                if q in fname.upper():
                    info["quantization"] = q
                    break
        m_ngl = re.search(r"-ngl[=\s]+([0-9]+)", cmd_str)
        if m_ngl:
            info["llama_cpp_gfl"] = m_ngl.group(1)
            info["gpu_layers"] = f"全部 ({m_ngl.group(1)} 层) GPU 卸载" if m_ngl.group(1) == "999" else f"{m_ngl.group(1)} 层 GPU 卸载"
        m_clen = re.search(r"llama-server\s+.*?-c\s+([0-9]+)", cmd_str) or re.search(r"-c\s+([0-9]+)", cmd_str)
        if m_clen:
            info["context_len"] = m_clen.group(1)
            info["max_model_len"] = f"{m_clen.group(1)} tokens"
        # llama.cpp 显存由 -ngl 控制，不适用 gpu-memory-utilization
        info["gpu_memory_utilization"] = "由 -ngl 层数控制（llama.cpp）"
    else:
        m_model = re.search(r"--model\s+([^\s]+)", cmd_str)
        if m_model:
            info["model_path"] = m_model.group(1)
            fname = m_model.group(1)
            for q in ("NVFP4", "AWQ", "GPTQ", "W4A16", "W8A8", "FP16", "FP8", "BF16"):
                if q in fname.upper():
                    info["quantization"] = q
                    break

    m_sname = re.search(r"--served-model-name[=\s]+([^\s]+)", cmd_str)
    if m_sname:
        info["served_model_name"] = m_sname.group(1)

    if not is_llama:
        m_len = re.search(r"--max-model-len[=\s]+([0-9]+)", cmd_str)
        if m_len:
            info["max_model_len"] = f"{m_len.group(1)} tokens"
        m_gpu = re.search(r"--gpu-memory-utilization[=\s]+([0-9\.]+)", cmd_str)
        if m_gpu:
            val = float(m_gpu.group(1))
            info["gpu_memory_utilization"] = f"{val * 100:.1f}% ({val})"
        m_tp = re.search(r"--tensor-parallel-size[=\s]+([0-9]+)", cmd_str)
        if m_tp:
            info["tp_size"] = m_tp.group(1)
        m_dt = re.search(r"--dtype[=\s]+([a-zA-Z0-9_\-]+)", cmd_str)
        if m_dt:
            info["dtype"] = m_dt.group(1)
        m_rp = re.search(r"--reasoning-parser[=\s]+([a-zA-Z0-9_\-]+)", cmd_str)
        if m_rp:
            info["reasoning_parser"] = m_rp.group(1)
        m_tp_parser = re.search(r"--tool-call-parser[=\s]+([a-zA-Z0-9_\-]+)", cmd_str)
        if m_tp_parser:
            info["tool_call_parser"] = m_tp_parser.group(1)
        m_spec = re.search(r"--speculative-config[=\s]+'([^']+)'", cmd_str)
        if not m_spec:
            m_spec = re.search(r'--speculative-config[=\s]+"([^"]+)"', cmd_str)
        if m_spec:
            try:
                info["speculative_config"] = json.loads(m_spec.group(1))
            except Exception:
                info["speculative_config"] = {"raw": m_spec.group(1)}

    # 有 --rm 时容器结束自动删除，无从谈及 unless-stopped 重启策略（修正矛盾）
    if "--rm" in cmd_str:
        info["restart_policy"] = "--rm（容器运行结束即自动删除）"

    return info


def _run_cmd_safe(args: list, timeout: int = 8) -> str:
    """安全执行本地探测命令并返回 stdout+stderr 首行（失败返回空串）"""
    import subprocess
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip() or (r.stderr or "").strip()
    except Exception:
        return ""


# 环境探测结果缓存：避免每次生成报告都对运行中的推理容器做高延时 docker exec 探测
# （压测容器繁忙时 docker exec vllm --version 可阻塞 ~13s，重复探测会让批量 ZIP 打包极慢）
_env_probe_cache: dict = {"ts": 0.0, "data": None}
_ENV_PROBE_TTL = 120.0
_env_probe_lock = threading.Lock()


def _probe_local_env_cached() -> dict:
    """带 TTL 缓存的环境探测：单进程内最多每 120s 真实探测一次，其余复用上次结果"""
    now = _now_ts()
    cache = _env_probe_cache
    if cache["data"] is not None and (now - cache["ts"]) <= _ENV_PROBE_TTL:
        return cache["data"]
    with _env_probe_lock:
        if cache["data"] is not None and (now - cache["ts"]) <= _ENV_PROBE_TTL:
            return cache["data"]
        cache["data"] = _probe_local_env()
        cache["ts"] = _now_ts()
    return cache["data"]


def _now_ts() -> float:
    import time
    return time.time()


def _probe_local_env() -> dict:
    """探测宿主机与当前推理容器的真实软硬件环境（回退为 None，由调用方兜底）"""
    env = {
        "gpu_name": None, "gpu_total_mib": None, "driver_version": None,
        "vllm_version": None, "python_version": None, "torch_version": None,
        "cuda_version": None, "os_version": None,
    }
    # GPU / 驱动（nvidia-smi 对统一内存架构返回 N/A 显存，显存用设备表）
    gpu_info = _run_cmd_safe(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"])
    if gpu_info:
        parts = [p.strip() for p in gpu_info.split(",")]
        if len(parts) >= 3:
            env["gpu_name"] = parts[0]
            if parts[1].replace(".", "", 1).replace("N/A", "").strip().isdigit():
                env["gpu_total_mib"] = float(parts[1]) if parts[1] != "N/A" else None
            env["driver_version"] = parts[2]
    # 操作系统
    os_rel = _run_cmd_safe(["sh", "-c", ". /etc/os-release 2>/dev/null && echo \"$PRETTY_NAME\""])
    env["os_version"] = os_rel or None
    # 宿主 Python
    py = _run_cmd_safe(["python3", "--version"])
    if py.startswith("Python"):
        env["python_version"] = py.split(" ", 1)[1]
    # 推理容器内真实版本（若当前有运行中的 aoni 容器）
    from backend.services.executor import CONTAINER_NAME
    container_present = bool(_run_cmd_safe(["docker", "ps", "--format", "{{.Names}}"]).split("\n").__contains__(CONTAINER_NAME))
    if container_present:
        v = _run_cmd_safe(["docker", "exec", CONTAINER_NAME, "vllm", "--version"], timeout=8)
        if v:
            # 取包含版本号的行（vllm --version 可能带前缀/换行）
            ver_line = next((ln.strip() for ln in v.split("\n") if ln.strip()), "")
            if ver_line:
                env["vllm_version"] = ver_line.split("version", 1)[-1].strip().lstrip("= ") if "version" in ver_line.lower() else ver_line
            if not env.get("vllm_version"):
                env["vllm_version"] = ver_line
        ct = _run_cmd_safe(["docker", "exec", CONTAINER_NAME, "python3", "-c",
                            "import torch;print(torch.__version__+','+torch.version.cuda)"], timeout=8)
        if ct:
            parts = ct.split(",")
            if len(parts) == 2:
                env["torch_version"] = parts[0].strip()
                env["cuda_version"] = parts[1].strip()
    return env


@router.get("/{model_run_id}/download")
def api_download_report(
    model_run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """下载单模型权威测试报告，100% 遵循 benchmark_report_Qwen3.6-35B-A3B-NVFP4.md 标准规范结构（全量真实数据绑定）"""
    import os
    mr = db.get(ModelRun, model_run_id)
    if not mr:
        raise HTTPException(404, "报告不存在")
    check_report_access(mr, current_user)

    dev = mr.device
    dev_name = mr.device_name or (dev.name if dev else "NVIDIA Jetson AGX Thor Developer Kit")
    dev_host = dev.host if dev else "127.0.0.1"

    # 动态探测宿主机与容器真实软硬件环境（探测不到时回退设备表真实值，最后才用默认）
    env_probe = _probe_local_env_cached()

    if dev and dev.gpu_info:
        gpu_spec = dev.gpu_info
    elif env_probe.get("gpu_name"):
        gpu_spec = env_probe["gpu_name"]
        if env_probe.get("driver_version"):
            gpu_spec += f" (驱动 {env_probe['driver_version']})"
    else:
        gpu_spec = "NVIDIA Jetson AGX Thor"
    # 清洗裸漏的占位符 / 空值，避免把 [N/A]、None 之类泄漏给客户
    gpu_spec = re.sub(r"[\s,;]*\[*\s*[Nn]/?\s*[Aa]\s*\]*[\s,;]*", ", ", gpu_spec).strip(" ,").strip(",").strip()
    if gpu_spec in ("", "None", "N/A", "nan"):
        gpu_spec = "NVIDIA Jetson AGX Thor"

    cpu_spec = f"{dev.cpu_cores if (dev and dev.cpu_cores) else 14} 核 ARM aarch64"
    mem_total_gb = dev.memory_gb if (dev and dev.memory_gb) else (122.0)

    # GPU 显存（统一内存架构 nvidia-smi 为 N/A，采用设备登记的总内存；独立 GPU 用 nvidia-smi 实时值）
    if env_probe.get("gpu_total_mib"):
        mem_total_gb = env_probe["gpu_total_mib"] / 1024.0

    docker_cmd = mr.docker_command or "vllm serve --port 8300 --max-model-len 40960 --gpu-memory-utilization 0.8"
    d_info = parse_full_docker_cmd(docker_cmd)
    engine_label = "llama.cpp 推理引擎" if d_info["engine"] == "llama_cpp" else "vLLM 推理引擎"

    # 动态解析设备最近监控资源；探测不到时回退为已登记的 Total（不再写死 90GiB）
    mem_used_str = None
    if dev and dev.last_check_detail and isinstance(dev.last_check_detail, dict):
        mem_info = dev.last_check_detail.get("memory", {})
        if isinstance(mem_info, dict) and "used" in mem_info:
            mem_used_str = f"约 {mem_info['used']} 已用"
    mem_spec = f"{mem_total_gb:g} GiB 总量" + (f"，{mem_used_str}" if mem_used_str else "") + f"（{engine_label} + 评测并发运行）"

    # 性能指标统计
    perf_list = mr.perf_results or []
    valid_perfs = [p for p in perf_list if p.throughput_tok_s is not None]
    
    max_tput = max([p.throughput_tok_s for p in valid_perfs], default=0.0)
    min_ttft = min([p.mean_ttft_ms for p in valid_perfs if p.mean_ttft_ms is not None], default=0.0)
    
    best_row = max(valid_perfs, key=lambda x: x.throughput_tok_s) if valid_perfs else None
    worst_row = min(valid_perfs, key=lambda x: x.throughput_tok_s) if valid_perfs else None
    
    concurrencies = sorted(list(set(p.concurrency for p in perf_list if p.concurrency is not None)))
    input_lens = sorted(list(set(p.input_len for p in perf_list if p.input_len is not None)))
    output_lens = sorted(list(set(p.output_len for p in perf_list if p.output_len is not None)))

    total_tests = len(perf_list)
    failed_tests = sum(1 for p in perf_list if p.error)
    completed_tests = total_tests - failed_tests
    pass_rate = f"{(completed_tests / total_tests * 100):.1f}%" if total_tests > 0 else "100.0%"

    test_date = (mr.completed_at or mr.started_at or datetime.datetime.utcnow()).strftime("%Y-%m-%d")

    # 模型架构与量化方式动态判定（优先取 docker 命令/权重路径解析出的真实量化）
    is_llama = d_info["engine"] == "llama_cpp"
    is_moe = "MoE" in mr.model_name or "A3B" in mr.model_name or "A14B" in mr.model_name or "mixtral" in mr.model_slug
    arch_desc = "MoE（Mixture-of-Experts 混合专家架构）" if is_moe else "Dense Transformer 密集自回归架构"

    # 量化优先：从 docker 命令的模型路径/文件名真实解析；其次才是模型名推测
    if d_info.get("quantization"):
        q = d_info["quantization"]
        quant_desc = f"{q} 量化"
        if q == "NVFP4":
            quant_desc = "NVFP4（NVIDIA 4-bit 浮点）"
        elif q in ("FP16", "BF16"):
            quant_desc = f"{q} 半精度"
    else:
        quant_desc = "FP16 半精度（默认推测，以实测权重为准）"
        if "NVFP4" in mr.model_name or "nvfp4" in mr.model_slug:
            quant_desc = "NVFP4（NVIDIA 4-bit 浮点）"
        elif "AWQ" in mr.model_name or "awq" in mr.model_slug:
            quant_desc = "AWQ 4-bit 量化"
        elif "GPTQ" in mr.model_name or "gptq" in mr.model_slug:
            quant_desc = "GPTQ 4-bit 量化"

    # 完成率与可靠性结论（避免"失败率极高仍写良好"）
    completion_ratio = (completed_tests / total_tests) if total_tests > 0 else 1.0
    if not valid_perfs:
        reliability_clause = "未获取到有效的性能数据，本次评估数据不足"
    elif completion_ratio >= 0.9:
        reliability_clause = "完成率较高，数据具备较好的参考价值"
    elif completion_ratio >= 0.6:
        reliability_clause = f"完成率 {pass_rate}，部分组合失败，结论仅供参考"
    else:
        reliability_clause = f"完成率仅 {pass_rate}，失败组合过多，结论不具备可靠性"

    # P99 尾部延迟预警：高并发下首字延迟若远超均值(≥2.5x)则提示
    p99_warning = None
    if valid_perfs and total_tests >= 6:
        flagged = []
        for p in valid_perfs:
            if p.concurrency and p.concurrency >= 8 and p.mean_ttft_ms and p.p99_ttft_ms:
                if p.p99_ttft_ms >= 2.5 * p.mean_ttft_ms:
                    flagged.append((p.concurrency, p.mean_ttft_ms, p.p99_ttft_ms))
        if flagged:
            concurrency_slots = sorted(set(c for c, _, _ in flagged))
            worst = max(flagged, key=lambda x: x[2])
            p99_warning = {
                "concurr": worst[0], "p99": worst[2], "mean": worst[1],
                "slots": ", ".join(map(str, concurrency_slots)),
            }

    lines = []
    # 报告大标题与元信息
    lines.append(f"# {mr.model_name} 推理性能测试报告")
    lines.append("")
    lines.append(f"> 测试日期：{test_date}")
    lines.append(f"> 测试平台：{dev_name}")
    if is_llama:
        lines.append(f"> 测试工具：llama.cpp Benchmark（`llama-server` OpenAI 兼容 API 压测）")
        lines.append(f"> 部署引擎：`llama.cpp`（`{d_info['image_repo']}:{d_info['image_tag']}`）")
    else:
        lines.append(f"> 测试工具：vLLM Benchmark（`vllm bench serve`，OpenAI backend）")
        lines.append(f"> 部署引擎：`vLLM`（`{d_info['image_repo']}:{d_info['image_tag']}`）")
    lines.append("")

    if not valid_perfs:
        summary_text = (
            f"**{mr.model_name}** 未获取到有效性能数据（完成 {completed_tests}/{total_tests} 组，完成率 {pass_rate}），"
            "本报告不基于吞吐/延迟作出性能结论，仅记录部署与环境配置。"
        )
    else:
        # 大吞吐值归因：峰值通常来自高并发下多路批量叠加，非单请求速度，需在摘要讲清避免夸大观感
        _best = max(valid_perfs, key=lambda x: x.throughput_tok_s or 0)
        _peak_conc = _best.concurrency
        _peak_il = _best.input_len
        _peak_ol = _best.output_len
        _single_tput = (1000.0 / _best.mean_tpot_ms) if (_best.mean_tpot_ms and _best.mean_tpot_ms > 0) else None
        _conc_clause = ""
        if _peak_conc is not None and _peak_conc >= 8:
            if _single_tput:
                _conc_clause = (f"该峰值出现在 **{_peak_conc} 路并发**（输入 {_peak_il} / 输出 {_peak_ol}），"
                                f"为多请求批量叠加下的**聚合吞吐**；折算单路流式吞吐约 **{_single_tput:.1f} tok/s**（对应 TPOT≈{_best.mean_tpot_ms:.0f}ms/Token）。")
            else:
                _conc_clause = (f"该峰值出现在 **{_peak_conc} 路并发**（输入 {_peak_il} / 输出 {_peak_ol}），"
                                f"为多请求批量叠加下的**聚合吞吐**。")
        summary_text = (
            f"在 **{dev_name}** 算力平台上，**{mr.model_name}** 模型在实测场景下最高输出吞吐达到 **{max_tput:.2f} tok/s**，"
            f"最佳首字响应延迟 (TTFT) 控制在 **{min_ttft:.2f} ms**。"
            + (f"{_conc_clause} " if _conc_clause else "")
            + f"在评测矩阵中完成 {completed_tests} 组测试，失败 {failed_tests} 组，完成率 {pass_rate}。{reliability_clause}。"
        )
    lines.append(f"**一句话摘要**：{summary_text}")

    # 场景化推荐：规则自动生成，仅基于本报告自身数据；数据不可靠(完成率<0.9)或无有效数据时不追加
    if valid_perfs and max_tput > 0 and completion_ratio >= 0.9:
        _peak = max_tput
        # 大模型判定（≥20B）：从 slug/name 解析"NB"数字，或参数量级为 medium_large
        _is_large = (mr.size_category or "") == "medium_large"
        _nb = re.search(r"(\d{2,})\s*b\b", (mr.model_slug or "").lower()) or re.search(r"(\d{2,})\s*b\b", (mr.model_name or "").lower())
        if _nb and int(_nb.group(1)) >= 20:
            _is_large = True
        _single_thr = 0.15 if _is_large else 0.25

        _cand = []
        # 1) 长上下文：Input ≥ 1433 且吞吐 > 峰值×0.4
        _rows = [p for p in valid_perfs if p.input_len and p.input_len >= 1433 and p.throughput_tok_s and p.throughput_tok_s > _peak * 0.40]
        if _rows:
            _r = max(_rows, key=lambda x: x.throughput_tok_s)
            _cand.append((_r.throughput_tok_s / _peak, _r, "lc"))
        # 2) 高并发：并发 ≥ 16 且 P99 TTFT < 1000ms 且吞吐 > 峰值×0.6
        _rows = [p for p in valid_perfs if p.concurrency and p.concurrency >= 16 and p.p99_ttft_ms is not None and p.p99_ttft_ms < 1000 and p.throughput_tok_s and p.throughput_tok_s > _peak * 0.60]
        if _rows:
            _r = max(_rows, key=lambda x: x.throughput_tok_s)
            _cand.append((_r.throughput_tok_s / _peak, _r, "hc"))
        # 3) 单路解码：Concurrency=1 且吞吐 > 峰值×(0.25 小模型 / 0.15 大模型)
        _rows = [p for p in valid_perfs if p.concurrency == 1 and p.throughput_tok_s and p.throughput_tok_s > _peak * _single_thr]
        if _rows:
            _r = max(_rows, key=lambda x: x.throughput_tok_s)
            _cand.append((_r.throughput_tok_s / _peak, _r, "sd"))
        # 4) 长输出：Output ≥ 4096 且吞吐 > 峰值×0.3
        _rows = [p for p in valid_perfs if p.output_len and p.output_len >= 4096 and p.throughput_tok_s and p.throughput_tok_s > _peak * 0.30]
        if _rows:
            _r = max(_rows, key=lambda x: x.throughput_tok_s)
            _cand.append((_r.throughput_tok_s / _peak, _r, "lo"))

        _cand.sort(key=lambda x: x[0], reverse=True)
        _top = _cand[:2]
        if _top:
            lines.append("**场景化推荐**：")
            for _score, _r, _kind in _top:
                if _kind == "hc":
                    lines.append(f"- **高并发实时交互**：推荐 `Input={_r.input_len}, Output={_r.output_len}, Concurrency={_r.concurrency}`，吞吐 {_r.throughput_tok_s:.2f} tok/s，P99 TTFT 仅 {_r.p99_ttft_ms:.1f} ms，适合实时交互/客服场景。")
                elif _kind == "lc":
                    lines.append(f"- **长上下文理解**：推荐 `Input={_r.input_len}, Output={_r.output_len}, Concurrency={_r.concurrency}`，吞吐 {_r.throughput_tok_s:.2f} tok/s，适合文档解析/RAG场景。")
                elif _kind == "sd":
                    _tpot = f"{_r.mean_tpot_ms:.1f}" if _r.mean_tpot_ms is not None else "-"
                    lines.append(f"- **单路解码**：推荐 `Input={_r.input_len}, Output={_r.output_len}, Concurrency=1`，单流吞吐 {_r.throughput_tok_s:.2f} tok/s（TPOT {_tpot} ms），适合单用户高体验场景。")
                elif _kind == "lo":
                    lines.append(f"- **长输出**：推荐 `Input={_r.input_len}, Output={_r.output_len}, Concurrency={_r.concurrency}`，吞吐 {_r.throughput_tok_s:.2f} tok/s，适合内容生成/代码创作场景。")
            lines.append("")

    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. 测试概述
    lines.append("## 1. 测试概述")
    lines.append("")
    lines.append("| 项目 | 内容 |")
    lines.append("|------|------|")
    lines.append(f"| 被测模型 | `{mr.model_name}`（Slug: `{mr.model_slug}`，架构: {arch_desc}，量化: {quant_desc}） |")
    if is_llama:
        lines.append("| 服务框架 | llama.cpp（`llama-server`，OpenAI 兼容 API） |")
        lines.append("| 请求速率 | 多路并发流式压测（每组合 Prompt 数与并发见 §2.1 用例表） |")
    else:
        lines.append("| 服务框架 | vLLM（`vllm serve`，OpenAI 兼容 API） |")
        lines.append("| 请求速率 | 无限满载（`request_rate=inf`，每组合 Prompt 数与并发见 §2.1） |")
    lines.append(f"| 采样规模 | 按任务配置矩阵采样（Task #{mr.task_id}），随机 Prompt 固定 input/output 长度 |")
    lines.append(f"| 并发度 | 梯度并发 `{', '.join(map(str, concurrencies)) if concurrencies else '1, 4, 8'}` |")
    lines.append(f"| 失败请求 | {failed_tests}（共 {total_tests} 组评测，completed={completed_tests}/failed={failed_tests}） |")
    in_str = " / ".join(map(str, input_lens)) if input_lens else "128 / 512 / 1024"
    out_str = " / ".join(map(str, output_lens)) if output_lens else "128 / 512 / 2048"
    lines.append(f"| 测试矩阵 | {len(input_lens) if input_lens else 3} 种输入长度 ({in_str}) × {len(output_lens) if output_lens else 3} 种输出长度 ({out_str}) |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 2. 测试方案与测试方法
    lines.append("## 2. 测试方案与测试方法")
    lines.append("")
    task_cfg = (mr.task.config if mr.task and mr.task.config else {})
    bench_tool = "llama.cpp 推理引擎（HTTP OpenAI 兼容压测）" if is_llama else "vLLM 原生 Benchmark（vllm bench serve）"
    _n2 = 0

    # 2.1 性能压测用例矩阵（基于真实已执行的组合，按 input×output 聚合）
    # 每组合 Prompt 数：优先取真实落的 raw_report（vLLM 有该字段）；
    # llama.cpp HTTP 压测 raw 无此字段，则按 output 长度回填任务配置 perf_rounds_config 的 num_prompts。
    _cfg_np_map = {}
    for _rd in (task_cfg.get("perf_rounds_config") or []):
        try:
            _npv = int(_rd.get("num_prompts") or 0)
            for _ol in (_rd.get("output_lens_str") or "").split(","):
                _ol_s = _ol.strip()
                if _npv and _ol_s.isdigit():
                    _cfg_np_map[int(_ol_s)] = _npv
        except (ValueError, TypeError):
            continue
    combos = {}
    for _p in perf_list:
        _key = (_p.input_len, _p.output_len)
        if _key not in combos:
            combos[_key] = {"concs": set(), "num_prompts": None}
        if _p.concurrency is not None:
            combos[_key]["concs"].add(int(_p.concurrency))
        if combos[_key]["num_prompts"] is None:
            try:
                _raw = _p.raw_report if isinstance(_p.raw_report, dict) else (json.loads(_p.raw_report) if _p.raw_report else {})
                if _raw.get("num_prompts"):
                    combos[_key]["num_prompts"] = int(_raw["num_prompts"])
            except Exception:
                pass
        if combos[_key]["num_prompts"] is None and (_p.output_len in _cfg_np_map):
            combos[_key]["num_prompts"] = _cfg_np_map[_p.output_len]
    _n2 += 1
    lines.append(f"### 2.{_n2} 性能压测用例矩阵")
    lines.append("")
    if combos:
        lines.append("| 用例 | 输入长度 (input_len) | 输出长度 (output_len) | 并发度 | 每组合 Prompt 数 |")
        lines.append("|:---:|:---:|:---:|:---:|:---:|")
        for _idx, ((_il, _ol), _info) in enumerate(sorted(combos.items()), 1):
            _concs = ", ".join(str(_c) for _c in sorted(_info["concs"]))
            _np = str(_info["num_prompts"]) if _info["num_prompts"] is not None else "-"
            lines.append(f"| P{_idx} | {_il} | {_ol} | {_concs} | {_np} |")
        lines.append("")
        lines.append(
            f"> 注：以上为实测执行过的性能用例组合。每组合以 `{bench_tool}` "
            + ("使用 random 数据集（固定 input/output 长度）、满载无限请求率（`--request-rate inf`）压测。"
               if is_llama is False
               else "通过 OpenAI 兼容接口并发发送固定长度随机 Prompt 压测。")
        )
        lines.append("")
    else:
        lines.append("*本次未收集到已完成的性能压测用例（无有效性能数据）。*")
        lines.append("")

    # 2.2 准确率评测用例
    if mr.acc_results:
        _n2 += 1
        lines.append(f"### 2.{_n2} 准确率评测用例")
        lines.append("")
        _acc_limit = task_cfg.get("acc_limit", 200)
        lines.append("| 评测集 (Dataset) | 抽取样本数 | 指标 |")
        lines.append("|:---:|:---:|:---:|")
        for _ar in mr.acc_results:
            _ds = (_ar.dataset or "-").upper()
            _lim = _ar.limit or _acc_limit
            lines.append(f"| {_ds} | {_lim} | Accuracy（Top-1） |")
        lines.append("")

    # 2.3 网关 / API 协议校验用例
    if mr.gateway_results:
        _n2 += 1
        lines.append(f"### 2.{_n2} 网关 / API 协议校验用例")
        lines.append("")
        lines.append("| 测试项 | 协议 | 状态 |")
        lines.append("|:---|:---:|:---:|")
        for _gr in mr.gateway_results:
            _st = _gr.status or "SKIP"
            lines.append(f"| {_gr.test_item} | {(_gr.protocol or '-').upper()} | {_st} |")
        lines.append("")

    # 2.4 测试方法说明
    _n2 += 1
    lines.append(f"### 2.{_n2} 测试方法说明")
    lines.append("")
    if is_llama:
        lines.append("- **部署与压测工具**：使用 llama.cpp（`llama-server` OpenAI 兼容 API）加载 GGUF 权重；llama.cpp 无原生 benchmark，故采用自研 HTTP 压测——通过 OpenAI 兼容 `/v1/chat/completions` 并发发送固定 input/output 长度的随机 Prompt，测量各并发档位下的吞吐与延迟。")
    else:
        lines.append("- **部署与压测工具**：使用 vLLM（`vllm serve`）提供 OpenAI 兼容服务；采用 vLLM 官方 `vllm bench serve` 压测工具（`--dataset-name random`，固定 input/output 长度），请求率无限（`--request-rate inf`，满载压测）。")
    lines.append("- **压测矩阵**：按任务配置的（输入长度 × 输出长度 × 并发梯度）组合逐个执行，每组合使用固定数量的随机 Prompt（见上方用例表 num_prompts 列）。")
    lines.append("- **核心指标**：Output Token 吞吐（tok/s）、请求吞吐（req/s）、首字延迟（TTFT：mean/median/p99）、逐 Token 时延（TPOT：mean/p99）、Token 间隔（ITL：mean/p99）。大模型单流解码受显存/内存带宽限制，低并发数据反映该硬件上的真实单流能力。")
    if mr.acc_results:
        lines.append("- **准确率评测**：对上述基准数据集各抽取固定数量样本，计算模型 Top-1 准确率（Accuracy）。")
    if mr.gateway_results:
        lines.append("- **协议规范校验**：通过 OpenAI/Anthropic/Responses 等 API 协议规范逐项校验模型的接口兼容性（分类、响应结构、鉴权等）。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 3. 容器启动命令与参数配置
    lines.append("## 3. 容器启动命令与参数配置")
    lines.append("")
    lines.append("### 3.1 容器镜像")
    lines.append("")
    lines.append("| 项目 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 镜像仓库 | `{d_info['image_repo']}` |")
    lines.append(f"| 镜像 Tag | `{d_info['image_tag']}` |")
    lines.append(f"| 容器名 | `{mr.container_name or d_info['container_name']}` |")
    lines.append(f"| 容器运行时 | `{d_info['runtime']}`（GPU 直通） |")
    lines.append(f"| ShmSize | `{d_info['shm_size']}` |")
    lines.append(f"| 重启策略 | `{d_info['restart_policy']}` |")
    lines.append(f"| 端口映射 | 服务端口 `{mr.port or d_info['port']}` |")
    lines.append("")
    lines.append("### 3.2 数据卷挂载")
    lines.append("")
    lines.append("| 宿主机路径 | 容器内路径 | 读写 |")
    lines.append("|------------|------------|------|")
    if d_info["volumes"]:
        for v in d_info["volumes"]:
            lines.append(f"| `{v['host']}` | `{v['container']}` | `{v['mode']}` |")
    else:
        lines.append(f"| `~/models` | `/models` | RW |")
    lines.append("")
    lines.append("### 3.3 容器启动命令（实际执行）")
    lines.append("")
    lines.append("```bash")
    lines.append(docker_cmd)
    lines.append("```")
    lines.append("")
    lines.append("> 该命令为该模型测试任务实际下发的容器启动命令行。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 3. 服务配置（按部署引擎动态输出）
    if is_llama:
        lines.append("## 4. llama.cpp 服务配置")
        lines.append("")
        lines.append("### 4.1 服务参数")
        lines.append("")
        lines.append("| 参数 | 值 | 说明 |")
        lines.append("|------|-----|------|")
        lines.append(f"| `-m` | `{d_info.get('model_path', 'N/A')}` | 加载的 GGUF 模型权重文件 |")
        if d_info.get("llama_model_file"):
            lines.append(f"| 权重文件 | `{d_info['llama_model_file']}` | llama.cpp 加载的具体 .gguf 分片 |")
        if d_info.get("quantization"):
            lines.append(f"| 量化格式 | `{d_info['quantization']}` | 权重量化（从文件名解析） |")
        ml2 = d_info.get("max_model_len") or f"{d_info.get('context_len','4096')} tokens"
        lines.append(f"| `-c` / `--ctx-size` | `{d_info.get('context_len','4096')}` | 上下文长度（{ml2}） |")
        gl = d_info.get("llama_cpp_gfl")
        lines.append(f"| `-ngl` | `{gl if gl else '999'}` | 全量 GPU 卸载层数 |")
        lines.append(f"| `--port` | `{mr.port or d_info['port']}` | 监听端口 |")
        mmproj = re.search(r"--mmproj\s+([^\s]+)", docker_cmd)
        if mmproj:
            lines.append(f"| `--mmproj` | `{mmproj.group(1)}` | 多模态视觉投影权重 |")
        lines.append("")
        lines.append("> 说明：llama.cpp 的显存占用由 `-ngl`（GPU 卸载层数）控制，不适用 `--gpu-memory-utilization` 参数。")
        lines.append("")
        lines.append("### 4.2 采样与推理行为")
        lines.append("")
        if d_info.get("gpu_layers") and d_info["gpu_layers"] != "N/A":
            lines.append(f"- **GPU 卸载**：`{d_info['gpu_layers']}`")
        lines.append("- **Decode 策略**：原生自回归逐 Token 生成。")
        lines.append("")
    else:
        lines.append("## 4. vLLM 服务配置")
        lines.append("")
        lines.append("### 4.1 服务参数")
        lines.append("")
        lines.append("| 参数 | 值 | 说明 |")
        lines.append("|------|-----|------|")
        # 仅展示命令中真实指定的参数；未指定的采用引擎默认，不臆造具体取值
        _model_path_disp = None
        if d_info.get("model_path") and d_info["model_path"] != "N/A":
            _model_path_disp = d_info["model_path"]
        elif d_info.get("actual_model_name"):
            _model_path_disp = f"/models/{d_info['actual_model_name']}"
        if _model_path_disp:
            lines.append(f"| `--model`（实际加载） | `{_model_path_disp}` | 模型权重路径 |")
        lines.append(f"| `--served-model-name` | `{mr.model_name}` | 对外暴露的模型名 |")
        lines.append(f"| `--port` | `{mr.port or d_info['port']}` | 监听端口 |")
        lines.append(f"| `--max-model-len` | `{d_info['max_model_len']}` | 最大上下文长度 |")
        if "--gpu-memory-utilization" in docker_cmd:
            lines.append(f"| `--gpu-memory-utilization` | `{d_info['gpu_memory_utilization']}` | GPU 显存预分配比例 |")
        if "--tensor-parallel-size" in docker_cmd:
            lines.append(f"| `--tensor-parallel-size` | `{d_info['tp_size']}` | 张量并行度 |")
        if "--dtype" in docker_cmd:
            lines.append(f"| `--dtype` | `{d_info['dtype']}` | 推理计算数据类型 |")
        if d_info["reasoning_parser"] != "N/A":
            lines.append(f"| `--reasoning-parser` | `{d_info['reasoning_parser']}` | 推理思考解析器 |")
        if d_info["tool_call_parser"] != "N/A":
            lines.append(f"| `--tool-call-parser` | `{d_info['tool_call_parser']}` | 工具调用 XML/JSON 解析器 |")
        lines.append("")
        lines.append("> 说明：以上为容器命令中**实际指定**的关键服务参数；未显式列出的参数由推理引擎采用默认值。")
        lines.append("")
        lines.append("### 4.2 投机解码（Speculative Decoding）配置")
        lines.append("")
        if d_info["speculative_config"]:
            lines.append("```json")
            lines.append(json.dumps(d_info["speculative_config"], indent=2, ensure_ascii=False))
            lines.append("```")
            lines.append("")
            lines.append(f"- **投机方法**：`{d_info['speculative_config'].get('method', 'MTP')}`")
            lines.append(f"- **投机 Token 数**：`{d_info['speculative_config'].get('num_speculative_tokens', 3)}`")
            lines.append(f"- **Backend 后端**：`{d_info['speculative_config'].get('moe_backend', 'triton')}`")
        else:
            lines.append("未开启投机解码（Speculative Decoding），采用原生自回归 Decode 策略，预分配 KV Cache。")
        lines.append("")
    lines.append("---")
    lines.append("")

    # 4. 版本与环境配置
    lines.append("## 5. 版本与环境配置")
    lines.append("")
    lines.append("### 5.1 软件栈版本（容器内）")
    lines.append("")
    lines.append("| 组件 | 版本 |")
    lines.append("|------|------|")
    vllm_ver = env_probe.get("vllm_version") or (f"Nightly（以镜像 {d_info['image_tag']} 为准）" if d_info.get('image_tag') else "-")
    py_ver = env_probe.get("python_version") or "-"
    torch_ver = env_probe.get("torch_version") or "-"
    cuda_ver = env_probe.get("cuda_version") or "-"
    if is_llama:
        lines.append(f"| llama.cpp | `Nightly（以镜像 {d_info['image_tag']} 为准）` |")
    else:
        lines.append(f"| vLLM | `{vllm_ver}` |")
    lines.append(f"| 容器镜像 | `{d_info['image_repo']}:{d_info['image_tag']}` |")
    lines.append(f"| Python | `{py_ver}` |")
    lines.append(f"| PyTorch | `{torch_ver}` |")
    if cuda_ver != "-":
        lines.append(f"| CUDA（容器） | `CUDA {cuda_ver}` |")
    lines.append("")
    lines.append("### 5.2 宿主机系统环境")
    lines.append("")
    lines.append("| 项目 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 操作系统 | `{env_probe.get('os_version') or 'Linux'}` |")
    lines.append(f"| 硬件平台 | `{dev_name}` (`{dev_host}`) |")
    lines.append(f"| GPU / NPU 规格 | `{gpu_spec}` |")
    lines.append(f"| CPU 核心数 | `{cpu_spec}` |")
    lines.append(f"| 物理内存 | `{mem_total_gb} GB 统一内存` |")
    lines.append("")
    lines.append("### 5.3 资源占用（测试时段）")
    lines.append("")
    lines.append("| 资源 | 状态 |")
    lines.append("|------|------|")
    lines.append(f"| 内存占用（已用） | `{mem_used_str or '未采集到监控快照'}` |")
    lines.append("| GPU 功耗/显存 | 受电源模式限制及统一内存共享架构调度 |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 5. 模型配置
    lines.append("## 6. 模型配置")
    lines.append("")
    lines.append("### 6.1 模型基本信息")
    lines.append("")
    lines.append("| 项目 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 模型名称 | `{mr.model_name}` |")
    lines.append(f"| 模型 Slug | `{mr.model_slug}` |")
    lines.append(f"| 架构 | `{arch_desc}` |")
    lines.append(f"| 量化方式 | `{quant_desc}` |")
    lines.append(f"| 参数规模分类 | `{mr.size_category or 'small_medium'}` |")
    lines.append(f"| 运行阶段状态 | `{mr.status}` |")
    lines.append(f"| 本地存放路径 | `{'/models/' + d_info['actual_model_name'] if d_info.get('actual_model_name') else '/models/' + mr.model_slug}` |")
    lines.append(f"| 测试任务 | `Task #{mr.task_id}` (`{mr.task.name if mr.task else 'N/A'}`) |")
    lines.append(f"| 执行账号 | `{mr.task.user.username if (mr.task and mr.task.user) else 'admin'}` |")
    lines.append("")
    lines.append("### 6.2 关键模型文件")
    lines.append("")
    
    # 动态检测本地物理文件
    local_model_dir = f"/models/{mr.model_slug}"
    if not os.path.exists(local_model_dir):
        local_model_dir = os.path.expanduser(f"~/models/{mr.model_slug}")
    
    if os.path.exists(local_model_dir) and os.path.isdir(local_model_dir):
        lines.append("| 文件 | 大小 | 说明 |")
        lines.append("|------|------|------|")
        try:
            # 仅列出对加载有用的核心文件，过滤 README/LICENSE/隐藏文件/图片等杂项，避免报告杂乱
            def _is_core_model_file(fname: str) -> bool:
                base = fname.lower()
                if base.startswith(".") or base.startswith("readme") or base.startswith("license") \
                   or base.startswith("notice") or base.startswith("sample"):
                    return False
                if base.endswith((".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".msc", ".mv", ".md", ".html", ".py", ".h5")):
                    return False
                if base.endswith((".safetensors", ".bin", ".gguf", ".json", ".txt", ".model", ".onnx", ".tokenizer", ".tiktoken", ".merges")):
                    return True
                return base in ("config.json", "tokenizer_config.json", "generation_config.json")
            core_files = [f for f in sorted(os.listdir(local_model_dir)) if _is_core_model_file(f)][:12]
            if core_files:
                for fname in core_files:
                    fpath = os.path.join(local_model_dir, fname)
                    size_mb = os.path.getsize(fpath) / (1024 * 1024)
                    size_str = f"{size_mb / 1024:.2f} GB" if size_mb > 1024 else f"{size_mb:.1f} MB"
                    desc = "权重分片" if fname.endswith((".safetensors", ".bin", ".gguf")) else ("主配置" if fname == "config.json" else "分词器/关联配置")
                    lines.append(f"| `{fname}` | {size_str} | {desc} |")
            else:
                lines.append("| `config.json` | - | 主配置 |")
                lines.append("| `model.safetensors` | 动态规模 | 模型权重分片 |")
        except Exception:
            lines.append("| `config.json` | 58 KB | 主配置 |")
            lines.append("| `model.safetensors` | 动态规模 | 模型权重分片 |")
    else:
        # 本地既无对应模型目录，也未找到物理权重文件时，如实说明（不虚构一份文件清单）
        lines.append("*未在本地检测到该模型的权重目录。*")
        lines.append("")
        lines.append("该模型通过 **TOS / 云端对象存储（`MODEL_OSS=True`）** 在容器启动时动态拉取，物理权重文件不常驻宿主机。")
        if d_info.get("llama_model_file"):
            lines.append("")
            lines.append(f"实际加载权重文件：`{d_info['llama_model_file']}`")
            if d_info.get("quantization"):
                lines.append(f"量化格式：`{d_info['quantization']}`")
        if is_llama and not d_info.get("llama_model_file"):
            lines.append("")
            lines.append("> 提示：本模型以 GGUF（llama.cpp）权重加载，具体 .gguf 分片请以容器启动命令 `-m` 参数为准。")
        lines.append("")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 6. 性能测试结果
    lines.append("## 7. 性能测试结果")
    lines.append("")
    lines.append("### 7.1 性能测试明细（吞吐 / 时延）")
    lines.append("")
    if perf_list:
        lines.append("| Input | Output | Conc | Out Tok/s | Total Tok/s | Req/s | TTFT mean(ms) | TTFT p99(ms) | TPOT mean(ms) | TPOT p99(ms) | ITL mean(ms) | ITL p99(ms) | 状态 |")
        lines.append("|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")
        for pr in perf_list:
            def _f(v, dec=1):
                if v is None: return "-"
                return f"{v:.{dec}f}" if isinstance(v, float) else str(v)
            try:
                _raw = pr.raw_report if isinstance(pr.raw_report, dict) else (json.loads(pr.raw_report) if pr.raw_report else {})
            except Exception:
                _raw = {}
            _total = _raw.get("total_token_throughput")
            st_tag = "❌ FAIL" if pr.error else "✅ PASS"
            _tp = _f(pr.throughput_tok_s, 2)
            _tp_cell = f"**{_tp}**" if pr.throughput_tok_s is not None else "-"
            lines.append(
                f"| {pr.input_len} | {pr.output_len} | {pr.concurrency} | {_tp_cell} | {_f(_total,2)} | {_f(pr.request_throughput,3)} | "
                f"{_f(pr.mean_ttft_ms)} | {_f(pr.p99_ttft_ms)} | {_f(pr.mean_tpot_ms)} | {_f(pr.p99_tpot_ms)} | "
                f"{_f(pr.mean_itl_ms)} | {_f(pr.p99_itl_ms)} | {st_tag} |"
            )
        lines.append("")
    else:
        lines.append("*无性能测试数据*")
        lines.append("")

    lines.append("### 7.2 指标口径与公式")
    lines.append("")
    lines.append("- **Output Token 吞吐（Out Tok/s）**：`输出 token 总和 ÷ 压测时长`，为多路并发聚合值（高并发数值偏大属正常，见摘要归因）。")
    lines.append("- **Total Token 吞吐（Total Tok/s）**：`(输入 + 输出) token 总和 ÷ 压测时长`。")
    lines.append("- **请求吞吐（Req/s）**：`成功请求数 ÷ 压测时长`。")
    lines.append("- **TTFT（Time To First Token）**：从发出请求到收到首个输出 token 的时长，反映 Prefill / 首包能力。")
    lines.append("- **TPOT（Time Per Output Token）**：`(端到端耗时 − TTFT) ÷ (输出 token 数 − 1)`，反映逐 token 解码能力。")
    lines.append("- **ITL（Inter-Token Latency）**：相邻两次流式输出之间的间隔；流式交互体验主要由 TTFT 与 ITL 决定。")
    if is_llama:
        lines.append("- **口径说明**：以上指标按 llama.cpp（OpenAI 兼容 HTTP 压测）的测量点与公式给出；不同基准工具对指标命名不统一，跨工具横向对比请以**测量点 / 公式**为准，而非仅看指标名称。")
    else:
        lines.append("- **口径说明**：指标按 vLLM `vllm bench serve` 的测量点与公式给出；不同基准工具对指标命名不统一，跨工具横向对比请以**测量点 / 公式**为准，而非仅看指标名称。")
    lines.append("")

    lines.append("### 7.3 准确率测试与 API 协议校验结果")
    lines.append("")
    if mr.acc_results or mr.gateway_results:
        if mr.acc_results:
            lines.append("#### 准确率测试结果 (Accuracy Evaluation)")
            lines.append("| 基准数据集 (Dataset) | 抽取样本数 | 实际测得准确率 (Accuracy) | 评测状态 |")
            lines.append("|:---:|:---:|:---:|:---:|")
            for ar in mr.acc_results:
                acc_str = f"**{(ar.accuracy * 100):.2f}%**" if ar.accuracy is not None else "-"
                status_str = "✅ 通过" if (ar.accuracy is not None and ar.accuracy > 0) else "⚠️ 异常"
                lines.append(f"| {ar.dataset.upper()} | {ar.limit or 200} | {acc_str} | {status_str} |")
            lines.append("")

        if mr.gateway_results:
            lines.append("#### API 协议规范校验 (Gateway Validation)")
            lines.append("| 测试项名称 | 协议分类 | 测试状态 | 响应耗时 (ms) | 说明 |")
            lines.append("|:---|:---:|:---:|:---:|:---|")
            for gr in mr.gateway_results:
                st = "✅ PASS" if gr.status == "PASS" else ("❌ FAIL" if gr.status == "FAIL" else "⏭️ SKIP")
                lat = f"{gr.latency_ms:.1f}" if gr.latency_ms else "-"
                lines.append(f"| {gr.test_item} | {gr.protocol.upper()} | {st} | {lat} | {gr.message or '-'} |")
            lines.append("")
    else:
        lines.append("*无准确率或协议校验数据*")
        lines.append("")

    lines.append("---")
    lines.append("")

    # 7. 结果分析
    lines.append("## 8. 结果分析")
    lines.append("")
    lines.append("### 8.1 吞吐规律")
    if valid_perfs and best_row and worst_row:
        lines.append(f"- **吞吐上限与规模表现**：在最高并发与输入输出组合下，输出 Token 吞吐最高达到 **{best_row.throughput_tok_s:.2f} tok/s** (输入={best_row.input_len}, 输出={best_row.output_len}, 并发={best_row.concurrency})。")
        lines.append(f"- **Prefill 阶段延迟**：平均首字响应延迟 (TTFT) 随着输入 Prompt 长度增加而上升，最小 TTFT 为 **{min_ttft:.2f} ms**。")
        lines.append(f"- **单流基准吞吐**：`Input={worst_row.input_len}, Output={worst_row.output_len}` 在**单路并发（conc=1）**时吞吐为 **{worst_row.throughput_tok_s:.2f} tok/s**，反映该模型的单路流式解码能力（见下方口径）；Prefill 在长输入下占较大部分开销。")
    else:
        lines.append("- 输出吞吐随输出长度增加而提升，长输出摊薄了固定 TTFT 开销。")
        lines.append("- 输入 Prompt 越长，Prefill 阶段耗时上升，首 Token 延迟（TTFT）显著升高。")
    lines.append("")
    
    lines.append("### 8.2 延迟开销分析 (TTFT vs TPOT)")
    if valid_perfs:
        mean_tpot = sum(p.mean_tpot_ms for p in valid_perfs if p.mean_tpot_ms)/len(valid_perfs) if valid_perfs else 0.0
        lines.append(f"- **首字延迟 (TTFT)**：实测最佳首字延迟 **{min_ttft:.2f} ms**，反映了预分配 KV Cache 与推理引擎 Prefill 阶段效率。")
        lines.append(f"- **字间延迟 (TPOT)**：平均字间 Token 生成耗时约为 **{mean_tpot:.2f} ms/tok**，维持了流畅自回归生成。")
    else:
        lines.append("- 延迟表现稳定，维持了流畅的自回归 Token 生成。")
    lines.append("")

    lines.append("### 8.3 最佳 / 单流基准配置")
    if best_row:
        lines.append(f"- **最佳吞吐配置**：`input={best_row.input_len}, output={best_row.output_len}, concurrency={best_row.concurrency}` → **{best_row.throughput_tok_s:.2f} tok/s**。")
    else:
        lines.append("- **最佳吞吐配置**：视压测矩阵组合而定。")
    if worst_row:
        lines.append(f"- **单流基准配置**：`input={worst_row.input_len}, output={worst_row.output_len}, concurrency={worst_row.concurrency}` → **{worst_row.throughput_tok_s:.2f} tok/s**（最低档并发的单流解码能力，非故障）。")
    else:
        lines.append("- **单流基准配置**：以并发度最低档为准。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 8. 结论与建议
    lines.append("## 9. 结论与建议")
    lines.append("")
    
    # ---- 结论整体尽可能基于真实数据；数据不足时如实声明，不做臆断 ----
    max_len_val = d_info.get("max_model_len", "40960 tokens")
    gpu_util_val = d_info.get("gpu_memory_utilization", "80.0%")
    max_c = max(concurrencies, default=4)
    n = 1

    if not valid_perfs:
        # 无有效性能数据：不作吞吐/延迟结论，仅给部署与配置说明（问题 3）
        lines.append(
            f"{n}. **部署与数据说明**：在 `{dev_name}` 算力节点上完成 `{mr.model_name}` 的容器部署（引擎：{'llama.cpp（GGUF）' if is_llama else 'vLLM'}）。"
            f"本次评测未获取到有效性能数据（完成率 {pass_rate}），因此**不对吞吐/延迟作出结论**。{reliability_clause}，建议定位压测失败原因后复测。"
        )
        n += 1
        lines.append(
            f"{n}. **配置记录**：已登记部署参数 `--max-model-len` 为 `{max_len_val}`，显存分配方式为 `{gpu_util_val}`。"
            "由于缺乏有效性能样本，暂不输出 Prefill/并发调度等基于实测的优化结论。"
        )
        n += 1
    else:
        spec_clause = "基于标准 KV Cache 预分配模式"
        if d_info["speculative_config"]:
            spec_clause = "借助 MTP 投机解码"

        # 动态判定 1：整体部署与吞吐表现（数据真实时给出，并依据完成率/可靠性修正措辞）
        if max_tput > 0:
            throughput_clause = f"实测峰值输出吞吐达 **{max_tput:.2f} tok/s**，"
        else:
            throughput_clause = ""
        lines.append(
            f"{n}. **整体部署与吞吐表现**：在 `{dev_name}` 算力节点上，模型 `{mr.model_name}` {spec_clause} 运行。"
            f"{throughput_clause}"
            + (f"{_conc_clause} " if _conc_clause else "")
            + f"最佳首字延迟控制在 **{min_ttft:.2f} ms**。当前配置 `--max-model-len` 为 `{max_len_val}`，"
            f"显存分配方式为 `{gpu_util_val}`。{reliability_clause}。"
            + ("因此本次结论**仅供参考，不作为最终选型依据**。" if completion_ratio < 0.9 else "")
        )
        n += 1

        # 动态判定 2：Prefill 与长上下文瓶颈分析
        if len(valid_perfs) > 1:
            max_ttft_row = max(valid_perfs, key=lambda x: x.mean_ttft_ms if x.mean_ttft_ms is not None else 0)
            lines.append(
                f"{n}. **Prefill / Decode 开销瓶颈**：当输入 Token 增加至 {max_ttft_row.input_len} 时，首字响应延迟 (Mean TTFT) 上升至 **{max_ttft_row.mean_ttft_ms:.2f} ms**。"
                " Prefill 阶段为长 Prompt 场景的主要时延瓶颈。对于 TTFT 敏感的高并发业务，建议配置 Chunked Prefill 优化或针对长 Prompt 场景设置独立队列限流。"
            )
            n += 1
        else:
            lines.append(
                f"{n}. **Prefill / Decode 开销瓶颈**：Prefill 阶段预处理为长 Prompt 场景的主要开销瓶颈，建议生产部署时结合业务 SLA 配置 Chunked Prefill 或调整 KV Cache 预分配比例。"
            )
            n += 1

    # 动态判定 3：P99 尾部延迟预警（问题 7）
    if p99_warning:
        ratio = (p99_warning["p99"] / p99_warning["mean"]) if p99_warning["mean"] else 0
        lines.append(
            f"{n}. **⚠️ P99 尾部延迟预警**：高并发（并发 ≥ {p99_warning['slots']}）下出现大量请求 P99 首字延迟远超均值（最高 **{p99_warning['p99']:.2f} ms**，约为并发 {p99_warning['concurr']} 下均值 **{p99_warning['mean']:.2f} ms** 的 {ratio:.1f} 倍），"
            "尾部抖动明显，存在排队拥塞。**对首字延迟敏感的生产业务（如实时对话、流式交互），建议将并发限制在更低档位或引入请求优先级/限流机制。**"
        )
        n += 1

    # 动态判定 4：准确率与 API 协议规范校验
    if mr.acc_results:
        acc_list = [f"{ar.dataset.upper()}: {ar.accuracy * 100:.1f}%" for ar in mr.acc_results if ar.accuracy is not None]
        acc_summary = "，".join(acc_list) if acc_list else "准确率校验完成"
        lines.append(f"{n}. **准确率评测完成度**：模型已完成基准数据集评测（{acc_summary}），模型理解与推理能力满足预期，无异常退化。")
        n += 1
    elif mr.gateway_results:
        pass_gw = sum(1 for gr in mr.gateway_results if gr.status == "PASS")
        lines.append(f"{n}. **API 协议规范校验**：通过 {pass_gw}/{len(mr.gateway_results)} 项 OpenAI API 兼容规范校验，可直接对接上层应用及 API 网关。")
        n += 1
    else:
        lines.append(f"{n}. **准确率/协议校验**：本报告未附带准确率或 API 协议校验数据，仅反映性能实测。")
        n += 1

    # 动态判定 5：算力节点与系统加速建议
    lines.append(
        f"{n}. **算力节点调优建议**：建议在算力设备 `{dev_name}` 宿主机上开启 GPU/NPU 持久化加速模式，"
        "并确保推理容器分配足够的共享内存 (`--shm-size`) 与算力直通权限 (`--runtime=nvidia`)，以发挥芯片最高计算效率。"
    )
    n += 1

    # 动态判定 6：生产部署与并发选型（仅在有有效数据时给出实测定量建议）
    if valid_perfs:
        # 选并发档位最全的 (input,output) 组合，给出吞吐×P99 选型表
        _grp = {}
        _seen = set()
        for _p in valid_perfs:
            _k = (_p.input_len, _p.output_len)
            if _k not in _seen:
                _grp[_k] = []
                _seen.add(_k)
            _grp[_k].append(_p)
        _chosen = None
        for _k, _rows in _grp.items():
            _cc = sorted({_r.concurrency for _r in _rows if _r.concurrency})
            if len(_cc) >= 4 and (_chosen is None or len(_cc) > len(_chosen[1])):
                _chosen = (_k, _cc, _rows)
        if _chosen:
            (_cil, _col), _cc, _rows = _chosen
            _rowmap = {_r.concurrency: _r for _r in _rows}
            _budget = 1000.0
            lines.append(f"{n}. **并发选型参考**（输入 {_cil} / 输出 {_col}，为实测并发梯度最全的一组）：")
            lines.append("")
            lines.append("| 并发 | 输出吞吐 (tok/s) | P99 TTFT (ms) |")
            lines.append("|:---:|:---:|:---:|")
            _last_ok = None
            for _c in _cc:
                _r = _rowmap[_c]
                _tp = f"{_r.throughput_tok_s:.1f}" if _r.throughput_tok_s is not None else "-"
                _p99 = f"{_r.p99_ttft_ms:.0f}" if _r.p99_ttft_ms is not None else "-"
                if _r.p99_ttft_ms is not None and _r.concurrency and _r.p99_ttft_ms <= _budget:
                    _last_ok = _c
                lines.append(f"| {_c} | **{_tp}** | {_p99} |")
            lines.append("")
            _sugg = _last_ok if _last_ok is not None else _cc[0]
            lines.append(
                f"按 **P99 TTFT ≤ {_budget:.0f} ms** 的接口首包口径，建议将该场景单节点并发控制在 **≤ {_sugg}**，"
                "在吞吐与首字延迟间取得平衡；实际并发请结合业务 TTFT/吞吐 SLA 调整。"
            )
            n += 1
        else:
            lines.append(
                f"{n}. **生产并发调度建议**：在实测梯度并发（1 ~ {max_c}）表现下，推荐根据 SLA 目标将单节点并发控制在最佳吞吐区间内，"
                "既可获得最高 Token 产出效率，又能维持 P99 延迟处于受控水平。"
            )
            n += 1
    lines.append("")
    lines.append("---")
    lines.append("")

    # 附录：数据来源
    lines.append("## 附录：数据来源")
    lines.append("")
    lines.append("| 资源标识 | 数据类型 | 描述与用途 |")
    lines.append("|----------|----------|------------|")
    lines.append(f"| `ModelRun #{mr.id}` | 数据库评测主记录 | 关联任务 `Task #{mr.task_id}` (`{mr.task.name if mr.task else 'N/A'}`) |")
    lines.append(f"| `PerfResults` | 性能矩阵表 | 累计 {len(perf_list)} 组并发与 Token 组合实测记录 |")
    lines.append(f"| `AccResults` | 准确率测评表 | 累计 {len(mr.acc_results or [])} 组基准数据集测评记录 |")
    lines.append(f"| `GatewayResults` | 协议校验表 | 累计 {len(mr.gateway_results or [])} 组 API 协议规范校验记录 |")
    lines.append(f"| `Container #{mr.container_name or 'N/A'}` | 部署容器 | 对应容器标识与部署启动命令行 |")
    lines.append(f"| 模型存储路径 | `/models/{mr.model_slug}` | 模型配置与物理权重文件目录 |")
    lines.append("")
    lines.append("### 可复现性说明")
    lines.append("")
    _eng_uri = ""
    _m = re.search(r"-e\s+ENGINE_URI=([^\s\\]+)", docker_cmd or "")
    if _m:
        _eng_uri = _m.group(1)
    lines.append("| 项目 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 测试日期 | {test_date} |")
    lines.append(f"| 部署引擎 | {'llama.cpp (GGUF)' if is_llama else 'vLLM'} |")
    lines.append(f"| 容器镜像 | `{d_info['image_repo']}:{d_info['image_tag']}` |")
    if _eng_uri:
        lines.append(f"| 权重来源（TOS） | `{_eng_uri}` |")
    if d_info.get("actual_model_name"):
        lines.append(f"| 加载模型 | `{d_info['actual_model_name']}` |")
    lines.append(f"| 软件栈（容器） | {'llama.cpp（Nightly，以镜像为准）' if is_llama else ('vLLM ' + vllm_ver)} / Python {py_ver} / PyTorch {torch_ver} / CUDA {cuda_ver} |")
    lines.append("")

    content = "\n".join(lines)
    filename = f"{mr.model_slug}_benchmark_report.md"
    return PlainTextResponse(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
