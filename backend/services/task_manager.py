"""
任务管理器 — 同步版
"""
import json
import threading
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from sqlalchemy.orm import Session

from backend.database import session_factory
from backend.models import Task, ModelRun, TaskLog, TaskStatus, ModelStage, StageStatus
from backend.schemas import TaskCreate
from backend.config import DATA_DIR

log = logging.getLogger(__name__)

_running_tasks: dict[int, threading.Thread] = {}
_pause_flags: dict[int, bool] = {}


def create_task(db: Session, data: TaskCreate, user_id: Optional[int] = None) -> Task:
    """创建新任务"""
    from backend.models import ModelInfo, ModelDeviceConfig
    from sqlalchemy import select

    device_id = data.device_id

    # 从数据库读取模型，考虑设备专属配置
    query = db.query(ModelInfo)

    if data.config.model_slugs:
        query = query.filter(ModelInfo.slug.in_(data.config.model_slugs))

    models = query.all()

    # 构建模型→设备专属配置映射
    device_config_map = {}
    if device_id:
        configs = db.execute(
            select(ModelDeviceConfig).where(
                ModelDeviceConfig.device_id == device_id,
                ModelDeviceConfig.model_id.in_([m.id for m in models])
            )
        ).scalars().all()
        device_config_map = {dc.model_id: dc for dc in configs}

    # 仅保留在该设备上有配置且 PASS 的模型
    pass_models = []
    for m in models:
        dc = device_config_map.get(m.id)
        if not dc or dc.status != "PASS":
            continue
        pass_models.append(m)

    if not pass_models:
        raise ValueError("所选模型在目标设备节点上尚未完成部署验证（状态非 PASS），无法创建任务。请先在【模型管理】中为该设备绑定配置并验证 PASS。")

    task = Task(
        name=data.name,
        status=TaskStatus.QUEUED,
        profile=data.profile,
        user_id=user_id,
        device_id=data.device_id,
        config=data.config.model_dump(),
    )
    db.add(task)
    db.flush()

    # 获取设备名
    device_name = task.device.name if task.device else None

    for m in pass_models:
        dc = device_config_map.get(m.id)
        # 使用设备专属 docker 命令（如有），否则用默认
        docker_cmd = dc.docker_command if dc and dc.docker_command else (m.docker_command or "")
        model_run = ModelRun(
            task_id=task.id,
            model_idx=m.idx,
            model_name=m.name,
            model_slug=m.slug,
            size_category=m.size_category or "unknown",
            device_id=task.device_id,
            device_name=device_name,
            status=ModelStage.DEPLOYING,
            stage_status={
                "deploying": StageStatus.PENDING.value,
                "validating": StageStatus.PENDING.value,
                "perf_testing": StageStatus.PENDING.value,
                "acc_testing": StageStatus.PENDING.value,
                "reporting": StageStatus.PENDING.value,
            },
            docker_command=docker_cmd,
            port=data.config.container_port,
        )
        db.add(model_run)

    db.commit()
    return task


def start_task(task_id: int):
    """后台线程启动任务"""
    _pause_flags[task_id] = False
    t = threading.Thread(target=_execute_task_pipeline, args=(task_id,), daemon=True)
    t.start()
    _running_tasks[task_id] = t


def pause_task(db: Session, task_id: int):
    """暂停任务：挂起测试基准脚本调度，不停止与下线 Docker 容器"""
    _pause_flags[task_id] = True
    task = db.get(Task, task_id)
    if task:
        task.status = TaskStatus.PAUSED
        db.commit()
        _add_log(db, task_id, "INFO", None, "任务已暂停 (基准测试挂起，推理服务容器保持运行中)", "system")


def resume_task(task_id: int):
    _pause_flags[task_id] = False
    start_task(task_id)


def cancel_task(db: Session, task_id: int):
    """取消任务：挂起测试脚本并强行停止与删除 Docker 容器，释放 GPU 显存与内存"""
    from backend.services.executor import stop_task_containers
    _pause_flags.pop(task_id, None)
    task = db.get(Task, task_id)
    if task:
        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.utcnow()
        db.commit()
        stop_task_containers(task)
        _add_log(db, task_id, "INFO", None, "任务已取消，测试容器与显存资源已成功释放", "system")


def _add_log(db: Session, task_id: int, level: str, model_slug: Optional[str], message: str, module: str = "system"):
    log_entry = TaskLog(task_id=task_id, level=level, model_slug=model_slug, module=module, message=message)
    db.add(log_entry)
    db.commit()


def _check_pause(task_id: int):
    import time
    while _pause_flags.get(task_id, False):
        time.sleep(1)


def _execute_task_pipeline(task_id: int):
    """在后台线程执行任务流水线"""
    import time
    from backend.services.executor import run_model_pipeline

    db = session_factory()
    try:
        task = db.get(Task, task_id)
        if not task:
            return
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        db.commit()
        _add_log(db, task_id, "INFO", None, f"任务开始: {task.name}", "system")

        model_runs = sorted(task.model_runs, key=lambda m: m.model_idx)
        for model_run in model_runs:
            _check_pause(task_id)

            try:
                _add_log(db, task_id, "INFO", model_run.model_slug,
                         f"[{model_run.model_name}] 开始测试", "system")
                run_model_pipeline(db, task_id, model_run, task.config,
                                   lambda lvl, slug, msg, mod="system": _add_log(db, task_id, lvl, slug, msg, mod))
            except Exception as e:
                _add_log(db, task_id, "ERROR", model_run.model_slug, f"异常: {str(e)}", "system")
                model_run.status = ModelStage.DONE
                model_run.stage_status["acc_testing"] = StageStatus.FAILED.value
                model_run.completed_at = datetime.utcnow()
                db.commit()

        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()
        db.commit()
        _add_log(db, task_id, "INFO", None, "全部模型测试完成", "system")
    finally:
        db.close()
        _running_tasks.pop(task_id, None)
