"""
AONI 模型测试平台 — 数据库连接管理 (同步版)
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from backend.config import DATABASE_URL_SYNC
from backend.models import Base

from sqlalchemy import event

engine = create_engine(
    DATABASE_URL_SYNC,
    echo=False,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

session_factory = sessionmaker(bind=engine)


def init_db():
    """创建所有表并补全迁移字段"""
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        try:
            from sqlalchemy import text
            conn.execute(text("ALTER TABLE users ADD COLUMN active_token VARCHAR(500)"))
            conn.commit()
        except Exception:
            pass


def get_db() -> Session:
    """依赖注入: 获取数据库会话"""
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
