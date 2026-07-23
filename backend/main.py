"""
AONI 模型测试平台 — FastAPI 后端入口 (同步版)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from backend.database import init_db
from backend.routers import tasks, models, reports, devices

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aoni-backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("数据库初始化完成")
    yield


app = FastAPI(
    title="AONI 模型测试平台",
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

app.include_router(tasks.router)
app.include_router(models.router)
app.include_router(reports.router)
app.include_router(devices.router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(f"未捕获异常: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/api/health")
def health():
    return {"status": "ok"}
