"""
测试策略管理模块

从 benchmark_strategies.csv 读取矩阵化测试策略，支持按模型筛选。
策略采用矩阵法：输出长度 (short/long) x 不同并发梯度。
"""
import csv
import logging
from pathlib import Path
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class BenchmarkStrategy:
    """单条性能测试策略"""
    model_idx: str
    model_name: str
    model_slug: str
    size_category: str          # ultra_light / small_medium / medium_large / moe
    concurrency_list: list[int] # 并发梯度列表
    input_len: int              # 输入长度
    output_len: int             # 输出长度
    output_type: str            # short / long
    num_prompts: int            # 请求数
    strategy_id: str            # 策略唯一标识


def read_strategies(strategy_csv: Path) -> list[BenchmarkStrategy]:
    """读取策略 CSV 文件，返回策略列表"""
    strategies = []
    if not strategy_csv.exists():
        log.error(f"策略配置文件不存在: {strategy_csv}")
        return strategies

    with open(strategy_csv, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            concurrency_str = row["并发梯度"].strip()
            try:
                concurrency_list = [int(x.strip()) for x in concurrency_str.split(",") if x.strip()]
            except ValueError:
                log.warning(f"策略 {row.get('策略ID', '?')} 的并发梯度解析失败: {concurrency_str}")
                continue

            strategies.append(BenchmarkStrategy(
                model_idx=row["模型序号"].strip(),
                model_name=row["模型名称"].strip(),
                model_slug=row["模型slug"].strip(),
                size_category=row["参数量级"].strip(),
                concurrency_list=concurrency_list,
                input_len=int(row["输入长度"].strip()),
                output_len=int(row["输出长度"].strip()),
                output_type=row["输出类型"].strip(),
                num_prompts=int(row["请求数"].strip()),
                strategy_id=row["策略ID"].strip(),
            ))
    log.info(f"加载了 {len(strategies)} 条性能测试策略")
    return strategies


def filter_strategies_by_model(
    strategies: list[BenchmarkStrategy],
    model_slug: str | None = None,
) -> list[BenchmarkStrategy]:
    """按模型 slug 过滤策略"""
    if not model_slug:
        return strategies
    return [s for s in strategies if s.model_slug == model_slug]
