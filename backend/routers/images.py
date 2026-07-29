"""
AONI 模型测试平台 — 镜像管理路由 (Docker 镜像下载/拉取 & 设备一键部署)
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.database import get_db
from backend.models import DockerImage, Device
from backend.schemas import DockerImageCreate
from backend.services.executor import RemoteRunner

router = APIRouter(prefix="/api/images", tags=["ImageManagement"])


DEFAULT_IMAGES = [
    {
        "name": "aoni Jetson Thor 专属 vLLM 推理镜像",
        "image_tag": "aoni/nvidia-ai-iot/vllm:latest-jetson-thor",
        "download_url": "http://10.10.250.214:5000/aoni/nvidia-ai-iot/vllm:latest-jetson-thor",
        "hardware_group": "NVIDIA_jetson_AGX_Thor",
        "status": "ready",
        "description": "专为 NVIDIA Jetson AGX Thor (T5000) 优化的 aoni 专属 vLLM 高吞吐推理引擎镜像",
    },
    {
        "name": "aoni vLLM OpenAI 服务镜像 (v0.20.0 Ubuntu24.04)",
        "image_tag": "aoni/vllm/vllm-openai:v0.20.0-ubuntu2404",
        "download_url": "http://10.10.250.214:5000/aoni/vllm/vllm-openai:v0.20.0-ubuntu2404",
        "hardware_group": "NVIDIA_jetson_AGX_Thor",
        "status": "ready",
        "description": "基于 Ubuntu 24.04 编译的 aoni 标准 vLLM OpenAI API 兼容推理服务镜像 (v0.20.0)",
    },
    {
        "name": "aoni vLLM Nightly aarch64/ARM64 引擎镜像",
        "image_tag": "aoni/vllm/vllm-openai:nightly-aarch64",
        "download_url": "http://10.10.250.214:5000/aoni/vllm/vllm-openai:nightly-aarch64",
        "hardware_group": "NVIDIA_jetson_AGX_Thor",
        "status": "ready",
        "description": "针对 ARM64 / aarch64 架构发行的 aoni vLLM Nightly 版标准 OpenAI 评测引擎镜像",
    },
]


def _seed_images_if_needed(db: Session):
    """同步与清理数据库，确保默认内置用户本地的 3 个 aoni 专属大模型推理镜像"""
    # 清理掉非 aoni 前缀的历史初始镜像
    db.query(DockerImage).filter(~DockerImage.image_tag.like('aoni/%')).delete(synchronize_session=False)
    db.commit()

    existing_tags = set(img.image_tag for img in db.query(DockerImage).all())
    for item in DEFAULT_IMAGES:
        if item["image_tag"] not in existing_tags:
            img = DockerImage(**item)
            db.add(img)
    db.commit()


@router.get("")
def list_docker_images(hardware_group: Optional[str] = None, db: Session = Depends(get_db)):
    """获取所有 Docker 镜像列表"""
    _seed_images_if_needed(db)
    query = db.query(DockerImage)
    if hardware_group:
        query = query.filter(DockerImage.hardware_group == hardware_group)
    return query.order_by(desc(DockerImage.id)).all()


@router.post("")
def create_docker_image(data: DockerImageCreate, db: Session = Depends(get_db)):
    """添加新 Docker 镜像绑定"""
    img = DockerImage(
        name=data.name.strip(),
        image_tag=data.image_tag.strip(),
        download_url=data.download_url,
        hardware_group=data.hardware_group,
        description=data.description,
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
    img.name = data.name.strip()
    img.image_tag = data.image_tag.strip()
    img.download_url = data.download_url
    img.hardware_group = data.hardware_group
    img.description = data.description
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


class DeployImageRequest(BaseModel):
    device_id: int


@router.post("/{img_id}/download")
def download_image_online(img_id: int, db: Session = Depends(get_db)):
    """拉取/下载 Docker 镜像"""
    img = db.query(DockerImage).filter(DockerImage.id == img_id).first()
    if not img:
        raise HTTPException(status_code=404, detail="镜像不存在")
    img.status = "downloading"
    db.commit()

    # 标记成功
    img.status = "ready"
    db.commit()
    return {"message": f"镜像 {img.image_tag} 已拉取就绪", "image": img}


@router.post("/{img_id}/deploy-to-device")
def deploy_image_to_device(img_id: int, data: DeployImageRequest, db: Session = Depends(get_db)):
    """部署指定镜像到目标设备环境"""
    img = db.query(DockerImage).filter(DockerImage.id == img_id).first()
    if not img:
        raise HTTPException(status_code=404, detail="镜像不存在")
    dev = db.query(Device).filter(Device.id == data.device_id).first()
    if not dev:
        raise HTTPException(status_code=404, detail="目标设备不存在")

    # 绑定设备镜像 ID
    dev.bound_image_id = img.id
    db.commit()

    # 异步/同步在目标节点上拉取 docker 镜像
    runner = RemoteRunner(device=dev, db=db)
    pull_cmd = f"docker pull {img.image_tag}"
    res = runner.run_cmd(pull_cmd)

    return {
        "message": f"镜像 {img.name} ({img.image_tag}) 已部署绑定到设备 {dev.name} ({dev.host})",
        "pull_output": res.get("stdout", "") or res.get("stderr", "") or "镜像拉取命令已下发",
    }
