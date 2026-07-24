"""
AONI 用户系统 — 用户 ORM 模型
"""
import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from backend.models import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    display_name = Column(String(200), nullable=True)
    role = Column(String(20), default="user", comment="admin / user")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    active_token = Column(String(500), nullable=True, comment="单设备登录校验唯一有效Token")
