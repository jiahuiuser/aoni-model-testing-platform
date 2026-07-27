"""
调度器 — 模型执行顺序、资源协调
"""
from typing import Optional


def sort_models_by_size(model_runs: list) -> list:
    """按参数量级排序：小模型优先（快速验证），大模型靠后"""
    size_order = {"ultra_light": 0, "small_medium": 1, "medium_large": 2, "moe": 1, "unknown": 99}
    return sorted(model_runs, key=lambda m: size_order.get(m.size_category, 99))


def get_next_model(model_runs: list, resume: bool = True) -> Optional:
    """
    获取下一个待执行的模型。
    resume=True: 跳过已完成的，优先执行失败/未完成的
    """
    from backend.models import ModelStage

    for model in sorted(model_runs, key=lambda m: m.model_idx):
        if model.status == ModelStage.DONE:
            continue
        return model
    return None
