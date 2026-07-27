"""
AONI 自动化测试套件 — 测试报告模块 (Reports)
包含设备筛选、对比吞吐量/准确率及下载 Markdown 报告测试
"""
import requests
import unittest

BASE_URL = "http://127.0.0.1:8800/api"

class TestReportsModule(unittest.TestCase):

    def test_01_get_reports_list(self):
        """测试获取测试报告列表及设备维度筛选"""
        res = requests.get(f"{BASE_URL}/reports")
        self.assertEqual(res.status_code, 200)
        reports = res.json()
        self.assertIsInstance(reports, list)
        print(f"✅ [测试报告] 获取测试报告成功，当前已有报告数: {len(reports)}")

    def test_02_compare_throughput_and_accuracy(self):
        """测试横向多模型/多设备对比数据接口 (吞吐量与准确率)"""
        # 1. 吞吐量对比
        tput_res = requests.get(f"{BASE_URL}/reports/compare/throughput")
        self.assertEqual(tput_res.status_code, 200)
        tput_data = tput_res.json()
        self.assertIsInstance(tput_data, list)
        print(f"✅ [测试报告] 吞吐量横向对比接口正常，数据条数: {len(tput_data)}")

        # 2. 准确率对比
        acc_res = requests.get(f"{BASE_URL}/reports/compare/accuracy?dataset=mmlu")
        self.assertEqual(acc_res.status_code, 200)
        acc_data = acc_res.json()
        self.assertIsInstance(acc_data, list)
        print(f"✅ [测试报告] 准确率横向对比接口正常，数据条数: {len(acc_data)}")

    def test_03_report_download(self):
        """测试导出/下载 Markdown 格式报告文件"""
        reports = requests.get(f"{BASE_URL}/reports").json()
        if reports:
            target_id = reports[0]["id"]
            dl_res = requests.get(f"{BASE_URL}/reports/{target_id}/download")
            self.assertEqual(dl_res.status_code, 200)
            self.assertIn("模型测试报告", dl_res.text)
            print(f"✅ [测试报告] 导出报告 #{target_id} Markdown 文件成功")

if __name__ == "__main__":
    unittest.main()
