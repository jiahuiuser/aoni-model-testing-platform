"""
AONI 核心 QA 测试用例套件 — 01. 设备管理扩展测试
"""
import requests
import unittest

BASE_URL = "http://127.0.0.1:8800/api"

class TestDevicesExtended(unittest.TestCase):

    def test_tc_dev_01_get_devices_list(self):
        """TC-DEV-01: 获取设备节点列表与结构校验"""
        res = requests.get(f"{BASE_URL}/devices")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1, "设备列表至少应包含 1 个本机节点")
        print(f"  [TC-DEV-01] 成功获取 {len(data)} 个设备节点")

    def test_tc_dev_02_device_health_check(self):
        """TC-DEV-02: 节点健康度与算力资源深度诊断"""
        res = requests.get(f"{BASE_URL}/devices")
        devices = res.json()
        local_dev = devices[0]

        check_res = requests.post(f"{BASE_URL}/devices/{local_dev['id']}/check")
        self.assertEqual(check_res.status_code, 200)
        body = check_res.json()
        self.assertIn("status", body)
        self.assertIn("detail", body)
        detail = body["detail"]
        self.assertTrue(detail.get("ssh_ok"))
        self.assertTrue(detail.get("docker_ok"))
        print(f"  [TC-DEV-02] 节点 '{local_dev['name']}' 诊断通过: Docker容器数={len(detail.get('docker_containers', []))}")

    def test_tc_dev_03_invalid_device_handling(self):
        """TC-DEV-03: 针对不存在或非法的设备 ID 异常边界测试"""
        res = requests.get(f"{BASE_URL}/devices/99999")
        self.assertIn(res.status_code, (404, 422))
        print("  [TC-DEV-03] 异常设备 ID 正确响应 404/422 Error")

    def test_tc_dev_04_credentials_crud(self):
        """TC-DEV-04: SSH 凭据全生命周期 CRUD 测试"""
        cred_payload = {
            "name": "QA_Test_SSH_Key",
            "type": "ssh_key",
            "ssh_username": "qa_runner",
            "ssh_port": 2222,
            "ssh_key_path": "/home/sd1/.ssh/id_rsa",
            "description": "QA 自动化测试使用"
        }
        # 创建
        c_res = requests.post(f"{BASE_URL}/credentials", json=cred_payload)
        self.assertEqual(c_res.status_code, 200)
        cred = c_res.json()
        cred_id = cred["id"]

        # 查
        list_res = requests.get(f"{BASE_URL}/credentials")
        self.assertTrue(any(c["id"] == cred_id for c in list_res.json()))

        # 改
        u_res = requests.put(f"{BASE_URL}/credentials/{cred_id}", json={"ssh_port": 2223})
        self.assertEqual(u_res.status_code, 200)

        # 删
        d_res = requests.delete(f"{BASE_URL}/credentials/{cred_id}")
        self.assertEqual(d_res.status_code, 200)
        print(f"  [TC-DEV-04] SSH 凭据 CRUD 生命周期测试全量通过")

if __name__ == "__main__":
    unittest.main()
