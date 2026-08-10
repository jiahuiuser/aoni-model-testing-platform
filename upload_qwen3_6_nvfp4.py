#!/usr/bin/env python3
"""
从 ModelScope 下载 Qwen3.6-35B-A3B-NVFP4 并打包上传至 TOS
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

from src.downloader import download_with_modelscope, create_tarball, check_disk_space
from src.uploader import load_tos_client, upload_to_tos

ENV_PATH = PROJECT_ROOT / "config" / ".env"
MODELS_DIR = Path("/home/sd1/models")

MODEL_CONFIG = {
    "name": "Qwen3.6-35B-A3B-NVFP4",
    "ms_repo": "unsloth/Qwen3.6-35B-A3B-NVFP4",
    "local_dir": MODELS_DIR / ".tmp_Qwen3.6-35B-A3B-NVFP4",
    "tarball": MODELS_DIR / "Qwen3.6-35B-A3B-NVFP4.tar.gz",
    "tos_key": "models/qwen/Qwen3.6-35B-A3B-NVFP4.tar.gz",
}


def main():
    client, bucket = load_tos_client(str(ENV_PATH))
    log.info(f"TOS 认证成功 (存储桶: {bucket})")

    name = MODEL_CONFIG["name"]
    ms_repo = MODEL_CONFIG["ms_repo"]
    local_dir = MODEL_CONFIG["local_dir"]
    tarball = MODEL_CONFIG["tarball"]
    tos_key = MODEL_CONFIG["tos_key"]

    log.info(f"\n==================== 【{name}】从 ModelScope 下载打包上传 TOS ====================")

    # 1. 检查磁盘空间
    check_disk_space(str(MODELS_DIR), min_free_gb=50.0)

    # 2. 从 ModelScope 下载模型
    if not local_dir.exists():
        log.info(f"开始从 ModelScope 下载 {ms_repo} → {local_dir} ...")
        download_with_modelscope(
            repo_id=ms_repo,
            local_dir=str(local_dir),
            min_free_gb=50.0
        )
    else:
        log.info(f"本地临时目录已存在: {local_dir}，跳过下载步骤")

    # 3. 打包压缩
    if tarball.exists():
        log.info(f"tarball 已存在，跳过打包: {tarball}")
    else:
        log.info(f"开始打包 {local_dir} → {tarball} ...")
        create_tarball(str(local_dir), str(tarball), label=name, min_free_gb=50.0)

    # 4. 上传 TOS
    log.info(f"开始上传至 TOS: {tos_key} ...")
    upload_to_tos(
        client=client,
        bucket=bucket,
        local_path=str(tarball),
        remote_key=tos_key,
        label=name,
    )
    log.info(f"✓ {name} 上传 TOS 完成: tos://{bucket}/{tos_key}")

    # 5. 清理临时文件
    if tarball.exists():
        tarball.unlink()
        log.info("已清理临时 tarball 文件")

    if local_dir.exists():
        import shutil
        shutil.rmtree(local_dir, ignore_errors=True)
        log.info("已清理本地临时下载目录")

    log.info("\n任务全部完成。")


if __name__ == "__main__":
    main()
