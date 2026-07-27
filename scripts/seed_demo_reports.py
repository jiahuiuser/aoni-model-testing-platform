"""
AONI 模型测试平台 — 演示评测数据生成脚本
向数据库生成涵盖多模型、跨设备、多并发阶梯与多数据集准确率的高质量评测报告。
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

# 加入工程根路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import session_factory, init_db
from backend.models import Task, ModelRun, PerfResult, AccResult, TaskStatus, ModelStage, Device, ModelInfo

def seed_demo_data():
    init_db()
    db = session_factory()
    try:
        print("🌱 正在为您注入多模型跨设备高清对比数据套件...")

        # 1. 确保核心设备节点存在
        devices = db.query(Device).all()
        dev_local = next((d for d in devices if d.host in ("127.0.0.1", "localhost")), None)
        if not dev_local:
            dev_local = Device(name="Jetson Thor (本机)", host="127.0.0.1", port=8800, status="online")
            db.add(dev_local)

        dev_edge = next((d for d in devices if d.host == "192.168.1.50"), None)
        if not dev_edge:
            dev_edge = Device(name="边缘节点 01", host="192.168.1.50", port=8800, status="online")
            db.add(dev_edge)

        dev_cluster = next((d for d in devices if d.host == "192.168.1.60"), None)
        if not dev_cluster:
            dev_cluster = Device(name="算力集群节点 02", host="192.168.1.60", port=8800, status="online")
            db.add(dev_cluster)

        db.commit()

        # 2. 创建一个完整的组合对比测试任务
        demo_task = Task(
            name="多模型全场景吞吐与准确率综合评测任务",
            profile="FullBenchmarkSuite",
            status=TaskStatus.COMPLETED,
            device_id=dev_local.id,
            config={
                "model_slugs": ["deepseek-r1-7b", "qwen2.5-7b-instruct", "cosmos-reason-2b", "llama-3-8b-instruct", "qwen2-vl-7b"],
                "perf_enabled": True, "acc_enabled": True
            },
            started_at=datetime.utcnow() - timedelta(hours=2),
            completed_at=datetime.utcnow() - timedelta(minutes=5)
        )
        db.add(demo_task)
        db.commit()
        db.refresh(demo_task)

        # 3. 5 大模型测试用例数据定义
        benchmark_scenarios = [
            {
                "idx": 1, "name": "DeepSeek-R1-Distill-7B", "slug": "deepseek-r1-7b",
                "device": dev_local, "tput_base": 168.5, "ttft_mean": 42.3, "ttft_p99": 68.1, "tpot": 5.9,
                "acc": {"mmlu": 0.8350, "ceval": 0.8620, "gsm8k": 0.8840, "arc": 0.8510}
            },
            {
                "idx": 2, "name": "Qwen2.5-7B-Instruct", "slug": "qwen2.5-7b-instruct",
                "device": dev_local, "tput_base": 192.4, "ttft_mean": 35.8, "ttft_p99": 52.4, "tpot": 5.2,
                "acc": {"mmlu": 0.7980, "ceval": 0.8260, "gsm8k": 0.8410, "arc": 0.8150}
            },
            {
                "idx": 3, "name": "Cosmos Reason 2B", "slug": "cosmos-reason-2b",
                "device": dev_edge, "tput_base": 245.8, "ttft_mean": 22.1, "ttft_p99": 38.6, "tpot": 4.1,
                "acc": {"mmlu": 0.7120, "ceval": 0.7450, "gsm8k": 0.7630, "arc": 0.7300}
            },
            {
                "idx": 4, "name": "Llama-3-8B-Instruct", "slug": "llama-3-8b-instruct",
                "device": dev_cluster, "tput_base": 135.2, "ttft_mean": 58.4, "ttft_p99": 92.0, "tpot": 7.4,
                "acc": {"mmlu": 0.7860, "ceval": 0.7210, "gsm8k": 0.7950, "arc": 0.7720}
            },
            {
                "idx": 5, "name": "Qwen2-VL-7B (视觉多模态)", "slug": "qwen2-vl-7b",
                "device": dev_local, "tput_base": 112.6, "ttft_mean": 84.2, "ttft_p99": 125.6, "tpot": 8.8,
                "acc": {"mmlu": 0.7640, "ceval": 0.7890, "gsm8k": 0.7320, "arc": 0.7480}
            }
        ]

        now = datetime.utcnow()

        for s in benchmark_scenarios:
            # 创建 ModelRun
            mr = ModelRun(
                task_id=demo_task.id,
                model_idx=s["idx"],
                model_name=s["name"],
                model_slug=s["slug"],
                device_id=s["device"].id,
                device_name=s["device"].name,
                status=ModelStage.DONE,
                progress=100,
                docker_command=f"sudo docker run -d --gpus all -p 8300:8000 -e MODEL_NAME={s['slug']} vllm/vllm-openai:latest",
                started_at=now - timedelta(minutes=30 - s["idx"] * 5),
                completed_at=now - timedelta(minutes=5 - s["idx"])
            )
            db.add(mr)
            db.commit()
            db.refresh(mr)

            # 插入不同并发 (1, 4, 8, 16) 与长短输出下的 PerfResult 阶梯数据
            conconcurrencies = [1, 4, 8, 16]
            output_specs = [("short", 128), ("long", 512)]

            for out_type, out_len in output_specs:
                for c in conconcurrencies:
                    # 并发越高，吞吐略升后趋稳，延迟略增
                    mult = (1 + 0.15 * (c ** 0.5)) if c <= 8 else 1.35
                    tput = round(s["tput_base"] * mult, 2)
                    mean_ttft = round(s["ttft_mean"] * (1 + 0.1 * c), 2)
                    p99_ttft = round(s["ttft_p99"] * (1 + 0.12 * c), 2)
                    tpot = round(s["tpot"] * (1 + 0.05 * c), 2)
                    itl = round(1000.0 / tput, 2) if tput > 0 else 0.0

                    pr = PerfResult(
                        model_run_id=mr.id,
                        round_num=1,
                        strategy_id=f"{s['slug']}_rd1_{out_type}",
                        output_type=out_type,
                        concurrency=c,
                        input_len=512,
                        output_len=out_len,
                        throughput_tok_s=tput,
                        request_throughput=round(tput / (out_len or 1), 2),
                        mean_ttft_ms=mean_ttft,
                        p99_ttft_ms=p99_ttft,
                        mean_tpot_ms=tpot,
                        p99_tpot_ms=round(tpot * 1.5, 2),
                        mean_itl_ms=itl,
                        p99_itl_ms=round(itl * 1.6, 2),
                        raw_report={"completed": c * 50, "failed": 0, "duration": 15.5}
                    )
                    db.add(pr)

            # 插入 AccResult 准确率测试结果
            for dataset_name, acc_val in s["acc"].items():
                ar = AccResult(
                    model_run_id=mr.id,
                    dataset=dataset_name,
                    accuracy=acc_val
                )
                db.add(ar)

        db.commit()
        print("✅ 多模型跨设备演示测试数据已成功注入完成！")

    finally:
        db.close()

if __name__ == "__main__":
    seed_demo_data()
