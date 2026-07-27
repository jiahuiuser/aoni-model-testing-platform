"""
准确率测试运行器

基于 EvalScope + ModelScope 数据集，对每个 PASS 模型执行在线 API 模式准确率评测。
支持 MMLU, C-Eval, GSM8K, ARC-Challenge, HumanEval 等标准评测集。
"""
import os
import re
import sys
import json
import time
import logging
import subprocess
import threading
from pathlib import Path
from datetime import datetime

log = logging.getLogger(__name__)

CONTAINER_NAME = "benchmark_acc_runner"
VLLM_ACC_PORT = 8801
VLLM_STARTUP_TIMEOUT = 7200

# 可用的评测数据集列表
ACCURACY_DATASETS = ["mmlu", "ceval", "gsm8k", "arc", "humaneval"]


# ---------- 容器管理 ----------

def _keep_sudo_alive():
    while True:
        subprocess.run(["sudo", "-v"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(60)


def _verify_sudo():
    try:
        subprocess.run(["sudo", "-v"], check=True)
    except subprocess.CalledProcessError:
        print("[ERROR] sudo 凭证验证失败。")
        sys.exit(1)
    t = threading.Thread(target=_keep_sudo_alive, daemon=True)
    t.start()


def _extract_model_name(cmd: str) -> str | None:
    m = re.search(r"-e MODEL_NAME=([^ \n\\]+)", cmd)
    return m.group(1).strip() if m else None


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


def _build_docker_cmd(original_cmd: str, target_port: int) -> str:
    """构建 Docker 命令，将端口替换为准确率评测专用端口"""
    cmd = original_cmd.strip()
    cmd = cmd.replace("&quot;", '"').replace("&amp;", "&")
    cmd = re.sub(r"(sudo\s+)?docker\s+run\b", "sudo docker run", cmd)
    cmd = re.sub(r"(?<= )--rm(?=\s|$|\\)", "", cmd)
    cmd = re.sub(r"(?<= )-it(?=\s|$|\\)", "", cmd)
    cmd = re.sub(r"\s+-d\b", "", cmd)
    cmd = re.sub(r"\s+--restart\s+\S+", "", cmd)
    cmd = re.sub(r"\s+--name\s+\S+", "", cmd)
    cmd = re.sub(r"(sudo docker run)\b", f"\\1 -d --name {CONTAINER_NAME}", cmd, count=1)

    # 替换端口为目标评测端口
    cmd = re.sub(r"--port\s+\d+", f"--port {target_port}", cmd)

    if "nightly-aarch64" in cmd:
        cmd = re.sub(r'(aoni/vllm/vllm-openai:nightly-aarch64\s+)vllm\s+serve\s+\S+(?=\s|\\|$)', r'\1', cmd)

    return cmd


def _start_container(original_cmd: str, log_file: Path) -> bool:
    docker_cmd = _build_docker_cmd(original_cmd, VLLM_ACC_PORT)
    with open(log_file, "a") as f:
        f.write(f"=== docker cmd ===\n{docker_cmd}\n")
    try:
        res = subprocess.run(docker_cmd, shell=True, capture_output=True, text=True, timeout=1800)
        with open(log_file, "a") as f:
            f.write(f"=== docker run stdout ===\n{res.stdout}\n")
            f.write(f"=== docker run stderr ===\n{res.stderr}\n")
        if res.returncode != 0:
            log.error(f"容器创建失败 (rc={res.returncode}): {res.stderr[:200]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        log.error("容器命令执行超时")
        return False


def _wait_for_vllm(log_file: Path) -> bool:
    import requests
    url = f"http://127.0.0.1:{VLLM_ACC_PORT}/v1/models"
    deadline = time.time() + VLLM_STARTUP_TIMEOUT
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                elapsed = int(time.time() - (deadline - VLLM_STARTUP_TIMEOUT))
                log.info(f"vLLM 评测服务就绪 (用时 {elapsed}s)")
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
    log.error("vLLM 评测服务启动超时")
    return False


# ---------- EvalScope 准确率评测 ----------

def _run_evalscope_eval(
    model_name: str,
    api_url: str,
    datasets: list[str],
    limit: int,
    result_dir: Path,
    log_file: Path,
) -> dict:
    """调用 EvalScope 进行在线 API 准确率评测"""
    datasets_str = " ".join(datasets)
    generation_config = json.dumps({
        "temperature": 0.0,
        "max_tokens": 512,
        "do_sample": False,
    })

    cmd = [
        "evalscope", "eval",
        "--model", model_name,
        "--eval-type", "openai_api",
        "--api-url", api_url,
        "--api-key", "EMPTY",
        "--datasets", datasets_str,
        "--limit", str(limit),
        "--generation-config", generation_config,
        "--work-dir", str(result_dir),
    ]

    log.info(f"执行准确率评测: datasets={datasets}")
    with open(log_file, "a") as f:
        f.write(f"=== evalscope command ===\n{' '.join(cmd)}\n\n")

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=14400)  # 4小时超时
        with open(log_file, "a") as f:
            f.write(f"=== stdout ===\n{res.stdout[-5000:]}\n")
            f.write(f"=== stderr ===\n{res.stderr[-3000:]}\n")
            f.write(f"=== returncode ===\n{res.returncode}\n")

        # 解析评测结果
        metrics = _parse_evalscope_output(res.stdout)
        metrics["returncode"] = res.returncode
        metrics["model_name"] = model_name
        metrics["datasets"] = datasets
        return metrics

    except subprocess.TimeoutExpired:
        log.error("准确率评测超时")
        return {"error": "timeout", "returncode": -1, "model_name": model_name}
    except Exception as e:
        log.error(f"准确率评测异常: {e}")
        return {"error": str(e), "returncode": -1, "model_name": model_name}


def _parse_evalscope_output(stdout: str) -> dict:
    """从 evalscope 输出中提取准确率指标"""
    metrics = {}

    # 匹配各数据集的 accuracy
    dataset_patterns = {
        "mmlu": r"mmlu.*?accuracy.*?([\d.]+)",
        "ceval": r"ceval.*?accuracy.*?([\d.]+)",
        "gsm8k": r"gsm8k.*?accuracy.*?([\d.]+)",
        "arc": r"arc.*?accuracy.*?([\d.]+)",
        "humaneval": r"humaneval.*?pass@1.*?([\d.]+)",
    }

    for ds, pattern in dataset_patterns.items():
        m = re.search(pattern, stdout, re.IGNORECASE)
        if m:
            try:
                metrics[f"{ds}_accuracy"] = float(m.group(1))
            except ValueError:
                metrics[f"{ds}_accuracy"] = m.group(1)

    # 尝试匹配更通用的格式
    # EvalScope 输出格式类似: "accuracy: 0.7234"
    generic_matches = re.findall(r"(\w+).*?accuracy.*?([\d.]+)", stdout, re.IGNORECASE)
    for name, val in generic_matches:
        if name.lower() not in metrics:
            try:
                metrics[f"{name.lower()}_accuracy"] = float(val)
            except ValueError:
                pass

    # 匹配 weighted avg
    wavg = re.search(r"weighted.*?avg.*?([\d.]+)", stdout, re.IGNORECASE)
    if wavg:
        try:
            metrics["weighted_avg"] = float(wavg.group(1))
        except ValueError:
            pass

    return metrics


# ---------- 单模型准确率测试 ----------

def _run_single_model_accuracy(
    row: dict,
    log_dir: Path,
    report_dir: Path,
    datasets: list[str],
    limit: int,
) -> dict:
    """对单模型执行准确率评测"""
    idx, name, slug, cmd = row["idx"], row["name"], row["slug"], row["cmd"]

    log.info(f"\n{'='*60}\n[准确率测试] #{idx} {name}\n{'='*60}")

    model_log_dir = log_dir / slug
    model_log_dir.mkdir(parents=True, exist_ok=True)
    model_result_dir = report_dir / slug
    model_result_dir.mkdir(parents=True, exist_ok=True)

    log_file = model_log_dir / "accuracy_test.log"
    with open(log_file, "w") as f:
        f.write(f"=== 准确率测试开始: {name} ===\n时间: {datetime.now()}\n\n")

    model_name = _extract_model_name(cmd)
    if not model_name:
        return {"model_name": name, "model_slug": slug, "status": "no_model_name"}

    # 启动容器 (使用独立端口避免冲突)
    _stop_existing_container()
    subprocess.run(["sudo", "sysctl", "-w", "vm.drop_caches=3"], capture_output=True)
    time.sleep(2)

    ok = _start_container(cmd, log_file)
    if not ok:
        _stop_existing_container()
        return {"model_name": name, "model_slug": slug, "status": "container_start_failed"}

    ready = _wait_for_vllm(log_file)
    if not ready:
        _stop_existing_container()
        return {"model_name": name, "model_slug": slug, "status": "vllm_startup_timeout"}

    # 执行 evalscope 评测
    api_url = f"http://127.0.0.1:{VLLM_ACC_PORT}/v1"
    metrics = _run_evalscope_eval(
        model_name=model_name,
        api_url=api_url,
        datasets=datasets,
        limit=limit,
        result_dir=model_result_dir,
        log_file=log_file,
    )

    # 保存汇总结果
    summary_file = model_result_dir / "accuracy_summary.json"
    with open(summary_file, "w") as f:
        json.dump({
            "model_name": name,
            "model_slug": slug,
            "model_idx": idx,
            "test_time": datetime.now().isoformat(),
            "metrics": metrics,
        }, f, ensure_ascii=False, indent=2)

    # 清理容器
    _stop_existing_container()

    log.info(f"[{name}] 准确率测试完成 -> {summary_file}")
    return {
        "model_name": name,
        "model_slug": slug,
        "status": "completed" if metrics.get("returncode") == 0 else "eval_error",
        "metrics": metrics,
        "summary_file": str(summary_file),
    }


# ---------- 批量准确率测试入口 ----------

def run_accuracy_benchmark(
    csv_path: Path,
    log_dir: Path,
    report_dir: Path,
    datasets: list[str] | None = None,
    limit: int = 500,
    model_slug: str | None = None,
):
    """批量准确率测试主入口"""
    _verify_sudo()

    if datasets is None:
        datasets = ACCURACY_DATASETS

    log_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    from src.csv_handler import read_model_csv

    rows, _ = read_model_csv(csv_path)
    pass_rows = [r for r in rows if r["result"].startswith("PASS")]
    log.info(f"共 {len(pass_rows)} 款 PASS 模型待进行准确率测试")

    if model_slug:
        pass_rows = [r for r in pass_rows if r["slug"] == model_slug]
        if not pass_rows:
            log.error(f"未找到 slug={model_slug} 的 PASS 模型")
            return

    _stop_existing_container()

    summary = []
    for row in pass_rows:
        try:
            result = _run_single_model_accuracy(row, log_dir, report_dir, datasets, limit)
        except KeyboardInterrupt:
            log.warning("用户中断测试")
            _stop_existing_container()
            break
        except Exception as e:
            log.error(f"模型 {row['name']} 准确率测试异常: {e}")
            result = {"model_name": row["name"], "model_slug": row["slug"], "status": f"error: {e}"}

        summary.append(result)
        time.sleep(5)

    completed = sum(1 for r in summary if r.get("status") == "completed")
    failed = len(summary) - completed
    log.info(f"\n准确率测试汇总: {completed} 完成 / {failed} 失败 / {len(summary)} 合计")

    for r in summary:
        status = r.get("status", "unknown")
        icon = "✓" if status == "completed" else "✗"
        m = r.get("metrics", {})
        acc_info = ""
        if m:
            for k, v in m.items():
                if k.endswith("_accuracy") and isinstance(v, (int, float)):
                    acc_info += f" {k}={v:.2%}"
        log.info(f"  {icon} {r['model_name']}: {status}{acc_info}")

    return summary
