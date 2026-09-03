#!/usr/bin/env python3
"""
列出对象存储(TOS)桶中的模型/对象。
用法:
  python3 scripts/tos_list.py                 # 列出桶内全部对象
  python3 scripts/tos_list.py models          # 按前缀过滤，如 models、models/qwen
  python3 scripts/tos_list.py models/qwen     # 只看 qwen 目录
  python3 scripts/tos_list.py <key> --top N   # 只看前 N 个
"""
import sys, os, logging
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
logging.basicConfig(level=logging.INFO, format="%(message)s")

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / "config" / ".env")
import tos

def human(n):
    for u in ["B","KB","MB","GB","TB"]:
        if n < 1024: return f"{n:.1f}{u}"
        n/=1024
    return f"{n:.1f}PB"

def main():
    prefix=sys.argv[1] if len(sys.argv)>1 else ""
    top=None
    for i,a in enumerate(sys.argv[2:],2):
        if a=="--top" and i+1<len(sys.argv):
            top=int(sys.argv[i+1])

    ak=os.getenv("TOS_ACCESS_KEY",""); sk=os.getenv("TOS_SECRET_KEY","")
    endpoint=os.getenv("TOS_ENDPOINT","https://tos-cn-guangzhou.volces.com")
    region=os.getenv("TOS_REGION","cn-guangzhou")
    bucket=os.getenv("TOS_BUCKET","ai-hub")
    if prefix and not prefix.endswith("/") and not (prefix.endswith(".tar.gz") or prefix.endswith(".gguf") or prefix.endswith(".tar")):
        prefix+="/"

    client=tos.TosClientV2(ak,sk,endpoint,region)
    out=client.list_objects_type2(bucket, prefix=prefix)
    items=[]
    for obj in out.contents:
        if obj.key.endswith("/") : continue
        items.append((obj.key, obj.size))

    items.sort()
    print(f"bucket: {bucket}  前缀: {prefix or '(全部)'}  对象数: {len(items)}")
    print("-"*70)
    total=0
    shown=items[:top] if top else items
    for key,size in shown:
        print(f"{key:<62} {human(size):>9}")
        total+=size
    if top and len(items)>top: print(f"... 还有 {len(items)-top} 个未显示")
    print("-"*70)
    print(f"总大小: {human(total)}  (显示 {len(shown)}/{len(items)} 个对象)")

if __name__=="__main__":
    main()
