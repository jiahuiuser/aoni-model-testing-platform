"""
大模型测试平台 — 功能测试模块注册表

每个功能测试模块统一暴露 run(base_url, model, api_key="", options=None, log_callback=None) -> dict
返回 dict 结构: {category, feature_key, test_item, status, latency_ms, message, raw_details}
status: PASS / FAIL / SKIP (模型不支持该特性, 不算失败)
"""
from backend.services.features import (
    agent_replay,
    garble,
    math_correctness,
    multimodal,
    needle,
    tool_smoke,
)

# 功能测试项注册表 (key -> 模块信息)
ITEMS = {
    "needle": {
        "name": "大海捞针（长上下文检索）",
        "module": needle,
        "requires_vl": False,
    },
    "math": {
        "name": "数学正确性",
        "module": math_correctness,
        "requires_vl": False,
    },
    "garble": {
        "name": "长上下文乱码检测",
        "module": garble,
        "requires_vl": False,
    },
    "tool_smoke": {
        "name": "工具调用冒烟快筛",
        "module": tool_smoke,
        "requires_vl": False,
    },
    "agent_replay": {
        "name": "Agent 多工具决定性回归",
        "module": agent_replay,
        "requires_vl": False,
    },
    "multimodal": {
        "name": "多模态图片输入测试",
        "module": multimodal,
        "requires_vl": True,
    },
}

__all__ = ["ITEMS"]
