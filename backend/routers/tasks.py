"""
任务 API 路由 + WebSocket (同步版)
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session, selectinload

from backend.database import get_db
from backend.models import Task, ModelRun, TaskLog, TaskStatus
from backend.schemas import (
    TaskCreate, TaskOut, TaskDetailOut, TaskLogOut, TaskAction, ModelRunOut,
    PerfResultOut, AccResultOut,
)
from backend.services.task_manager import create_task, start_task, pause_task, resume_task, cancel_task

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", response_model=TaskOut)
def api_create_task(data: TaskCreate, db: Session = Depends(get_db)):
    task = create_task(db, data)
    # 后台启动
    import threading
    t = threading.Thread(target=start_task, args=(task.id,), daemon=True)
    t.start()
    return _task_to_out(task)


@router.get("", response_model=list[TaskOut])
def api_list_tasks(db: Session = Depends(get_db)):
    tasks = db.execute(select(Task).order_by(desc(Task.created_at)).limit(50)).scalars().all()
    return [_task_to_out(t) for t in tasks]


@router.get("/{task_id}", response_model=TaskDetailOut)
def api_get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return _task_to_detail(task)


@router.post("/{task_id}/action")
def api_task_action(task_id: int, action: TaskAction, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")

    if action.action == "pause":
        pause_task(db, task_id)
    elif action.action == "resume":
        resume_task(task_id)
    elif action.action == "cancel":
        cancel_task(db, task_id)
    else:
        raise HTTPException(400, f"未知操作: {action.action}")

    return {"status": "ok", "action": action.action}


@router.delete("/{task_id}")
def api_delete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status in (TaskStatus.RUNNING, TaskStatus.PAUSED):
        cancel_task(db, task_id)
    db.delete(task)
    db.commit()
    return {"status": "deleted"}


@router.get("/{task_id}/logs", response_model=list[TaskLogOut])
def api_get_logs(task_id: int, model_slug: Optional[str] = None, limit: int = 200, db: Session = Depends(get_db)):
    query = select(TaskLog).where(TaskLog.task_id == task_id)
    if model_slug:
        query = query.where(TaskLog.model_slug == model_slug)
    query = query.order_by(desc(TaskLog.id)).limit(limit)
    return db.execute(query).scalars().all()


# ---------- 辅助函数 ----------

def _task_to_out(t: Task) -> TaskOut:
    completed = sum(1 for m in (t.model_runs or []) if m.status and m.status.value == "done")
    return TaskOut(
        id=t.id, name=t.name, status=t.status.value, profile=t.profile,
        device_id=t.device_id, device_name=t.device.name if t.device else None,
        config=t.config, created_at=t.created_at, started_at=t.started_at,
        completed_at=t.completed_at, model_count=len(t.model_runs or []),
        completed_count=completed,
    )


def _task_to_detail(t: Task) -> TaskDetailOut:
    basic = _task_to_out(t)
    runs = []
    for mr in (t.model_runs or []):
        perf_out = []
        for pr in (mr.perf_results or []):
            perf_out.append(PerfResultOut(
                id=pr.id, round_num=pr.round_num, strategy_id=pr.strategy_id or "",
                output_type=pr.output_type or "", concurrency=pr.concurrency or 0,
                input_len=pr.input_len or 0, output_len=pr.output_len or 0,
                throughput_tok_s=pr.throughput_tok_s, mean_ttft_ms=pr.mean_ttft_ms,
                p99_ttft_ms=pr.p99_ttft_ms, mean_tpot_ms=pr.mean_tpot_ms,
                p99_tpot_ms=pr.p99_tpot_ms, raw_report=pr.raw_report, error=pr.error,
            ))
        acc_out = []
        for ar in (mr.acc_results or []):
            acc_out.append(AccResultOut(
                id=ar.id, dataset=ar.dataset or "", accuracy=ar.accuracy, error=ar.error,
            ))
        runs.append(ModelRunOut(
            id=mr.id, model_idx=mr.model_idx, model_name=mr.model_name,
            model_slug=mr.model_slug, status=mr.status.value if mr.status else "unknown",
            device_id=mr.device_id, device_name=mr.device_name,
            progress=mr.progress, progress_detail=mr.progress_detail,
            started_at=mr.started_at, completed_at=mr.completed_at,
            perf_results=perf_out, acc_results=acc_out,
        ))
    return TaskDetailOut(
        id=basic.id, name=basic.name, status=basic.status, profile=basic.profile,
        device_id=basic.device_id, device_name=basic.device_name,
        config=basic.config, created_at=basic.created_at, started_at=basic.started_at,
        completed_at=basic.completed_at, model_count=basic.model_count,
        completed_count=basic.completed_count, model_runs=runs,
    )
