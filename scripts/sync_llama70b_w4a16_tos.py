#!/usr/bin/env python3
"""
从 HuggingFace 官方仓库 RedHatAI/Meta-Llama-3.1-70B-Instruct-quantized.w4a16 下载模型，
打包成 tar.gz 并上传至 TOS 对象存储，更新数据库引擎与下载配置。
"""
import os
import sys
import logging
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

from src.downloader import download_with_huggingface, create_tarball, check_disk_space
from src.uploader import load_tos_client, upload_to_tos
from backend.database import session_factory
from backend.models import ModelInfo, ModelDeviceConfig, ModelRun

ENV_PATH = PROJECT_ROOT / "config" / ".env"
MODELS_DIR = Path("/home/sd1/models")

HF_REPO = "RedHatAI/Meta-Llama-3.1-70B-Instruct-quantized.w4a16"
MODEL_NAME = "Meta-Llama-3.1-70B-Instruct-quantized.w4a16"
LOCAL_DIR = MODELS_DIR / "llama" / MODEL_NAME
TARBALL = MODELS_DIR / f"{MODEL_NAME}.tar.gz"
TOS_KEY = f"models/llama/{MODEL_NAME}.tar.gz"


def main():
    client, bucket = load_tos_client(str(ENV_PATH))
    log.info(f"TOS 认证成功 (存储桶: {bucket})")

    log.info(f"\n==================== 下载【{HF_REPO}】打包上传 TOS ====================")

    # 1. 磁盘空间检查
    check_disk_space(str(MODELS_DIR), min_free_gb=50.0)

    # 2. 从 HuggingFace 下载模型
    if not LOCAL_DIR.exists():
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)

    log.info(f"1. 开始从 HuggingFace ({HF_REPO}) 下载权重 -> {LOCAL_DIR} ...")
    download_with_huggingface(
        repo_id=HF_REPO,
        local_dir=str(LOCAL_DIR),
        min_free_gb=50.0
    )

    # 3. 打包压缩包
    log.info(f"2. 开始打包压缩 -> {TARBALL} ...")
    check_disk_space(str(MODELS_DIR), min_free_gb=50.0)
    create_tarball(str(LOCAL_DIR), str(TARBALL), label=MODEL_NAME, min_free_gb=50.0)

    # 4. 上传至 TOS
    log.info(f"3. 开始上传至 TOS: {TOS_KEY} ...")
    upload_to_tos(
        client=client,
        bucket=bucket,
        local_path=str(TARBALL),
        remote_key=TOS_KEY,
        label=MODEL_NAME
    )
    log.info(f"✓ {MODEL_NAME} 上传 TOS 完成: tos://{bucket}/{TOS_KEY}")

    # 5. 清理临时 tarball 节省空间
    if TARBALL.exists():
        TARBALL.unlink()
        log.info("已清理临时压缩包")

    # 6. 更新数据库中的 ModelInfo, ModelDeviceConfig 与 Task 39 ModelRun
    db = session_factory()
    cmd = (
        'sudo docker run --shm-size 16g -it --rm --runtime=nvidia --network host '
        '-e MODEL_OSS=True -e MODEL_ROOT=/models '
        f'-e ENGINE_URI=tos://{bucket}/{TOS_KEY} '
        f'-e MODEL_NAME=llama/{MODEL_NAME} '
        '-v ~/models:/models '
        'aoni/vllm/vllm-openai:nightly-aarch64 '
        '--port 8300 --max-model-len 16384 --gpu-memory-utilization 0.85'
    )

    m = db.query(ModelInfo).filter(ModelInfo.slug == 'llama-3-1-70b').first()
    if m:
        m.docker_command = cmd

    dcs = db.query(ModelDeviceConfig).filter(ModelDeviceConfig.model_id == m.id).all() if m else []
    for dc in dcs:
        dc.docker_command = cmd

    mrs = db.query(ModelRun).filter(ModelRun.task_id == 39, ModelRun.model_slug == 'llama-3-1-70b').all() if m else []
    for mr in mrs:
        mr.docker_command = cmd

    db.commit()
    log.info("✓ 数据库对应 docker_command 指令已同步更新为全新 TOS URLEngine 地址！")


if __name__ == "__main__":
    main()
