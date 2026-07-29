"""
任务 API 路由 + WebSocket (同步版)
"""
from typing import Optional
from pydantic import BaseModel
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session, selectinload

from backend.database import get_db
from backend.models import Task, ModelRun, TaskLog, TaskStatus
from backend.schemas import (
    TaskCreate, TaskOut, TaskDetailOut, TaskLogOut, TaskAction, ModelRunOut,
    PerfResultOut, AccResultOut, GatewayResultOut,
)
from backend.services.task_manager import create_task, start_task, pause_task, resume_task, cancel_task

from backend.auth import get_current_user
from backend.models.user import User

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def check_task_access(task: Task, user: User):
    if user.role != "admin" and task.user_id is not None and task.user_id != user.id:
        raise HTTPException(403, "权限拒绝：您无权访问或操作其他用户的测试任务")


@router.post("", response_model=TaskOut)
def api_create_task(
    data: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    import threading

    device_list = data.device_ids if data.device_ids else ([data.device_id] if data.device_id else [None])
    created_tasks = []

    for dev_id in device_list:
        sub_data = TaskCreate(
            name=f"{data.name}" + (f" (Device #{dev_id})" if len(device_list) > 1 else ""),
            profile=data.profile,
            device_id=dev_id,
            template_id=data.template_id,
            config=data.config
        )
        try:
            task = create_task(db, sub_data, user_id=current_user.id)
            created_tasks.append(task)
            # 后台异步启动
            t = threading.Thread(target=start_task, args=(task.id,), daemon=True)
            t.start()
        except ValueError as e:
            if not created_tasks:
                raise HTTPException(400, detail=str(e))

    return _task_to_out(created_tasks[0])


from sqlalchemy import select, func, desc, asc

@router.get("", response_model=list[TaskOut])
def api_list_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(Task).order_by(desc(Task.id)).limit(200)
    # 多用户数据隔离：普通用户只能查看自己的测试任务；管理员 (admin) 可查阅全量数据
    if current_user.role != "admin":
        query = query.where(Task.user_id == current_user.id)
    tasks = db.execute(query).scalars().all()
    return [_task_to_out(t) for t in tasks]


@router.get("/{task_id}", response_model=TaskDetailOut)
def api_get_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    check_task_access(task, current_user)
    return _task_to_detail(task)


@router.post("/{task_id}/action")
def api_task_action(
    task_id: int,
    action: TaskAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    check_task_access(task, current_user)

    if action.action == "pause":
        pause_task(db, task_id)
    elif action.action == "resume":
        resume_task(task_id)
    elif action.action == "cancel":
        cancel_task(db, task_id)
    elif action.action in ("rerun", "restart"):
        from backend.services.task_manager import restart_task
        restart_task(db, task_id)
    else:
        raise HTTPException(400, f"未知操作: {action.action}")

    return {"status": "ok", "action": action.action}


class TaskUpdate(BaseModel):
    name: Optional[str] = None
    profile: Optional[str] = None
    device_id: Optional[int] = None
    config: Optional[dict] = None


@router.patch("/{task_id}", response_model=TaskOut)
def api_update_task(
    task_id: int,
    data: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """编辑任务基本信息与配置（仅允许编辑未运行 / 已完成 / 已取消的任务）"""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    check_task_access(task, current_user)
    if task.status == TaskStatus.RUNNING:
        raise HTTPException(400, "任务正在运行中，无法编辑。请先暂停或等待任务完成。")
    if data.name is not None:
        task.name = data.name
    if data.profile is not None:
        task.profile = data.profile
    if data.device_id is not None:
        task.device_id = data.device_id
    if data.config is not None:
        task.config = data.config
    db.commit()
    db.refresh(task)
    return _task_to_out(task)


@router.delete("/{task_id}")
def api_delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    check_task_access(task, current_user)
    
    # 删除任务时，强行停止并删除该任务关联的所有 Docker 测试容器
    from backend.services.executor import stop_task_containers
    stop_task_containers(task)

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

def _get_status_str(val):
    if not val:
        return "unknown"
    return val.value if hasattr(val, "value") else str(val)


def _task_to_out(t: Task) -> TaskOut:
    model_runs = t.model_runs or []
    completed = sum(1 for m in model_runs if _get_status_str(m.status) in ("done", "completed"))
    status_str = _get_status_str(t.status)

    # 【自愈状态校准】：如果所有 ModelRun 均已 DONE/100%，但父 Task 状态仍停留在 RUNNING/PAUSED，自动校准为 COMPLETED
    if len(model_runs) > 0 and completed == len(model_runs) and status_str in ("running", "paused"):
        t.status = "completed"
        status_str = "completed"
        if not t.completed_at:
            t.completed_at = datetime.utcnow()
        try:
            from backend.database import session_factory
            with session_factory() as s:
                db_t = s.get(Task, t.id)
                if db_t:
                    db_t.status = "completed"
                    if not db_t.completed_at:
                        db_t.completed_at = datetime.utcnow()
                    s.commit()
        except Exception:
            pass

    return TaskOut(
        id=t.id, name=t.name, status=status_str, profile=t.profile,
        user_id=t.user_id, username=t.user.username if t.user else None,
        device_id=t.device_id, device_name=t.device.name if t.device else None,
        config=t.config, created_at=t.created_at, started_at=t.started_at,
        completed_at=t.completed_at, model_count=len(model_runs),
        completed_count=completed,
    )


def _task_to_detail(t: Task) -> TaskDetailOut:
    basic = _task_to_out(t)
    runs = []
    for mr in (t.model_runs or []):
        gw_out = []
        for gr in (mr.gateway_results or []):
            gw_out.append(GatewayResultOut(
                id=gr.id, category=gr.category or "protocol", test_item=gr.test_item or "",
                protocol=gr.protocol or "system", status=gr.status or "SKIP",
                latency_ms=gr.latency_ms, message=gr.message, raw_details=gr.raw_details,
            ))
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
            model_slug=mr.model_slug, status=_get_status_str(mr.status),
            device_id=mr.device_id, device_name=mr.device_name,
            progress=mr.progress, progress_detail=mr.progress_detail,
            started_at=mr.started_at, completed_at=mr.completed_at,
            gateway_results=gw_out, perf_results=perf_out, acc_results=acc_out,
        ))
    return TaskDetailOut(
        id=basic.id, name=basic.name, status=basic.status, profile=basic.profile,
        device_id=basic.device_id, device_name=basic.device_name,
        config=basic.config, created_at=basic.created_at, started_at=basic.started_at,
        completed_at=basic.completed_at, model_count=basic.model_count,
        completed_count=basic.completed_count, model_runs=runs,
    )
