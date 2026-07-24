import os
import sys
import time
import re
import json
import socket
import threading
import textwrap
import subprocess
from datetime import datetime
from pathlib import Path
import requests

from .csv_handler import read_model_csv, update_csv_result

# 默认全局常量配置
CONTAINER_NAME = "model_test_runner"
VLLM_HOST = "127.0.0.1"
VLLM_STARTUP_TIMEOUT = 7200  # 最大超时 2 小时给容器下载并启动
CHAT_TIMEOUT = 60
DISK_LOW_THRESHOLD_GB = 100   # 剩余空间低于此值时清理本地模型缓存

def keep_sudo_alive():
    """在后台更新 sudo 密码缓存，防止长时间挂机跑批测试时密码过期."""
    while True:
        try:
            subprocess.run(["sudo", "-n", "-v"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        time.sleep(60)

def is_port_in_use(port: int) -> bool:
    """快速检查宿主机对应端口是否已被其他进程占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(('127.0.0.1', port)) == 0

def get_disk_free_gb(models_dir: Path) -> float:
    """检查模型存储目录所在硬盘的分区剩余空间"""
    import shutil
    total, used, free = shutil.disk_usage(str(models_dir))
    return free / (1024 ** 3)

def verify_sudo():
    """运行前检查凭证；如果当前用户可直连 docker，则静默通过"""
    try:
        res = subprocess.run(["sudo", "-n", "true"], capture_output=True)
        if res.returncode == 0:
            t = threading.Thread(target=keep_sudo_alive, daemon=True)
            t.start()
    except Exception:
        pass

def extract_model_name(cmd: str) -> str | None:
    """从 Docker 部署命令中正则匹配出 MODEL_NAME 的值"""
    m = re.search(r"-e MODEL_NAME=([^ \n\\]+)", cmd)
    return m.group(1).strip() if m else None

def stop_existing_container():
    """彻底并优雅地停止并删除 model_test_runner 容器，以完全释放 UMA 统一显存"""
    # 检查容器是否运行中
    check_running = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME],
        capture_output=True, text=True, timeout=10
    )
    is_running = check_running.stdout.strip() == "true"
    
    if is_running:
        print(f"  [Docker] 检测到旧容器在运行，正在优雅停止 (t=15 SIGTERM)...")
        subprocess.run(["docker", "stop", "-t", "15", CONTAINER_NAME], capture_output=True, timeout=35)
        time.sleep(2)
        
    # 干净删除容器，如果僵死或被阻碍则强行 rm
    check_exists = subprocess.run(
        ["docker", "inspect", CONTAINER_NAME],
        capture_output=True, timeout=10
    )
    if check_exists.returncode == 0:
        rm_check = subprocess.run(["docker", "rm", CONTAINER_NAME], capture_output=True, timeout=10)
        if rm_check.returncode != 0:
            print("  [Docker] [Warning] 容器优雅删除失败，执行强杀 rm -f...")
            subprocess.run(["docker", "kill", CONTAINER_NAME], capture_output=True, timeout=10)
            subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True, timeout=10)
            time.sleep(3)
    else:
        time.sleep(1)

def build_docker_cmd(original_cmd: str) -> str:
    """提取 CSV 里的部署指令，转换并注入符合测试管线的标准化后台运行参数"""
    cmd = original_cmd.strip()
    cmd = cmd.replace("&quot;", '"').replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<")
    cmd = re.sub(r"(sudo\s+)?docker\s+run\b", "docker run", cmd)
    cmd = re.sub(r"(?<= )--rm(?=\s|$|\\)", "", cmd)
    cmd = re.sub(r"(?<= )-it(?=\s|$|\\)", "", cmd)
    cmd = re.sub(r"\s+-d\b", "", cmd)
    cmd = re.sub(r"\s+--restart\s+\S+", "", cmd)
    cmd = re.sub(r"\s+--name\s+\S+", "", cmd)
    cmd = re.sub(r"(docker run)\b", f"\\1 -d --name {CONTAINER_NAME}", cmd, count=1)
    
    # 解决 nightly 镜像 entrypoint 重叠覆盖问题
    if "nightly-aarch64" in cmd:
        cmd = re.sub(r'(aoni/vllm/vllm-openai:nightly-aarch64\s+)vllm\s+serve\s+\S+(?=\s|\\|$)', r'\1', cmd)
    return cmd

def start_container(original_cmd: str, log_file: Path) -> bool:
    """标准化修改并启动容器，将其标准输出和标准错误输出流记录至 log_file"""
    docker_cmd = build_docker_cmd(original_cmd)
    print(f"  容器启动命令:\n{textwrap.indent(docker_cmd[:350] + '...', '    ')}")
    os.makedirs(log_file.parent, exist_ok=True)
    with open(log_file, "a") as lf:
        lf.write(f"=== docker cmd ===\n{docker_cmd}\n")

    try:
        res = subprocess.run(docker_cmd, shell=True, capture_output=True, text=True, timeout=1800)
        with open(log_file, "a") as lf:
            lf.write(f"=== docker run stdout ===\n{res.stdout}\n")
            lf.write(f"=== docker run stderr ===\n{res.stderr}\n")
        
        if res.returncode != 0:
            print(f"  [ERROR] 容器创建失败 (rc={res.returncode}): {res.stderr[:200]}")
            return False
            
        container_id = res.stdout.strip()
        print(f"  容器创建成功: {container_id[:12]}")
        
        # 等待 5 秒打印最初始日志
        time.sleep(5)
        init_logs = subprocess.run(["docker", "logs", CONTAINER_NAME], capture_output=True, text=True)
        init_output = (init_logs.stdout + init_logs.stderr).strip()
        with open(log_file, "a") as lf:
            lf.write(f"=== docker initial logs ===\n{init_output}\n")
        return True
    except subprocess.TimeoutExpired:
        print("  [ERROR] 容器命令执行超时")
        return False

def wait_for_vllm(log_file: Path, port: int) -> bool:
    """轮询 vLLM 接口直到其就绪 (包含模型下载和显存加载，最长等待 2 小时)"""
    url = f"http://{VLLM_HOST}:{port}/v1/models"
    deadline = time.time() + VLLM_STARTUP_TIMEOUT
    print(f"  轮询就绪状态 (最大等待超时 {VLLM_STARTUP_TIMEOUT}s)...")
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                elapsed = int(time.time() - (deadline - VLLM_STARTUP_TIMEOUT))
                print(f"  vLLM 引擎服务已就绪！(用时 {elapsed}s)")
                return True
        except Exception:
            pass

        # 每 30 秒打印一次心跳及最新容器日志，并监测容器是否中途挂掉
        if attempt % 3 == 0:
            container_check = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Status}}", CONTAINER_NAME],
                capture_output=True, text=True
            )
            status = container_check.stdout.strip()
            elapsed = int(time.time() - (deadline - VLLM_STARTUP_TIMEOUT))

            if status not in ("running", "created"):
                print(f"  [ERROR] 检测到容器发生异常退出 (状态为: {status})，停止等待")
                return False

            logs_r = subprocess.run(
                ["docker", "logs", "--tail", "3", CONTAINER_NAME],
                capture_output=True, text=True
            )
            last_log = (logs_r.stdout + logs_r.stderr).strip()[-150:]
            print(f"  [{elapsed}s] 容器 {status}... 最尾日志:\n{textwrap.indent(last_log, '    ')}")
            with open(log_file, "a") as lf:
                lf.write(f"=== docker logs (elapsed={elapsed}s) ===\n{logs_r.stdout}\n{logs_r.stderr}\n")
        time.sleep(10)

    print("  [ERROR] vLLM 服务轮询就绪超时")
    return False

def chat_test(model_name: str, log_file: Path, port: int) -> tuple[bool, str]:
    """发送测试 Prompt，若成功回答则返回 PASS 与具体回答文本，支持思维链验证"""
    url = f"http://{VLLM_HOST}:{port}/v1/chat/completions"
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "你好，请问 1+1 等于几？"}],
        "max_tokens": 50,
        "temperature": 0,
    }
    print("  发送基础对话验证请求...")
    try:
        r = requests.post(url, json=payload, timeout=CHAT_TIMEOUT)
        with open(log_file, "a") as lf:
            lf.write(f"=== chat request ===\n{json.dumps(payload, ensure_ascii=False)}\n")
            lf.write(f"=== chat response ({r.status_code}) ===\n{r.text[:2000]}\n")

        if r.status_code != 200:
            return False, f"HTTP_{r.status_code}"

        data = r.json()
        msg = data["choices"][0]["message"]
        content = (msg.get("content") or "").strip()
        reasoning = (msg.get("reasoning_content") or msg.get("reasoning") or "").strip()
        ans = content or reasoning

        display_content = ans[:80]
        if reasoning:
            print(f"  模型思维链 (reasoning): {reasoning[:60]}...")
            
        print(f"  模型回答: {display_content!r}")
        return (True, f"PASS: {display_content}") if ans else (False, "EMPTY_RESPONSE")
    except requests.exceptions.Timeout:
        return False, "CHAT_TIMEOUT"
    except Exception as e:
        return False, f"CHAT_ERROR: {type(e).__name__}: {e}"

def cleanup_model(model_name: str, models_dir: Path):
    """如果磁盘剩余空间低于阈值，则清理本地缓存的模型目录以避免磁盘占满"""
    try:
        free_gb = get_disk_free_gb(models_dir)
        org, name = model_name.split("/", 1)
        model_dir = models_dir / org / name
        if free_gb < DISK_LOW_THRESHOLD_GB:
            if model_dir.exists():
                subprocess.run(["rm", "-rf", str(model_dir)], check=False)
                print(f"  [Disk] 磁盘剩余空间 {free_gb:.1f}GB < {DISK_LOW_THRESHOLD_GB}GB，自动清理模型缓存: {model_dir}")
        else:
            print(f"  [Disk] 磁盘剩余空间 {free_gb:.1f}GB，保留模型缓存以复用")
    except Exception as e:
        print(f"  [Warning] 清理模型文件时发生异常: {e}")

def stop_and_cleanup_container():
    """强制关停容器并清理无用镜像，平滑释放显存"""
    print("  清理并关停 Docker 测试容器中...")
    stop_existing_container()
    subprocess.run(["docker", "image", "prune", "-f"], capture_output=True)

def test_single_row(row: dict, csv_path: Path, log_dir: Path, models_dir: Path) -> str:
    """完整测试单行模型记录的核心工作流"""
    idx, name, slug, cmd, tos_path = row["idx"], row["name"], row["slug"], row["cmd"], row["tos_path"]
    print(f"\n{'='*60}\n[运行测试 #{idx}] 模型名称: {name}\n{'='*60}")
    
    log_file = log_dir / f"{int(idx):02d}_{slug}.log"
    with open(log_file, "w") as lf:
        lf.write(f"=== 测试开始: {name} ===\n当前系统时间: {datetime.now()}\n\n")

    model_name = extract_model_name(cmd)
    if not model_name:
        result = "FAIL: 无法从命令中提取 MODEL_NAME"
        print(f"  {result}")
        return result

    if tos_path.startswith("NOT_IN_TOS"):
        result = "FAIL: TOS 上无此模型文件"
        print(f"  {result}")
        return result

    # 1. 端口冲突校验
    port_match = re.search(r"--port\s+(\d+)", cmd)
    port = int(port_match.group(1)) if port_match else 8000
    if is_port_in_use(port):
        result = f"FAIL: 端口 {port} 被占用"
        print(f"  {result}")
        return result

    # 2. 清理残留，清理 Page Cache 释放显存/UMA 缓存
    stop_existing_container()
    print("  清理系统 Page Cache 并释放统一内存...")
    subprocess.run(["sudo", "sysctl", "-w", "vm.drop_caches=3"], capture_output=True)
    time.sleep(2)

    # 3. 启动
    ok = start_container(cmd, log_file)
    if not ok:
        result = "FAIL: 容器启动超时或失败"
        stop_and_cleanup_container()
        cleanup_model(model_name, models_dir)
        return result

    # 4. 轮询就绪
    ready = wait_for_vllm(log_file, port)
    if not ready:
        docker_logs = subprocess.run(["sudo", "docker", "logs", CONTAINER_NAME], capture_output=True, text=True)
        with open(log_file, "a") as lf:
            lf.write(f"=== 最终容器日志 ===\n{docker_logs.stdout}\n{docker_logs.stderr}\n")
        result = "FAIL: vLLM 启动超时"
        stop_and_cleanup_container()
        cleanup_model(model_name, models_dir)
        return result

    # 5. 对话测试
    passed, msg = chat_test(model_name, log_file, port)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    result = f"PASS ({ts})" if passed else f"FAIL: {msg}"
    print(f"  测试完成 -> {'✓' if passed else '✗'} {result}")

    # 6. 后处理及清理
    stop_and_cleanup_container()
    cleanup_model(model_name, models_dir)

    with open(log_file, "a") as lf:
        lf.write(f"\n=== 结果: {result} ===\n结束系统时间: {datetime.now()}\n")

    return result

def run_tests_loop(csv_path: Path, log_dir: Path, models_dir: Path, start_idx: int, end_idx: int, resume: bool):
    """模型批处理测试循环总控"""
    verify_sudo()
    log_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    rows, _ = read_model_csv(csv_path)
    target_rows = [r for r in rows if r["idx"].isdigit() and start_idx <= int(r["idx"]) <= end_idx]
    
    print(f"待测试模型数量: {len(target_rows)} (序号范围: #{start_idx} ~ #{end_idx})")
    print(f"断点续测模式: {'开启' if resume else '关闭'}")

    stop_existing_container()
    summary = []

    for row in target_rows:
        idx, name = row["idx"], row["name"]
        if resume and row["result"].startswith("PASS"):
            print(f"已跳过 #{idx} {name} (已通过校验)")
            summary.append((idx, name, row["result"]))
            continue

        try:
            result = test_single_row(row, csv_path, log_dir, models_dir)
        except KeyboardInterrupt:
            print("\n[WARN] 用户手动中断了测试循环")
            stop_existing_container()
            break
        except Exception as e:
            result = f"FAIL: 未捕获异常: {type(e).__name__}: {e}"
            print(f"  {result}")

        update_csv_result(csv_path, idx, result)
        summary.append((idx, name, result))
        time.sleep(5)

    print(f"\n{'='*60}\n全部测试运行汇总\n{'='*60}")
    pass_cnt = sum(1 for _, _, r in summary if r.startswith("PASS"))
    for idx, name, res in summary:
        print(f"  {'✓' if res.startswith('PASS') else '✗'} #{idx:>2}: {name:<35} {res}")
    print(f"\n总计: {pass_cnt} 通过 / {len(summary) - pass_cnt} 失败 / {len(summary)} 合计")
