#!/usr/bin/env python3
"""
从 HuggingFace 官方仓库 nvidia/Qwen3.6-35B-A3B-NVFP4 下载模型，并打包上传至 TOS
"""
import os
import sys
import logging
import shutil
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# 使用本地 127.0.0.1:7897 高速代理直连 HF 官方源，并启用 Rust 原生并发加速引擎 hf_transfer
os.environ.pop("HF_ENDPOINT", None)
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
os.environ["HTTP_PROXY"] = "http://127.0.0.1:7897"
os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7897"
os.environ["http_proxy"] = "http://127.0.0.1:7897"
os.environ["https_proxy"] = "http://127.0.0.1:7897"

from src.downloader import download_with_huggingface, create_tarball, check_disk_space
from src.uploader import load_tos_client, upload_to_tos

ENV_PATH = PROJECT_ROOT / "config" / ".env"
MODELS_DIR = Path("/home/sd1/models")

MODEL_CONFIG = {
    "name": "Qwen3.6-35B-A3B-NVFP4",
    "hf_repo": "nvidia/Qwen3.6-35B-A3B-NVFP4",
    "local_dir": MODELS_DIR / "qwen" / "Qwen3.6-35B-A3B-NVFP4",
    "tarball": MODELS_DIR / "Qwen3.6-35B-A3B-NVFP4.tar.gz",
    "tos_key": "models/qwen/Qwen3.6-35B-A3B-NVFP4.tar.gz",
}


def main():
    client, bucket = load_tos_client(str(ENV_PATH))
    log.info(f"TOS 认证成功 (存储桶: {bucket})")

    name = MODEL_CONFIG["name"]
    hf_repo = MODEL_CONFIG["hf_repo"]
    local_dir = MODEL_CONFIG["local_dir"]
    tarball = MODEL_CONFIG["tarball"]
    tos_key = MODEL_CONFIG["tos_key"]

    log.info(f"\n==================== 【{name}】从 HuggingFace ({hf_repo}) 下载打包上传 TOS ====================")

    # 1. 检查磁盘空间
    check_disk_space(str(MODELS_DIR), min_free_gb=50.0)

    # 2. 从 HuggingFace 下载官方模型（保留已下载文件，支持断点续传）
    if not local_dir.exists():
        local_dir.mkdir(parents=True, exist_ok=True)
    
    log.info(f"开始从 HuggingFace (hf-mirror.com) 下载官方仓库 {hf_repo} → {local_dir} ...")
    download_with_huggingface(
        repo_id=hf_repo,
        local_dir=str(local_dir),
        min_free_gb=50.0
    )

    # 3. 打包压缩 (保持目录结构 /models/qwen/Qwen3.6-35B-A3B-NVFP4)
    if tarball.exists():
        tarball.unlink()
    
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
    log.info(f"✓ {name} 官方 HF 版本上传 TOS 完成: tos://{bucket}/{tos_key}")

    # 5. 清理临时 tarball
    if tarball.exists():
        tarball.unlink()
        log.info("已清理临时 tarball 压缩包文件")

    log.info("\n官方 HuggingFace 版本 Qwen3.6-35B-A3B-NVFP4 下载、打包、上传 TOS 全部完成！")


if __name__ == "__main__":
    main()
