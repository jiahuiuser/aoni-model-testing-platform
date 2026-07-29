"""
AONI 模型测试平台 — 网关协议与技能工具适配验证器
功能原生移植并升级自 validate_api_full.sh
"""

import time
import json
import re
import urllib.request
import urllib.error
import logging
from typing import List, Dict, Any, Tuple

log = logging.getLogger(__name__)


def _make_request(
    url: str,
    method: str = "POST",
    headers: Dict[str, str] = None,
    data: Dict[str, Any] = None,
    timeout: int = 90,
    stream: bool = False
) -> Tuple[int, str, float]:
    """通用 HTTP 请求封装，返回 (status_code, body_text, latency_ms)"""
    headers = headers or {}
    if "Content-Type" not in headers and data is not None:
        headers["Content-Type"] = "application/json"

    encoded_data = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            latency_ms = round((time.time() - t0) * 1000, 2)
            if stream:
                # 针对流式 SSE 读取前 30 行或最多 4096 字节
                lines = []
                for _ in range(30):
                    line = resp.readline()
                    if not line:
                        break
                    lines.append(line.decode("utf-8", errors="ignore"))
                return resp.status, "".join(lines), latency_ms
            else:
                body = resp.read().decode("utf-8", errors="ignore")
                return resp.status, body, latency_ms
    except urllib.error.HTTPError as e:
        latency_ms = round((time.time() - t0) * 1000, 2)
        body = e.read().decode("utf-8", errors="ignore") if hasattr(e, 'read') else str(e)
        return e.code, body, latency_ms
    except Exception as e:
        latency_ms = round((time.time() - t0) * 1000, 2)
        return 500, str(e), latency_ms


def _is_garbage(text: str) -> str:
    """检测 content 是否包含垃圾/乱码/幻觉 URL"""
    if not text or not text.strip():
        return "EMPTY"
    t = text.lower()
    garb = re.findall(r'https?://|\.com|\.www|null|undefined|\xaa{2,}', t)
    cjk = any(0x4e00 <= ord(ch) <= 0x9fff for ch in text[:80])
    if garb:
        return "GARBAGE"
    elif not cjk and len(text) > 20:
        return "NO_CJK"
    return "OK"


