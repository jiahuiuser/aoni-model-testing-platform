"""
Pipeline Engine — 模型参数量级映射 & 并发梯度规则
"""
import csv
from pathlib import Path
from backend.config import DATA_DIR

DEFAULT_CONCURRENCY_MAP = {
    "ultra_light": [1, 4, 8, 16, 32],
    "small_medium": [1, 2, 4, 8, 16],
    "medium_large": [1, 2, 4, 8],
    "moe": [1, 4, 8, 16, 32],
}


def get_size_category_map() -> dict[str, str]:
    """从 benchmark_strategies.csv 读取 slug → size_category 映射"""
    strategy_csv = DATA_DIR / "benchmark_strategies.csv"
    size_map = {}
    if strategy_csv.exists():
        with open(strategy_csv, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                slug = row["模型slug"].strip()
                cat = row["参数量级"].strip()
                if slug not in size_map:
                    size_map[slug] = cat
    return size_map


def get_concurrency_for_category(size_category: str) -> list[int]:
    """根据参数量级获取推荐并发梯度"""
    return DEFAULT_CONCURRENCY_MAP.get(size_category, [1, 2, 4, 8])
