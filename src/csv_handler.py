import csv
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# CSV 列索引定义
COL_IDX = 0
COL_NAME = 1
COL_SLUG = 2
COL_CMD = 3
COL_RESULT = 4
COL_TOS_PATH = 5

def read_model_csv(csv_path: Path) -> tuple[list[dict], list[str]]:
    """读取指定路径下的 CSV，并返回数据行字典列表与原始表头"""
    rows = []
    if not csv_path.exists():
        log.error(f"CSV 数据文件不存在: {csv_path}")
        return [], []

    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        headers = next(reader)
        for row in reader:
            if not row:
                continue
            # 兼容短行补齐
            while len(row) < 6:
                row.append("")
            rows.append({
                "idx": row[COL_IDX].strip(),
                "name": row[COL_NAME].strip(),
                "slug": row[COL_SLUG].strip(),
                "cmd": row[COL_CMD],
                "result": row[COL_RESULT].strip(),
                "tos_path": row[COL_TOS_PATH].strip(),
            })
    return rows, headers

def update_csv_result(csv_path: Path, row_idx: str, result: str):
    """更新 CSV 文件中指定编号模型测试结果 (同时同步 Desktop 与 data/ 目录下的 CSV)"""
    target_paths = [Path(csv_path), Path("/home/sd1/Desktop/aoni_models_thor128g.csv")]
    
    for p in target_paths:
        if not p.exists():
            log.warning(f"CSV 数据文件不存在，跳过: {p}")
            continue

        with open(p, encoding="utf-8-sig", newline="") as f:
            all_rows = list(csv.reader(f))

        updated = False
        for i, row in enumerate(all_rows):
            if i > 0 and row[0].strip() == str(row_idx):
                while len(row) < 6:
                    row.append("")
                row[COL_RESULT] = result
                all_rows[i] = row
                updated = True
                break

        if updated:
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                csv.writer(f).writerows(all_rows)
            log.info(f"  ✓ 结果写入 CSV 成功: #{row_idx} -> {result!r} ({p.name})")
        else:
            log.warning(f"  ✗ 未在 CSV 中找到序号为 #{row_idx} 的模型行 ({p.name})")
