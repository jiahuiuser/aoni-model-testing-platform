import os
import sys
import logging
import time

log = logging.getLogger(__name__)

def load_tos_client(env_file):
    """从指定的 .env 文件中加载配置并初始化 TOS 客户端"""
    from dotenv import load_dotenv
    import tos

    if not os.path.exists(env_file):
        log.error(f"TOS 配置文件不存在: {env_file}")
        sys.exit(1)

    load_dotenv(env_file)
    ak = os.getenv("TOS_ACCESS_KEY")
    sk = os.getenv("TOS_SECRET_KEY")
    bucket = os.getenv("TOS_BUCKET")
    endpoint = os.getenv("TOS_ENDPOINT", "https://tos-cn-guangzhou.volces.com")
    region = os.getenv("TOS_REGION", "cn-guangzhou")

    if not all([ak, sk, bucket]):
        log.error("TOS 配置不完整，请检查 .env 中的 TOS_ACCESS_KEY, TOS_SECRET_KEY, TOS_BUCKET")
        sys.exit(1)

    client = tos.TosClientV2(ak, sk, endpoint, region)
    return client, bucket

def upload_to_tos(client, bucket, local_path, remote_key, label=""):
    """上传本地文件到 TOS，支持断点续传与并发上传，并显示详细进度百分比"""
    size_gb = os.path.getsize(local_path) / (1024 ** 3)
    log.info("  上传 %s (%.2f GB) → tos://%s/%s", label, size_gb, bucket, remote_key)

    # 预先检查并清理 TOS 上的同名旧文件
    try:
        client.head_object(bucket, remote_key)
        client.delete_object(bucket, remote_key)
        log.info("  已清理 TOS 上的旧版模型文件")
    except Exception:
        pass

    last_pct = [0]
    def on_progress(consumed_bytes, total_bytes, rw_once_bytes, type):
        if total_bytes:
            pct = int(100 * consumed_bytes / total_bytes)
            if pct != last_pct[0] and pct % 5 == 0:
                mb = consumed_bytes / (1024 * 1024)
                total_mb = total_bytes / (1024 * 1024)
                log.info("  上传进度: %3d%%  %.1f/%.1f MB", pct, mb, total_mb)
                last_pct[0] = pct

    start_time = time.time()
    resp = client.upload_file(
        bucket, remote_key, str(local_path),
        task_num=4,
        part_size=50 * 1024 * 1024,
        enable_checkpoint=True,
        data_transfer_listener=on_progress,
    )
    elapsed = time.time() - start_time
    log.info("  ✓ %s 上传完成！(耗时 %.1f 分钟, request_id: %s)", label, elapsed / 60, resp.request_id)