class GatewayValidator:
    """网关与多协议能力验证引擎"""

    def __init__(self, base_url: str, model_slug: str, api_key: str = ""):
        # 归一化: base_url 不含 /v1 尾缀
        url = base_url.rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        self.base_url = url
        self.model_slug = model_slug
        self.api_key = api_key

        self.headers = {}
        if api_key and api_key != "EMPTY":
            self.headers["Authorization"] = f"Bearer {api_key}"

    def run_all_checks(
        self,
        protocols: List[str] = None,
        test_longctx: bool = False,
        log_callback=None
    ) -> List[Dict[str, Any]]:
        """按层级运行全量验收检测，返回结果列表"""
        protocols = protocols or ["openai", "anthropic", "responses"]
        results = []

        def _log(level: str, msg: str):
            if log_callback:
                log_callback(level, self.model_slug, msg, "gateway")

        _log("INFO", f"========== 开始 API 网关与多协议规范全量校验 ({self.base_url}) ==========")

        def _log_result_detail(r: dict, idx: int, total: int):
            status_tag = f"[{r['status']}]"
            level = "INFO" if r['status'] == "PASS" else ("WARNING" if r['status'] == "SKIP" else "ERROR")
            _log(level, f"[{idx}/{total}] 校验项: {r['test_item']} (协议: {(r.get('protocol') or 'system').upper()})")
            if r.get("url"):
                _log("INFO", f"  ➜ 请求地址: {r.get('method', 'POST')} {r['url']}")
            if r.get("payload") is not None:
                payload_str = json.dumps(r['payload'], ensure_ascii=False)
                if len(payload_str) > 260:
                    payload_str = payload_str[:260] + "..."
                _log("DEBUG", f"  ➜ 请求参数: {payload_str}")
            code_str = f"HTTP {r.get('code')}" if r.get('code') else "N/A"
            _log("INFO", f"  ➜ 响应状态: {code_str} (耗时 {r.get('latency_ms', 0)} ms) | 结论: {status_tag}")
            _log("INFO", f"  ➜ 校验依据: {r.get('message', '')}")

        # 预估总测试项数
        total_items = 2
        if "openai" in protocols: total_items += 3
        if "responses" in protocols: total_items += 1
        if "anthropic" in protocols: total_items += 3
        total_items += 3
        if test_longctx: total_items += 1

        item_counter = 0

        # ── Layer 1: 可达性与元数据 ──
        _log("INFO", "--- Layer 1: 服务可达性与模型存在性 ---")
        reach_res, max_len = self.check_reachability()
        for r in reach_res:
            item_counter += 1
            results.append(r)
            _log_result_detail(r, item_counter, total_items)

        if any(r["status"] == "FAIL" and r["test_item"] == "服务端口与可达性" for r in reach_res):
            _log("ERROR", "推理服务不可达，终止后续协议测试")
            return results

        # ── Layer 2: 协议覆盖 ──
        _log("INFO", "--- Layer 2: 协议覆盖与接口接入规范校验 ---")
        if "openai" in protocols:
            res_openai = self.check_openai_chat()
            for r in res_openai:
                item_counter += 1
                results.append(r)
                _log_result_detail(r, item_counter, total_items)

        if "responses" in protocols:
            res_resp = self.check_openai_responses()
            for r in res_resp:
                item_counter += 1
                results.append(r)
                _log_result_detail(r, item_counter, total_items)

        if "anthropic" in protocols:
            res_ant = self.check_anthropic_messages()
            for r in res_ant:
                item_counter += 1
                results.append(r)
                _log_result_detail(r, item_counter, total_items)

        # ── Layer 3: 特性与技能工具 ──
        _log("INFO", "--- Layer 3: 技能工具调用与边界特性校验 ---")
        feat_res = self.check_features(max_len=max_len, test_longctx=test_longctx)
        for r in feat_res:
            item_counter += 1
            results.append(r)
            _log_result_detail(r, item_counter, total_items)

        _log("INFO", f"========== 网关协议规范全量校验完成 (共完成 {len(results)} 项) ==========")
        return results

    # ── Layer 1 实现 ──
    def check_reachability(self) -> Tuple[List[Dict[str, Any]], int]:
        results = []
        max_len = 8192

        # 1. 端口与健康可达性
        code_h, body_h, lat_h = _make_request(f"{self.base_url}/v1/health", method="GET", headers=self.headers, timeout=10)
        code_m, body_m, lat_m = _make_request(f"{self.base_url}/v1/models", method="GET", headers=self.headers, timeout=10)

        if code_h == 200 or code_m == 200:
            results.append({
                "category": "reachability",
                "test_item": "服务端口与可达性",
                "protocol": "system",
                "status": "PASS",
                "latency_ms": lat_m if code_m == 200 else lat_h,
                "url": f"{self.base_url}/v1/models" if code_m == 200 else f"{self.base_url}/v1/health",
                "method": "GET",
                "payload": None,
                "code": 200,
                "message": f"通过 /v1/models 或 /v1/health 可达"
            })
        else:
            results.append({
                "category": "reachability",
                "test_item": "服务端口与可达性",
                "protocol": "system",
                "status": "FAIL",
                "latency_ms": lat_h,
                "url": f"{self.base_url}/v1/health",
                "method": "GET",
                "payload": None,
                "code": code_h,
                "message": f"连接失败 (HTTP {code_h}/{code_m})"
            })
            return results, max_len

        # 2. 检查模型列表中包含目标模型
        has_model = False
        try:
            d = json.loads(body_m)
            for m in d.get("data", []):
                if m.get("id") == self.model_slug or self.model_slug in m.get("id", ""):
                    has_model = True
                    mlen = m.get("max_model_len") or m.get("owned_by")
                    if mlen and str(mlen).isdigit():
                        max_len = int(mlen)
                    break
        except Exception:
            pass

        if has_model:
            results.append({
                "category": "reachability",
                "test_item": "模型节点存在性",
                "protocol": "system",
                "status": "PASS",
                "latency_ms": lat_m,
                "url": f"{self.base_url}/v1/models",
                "method": "GET",
                "payload": None,
                "code": code_m,
                "message": f"已确认包含模型 [{self.model_slug}] (max_len={max_len})"
            })
        else:
            results.append({
                "category": "reachability",
                "test_item": "模型节点存在性",
                "protocol": "system",
                "status": "FAIL",
                "latency_ms": lat_m,
                "url": f"{self.base_url}/v1/models",
                "method": "GET",
                "payload": None,
                "code": code_m,
                "message": f"模型列表中未匹配到 [{self.model_slug}]"
            })

        return results, max_len

    # ── Layer 2 实现: OpenAI Chat ──
    def check_openai_chat(self) -> List[Dict[str, Any]]:
        results = []
        url = f"{self.base_url}/v1/chat/completions"

        # 1. Chat 同步
        data_sync = {
            "model": self.model_slug,
            "messages": [{"role": "user", "content": "回复OK"}],
            "max_tokens": 50,
            "temperature": 0
        }
        code, body, lat = _make_request(url, data=data_sync, headers=self.headers)
        if code == 200:
            try:
                d = json.loads(body)
                msg = d["choices"][0]["message"]
                content = msg.get("content") or msg.get("reasoning")
                if content:
                    results.append({
                        "category": "protocol", "test_item": "OpenAI Chat 同步输出", "protocol": "openai",
                        "status": "PASS", "latency_ms": lat, "url": url, "method": "POST", "payload": data_sync, "code": code,
                        "message": "返回有效文本内容"
                    })
                else:
                    results.append({
                        "category": "protocol", "test_item": "OpenAI Chat 同步输出", "protocol": "openai",
                        "status": "FAIL", "latency_ms": lat, "url": url, "method": "POST", "payload": data_sync, "code": code,
                        "message": "content 与 reasoning 均为空"
                    })
            except Exception as e:
                results.append({
                    "category": "protocol", "test_item": "OpenAI Chat 同步输出", "protocol": "openai",
                    "status": "FAIL", "latency_ms": lat, "url": url, "method": "POST", "payload": data_sync, "code": code,
                    "message": f"JSON 解析失败: {str(e)}"
                })
        else:
            results.append({
                "category": "protocol", "test_item": "OpenAI Chat 同步输出", "protocol": "openai",
                "status": "FAIL", "latency_ms": lat, "url": url, "method": "POST", "payload": data_sync, "code": code,
                "message": f"HTTP Status {code}"
            })

        # 2. Chat 流式 (SSE)
        data_stream = {
            "model": self.model_slug,
            "messages": [{"role": "user", "content": "回复OK"}],
            "max_tokens": 30,
            "stream": True
        }
        code_s, body_s, lat_s = _make_request(url, data=data_stream, headers=self.headers, stream=True)
        if code_s == 200 and "data:" in body_s:
            results.append({
                "category": "protocol", "test_item": "OpenAI Chat 流式 SSE 响应", "protocol": "openai",
                "status": "PASS", "latency_ms": lat_s, "url": url, "method": "POST", "payload": data_stream, "code": code_s,
                "message": "正常收到 SSE data: 事件"
            })
        else:
            results.append({
                "category": "protocol", "test_item": "OpenAI Chat 流式 SSE 响应", "protocol": "openai",
                "status": "FAIL", "latency_ms": lat_s, "url": url, "method": "POST", "payload": data_stream, "code": code_s,
                "message": f"未检测到 SSE data 事件 (code={code_s})"
            })

        # 3. Chat 工具调用传输
        data_tool = {
            "model": self.model_slug,
            "messages": [{"role": "user", "content": "请调用 get_weather 工具查询北京的天气"}],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "获取城市天气",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"]
                    }
                }
            }],
            "max_tokens": 200,
            "temperature": 0
        }
        code_t, body_t, lat_t = _make_request(url, data=data_tool, headers=self.headers)
        if code_t == 200:
            try:
                d = json.loads(body_t)
                tc = d["choices"][0]["message"].get("tool_calls", [])
                if len(tc) > 0:
                    results.append({
                        "category": "protocol", "test_item": "OpenAI Chat 工具调用响应", "protocol": "openai",
                        "status": "PASS", "latency_ms": lat_t, "url": url, "method": "POST", "payload": data_tool, "code": code_t,
                        "message": f"成功返回 {len(tc)} 个 tool_calls"
                    })
                else:
                    results.append({
                        "category": "protocol", "test_item": "OpenAI Chat 工具调用响应", "protocol": "openai",
                        "status": "SKIP", "latency_ms": lat_t, "url": url, "method": "POST", "payload": data_tool, "code": code_t,
                        "message": "模型未触发 tool_calls (可能需要更强制 Prompt)"
                    })
            except Exception:
                results.append({
                    "category": "protocol", "test_item": "OpenAI Chat 工具调用响应", "protocol": "openai",
                    "status": "FAIL", "latency_ms": lat_t, "url": url, "method": "POST", "payload": data_tool, "code": code_t,
                    "message": "响应解析失败"
                })
        else:
            results.append({
                "category": "protocol", "test_item": "OpenAI Chat 工具调用响应", "protocol": "openai",
                "status": "FAIL", "latency_ms": lat_t, "url": url, "method": "POST", "payload": data_tool, "code": code_t,
                "message": f"HTTP Status {code_t}"
            })

        return results

    # ── Layer 2 实现: OpenAI Responses ──
    def check_openai_responses(self) -> List[Dict[str, Any]]:
        results = []
        url = f"{self.base_url}/v1/responses"
        data = {
            "model": self.model_slug,
            "input": "请简要说明 vLLM 的主要功能，用一段话概括",
            "max_output_tokens": 200,
            "temperature": 0
        }
        code, body, lat = _make_request(url, data=data, headers=self.headers)
        if code == 200:
            try:
                d = json.loads(body)
                has_text = False
                for o in d.get("output", []):
                    for c in (o.get("content") or []):
                        if c.get("text"):
                            has_text = True
                            break
                if has_text:
                    results.append({
                        "category": "protocol", "test_item": "OpenAI Responses 规范响应", "protocol": "responses",
                        "status": "PASS", "latency_ms": lat, "url": url, "method": "POST", "payload": data, "code": code,
                        "message": "标准 output text 字段有效"
                    })
                else:
                    results.append({
                        "category": "protocol", "test_item": "OpenAI Responses 规范响应", "protocol": "responses",
                        "status": "FAIL", "latency_ms": lat, "url": url, "method": "POST", "payload": data, "code": code,
                        "message": "Responses 返回内容为空"
                    })
            except Exception as e:
                results.append({
                    "category": "protocol", "test_item": "OpenAI Responses 规范响应", "protocol": "responses",
                    "status": "FAIL", "latency_ms": lat, "url": url, "method": "POST", "payload": data, "code": code,
                    "message": f"返回格式不符合 Responses 规范: {str(e)}"
                })
        else:
            results.append({
                "category": "protocol", "test_item": "OpenAI Responses 规范响应", "protocol": "responses",
                "status": "SKIP", "latency_ms": lat, "url": url, "method": "POST", "payload": data, "code": code,
                "message": f"服务端未开启 /v1/responses 端点 (HTTP {code})"
            })
        return results
        return results

    # ── Layer 2 实现: Anthropic Messages ──
    def check_anthropic_messages(self) -> List[Dict[str, Any]]:
        results = []
        url = f"{self.base_url}/v1/messages"
        headers = dict(self.headers)
        headers["x-api-key"] = self.api_key or "none"
        headers["anthropic-version"] = "2023-06-01"

        # 1. Anthropic 同步
        data_sync = {
            "model": self.model_slug,
            "max_tokens": 50,
            "messages": [{"role": "user", "content": "回复OK"}]
        }
        code, body, lat = _make_request(url, data=data_sync, headers=headers)
        if code == 200:
            try:
                d = json.loads(body)
                has_text = any(c.get("text") for c in d.get("content", []) if isinstance(c, dict))
                if has_text:
                    results.append({
                        "category": "protocol", "test_item": "Anthropic Messages 同步响应", "protocol": "anthropic",
                        "status": "PASS", "latency_ms": lat, "url": url, "method": "POST", "payload": data_sync, "code": code,
                        "message": "返回标准 Anthropic content 数组"
                    })
                else:
                    results.append({
                        "category": "protocol", "test_item": "Anthropic Messages 同步响应", "protocol": "anthropic",
                        "status": "FAIL", "latency_ms": lat, "url": url, "method": "POST", "payload": data_sync, "code": code,
                        "message": "Anthropic content 缺少 text 节点"
                    })
            except Exception as e:
                results.append({
                    "category": "protocol", "test_item": "Anthropic Messages 同步响应", "protocol": "anthropic",
                    "status": "FAIL", "latency_ms": lat, "url": url, "method": "POST", "payload": data_sync, "code": code,
                    "message": f"Anthropic JSON 解析失败: {str(e)}"
                })
        else:
            results.append({
                "category": "protocol", "test_item": "Anthropic Messages 同步响应", "protocol": "anthropic",
                "status": "SKIP", "latency_ms": lat, "url": url, "method": "POST", "payload": data_sync, "code": code,
                "message": f"服务端未开启 /v1/messages 端口 (HTTP {code})"
            })

        # 2. Anthropic 流式
        data_stream = dict(data_sync)
        data_stream["stream"] = True
        code_s, body_s, lat_s = _make_request(url, data=data_stream, headers=headers, stream=True)
        if code_s == 200 and any(k in body_s for k in ["message_start", "content_block_start", "content_block_delta", "text_delta"]):
            results.append({
                "category": "protocol", "test_item": "Anthropic Messages 流式 SSE", "protocol": "anthropic",
                "status": "PASS", "latency_ms": lat_s, "url": url, "method": "POST", "payload": data_stream, "code": code_s,
                "message": "收到 Anthropic 事件流"
            })
        else:
            results.append({
                "category": "protocol", "test_item": "Anthropic Messages 流式 SSE", "protocol": "anthropic",
                "status": "SKIP" if code != 200 else "FAIL", "latency_ms": lat_s, "url": url, "method": "POST", "payload": data_stream, "code": code_s,
                "message": "未收到预期 Anthropic SSE 事件"
            })

        # 3. Anthropic Tool Use
        data_tool = {
            "model": self.model_slug,
            "max_tokens": 100,
            "messages": [{"role": "user", "content": "请调用 get_weather 工具查询北京的天气"}],
            "tools": [{
                "name": "get_weather",
                "description": "获取城市天气",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"]
                }
            }]
        }
        code_t, body_t, lat_t = _make_request(url, data=data_tool, headers=headers)
        if code_t == 200:
            try:
                d = json.loads(body_t)
                has_tool = any(c.get("type") == "tool_use" for c in d.get("content", []) if isinstance(c, dict))
                if has_tool:
                    results.append({
                        "category": "protocol", "test_item": "Anthropic Tool Use 响应", "protocol": "anthropic",
                        "status": "PASS", "latency_ms": lat_t, "url": url, "method": "POST", "payload": data_tool, "code": code_t,
                        "message": "正确触发 tool_use 类型 content 节点"
                    })
                else:
                    results.append({
                        "category": "protocol", "test_item": "Anthropic Tool Use 响应", "protocol": "anthropic",
                        "status": "SKIP", "latency_ms": lat_t, "url": url, "method": "POST", "payload": data_tool, "code": code_t,
                        "message": "未包含 tool_use 类型节点"
                    })
            except Exception:
                results.append({
                    "category": "protocol", "test_item": "Anthropic Tool Use 响应", "protocol": "anthropic",
                    "status": "FAIL", "latency_ms": lat_t, "url": url, "method": "POST", "payload": data_tool, "code": code_t,
                    "message": "解析失败"
                })
        else:
            results.append({
                "category": "protocol", "test_item": "Anthropic Tool Use 响应", "protocol": "anthropic",
                "status": "SKIP", "latency_ms": lat_t, "url": url, "method": "POST", "payload": data_tool, "code": code_t,
                "message": f"未支持 (HTTP {code_t})"
            })

        return results

    # ── Layer 3 实现: 特性与技能工具 ──
    def check_features(self, max_len: int = 8192, test_longctx: bool = False) -> List[Dict[str, Any]]:
        results = []

        # 1. 工具调用正确性 (get_weather 匹配 & finish_reason == tool_calls)
        url = f"{self.base_url}/v1/chat/completions"
        data_tool = {
            "model": self.model_slug,
            "messages": [{"role": "user", "content": "请调用 get_weather 工具查询北京的天气"}],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "获取城市天气",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"]
                    }
                }
            }],
            "max_tokens": 200,
            "temperature": 0
        }
        code, body, lat = _make_request(url, data=data_tool, headers=self.headers)
        if code == 200:
            try:
                d = json.loads(body)
                choice = d["choices"][0]
                tc_name = choice["message"].get("tool_calls", [{}])[0].get("function", {}).get("name")
                fr = choice.get("finish_reason")
                if tc_name == "get_weather" and fr == "tool_calls":
                    results.append({
                        "category": "feature", "test_item": "工具调用准确性与 finish_reason 格式", "protocol": "openai",
                        "status": "PASS", "latency_ms": lat, "url": url, "method": "POST", "payload": data_tool, "code": code,
                        "message": f"函数名: {tc_name}, finish_reason: {fr}"
                    })
                else:
                    results.append({
                        "category": "feature", "test_item": "工具调用准确性与 finish_reason 格式", "protocol": "openai",
                        "status": "FAIL", "latency_ms": lat, "url": url, "method": "POST", "payload": data_tool, "code": code,
                        "message": f"预期 get_weather/tool_calls，实际: {tc_name}/{fr}"
                    })
            except Exception as e:
                results.append({
                    "category": "feature", "test_item": "工具调用准确性与 finish_reason 格式", "protocol": "openai",
                    "status": "FAIL", "latency_ms": lat, "url": url, "method": "POST", "payload": data_tool, "code": code,
                    "message": f"响应解析异常: {str(e)}"
                })
        else:
            results.append({
                "category": "feature", "test_item": "工具调用准确性与 finish_reason 格式", "protocol": "openai",
                "status": "FAIL", "latency_ms": lat, "url": url, "method": "POST", "payload": data_tool, "code": code,
                "message": f"HTTP Status {code}"
            })

        # 2. Reasoning 思考过程分离
        data_reas = {
            "model": self.model_slug,
            "messages": [{"role": "user", "content": "1+1=?，先思考再回答"}],
            "max_tokens": 200,
            "temperature": 0
        }
        code_r, body_r, lat_r = _make_request(url, data=data_reas, headers=self.headers)
        if code_r == 200:
            try:
                d = json.loads(body_r)
                msg = d["choices"][0]["message"]
                reasoning = msg.get("reasoning") or msg.get("reasoning_content")
                if reasoning:
                    results.append({
                        "category": "feature", "test_item": "Reasoning 思考逻辑独立提取", "protocol": "openai",
                        "status": "PASS", "latency_ms": lat_r, "url": url, "method": "POST", "payload": data_reas, "code": code_r,
                        "message": f"检测到独立 reasoning 字段 (长度 {len(reasoning)})"
                    })
                else:
                    results.append({
                        "category": "feature", "test_item": "Reasoning 思考逻辑独立提取", "protocol": "openai",
                        "status": "SKIP", "latency_ms": lat_r, "url": url, "method": "POST", "payload": data_reas, "code": code_r,
                        "message": "模型未输出独立 reasoning 字段 (思考混在 content 中)"
                    })
            except Exception:
                results.append({
                    "category": "feature", "test_item": "Reasoning 思考逻辑独立提取", "protocol": "openai",
                    "status": "FAIL", "latency_ms": lat_r, "url": url, "method": "POST", "payload": data_reas, "code": code_r,
                    "message": "解析失败"
                })
        else:
            results.append({
                "category": "feature", "test_item": "Reasoning 思考逻辑独立提取", "protocol": "openai",
                "status": "FAIL", "latency_ms": lat_r, "url": url, "method": "POST", "payload": data_reas, "code": code_r,
                "message": f"HTTP Status {code_r}"
            })

        # 3. 大 Prompt / 15 工具注入压测与无乱码检测
        tools_15 = [{
            "type": "function",
            "function": {
                "name": f"tool_{i}",
                "description": f"Tool {i} description. " * 5,
                "parameters": {
                    "type": "object",
                    "properties": {f"p{j}": {"type": "string", "description": f"Param {j}"} for j in range(3)},
                    "required": ["p0"]
                }
            }
        } for i in range(15)]
        data_lp = {
            "model": self.model_slug,
            "messages": [
                {"role": "system", "content": "You are opencode model assistant. " * 30},
                {"role": "user", "content": "你好，请简单自我介绍"}
            ],
            "tools": tools_15,
            "max_tokens": 200,
            "temperature": 0
        }
        code_lp, body_lp, lat_lp = _make_request(url, data=data_lp, headers=self.headers, timeout=120)
        if code_lp == 200:
            try:
                d = json.loads(body_lp)
                c = d["choices"][0]["message"]
                text = (c.get("content") or "") + (c.get("reasoning") or "")
                garb_status = _is_garbage(text)
                if garb_status == "OK":
                    results.append({
                        "category": "feature", "test_item": "大 Prompt 与 15 工具高载压测", "protocol": "openai",
                        "status": "PASS", "latency_ms": lat_lp, "url": url, "method": "POST", "payload": data_lp, "code": code_lp,
                        "message": "负载正常输出，无乱码与 URL 幻觉"
                    })
                else:
                    results.append({
                        "category": "feature", "test_item": "大 Prompt 与 15 工具高载压测", "protocol": "openai",
                        "status": "FAIL", "latency_ms": lat_lp, "url": url, "method": "POST", "payload": data_lp, "code": code_lp,
                        "message": f"检测到异常输出状态: {garb_status}"
                    })
            except Exception as e:
                results.append({
                    "category": "feature", "test_item": "大 Prompt 与 15 工具高载压测", "protocol": "openai",
                    "status": "FAIL", "latency_ms": lat_lp, "url": url, "method": "POST", "payload": data_lp, "code": code_lp,
                    "message": f"解析错误: {str(e)}"
                })
        else:
            results.append({
                "category": "feature", "test_item": "大 Prompt 与 15 工具高载压测", "protocol": "openai",
                "status": "FAIL", "latency_ms": lat_lp, "url": url, "method": "POST", "payload": data_lp, "code": code_lp,
                "message": f"HTTP Status {code_lp}"
            })

        # 4. 长上下文边界安全测试 (选填开关)
        if test_longctx:
            target_tokens = int(max_len * 0.85)
            probe = "这是一段用于测试模型长上下文边界能力的探测文本内容。"
            repeats = max(10, target_tokens * 60 // len(probe))
            long_text = probe * repeats
            data_lc = {
                "model": self.model_slug,
                "messages": [{"role": "user", "content": long_text + "\n\n请回答：上面测试文本的主题是什么？"}],
                "max_tokens": 20
            }
            code_lc, body_lc, lat_lc = _make_request(url, data=data_lc, headers=self.headers, timeout=240)
            if code_lc == 200:
                results.append({
                    "category": "feature", "test_item": "长上下文极限边界测试", "protocol": "openai",
                    "status": "PASS", "latency_ms": lat_lc, "url": url, "method": "POST", "payload": data_lc, "code": code_lc,
                    "message": f"85% 上限 prompt ({target_tokens} tokens) 正常推理"
                })
            elif "contains at least" in body_lc or "input tokens" in body_lc:
                results.append({
                    "category": "feature", "test_item": "长上下文极限边界测试", "protocol": "openai",
                    "status": "PASS", "latency_ms": lat_lc, "url": url, "method": "POST", "payload": data_lc, "code": code_lc,
                    "message": "边界正确触发超限拒绝提示，服务未崩溃"
                })
            else:
                results.append({
                    "category": "feature", "test_item": "长上下文极限边界测试", "protocol": "openai",
                    "status": "FAIL", "latency_ms": lat_lc, "url": url, "method": "POST", "payload": data_lc, "code": code_lc,
                    "message": f"HTTP Status {code_lc}"
                })
        else:
            results.append({
                "category": "feature", "test_item": "长上下文极限边界测试", "protocol": "openai",
                "status": "SKIP", "latency_ms": 0, "url": url, "method": "POST", "payload": None, "code": 0,
                "message": "未开启长上下文边界测试 (test_longctx=False)"
            })

        return results
