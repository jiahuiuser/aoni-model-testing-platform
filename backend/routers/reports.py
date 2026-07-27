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
            "status": mr.status.value if mr.status else "unknown",
            "perf_results_count": len(mr.perf_results or []),
            "acc_results_count": len(mr.acc_results or []),
            "started_at": (mr.started_at.isoformat() + "Z") if mr.started_at else None,
            "completed_at": (mr.completed_at.isoformat() + "Z") if mr.completed_at else None,
        })
    return data


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

    return {
        "id": mr.id, "task_id": mr.task_id,
        "model_name": mr.model_name, "model_slug": mr.model_slug,
        "model_idx": mr.model_idx,
        "status": mr.status.value if mr.status else "unknown",
        "started_at": mr.started_at.isoformat() if mr.started_at else None,
        "completed_at": mr.completed_at.isoformat() if mr.completed_at else None,
        "perf_results": perf_data, "acc_results": acc_data,
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


@router.get("/{model_run_id}/download")
def api_download_report(
    model_run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """下载单模型测试报告为 .md 文件"""
    mr = db.get(ModelRun, model_run_id)
    if not mr:
        raise HTTPException(404, "报告不存在")
    check_report_access(mr, current_user)

    lines = []
    lines.append(f"# {mr.model_name} 模型测试报告")
    lines.append("")
    lines.append(f"- **模型索引**: #{mr.model_idx}")
    lines.append(f"- **模型 slug**: `{mr.model_slug}`")
    lines.append(f"- **参数量级**: `{mr.size_category or 'unknown'}`")
    lines.append("")

    # 性能测试
    lines.append("## 1. 性能测试结果")
    lines.append("")
    if mr.perf_results:
        lines.append("| 并发 | 输入 | 输出 | 吞吐(tok/s) | 请求吞吐(req/s) | TTFT均值(ms) | P99 TTFT(ms) | TPOT均值(ms) | P99 TPOT(ms) | ITL均值(ms) |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for pr in mr.perf_results:
            def _f(v):
                if v is None: return "-"
                return f"{v:.1f}" if isinstance(v, float) else str(v)
            lines.append(
                f"| {pr.concurrency} | {pr.input_len} | {pr.output_len} | {_f(pr.throughput_tok_s)} | "
                f"{_f(pr.request_throughput)} | {_f(pr.mean_ttft_ms)} | {_f(pr.p99_ttft_ms)} | "
                f"{_f(pr.mean_tpot_ms)} | {_f(pr.p99_tpot_ms)} | {_f(pr.mean_itl_ms)} |"
            )
        lines.append("")

        # 如果有 raw_report，展示 vLLM bench 的详细百分位数据
        for pr in mr.perf_results:
            raw = pr.raw_report
            if raw and isinstance(raw, dict):
                lines.append(f"### 并发={pr.concurrency}, 输出={pr.output_len} 详细指标")
                lines.append("")
                # 提取百分位延迟
                ttft_percentiles = raw.get("ttft_percentiles") or raw.get("ttft_percentile_intervals") or []
                tpot_percentiles = raw.get("tpot_percentiles") or raw.get("tpot_percentile_intervals") or []
                itl_percentiles = raw.get("itl_percentiles") or raw.get("itl_percentile_intervals") or []
                e2e_percentiles = raw.get("e2e_latency_percentiles") or []

                if ttft_percentiles or tpot_percentiles:
                    lines.append("| 指标 | P50 | P75 | P90 | P95 | P99 |")
                    lines.append("|---|---|---|---|---|---|")
                    for label, data in [("TTFT", ttft_percentiles), ("TPOT", tpot_percentiles), ("ITL", itl_percentiles), ("E2E Latency", e2e_percentiles)]:
                        if data:
                            vals = [f"{v:.1f}" for v in data[:5]] if isinstance(data, list) else []
                            if vals:
                                while len(vals) < 5: vals.append("-")
                                lines.append(f"| {label} | {' | '.join(vals)} |")
                    lines.append("")

                # 其他关键指标
                extra = {k: v for k, v in raw.items()
                         if k not in ("ttft_percentiles", "tpot_percentiles", "itl_percentiles",
                                      "e2e_latency_percentiles", "ttft_percentile_intervals",
                                      "tpot_percentile_intervals", "itl_percentile_intervals")
                         and not isinstance(v, (list, dict))}
                if extra:
                    lines.append("**其他指标**:")
                    lines.append("")
                    for k, v in sorted(extra.items()):
                        if isinstance(v, float):
                            lines.append(f"- **{k}**: {v:.2f}")
                    lines.append("")
    else:
        lines.append("*无性能测试数据*")
        lines.append("")

    # 准确率测试
    lines.append("## 2. 准确率测试结果")
    lines.append("")
    if mr.acc_results:
        lines.append("| 数据集 | 准确率 |")
        lines.append("|---|---|")
        for ar in mr.acc_results:
            acc_str = f"{ar.accuracy:.2%}" if ar.accuracy is not None else "-"
            lines.append(f"| {ar.dataset} | {acc_str} |")
        lines.append("")
    else:
        lines.append("*无准确率测试数据*")
        lines.append("")

    lines.append(f"*报告生成时间: {mr.completed_at or mr.started_at or 'N/A'}*")
    lines.append("")

    content = "\n".join(lines)
    filename = f"{mr.model_slug}_report.md"
    return PlainTextResponse(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
