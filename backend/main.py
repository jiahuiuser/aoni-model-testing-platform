"""
大模型测试平台 — FastAPI 后端入口 (同步版)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from backend.database import init_db, session_factory
from backend.routers import tasks, models, reports, devices, data_mgmt, images, image_categories, hardware_groups, eval_tools
from backend.routers.auth import router as auth_router, ensure_admin

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aoni-backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("数据库初始化完成")
    # 确保默认 admin 账号存在
    with session_factory() as db:
        created = ensure_admin(db)
        if created:
            log.info("已自动创建默认管理员账号: admin / jiahui123")

    # 自动恢复自愈：扫描并恢复服务端重启前处于 RUNNING 状态的任务线程
    try:
        from backend.services.task_manager import recover_running_tasks
        recover_running_tasks()
        log.info("任务运行线程自愈扫描完成")
    except Exception as e:
        log.error(f"自愈恢复运行任务失败: {e}")

    # 设备资源动态采集：每 60 秒自动巡检全部设备并落库
    try:
        from backend.routers.devices import start_device_collect_if_needed
        start_device_collect_if_needed()
    except Exception as e:
        log.error(f"启动设备定时采集失败: {e}")
    yield


app = FastAPI(
    title="大模型测试平台",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(tasks.router)
app.include_router(models.router)
app.include_router(reports.router)
app.include_router(devices.router)
app.include_router(data_mgmt.router)
app.include_router(images.router)
app.include_router(image_categories.router)
app.include_router(hardware_groups.router)
app.include_router(eval_tools.router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(f"未捕获异常: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/api/health")
def health():
    return {"status": "ok"}
