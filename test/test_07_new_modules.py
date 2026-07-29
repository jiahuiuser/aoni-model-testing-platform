import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from fastapi.testclient import TestClient
from backend.main import app

class TestNewModules(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    def test_01_hardware_groups_crud(self):
        """验证硬件组列表与新增/删除"""
        res = self.client.get("/api/hardware-groups")
        self.assertEqual(res.status_code, 200)
        groups = res.json()
        self.assertTrue(len(groups) >= 4)

        # 创建新硬件组
        new_res = self.client.post("/api/hardware-groups", json={
            "name": "NVIDIA_H100_SXM",
            "description": "NVIDIA H100 80GB HBM3"
        })
        self.assertEqual(new_res.status_code, 200)
        hg_id = new_res.json()["id"]

        # 删除
        del_res = self.client.delete(f"/api/hardware-groups/{hg_id}")
        self.assertEqual(del_res.status_code, 200)

    def test_02_data_mgmt_templates_and_datasets(self):
        """验证测试用例模板 CRUD 与数据集在线下载"""
        res = self.client.get("/api/data/templates")
        self.assertEqual(res.status_code, 200)
        tpls = res.json()
        self.assertTrue(len(tpls) >= 3)

        # 创建模板
        create_res = self.client.post("/api/data/templates", json={
            "name": "自动化测试模板",
            "description": "接口测试",
            "num_prompts": 200,
            "input_lens": [128, 512],
            "output_lens": [128],
            "concurrencies": [1, 4, 8],
            "datasets": ["mmlu"],
            "acc_limit": 100
        })
        self.assertEqual(create_res.status_code, 200)

        # 数据集列表
        ds_res = self.client.get("/api/data/datasets")
        self.assertEqual(ds_res.status_code, 200)

    def test_03_images_management(self):
        """验证 Docker 镜像管理"""
        res = self.client.get("/api/images")
        self.assertEqual(res.status_code, 200)
        images = res.json()
        self.assertTrue(len(images) >= 3)


if __name__ == "__main__":
    unittest.main()
