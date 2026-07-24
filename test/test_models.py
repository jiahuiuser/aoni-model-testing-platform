"""
AONI 自动化测试套件 — 模型管理模块 (Model Management)
包含 docker run 命令跑通验证及设备专属配置测试
"""
import requests
import unittest

BASE_URL = "http://127.0.0.1:8800/api"

class TestModelManagement(unittest.TestCase):

    def test_01_list_models(self):
        """测试获取模型库列表"""
        res = requests.get(f"{BASE_URL}/models")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)
        self.assertTrue(len(data) >= 1)
        print(f"✅ [模型管理] 获取模型列表成功，模型总数: {len(data)}")

    def test_02_model_docker_run_verification(self):
        """测试跑通模型 docker run 命令验证（验证不卡死与响应情况）"""
        res = requests.get(f"{BASE_URL}/models")
        models = res.json()
        target_model = models[0]
        slug = target_model["slug"]

        print(f"🧪 [模型管理] 正在对模型 '{target_model['name']}' ({slug}) 执行一键跑通验证...")
        test_res = requests.post(f"{BASE_URL}/models/{slug}/test")
        self.assertEqual(test_res.status_code, 200)
        result_data = test_res.json()
        self.assertIn("status", result_data)
        self.assertIn(result_data["status"], ("PASS", "FAIL"))
        print(f"✅ [模型管理] 模型验证完成，状态: {result_data['status']}, 详细: {result_data.get('detail', '')[:100]}")

    def test_03_device_specific_config(self):
        """测试设备专属 Docker 指令配置更新"""
        res = requests.get(f"{BASE_URL}/models")
        models = res.json()
        target_model = models[0]
        slug = target_model["slug"]

        # 获取设备
        dev_res = requests.get(f"{BASE_URL}/devices")
        dev_id = dev_res.json()[0]["id"]

        # 更新或添加设备专属配置
        config_data = {
            "device_id": dev_id,
            "docker_command": f"sudo docker run -d -e MODEL_NAME={slug} -p 8300:8000 aoni/vllm/vllm-openai:latest"
        }
        update_res = requests.post(f"{BASE_URL}/models/{slug}/device-configs", json=config_data)
        self.assertEqual(update_res.status_code, 200)
        print(f"✅ [模型管理] 设备 #{dev_id} 上更新 '{slug}' 专属 Docker 配置成功")

if __name__ == "__main__":
    unittest.main()
