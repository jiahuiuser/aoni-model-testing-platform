"""
大模型测试平台 — 功能测试: 多模态图片输入测试

移植自 aoni-model-deploy/benchmarks/bench_glm53_mm.py
生成合成 PNG 通过 chat completions 发给模型, 验证图片输入能力并测量
TTFT(含图片编码)/TPOT/吞吐/image_tokens。仅适用于 VL (多模态) 模型。
"""
import base64
import io
import json
import statistics
import time
import urllib.request

from backend.services.features._common import chat_url

DEFAULT_SCENARIOS = [
    {"label": "s1", "n_images": 1, "img_size": 448, "conc": 1, "out_len": 512},
    {"label": "s2", "n_images": 1, "img_size": 448, "conc": 4, "out_len": 512},
    {"label": "s3", "n_images": 2, "img_size": 448, "conc": 2, "out_len": 512},
]


def _make_image_b64(size=448, color=(255, 0, 0)):
    from PIL import Image
    img = Image.new("RGB", (size, size), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _run_one(base, model, n_images, img_size, out_len, sid, timeout, thinking_off, api_key):
    url = chat_url(base)
    imgs = [_make_image_b64(img_size, color=((i * 80) % 255, (i * 60) % 255, (i * 40) % 255)) for i, _ in enumerate(range(n_images))]
    content = [{"type": "text", "text": f"Describe what you see in {'this image' if n_images == 1 else f'these {n_images} images'}. Be concise."}]
    for b64 in imgs:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": out_len,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if thinking_off:
        body["enable_thinking"] = False
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    t_start = time.time()
    ttft = None
    out_tokens = 0
    image_tokens = 0
    last = None
    itls = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            buf = ""
            for raw in resp:
                buf += raw.decode("utf-8", errors="replace")
                while "\n" in buf:
                    part, buf = buf.split("\n", 1)
                    part = part.strip()
                    if not part.startswith("data: ") or part[6:] == "[DONE]":
                        continue
                    try:
                        ch = json.loads(part[6:])
                    except Exception:
                        continue
                    usage = ch.get("usage")
                    if usage:
                        if usage.get("completion_tokens"):
                            out_tokens = usage["completion_tokens"]
                        ptd = usage.get("prompt_tokens_details")
                        if ptd and ptd.get("image_tokens"):
                            image_tokens = ptd["image_tokens"]
                    chs = ch.get("choices", [])
                    if not chs:
                        continue
                    d = chs[0].get("delta", {})
                    c = d.get("content", "")
                    if c:
                        now = time.time()
                        if ttft is None:
                            ttft = now - t_start
                        elif last is not None:
                            itls.append((now - last) * 1000)
                        last = now
                        out_tokens += 1
        t_end = time.time()
    except Exception as e:
        return {"id": sid, "ok": False, "error": str(e)[:200]}
    dt = t_end - t_start
    tpot = ((dt - ttft) / max(out_tokens - 1, 1) * 1000) if out_tokens > 1 and ttft else 0
    return {
        "id": sid, "ok": True, "ttft_s": round(ttft, 3) if ttft else None,
        "latency_s": round(dt, 3), "out_tokens": out_tokens,
        "image_tokens": image_tokens,
        "tpot_ms": round(tpot, 2), "tok_per_s": round(out_tokens / dt, 2) if dt > 0 else 0,
        "itl_med_ms": round(statistics.median(itls), 2) if itls else 0,
    }


def run(base_url, model, api_key="", options=None, log_callback=None):
    """执行多模态图片测试，返回统一 FeatureResult dict"""
    import concurrent.futures

    options = options or {}
    scenarios = options.get("scenarios") or DEFAULT_SCENARIOS
    thinking_off = bool(options.get("thinking_off", True))
    timeout = int(options.get("timeout", 300))

    def log(msg):
        if log_callback:
            log_callback("INFO", "", f"  {msg}", "feature")

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        return {
            "category": "vision",
            "feature_key": "multimodal",
            "test_item": "多模态图片输入测试",
            "status": "SKIP",
            "latency_ms": None,
            "message": "本机未安装 Pillow (pip install Pillow)，无法生成测试图片",
            "raw_details": {},
        }

    results = []
    for sc in scenarios:
        label = sc["label"]
        conc = sc["conc"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as ex:
            futs = [ex.submit(_run_one, base_url, model, sc["n_images"], sc["img_size"],
                              sc["out_len"], i, timeout, thinking_off, api_key)
                    for i in range(conc)]
            rows = [f.result() for f in futs]
        ok = [x for x in rows if x["ok"]]
        errs = [x for x in rows if not x["ok"]]
        ttfts = sorted([x["ttft_s"] for x in ok if x.get("ttft_s") is not None])
        tpots = sorted([x["tpot_ms"] for x in ok if x.get("tpot_ms")])
        img_toks = [x["image_tokens"] for x in ok if x.get("image_tokens")]
        res = {
            "label": label, "conc": conc, "n_images": sc["n_images"], "img_size": sc["img_size"],
            "ok": len(ok), "err": len(errs),
            "ttft_avg_s": round(statistics.mean(ttfts), 3) if ttfts else None,
            "tpot_avg_ms": round(statistics.mean(tpots), 2) if tpots else None,
            "image_tokens_avg": round(statistics.mean(img_toks), 1) if img_toks else 0,
            "errors": [e["error"][:100] for e in errs[:2]],
        }
        results.append(res)
        log(f"[multimodal] {label}: ok={res['ok']}/{conc} "
            f"ttft_avg={res['ttft_avg_s']}s img_tok={res['image_tokens_avg']}")

    total_ok = sum(r["ok"] for r in results)
    total_req = sum(r["ok"] + r["err"] for r in results)
    status = "PASS" if (total_req > 0 and total_ok == total_req) else ("FAIL" if total_req else "SKIP")
    message = f"图片请求成功 {total_ok}/{total_req}"
    return {
        "category": "vision",
        "feature_key": "multimodal",
        "test_item": "多模态图片输入测试",
        "status": status,
        "latency_ms": None,
        "message": message,
        "raw_details": {"total_ok": total_ok, "total_req": total_req, "results": results},
    }
