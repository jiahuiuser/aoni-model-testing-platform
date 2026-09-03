"""
大模型测试平台 — 镜像分类（文件夹目录）管理路由
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import ImageCategory, DockerImage
from backend.schemas import ImageCategoryCreate

router = APIRouter(prefix="/api/image-categories", tags=["ImageCategories"])


@router.get("")
def list_categories(db: Session = Depends(get_db)):
    """获取全部分类（含层级信息与分类下镜像计数）"""
    cats = db.query(ImageCategory).order_by(ImageCategory.sort_order, ImageCategory.id).all()
    counts = {}
    for img in db.query(DockerImage).filter(DockerImage.category_id.isnot(None)).all():
        counts[img.category_id] = counts.get(img.category_id, 0) + 1
    return [
        {
            "id": c.id,
            "name": c.name,
            "parent_id": c.parent_id,
            "description": c.description,
            "sort_order": c.sort_order,
            "image_count": counts.get(c.id, 0),
            "created_at": c.created_at,
        }
        for c in cats
    ]


@router.post("")
def create_category(data: ImageCategoryCreate, db: Session = Depends(get_db)):
    """新建分类（文件夹）"""
    name = data.name.strip()
    if not name:
        raise HTTPException(400, "分类名称不能为空")
    exists = db.query(ImageCategory).filter(ImageCategory.name == name).first()
    if exists:
        raise HTTPException(400, f"分类「{name}」已存在")
    cat = ImageCategory(
        name=name,
        parent_id=data.parent_id,
        description=data.description,
        sort_order=data.sort_order,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.put("/{cat_id}")
def update_category(cat_id: int, data: ImageCategoryCreate, db: Session = Depends(get_db)):
    """编辑分类"""
    cat = db.query(ImageCategory).filter(ImageCategory.id == cat_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    name = data.name.strip()
    if not name:
        raise HTTPException(400, "分类名称不能为空")
    dup = db.query(ImageCategory).filter(ImageCategory.name == name, ImageCategory.id != cat_id).first()
    if dup:
        raise HTTPException(400, f"分类「{name}」已存在")
    cat.name = name
    cat.parent_id = data.parent_id
    cat.description = data.description
    cat.sort_order = data.sort_order
    db.commit()
    db.refresh(cat)
    return cat


@router.delete("/{cat_id}")
def delete_category(cat_id: int, db: Session = Depends(get_db)):
    """删除分类（其下镜像移回未分类）"""
    cat = db.query(ImageCategory).filter(ImageCategory.id == cat_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    # 分类下镜像移回未分类，不删镜像
    db.query(DockerImage).filter(DockerImage.category_id == cat_id).update(
        {DockerImage.category_id: None}
    )
    db.delete(cat)
    db.commit()
    return {"message": f"分类「{cat.name}」已删除，其下镜像已移出"}
