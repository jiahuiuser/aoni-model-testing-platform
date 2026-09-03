"""
大模型测试平台 — 功能测试: 工具调用冒烟快筛

移植自 aoni-model-deploy/benchmarks/glm53_tool_smoke.py
5 工具简单场景冒烟。失败 = 权重/推理栈有硬伤; 通过 ≠ 可用(需配合 agent_replay)。
"""
import json
import time
import urllib.request

from backend.services.features._common import chat_url


def _mk(n, d, p, r):
    inner = {"name": n, "description": d, "parameters": {"type": "object", "properties": p, "required": r}}
    return {"type": "function", "function": inner}


def run(base_url, model, api_key="", options=None, log_callback=None):
    """执行工具调用冒烟测试，返回统一 FeatureResult dict"""
    tools = [
        _mk("bash", "Execute a bash command and return output",
            {"command": {"type": "string", "description": "cmd"}}, ["command"]),
        _mk("read", "Read file contents",
            {"path": {"type": "string", "description": "path"}}, ["path"]),
        _mk("glob", "Find files matching a glob pattern",
            {"pattern": {"type": "string", "description": "pattern"}}, ["pattern"]),
        _mk("grep", "Search file contents with regex",
            {"pattern": {"type": "string", "description": "pattern"}}, ["pattern"]),
        _mk("edit", "Edit file",
            {"file": {"type": "string", "description": "file"}}, ["file"]),
    ]

    def log(msg):
        if log_callback:
            log_callback("INFO", "", f"  {msg}", "feature")

    url = chat_url(base_url)
    total_ok = total = 0
    details = []

    # 多 effort 档循环, 测不同推理档位下工具调用稳定性
    for eff in ["low", "medium", "high", None, None, None]:
        ok = fail = 0
        for _ in range(3):
            data = {
                "model": model,
                "messages": [{"role": "user", "content": "列出当前项目结构并读一下 README"}],
                "tools": tools,
                "tool_choice": "auto",
                "max_tokens": 300,
                "temperature": 0,
                "stream": False,
            }
            if eff:
                data["reasoning_effort"] = eff
            body = json.dumps(data).encode()
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    j = json.loads(resp.read())
                if j["choices"][0]["message"].get("tool_calls"):
                    ok += 1
                else:
                    fail += 1
            except Exception:
                fail += 1
        total_ok += ok
        total += 3
        details.append({"effort": eff or "default", "ok": ok, "fail": fail})
        log(f"[tool_smoke] effort={eff or 'default'}: {ok}/3 tool_calls")

    status = "PASS" if (total > 0 and total_ok == total) else ("FAIL" if total else "SKIP")
    message = f"tool_calls {total_ok}/{total}"
    return {
        "category": "feature",
        "feature_key": "tool_smoke",
        "test_item": "工具调用冒烟快筛",
        "status": status,
        "latency_ms": None,
        "message": message,
        "raw_details": {"total_ok": total_ok, "total": total, "details": details},
    }
