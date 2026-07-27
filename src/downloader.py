import os
import time
import shutil
import tarfile
import logging
import subprocess
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / "config" / ".env")
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger(__name__)

def get_disk_free_gb(path="/home/sd1/models") -> float:
    """获取指定路径所在磁盘分区的剩余可用空间 (GB)"""
    try:
        total, used, free = shutil.disk_usage(str(path))
        return free / (1024 ** 3)
    except Exception:
        parent = os.path.dirname(path) or "/"
        total, used, free = shutil.disk_usage(parent)
        return free / (1024 ** 3)

def check_disk_space(path="/home/sd1/models", min_free_gb=100.0) -> float:
    """检查剩余空间，若低于 min_free_gb 则抛出 RuntimeError 阻止操作以保护系统磁盘安全"""
    free_gb = get_disk_free_gb(path)
    log.info("  [Disk Check] 当前磁盘剩余空间: %.2f GB (最低安全阈值: %.2f GB)", free_gb, min_free_gb)
    if free_gb < min_free_gb:
        err_msg = (
            f"❌ 磁盘安全限制激活: 当前可用空间仅剩 {free_gb:.2f} GB，"
            f"低于要求的 {min_free_gb:.2f} GB 安全线！放弃执行以防止撑爆磁盘导致系统故障。"
        )
        log.error(err_msg)
        raise RuntimeError(err_msg)
    return free_gb

def download_with_modelscope(repo_id, local_dir, include=None, min_free_gb=100.0):
    """使用 ModelScope snapshot_download 下载模型（包含磁盘 100G 安全校验）"""
    from modelscope.hub.snapshot_download import snapshot_download

    # 下载前先做磁盘 100G 安全预检
    check_disk_space(local_dir, min_free_gb=min_free_gb)

    log.info("  [ModelScope] 开始下载仓库: %s → %s", repo_id, local_dir)
    os.makedirs(local_dir, exist_ok=True)
    
    # 强制开启 16 线程高速切片下载
    os.environ["MODELSCOPE_DOWNLOAD_PARALLELS"] = "16"
    
    start_time = time.time()
    kwargs = dict(
        repo_id=repo_id,
        local_dir=local_dir,
    )
    if include:
        kwargs["allow_patterns"] = include

    snapshot_download(**kwargs)

    # 下载完成后再次校验磁盘空间
    check_disk_space(local_dir, min_free_gb=min_free_gb)

    elapsed = time.time() - start_time
    total_gb = (
        sum(
            os.path.getsize(os.path.join(dp, f))
            for dp, dn, fn in os.walk(local_dir)
            for f in fn
        )
        / (1024**3)
    )
    log.info("  [ModelScope] 下载完成 (总计 %.2f GB, 耗时 %.1f 分钟)", total_gb, elapsed / 60)
    return total_gb

def download_with_huggingface(repo_id, local_dir, include=None, min_free_gb=100.0):
    """使用 HuggingFace snapshot_download 下载模型（包含磁盘 100G 安全校验与代理配置）"""
    from huggingface_hub import snapshot_download

    # 设置网络代理与磁盘缓存目录
    os.environ["HTTP_PROXY"] = os.getenv("HTTP_PROXY", "http://127.0.0.1:7897")
    os.environ["HTTPS_PROXY"] = os.getenv("HTTPS_PROXY", "http://127.0.0.1:7897")
    if os.getenv("HF_TOKEN"):
        os.environ["HF_TOKEN"] = os.getenv("HF_TOKEN")
    os.environ["HF_HOME"] = os.getenv("HF_HOME", "/home/sd1/models/.hf_cache")

    check_disk_space(local_dir, min_free_gb=min_free_gb)

    log.info("  [HuggingFace] 开始下载仓库: %s → %s", repo_id, local_dir)
    os.makedirs(local_dir, exist_ok=True)

    start_time = time.time()
    kwargs = dict(
        repo_id=repo_id,
        local_dir=local_dir,
    )
    if include:
        kwargs["allow_patterns"] = include

    snapshot_download(**kwargs)

    check_disk_space(local_dir, min_free_gb=min_free_gb)

    elapsed = time.time() - start_time
    total_gb = (
        sum(
            os.path.getsize(os.path.join(dp, f))
            for dp, dn, fn in os.walk(local_dir)
            for f in fn
        )
        / (1024**3)
    )
    log.info("  [HuggingFace] 下载完成 (总计 %.2f GB, 耗时 %.1f 分钟)", total_gb, elapsed / 60)
    return total_gb

def create_tarball(source_dir, output_path, label="", min_free_gb=100.0):
    """将源目录打包为 tar.gz 文件，包含磁盘 100G 安全校验，并以系统 tar 命令加速打包过程"""
    output_dir = os.path.dirname(output_path) or "/home/sd1/models"
    check_disk_space(output_dir, min_free_gb=min_free_gb)

    log.info("  [Tarball] 开始打包目录 %s → %s", label, output_path)
    start_time = time.time()
    
    parent_dir = os.path.dirname(source_dir)
    base_name = os.path.basename(source_dir)
    # 使用系统 tar 结合 pigz 并行多线程压缩
    cmd = f"tar -I pigz -cf {output_path} -C {parent_dir} {base_name}"
    subprocess.run(cmd, shell=True, check=True)
        
    elapsed = time.time() - start_time
    size_gb = os.path.getsize(output_path) / (1024**3)
    log.info("  [Tarball] 打包完成 (Gzip 大小 %.2f GB, 耗时 %.1f 分钟)", size_gb, elapsed / 60)
    
    # 打包完成后再次校验剩余空间
    check_disk_space(output_dir, min_free_gb=min_free_gb)
    return size_gb
