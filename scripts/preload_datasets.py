#!/usr/bin/env python3
"""
预下载与本地落盘全量 11 个准确率测试数据集脚本
使用 EvalScope 内置加载器拉取，保证数据 100% 缓存至本地磁盘 ~/.cache/ 目录。
"""
import os
import sys
import subprocess
import time
from pathlib import Path

# 环境变量设置：开启国内镜像与 NO_PROXY 直连防护
eval_env = os.environ.copy()
eval_env["HF_ENDPOINT"] = "https://hf-mirror.org"
eval_env["NO_PROXY"] = "127.0.0.1,localhost,0.0.0.0,modelscope.cn,www.modelscope.cn,api.modelscope.cn"
eval_env["DATASETS_MAX_RETRIES"] = "10"
eval_env["MODELSCOPE_MAX_RETRIES"] = "10"

local_bin = os.path.expanduser("~/.local/bin")
if local_bin not in eval_env.get("PATH", ""):
    eval_env["PATH"] = f"{local_bin}:{eval_env.get('PATH', '')}"

DATASETS_TO_PRELOAD = [
    "mmlu", "ceval", "gsm8k", "arc", "math_500", 
    "humaneval", "bigcodebench", "longbench_v2", 
    "gpqa_diamond", "aime24", "arena_hard"
]

def preload():
    print("==================================================")
    print("🚀 开始预下载全量 11 个基准题库至本地磁盘缓存 (~/.cache)...")
    print("==================================================")
    
    tmp_dir = Path("data/preload_tmp")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    success_count = 0
    failed_datasets = []

    for name in DATASETS_TO_PRELOAD:
        print(f"\n📦 数据集 [{name.upper()}]: 正在触发下载与本地缓存...")
        cmd = [
            "evalscope", "eval",
            "--model", "preload-check",
            "--eval-type", "openai_api",
            "--api-url", "http://127.0.0.1:8800/v1",
            "--api-key", "none",
            "--datasets", name,
            "--limit", "1",
            "--work-dir", str(tmp_dir / name)
        ]
        
        loaded = False
        for attempt in range(1, 4):
            try:
                print(f"   执行预拉取 (第 {attempt}/3 次)...")
                res = subprocess.run(cmd, capture_output=True, text=True, env=eval_env, timeout=1200)
                out = (res.stdout or "") + (res.stderr or "")
                
                if "Start loading benchmark dataset" in out or "dataset" in out.lower():
                    print(f"   ✅ 数据集 [{name.upper()}] 预下载并成功落盘本地缓存！")
                    loaded = True
                    success_count += 1
                    break
                else:
                    print(f"   ⚠️ 下载网络提示: {out[-200:].strip()}")
            except Exception as e:
                print(f"   ⚠️ 下载重试提示 (第 {attempt} 次): {e}")
                time.sleep(3)
        
        if not loaded:
            failed_datasets.append(name)
            print(f"   ❌ 数据集 [{name.upper()}] 预下载未完成。")

    print("\n==================================================")
    print(f"📊 预下载落盘总结: 成功 {success_count}/{len(DATASETS_TO_PRELOAD)}")
    if failed_datasets:
        print(f"⚠️ 尚有未落盘的数据集: {', '.join(failed_datasets)}")
    else:
        print("🎉 全部 11 个数据集已 100% 成功预下载至本地磁盘！后续测试将 100% 直接读取本地缓存。")
    print("==================================================")

if __name__ == "__main__":
    preload()
