#!/usr/bin/env python3
"""
逐模型：本地全精度 -> 官网量化版 替换执行器
用法: python3 scripts/replace_models_to_official.py <model_key>
日志: logs/model_replace_YYYYMMDD.log
进度: logs/PROGRESS_model_replace_YYYYMMDD.md
"""
import os, sys, json, time, shutil, logging, subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(PROJECT_ROOT/"logs"/"model_replace_20260818.log")])
log = logging.getLogger("replace")

MODELS = "/home/sd1/models"
PROGRESS_MD = PROJECT_ROOT/"logs"/"PROGRESS_model_replace_20260818.md"
MIN_FREE_GB = 60.0

from src.downloader import download_with_modelscope, download_with_huggingface, create_tarball, check_disk_space

def free_gb():
    t,u,f = shutil.disk_usage(MODELS)
    return f/(1024**3)

LOCK_DIR = PROJECT_ROOT/"logs"
def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return ProcessLookupError and False
    except Exception:
        return False

def acquire_single_instance_lock(key):
    """同 key 只允许一个实例：若已有存活进程正在处理该 key 则拒绝并退出，
    避免两个 snapshot_download 并发写同一 local_dir（锁冲突/临时文件互删/带宽争抢）。"""
    lock = LOCK_DIR / f"replace_{key}.pid"
    try:
        if lock.exists():
            try:
                old = int(lock.read_text().strip().split()[0])
            except Exception:
                old = None
            if old and _pid_alive(old):
                log.error(f"[{key}] 已有实例 pid={old} 正在处理该模型，本实例退出，避免重复下载")
                sys.exit(3)
            else:
                lock.unlink(missing_ok=True)
        lock.write_text(f"{os.getpid()} {time.strftime('%F %T')}\n")
    except Exception as e:
        log.warning(f"[{key}] 单实例锁处理异常(继续运行): {e}")
    return lock

def release_single_instance_lock(lock):
    try:
        if lock is not None and lock.exists():
            lock.unlink()
    except Exception:
        pass

def hf_download(repo, target):
    # 用官方 hf_xet 高速通道（1.24 中 Xet 即高速传输）；hf_transfer 已废弃，关闭以免干扰。
    # 前置：VPN/代理(127.0.0.1:7897)需保持开启，以保证 Xet 端点可达。
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
    os.environ.pop("HF_HUB_DISABLE_XET", None)
    os.environ.pop("HF_XET", None)
    os.environ.pop("HF_XET_HIGH_PERFORMANCE", None)
    os.environ["HF_HOME"] = "/home/sd1/models/.hf_cache"
    for k in ["ALL_PROXY","all_proxy"]: os.environ.pop(k, None)
    os.environ["HTTP_PROXY"]="http://127.0.0.1:7897"
    os.environ["HTTPS_PROXY"]="http://127.0.0.1:7897"
    if os.getenv("HF_TOKEN"): os.environ["HF_TOKEN"]=os.getenv("HF_TOKEN")
    download_with_huggingface(repo, target)

def ms_download(repo, target):
    os.environ["MODELSCOPE_DOWNLOAD_PARALLELS"]="16"
    # 清理陈旧 ModelScope 锁，避免卡死
    lockdir="/home/sd1/models/.ms_cache/.lock"
    if os.path.isdir(lockdir):
        shutil.rmtree(lockdir, ignore_errors=True)
    download_with_modelscope(repo, target)

def dir_gb(d):
    t=0
    for dp,dn,fn in os.walk(d):
        for f in fn:
            try: t+=os.path.getsize(os.path.join(dp,f))
            except: pass
    return t/(2**30)

def verify_target(repo, target):
    """粗校验：有权重文件、无 .incomplete、config 存在"""
    weight_exts=(".safetensors",".gguf",".pt",".bin")
    n=0; cfg=False; incomplete=False
    for dp,dn,fn in os.walk(target):
        for f in fn:
            if file:= os.path.join(dp,f):
                if f.endswith(".incomplete") or os.path.exists(file+".incomplete"):
                    incomplete=True
                if f.endswith(weight_exts): n+=1
                if f=="config.json": cfg=True
    if incomplete or n==0:
        return False
    return True

