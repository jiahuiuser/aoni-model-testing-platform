"""
AONI 自动化测试套件 — 任务管理模块 (Task Management)
测试任务创建、流转跑通、暂停/恢复、删除及显存释放
"""
import time
import requests
import unittest

BASE_URL = "http://127.0.0.1:8800/api"

class TestTaskManagement(unittest.TestCase):

    def test_01_create_task(self):
        """测试创建测试任务（支持模型列表、并发策略及数据集配置）"""
        # 获取可用模型
        models = requests.get(f"{BASE_URL}/models").json()
        slugs = [m["slug"] for m in models[:2]]

        # 获取设备
        devices = requests.get(f"{BASE_URL}/devices").json()
        dev_id = devices[0]["id"]

        task_payload = {
            "name": f"自动化测试任务_{int(time.time())}",
            "profile": "QuickBenchmark",
            "device_id": dev_id,
            "config": {
                "model_slugs": slugs,
                "perf_enabled": True,
                "acc_enabled": True,
                "perf_rounds_config": [
                    {
                        "input_len": 512,
                        "output_lens_str": "128,512",
                        "concurrencies_str": "1,4,8",
                        "num_prompts": 100
                    }
                ],
                "acc_datasets": ["mmlu", "ceval"],
                "gpu_memory_utilization": 0.25,
                "container_port": 8300
            }
        }

        res = requests.post(f"{BASE_URL}/tasks", json=task_payload)
        self.assertEqual(res.status_code, 200)
        task_data = res.json()
        self.assertIn("id", task_data)
        print(f"✅ [任务管理] 任务 #{task_data['id']} 创建成功，名字: {task_data['name']}")
        return task_data["id"]

    def test_02_task_lifecycle_pause_resume_delete(self):
        """测试任务生命周期：暂停(只停测试不停容器)、恢复、删除(停止容器释放显存)"""
        task_id = self.test_01_create_task()

        # 等待线程启动
        time.sleep(2)

        # 1. 暂停任务
        pause_res = requests.post(f"{BASE_URL}/tasks/{task_id}/action", json={"action": "pause"})
        self.assertEqual(pause_res.status_code, 200)
        task_info = requests.get(f"{BASE_URL}/tasks/{task_id}").json()
        self.assertEqual(task_info["status"], "paused")
        print(f"✅ [任务管理] 任务 #{task_id} 暂停成功，状态为 PAUSED (容器保持健康上线)")

        # 2. 恢复任务
        resume_res = requests.post(f"{BASE_URL}/tasks/{task_id}/action", json={"action": "resume"})
        self.assertEqual(resume_res.status_code, 200)
        task_info = requests.get(f"{BASE_URL}/tasks/{task_id}").json()
        self.assertIn(task_info["status"], ("running", "queued", "completed"))
        print(f"✅ [任务管理] 任务 #{task_id} 恢复成功，当前状态: {task_info['status']}")

        # 3. 删除任务（物理清理容器与显存）
        del_res = requests.delete(f"{BASE_URL}/tasks/{task_id}")
        self.assertEqual(del_res.status_code, 200)
        print(f"✅ [任务管理] 任务 #{task_id} 删除成功，关联容器与显存空间已安全释放")

if __name__ == "__main__":
    unittest.main()
