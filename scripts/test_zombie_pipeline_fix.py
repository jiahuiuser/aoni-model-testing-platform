#!/usr/bin/env python3
"""
回归测试: 暂停 → 删除 → 重建同 id 任务，验证僵尸流水线不再污染新任务

场景复现 (2026-09-03 事故):
  1. 创建任务 A (gen=1) → 流水线启动
  2. 暂停任务 A → 流水线挂起在 _check_pause
  3. 删除任务 A → cancel 标志设置 (旧版会在 0.5s 后被误复位)
  4. 重建同 id 任务 B → start_task 复位 cancel 标志 + bump generation
  5. 旧流水线 (gen=1) 应在下一个检查点退出，不再执行
"""
import sys
import warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

import time


def test_stale_pipeline_detection():
    from backend.services import task_manager as tm

    print("=== 场景: 暂停 → 删除 → 重建同 id 任务 ===")

    # 模拟任务 id=999 的第一代流水线
    task_id = 999
    tm._task_generation[task_id] = 1
    tm._pipeline_gen_start[task_id] = 1
    gen_old = 1

    # 模拟 pause (流水线会挂起)
    tm._pause_flags[task_id] = True

    # 模拟 delete: cancel_task 设标志且不复位
    tm._cancel_flags[task_id] = True
    tm._pause_flags.pop(task_id, None)

    # 模拟重建: start_task 复位标志 + bump generation
    tm._task_generation[task_id] = 2  # start_task: gen += 1
    tm._cancel_flags[task_id] = False  # start_task 复位
    tm._pause_flags[task_id] = False

    # === 旧流水线在 _check_pause 中醒来检查 ===
    # 旧版代码: cancel 标志已被复位 + 无代际检查 → 僵尸存活
    # 新版代码: is_pipeline_stale 应返回 True
    stale = tm.is_pipeline_stale(task_id)
    assert stale, "FAIL: 旧流水线应检测到自己已过时"
    print("  [PASS] 旧代流水线 (gen=1) 检测到 is_pipeline_stale=True → 自行退出 ✓")

    # 新流水线不应过时
    tm._pipeline_gen_start[task_id] = 2
    assert not tm.is_pipeline_stale(task_id), "FAIL: 新流水线不应过时"
    print("  [PASS] 新代流水线 (gen=2) is_pipeline_stale=False → 正常运行 ✓")
    print()


    print("=== 场景: 同代流水线不受影响 ===")
    tm._pipeline_gen_start[task_id] = 2
    assert not tm.is_pipeline_stale(task_id)
    print("  [PASS] 未被取代的流水线正常 ✓")
    print()

    print("=== 场景: 未知任务 (无登记) 默认不过时 ===")
    assert not tm.is_pipeline_stale(12345)
    print("  [PASS] 无登记任务 is_pipeline_stale=False ✓")
    print()

    # 清理
    tm._task_generation.pop(task_id, None)
    tm._pipeline_gen_start.pop(task_id, None)
    tm._cancel_flags.pop(task_id, None)
    tm._pause_flags.pop(task_id, None)

    print("=== 全部通过 ===")


if __name__ == "__main__":
    test_stale_pipeline_detection()
