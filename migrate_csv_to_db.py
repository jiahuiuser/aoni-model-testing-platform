"""一次性迁移：将 CSV 数据导入 SQLite 数据库 + 注册本机设备"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.csv_handler import read_model_csv
from backend.database import engine, session_factory, init_db
from backend.models import ModelInfo, Device
from backend.services.pipeline import get_size_category_map

init_db()
db = session_factory()

# 1. 注册本机为默认设备
existing_device = db.query(Device).filter(Device.host == "127.0.0.1").first()
if not existing_device:
    d = Device(
        name="Jetson Thor (本机)", host="127.0.0.1", device_type="jetson",
        port=8800, cpu_cores=8, memory_gb=128.0,
        gpu_info="NVIDIA Thor 128GB UMA",
        status="online", description="本机默认设备",
    )
    db.add(d)
    db.commit()
    device_id = d.id
else:
    device_id = existing_device.id

# 2. 迁移 CSV 模型数据
csv_path = Path("data/aoni_models_thor128g.csv")
rows, _ = read_model_csv(csv_path)
size_map = get_size_category_map()

count = 0
for r in rows:
    if not r["idx"].isdigit():
        continue
    existing = db.query(ModelInfo).filter(ModelInfo.slug == r["slug"]).first()
    if existing:
        continue
    m = ModelInfo(
        idx=int(r["idx"]), name=r["name"], slug=r["slug"],
        docker_command=r["cmd"],
        tos_path=r.get("tos_path", ""),
        size_category=size_map.get(r["slug"], "unknown"),
        status="PASS" if r["result"].startswith("PASS") else ("FAIL" if r["result"].startswith("FAIL") else "NEW"),
        result_detail=r.get("result", ""),
    )
    db.add(m)
    count += 1

db.commit()
db.close()
print(f"迁移完成: {count} 模型 + 1 设备 (id={device_id})")
