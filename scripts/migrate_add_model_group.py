"""
数据库平滑迁移脚本：为 models 表添加 group_name 列，并将已有 43 款模型全量归至 NVIDIA_jetson_AGX_Thor
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "aoni_platform.db"

def migrate():
    print(f"开始迁移数据库: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 检查 models 表字段
    cursor.execute("PRAGMA table_info(models)")
    columns = [col[1] for col in cursor.fetchall()]

    if "group_name" not in columns:
        print("为 models 表增加 group_name 字段...")
        cursor.execute("ALTER TABLE models ADD COLUMN group_name VARCHAR(100) DEFAULT 'NVIDIA_jetson_AGX_Thor'")
    else:
        print("models 表已存在 group_name 字段")

    # 全量更新现存模型归属于 NVIDIA_jetson_AGX_Thor
    cursor.execute("UPDATE models SET group_name = 'NVIDIA_jetson_AGX_Thor' WHERE group_name IS NULL OR group_name = ''")
    updated_count = cursor.rowcount
    conn.commit()

    # 打印迁移结果
    cursor.execute("SELECT group_name, COUNT(*) FROM models GROUP BY group_name")
    summary = cursor.fetchall()
    print("数据库迁移完成！模型硬件组分布统计:")
    for group, count in summary:
        print(f"  - {group}: {count} 款模型")

    conn.close()

if __name__ == "__main__":
    migrate()
