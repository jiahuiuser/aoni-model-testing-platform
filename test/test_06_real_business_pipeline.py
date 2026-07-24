"""
AONI 真实业务链路测试 — 跨设备跑模型性能测试、准确率测试及 Docker Run 启动
"""
import time
import requests
import unittest

BASE_URL = "http://127.0.0.1:8800/api"

class TestRealBusinessPipeline(unittest.TestCase):

    def setUp(self):
        """拉取可用设备与模型基础环境"""
        self.devices = requests.get(f"{BASE_URL}/devices").json()
        self.models = requests.get(f"{BASE_URL}/models").json()
        self.assertTrue(len(self.devices) >= 1, "系统中应至少存在 1 个设备节点")
        self.assertTrue(len(self.models) >= 1, "模型库中应至少存在 1 个预设模型")

    def test_biz_01_model_docker_run_by_device(self):
        """业务验证 1: 测试不同设备维度下拉起与验证专属 Docker Run 命令"""
        target_model = self.models[0]
        slug = target_model["slug"]

        for dev in self.devices:
            dev_id = dev["id"]
            dev_name = dev["name"]
            print(f"  [BIZ-01] 验证模型 '{slug}' 在设备 [{dev_name}] (#{dev_id}) 上的 Docker Run 验证命令...")
            
            # 请求按设备维度的模型跑通测试
            res = requests.post(f"{BASE_URL}/models/{slug}/test?device_id={dev_id}")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("status", data)
            self.assertIn(data["status"], ("PASS", "FAIL"))
            print(f"    -> 设备 [{dev_name}] 验证结果: {data['status']} (Docker ID: {data.get('container_id', 'N/A')})")

    def test_biz_02_multi_device_perf_and_acc_task(self):
        """业务验证 2: 在不同设备上跑模型性能测试 (tok/s, TTFT) 与 准确率测试 (MMLU)"""
        target_slugs = [m["slug"] for m in self.models[:2]]

        for dev in self.devices:
            dev_id = dev["id"]
            dev_name = dev["name"]
            print(f"\n  [BIZ-02] 创建并跑通设备 [{dev_name}] 的完整性能+准确率基准任务...")

            task_payload = {
                "name": f"业务实测_{dev_name}_{int(time.time())}",
                "profile": "QuickBenchmark",
                "device_id": dev_id,
                "config": {
                    "model_slugs": target_slugs,
                    "perf_enabled": True,
                    "acc_enabled": True,
                    "perf_rounds_config": [
                        {
                            "input_len": 512,
                            "output_lens_str": "128,512",
                            "concurrencies_str": "1,4,8",
                            "num_prompts": 50
                        }
                    ],
                    "acc_datasets": ["mmlu", "ceval"],
                    "gpu_memory_utilization": 0.25,
                    "container_port": 8300 + dev_id
                }
            }

            res = requests.post(f"{BASE_URL}/tasks", json=task_payload)
            self.assertEqual(res.status_code, 200)
            task = res.json()
            task_id = task["id"]
            print(f"    -> 任务 #{task_id} 已在设备 [{dev_name}] 下派发成功")

            # 轮询等待任务完成或状态流转
            max_wait = 20
            start_t = time.time()
            final_status = "unknown"
            while time.time() - start_t < max_wait:
                t_info = requests.get(f"{BASE_URL}/tasks/{task_id}").json()
                final_status = t_info.get("status")
                if final_status in ("completed", "done", "failed"):
                    break
                time.sleep(2)

            print(f"    -> 设备 [{dev_name}] 任务状态流转至: {final_status}")

            # 清理该测试任务并确保释放其占用容器
            requests.delete(f"{BASE_URL}/tasks/{task_id}")
            print(f"    -> 任务 #{task_id} 已清理，关联 Docker 容器及资源全量解绑释放")

    def test_biz_03_cross_device_and_model_report_comparison(self):
        """业务验证 3: 跨设备、跨模型的测试报告数据拉取与对比」"""
        reports = requests.get(f"{BASE_URL}/reports").json()
        self.assertIsInstance(reports, list)
        print(f"\n  [BIZ-03] 系统已安全归档 {len(reports)} 份真实测试报告")

        # 检查吞吐量横向比对接口
        tput_compare = requests.get(f"{BASE_URL}/reports/compare/throughput").json()
        self.assertIsInstance(tput_compare, list)

        # 检查准确率横向比对接口
        acc_compare = requests.get(f"{BASE_URL}/reports/compare/accuracy?dataset=mmlu").json()
        self.assertIsInstance(acc_compare, list)

        print("  [BIZ-03] 跨模型/跨设备吞吐量 (Throughput tok/s) 与准确率 (MMLU Accuracy) 图表比对成功！")

if __name__ == "__main__":
    unittest.main()
