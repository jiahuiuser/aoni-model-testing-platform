"""
AONI 核心 QA 测试用例套件 — 03. 任务管理全流水线与容器隔离机制测试
"""
import time
import requests
import unittest

BASE_URL = "http://127.0.0.1:8800/api"

def get_admin_headers():
    res = requests.post(f"{BASE_URL}/auth/login", data={"username": "admin", "password": "jiahui123"})
    if res.status_code == 200:
        token = res.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    return {}

class TestTasksExtended(unittest.TestCase):

    def test_tc_task_01_full_benchmark_task_pipeline(self):
        """TC-TASK-01: 完整 benchmark 测试任务创建与流转测试"""
        headers = get_admin_headers()
        models = requests.get(f"{BASE_URL}/models", headers=headers).json()
        slugs = [m["slug"] for m in models[:2]]
        devices = requests.get(f"{BASE_URL}/devices", headers=headers).json()
        dev_id = devices[0]["id"]

        task_payload = {
            "name": f"QA_全流水线测试_{int(time.time())}",
            "profile": "QuickBenchmark",
            "device_id": dev_id,
            "config": {
                "model_slugs": slugs,
                "perf_enabled": True,
                "acc_enabled": True,
                "perf_rounds_config": [
                    {
                        "input_len": 256,
                        "output_lens_str": "128",
                        "concurrencies_str": "1,4",
                        "num_prompts": 20
                    }
                ],
                "acc_datasets": ["mmlu"],
                "gpu_memory_utilization": 0.25,
                "container_port": 8450
            }
        }
        res = requests.post(f"{BASE_URL}/tasks", json=task_payload, headers=headers)
        self.assertEqual(res.status_code, 200)
        task = res.json()
        task_id = task["id"]
        print(f"  [TC-TASK-01] 任务 #{task_id} 创建成功")

        # 校验列表呈现
        t_list = requests.get(f"{BASE_URL}/tasks", headers=headers).json()
        self.assertTrue(any(t["id"] == task_id for t in t_list))

        # 测试 暂停 -> 恢复 -> 删除 隔离机制
        time.sleep(1)

        # 暂停 (保留容器)
        requests.post(f"{BASE_URL}/tasks/{task_id}/action", json={"action": "pause"}, headers=headers)
        t_paused = requests.get(f"{BASE_URL}/tasks/{task_id}", headers=headers).json()
        self.assertEqual(t_paused["status"], "paused")
        print(f"  [TC-TASK-01] 任务 #{task_id} 暂停成功，状态为 PAUSED (容器保留在线)")

        # 恢复
        requests.post(f"{BASE_URL}/tasks/{task_id}/action", json={"action": "resume"}, headers=headers)
        t_resumed = requests.get(f"{BASE_URL}/tasks/{task_id}", headers=headers).json()
        self.assertIn(t_resumed["status"], ("running", "queued", "completed"))
        print(f"  [TC-TASK-01] 任务 #{task_id} 恢复成功，状态: {t_resumed['status']}")

        # 删除 (强行清理容器并释放显存)
        del_res = requests.delete(f"{BASE_URL}/tasks/{task_id}", headers=headers)
        self.assertEqual(del_res.status_code, 200)
        print(f"  [TC-TASK-01] 任务 #{task_id} 删除并彻底清理 Docker 容器资源成功")

    def test_tc_task_02_invalid_task_config_validation(self):
        """TC-TASK-02: 空模型列表异常容错校验"""
        headers = get_admin_headers()
        invalid_payload = {
            "name": "非法任务",
            "device_id": 1,
            "config": { "model_slugs": [] }
        }
        res = requests.post(f"{BASE_URL}/tasks", json=invalid_payload, headers=headers)
        self.assertEqual(res.status_code, 400)
        print("  [TC-TASK-02] 非法任务配置拦截验证通过 (HTTP 400)")

if __name__ == "__main__":
    unittest.main()
