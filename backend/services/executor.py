"""
执行器 — 支持本地和远程 SSH 执行
"""
import re
import json
import time
import logging
import subprocess
import threading
import sys
from pathlib import Path
from datetime import datetime
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.models import ModelRun, PerfResult, AccResult, ModelStage, StageStatus, Device
from backend.config import REPORTS_DIR, LOGS_DIR, DATA_DIR
from backend.services.pipeline import get_concurrency_for_category

log = logging.getLogger(__name__)
CONTAINER_NAME = "aoni_benchmark_runner"


# ============================================================
#  RemoteRunner — 封装本地/SSH 命令执行
# ============================================================

class RemoteRunner:
    """根据设备配置自动选择本地执行或 SSH 远程执行"""

    def __init__(self, device: Device | None):
        self.device = device
        self._ssh_info = None
        if device and device.credential:
            c = device.credential
            self._ssh_info = {
                "host": device.host,
                "username": c.ssh_username,
                "ssh_port": c.ssh_port or 22,
                "type": c.type,
                "key_path": c.ssh_key_path,
                "password": c.password,
            }
        self.is_remote = self._ssh_info is not None

    @property
    def api_host(self) -> str:
        if self.is_remote:
            return self.device.host
        return "127.0.0.1"

    @property
    def host_label(self) -> str:
        if self.is_remote:
            return f"{self.device.name}({self.device.host})"
        return "本机"

    def run(self, cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
        if self.is_remote:
            return _ssh_exec(self._ssh_info, cmd, timeout)
        else:
            return _local_exec(cmd, timeout)

    def run_shell(self, cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
        if self.is_remote:
            return _ssh_exec_shell(self._ssh_info, cmd, timeout)
        else:
            return _local_exec_shell(cmd, timeout)

    def run_docker(self, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
        return self.run(["sudo", "docker"] + args, timeout)


# ---------- 底层执行函数 ----------

def _local_exec(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, -1, stdout="", stderr="timeout")
    except Exception as e:
        return subprocess.CompletedProcess(cmd, -1, stdout="", stderr=str(e))


def _local_exec_shell(cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, -1, stdout="", stderr="timeout")
    except Exception as e:
        return subprocess.CompletedProcess(cmd, -1, stdout="", stderr=str(e))


def _ssh_exec(ssh_info: dict, cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """通过 SSH 在远程设备执行命令，支持密钥和密码两种方式"""
    if ssh_info["type"] == "ssh_key":
        ssh_args = [
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            "-i", ssh_info["key_path"],
            "-p", str(ssh_info["ssh_port"]),
            f"{ssh_info['username']}@{ssh_info['host']}",
        ]
    else:
        ssh_args = [
            "sshpass", "-p", ssh_info["password"],
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            "-p", str(ssh_info["ssh_port"]),
            f"{ssh_info['username']}@{ssh_info['host']}",
        ]
    quoted = " ".join(_quote_arg(a) for a in cmd)
    full_cmd = ssh_args + [quoted]
    try:
        return subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(full_cmd, -1, stdout="", stderr="timeout")
    except Exception as e:
        return subprocess.CompletedProcess(full_cmd, -1, stdout="", stderr=str(e))


def _ssh_exec_shell(ssh_info: dict, cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return _ssh_exec(ssh_info, ["bash", "-c", cmd], timeout)


def _quote_arg(arg: str) -> str:
    """安全引用 shell 参数"""
    if not arg:
        return "''"
    # 如果包含特殊字符，用单引号包裹
    if re.search(r'[^\w@%+=:,./-]', arg):
        escaped = arg.replace("'", "'\\''")
        return f"'{escaped}'"
    return arg


# ============================================================
#  容器管理
# ============================================================

def _stop_container(runner: RemoteRunner):
    """停止并删除旧容器"""
    # 先检查容器是否存在
    inspect = runner.run_docker(["inspect", CONTAINER_NAME], timeout=5)
    if inspect.returncode != 0:
        return  # 容器不存在

    runner.run_docker(["stop", "-t", "15", CONTAINER_NAME], timeout=30)
    runner.run_docker(["rm", "-f", CONTAINER_NAME], timeout=10)


def _start_container(runner: RemoteRunner, docker_cmd: str, port: int, log_callback) -> tuple[bool, str]:
    """启动容器并返回 (成功, container_id)"""
    cmd = docker_cmd.strip()
    cmd = cmd.replace("&quot;", '"').replace("&amp;", "&")
    cmd = re.sub(r"(sudo\s+)?docker\s+run\b", "sudo docker run", cmd)
    cmd = re.sub(r"(?<= )--rm(?=\s|$|\\)", "", cmd)
    cmd = re.sub(r"(?<= )-it(?=\s|$|\\)", "", cmd)
    cmd = re.sub(r"\s+-d\b", "", cmd)
    cmd = re.sub(r"\s+--restart\s+\S+", "", cmd)
    cmd = re.sub(r"\s+--name\s+\S+", "", cmd)
    cmd = re.sub(r"(sudo docker run)\b", f"\\1 -d --name {CONTAINER_NAME}", cmd, count=1)
    cmd = re.sub(r"--port\s+\d+", f"--port {port}", cmd)
    # 小模型降低 GPU 内存占用
    cmd = re.sub(r"--gpu-memory-utilization\s+[\d.]+", "--gpu-memory-utilization 0.25", cmd)
    if "nightly-aarch64" in cmd:
        cmd = re.sub(r'(aoni/vllm/vllm-openai:nightly-aarch64\s+)vllm\s+serve\s+\S+(?=\s|\\|$)', r'\1', cmd)

    short_cmd = cmd[:300] + "..." if len(cmd) > 300 else cmd
    log_callback("INFO", "", f"  [{runner.host_label}] docker run 命令: {short_cmd}", "container")

    try:
        res = runner.run_shell(cmd, timeout=1800)
        cid = res.stdout.strip()
        if res.returncode == 0:
            log_callback("INFO", "", f"  容器启动成功, ID: {cid[:12]}", "container")
            # 抓取初始日志
            time.sleep(3)
            init_logs = runner.run_docker(["logs", "--tail", "5", CONTAINER_NAME], timeout=10)
            for line in init_logs.stdout.strip().split("\n")[:5]:
                if line.strip():
                    log_callback("INFO", "", f"  [容器] {line.strip()[:200]}", "container")
            return True, cid
        else:
            log_callback("ERROR", "", f"  容器启动失败 rc={res.returncode}: {res.stderr[:300]}", "container")
            return False, ""
    except Exception as e:
        log_callback("ERROR", "", f"  容器命令异常: {e}", "container")
        return False, ""


def _wait_for_vllm(runner: RemoteRunner, port: int, timeout: int = 7200, log_callback=None) -> bool:
    """轮询等待 vLLM 服务就绪"""
    import requests
    url = f"http://{runner.api_host}:{port}/v1/models"
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                elapsed = int(time.time() - (deadline - timeout))
                if log_callback:
                    log_callback("INFO", "", f"  vLLM 服务就绪 (用时 {elapsed}s)", "vllm")
                return True
        except Exception:
            pass

        # 每 30 秒输出容器状态
        if attempt % 3 == 0 and log_callback:
            try:
                check = runner.run_docker(
                    ["inspect", "-f", "{{.State.Status}}", CONTAINER_NAME], timeout=5)
                status = check.stdout.strip()
                elapsed = int(time.time() - (deadline - timeout))
                if status not in ("running", "created"):
                    log_callback("ERROR", "", f"  容器异常退出 (状态: {status})", "vllm")
                    logs = runner.run_docker(["logs", "--tail", "10", CONTAINER_NAME], timeout=10)
                    for line in (logs.stdout + logs.stderr).strip().split("\n")[-5:]:
                        if line.strip():
                            log_callback("ERROR", "", f"  [容器最后日志] {line.strip()[:200]}", "vllm")
                    return False
                log_callback("INFO", "", f"  [{elapsed}s] 等待中... 容器状态: {status}", "vllm")
                logs = runner.run_docker(["logs", "--tail", "3", CONTAINER_NAME], timeout=10)
                for line in (logs.stdout + logs.stderr).strip().split("\n")[-3:]:
                    if line.strip():
                        log_callback("INFO", "", f"  [容器] {line.strip()[:200]}", "vllm")
            except Exception:
                pass
        time.sleep(10)

    if log_callback:
        log_callback("ERROR", "", "vLLM 启动超时，打印最后日志:", "vllm")
        try:
            logs = runner.run_docker(["logs", "--tail", "20", CONTAINER_NAME], timeout=10)
            for line in (logs.stdout + logs.stderr).strip().split("\n")[-10:]:
                if line.strip():
                    log_callback("ERROR", "", f"  [容器] {line.strip()[:200]}", "vllm")
        except Exception:
            pass
    return False


# ============================================================
#  主流水线
# ============================================================

def run_model_pipeline(db: Session, task_id: int, model_run: ModelRun, config: dict, log_callback):
    """执行单个模型的完整测试流水线"""
    # 获取设备
    task = model_run.task
    device = task.device if task else None
    runner = RemoteRunner(device)

    model_slug = model_run.model_slug
    port = config.get("container_port", 8300)
    docker_cmd = config.get("docker_command") or model_run.docker_command

    # Stage 1: 部署容器
    log_callback("INFO", model_slug, f"========== 容器部署 [{runner.host_label}] ==========", "container")
    log_callback("INFO", model_slug, "正在清理旧容器...", "container")
    _stop_container(runner)
    log_callback("INFO", model_slug, "释放系统缓存...", "container")
    try:
        runner.run_shell("sudo sysctl -w vm.drop_caches=3", timeout=5)
    except Exception:
        pass
    time.sleep(2)

    ok, container_id = _start_container(runner, docker_cmd, port, log_callback)
    if not ok:
        log_callback("ERROR", model_slug, "容器启动失败，测试终止", "container")
        model_run.stage_status["deploying"] = StageStatus.FAILED.value
        model_run.status = ModelStage.DONE
        model_run.completed_at = datetime.utcnow()
        db.commit()
        return

    model_run.container_name = container_id[:12] if container_id else ""
    model_run.stage_status["deploying"] = StageStatus.COMPLETED.value
    model_run.status = ModelStage.VALIDATING
    model_run.progress = 10
    db.commit()

    # Stage 2: 等待 vLLM
    log_callback("INFO", model_slug, "========== vLLM 服务启动 ==========", "vllm")
    log_callback("INFO", model_slug, f"轮询 {runner.api_host}:{port} 等待推理服务就绪...", "vllm")
    if not _wait_for_vllm(runner, port, config.get("container_startup_timeout", 7200), log_callback):
        log_callback("ERROR", model_slug, "vLLM 启动超时，测试终止", "vllm")
        model_run.stage_status["validating"] = StageStatus.FAILED.value
        model_run.status = ModelStage.DONE
        model_run.completed_at = datetime.utcnow()
        db.commit()
        _stop_container(runner)
        return

    # 验证模型列表
    try:
        import requests
        r = requests.get(f"http://{runner.api_host}:{port}/v1/models", timeout=5)
        if r.status_code == 200:
            models_data = r.json().get("data", [])
            for m in models_data[:3]:
                log_callback("INFO", model_slug, f"  可用模型: {m.get('id', '?')}", "vllm")
    except Exception:
        pass

    model_run.stage_status["validating"] = StageStatus.COMPLETED.value
    model_run.progress = 20
    db.commit()

    # Stage 3: 性能测试
    if config.get("perf_enabled", True):
        model_run.status = ModelStage.PERF_TESTING
        model_run.stage_status["perf_testing"] = StageStatus.RUNNING.value
        db.commit()
        log_callback("INFO", model_slug, "========== 性能测试 ==========", "perf")
        _run_perf_stage(db, model_run, config, log_callback, runner)
        model_run.stage_status["perf_testing"] = StageStatus.COMPLETED.value
        model_run.progress = 60
        db.commit()

    # Stage 4: 准确率测试
    if config.get("acc_enabled", True):
        model_run.status = ModelStage.ACC_TESTING
        model_run.stage_status["acc_testing"] = StageStatus.RUNNING.value
        db.commit()
        log_callback("INFO", model_slug, "========== 准确率测试 ==========", "accuracy")
        _run_accuracy_stage(db, model_run, config, log_callback, runner)
        model_run.stage_status["acc_testing"] = StageStatus.COMPLETED.value
        model_run.progress = 90
        db.commit()

    # Stage 5: 完成
    model_run.status = ModelStage.DONE
    model_run.progress = 100
    model_run.completed_at = datetime.utcnow()
    db.commit()
    _stop_container(runner)
    log_callback("INFO", model_slug, "========== 测试完成 ==========", "system")


# ============================================================
#  性能测试
# ============================================================

def _run_perf_stage(db: Session, model_run: ModelRun, config: dict, log_callback, runner: RemoteRunner):
    port = config.get("container_port", 8300)
    rounds_config = config.get("perf_rounds_config")
    if not rounds_config:
        rounds_config = [{"input_len": 512, "output_lens_str": "128,512", "concurrencies_str": "", "num_prompts": 300}]

    m = re.search(r"-e MODEL_NAME=([^ \n\\]+)", model_run.docker_command)
    vllm_model_name = m.group(1).strip() if m else model_run.model_name
    use_fallback = not _check_vllm_bench(runner)

    round_num = 0
    for rd in rounds_config:
        round_num += 1
        input_len = int(rd.get("input_len", 512))
        num_prompts = int(rd.get("num_prompts", 300))
        output_lens_str = rd.get("output_lens_str", "128,512")
        concurrencies_str = rd.get("concurrencies_str", "")

        try:
            output_lens = [int(x.strip()) for x in output_lens_str.split(",") if x.strip()]
        except (ValueError, AttributeError):
            output_lens = [128, 512]
        if not output_lens:
            output_lens = [128, 512]

        if concurrencies_str:
            try:
                concurrencies = [int(x.strip()) for x in concurrencies_str.split(",") if x.strip()]
            except ValueError:
                concurrencies = get_concurrency_for_category(model_run.size_category or "small_medium")
        else:
            concurrencies = get_concurrency_for_category(model_run.size_category or "small_medium")

        log_callback("INFO", model_run.model_slug,
                     f"第 {round_num} 轮: input={input_len}, output={output_lens}, concurrency={concurrencies}", "perf")
        log_callback("INFO", model_run.model_slug,
                     f"  每轮请求数: {num_prompts}, 方法: {'vLLM bench' if not use_fallback else 'HTTP API'}", "perf")

        for output_len in output_lens:
            output_type = "short" if output_len <= 128 else "long"
            strategy_id = f"{model_run.model_slug}_round{round_num}_{output_type}"

            for concurrency in concurrencies:
                log_callback("INFO", model_run.model_slug,
                             f"  性能测试: c={concurrency}, output={output_len}, round={round_num}", "perf")

                if use_fallback:
                    log_callback("INFO", model_run.model_slug,
                                 f"  使用 HTTP API 压测, URL: http://{runner.api_host}:{port}/v1/chat/completions", "perf")
                    result = _run_http_benchmark(runner, port, concurrency, input_len, output_len, num_prompts, vllm_model_name)
                else:
                    result = _run_vllm_bench_single(runner, port, concurrency, input_len, output_len, num_prompts, vllm_model_name, log_callback)

                if result:
                    err = result.get("error")
                    perf = PerfResult(
                        model_run_id=model_run.id, round_num=round_num,
                        strategy_id=strategy_id, output_type=output_type,
                        concurrency=concurrency, input_len=input_len, output_len=output_len,
                        throughput_tok_s=result.get("output_throughput"),
                        request_throughput=result.get("request_throughput"),
                        mean_ttft_ms=result.get("mean_ttft_ms"),
                        p99_ttft_ms=result.get("p99_ttft_ms"),
                        mean_tpot_ms=result.get("mean_tpot_ms"),
                        p99_tpot_ms=result.get("p99_tpot_ms"),
                        mean_itl_ms=result.get("mean_itl_ms"),
                        median_ttft_ms=result.get("median_ttft_ms"),
                        median_tpot_ms=result.get("median_tpot_ms"),
                        p99_itl_ms=result.get("p99_itl_ms"),
                        raw_report=result.get("raw_report"),
                        error=err,
                    )
                    db.add(perf)
                    db.commit()
                    if err:
                        log_callback("ERROR", model_run.model_slug,
                                     f"    c={concurrency}, output={output_len}: 失败 - {err}", "perf")
                    else:
                        tps = result.get("output_throughput", 0)
                        ttft = result.get("mean_ttft_ms", 0)
                        tpot = result.get("mean_tpot_ms", 0)
                        p99_ttft = result.get("p99_ttft_ms", 0)
                        tps_str = f"{tps:.1f}" if isinstance(tps, (int, float)) else str(tps)
                        ttft_str = f"{ttft:.1f}" if isinstance(ttft, (int, float)) else str(ttft)
                        tpot_str = f"{tpot:.1f}" if isinstance(tpot, (int, float)) else str(tpot)
                        log_callback("INFO", model_run.model_slug,
                                     f"    结果: 吞吐={tps_str} tok/s, TTFT={ttft_str}ms, TPOT={tpot_str}ms, P99_TTFT={p99_ttft}ms", "perf")
                        raw = result.get("raw_report")
                        if raw and isinstance(raw, dict):
                            completed = raw.get("completed", "?")
                            failed = raw.get("failed", "?")
                            duration = raw.get("duration", 0)
                            log_callback("INFO", model_run.model_slug,
                                         f"    完成={completed}/{completed+failed}, 耗时={duration:.1f}s" if isinstance(duration, float) else f"    完成={completed}/{completed+failed}", "perf")


def _check_vllm_bench(runner: RemoteRunner) -> bool:
    """检查容器内是否有 vllm bench 工具"""
    try:
        res = runner.run_docker(["exec", CONTAINER_NAME, "which", "vllm"], timeout=10)
        return res.returncode == 0
    except Exception:
        return False


def _run_vllm_bench_single(runner: RemoteRunner, port, concurrency, input_len, output_len,
                           num_prompts, model_name, log_callback=None) -> dict | None:
    """调用 vllm bench serve，用 --save-result 生成 JSON 报告后解析"""
    import os as _os

    result_dir = "/tmp/vllm_bench_results"
    cmd = ["sudo", "docker", "exec", CONTAINER_NAME, "vllm", "bench", "serve",
           "--host", "127.0.0.1", "--port", str(port),
           "--dataset-name", "random",
           "--random-input-len", str(input_len),
           "--random-output-len", str(output_len),
           "--num-prompts", str(num_prompts),
           "--max-concurrency", str(concurrency),
           "--request-rate", "inf", "--ignore-eos",
           "--save-result",
           "--result-dir", result_dir]

    if log_callback:
        log_callback("INFO", "", f"  [{runner.host_label}] 执行命令: {' '.join(cmd)}", "perf")

    try:
        res = runner.run(cmd, timeout=1800)

        # 从容器拷贝 JSON 结果文件
        host_dir = "/tmp/vllm_bench_host"
        subprocess.run(["mkdir", "-p", host_dir], capture_output=True)

        # 远程设备：先 docker cp 到设备本地，再 scp 回来
        if runner.is_remote:
            ssh = runner._ssh_info
            runner.run_shell(
                f"sudo docker cp {CONTAINER_NAME}:{result_dir}/. /tmp/vllm_bench_remote/ && "
                f"mkdir -p /tmp/vllm_bench_remote",
                timeout=30)
            if ssh["type"] == "ssh_key":
                subprocess.run([
                    "scp", "-o", "StrictHostKeyChecking=no",
                    "-i", ssh["key_path"],
                    "-P", str(ssh["ssh_port"]),
                    "-r", f"{ssh['username']}@{ssh['host']}:/tmp/vllm_bench_remote/.",
                    host_dir
                ], capture_output=True, timeout=30)
            else:
                subprocess.run([
                    "sshpass", "-p", ssh["password"],
                    "scp", "-o", "StrictHostKeyChecking=no",
                    "-P", str(ssh["ssh_port"]),
                    "-r", f"{ssh['username']}@{ssh['host']}:/tmp/vllm_bench_remote/.",
                    host_dir
                ], capture_output=True, timeout=30)
        else:
            subprocess.run(
                ["sudo", "docker", "cp", f"{CONTAINER_NAME}:{result_dir}/.", host_dir],
                capture_output=True, timeout=30)

        # 查找最新的 JSON 文件
        host_path = Path(host_dir)
        json_files = sorted(host_path.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        raw_report = None
        if json_files:
            try:
                with open(json_files[0]) as f:
                    raw_report = json.load(f)
            except Exception:
                pass

        # 从 JSON 提取关键指标
        metrics = {"concurrency": concurrency}
        if raw_report:
            metrics["raw_report"] = raw_report
            metrics["output_throughput"] = raw_report.get("output_throughput") or raw_report.get("mean_tokens_per_second")
            metrics["request_throughput"] = raw_report.get("request_throughput")
            metrics["mean_ttft_ms"] = raw_report.get("mean_ttft_ms")
            metrics["median_ttft_ms"] = raw_report.get("median_ttft_ms")
            metrics["p99_ttft_ms"] = raw_report.get("p99_ttft_ms") or raw_report.get("ttft_p99")
            metrics["mean_tpot_ms"] = raw_report.get("mean_tpot_ms")
            metrics["median_tpot_ms"] = raw_report.get("median_tpot_ms")
            metrics["p99_tpot_ms"] = raw_report.get("p99_tpot_ms") or raw_report.get("tpot_p99")
            metrics["mean_itl_ms"] = raw_report.get("mean_itl_ms")
            metrics["median_itl_ms"] = raw_report.get("median_itl_ms")
            metrics["p99_itl_ms"] = raw_report.get("p99_itl_ms")

        # 如果 JSON 解析失败，fallback 到正则
        if not metrics.get("output_throughput"):
            regex_metrics = _parse_bench_output(res.stdout)
            metrics.update(regex_metrics)

        metrics["concurrency"] = concurrency
        metrics["input_len"] = input_len
        metrics["output_len"] = output_len
        return metrics

    except subprocess.TimeoutExpired:
        return {"concurrency": concurrency, "error": "timeout", "returncode": -1}
    except Exception as e:
        return {"concurrency": concurrency, "error": str(e)}


def _run_http_benchmark(runner: RemoteRunner, port, concurrency, input_len, output_len,
                        num_prompts, model_name) -> dict | None:
    """HTTP API 压测（fallback）"""
    import requests
    from concurrent.futures import ThreadPoolExecutor, as_completed

    url = f"http://{runner.api_host}:{port}/v1/chat/completions"
    prompt_text = "hello " * min(input_len // 2, 2000)

    def send_request():
        t_start = time.time()
        payload = {"model": model_name, "messages": [{"role": "user", "content": prompt_text}],
                   "max_tokens": output_len, "temperature": 0, "stream": True}
        try:
            r = requests.post(url, json=payload, timeout=600, stream=True)
            first_token_ts = None; token_count = 0; last_ts = t_start
            for line in r.iter_lines():
                if not line: continue
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    if line[6:] in ("[DONE]", ""): break
                    if first_token_ts is None: first_token_ts = time.time()
                    token_count += 1; last_ts = time.time()
            total = time.time() - t_start
            ttft = (first_token_ts - t_start) if first_token_ts else total
            tpot = ((last_ts - first_token_ts) / token_count) if first_token_ts and token_count > 0 else 0
            return {"ttft": ttft, "tpot": tpot, "output_tokens": token_count, "success": token_count > 0}
        except Exception:
            return {"success": False}

    t0 = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=min(concurrency * 2, 64)) as ex:
        futures = [ex.submit(send_request) for _ in range(num_prompts)]
        for f in as_completed(futures):
            results.append(f.result())
    total_time = time.time() - t0

    successes = [r for r in results if r.get("success")]
    if not successes:
        return {"concurrency": concurrency, "error": "all_failed"}

    ttfts = sorted([r["ttft"] for r in successes])
    tpots = sorted([r["tpot"] for r in successes])
    total_out = sum(r.get("output_tokens", 0) for r in successes)

    return {
        "concurrency": concurrency,
        "request_throughput": len(results) / total_time,
        "output_throughput": total_out / total_time,
        "mean_ttft_ms": sum(ttfts) / len(ttfts) * 1000,
        "median_ttft_ms": ttfts[len(ttfts) // 2] * 1000,
        "p99_ttft_ms": ttfts[min(int(len(ttfts) * 0.99), len(ttfts) - 1)] * 1000,
        "mean_tpot_ms": sum(tpots) / len(tpots) * 1000,
        "median_tpot_ms": tpots[len(tpots) // 2] * 1000,
        "p99_tpot_ms": tpots[min(int(len(tpots) * 0.99), len(tpots) - 1)] * 1000,
    }


def _parse_bench_output(stdout: str) -> dict:
    """正则解析 vllm bench 文本输出"""
    metrics = {}
    patterns = {
        "request_throughput": r"Request throughput.*?:\s*([\d.]+)\s*requests/s",
        "output_throughput": r"Output token throughput.*?:\s*([\d.]+)\s*tokens/s",
        "mean_ttft_ms": r"Mean TTFT.*?:\s*([\d.]+)\s*ms",
        "median_ttft_ms": r"Median TTFT.*?:\s*([\d.]+)\s*ms",
        "p99_ttft_ms": r"P99 TTFT.*?:\s*([\d.]+)\s*ms",
        "mean_tpot_ms": r"Mean TPOT.*?:\s*([\d.]+)\s*ms",
        "median_tpot_ms": r"Median TPOT.*?:\s*([\d.]+)\s*ms",
        "p99_tpot_ms": r"P99 TPOT.*?:\s*([\d.]+)\s*ms",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, stdout)
        if m:
            try:
                metrics[key] = float(m.group(1))
            except ValueError:
                pass
    return metrics


# ============================================================
#  准确率测试
# ============================================================

def _run_accuracy_stage(db: Session, model_run: ModelRun, config: dict, log_callback, runner: RemoteRunner):
    port = config.get("container_port", 8300)
    datasets = config.get("acc_datasets", ["mmlu", "ceval", "gsm8k", "arc"])
    limit = config.get("acc_limit", 200)

    api_url = f"http://{runner.api_host}:{port}/v1"
    gen_config = json.dumps({"temperature": 0.0, "max_tokens": 512, "do_sample": False})

    cmd = ["evalscope", "eval", "--model", model_run.model_name,
           "--eval-type", "openai_api", "--api-url", api_url,
           "--api-key", "EMPTY", "--datasets"] + datasets + [
           "--limit", str(limit), "--generation-config", gen_config]

    log_callback("INFO", model_run.model_slug,
                 f"评测命令: evalscope eval --model {model_run.model_name} --datasets {' '.join(datasets)} --limit {limit}", "accuracy")
    log_callback("INFO", model_run.model_slug, f"API 地址: {api_url}", "accuracy")
    log_callback("INFO", model_run.model_slug, f"生成配置: temperature=0, max_tokens=512", "accuracy")
    log_callback("INFO", model_run.model_slug, f"开始评测，预计耗时较长 (limit={limit}/数据集)...", "accuracy")

    try:
        # evalscope 在本机执行（通过 API 调用远端 vLLM）
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=14400)
        metrics = _parse_evalscope_output(res.stdout)
        for line in res.stdout.strip().split("\n")[-20:]:
            if any(kw in line.lower() for kw in ("accuracy", "score", "result", "metric", "pass", "eval")):
                log_callback("INFO", model_run.model_slug, f"  {line.strip()[:200]}", "accuracy")
        for ds in datasets:
            acc = None
            for k, v in metrics.items():
                if ds in k.lower() and "accuracy" in k.lower():
                    try:
                        acc = float(v)
                    except (ValueError, TypeError):
                        pass
                    break
            db.add(AccResult(model_run_id=model_run.id, dataset=ds, accuracy=acc, limit=limit,
                             error=None if acc is not None else "解析失败"))
            db.commit()
            log_callback("INFO", model_run.model_slug,
                         f"  准确率 {ds}: {acc:.2%}" if acc is not None else f"  {ds}: 失败", "accuracy")
    except subprocess.TimeoutExpired:
        for ds in datasets:
            db.add(AccResult(model_run_id=model_run.id, dataset=ds, error="timeout"))
        db.commit()
    except Exception as e:
        for ds in datasets:
            db.add(AccResult(model_run_id=model_run.id, dataset=ds, error=str(e)))
        db.commit()


def _parse_evalscope_output(stdout: str) -> dict:
    metrics = {}
    for m in re.findall(r"(\w+).*?accuracy.*?([\d.]+)", stdout, re.IGNORECASE):
        try:
            metrics[f"{m[0].lower()}_accuracy"] = float(m[1])
        except ValueError:
            pass
    return metrics
