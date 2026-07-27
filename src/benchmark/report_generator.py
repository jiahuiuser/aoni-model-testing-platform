"""
报告生成模块

读取性能和准确率的 JSON 汇总结果，为每个模型生成 Markdown 格式的综合测试报告。
包含性能矩阵表、准确率对比表和评级结论。
"""
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)

# ---------- 性能评级标准 (来自测试方案第7节) ----------

PERF_GRADE_TABLE = {
    # (参数量级, min_tps, max_tps) -> 等级
    "ultra_light": [(120, "A"), (60, "B"), (0, "C")],
    "small_medium": [(80, "A"), (40, "B"), (0, "C")],
    "medium_large": [(25, "A"), (12, "B"), (0, "C")],
    "moe": [(100, "A"), (60, "B"), (0, "C")],
}

ACC_GRADE_TABLE = {
    "mmlu": [(0.65, "A"), (0.45, "B"), (0, "C")],
    "ceval": [(0.70, "A"), (0.50, "B"), (0, "C")],
    "gsm8k": [(0.55, "A"), (0.35, "B"), (0, "C")],
    "humaneval": [(0.30, "A"), (0.15, "B"), (0, "C")],
    "arc": [(0.65, "A"), (0.45, "B"), (0, "C")],
}


def _grade(value: float, thresholds: list[tuple[float, str]]) -> str:
    """根据阈值评等级"""
    for threshold, grade in thresholds:
        if value >= threshold:
            return grade
    return "C"


def _load_json(path: Path) -> dict | None:
    """安全加载 JSON 文件"""
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"加载 JSON 失败: {path} -> {e}")
        return None


