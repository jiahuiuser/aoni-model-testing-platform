"""
大模型测试平台 — 功能测试: 长上下文乱码检测

移植自 aoni-model-deploy/benchmarks/check_gpu6_dspark_garble.py
分层长度扫描输出, 检测乱码 (U+FFFD/空字节/重复符号堆叠) 与空输出。
"""
import json
import re
import time
import urllib.request

from backend.services.features._common import chat_url

DEFAULT_TOKEN_SIZES = [256, 2048]

FILL = "知识库条目 {}：DeepSeek 是深度求索开发的大语言模型。参与本项目长期稳定性验证。\n"
Q_TEMPLATE = "\n参考以上内容，只回答最终数字：7 × 9 等于多少？答案是一个整数，不要多余内容。"
# 标定: 每条约 25.1 token
TOK_PER_ENTRY = 25.1


def _garble(text):
    """返回 (is_garble, hint)"""
    if not text:
        return True, "空输出"
    if "\ufffd" in text or "\x00" in text:
        return True, "含 U+FFFD/空字节"
    if re.search(r"([+#*=&\-]{3,})", text):
        return True, "重复符号堆叠"
    return False, ""


def _longest_run(text):
    return max((len(m.group(0)) for m in re.finditer(r"(.)\1+", text)), default=0)


def _build(prompt_tokens):
    n = max(1, int(prompt_tokens / TOK_PER_ENTRY))
    body = "".join(FILL.format(i) for i in range(n))
    return body + Q_TEMPLATE


def run(base_url, model, api_key="", options=None, log_callback=None):
    """执行长上下文乱码检测，返回统一 FeatureResult dict"""
    options = options or {}
    token_sizes = options.get("token_sizes") or DEFAULT_TOKEN_SIZES

    def log(msg):
        if log_callback:
            log_callback("INFO", "", f"  {msg}", "feature")

    details = []
    garble_count = 0
    total = 0

    for target in token_sizes:
        prompt = _build(target)
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 64,
            "temperature": 0.0,
            "stream": False,
        }).encode()
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(
            chat_url(base_url),
            data=body, headers=headers,
        )
        total += 1
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
            text = data["choices"][0]["message"]["content"] or ""
        except Exception as e:
            garble_count += 1
            details.append({"target": target, "status": "ERROR", "hint": str(e)[:100]})
            log(f"[garble] {target:>6}tok ERROR: {e}")
            continue

        is_garble, hint = _garble(text)
        if is_garble:
            garble_count += 1
        details.append({
            "target": target,
            "status": "GARBLE" if is_garble else "OK",
            "hint": hint if is_garble else f"run={_longest_run(text)}",
            "preview": text[:60],
        })
        log(f"[garble] {target:>6}tok {'乱码!' if is_garble else 'OK'} {hint or ''}")

    status = "PASS" if (total > 0 and garble_count == 0) else ("FAIL" if total else "SKIP")
    message = f"扫描 {total} 层, 乱码 {garble_count} 层" if total else "无测试数据"
    return {
        "category": "feature",
        "feature_key": "garble",
        "test_item": "长上下文乱码检测",
        "status": status,
        "latency_ms": None,
        "message": message,
        "raw_details": {"garble_count": garble_count, "total": total, "details": details},
    }
