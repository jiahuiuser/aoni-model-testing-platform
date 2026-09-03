#!/usr/bin/env python3
"""
打包并上传本次替换/下载的量化模型到 TOS 桶。
用法: python3 scripts/upload_to_official_tos.py            # 全量
      python3 scripts/upload_to_official_tos.py <key>     # 单个
TOS key 对齐: models/<vendor>/<name>.tar.gz
"""
import os, sys, logging, shutil
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(PROJECT_ROOT/"logs"/"model_replace_20260818.log")])
log=logging.getLogger("tos")
ENV=PROJECT_ROOT/"config"/".env"
MODELS="/home/sd1/models"
from src.downloader import create_tarball, check_disk_space
from src.uploader import load_tos_client, upload_to_tos

MODELS_TOS = [
 ("qwen/Qwen3-32B-quantized.w4a16","models/qwen/Qwen3-32B-quantized.w4a16.tar.gz"),
 ("qwen/Qwen3-30B-A3B-quantized.w4a16","models/qwen/Qwen3-30B-A3B-quantized.w4a16.tar.gz"),
 ("qwen/Qwen3-8B-quantized.w4a16","models/qwen/Qwen3-8B-quantized.w4a16.tar.gz"),
 ("qwen/Qwen3-4B-quantized.w4a16","models/qwen/Qwen3-4B-quantized.w4a16.tar.gz"),
 ("qwen/Qwen3.5-27B-NVFP4","models/qwen/Qwen3.5-27B-NVFP4.tar.gz"),
 ("qwen/Qwen3.5-35B-A3B-NVFP4","models/qwen/Qwen3.5-35B-A3B-NVFP4.tar.gz"),
 ("qwen/Qwen3.5-9B-NVFP4","models/qwen/Qwen3.5-9B-NVFP4.tar.gz"),
 ("qwen/Qwen3.5-4B-NVFP4","models/qwen/Qwen3.5-4B-NVFP4.tar.gz"),
 ("qwen/Qwen3.6-27B-NVFP4","models/qwen/Qwen3.6-27B-NVFP4.tar.gz"),
 ("qwen/Qwen3-VL-8B-AWQ","models/qwen/Qwen3-VL-8B-AWQ.tar.gz"),
 ("qwen/Qwen3-VL-4B-AWQ","models/qwen/Qwen3-VL-4B-AWQ.tar.gz"),
 ("gemma/gemma-3-27b-w4a16","models/gemma/gemma-3-27b-w4a16.tar.gz"),
 ("gemma/gemma-3-12b-w4a16","models/gemma/gemma-3-12b-w4a16.tar.gz"),
 ("gemma/gemma-3-4b-w4a16","models/gemma/gemma-3-4b-w4a16.tar.gz"),
 ("gemma/Gemma-4-31B-NVFP4","models/gemma/Gemma-4-31B-NVFP4.tar.gz"),
 ("gemma/Gemma-4-E2B-NVFP4","models/gemma/Gemma-4-E2B-NVFP4.tar.gz"),
 ("gemma/Gemma-4-E4B-NVFP4","models/gemma/Gemma-4-E4B-NVFP4.tar.gz"),
 ("gemma/functiongemma-270m-it-GGUF","models/gemma/functiongemma-270m-it-GGUF.tar.gz"),
 ("llama/Meta-Llama-3.1-8B-Instruct-quantized.w4a16","models/llama/Meta-Llama-3.1-8B-Instruct-quantized.w4a16.tar.gz"),
 ("llama/Llama-3.2-3B-w4a16","models/llama/Llama-3.2-3B-w4a16.tar.gz"),
 ("nvidia/Nemotron-Nano-9B-v2-NVFP4","models/nvidia/Nemotron-Nano-9B-v2-NVFP4.tar.gz"),
 ("nvidia/Nemotron3-Nano-30B-A3B-NVFP4","models/nvidia/Nemotron3-Nano-30B-A3B-NVFP4.tar.gz"),
 ("nvidia/Cosmos-Reason1-7B","models/nvidia/Cosmos-Reason1-7B.tar.gz"),
]

def process(client,bucket, local_rel, tos_key):
    local_dir=os.path.join(MODELS, local_rel)
    name=local_rel.split("/")[-1]
    if not os.path.isdir(local_dir):
        log.warning(f"本地目录不存在，跳过: {local_dir}"); return False
    check_disk_space(MODELS, min_free_gb=60.0)
    tarball=os.path.join(MODELS, name+".tar.gz")
    log.info(f"打包 {local_dir} -> {tarball}")
    create_tarball(local_dir, tarball, label=name, min_free_gb=60.0)
    upload_to_tos(client, bucket, tarball, tos_key, label=name)
    if os.path.exists(tarball):
        os.remove(tarball); log.info(f"已清理本地 tarball {tarball}")

def main():
    only=sys.argv[1] if len(sys.argv)>1 else None
    client,bucket=load_tos_client(str(ENV))
    log.info(f"TOS 认证成功 (bucket={bucket})")
    ok=skip=0
    for rel,key in MODELS_TOS:
        if only and only not in rel: continue
        name=rel.split("/")[-1]
        if os.path.isdir(os.path.join(MODELS,rel)):
            try:
                process(client,bucket,rel,key); ok+=1
            except Exception as e:
                log.error(f"[{name}] 失败: {repr(e)}")
        else:
            log.warning(f"[{name}] 目录缺失，跳过"); skip+=1
    log.info(f"TOS 上传全流程完成: 成功 {ok}, 跳过 {skip}")

if __name__=="__main__":
    main()
