"""
AONI 核心 QA 测试用例套件 — 一键全量自动化测试引擎
涵盖 5 大维度：设备扩展、模型/DockerRun防卡死、任务隔离与生命周期、报告比对、高并发高压压测
"""
import sys
import time
import unittest
from pathlib import Path

# 添加路径
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_01_devices_extended import TestDevicesExtended
from test_02_models_extended import TestModelsExtended
from test_03_tasks_extended import TestTasksExtended
from test_04_reports_extended import TestReportsExtended
from test_05_concurrency_stress import TestConcurrencyStress
from test_06_real_business_pipeline import TestRealBusinessPipeline

def run_all_qa_suites():
    print("=" * 75)
    print("🚀 AONI 模型测试平台 — 企业级 QA 自动化测试套件 (Test Suite)")
    print(f"🕒 执行时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 75)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTest(loader.loadTestsFromTestCase(TestDevicesExtended))
    suite.addTest(loader.loadTestsFromTestCase(TestModelsExtended))
    suite.addTest(loader.loadTestsFromTestCase(TestTasksExtended))
    suite.addTest(loader.loadTestsFromTestCase(TestReportsExtended))
    suite.addTest(loader.loadTestsFromTestCase(TestConcurrencyStress))
    suite.addTest(loader.loadTestsFromTestCase(TestRealBusinessPipeline))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 75)
    if result.wasSuccessful():
        print("🎉 [QA 测试总结] 恭喜！全平台 5 大维度高级测试用例 100% 成功通过！后端服务无死锁、无挂起、零崩溃！")
    else:
        print(f"❌ [QA 测试总结] 包含 {len(result.failures)} 处失败, {len(result.errors)} 处错误")
    print("=" * 75)

    return result.wasSuccessful()

if __name__ == "__main__":
    success = run_all_qa_suites()
    sys.exit(0 if success else 1)
