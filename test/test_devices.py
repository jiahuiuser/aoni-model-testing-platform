"""
AONI 自动化测试套件 — 设备管理模块 (Device Management)
"""
import requests
import unittest

BASE_URL = "http://127.0.0.1:8800/api"

class TestDeviceManagement(unittest.TestCase):
    
    def test_01_get_devices_list(self):
        """测试获取设备节点列表"""
        res = requests.get(f"{BASE_URL}/devices")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)
        self.assertTrue(len(data) >= 1)
        # 验证必须包含本机节点
        has_local = any(d.get("name") in ("本机", "本机节点", "Jetson Thor (本机)") or d.get("host") == "127.0.0.1" for d in data)
        self.assertTrue(has_local, "设备列表中未找到本机节点")
        print(f"✅ [设备管理] 获取设备列表成功，当前节点数: {len(data)}")

    def test_02_device_health_check(self):
        """测试节点诊断与连通性检查功能"""
        res = requests.get(f"{BASE_URL}/devices")
        devices = res.json()
        local_dev = devices[0]
        
        # 触发节点检查
        check_res = requests.post(f"{BASE_URL}/devices/{local_dev['id']}/check")
        self.assertEqual(check_res.status_code, 200)
        detail = check_res.json()
        self.assertIn("ssh_ok", detail)
        print(f"✅ [设备管理] 节点 {local_dev['name']} 诊断检查成功: SSH={detail.get('ssh_ok')}, Docker={detail.get('docker_ok')}")

if __name__ == "__main__":
    unittest.main()
