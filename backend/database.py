"""
AONI 模型测试平台 — 数据库连接管理 (同步版)
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from backend.config import DATABASE_URL_SYNC
from backend.models import Base

engine = create_engine(DATABASE_URL_SYNC, echo=False, connect_args={"check_same_thread": False})
session_factory = sessionmaker(bind=engine)


def init_db():
    """创建所有表"""
    Base.metadata.create_all(engine)


def get_db() -> Session:
    """依赖注入: 获取数据库会话"""
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
