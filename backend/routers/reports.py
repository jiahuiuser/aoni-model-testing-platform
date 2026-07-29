"""
报告 API 路由 (同步版)
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
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


@router.get("/{model_run_id}/download")
def api_download_report(
    model_run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """下载单模型权威测试报告为 Markdown 规范文件"""
    mr = db.get(ModelRun, model_run_id)
    if not mr:
        raise HTTPException(404, "报告不存在")
    check_report_access(mr, current_user)

    dev = mr.device
    dev_name = mr.device_name or (dev.name if dev else "NVIDIA AGX Thor (本机)")
    dev_host = dev.host if dev else "127.0.0.1"
    gpu_spec = (dev.gpu_info if dev and dev.gpu_info else "NVIDIA AGX Thor (Blackwell Tensor Cores / 64GB LPDDR5X)")
    cpu_spec = f"{dev.cpu_cores if (dev and dev.cpu_cores) else 12} Cores ARM"
    mem_spec = f"{dev.memory_gb if (dev and dev.memory_gb) else 64.0} GB 统一显存"
    docker_cmd = mr.docker_command or "vllm serve --port 8300 --max-model-len 4096 --gpu-memory-utilization 0.85"

    lines = []
    lines.append(f"# {mr.model_name} 基准性能与准确率测试报告")
    lines.append("")
    lines.append("> 本报告由 **AONI 模型测试平台** 自动测试生成，测试数据源自硬件实测。")
    lines.append("")

    # 1. 基础元数据与硬件环境
    lines.append("## 1. 测试环境与硬件规格")
    lines.append("")
    lines.append(f"- **目标算力节点**: `{dev_name}` (`{dev_host}`)")
    lines.append(f"- **GPU / NPU 硬件规格**: `{gpu_spec}`")
    lines.append(f"- **CPU & 物理内存**: `{cpu_spec}` / `{mem_spec}`")
    lines.append(f"- **测试任务 ID**: `Task #{mr.task_id}` (`{mr.task.name if mr.task else '自动评测'}`)")
    lines.append(f"- **测试执行账号**: `{mr.task.user.username if (mr.task and mr.task.user) else 'admin'}`")
    lines.append(f"- **测试发起时间**: `{mr.started_at or 'N/A'}`")
    lines.append(f"- **测试完成时间**: `{mr.completed_at or 'N/A'}`")
    lines.append("")

    # 2. 推理引擎配置
    engine_params = parse_docker_env_params(docker_cmd)
    lines.append("## 2. 推理引擎与模型启动参数 (Engine & Startup Parameters)")
    lines.append("")
    lines.append("| 参数名称 (Parameter) | 配置值 (Configured Value) | 说明 |")
    lines.append("|:---|:---|:---|")
    lines.append(f"| **模型标识 (Model Slug)** | `{mr.model_slug}` | 模型注册 ID |")
    lines.append(f"| **模型规模 (Size Category)** | `{mr.size_category or 'small_medium'}` | 参数量级 |")
    lines.append(f"| **最大上下文长度 (Max Model Len)** | `{engine_params['max_model_len']}` | 单次推理最大 Token 上下文限制 |")
    lines.append(f"| **GPU 显存利用率 (GPU Utilization)** | `{engine_params['gpu_memory_utilization']}` | vLLM/推理引擎预分配 KV Cache 显存比例 |")
    lines.append(f"| **GPU 卸载图层 (GPU Layers)** | `{engine_params['gpu_layers']}` | 算力卡卸载图层数 |")
    lines.append("")
    lines.append("**容器部署完整启动命令**: ")
    lines.append("```bash")
    lines.append(docker_cmd)
    lines.append("```")
    lines.append("")

    # 3. 性能测试结果
    lines.append("## 3. 性能测试结果矩阵 (Throughput & Latency)")
    lines.append("")
    if mr.perf_results:
        lines.append("| 测试轮次 | 并发数 | 输入 Token | 输出 Token | 吞吐量 (tok/s) | 请求吞吐 (req/s) | 首字延迟 TTFT 均值 (ms) | P99 TTFT (ms) | 字间延迟 TPOT 均值 (ms) | P99 TPOT (ms) |")
        lines.append("|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")
        for pr in mr.perf_results:
            def _f(v):
                if v is None: return "-"
                return f"{v:.1f}" if isinstance(v, float) else str(v)
            lines.append(
                f"| 第 {pr.round_num} 轮 | {pr.concurrency} | {pr.input_len} | {pr.output_len} | **{_f(pr.throughput_tok_s)}** | "
                f"{_f(pr.request_throughput)} | {_f(pr.mean_ttft_ms)} | {_f(pr.p99_ttft_ms)} | "
                f"{_f(pr.mean_tpot_ms)} | {_f(pr.p99_tpot_ms)} |"
            )
        lines.append("")
    else:
        lines.append("*无性能测试数据*")
        lines.append("")

    # 4. 准确率测试
    lines.append("## 4. 准确率测试结果 (Accuracy Evaluation)")
    lines.append("")
    if mr.acc_results:
        lines.append("| 基准数据集 (Dataset) | 抽取样本数 | 实际测得准确率 (Accuracy) | 评测状态 |")
        lines.append("|:---:|:---:|:---:|:---:|")
        for ar in mr.acc_results:
            acc_str = f"**{(ar.accuracy * 100):.2f}%**" if ar.accuracy is not None else "-"
            status_str = "✅ 通过" if (ar.accuracy is not None and ar.accuracy > 0) else "⚠️ 异常"
            lines.append(f"| {ar.dataset.upper()} | {ar.limit or 200} | {acc_str} | {status_str} |")
        lines.append("")
    else:
        lines.append("*无准确率测试数据*")
        lines.append("")

    # 5. 结论与说明
    lines.append("## 5. 测试环境与数据说明")
    lines.append("")
    lines.append("- **测试引擎**: AONI System v2.5 Standard Benchmarking Suite")
    lines.append("- **数据来源**: 真实 HTTP/vLLM 异步并发套件实测数据")
    lines.append("")

    content = "\n".join(lines)
    filename = f"{mr.model_slug}_authoritative_report.md"
    return PlainTextResponse(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
