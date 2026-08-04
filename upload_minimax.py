#!/usr/bin/env python3
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.uploader import load_tos_client, upload_to_tos

ENV_PATH = PROJECT_ROOT / "config" / ".env"
MODELS_DIR = Path("/home/sd1/models")
tarball = MODELS_DIR / "MiniMax-M2.7.tar.gz"
tos_key = "models/minimax/MiniMax-M2.7.tar.gz"

def main():
    client, bucket = load_tos_client(str(ENV_PATH))
    log.info(f"TOS 认证成功 (存储桶: {bucket})")
    log.info(f"开始上传 {tarball} ({tarball.stat().st_size / (1024**3):.2f} GB) -> tos://{bucket}/{tos_key}")

    upload_to_tos(client=client, bucket=bucket, local_path=str(tarball), remote_key=tos_key, label="MiniMax-M2.7")
    log.info("✓ MiniMax-M2.7 上传 TOS 成功！")

    if tarball.exists():
        tarball.unlink()
        log.info("已清理 MiniMax-M2.7.tar.gz 临时压缩文件。")

if __name__ == "__main__":
    main()
