"""
AONI 模型测试平台 — 硬件组管理路由 (硬件组自定义增删改查)
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.database import get_db
from backend.models import HardwareGroup
from backend.schemas import HardwareGroupCreate

router = APIRouter(prefix="/api/hardware-groups", tags=["HardwareGroups"])

DEFAULT_GROUPS = [
    {"name": "NVIDIA_jetson_AGX_Thor", "description": "NVIDIA Jetson AGX Thor (T5000) 算力架构"},
    {"name": "NVIDIA_jetson_AGX_Orin", "description": "NVIDIA Jetson AGX Orin 64GB 边缘推理节点"},
    {"name": "NVIDIA_RTX_4090", "description": "NVIDIA GeForce RTX 4090 24GB 工作站"},
    {"name": "General_Server_GPU", "description": "通用服务器 GPU 算力集群"},
]


def _seed_hardware_groups_if_needed(db: Session):
    """初始化内置硬件组列表"""
    if db.query(HardwareGroup).count() == 0:
        for item in DEFAULT_GROUPS:
            hg = HardwareGroup(**item)
            db.add(hg)
        db.commit()


@router.get("")
def list_hardware_groups(db: Session = Depends(get_db)):
    """获取所有硬件组"""
    _seed_hardware_groups_if_needed(db)
    return db.query(HardwareGroup).order_by(HardwareGroup.id).all()


@router.post("")
def create_hardware_group(data: HardwareGroupCreate, db: Session = Depends(get_db)):
    """添加硬件组"""
    name = data.name.strip()
    exist = db.query(HardwareGroup).filter(HardwareGroup.name == name).first()
    if exist:
        raise HTTPException(status_code=400, detail="该硬件组已存在")
    hg = HardwareGroup(name=name, description=data.description)
    db.add(hg)
    db.commit()
    db.refresh(hg)
    return hg


@router.put("/{hg_id}")
def update_hardware_group(hg_id: int, data: HardwareGroupCreate, db: Session = Depends(get_db)):
    """修改硬件组"""
    hg = db.query(HardwareGroup).filter(HardwareGroup.id == hg_id).first()
    if not hg:
        raise HTTPException(status_code=404, detail="硬件组不存在")
    hg.name = data.name.strip()
    hg.description = data.description
    db.commit()
    db.refresh(hg)
    return hg


@router.delete("/{hg_id}")
def delete_hardware_group(hg_id: int, db: Session = Depends(get_db)):
    """删除硬件组"""
    hg = db.query(HardwareGroup).filter(HardwareGroup.id == hg_id).first()
    if not hg:
        raise HTTPException(status_code=404, detail="硬件组不存在")
    db.delete(hg)
    db.commit()
    return {"message": "已删除硬件组"}
