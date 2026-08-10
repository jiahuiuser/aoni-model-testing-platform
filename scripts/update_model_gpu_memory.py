"""
批量优化 SQLite 数据库中所有模型的 --gpu-memory-utilization 显存分配策略
"""
import sys
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import session_factory
from backend.models import ModelInfo, ModelDeviceConfig

LARGE_SLUGS = {"gpt-oss-120b", "llama-3-1-70b"}
MEDIUM_SLUGS = {
    "gemma-3-12b", "gemma-3-27b", "gemma-4-26b-a4b", "gemma-4-31b",
    "gpt-oss-20b", "ministral-3-14b-instruct", "ministral-3-14b-reasoning",
    "nemotron-nano-12b-vl", "nemotron-nano-9b-v2", "nemotron3-nano-30b-a3b",
    "qwen3-30b-a3b", "qwen3-32b", "qwen3-5-27b", "qwen3-5-35b-a3b",
    "qwen3-5-9b", "qwen3-6-27b", "qwen3-6-35b-a3b"
}


def update_cmd_memory(cmd: str, target_util: float) -> str:
    if not cmd:
        return cmd
    if "--gpu-memory-utilization" in cmd:
        cmd = re.sub(r'--gpu-memory-utilization\s+[0-9\.]+', f'--gpu-memory-utilization {target_util}', cmd)
    else:
        cmd = cmd.strip() + f" --gpu-memory-utilization {target_util}"
    return cmd


def main():
    db = session_factory()
    models = db.query(ModelInfo).all()
    updated_count = 0

    print(f"开始对 {len(models)} 个模型更新显存利用率配置...")

    for m in models:
        slug = m.slug
        if slug in LARGE_SLUGS:
            target_util = 0.85
        elif slug in MEDIUM_SLUGS:
            target_util = 0.80
        else:
            target_util = 0.70

        old_cmd = m.docker_command or ""
        new_cmd = update_cmd_memory(old_cmd, target_util)

        # 针对 gpt-oss-120b 确保环境挂载正确
        if slug == "gpt-oss-120b" and "TIKTOKEN_ENCODINGS_BASE" not in new_cmd:
            new_cmd = (
                "sudo docker run -it --rm --pull always --runtime=nvidia --network host "
                "-v $HOME/.cache/huggingface:/root/.cache/huggingface "
                "-v $HOME/.cache/tiktoken:/etc/encodings "
                "-e TIKTOKEN_ENCODINGS_BASE=/etc/encodings "
                "vllm/vllm-openai:latest "
                f"openai/gpt-oss-120b --port 8300 --gpu-memory-utilization {target_util}"
            )

        if old_cmd != new_cmd:
            m.docker_command = new_cmd
            updated_count += 1

        # 同步更新 ModelDeviceConfig 表
        dev_configs = db.query(ModelDeviceConfig).filter(ModelDeviceConfig.model_id == m.id).all()
        for dc in dev_configs:
            dc.docker_command = update_cmd_memory(dc.docker_command or old_cmd, target_util)

    db.commit()
    print(f"已成功更新 {updated_count} 个模型的显存参数与启动命令！")


if __name__ == "__main__":
    main()