MANIFEST = {
 "qwen3-32b": dict(name="Qwen3-32B", hf="RedHatAI/Qwen3-32B-quantized.w4a16", ms="RedHatAI/Qwen3-32B-quantized.w4a16", src=f"{MODELS}/qwen/Qwen3-32B-quantized.w4a16", old=[f"{MODELS}/qwen/Qwen3-32B"], link=None),
 "qwen3-30b-a3b": dict(name="Qwen3-30B-A3B", hf="RedHatAI/Qwen3-30B-A3B-quantized.w4a16", ms="RedHatAI/Qwen3-30B-A3B-quantized.w4a16", src=f"{MODELS}/qwen/Qwen3-30B-A3B-quantized.w4a16", old=[f"{MODELS}/qwen/Qwen3-30B-A3B"], link="qwen3-30b-a3b"),
 "qwen3-8b": dict(name="Qwen3-8B", hf="RedHatAI/Qwen3-8B-quantized.w4a16", ms="RedHatAI/Qwen3-8B-quantized.w4a16", src=f"{MODELS}/qwen/Qwen3-8B-quantized.w4a16", old=[f"{MODELS}/qwen/Qwen3-8B"], link="qwen3-8b"),
 "qwen3-4b": dict(name="Qwen3-4B", hf="RedHatAI/Qwen3-4B-quantized.w4a16", ms="RedHatAI/Qwen3-4B-quantized.w4a16", src=f"{MODELS}/qwen/Qwen3-4B-quantized.w4a16", old=[f"{MODELS}/qwen/Qwen3-4B"], link="qwen3-4b"),
 "qwen3-5-27b": dict(name="Qwen3.5-27B", hf="Kbenkhaled/Qwen3.5-27B-NVFP4", ms=None, src=f"{MODELS}/qwen/Qwen3.5-27B-NVFP4", old=[f"{MODELS}/qwen/Qwen3.5-27B"], link="qwen3-5-27b"),
 "qwen3-5-35b-a3b": dict(name="Qwen3.5-35B-A3B", hf="AxionML/Qwen3.5-35B-A3B-NVFP4", ms=None, src=f"{MODELS}/qwen/Qwen3.5-35B-A3B-NVFP4", old=[f"{MODELS}/qwen/Qwen3.5-35B-A3B"], link="qwen3-5-35b-a3b"),
 "qwen3-5-9b": dict(name="Qwen3.5-9B", hf="AxionML/Qwen3.5-9B-NVFP4", ms=None, src=f"{MODELS}/qwen/Qwen3.5-9B-NVFP4", old=[f"{MODELS}/qwen/Qwen3.5-9B"], link="qwen3-5-9b"),
 "qwen3-5-4b": dict(name="Qwen3.5-4B", hf="AxionML/Qwen3.5-4B-NVFP4", ms=None, src=f"{MODELS}/qwen/Qwen3.5-4B-NVFP4", old=[f"{MODELS}/qwen/Qwen3.5-4B"], link="qwen3-5-4b"),
 "qwen3-6-27b": dict(name="Qwen3.6-27B", hf="nvidia/Qwen3.6-27B-NVFP4", ms=None, src=f"{MODELS}/qwen/Qwen3.6-27B-NVFP4", old=[f"{MODELS}/qwen/Qwen3.6-27B"], link="qwen3-6-27b"),
 "qwen3-vl-8b": dict(name="Qwen3-VL-8B", hf="cpatonn/Qwen3-VL-8B-Instruct-AWQ-4bit", ms=None, src=f"{MODELS}/qwen/Qwen3-VL-8B-AWQ", old=[f"{MODELS}/qwen/Qwen3-VL-8B-Instruct"], link="qwen3-vl-8b"),
 "qwen3-vl-4b": dict(name="Qwen3-VL-4B", hf="cpatonn/Qwen3-VL-4B-Instruct-AWQ-4bit", ms=None, src=f"{MODELS}/qwen/Qwen3-VL-4B-AWQ", old=[f"{MODELS}/qwen/Qwen3-VL-4B-Instruct"], link="qwen3-vl-4b"),
 # Gemma
 "gemma3-27b": dict(name="gemma3-27b", hf="RedHatAI/gemma-3-27b-it-quantized.w4a16", ms="RedHatAI/gemma-3-27b-it-quantized.w4a16", src=f"{MODELS}/gemma/gemma-3-27b-w4a16", old=[f"{MODELS}/gemma/gemma-3-27b"], link="gemma-3-27b"),
 "gemma3-12b": dict(name="gemma3-12b", hf="RedHatAI/gemma-3-12b-it-quantized.w4a16", ms="RedHatAI/gemma-3-12b-it-quantized.w4a16", src=f"{MODELS}/gemma/gemma-3-12b-w4a16", old=[f"{MODELS}/gemma/gemma-3-12b"], link="gemma-3-12b"),
 "gemma3-4b": dict(name="gemma3-4b", hf="RedHatAI/gemma-3-4b-it-quantized.w4a16", ms="RedHatAI/gemma-3-4b-it-quantized.w4a16", src=f"{MODELS}/gemma/gemma-3-4b-w4a16", old=[f"{MODELS}/gemma/gemma-3-4b"], link="gemma-3-4b"),
 "gemma4-31b": dict(name="Gemma-4-31B", hf="nvidia/Gemma-4-31B-IT-NVFP4", ms=None, src=f"{MODELS}/gemma/Gemma-4-31B-NVFP4", old=[f"{MODELS}/gemma/Gemma-4-31B"], link="gemma-4-31b"),
 "gemma4-e2b": dict(name="Gemma-4-E2B", hf="unsloth/gemma-4-E2B-it-NVFP4", ms=None, src=f"{MODELS}/gemma/Gemma-4-E2B-NVFP4", old=[f"{MODELS}/google/Gemma-4-E2B-GGUF"], link="gemma-4-e2b"),
 "gemma4-e4b": dict(name="Gemma-4-E4B", hf="unsloth/gemma-4-E4B-it-NVFP4", ms=None, src=f"{MODELS}/gemma/Gemma-4-E4B-NVFP4", old=[f"{MODELS}/google/Gemma-4-E4B-GGUF"], link="gemma-4-e4b"),
 "functiongemma": dict(name="functiongemma", hf="ggml-org/functiongemma-270m-it-GGUF", ms=None, src=f"{MODELS}/gemma/functiongemma-270m-it-GGUF", old=[f"{MODELS}/gemma/functiongemma-270m-it"], link="functiongemma"),
 # Llama
 "llama3-1-8b": dict(name="Llama-3.1-8B", hf="RedHatAI/Meta-Llama-3.1-8B-Instruct-quantized.w4a16", ms="RedHatAI/Meta-Llama-3.1-8B-Instruct-quantized.w4a16", src=f"{MODELS}/llama/Meta-Llama-3.1-8B-Instruct-quantized.w4a16", old=[f"{MODELS}/llama/Llama-3.1-8B"], link="llama-3-1-8b"),
 "llama3-2-3b": dict(name="Llama-3.2-3B", hf="espressor/meta-llama.Llama-3.2-3B-Instruct_W4A16", ms=None, src=f"{MODELS}/llama/Llama-3.2-3B-w4a16", old=[f"{MODELS}/llama/Llama-3.2-3B"], link="llama-3-2-3b"),
 # NVIDIA
 "nemotron-nano-9b-v2": dict(name="Nemotron-Nano-9B-v2", hf="nvidia/NVIDIA-Nemotron-Nano-9B-v2-NVFP4", ms=None, src=f"{MODELS}/nvidia/Nemotron-Nano-9B-v2-NVFP4", old=[f"{MODELS}/nvidia/Nemotron-Nano-9B-v2", f"{MODELS}/nemotron/Nemotron-Nano-9B-v2"], link="nemotron-nano-9b-v2"),
 "nemotron3-nano-30b-a3b": dict(name="Nemotron3-Nano-30B-A3B", hf="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4", ms=None, src=f"{MODELS}/nvidia/Nemotron3-Nano-30B-A3B-NVFP4", old=[f"{MODELS}/nvidia/Nemotron3-Nano-30B-A3B"], link="nemotron3-nano-30b-a3b"),
 "cosmos-reason1-7b": dict(name="Cosmos-Reason1-7B", hf="nvidia/Cosmos-Reason1-7B", ms=None, src=f"{MODELS}/nvidia/Cosmos-Reason1-7B", old=[], link=None),
}

