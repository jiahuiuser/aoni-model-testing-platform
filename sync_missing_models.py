#!/usr/bin/env python3
"""
缺失模型下载并上传 TOS 脚本
处理剩余 3 款模型：
1. Nemotron-Nano (直接上传本地 21G 离线包)
2. cosmos-reason-1-7b (HuggingFace: unsloth/Cosmos-Reason1-7B-GGUF)
3. llama-3-1-70b (HuggingFace: bartowski/Meta-Llama-3.1-70B-Instruct-GGUF)
"""
import os
import sys
import logging
import shutil
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/tmp/sync_missing_models.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.downloader import download_with_huggingface, create_tarball, check_disk_space
from src.uploader import load_tos_client, upload_to_tos

ENV_PATH = PROJECT_ROOT / "config" / ".env"
MODELS_DIR = Path("/home/sd1/models")

REMAINING_MODELS = [
    {
        "name": "Nemotron-Nano-12B-v1",
        "type": "local_file",
        "local_file": Path("/home/sd1/Desktop/ai-agent-os-setup/models/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4.tar"),
        "tos_key": "models/nemotron/Nemotron-Nano-12B-v1.tar.gz",
    },
    {
        "name": "cosmos-reason-1-7b",
        "type": "hf_download",
        "repo_id": "unsloth/Cosmos-Reason1-7B-GGUF",
        "include": ["*Q4_K_M*"],
        "tos_key": "models/cosmos/cosmos-reason-1-7b.tar.gz",
        "min_size_gb": 3.0,
    },
    {
        "name": "llama-3-1-70b",
        "type": "hf_download",
        "repo_id": "bartowski/Meta-Llama-3.1-70B-Instruct-GGUF",
        "include": ["*Q4_K_M*"],
        "tos_key": "models/llama/llama-3-1-70b.tar.gz",
        "min_size_gb": 30.0,
    },
]


def tos_file_exists(client, bucket, key):
    try:
        client.head_object(bucket, key)
        return True
    except Exception:
        return False


def main():
    client, bucket = load_tos_client(str(ENV_PATH))
    log.info(f"TOS 认证成功 (存储桶: {bucket})")

    for model in REMAINING_MODELS:
        name = model["name"]
        tos_key = model["tos_key"]
        log.info(f"\n{'='*60}")
        log.info(f"处理模型: {name}")
        log.info(f"  TOS 目标: {tos_key}")

        if tos_file_exists(client, bucket, tos_key):
            log.info(f"  [跳过] TOS 上已存在: {tos_key}")
            continue

        try:
            if model["type"] == "local_file":
                filepath = model["local_file"]
                if not filepath.exists():
                    log.error(f"  本地离线包不存在: {filepath}")
                    continue
                log.info(f"  直接上传本地文件 ({filepath.stat().st_size / (1024**3):.2f} GB) -> TOS: {tos_key}")
                upload_to_tos(client=client, bucket=bucket, local_path=str(filepath), remote_key=tos_key, label=name)
                log.info(f"  ✓ {name} 上传 TOS 成功")

            elif model["type"] == "hf_download":
                tmp_dir = MODELS_DIR / f".tmp_{name}"
                tarball = MODELS_DIR / f"{name}.tar.gz"

                check_disk_space(str(MODELS_DIR), min_free_gb=40.0)

                log.info(f"  从 HuggingFace 下载: {model['repo_id']}")
                os.makedirs(tmp_dir, exist_ok=True)
                download_with_huggingface(
                    repo_id=model["repo_id"],
                    local_dir=str(tmp_dir),
                    include=model.get("include"),
                    min_free_gb=40.0,
                )

                log.info(f"  打包 {tmp_dir} -> {tarball}")
                check_disk_space(str(MODELS_DIR), min_free_gb=40.0)
                create_tarball(str(tmp_dir), str(tarball), label=name, min_free_gb=40.0)

                log.info(f"  上传 TOS -> {tos_key}")
                upload_to_tos(client=client, bucket=bucket, local_path=str(tarball), remote_key=tos_key, label=name)
                log.info(f"  ✓ {name} 上传 TOS 成功")

                if tarball.exists():
                    tarball.unlink()
                if tmp_dir.exists():
                    shutil.rmtree(tmp_dir, ignore_errors=True)

        except Exception as e:
            log.error(f"  ❌ 【{name}】处理异常: {e}")

    log.info(f"\n{'='*60}")
    log.info("所有剩余缺失模型同步全部完成。")


if __name__ == "__main__":
    main()
