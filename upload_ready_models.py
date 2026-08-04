#!/usr/bin/env python3
"""
快速打包上传已就绪的本地模型文件到 TOS（跳过 Docker 测试）
"""
import os
import sys
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.downloader import create_tarball, check_disk_space
from src.uploader import load_tos_client, upload_to_tos

ENV_PATH = PROJECT_ROOT / "config" / ".env"
MODELS_DIR = Path("/home/sd1/models")

# 已就绪待上传的模型
READY_MODELS = [
    {
        "name": "Gemma-4-26B-A4B-GGUF",
        "local_dir": MODELS_DIR / "gemma" / ".tmp_Gemma-4-26B-A4B-GGUF",
        "tarball": MODELS_DIR / "Gemma-4-26B-A4B-upload.tar.gz",
        "tos_key": "models/gemma/Gemma-4-26B-A4B.tar.gz",
    },
]


def main():
    client, bucket = load_tos_client(str(ENV_PATH))
    log.info(f"TOS 认证成功 (存储桶: {bucket})")

    for model in READY_MODELS:
        name = model["name"]
        local_dir = model["local_dir"]
        tarball = model["tarball"]
        tos_key = model["tos_key"]

        log.info(f"\n==================== 【{name}】打包上传 TOS ====================")

        if not local_dir.exists():
            log.warning(f"  本地目录不存在，跳过: {local_dir}")
            continue

        total = sum(f.stat().st_size for f in local_dir.rglob("*") if f.is_file())
        log.info(f"  本地目录大小: {total / (1024**3):.2f} GB")

        check_disk_space(str(MODELS_DIR), min_free_gb=50.0)

        if tarball.exists():
            log.info(f"  tarball 已存在，直接上传: {tarball}")
        else:
            log.info(f"  开始打包 {local_dir} → {tarball} ...")
            create_tarball(str(local_dir), str(tarball), label=name, min_free_gb=50.0)
            size_gb = tarball.stat().st_size / (1024**3)
            log.info(f"  打包完成: {size_gb:.2f} GB")

        upload_to_tos(
            client=client,
            bucket=bucket,
            local_path=str(tarball),
            remote_key=tos_key,
            label=name,
        )
        log.info(f"  [OK] {name} 上传 TOS 完成: {tos_key}")

        if tarball.exists():
            tarball.unlink()
            log.info(f"  临时 tarball 已清理")

    log.info("\n全部已就绪模型上传完成。")


if __name__ == "__main__":
    main()
