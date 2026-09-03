"""
大模型测试平台 — 功能测试: 大海捞针 (Needle-in-a-Haystack)

移植自 aoni-model-deploy/benchmarks/bench_hy4_needle.py
在长文本中嵌入 needle, 问模型 needle 内容, 验证长上下文检索正确性。
"""
import json
import time
import urllib.request

from backend.services.features._common import chat_url

NEEDLE = "The magic password for the secret vault is: ZEPHYR-7X-QUARTZ-9921."

DEFAULT_LENGTHS = [4096, 32768]
DEFAULT_REPEAT = 2


def make_haystack(target_tokens, needle, needle_pos_pct=0.5):
    """构造 ~target_tokens 的 haystack, needle 插在 pos_pct 位置。"""
    filler_para = ("The quick brown fox jumps over the lazy dog near the riverbank. "
                   "She sells seashells by the seashore on sunny afternoons. "
                   "Technology evolves rapidly in the modern era of computing. ")
    chars_per_token = 4.0
    target_chars = int(target_tokens * chars_per_token)
    copies = max(1, target_chars // len(filler_para))
    prefix = filler_para * (copies // 2)
    suffix = filler_para * (copies - copies // 2)
    insert_idx = int(len(prefix) * needle_pos_pct)
    haystack = prefix[:insert_idx] + "\n\n" + needle + "\n\n" + prefix[insert_idx:] + suffix
    return haystack


def check_needle(text):
    needles = ["ZEPHYR", "7X", "QUARTZ", "9921"]
    hits = sum(1 for n in needles if n in text.upper())
    return hits, needles


def _chat(base_url, model, content, api_key="", max_tokens=512, timeout=300):
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        chat_url(base_url),
        data=payload, headers=headers,
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        d = json.loads(resp.read())
    dt = time.time() - t0
    msg = d["choices"][0]["message"]
    content_out = msg.get("content") or ""
    reasoning = msg.get("reasoning") or msg.get("reasoning_content") or ""
    return dt, content_out + " " + reasoning, content_out


def run(base_url, model, api_key="", options=None, log_callback=None):
    """执行大海捞针测试，返回统一 FeatureResult dict"""
    options = options or {}
    lengths = options.get("lengths") or DEFAULT_LENGTHS
    repeat = int(options.get("repeat", DEFAULT_REPEAT))

    def log(msg):
        if log_callback:
            log_callback("INFO", "", f"  {msg}", "feature")

    total = 0
    passed = 0
    details = []

    for length in lengths:
        for i in range(repeat):
            pos = 0.3 + (i * 0.3)
            haystack = make_haystack(length, NEEDLE, pos)
            question = ("What is the magic password for the secret vault? "
                        "Answer with ONLY the password, nothing else.")
            try:
                dt, full, content = _chat(base_url, model, haystack + "\n\n" + question, api_key)
            except Exception as e:
                total += 1
                details.append({"length": length, "pos": round(pos, 2), "hit": False,
                                "dt": None, "content": f"ERROR: {e}"[:200]})
                log(f"[needle] len={length} pos={pos:.0%} ERROR: {e}")
                continue
            total += 1
            hits, _ = check_needle(full)
            hit = hits >= 3
            if hit:
                passed += 1
            details.append({"length": length, "pos": round(pos, 2), "hit": hit,
                            "hits": f"{hits}/4", "dt": round(dt, 1), "content": content[:200]})
            log(f"[needle] len={length:>6} pos={pos:.0%} {'PASS' if hit else 'FAIL'} "
                f"hits={hits}/4 dt={dt:.1f}s")

    status = "PASS" if (total > 0 and passed == total) else ("FAIL" if total else "SKIP")
    message = f"通过 {passed}/{total} ({passed * 100 // total if total else 0}%)"
    return {
        "category": "feature",
        "feature_key": "needle",
        "test_item": "大海捞针（长上下文检索）",
        "status": status,
        "latency_ms": None,
        "message": message,
        "raw_details": {"passed": passed, "total": total, "details": details},
    }
