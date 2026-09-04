"""
大模型测试平台 — 镜像管理路由 (分类目录 + 多来源镜像 + 批量设备部署 + 部署日志)
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.database import get_db
from backend.models import DockerImage, Device, DeviceImageBinding
from backend.schemas import DockerImageCreate
from backend.services import images as image_svc
from backend.services.executor import RemoteRunner

router = APIRouter(prefix="/api/images", tags=["ImageManagement"])


class DeployRequest(BaseModel):
    device_ids: List[int]


def _validate_image_tag(tag: str):
    """校验 docker 镜像 tag 基本格式: [host[:port]/]repo[:tag]"""
    if not tag or not tag.strip():
        raise HTTPException(400, "镜像 Tag 不能为空")
    tag = tag.strip()
    invalid_chars = set(tag) - set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/._:@-")
    if invalid_chars:
        raise HTTPException(400, f"镜像 Tag 含非法字符: {''.join(invalid_chars)}")
    return tag


@router.get("")
def list_docker_images(
    category_id: Optional[int] = None,
    source: Optional[str] = None,
    chip_type: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """获取镜像列表（支持分类/来源/芯片筛选与关键字搜索、分页）"""
    query = db.query(DockerImage)
    if category_id:
        query = query.filter(DockerImage.category_id == category_id)
    if source:
        query = query.filter(DockerImage.source == source)
    if chip_type:
        query = query.filter(DockerImage.chip_type == chip_type)
    if search:
        kw = f"%{search.strip()}%"
        query = query.filter(or_(
            DockerImage.name.like(kw),
            DockerImage.image_tag.like(kw),
            DockerImage.description.like(kw),
        ))
    total = query.count()
    query = query.order_by(DockerImage.id.desc())
    if limit > 0:
        query = query.offset((page - 1) * limit).limit(limit)
    items = query.all()
    return {"total": total, "items": items}


@router.post("")
def create_docker_image(data: DockerImageCreate, db: Session = Depends(get_db)):
    """添加新 Docker 镜像绑定"""
    tag = _validate_image_tag(data.image_tag)
    img = DockerImage(
        name=data.name.strip(),
        image_tag=tag,
        download_url=data.download_url,
        hardware_group=data.hardware_group,
        description=data.description,
        category_id=data.category_id,
        source=data.source or "custom",
        chip_type=data.chip_type,
        arch=data.arch or "amd64",
        source_ref=data.source_ref,
        size_bytes=data.size_bytes,
        pull_command=data.pull_command,
        install_step=data.install_step,
        status="ready",
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return img


@router.put("/{img_id}")
def update_docker_image(img_id: int, data: DockerImageCreate, db: Session = Depends(get_db)):
    """编辑/修改指定的 Docker 镜像信息"""
    img = db.query(DockerImage).filter(DockerImage.id == img_id).first()
    if not img:
        raise HTTPException(status_code=404, detail="镜像不存在")
    tag = _validate_image_tag(data.image_tag)
    img.name = data.name.strip()
    img.image_tag = tag
    img.download_url = data.download_url
    img.hardware_group = data.hardware_group
    img.description = data.description
    if data.category_id is not None:
        img.category_id = data.category_id
    img.source = data.source or img.source or "custom"
    img.chip_type = data.chip_type
    img.arch = data.arch or img.arch
    img.source_ref = data.source_ref
    img.size_bytes = data.size_bytes
    img.pull_command = data.pull_command
    img.install_step = data.install_step
    db.commit()
    db.refresh(img)
    return img


@router.delete("/{img_id}")
def delete_docker_image(img_id: int, db: Session = Depends(get_db)):
    """删除指定的 Docker 镜像记录"""
    img = db.query(DockerImage).filter(DockerImage.id == img_id).first()
    if not img:
        raise HTTPException(status_code=404, detail="镜像不存在")
    db.delete(img)
    db.commit()
    return {"message": "已成功删除镜像记录"}


# ---------- 沐曦来源镜像（前端浏览后落库登记） ----------

class MetaxImageRegister(BaseModel):
    name: str
    image_tag: str
    download_url: Optional[str] = None
    chip_type: str = "metax_c500"
    arch: str = "amd64"
    source_ref: Optional[str] = None
    size_bytes: Optional[int] = None
    pull_command: Optional[str] = None
    install_step: Optional[str] = None
    description: Optional[str] = None


@router.post("/metax/register")
def register_metax_image(data: MetaxImageRegister, db: Session = Depends(get_db)):
    """将沐曦资源中心选中的镜像登记入库（归入「沐曦推理镜像」分类）"""
    from datetime import datetime
    from sqlalchemy import text as _t

    tag = _validate_image_tag(data.image_tag)
    cat = db.execute(_t("SELECT id FROM image_categories WHERE name = '沐曦推理镜像'")).fetchone()

    img = db.query(DockerImage).filter(DockerImage.image_tag == tag).first()
    if img:
        # 更新已有记录
        img.pull_command = data.pull_command or img.pull_command
        img.source_ref = data.source_ref or img.source_ref
        img.size_bytes = data.size_bytes or img.size_bytes
        img.description = data.description or img.description
        img.install_step = data.install_step or img.install_step
        img.sync_at = __import__("datetime").datetime.utcnow()
        db.commit()
        db.refresh(img)
        return img

    img = DockerImage(
        name=data.name.strip(),
        image_tag=tag,
        download_url=data.download_url,
        hardware_group="MetaX_C500",
        description=data.description,
        category_id=cat[0] if cat else None,
        source="official",
        chip_type=data.chip_type,
        arch=data.arch,
        source_ref=data.source_ref,
        size_bytes=data.size_bytes,
        pull_command=data.pull_command,
        install_step=data.install_step,
        status="ready",
        sync_at=__import__("datetime").datetime.utcnow(),
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return img


# ---------- 部署（真实 docker pull，批量/异步） ----------

@router.post("/{img_id}/deploy-to-device")
def deploy_image_to_devices(img_id: int, data: DeployRequest, db: Session = Depends(get_db)):
    """批量部署指定镜像到多个目标设备（后台线程异步执行 docker pull）"""
    img = db.query(DockerImage).filter(DockerImage.id == img_id).first()
    if not img:
        raise HTTPException(status_code=404, detail="镜像不存在")
    if not data.device_ids:
        raise HTTPException(400, "请至少选择一个目标设备")

    devices = db.query(Device).filter(Device.id.in_(data.device_ids)).all()
    if len(devices) != len(set(data.device_ids)):
        raise HTTPException(404, "部分目标设备不存在")

    binding_ids = image_svc.deploy_image_to_devices(img_id, data.device_ids)

    dev_names = ", ".join(f"{d.name}({d.host})" for d in devices)
    return {
        "message": f"镜像 {img.name} 已下发到 {len(devices)} 台设备: {dev_names}",
        "binding_ids": binding_ids,
        "device_count": len(devices),
    }


@router.get("/{img_id}/deploy-status")
def get_deploy_status(img_id: int, db: Session = Depends(get_db)):
    """查询镜像在各设备上的部署状态（实时）"""
    from backend.models import DeviceImageBinding
    img = db.query(DockerImage).filter(DockerImage.id == img_id).first()
    if not img:
        raise HTTPException(status_code=404, detail="镜像不存在")
    bindings = db.query(DeviceImageBinding).filter(DeviceImageBinding.image_id == img_id) \
        .order_by(DeviceImageBinding.id.desc()).all()
    return bindings


@router.get("/{img_id}/deploy-logs")
def get_deploy_logs(img_id: int, device_id: Optional[int] = None, limit: int = 200, db: Session = Depends(get_db)):
    """查询镜像部署历史日志（后台查看，已脱敏）"""
    logs = image_svc.list_deploy_logs(img_id, device_id=device_id, limit=limit)
    return [
        {
            "id": l.id,
            "image_id": l.image_id,
            "device_id": l.device_id,
            "level": l.level,
            "message": l.message,
            "created_at": l.created_at,
        }
        for l in logs
    ]


# ---------- 沐曦软星（手动 pull 命令接入） ----------
# 说明: 沐曦 authing 登录回调有域名白名单（仅 developer.metax-tech.com），
# 平台回调地址无法收到登录码，故改为手动粘贴 pull 命令方式接入。
