"""
AONI 核心 QA 测试用例套件 — 02. 模型管理与 Docker Run 秒级响应测试
"""
import requests
import unittest

BASE_URL = "http://127.0.0.1:8800/api"

class TestModelsExtended(unittest.TestCase):

    def test_tc_mod_01_model_crud(self):
        """TC-MOD-01: 模型元数据创建、拉取与删除生命周期测试"""
        slug = "qa-temp-test-model"
        payload = {
            "name": "QA 临时测试模型",
            "slug": slug,
            "docker_command": "sudo docker run -d --gpus all -p 8000:8000 vllm/vllm-openai:latest --model Qwen/Qwen2.5-7B-Instruct",
            "tos_path": "tos://aoni-models/qa-temp/"
        }
        # 清理旧数据
        requests.delete(f"{BASE_URL}/models/{slug}")

        # 创建
        c_res = requests.post(f"{BASE_URL}/models", json=payload)
        self.assertEqual(c_res.status_code, 200)

        # 查
        g_res = requests.get(f"{BASE_URL}/models/{slug}")
        self.assertEqual(g_res.status_code, 200)
        self.assertEqual(g_res.json()["name"], "QA 临时测试模型")

        # 删除
        d_res = requests.delete(f"{BASE_URL}/models/{slug}")
        self.assertEqual(d_res.status_code, 200)
        print("  [TC-MOD-01] 模型元数据 CRUD 生命周期测试成功")

    def test_tc_mod_02_model_test_endpoint_non_hanging(self):
        """TC-MOD-02: 模型 docker run 跑通验证接口防卡死与快速响应测试"""
        models = requests.get(f"{BASE_URL}/models").json()
        self.assertGreater(len(models), 0)
        target = models[0]
        slug = target["slug"]

        print(f"  [TC-MOD-02] 正在请求 /{slug}/test 跑通验证...")
        res = requests.post(f"{BASE_URL}/models/{slug}/test", timeout=30)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIn("status", body)
        self.assertIn(body["status"], ("PASS", "FAIL"))
        print(f"  [TC-MOD-02] 跑通验证快速响应通过，状态: {body['status']}")

    def test_tc_mod_03_device_specific_config_binding(self):
        """TC-MOD-03: 专属设备维度 Docker 命令覆盖机制校验"""
        models = requests.get(f"{BASE_URL}/models").json()
        target = models[0]
        slug = target["slug"]

        devices = requests.get(f"{BASE_URL}/devices").json()
        dev_id = devices[0]["id"]

        config_payload = {
            "device_id": dev_id,
            "docker_command": f"sudo docker run -d --name test_{slug} -p 8400:8000 vllm:latest"
        }
        res = requests.post(f"{BASE_URL}/models/{slug}/device-configs", json=config_payload)
        self.assertEqual(res.status_code, 200)
        print("  [TC-MOD-03] 设备专属 Docker 命令覆盖绑定测试成功")

if __name__ == "__main__":
    unittest.main()