def update_progress(status_by_key):
    # 简单：append 一行到 log 即可；md 用单独手动维护
    pass

def main():
    key=sys.argv[1]
    m=MANIFEST[key]
    name=m["name"]; repo=m["hf"]; ms=m.get("ms"); src=m["src"]
    lock = acquire_single_instance_lock(key)
    try:
        return _run(key, m, lock)
    finally:
        release_single_instance_lock(lock)

def _run(key, m, lock):
    name=m["name"]; repo=m["hf"]; ms=m.get("ms"); src=m["src"]
    log.info(f"===== [{name}] 开始  磁盘剩余 {free_gb():.1f}GB =====")

    # 1 磁盘预检
    if free_gb() < MIN_FREE_GB:
        log.error(f"[{name}] 磁盘剩余 {free_gb():.1f}GB < {MIN_FREE_GB}GB，跳过（需先回收空间）")
        return "SKIP_DISK"

    # 2 清理目标残留
    if os.path.isdir(src):
        log.info(f"[{name}] 清理目标残留 {src}")
        shutil.rmtree(src)

    # 3 下载（自动重试，HF 从缓存续传）
    os.makedirs(src, exist_ok=True)
    last_err=None
    for attempt in range(1, 4):
        try:
            if m.get("ms"):
                log.info(f"[{name}] ModelScope 下载 {ms} -> {src} (尝试{attempt})")
                ms_download(ms, src)
            else:
                log.info(f"[{name}] HF 下载 {repo} -> {src} (尝试{attempt})")
                hf_download(repo, src)
            last_err=None
            break
        except Exception as e:
            last_err=e
            log.error(f"[{name}] 第{attempt}次下载失败: {repr(e)}，清理残留后重试")
            if os.path.isdir(src):
                shutil.rmtree(src, ignore_errors=True)
            if attempt < 3:
                time.sleep(30)
    if last_err is not None:
        log.error(f"[{name}] 下载失败(3次): {repr(last_err)}")
        return "FAIL_DOWNLOAD"

    # 4 校验
    ok=verify_target(repo, src)
    size=dir_gb(src)
    if not ok:
        log.error(f"[{name}] 校验失败 (无权重/ .incomplete)，保留，不删除旧模型")
        return "FAIL_VERIFY"
    log.info(f"[{name}] 校验通过, {size:.1f}GB")

    # 5 删除旧全精度
    for old in m["old"]:
        if os.path.exists(old):
            log.info(f"[{name}] 删除旧全精度 {old} ({dir_gb(old):.1f}GB)")
            shutil.rmtree(old)
    # 清理空父目录/符号链接
    if m.get("link"):
        ln=f"{MODELS}/{m['link']}"
        try:
            if os.path.islink(ln): os.unlink(ln)
            elif os.path.exists(ln): shutil.rmtree(ln)
            os.symlink(src, ln)
            log.info(f"[{name}] 重指符号链接 {ln} -> {src}")
        except Exception as e:
            log.warning(f"[{name}] 符号链接处理: {e}")
    log.info(f"[{name}] 完成 ✅  磁盘剩余 {free_gb():.1f}GB")
    return "DONE"

if __name__=="__main__":
    r=main()
    print("RESULT", r)
