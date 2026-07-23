"""
数据集下载模块

从 ModelScope (魔搭社区) 下载准确率评测所需的标准数据集。
支持的数据集: MMLU, C-Eval, GSM8K, ARC-Challenge, HumanEval
"""
import os
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# 可用评测数据集列表及其 ModelScope 仓库 ID
DATASET_REGISTRY = {
    "mmlu": {
        "repo": "modelscope/mmlu",
        "description": "MMLU - 57学科综合知识评测 (英文)",
        "subset": "full",
    },
    "ceval": {
        "repo": "modelscope/ceval-exam",
        "description": "C-Eval - 52学科中文知识评测",
        "subset": "full",
    },
    "cmmlu": {
        "repo": "modelscope/cmmlu",
        "description": "CMMLU - 中文语言与理解评测",
        "subset": "full",
    },
    "gsm8k": {
        "repo": "modelscope/gsm8k",
        "description": "GSM8K - 数学多步推理评测",
        "subset": "full",
    },
    "humaneval": {
        "repo": "modelscope/humaneval",
        "description": "HumanEval - Python代码生成评测",
        "subset": "full",
    },
    "arc": {
        "repo": "modelscope/ai2_arc",
        "description": "ARC-Challenge - 科学推理评测",
        "subset": "ARC-Challenge",
    },
}


def download_dataset(dataset_name: str, save_dir: Path) -> bool:
    """从 ModelScope 下载指定评测数据集到本地目录"""
    if dataset_name not in DATASET_REGISTRY:
        log.error(f"未知数据集: {dataset_name}，可用: {list(DATASET_REGISTRY.keys())}")
        return False

    info = DATASET_REGISTRY[dataset_name]
    target_dir = save_dir / dataset_name

    if target_dir.exists() and any(target_dir.iterdir()):
        log.info(f"数据集 {dataset_name} 已存在，跳过下载: {target_dir}")
        return True

    target_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"正在从 ModelScope 下载数据集: {dataset_name} ({info['description']})")

    try:
        from modelscope.msdatasets import MsDataset
        MsDataset.load(
            info["repo"],
            subset_name=info.get("subset"),
            cache_dir=str(target_dir),
        )
        log.info(f"数据集 {dataset_name} 下载完成 -> {target_dir}")
        return True
    except ImportError:
        log.error("modelscope 未安装，请执行: pip install modelscope")
        return False
    except Exception as e:
        log.error(f"下载数据集 {dataset_name} 失败: {e}")
        return False


def download_all_datasets(save_dir: Path, datasets: list[str] | None = None) -> dict[str, bool]:
    """批量下载所有或指定评测数据集"""
    if datasets is None:
        datasets = list(DATASET_REGISTRY.keys())

    results = {}
    for name in datasets:
        results[name] = download_dataset(name, save_dir)
    return results


def get_available_datasets() -> list[str]:
    """返回可用的数据集名称列表"""
    return list(DATASET_REGISTRY.keys())
