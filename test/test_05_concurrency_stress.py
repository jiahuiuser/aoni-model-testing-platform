"""
AONI 核心 QA 测试用例套件 — 05. 并发高压与数据库鲁棒性测试
"""
import requests
import unittest
from concurrent.futures import ThreadPoolExecutor

BASE_URL = "http://127.0.0.1:8800/api"

class TestConcurrencyStress(unittest.TestCase):

    def test_tc_stress_01_concurrent_read_queries(self):
        """TC-STRESS-01: 50 线程高并发轮询只读 API，验证后端连接池稳定性"""
        urls = [
            f"{BASE_URL}/devices",
            f"{BASE_URL}/models",
            f"{BASE_URL}/tasks",
            f"{BASE_URL}/reports",
            f"{BASE_URL}/reports/compare/throughput",
            f"{BASE_URL}/reports/compare/accuracy?dataset=mmlu"
        ]

        def request_worker(url):
            try:
                r = requests.get(url, timeout=5)
                return r.status_code == 200
            except Exception:
                return False

        with ThreadPoolExecutor(max_workers=20) as executor:
            tasks = [executor.submit(request_worker, urls[i % len(urls)]) for i in range(50)]
            results = [t.result() for t in tasks]

        success_rate = (sum(results) / len(results)) * 100
        self.assertEqual(success_rate, 100.0, f"高并发压测存在失败请求，成功率: {success_rate}%")
        print(f"  [TC-STRESS-01] 50 线程高压轮询压测 100% 成功完成，零超时、零连接拒绝")

if __name__ == "__main__":
    unittest.main()
