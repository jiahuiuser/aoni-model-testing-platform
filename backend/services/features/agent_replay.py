"""
大模型测试平台 — 功能测试: Agent 多工具决定性回归

移植自 aoni-model-deploy/benchmarks/validate_agent.py (段B) + glm53_opencode_replay.py
真实 opencode agent 请求 (39 工具 + 33K content) 固化重放 × N。
简单测试全过但真实 agent 请求退化的量化问题, 只有此测试能暴露。
"""
import json
import os
import time
import urllib.request

from backend.services.features._common import chat_url

HERE = os.path.dirname(os.path.abspath(__file__))
REPLAY_REQ_PATH = os.path.join(HERE, "glm53_opencode_req.json")

DEFAULT_RUNS = 3


def _stream_once(url, body, api_key="", wall_limit=600):
    """单次流式请求。返回 dict(content, reasoning*, tool_calls, finish, ...)"""
    t0 = time.time()
    res = {"content": "", "reasoning": "", "reasoning_content": "", "tool_calls": [],
           "finish": "", "chunks": 0, "ttft": None, "elapsed": None, "error": None,
           "status": None, "error_body": ""}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers=headers, method="POST")
        resp = urllib.request.urlopen(req, timeout=wall_limit)
        res["status"] = resp.status
        buf = b""
        while True:
            if time.time() - t0 > wall_limit:
                res["error"] = "wall-clock timeout (%ds)" % wall_limit
                break
            chunk = resp.readline()
            if not chunk:
                break
            buf += chunk
            if not buf.endswith(b"\n"):
                continue
            line = buf.decode(errors="replace").strip()
            buf = b""
            if not line.startswith("data: "):
                continue
            if "[DONE]" in line:
                break
            try:
                d = json.loads(line[6:])
            except Exception:
                continue
            res["chunks"] += 1
            ch_list = d.get("choices") or [{}]
            if not ch_list:
                continue
            ch = ch_list[0]
            if ch.get("finish_reason"):
                res["finish"] = ch["finish_reason"]
            dl = ch.get("delta") or {}
            if dl.get("content"):
                if res["ttft"] is None:
                    res["ttft"] = time.time() - t0
                res["content"] += dl["content"]
            if dl.get("reasoning_content"):
                if res["ttft"] is None:
                    res["ttft"] = time.time() - t0
                res["reasoning_content"] += dl["reasoning_content"]
            if dl.get("reasoning"):
                if res["ttft"] is None:
                    res["ttft"] = time.time() - t0
                res["reasoning"] += dl["reasoning"]
            for tc in dl.get("tool_calls") or []:
                while len(res["tool_calls"]) <= tc.get("index", 0):
                    res["tool_calls"].append({"id": None, "name": "", "arguments": ""})
                i = tc["index"]
                if tc.get("id"):
                    res["tool_calls"][i]["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    res["tool_calls"][i]["name"] = fn["name"]
                res["tool_calls"][i]["arguments"] += fn.get("arguments") or ""
    except urllib.error.HTTPError as e:
        res["status"] = e.code
        try:
            res["error_body"] = e.read().decode(errors="replace")[:200]
        except Exception:
            pass
        res["error"] = "HTTP %d: %s" % (e.code, res["error_body"])
    except Exception as ex:
        res["error"] = str(ex)[:120]
    res["elapsed"] = time.time() - t0
    res["tool_calls"] = [t for t in res["tool_calls"] if t["id"] or t["name"]]
    return res


def _judge(res):
    """判定一次请求: (ok, note)。ok=None 表示 SKIP(服务端不支持, 非质量问题)。"""
    if res.get("error"):
        if res.get("status") == 400:
            return None, "SKIP(400 不支持): %s" % res.get("error_body", "")[:100]
        return False, res["error"]
    if not res["tool_calls"]:
        if res["finish"] == "length" and (res["reasoning"] or res["reasoning_content"]):
            return False, "思考耗尽预算(reasoning=%d字符,无tool_call)" % (
                len(res["reasoning"]) + len(res["reasoning_content"]))
        if res["chunks"] == 0:
            return False, "零chunk空响应"
        return False, "无tool_call, finish=%s, content=%r" % (res["finish"] or "?", res["content"][:60])
    tc = res["tool_calls"][0]
    if not tc["id"]:
        return False, "tool_call id 为 null (name=%s)" % tc["name"]
    try:
        json.loads(tc["arguments"])
        return True, "name=%s args-ok" % tc["name"]
    except Exception:
        return False, "args 截断/非法: %r" % tc["arguments"][:60]


def run(base_url, model, api_key="", options=None, log_callback=None):
    """执行 Agent 决定性重放测试，返回统一 FeatureResult dict"""
    options = options or {}
    runs = int(options.get("runs", DEFAULT_RUNS))

    def log(msg):
        if log_callback:
            log_callback("INFO", "", f"  {msg}", "feature")

    if not os.path.exists(REPLAY_REQ_PATH):
        return {
            "category": "feature",
            "feature_key": "agent_replay",
            "test_item": "Agent 多工具决定性回归",
            "status": "SKIP",
            "latency_ms": None,
            "message": "重放请求文件缺失: glm53_opencode_req.json",
            "raw_details": {},
        }

    with open(REPLAY_REQ_PATH) as f:
        body = json.load(f)
    body["model"] = model
    body["stream"] = True
    body["max_tokens"] = 500

    url = chat_url(base_url)
    ok = 0
    details = []
    for i in range(runs):
        res = _stream_once(url, body, api_key=api_key)
        passed, note = _judge(res)
        if passed:
            ok += 1
        details.append({
            "run": i + 1,
            "ok": bool(passed),
            "note": note,
            "ttft": round(res["ttft"], 1) if res["ttft"] else None,
            "elapsed": round(res["elapsed"], 1) if res["elapsed"] else None,
        })
        log(f"[agent_replay] run {i + 1}/{runs} {'OK' if passed else 'FAIL'} {note}")

    status = "PASS" if (runs > 0 and ok == runs) else ("FAIL" if runs else "SKIP")
    message = f"重放通过 {ok}/{runs}"
    return {
        "category": "feature",
        "feature_key": "agent_replay",
        "test_item": "Agent 多工具决定性回归",
        "status": status,
        "latency_ms": None,
        "message": message,
        "raw_details": {"ok": ok, "runs": runs, "details": details},
    }