def generate_model_report(
    model_name: str,
    model_slug: str,
    model_idx: str,
    perf_summary: dict | None,
    acc_summary: dict | None,
    size_category: str,
    output_dir: Path,
) -> Path:
    """为单个模型生成 Markdown 测试报告"""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{model_slug}_report.md"

    lines = []
    lines.append(f"# {model_name} 模型测试报告")
    lines.append("")
    lines.append(f"- **模型索引**: #{model_idx}")
    lines.append(f"- **模型 slug**: `{model_slug}`")
    lines.append(f"- **参数量级**: `{size_category}`")
    lines.append(f"- **报告生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # ---- 性能测试部分 ----
    lines.append("## 1. 性能测试结果")
    lines.append("")

    if perf_summary and perf_summary.get("results"):
        results = perf_summary["results"]
        lines.append(f"**测试时间**: {perf_summary.get('test_time', 'N/A')}")
        lines.append(f"**测试用例数**: {len(results)}")
        lines.append("")

        # 按 output_type 和 concurrency 组织
        lines.append("### 1.1 性能矩阵 (输出吞吐量 tokens/s)")
        lines.append("")

        # 收集所有数据
        short_results = {}
        long_results = {}
        for r in results:
            output_type = r.get("output_type", "short")
            concurrency = r.get("concurrency", 0)
            throughput = r.get("output_throughput", r.get("total_input_throughput", "N/A"))
            target = short_results if output_type == "short" else long_results
            target[concurrency] = throughput

        lines.append("| 输出类型 | " + " | ".join(f"并发={c}" for c in sorted(set(
            list(short_results.keys()) + list(long_results.keys())
        ))) + " |")
        lines.append("|" + "---|" * (len(set(list(short_results.keys()) + list(long_results.keys()))) + 1))

        all_concurrencies = sorted(set(list(short_results.keys()) + list(long_results.keys())))

        for label, data in [("short (128 tokens)", short_results), ("long (512 tokens)", long_results)]:
            row = f"| {label} "
            for c in all_concurrencies:
                val = data.get(c, "-")
                if isinstance(val, float):
                    row += f"| {val:.1f} "
                else:
                    row += f"| {val} "
            row += "|"
            lines.append(row)

        lines.append("")

        # 详细指标表
        lines.append("### 1.2 详细性能指标")
        lines.append("")
        lines.append("| 策略 | 并发 | TTFT均值(ms) | TPOT均值(ms) | P99 TTFT(ms) | P99 TPOT(ms) | 吞吐(tok/s) |")
        lines.append("|---|---|---|---|---|---|---|")

        for r in results:
            sid = r.get("strategy_id", "?")
            con = r.get("concurrency", "?")
            ttft = r.get("mean_ttft_ms", "-")
            tpot = r.get("mean_tpot_ms", "-")
            p99_ttft = r.get("p99_ttft_ms", "-")
            p99_tpot = r.get("p99_tpot_ms", "-")
            tput = r.get("output_throughput", "-")

            def _fmt(v):
                return f"{v:.1f}" if isinstance(v, float) else str(v)

            lines.append(f"| {sid} | {con} | {_fmt(ttft)} | {_fmt(tpot)} | {_fmt(p99_ttft)} | {_fmt(p99_tpot)} | {_fmt(tput)} |")

        lines.append("")

        # 性能等级评定 (优先取并发=8 的 short 指标，其次并发=4)
        c8_short = [r for r in results if r.get("concurrency") == 8 and r.get("output_type") == "short"]
        if not c8_short:
            c8_short = [r for r in results if r.get("concurrency") == 4 and r.get("output_type") == "short"]
        if not c8_short:
            c8_short = [r for r in results if r.get("output_type") == "short"]
        if c8_short:
            best_tps = c8_short[0].get("output_throughput", 0)
            if isinstance(best_tps, (int, float)):
                grade = _grade(best_tps, PERF_GRADE_TABLE.get(size_category, [(0, "C")]))
                lines.append(f"**性能等级 (并发=8, 短输出)**: **{grade} 级** (吞吐量 {best_tps:.1f} tok/s)")
                lines.append("")
    else:
        lines.append("*无性能测试数据*")
        lines.append("")

    # ---- 准确率测试部分 ----
    lines.append("## 2. 准确率测试结果")
    lines.append("")

    if acc_summary and acc_summary.get("metrics"):
        metrics = acc_summary["metrics"]
        lines.append(f"**测试时间**: {acc_summary.get('test_time', 'N/A')}")
        lines.append("")

        lines.append("| 评测数据集 | 准确率 | 等级 |")
        lines.append("|---|---|---|")

        dataset_labels = {
            "mmlu_accuracy": "MMLU",
            "ceval_accuracy": "C-Eval",
            "gsm8k_accuracy": "GSM8K",
            "arc_accuracy": "ARC-Challenge",
            "humaneval_accuracy": "HumanEval (Pass@1)",
            "weighted_avg": "加权平均",
        }

        acc_values = {}
        for key, label in dataset_labels.items():
            val = metrics.get(key)
            if val is not None and isinstance(val, (int, float)):
                acc_values[key] = val
                lookup = key.replace("_accuracy", "")
                thresholds = ACC_GRADE_TABLE.get(lookup, [(0, "C")])
                grade = _grade(val, thresholds)
                lines.append(f"| {label} | {val:.2%} | {grade} |")

        lines.append("")

        # 总体准确率评估
        all_accs = [v for k, v in acc_values.items() if k != "weighted_avg"]
        if all_accs:
            avg_acc = sum(all_accs) / len(all_accs)
            lines.append(f"**平均准确率**: {avg_acc:.2%}")
            lines.append("")
    else:
        lines.append("*无准确率测试数据*")
        lines.append("")

    # ---- 综合评估 ----
    lines.append("## 3. 综合评估")
    lines.append("")

    perf_grade = "N/A"
    acc_grade_str = "N/A"

    if perf_summary and perf_summary.get("results"):
        results = perf_summary["results"]
        c8 = [r for r in results if r.get("concurrency") == 8 and r.get("output_type") == "short"]
        if not c8:
            c8 = [r for r in results if r.get("concurrency") == 4 and r.get("output_type") == "short"]
        if c8:
            tps = c8[0].get("output_throughput", 0)
            if isinstance(tps, (int, float)):
                perf_grade = _grade(tps, PERF_GRADE_TABLE.get(size_category, [(0, "C")]))

    if acc_summary and acc_summary.get("metrics"):
        metrics = acc_summary["metrics"]
        accs = [v for k, v in metrics.items() if k.endswith("_accuracy") and isinstance(v, (int, float))]
        if accs:
            avg_acc = sum(accs) / len(accs)
            if avg_acc >= 0.70:
                acc_grade_str = "A"
            elif avg_acc >= 0.50:
                acc_grade_str = "B"
            else:
                acc_grade_str = "C"

    lines.append(f"| 维度 | 等级 | 说明 |")
    lines.append(f"|---|---|---|")
    lines.append(f"| 推理性能 | {perf_grade} | 基于并发短输出吞吐量评定 |")
    lines.append(f"| 准确率 | {acc_grade_str} | 基于多数据集平均准确率评定 |")
    lines.append("")

    # 部署建议
    if perf_grade == "A" and acc_grade_str == "A":
        recommendation = "强烈推荐 - 性能和准确率均优秀，适合生产环境部署"
    elif perf_grade in ("A", "B") and acc_grade_str in ("A", "B"):
        recommendation = "推荐 - 性能和准确率良好，多数场景适用"
    elif "C" not in (perf_grade, acc_grade_str):
        recommendation = "可用 - 基本满足需求，有特定局限"
    else:
        recommendation = "谨慎使用 - 性能或准确率不达标，仅建议验证用途"

    lines.append(f"**部署建议**: {recommendation}")
    lines.append("")

    # 写入文件
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    log.info(f"报告已生成: {report_path}")
    return report_path


def generate_summary_report(
    all_perf_summaries: dict[str, dict | None],
    all_acc_summaries: dict[str, dict | None],
    model_info: dict[str, dict],  # slug -> {idx, name, size_category}
    output_dir: Path,
) -> Path:
    """生成所有模型的汇总对比报告"""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "benchmark_summary.md"

    lines = []
    lines.append("# 43模型汇总测试报告")
    lines.append("")
    lines.append(f"**报告生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## 模型性能与准确率汇总")
    lines.append("")
    lines.append("| # | 模型 | 参数量级 | 吞吐(tok/s, c=8) | 性能等级 | MMLU | C-Eval | GSM8K | ARC | 准确率等级 | 部署建议 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")

    for slug, info in sorted(model_info.items(), key=lambda x: x[1].get("idx", "99")):
        name = info.get("name", slug)
        idx = info.get("idx", "?")
        size_cat = info.get("size_category", "unknown")

        perf = all_perf_summaries.get(slug)
        acc = all_acc_summaries.get(slug)

        # 提取性能指标
        tps_str = "-"
        perf_grade = "-"
        if perf and perf.get("results"):
            c8 = [r for r in perf["results"] if r.get("concurrency") == 8 and r.get("output_type") == "short"]
            if not c8:
                c8 = [r for r in perf["results"] if r.get("concurrency") == 4 and r.get("output_type") == "short"]
            if c8:
                tps = c8[0].get("output_throughput", 0)
                if isinstance(tps, (int, float)):
                    tps_str = f"{tps:.1f}"
                    perf_grade = _grade(tps, PERF_GRADE_TABLE.get(size_cat, [(0, "C")]))

        # 提取准确率指标
        mmlu = "-"; ceval = "-"; gsm8k = "-"; arc = "-"; acc_grade = "-"
        if acc and acc.get("metrics"):
            m = acc["metrics"]
            if m.get("mmlu_accuracy"):
                mmlu = f"{m['mmlu_accuracy']:.1%}"
            if m.get("ceval_accuracy"):
                ceval = f"{m['ceval_accuracy']:.1%}"
            if m.get("gsm8k_accuracy"):
                gsm8k = f"{m['gsm8k_accuracy']:.1%}"
            if m.get("arc_accuracy"):
                arc = f"{m['arc_accuracy']:.1%}"

            accs = [v for k, v in m.items() if k.endswith("_accuracy") and isinstance(v, (int, float))]
            if accs:
                avg = sum(accs) / len(accs)
                if avg >= 0.70:
                    acc_grade = "A"
                elif avg >= 0.50:
                    acc_grade = "B"
                else:
                    acc_grade = "C"

        # 部署建议
        if perf_grade == "A" and acc_grade == "A":
            rec = "强烈推荐"
        elif perf_grade in ("A", "B") and acc_grade in ("A", "B"):
            rec = "推荐"
        elif "C" not in (perf_grade, acc_grade):
            rec = "可用"
        else:
            rec = "谨慎"

        lines.append(f"| {idx} | {name} | {size_cat} | {tps_str} | {perf_grade} | {mmlu} | {ceval} | {gsm8k} | {arc} | {acc_grade} | {rec} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*注: 性能等级以并发=8 (或4) 短输出场景为基准评定*")
    lines.append("")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    log.info(f"汇总报告已生成: {report_path}")
    return report_path


def batch_generate_reports(
    perf_report_dir: Path,
    acc_report_dir: Path,
    output_dir: Path,
    strategy_csv: Path,
):
    """批量生成所有模型的单模型报告和汇总报告"""
    import csv

    output_dir.mkdir(parents=True, exist_ok=True)

    # 读取策略，获取参数量级映射
    model_size_map = {}
    if strategy_csv.exists():
        with open(strategy_csv, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                slug = row["模型slug"].strip()
                size_cat = row["参数量级"].strip()
                model_size_map[slug] = size_cat

    # 收集所有结果
    all_perf = {}
    all_acc = {}
    model_info = {}

    for perf_file in sorted(perf_report_dir.glob("*/perf_summary.json")):
        slug = perf_file.parent.name
        all_perf[slug] = _load_json(perf_file)
        if slug not in model_info:
            model_info[slug] = {"name": slug, "idx": "?", "size_category": model_size_map.get(slug, "unknown")}

    for acc_file in sorted(acc_report_dir.glob("*/accuracy_summary.json")):
        slug = acc_file.parent.name
        all_acc[slug] = _load_json(acc_file)
        if slug not in model_info:
            model_info[slug] = {"name": slug, "idx": "?", "size_category": model_size_map.get(slug, "unknown")}

    # 补充模型名称信息
    for slug in list(model_info.keys()):
        if model_info[slug]["name"] == slug:
            perf = all_perf.get(slug)
            if perf and perf.get("model_name"):
                model_info[slug]["name"] = perf["model_name"]
                model_info[slug]["idx"] = perf.get("model_idx", "?")

    # 生成单模型报告
    generated = []
    for slug, info in model_info.items():
        perf = all_perf.get(slug)
        acc = all_acc.get(slug)
        size_cat = info.get("size_category", "unknown")

        report_path = generate_model_report(
            model_name=info["name"],
            model_slug=slug,
            model_idx=info["idx"],
            perf_summary=perf,
            acc_summary=acc,
            size_category=size_cat,
            output_dir=output_dir / "models",
        )
        generated.append(report_path)

    # 生成汇总报告
    summary_path = generate_summary_report(
        all_perf_summaries=all_perf,
        all_acc_summaries=all_acc,
        model_info=model_info,
        output_dir=output_dir,
    )

    log.info(f"共生成 {len(generated)} 份单模型报告 + 1 份汇总报告")
    return generated, summary_path
