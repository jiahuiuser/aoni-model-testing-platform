"""
性能测试运行器

基于 vLLM benchmark 工具，按照 benchmark_strategies.csv 中定义的矩阵策略，
对每个 PASS 模型执行多并发、长短输出的性能扫描测试。
"""
import os
import re
import sys
import json
import time
import socket
import shutil
import logging
import subprocess
import threading
from pathlib import Path
from datetime import datetime

from .strategy import BenchmarkStrategy, read_strategies, filter_strategies_by_model

log = logging.getLogger(__name__)

CONTAINER_NAME = "benchmark_perf_runner"
VLLM_STARTUP_TIMEOUT = 7200
PERF_LOG_DIR_NAME = "perf"


# ---------- 容器管理 (复用现有 test_runner 逻辑) ----------

def _keep_sudo_alive():
    while True:
        subprocess.run(["sudo", "-v"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(60)


def _verify_sudo():
    try:
        subprocess.run(["sudo", "-v"], check=True)
    except subprocess.CalledProcessError:
        print("[ERROR] sudo 凭证验证失败，请先取得 sudo 授权。")
        sys.exit(1)
    t = threading.Thread(target=_keep_sudo_alive, daemon=True)
    t.start()


def _extract_model_name(cmd: str) -> str | None:
    m = re.search(r"-e MODEL_NAME=([^ \n\\]+)", cmd)
    return m.group(1).strip() if m else None


def _extract_port(cmd: str) -> int:
    m = re.search(r"--port\s+(\d+)", cmd)
    return int(m.group(1)) if m else 8000


def _stop_existing_container():
    check_running = subprocess.run(
        ["sudo", "docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME],
        capture_output=True, text=True, timeout=10
    )
    if check_running.stdout.strip() == "true":
        subprocess.run(["sudo", "docker", "stop", "-t", "15", CONTAINER_NAME], capture_output=True, timeout=35)
        time.sleep(2)
    check_exists = subprocess.run(
        ["sudo", "docker", "inspect", CONTAINER_NAME], capture_output=True, timeout=10
    )
    if check_exists.returncode == 0:
        subprocess.run(["sudo", "docker", "rm", "-f", CONTAINER_NAME], capture_output=True, timeout=10)
        time.sleep(1)


def _build_docker_cmd(original_cmd: str) -> str:
    cmd = original_cmd.strip()
    cmd = cmd.replace("&quot;", '"').replace("&amp;", "&")
    cmd = re.sub(r"(sudo\s+)?docker\s+run\b", "sudo docker run", cmd)
    cmd = re.sub(r"(?<= )--rm(?=\s|$|\\)", "", cmd)
    cmd = re.sub(r"(?<= )-it(?=\s|$|\\)", "", cmd)
    cmd = re.sub(r"\s+-d\b", "", cmd)
    cmd = re.sub(r"\s+--restart\s+\S+", "", cmd)
    cmd = re.sub(r"\s+--name\s+\S+", "", cmd)
    cmd = re.sub(r"(sudo docker run)\b", f"\\1 -d --name {CONTAINER_NAME}", cmd, count=1)
    if "nightly-aarch64" in cmd:
        cmd = re.sub(r'(aoni/vllm/vllm-openai:nightly-aarch64\s+)vllm\s+serve\s+\S+(?=\s|\\|$)', r'\1', cmd)
    return cmd


def _start_container(original_cmd: str, log_file: Path) -> bool:
    docker_cmd = _build_docker_cmd(original_cmd)
    with open(log_file, "a") as lf:
        lf.write(f"=== docker cmd ===\n{docker_cmd}\n")
    try:
        res = subprocess.run(docker_cmd, shell=True, capture_output=True, text=True, timeout=1800)
        with open(log_file, "a") as lf:
            lf.write(f"=== docker run stdout ===\n{res.stdout}\n")
            lf.write(f"=== docker run stderr ===\n{res.stderr}\n")
        if res.returncode != 0:
            log.error(f"容器创建失败 (rc={res.returncode}): {res.stderr[:200]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        log.error("容器命令执行超时")
        return False


def _wait_for_vllm(log_file: Path, port: int) -> bool:
    import requests
    url = f"http://127.0.0.1:{port}/v1/models"
    deadline = time.time() + VLLM_STARTUP_TIMEOUT
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                elapsed = int(time.time() - (deadline - VLLM_STARTUP_TIMEOUT))
                log.info(f"vLLM 服务就绪 (用时 {elapsed}s)")
                return True
        except Exception:
            pass
        if attempt % 3 == 0:
            check = subprocess.run(
                ["sudo", "docker", "inspect", "-f", "{{.State.Status}}", CONTAINER_NAME],
                capture_output=True, text=True
            )
            status = check.stdout.strip()
            if status not in ("running", "created"):
                log.error(f"容器异常退出 (status={status})")
                return False
            elapsed = int(time.time() - (deadline - VLLM_STARTUP_TIMEOUT))
            log.info(f"[{elapsed}s] 等待中... 容器状态: {status}")
        time.sleep(10)
    log.error("vLLM 启动超时")
    return False


# ---------- vLLM Benchmark 执行 ----------

def _run_benchmark_via_api(
    port: int,
    concurrency: int,
    input_len: int,
    output_len: int,
    num_prompts: int,
    model_name: str,
    result_dir: Path,
) -> dict:
    """通过 OpenAI API 进行 HTTP 并发压测 (fallback，适用于 llama.cpp 等无 vllm bench 的推理引擎)"""
    import requests
    from concurrent.futures import ThreadPoolExecutor, as_completed

    url = f"http://127.0.0.1:{port}/v1/chat/completions"

    # 生成随机输入（模拟 vllm bench 的 random dataset）
    prompt_text = "hello " * (input_len // 2)  # 近似 input_len tokens

    ttft_list = []
    tpot_list = []
    latencies = []
    total_output_tokens = 0

    def send_request():
        t_start = time.time()
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt_text[:4096]}],
            "max_tokens": output_len,
            "temperature": 0,
            "stream": True,
        }
        try:
            r = requests.post(url, json=payload, timeout=600, stream=True)
            first_token_ts = None
            token_count = 0
            last_ts = t_start
            for line in r.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    if first_token_ts is None:
                        first_token_ts = time.time()
                    token_count += 1
                    last_ts = time.time()
            total_time = time.time() - t_start
            ttft = (first_token_ts - t_start) if first_token_ts else total_time
            tpot = ((last_ts - first_token_ts) / token_count) if first_token_ts and token_count > 0 else 0

            return {
                "ttft": ttft,
                "tpot": tpot,
                "latency": total_time,
                "output_tokens": token_count,
                "success": token_count > 0,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    log.info(f"HTTP API 压测: concurrency={concurrency}, prompts={num_prompts}")
    results = []
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=min(concurrency * 2, 64)) as executor:
        futures = [executor.submit(send_request) for _ in range(num_prompts)]
        for f in as_completed(futures):
            results.append(f.result())

    total_time = time.time() - t_start

    successes = [r for r in results if r.get("success")]
    if not successes:
        return {"concurrency": concurrency, "error": "all_requests_failed", "returncode": -1}

    ttft_values = sorted([r["ttft"] for r in successes])
    tpot_values = sorted([r["tpot"] for r in successes])
    total_output_tokens = sum(r.get("output_tokens", 0) for r in successes)

    def percentile(data, p):
        idx = int(len(data) * p / 100)
        return data[min(idx, len(data) - 1)]

    metrics = {
        "concurrency": concurrency,
        "input_len": input_len,
        "output_len": output_len,
        "request_throughput": len(results) / total_time,
        "output_throughput": total_output_tokens / total_time,
        "total_input_throughput": (len(results) * input_len + total_output_tokens) / total_time,
        "mean_ttft_ms": sum(ttft_values) / len(ttft_values) * 1000,
        "median_ttft_ms": percentile(ttft_values, 50) * 1000,
        "p99_ttft_ms": percentile(ttft_values, 99) * 1000,
        "mean_tpot_ms": sum(tpot_values) / len(tpot_values) * 1000,
        "median_tpot_ms": percentile(tpot_values, 50) * 1000,
        "p99_tpot_ms": percentile(tpot_values, 99) * 1000,
        "mean_itl_ms": sum(tpot_values) / len(tpot_values) * 1000,
        "median_itl_ms": percentile(tpot_values, 50) * 1000,
        "p99_itl_ms": percentile(tpot_values, 99) * 1000,
        "returncode": 0,
    }

    # 记录结果
    log_file = result_dir / f"bench_c{concurrency}.log"
    with open(log_file, "w") as f:
        f.write(f"=== HTTP API benchmark ===\n")
        f.write(f"total_time={total_time:.2f}s, success={len(successes)}/{len(results)}\n")
        json.dump(metrics, f, indent=2, default=str)

    return metrics


def _run_benchmark_serve(
    port: int,
    concurrency: int,
    input_len: int,
    output_len: int,
    num_prompts: int,
    model_name: str,
    result_dir: Path,
    use_api_fallback: bool = False,
) -> dict | None:
    """调用 vllm bench serve 执行单次性能基准测试，不可用时自动 fallback 到 HTTP API"""

    log.info(f"执行 benchmark: concurrency={concurrency}, input={input_len}, output={output_len}")

    # 先尝试 vllm bench serve (容器内)
    if not use_api_fallback:
        container_result_dir = "/tmp/bench_results"
        cmd = [
            "sudo", "docker", "exec", CONTAINER_NAME,
            "vllm", "bench", "serve",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--dataset-name", "random",
            "--random-input-len", str(input_len),
            "--random-output-len", str(output_len),
            "--num-prompts", str(num_prompts),
            "--max-concurrency", str(concurrency),
            "--request-rate", "inf",
            "--ignore-eos",
            "--save-result",
            "--result-dir", container_result_dir,
            "--metadata", f"model={model_name},concurrency={concurrency},output_type={'short' if output_len <= 128 else 'long'}",
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            stdout = res.stdout
            stderr = res.stderr

            log_file = result_dir / f"bench_c{concurrency}.log"
            with open(log_file, "w") as f:
                f.write(f"=== command ===\n{' '.join(cmd)}\n\n")
                f.write(f"=== stdout ===\n{stdout}\n")
                f.write(f"=== stderr ===\n{stderr}\n")
                f.write(f"=== returncode ===\n{res.returncode}\n")

            # 如果容器内没有 vllm 命令，fallback 到 HTTP API
            if res.returncode != 0 and ("No such file" in stderr or "executable file not found" in stderr or "not found" in stderr.lower()):
                log.warning(f"容器内无 vllm bench 命令，切换到 HTTP API 模式")
                return _run_benchmark_via_api(port, concurrency, input_len, output_len, num_prompts, model_name, result_dir)

            metrics = _parse_benchmark_output(stdout)
            metrics["concurrency"] = concurrency
            metrics["input_len"] = input_len
            metrics["output_len"] = output_len
            metrics["returncode"] = res.returncode
            return metrics

        except subprocess.TimeoutExpired:
            log.error(f"benchmark 超时 (concurrency={concurrency})")
            return {"concurrency": concurrency, "error": "timeout", "returncode": -1}
        except Exception as e:
            log.warning(f"vllm bench 异常，fallback 到 HTTP API: {e}")
            return _run_benchmark_via_api(port, concurrency, input_len, output_len, num_prompts, model_name, result_dir)

    # 直接使用 HTTP API fallback
    return _run_benchmark_via_api(port, concurrency, input_len, output_len, num_prompts, model_name, result_dir)


def _parse_benchmark_output(stdout: str) -> dict:
    """从 vllm bench serve 输出中提取关键性能指标"""
    metrics = {}

    patterns = {
        "request_throughput": r"Request throughput.*?:\s*([\d.]+)\s*requests/s",
        "output_throughput": r"Output token throughput.*?:\s*([\d.]+)\s*tokens/s",
        "total_input_throughput": r"Total token throughput.*?:\s*([\d.]+)\s*tokens/s",
        "mean_ttft_ms": r"Mean TTFT.*?:\s*([\d.]+)\s*ms",
        "median_ttft_ms": r"Median TTFT.*?:\s*([\d.]+)\s*ms",
        "p99_ttft_ms": r"P99 TTFT.*?:\s*([\d.]+)\s*ms",
        "mean_tpot_ms": r"Mean TPOT.*?:\s*([\d.]+)\s*ms",
        "median_tpot_ms": r"Median TPOT.*?:\s*([\d.]+)\s*ms",
        "p99_tpot_ms": r"P99 TPOT.*?:\s*([\d.]+)\s*ms",
        "mean_itl_ms": r"Mean ITL.*?:\s*([\d.]+)\s*ms",
        "median_itl_ms": r"Median ITL.*?:\s*([\d.]+)\s*ms",
        "p99_itl_ms": r"P99 ITL.*?:\s*([\d.]+)\s*ms",
    }

    for key, pattern in patterns.items():
        m = re.search(pattern, stdout)
        if m:
            try:
                metrics[key] = float(m.group(1))
            except ValueError:
                metrics[key] = m.group(1)

    return metrics


# ---------- 单模型完整性能测试 ----------

def _run_single_model_perf(
    row: dict,
    strategies: list[BenchmarkStrategy],
    log_dir: Path,
    report_dir: Path,
) -> dict:
    """对单模型执行全部策略的性能测试"""
    idx, name, slug, cmd = row["idx"], row["name"], row["slug"], row["cmd"]

    model_strategies = [s for s in strategies if s.model_slug == slug]
    if not model_strategies:
        log.warning(f"模型 {name} 无对应性能测试策略，跳过")
        return {"model_name": name, "model_slug": slug, "status": "no_strategy"}

    log.info(f"\n{'='*60}\n[性能测试] #{idx} {name}\n{'='*60}")

    # 创建模型专用日志和结果目录
    model_log_dir = log_dir / slug
    model_log_dir.mkdir(parents=True, exist_ok=True)
    model_result_dir = report_dir / slug
    model_result_dir.mkdir(parents=True, exist_ok=True)

    log_file = model_log_dir / "perf_test.log"
    with open(log_file, "w") as f:
        f.write(f"=== 性能测试开始: {name} ===\n时间: {datetime.now()}\n\n")

    model_name = _extract_model_name(cmd)
    if not model_name:
        return {"model_name": name, "model_slug": slug, "status": "no_model_name"}

    port = _extract_port(cmd)

    # 启动容器
    _stop_existing_container()
    subprocess.run(["sudo", "sysctl", "-w", "vm.drop_caches=3"], capture_output=True)
    time.sleep(2)

    ok = _start_container(cmd, log_file)
    if not ok:
        _stop_existing_container()
        return {"model_name": name, "model_slug": slug, "status": "container_start_failed"}

    ready = _wait_for_vllm(log_file, port)
    if not ready:
        _stop_existing_container()
        return {"model_name": name, "model_slug": slug, "status": "vllm_startup_timeout"}

    # 执行所有策略
    all_results = []
    for strategy in model_strategies:
        strategy_dir = model_result_dir / strategy.strategy_id
        strategy_dir.mkdir(parents=True, exist_ok=True)

        for concurrency in strategy.concurrency_list:
            log.info(f"  [{strategy.strategy_id}] concurrency={concurrency}, "
                     f"input={strategy.input_len}, output={strategy.output_len}")

            result = _run_benchmark_serve(
                port=port,
                concurrency=concurrency,
                input_len=strategy.input_len,
                output_len=strategy.output_len,
                num_prompts=strategy.num_prompts,
                model_name=model_name,
                result_dir=strategy_dir,
            )
            if result:
                result["strategy_id"] = strategy.strategy_id
                result["output_type"] = strategy.output_type
                all_results.append(result)

    # 保存汇总结果
    summary_file = model_result_dir / "perf_summary.json"
    with open(summary_file, "w") as f:
        json.dump({
            "model_name": name,
            "model_slug": slug,
            "model_idx": idx,
            "test_time": datetime.now().isoformat(),
            "results": all_results,
        }, f, ensure_ascii=False, indent=2)

    # 清理容器
    _stop_existing_container()

    log.info(f"[{name}] 性能测试完成，结果保存至 {summary_file}")
    return {
        "model_name": name,
        "model_slug": slug,
        "status": "completed",
        "num_tests": len(all_results),
        "summary_file": str(summary_file),
    }


# ---------- 批量性能测试入口 ----------

def run_perf_benchmark(
    csv_path: Path,
    strategy_csv: Path,
    log_dir: Path,
    report_dir: Path,
    model_slug: str | None = None,
    resume: bool = False,
):
    """批量性能测试主入口"""
    _verify_sudo()

    log_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    # 读取模型列表和策略
    from src.csv_handler import read_model_csv

    rows, _ = read_model_csv(csv_path)
    strategies = read_strategies(strategy_csv)

    if not strategies:
        log.error("无有效测试策略，退出")
        return

    # 只测试 PASS 模型
    pass_rows = [r for r in rows if r["result"].startswith("PASS")]
    log.info(f"共 {len(pass_rows)} 款 PASS 模型待进行性能测试")

    if model_slug:
        pass_rows = [r for r in pass_rows if r["slug"] == model_slug]
        if not pass_rows:
            log.error(f"未找到 slug={model_slug} 的 PASS 模型")
            return

    _stop_existing_container()

    summary = []
    for row in pass_rows:
        try:
            result = _run_single_model_perf(row, strategies, log_dir, report_dir)
        except KeyboardInterrupt:
            log.warning("用户中断测试")
            _stop_existing_container()
            break
        except Exception as e:
            log.error(f"模型 {row['name']} 性能测试异常: {e}")
            result = {"model_name": row["name"], "model_slug": row["slug"], "status": f"error: {e}"}

        summary.append(result)
        time.sleep(5)

    # 打印汇总
    completed = sum(1 for r in summary if r.get("status") == "completed")
    failed = len(summary) - completed
    log.info(f"\n性能测试汇总: {completed} 完成 / {failed} 失败 / {len(summary)} 合计")

    for r in summary:
        status = r.get("status", "unknown")
        icon = "✓" if status == "completed" else "✗"
        log.info(f"  {icon} {r['model_name']}: {status}")

    return summary
