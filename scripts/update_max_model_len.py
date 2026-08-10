"""
批量升级 SQLite 数据库中所有模型的 --max-model-len 上下文上限，满足全量性能压测项需求
"""
import sys
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import session_factory
from backend.models import ModelInfo, ModelDeviceConfig

# 根据模型规格匹配合理的 max-model-len 上下文上限
TARGET_MAX_LEN = {
    "gpt-oss-120b": 8192,
    "llama-3-1-70b": 16384,
    "gpt-oss-20b": 16384,
    "llama-3-1-8b": 16384,
    "llama-3-2-3b": 16384,
    "qwen3-4b": 16384,
    "qwen3-32b": 16384,
    "qwen3-vl-4b": 8192,
    "qwen3-vl-8b": 16384,
    "gemma-3-1b": 8192,
    "gemma-3-4b": 8192,
    "gemma-3-12b": 8192,
    "gemma-3-27b": 16384,
    "gemma-3-270m": 8192,
    "functiongemma": 8192,
    "cosmos-reason-1-7b": 8192,
    "cosmos-reason-2-2b": 8192,
    "cosmos-reason-2-8b": 8192,
    "nemotron-nano-12b-vl": 8192,
    "nemotron-nano-9b-v2": 8192,
}


def update_cmd_max_len(cmd: str, target_len: int) -> str:
    if not cmd:
        return cmd
    if "--max-model-len" in cmd:
        cmd = re.sub(r'--max-model-len\s+\d+', f'--max-model-len {target_len}', cmd)
    else:
        cmd = cmd.strip() + f" --max-model-len {target_len}"
    return cmd


def main():
    db = session_factory()
    models = db.query(ModelInfo).all()
    updated_count = 0

    print(f"开始升级 {len(models)} 个模型的 --max-model-len 上下文配置...")

    for m in models:
        slug = m.slug
        target_len = TARGET_MAX_LEN.get(slug, 8192)

        # 若原本已有较大设置 (如 32768)，保留较大值
        old_cmd = m.docker_command or ""
        m_len_match = re.search(r'--max-model-len\s+(\d+)', old_cmd)
        if m_len_match:
            curr_len = int(m_len_match.group(1))
            if curr_len > target_len:
                target_len = curr_len

        new_cmd = update_cmd_max_len(old_cmd, target_len)

        if old_cmd != new_cmd:
            m.docker_command = new_cmd
            updated_count += 1
            print(f"  [+] {slug:<28}: --max-model-len -> {target_len}")

        # 同步更新 ModelDeviceConfig 表
        dev_configs = db.query(ModelDeviceConfig).filter(ModelDeviceConfig.model_id == m.id).all()
        for dc in dev_configs:
            dc.docker_command = update_cmd_max_len(dc.docker_command or old_cmd, target_len)

    db.commit()
    print(f"\n✓ 成功升级 {updated_count} 个模型的 --max-model-len 启动配置！")


if __name__ == "__main__":
    main()
