"""
AONI 核心 QA 测试用例套件 — 04. 测试报告与多维度比对测试
"""
import requests
import unittest

BASE_URL = "http://127.0.0.1:8800/api"

class TestReportsExtended(unittest.TestCase):

    def test_tc_rep_01_reports_list_filtering(self):
        """TC-REP-01: 测试报告列表与按设备过滤查询"""
        res = requests.get(f"{BASE_URL}/reports")
        self.assertEqual(res.status_code, 200)
        reports = res.json()
        self.assertIsInstance(reports, list)

        # 设备维度过滤测试
        devices = requests.get(f"{BASE_URL}/devices").json()
        if devices:
            dev_id = devices[0]["id"]
            filtered_res = requests.get(f"{BASE_URL}/reports?device_id={dev_id}")
            self.assertEqual(filtered_res.status_code, 200)
            print(f"  [TC-REP-01] 设备 #{dev_id} 过滤报告列表成功")

    def test_tc_rep_02_cross_model_comparison_apis(self):
        """TC-REP-02: 多模型/多设备横向对比 API (吞吐量与准确率) 稳定性测试"""
        tput_res = requests.get(f"{BASE_URL}/reports/compare/throughput")
        self.assertEqual(tput_res.status_code, 200)
        self.assertIsInstance(tput_res.json(), list)

        acc_res = requests.get(f"{BASE_URL}/reports/compare/accuracy?dataset=mmlu")
        self.assertEqual(acc_res.status_code, 200)
        self.assertIsInstance(acc_res.json(), list)
        print("  [TC-REP-02] 跨模型横向吞吐与准确率对比 API 测试通过")

    def test_tc_rep_03_markdown_export_validity(self):
        """TC-REP-03: 一键导出 Markdown 报告完整性校验"""
        reports = requests.get(f"{BASE_URL}/reports").json()
        if reports:
            rep_id = reports[0]["id"]
            dl_res = requests.get(f"{BASE_URL}/reports/{rep_id}/download")
            self.assertEqual(dl_res.status_code, 200)
            text = dl_res.text
            self.assertIn("# ", text)
            self.assertIn("准确率测试结果", text)
            print(f"  [TC-REP-03] 报告 #{rep_id} Markdown 导出校验成功")

if __name__ == "__main__":
    unittest.main()
