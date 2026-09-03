#!/usr/bin/env python3
"""
镜像管理重构迁移脚本
- 幂等执行，可重复运行
- DockerImage 加列（保留现有记录）
- 新建 ImageCategory / DeviceImageBinding / ImageDeployLog 表
- 旧 Device.bound_image_id 迁移到 DeviceImageBinding
- 初始化默认分类（沐曦推理镜像 / vLLM 官网镜像 / 自定义镜像）
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import warnings
warnings.filterwarnings("ignore")

from sqlalchemy import text, inspect
from backend.database import session_factory, engine
from backend.models import Base, DockerImage, DeviceImageBinding


def _table_exists(insp, name: str) -> bool:
    return insp.has_table(name)


def _column_exists(insp, table: str, column: str) -> bool:
    if not _table_exists(insp, table):
        return False
    return column in [c["name"] for c in insp.get_columns(table)]


def _add_columns_if_missing():
    """DockerImage 扩列（幂等）"""
    insp = inspect(engine)
    cols = [
        ("category_id", "INTEGER REFERENCES image_categories(id) ON DELETE SET NULL"),
        ("source", "VARCHAR(30) DEFAULT 'custom'"),
        ("chip_type", "VARCHAR(50)"),
        ("arch", "VARCHAR(20) DEFAULT 'amd64'"),
        ("source_ref", "VARCHAR(500)"),
        ("size_bytes", "BIGINT"),
        ("pull_command", "TEXT"),
        ("install_step", "TEXT"),
        ("pulled", "BOOLEAN DEFAULT 0"),
        ("pulled_at", "DATETIME"),
        ("sync_at", "DATETIME"),
        ("latest", "BOOLEAN DEFAULT 1"),
        ("updated_at", "DATETIME"),
    ]
    for col, ddl in cols:
        if _column_exists(insp, "docker_images", col):
            print(f"  [跳过] docker_images.{col} 已存在")
            continue
        engine.execute(text(f"ALTER TABLE docker_images ADD COLUMN {col} {ddl}")) \
            if False else None
        with engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE docker_images ADD COLUMN {col} {ddl}"))
            conn.commit()
        print(f"  [新增] docker_images.{col}")


def _seed_default_categories():
    """初始化默认分类（幂等）"""
    db = session_factory()
    try:
        defaults = [
            {"name": "沐曦推理镜像", "description": "来自沐曦软星资源中心的官方推理镜像（docker pull 需登录授权）", "sort_order": 1},
            {"name": "vLLM 官网镜像", "description": "vLLM 官方公开镜像，匿名 docker pull 即可拉取", "sort_order": 2},
            {"name": "自定义镜像", "description": "用户手动注册的镜像", "sort_order": 3},
        ]
        existing = {c.name for c in db.execute(text("SELECT name FROM image_categories")).fetchall()}
        for d in defaults:
            if d["name"] not in existing:
                db.execute(text(
                    "INSERT INTO image_categories (name, description, sort_order) VALUES (:n, :d, :s)"
                ), {"n": d["name"], "d": d["description"], "s": d["sort_order"]})
                print(f"  [新增分类] {d['name']}")
        db.commit()
    finally:
        db.close()


def _migrate_bound_images():
    """旧 Device.bound_image_id → DeviceImageBinding（幂等）"""
    db = session_factory()
    try:
        rows = db.execute(text(
            "SELECT id, bound_image_id FROM devices WHERE bound_image_id IS NOT NULL"
        )).fetchall()
        migrated = 0
        for dev_id, img_id in rows:
            exists = db.execute(text(
                "SELECT id FROM device_image_bindings WHERE image_id = :i AND device_id = :d"
            ), {"i": img_id, "d": dev_id}).fetchone()
            if not exists:
                db.execute(text(
                    "INSERT INTO device_image_bindings (image_id, device_id, status) VALUES (:i, :d, 'ready')"
                ), {"i": img_id, "d": dev_id})
                migrated += 1
        db.commit()
        if migrated:
            print(f"  [迁移] bound_image_id → 绑定表，共 {migrated} 条")
    finally:
        db.close()


def _tag_existing_images():
    """给现有镜像打 source 标签（幂等）"""
    db = session_factory()
    try:
        # aoni 前缀 + 内网 registry 特征的归为 registry，其余 custom
        db.execute(text(
            "UPDATE docker_images SET source = 'registry' "
            "WHERE (source IS NULL OR source = '') "
            "AND (image_tag LIKE 'aoni/%' OR image_tag LIKE 'aoni-docker%' OR image_tag LIKE '%cr.volces.com%')"
        ))
        db.execute(text(
            "UPDATE docker_images SET source = 'custom' WHERE source IS NULL OR source = ''"
        ))
        db.commit()
        print("  [标记] 现有镜像 source 归类完成")
    finally:
        db.close()


def main():
    print("=== 镜像管理重构迁移开始 ===")

    print("[1/4] 创建新表...")
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Base.metadata.tables["image_categories"],
            Base.metadata.tables["device_image_bindings"],
            Base.metadata.tables["image_deploy_logs"],
        ],
    )

    print("[2/4] DockerImage 扩列...")
    _add_columns_if_missing()

    print("[3/4] 初始化默认分类...")
    _seed_default_categories()

    print("[3.5/4] 现有镜像打标...")
    _tag_existing_images()

    print("[4/4] 迁移旧绑定关系...")
    _migrate_bound_images()

    print("=== 迁移完成 ===")


if __name__ == "__main__":
    main()
