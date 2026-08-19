#!/usr/bin/env python3
"""后台顺序执行所有替换，逐模型写状态到 logs/done.log（可跨命令轮询）"""
import os, sys, time, subprocess
from pathlib import Path
from importlib import import_module

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
DONE = PROJECT_ROOT/"logs"/"done.log"
KEY = PROJECT_ROOT/"logs"/"current_key.txt"

run_mod = import_module("scripts.replace_models_to_official")
MANIFEST = run_mod.MANIFEST

# 顺序（先 ModelScope 系，再 HF 小，再 HF 大）
ORDER = [
 "qwen3-8b","qwen3-4b","qwen3-30b-a3b","qwen3-32b",
 "gemma3-4b","gemma3-12b","gemma3-27b","llama3-1-8b",
 "qwen3-5-4b","qwen3-5-9b","qwen3-vl-4b","qwen3-vl-8b",
 "functiongemma","qwen3-5-27b","qwen3-6-27b","qwen3-5-35b-a3b",
 "gemma4-e2b","gemma4-e4b","gemma4-31b","llama3-2-3b",
 "nemotron-nano-9b-v2","nemotron3-nano-30b-a3b","cosmos-reason1-7b",
]

def done_set():
    s=set()
    if DONE.exists():
        for line in DONE.read_text().splitlines():
            line=line.strip()
            if line and "|" in line: s.add(line.split("|")[0])
    return s

os.environ["HF_TOKEN"] = os.environ.get("HF_TOKEN","")
done=done_set()
for k in ORDER:
    if k in done:
        print("skip(已done)", k)
        continue
    KEY.write_text(k)
    print(">>> 开始", k, flush=True)
    r=subprocess.run([sys.executable, str(PROJECT_ROOT/"scripts/replace_models_to_official.py"), k],
                     capture_output=True, text=True)
    tail="\n".join(r.stdout.splitlines()[-3:])
    import shutil
    free=shutil.disk_usage("/home/sd1/models").free/2**30
    with open(DONE,"a") as f:
        f.write(f"{k}|{time.strftime('%F %T')}|{free:.1f}GB|{tail}\n")
    print(">>> 完成", k, flush=True)
print("ALL_DONE")
