"""
大模型测试平台 — 功能测试: 数学正确性

移植自 aoni-model-deploy/benchmarks/test_dsv4_pd_math_correctness.py
多道确定性数学题, 检查模型基础运算正确性与确定性错误。
"""
import json
import re
import time
import urllib.request

from backend.services.features._common import chat_url

# 数学题 (表达式, 期望值由 eval 自动计算)
MATH_QUESTIONS = [
    "17*23",
    "13*17",
    "99*99",
    "1+1",
    "12*13",
    "9*9",
    "50+50",
    "100-37",
    "2**10",
    "15*15",
    "7*8",
    "123+456",
]


def expected_answer(expr):
    """安全计算期望值 (只允许数字和运算符)。"""
    assert re.fullmatch(r"[\d+\-*/() ]+", expr), f"unsafe expr: {expr}"
    return str(eval(expr))


def run(base_url, model, api_key="", options=None, log_callback=None):
    """执行数学正确性测试，返回统一 FeatureResult dict"""
    options = options or {}
    timeout = int(options.get("timeout", 120))

    def log(msg):
        if log_callback:
            log_callback("INFO", "", f"  {msg}", "feature")

    total = 0
    correct = 0
    wrong_items = []

    for expr in MATH_QUESTIONS:
        expected = expected_answer(expr)
        body = json.dumps({
            "model": model,
            "messages": [
                {"role": "user", "content": f"What is {expr}? Reply with ONLY the number, nothing else."}
            ],
            "max_tokens": 256,
            "temperature": 0,
            "seed": 0,
        }).encode()
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(
            chat_url(base_url),
            data=body, headers=headers, method="POST",
        )
        try:
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
            _dt = time.time() - t0
            msg = data["choices"][0]["message"]
            ans = (msg.get("content") or msg.get("reasoning") or "").strip()
        except Exception as e:
            total += 1
            wrong_items.append({"expr": expr, "expected": expected, "got": f"ERR: {e}"})
            log(f"[math] {expr:10s} ERROR: {e}")
            continue

        total += 1
        if expected in ans:
            correct += 1
            log(f"[math] {expr:10s} PASS ({expected})")
        else:
            wrong_items.append({"expr": expr, "expected": expected, "got": ans[:80]})
            log(f"[math] {expr:10s} FAIL expect={expected} got={ans[:40]!r}")

    status = "PASS" if (total > 0 and correct == total) else ("FAIL" if total else "SKIP")
    if wrong_items and len(wrong_items) >= 2:
        status = "FAIL"
    message = f"正确 {correct}/{total}" + ("（存在确定性错误，需关注）" if wrong_items else "")
    return {
        "category": "feature",
        "feature_key": "math",
        "test_item": "数学正确性",
        "status": status,
        "latency_ms": None,
        "message": message,
        "raw_details": {"correct": correct, "total": total, "wrong_items": wrong_items},
    }
