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
import os
from pathlib import Path
from datetime import datetime
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.models import Task, ModelRun, PerfResult, AccResult, GatewayResult, TaskLog, ModelStage, StageStatus, Device, ModelInfo
from sqlalchemy import select
from backend.config import REPORTS_DIR, LOGS_DIR, DATA_DIR
from backend.services.pipeline import get_concurrency_for_category

log = logging.getLogger(__name__)
CONTAINER_NAME = "aoni_benchmark_runner"
# 全局串行化容器“清理+创建”，防止多路并发(含单模型重试)抢同一容器名导致 Conflict/token=0
_container_launch_lock = threading.Lock()


def _wait_if_paused(task_id: int):
    """暂停等待: 任务被暂停时阻塞在此，直到恢复或被取消。用于阶段间/数据集间检查点。"""
    from backend.services.task_manager import _cancel_flags, _pause_flags
    while _pause_flags.get(task_id, False):
        if _cancel_flags.get(task_id, False):
            raise InterruptedError("任务已在暂停期间被取消")
        time.sleep(2)


def _format_duration(seconds: float) -> str:
    """格式化秒数为易读时间，如 '45秒' 或 '2分15秒' 或 '1小时10分'"""
    if seconds is None or seconds <= 0:
        return "0秒"
    s = int(seconds)
    if s < 60:
        return f"{s}秒"
    m = s // 60
    rem_s = s % 60
    if m < 60:
        return f"{m}分{rem_s}秒" if rem_s > 0 else f"{m}分钟"
    h = m // 60
    rem_m = m % 60
    return f"{h}小时{rem_m}分" if rem_m > 0 else f"{h}小时"



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
        return self.run(["docker"] + args, timeout)

    def get_available_disk_gb(self) -> float:
        """获取目标节点挂载点 (如 /models 或 /home 或 /) 的可用磁盘空间 (单位 GB)"""
        try:
            res = self.run_shell("df -BG /models 2>/dev/null || df -BG /home 2>/dev/null || df -BG /", timeout=10)
            if res.returncode == 0 and res.stdout:
                lines = [l.strip() for l in res.stdout.strip().split("\n") if l.strip()]
                if len(lines) >= 2:
                    parts = lines[-1].split()
                    if len(parts) >= 4:
                        avail_str = parts[3].rstrip("G").rstrip("B")
                        return float(avail_str)
        except Exception:
            pass
        return 999.0


# ---------- 底层执行函数 ----------

def _local_exec(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        # 如果是 sudo 命令，自动添加 -n (non-interactive)
        if cmd and cmd[0] == "sudo" and (len(cmd) == 1 or cmd[1] != "-n"):
            cmd = ["sudo", "-n"] + cmd[1:]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, -1, stdout="", stderr="timeout")
    except Exception as e:
        return subprocess.CompletedProcess(cmd, -1, stdout="", stderr=str(e))


def _local_exec_shell(cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        if cmd.strip().startswith("sudo ") and not cmd.strip().startswith("sudo -n "):
            cmd = "sudo -n " + cmd.strip()[5:]
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, -1, stdout="", stderr="timeout")
    except Exception as e:
        return subprocess.CompletedProcess(cmd, -1, stdout="", stderr=str(e))


def _ssh_exec(ssh_info: dict, cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """通过 SSH 在远程设备执行命令，支持密钥和密码两种方式，并自动为 sudo 命令注入密码"""
    pwd = ssh_info.get("password")
    # 如果是以 sudo 开头的列表命令，且存在密码，自动改写为 echo 'pwd' | sudo -S -E
    if pwd and cmd and cmd[0] == "sudo":
        esc_pwd = pwd.replace("'", "'\\''")
        docker_sub_cmd = " ".join(_quote_arg(a) for a in cmd[1:])
        cmd = ["bash", "-c", f"echo '{esc_pwd}' | sudo -S -E {docker_sub_cmd}"]

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
    pwd = ssh_info.get("password")
    if pwd and "sudo" in cmd and "sudo -S" not in cmd:
        esc_pwd = pwd.replace("'", "'\\''")
        cmd = re.sub(r"(^|\s)sudo\b", f"\\1echo '{esc_pwd}' | sudo -S -E", cmd)
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

def _get_gpu_free_mib(runner: RemoteRunner) -> float:
    """获取系统可用内存 (MiB)。
    Jetson Thor 为 CPU/GPU 统一内存架构，直接读 /proc/meminfo MemAvailable。
    标准 PCIe GPU 优先用 nvidia-smi memory.free，不支持时回退到 /proc/meminfo。
    """
    # 优先尝试 nvidia-smi（标准独立 GPU）
    try:
        r = runner.run_shell(
            "nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null",
            timeout=5,
        )
        val = (r.stdout or "").strip().split("\n")[0].strip()
        if val and val != "[N/A]" and val.lstrip("-").isdigit():
            return float(val)
    except Exception:
        pass

    # Jetson 统一内存：读 /proc/meminfo MemAvailable (单位 kB → MiB)
    try:
        r = runner.run_shell("grep MemAvailable /proc/meminfo", timeout=3)
        line = (r.stdout or "").strip()
        kb = int(line.split()[1])
        return kb / 1024.0
    except Exception:
        pass

    return 999999.0  # 无法获取时视为充足


def _wait_gpu_free(runner: RemoteRunner, min_free_mib: float = 81920, max_wait: int = 120, log_callback=None):
    """等待系统可用内存 >= min_free_mib (默认 80 GiB)，最多等 max_wait 秒。
    vLLM 需要 0.6 × 122.82 GiB = 73.69 GiB，加 6 GiB 余量设为 80 GiB。
    """
    for elapsed in range(0, max_wait, 3):
        free_mib = _get_gpu_free_mib(runner)
        if free_mib >= min_free_mib:
            if log_callback and elapsed > 0:
                log_callback("INFO", "", f"  内存已回收：可用 {free_mib/1024:.1f} GiB，满足启动条件 (≥{min_free_mib/1024:.0f} GiB)", "container")
            return True
        if log_callback:
            log_callback("INFO", "", f"  等待内存回收... 当前可用 {free_mib/1024:.1f} GiB / 需要 {min_free_mib/1024:.0f} GiB ({elapsed}s)", "container")
        time.sleep(3)
    free_mib = _get_gpu_free_mib(runner)
    if log_callback:
        log_callback("WARNING", "", f"  内存等待超时 ({max_wait}s)，当前可用 {free_mib/1024:.1f} GiB，强制继续", "container")
    return False


def _get_gpu_total_mib(runner: RemoteRunner) -> float:
    """获取系统总内存 (MiB)。Jetson 统一内存读 /proc/meminfo，标准 GPU 读 nvidia-smi。"""
    try:
        r = runner.run_shell(
            "nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null",
            timeout=5,
        )
        val = (r.stdout or "").strip().split("\n")[0].strip()
        if val and val != "[N/A]" and val.lstrip("-").isdigit():
            return float(val)
    except Exception:
        pass
    try:
        r = runner.run_shell("grep MemTotal /proc/meminfo", timeout=3)
        return int(r.stdout.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def _get_gpu_top_consumers(runner: RemoteRunner, top: int = 3) -> str:
    """获取 GPU 显存占用最高的进程描述（用于报错提示），失败返回空串。"""
    try:
        r = runner.run_shell(
            "nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader 2>/dev/null",
            timeout=5,
        )
        items = []
        for line in (r.stdout or "").strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 2:
                continue
            pid, mem = parts
            try:
                mem_f = float(mem.replace("MiB", "").strip())
            except ValueError:
                continue
            cmd_r = runner.run_shell(f"ps -p {pid} -o args= 2>/dev/null", timeout=3)
            name = (cmd_r.stdout or "").strip() or f"pid {pid}"
            if len(name) > 60:
                name = name[:57] + "..."
            items.append((mem_f, name))
        items.sort(reverse=True)
        return "；".join(f"{name} 占 {mem/1024:.0f} GiB" for mem, name in items[:top])
    except Exception:
        return ""


def check_gpu_memory(runner: RemoteRunner, docker_cmd: str) -> tuple[bool, str]:
    """
    启动容器前检查目标机内存是否足够 vLLM 预分配。
    vLLM 按 gpu_memory_utilization × 总内存 预分配；非 vLLM 命令(llama.cpp 等)不做限制。
    返回 (ok, 错误提示)。读不到总量时不拦截。
    """
    try:
        if "vllm" not in (docker_cmd or "").lower():
            return True, ""
        m = re.search(r"--gpu-memory-utilization\s+([\d.]+)", docker_cmd or "")
        util = float(m.group(1)) if m else 0.8
        total_mib = _get_gpu_total_mib(runner)
        if total_mib <= 0:
            return True, ""
        free_mib = _get_gpu_free_mib(runner)
        required_mib = total_mib * util
        if free_mib < required_mib:
            msg = (f"目标机 [{runner.host_label}] 内存不足: vLLM 需预分配约 {required_mib/1024:.0f} GiB "
                   f"(gpu-memory-utilization={util} × 总内存 {total_mib/1024:.0f} GiB)，"
                   f"当前仅剩 {free_mib/1024:.1f} GiB。")
            tops = _get_gpu_top_consumers(runner)
            if tops:
                msg += f" 显存占用大户: {tops}。"
            msg += " 请先停止占用内存的服务/容器后重试。"
            return False, msg
        return True, ""
    except Exception:
        return True, ""



def _stop_container(runner: RemoteRunner, log_callback=None):
    """停止并删除旧容器，强杀僵尸子进程，深度释放 GPU 显存与系统内存，等待 GPU 完全空闲"""
    # 第 0 步：先探测是否存在平台管理的容器。
    # 仅当确实存在由平台下发的测试容器时，才允许后续回收 CUDA 计算进程，
    # 避免外部 API/无容器任务(device=None 走本地 runner)误杀本机手动部署的服务
    # (如用户自行启动的 MiniCPM5 / vllm 原生服务)。
    had_managed_container = False
    try:
        res = runner.run_shell(
            "sudo docker ps -a -q --filter name=aoni_benchmark_runner "
            "--filter name=test_ --filter name=debug_ 2>/dev/null | wc -l",
            timeout=5,
        )
        count = (res.stdout or "").strip()
        had_managed_container = count not in ("", "0")
    except Exception:
        pass

    # 第 1 步：强制删除所有相关容器
    runner.run_shell("sudo docker rm -f aoni_benchmark_runner test_eager test_vl_live debug_gemma27b_file 2>/dev/null || true", timeout=5)
    runner.run_shell("sudo docker ps -a --filter name=test_ --filter name=debug_ -q | xargs -r sudo docker rm -f 2>/dev/null || true", timeout=5)

    # 第 2 步：杀掉占用推理端口的进程（含 MIM 容器固定服务端口 25535）
    runner.run_shell("fuser -k 8300/tcp 2>/dev/null || true; fuser -k 25535/tcp 2>/dev/null || true", timeout=3)

    # 第 3 步：仅在确认平台确实管理了测试容器时才回收 CUDA 计算进程（排除 Xorg / gnome）
    # 避免无差别 kill -9 本机手动部署的外部 API / vllm 服务。
    if had_managed_container:
        runner.run_shell(
            "nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null "
            "| xargs -r -I{} sh -c 'kill -9 {} 2>/dev/null || true'",
            timeout=5,
        )

    # 第 4 步：清理系统页缓存和 slab（优先通过免密特权容器或 sysctl 彻底释放）
    try:
        runner.run_shell("docker run --rm --privileged -v /proc/sys/vm:/host_vm alpine sh -c 'sync && echo 3 > /host_vm/drop_caches' 2>/dev/null || sudo sysctl -w vm.drop_caches=3 2>/dev/null || true", timeout=10)
    except Exception:
        pass

    # 第 5 步：等待系统可用内存满足启动门槛（设为 32 GiB，当前 52 GiB 已完全足够）
    _wait_gpu_free(runner, min_free_mib=32768, max_wait=30, log_callback=log_callback)




def _start_container(runner: RemoteRunner, docker_cmd: str, port: int, log_callback) -> tuple[bool, str]:
    """启动容器并返回 (成功, container_id)。用全局锁串行化‘清理+创建’，避免并发抢同一容器名导致 Conflict/token=0。"""
    with _container_launch_lock:
        # 强制无条件清空同名冲突容器，确保 docker run 绝不报 Conflict 错
        runner.run_shell(f"sudo docker rm -f {CONTAINER_NAME} 2>/dev/null || docker rm -f {CONTAINER_NAME} 2>/dev/null", timeout=5)
        time.sleep(1)

        cmd = docker_cmd.strip()
        cmd = cmd.replace("&quot;", '"').replace("&amp;", "&")
        cmd = cmd.replace("\\\n", " ").replace("\\", " ")

        # ── 内存预检: vLLM 需预分配 gpu_memory_utilization × 总内存，不足直接友好报错 ──
        mem_ok, mem_msg = check_gpu_memory(runner, cmd)
        if not mem_ok:
            log_callback("ERROR", "", mem_msg, "container")
            return False, mem_msg

        cmd = re.sub(r"\s+-([it]{1,2})\b", "", cmd)
        cmd = re.sub(r"\s+--rm\b", "", cmd)

        # ── 本地模型优先策略 ────────────────────────────────────────────────────────
        # 若本地 MODEL_ROOT/MODEL_NAME 目录已存在，直接使用本地权重，跳过 TOS 下载
        _model_name_m = re.search(r"-e\s+MODEL_NAME=(\S+)", cmd)
        _model_root_m = re.search(r"-e\s+MODEL_ROOT=(\S+)", cmd)
        if _model_name_m and _model_root_m:
            _model_name = _model_name_m.group(1)
            _model_root_container = _model_root_m.group(1)  # 容器内路径, e.g. /models
            # 找 volume 挂载：-v <host_path>:<container_root>
            _vol_m = re.search(rf"-v\s+(\S+):{re.escape(_model_root_container)}", cmd)
            _host_root = _vol_m.group(1) if _vol_m else None
            if _host_root:
                # 存在性检查：远程设备必须下发到目标机执行（os.path.isdir 只能看到后端机自己的文件系统）
                _root_raw = _vol_m.group(1)  # 原始挂载路径（可能含 ~）
                _host_root = os.path.expanduser(_root_raw)
                _local_model_path = os.path.join(_host_root, _model_name)
                # 容器内的模型路径（挂载后）
                _container_model_path = f"{_model_root_container}/{_model_name}"
                if runner.is_remote:
                    # 远程机：~ 由目标机 shell 展开为其家目录（用 $HOME 前缀保证展开）
                    _rest = (_root_raw[1:] if _root_raw.startswith("~") else _root_raw) + "/" + _model_name
                    _rest = _rest.replace("'", "'\\''")
                    _check_expr = f"$HOME'{_rest}'" if _root_raw.startswith("~") else f"'{_rest}'"
                    _check_res = runner.run_shell(f"test -d {_check_expr}", timeout=15)
                    _has_local_model = _check_res.returncode == 0
                else:
                    _has_local_model = os.path.isdir(_local_model_path)
                # 日志展示路径（远程机显示 ~ 原样路径，本机显示展开路径）
                _display_path = _local_model_path if not runner.is_remote else (_root_raw.rstrip("/") + "/" + _model_name)
                if _has_local_model:
                    # 本地已有完整模型目录 → 强制禁用 TOS 下载
                    cmd = re.sub(r"-e\s+MODEL_OSS=\S+", "-e MODEL_OSS=False", cmd)
                    # 关键：vllm_monkey 在 MODEL_OSS=False 时不会自动传 --model 参数
                    # 必须在命令行里显式追加 --model <容器内路径>，否则 vLLM 使用默认模型
                    if "--model " not in cmd and "-m " not in cmd:
                        # 在镜像名之后、其他 vllm 参数之前插入 --model
                        cmd = re.sub(
                            r"(aoni-docker-cn-guangzhou\.cr\.volces\.com/public/llm:[^\s]+|aoni/vllm/vllm-openai:\S+)\s*",
                            rf"\1 --model {_container_model_path} ",
                            cmd,
                            count=1,
                        )
                    if log_callback:
                        log_callback("INFO", "", f"  [本地优先] 检测到本地模型: {_display_path}，已跳过 TOS 下载 (MODEL_OSS=False, --model {_container_model_path})", "container")
                else:
                    if log_callback:
                        log_callback("INFO", "", f"  [TOS 下载] 本地路径 {_display_path} 不存在，将从 TOS 拉取模型权重", "container")
        # ───────────────────────────────────────────────────────────────────────────


        # 存在性检查：远程设备必须下发到目标机执行（os.path.exists 只能看到后端机自己的文件系统）
        if runner.is_remote:
            _pp_res = runner.run_shell("test -d /models/python_packages", timeout=15)
            _has_python_packages = _pp_res.returncode == 0
        else:
            _has_python_packages = os.path.exists("/models/python_packages")

        if _has_python_packages:

            if "-v /models/python_packages" not in cmd and "-v /models:" not in cmd:
                cmd = re.sub(r"(docker run\b)", r"\1 -v /models/python_packages:/models/python_packages", cmd, count=1)
            if "-e PYTHONPATH=" not in cmd:
                cmd = re.sub(r"(docker run\b)", r"\1 -e PYTHONPATH=/models/python_packages:$PYTHONPATH", cmd, count=1)
            if "-e PIP_FIND_LINKS=" not in cmd:
                cmd = re.sub(r"(docker run\b)", r"\1 -e PIP_FIND_LINKS=file:///models/python_packages -e PIP_NO_INDEX=1", cmd, count=1)

        if "-e VLLM_USE_V1=" not in cmd and "mxcr.metax-tech.com/" not in cmd:
            cmd = re.sub(r"(docker run\b)", r"\1 -e VLLM_USE_V1=0", cmd, count=1)

        is_llama_cpp = "llama_cpp" in cmd or "llama-cpp" in cmd
        is_mim = "mxcr.metax-tech.com/" in cmd  # MIM 官方镜像: 固定 entrypoint，禁止通用 vLLM 参数注入
        if runner.is_remote:
            cmd = re.sub(r"(sudo\s+)?docker\s+run\b", "sudo docker run", cmd)
            cmd = re.sub(r"\s+-d\b", "", cmd)
            cmd = re.sub(r"\s+-it\b", "", cmd)
            cmd = re.sub(r"\s+--rm\b", "", cmd)
            cmd = re.sub(r"\s+--restart\s+\S+", "", cmd)
            cmd = re.sub(r"\s+--name\s+\S+", "", cmd)
            if is_llama_cpp or is_mim:
                cmd = re.sub(r"(sudo docker run)\b", f"\\1 -d --name {CONTAINER_NAME}", cmd, count=1)
            else:
                cmd = re.sub(r"(sudo docker run)\b", f"\\1 -d --name {CONTAINER_NAME} --memory 112g --memory-swap 112g", cmd, count=1)
            # 清除重复的 --shm-size，然后统一追加一个（MIM 镜像保留自带的 100gb）
            if not is_mim:
                cmd = re.sub(r"\s+--shm-size\s+\S+", "", cmd)
                cmd = re.sub(r"(sudo docker run)\b", r"\1 --shm-size 16g", cmd, count=1)
        else:
            cmd = re.sub(r"(sudo\s+)?docker\s+run\b", "docker run", cmd)
            cmd = re.sub(r"\s+-d\b", "", cmd)
            cmd = re.sub(r"\s+-it\b", "", cmd)
            cmd = re.sub(r"\s+--rm\b", "", cmd)
            cmd = re.sub(r"\s+--restart\s+\S+", "", cmd)
            cmd = re.sub(r"\s+--name\s+\S+", "", cmd)
            if is_llama_cpp or is_mim:
                cmd = re.sub(r"(docker run)\b", f"\\1 -d --name {CONTAINER_NAME}", cmd, count=1)
            else:
                cmd = re.sub(r"(docker run)\b", f"\\1 -d --name {CONTAINER_NAME} --memory 112g --memory-swap 112g", cmd, count=1)
            # 清除重复的 --shm-size，然后统一追加一个（MIM 镜像保留自带的 100gb）
            if not is_mim:
                cmd = re.sub(r"\s+--shm-size\s+\S+", "", cmd)
                cmd = re.sub(r"(docker run)\b", r"\1 --shm-size 16g", cmd, count=1)
        cmd = re.sub(r"--port\s+\d+", f"--port {port}", cmd)
        if not is_llama_cpp and not is_mim:
            if "--trust-remote-code" not in cmd:
                cmd += " --trust-remote-code"
            if ("-vl-" in cmd.lower() or "gemma-3" in cmd.lower() or "gemma-4" in cmd.lower()) and "--limit-mm-per-prompt" not in cmd:
                cmd += ' --limit-mm-per-prompt \'{"image": 4}\''
        if "nightly-aarch64" in cmd:
            cmd = re.sub(r'(aoni-docker-cn-guangzhou\.cr\.volces\.com/public/llm:vllm-openai-nightly-aarch64|aoni/vllm/vllm-openai:nightly-aarch64)\s+vllm\s+serve(\s+[^-][^\s]*)?', r'\1', cmd)

        short_cmd = cmd[:300] + "..." if len(cmd) > 300 else cmd
        log_callback("INFO", "", f"  [{runner.host_label}] docker run 命令: {short_cmd}", "container")

        try:
            res = runner.run_shell(cmd, timeout=10)
            cid = res.stdout.strip()
            if res.returncode == 0:
                log_callback("INFO", "", f"  容器启动成功, ID: {cid[:12]}", "container")
                time.sleep(2)
                init_logs = runner.run_docker(["logs", "--tail", "30", CONTAINER_NAME], timeout=10)
                if init_logs.stdout:
                    for line in init_logs.stdout.strip().split("\n"):
                        if line.strip():
                            log_callback("DEBUG", "", f"   [Container Log] {line.strip()[:200]}", "container")
                return True, cid
            else:
                err_msg = (res.stderr or res.stdout or "").strip()
                log_callback("ERROR", "", f"❌ 容器启动失败 (docker run returncode={res.returncode}): {err_msg[:300]}", "container")
                return False, ""
        except Exception as e:
            log_callback("ERROR", "", f"❌ 容器启动异常: {e}", "container")
            return False, ""



def _save_container_logs_to_file(runner: RemoteRunner, task_id: int, model_slug: str):
    """把未成功/失败模型的完整 Docker 容器 Output 倾倒保存到独立 log 文件中"""
    log_dir = "/home/sd1/Desktop/Aoni_Model_Testing_Platform/data/container_logs"
    try:
        os.makedirs(log_dir, exist_ok=True)
        filename = f"{log_dir}/task_{task_id}_{model_slug}.log"
        logs_res = runner.run_docker(["logs", "--tail", "500", CONTAINER_NAME], timeout=5)
        content = (logs_res.stderr or "") + "\n" + (logs_res.stdout or "")
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"=== Model: {model_slug} (Task #{task_id}) Container Full Dump Logs ===\n")
            f.write(content)
    except Exception:
        pass


def _wait_for_vllm(runner: RemoteRunner, port: int, timeout: int = 60, log_callback=None, task_id: int = 0) -> bool:
    """轮询等待 vLLM 服务就绪（带 180s TOS 网络超时快速跳过与实时日志增强）"""
    import requests
    url = f"http://{runner.api_host}:{port}/v1/models"
    # 给大型模型（如 Llama 3.1 8B / 30B / 多模态）至少保留 300 秒的权重加载与 CUDA 图捕获窗口
    actual_timeout = max(timeout if timeout and timeout > 0 else 1800, 300)
    deadline = time.time() + actual_timeout
    start_time = time.time()
    attempt = 0
    tos_error_count = 0
    seen_log_lines = set()

    while time.time() < deadline:
        attempt += 1
        from backend.services.task_manager import _cancel_flags
        if task_id and _cancel_flags.get(task_id, False):
            if log_callback:
                log_callback("WARNING", "", "检测到任务已重新下发/取消，旧服务轮询线程安全终止退出", "vllm")
            return False
        try:
            r = requests.get(url, timeout=3)
            if r.status_code == 200:
                # 二次验证: 确认 /v1/chat/completions 端点也已就绪（llama-server 等镜像模型加载后才开放此路由）
                chat_url = url.replace("/v1/models", "/v1/chat/completions")
                try:
                    cr = requests.post(chat_url, json={"model": "test", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}, timeout=5)
                    # 任何 HTTP 响应（包括 400/422 模型不匹配）都代表端口已在服务，Connection refused 才是未就绪
                    elapsed = int(time.time() - start_time)
                    if log_callback:
                        log_callback("INFO", "", f"  推理服务就绪 (用时 {elapsed}s)", "vllm")
                    return True
                except requests.exceptions.ConnectionError:
                    pass  # chat/completions 还未就绪，继续等待
                except Exception:
                    # 其他错误（超时、服务器错误）视为已就绪（端口开放但逻辑报错）
                    elapsed = int(time.time() - start_time)
                    if log_callback:
                        log_callback("INFO", "", f"  推理服务就绪 (用时 {elapsed}s)", "vllm")
                    return True
        except Exception:
            pass

        # 检查容器运行状态与拉取日志
        if attempt % 2 == 0 and log_callback:
            try:
                check = runner.run_docker(["inspect", "-f", "{{.State.Status}}", CONTAINER_NAME], timeout=3)
                status = check.stdout.strip()
                elapsed = int(time.time() - start_time)

                if status in ("exited", "dead"):
                    _save_container_logs_to_file(runner, task_id, getattr(runner, "current_model_slug", "unknown"))
                    err_logs = runner.run_docker(["logs", "--tail", "100", CONTAINER_NAME], timeout=5)
                    log_callback("ERROR", "", f"❌ 测试容器意外退出 (Status: {status})！完整容器 Log 已自动转存至 data/container_logs/，控制台摘要如下:", "vllm")
                    if err_logs.stdout or err_logs.stderr:
                        full_err = (err_logs.stderr or "") + "\n" + (err_logs.stdout or "")
                        for line in full_err.strip().split("\n"):
                            if line.strip():
                                log_callback("ERROR", "", f"   [Container Log] {line.strip()}", "vllm")
                    return False
                elif status not in ("running", "created"):
                    log_callback("WARNING", "", f"  容器状态: {status}，放弃等待服务初始化", "vllm")
                    return False

                # 提取容器全量最新日志，增量流式推送全新 Log 行
                clogs = runner.run_docker(["logs", "--tail", "100", CONTAINER_NAME], timeout=3)
                log_text = (clogs.stdout or "") + "\n" + (clogs.stderr or "")

                # 过滤出全新的、未展示过的 log 行，流式推送到前端控制台
                all_lines = [l.strip() for l in log_text.strip().split("\n") if l.strip()]
                new_lines = [l for l in all_lines if l not in seen_log_lines]
                if new_lines:
                    for line in new_lines[-5:]:
                        seen_log_lines.add(line)
                        log_callback("INFO", "", f"  [Live Log] {line}", "vllm")

                # 动态提取日志中的下载/解压百分比
                progress_match = re.search(r"(\d{1,3})%", log_text)
                progress_str = f" 进度: {progress_match.group(1)}%" if progress_match else ""

                if "TosServerError" in log_text or "tos.exceptions" in log_text:
                    if log_callback:
                        log_callback("ERROR", "", "❌ 远程 TOS 模型文件不存在/拉取失败 (TosServerError)，自动跳过该模型", "vllm")
                    return False

                if "SSLError" in log_text or "Max retries exceeded" in log_text or "request timeout" in log_text:
                    tos_error_count += 1
                    if tos_error_count >= 15 and elapsed >= 600:
                        log_callback("ERROR", "", f"❌ 远程 TOS 模型权重网络下载超时/连接失败 (已重试 {elapsed}s)，自动跳过该模型", "vllm")
                        return False
                else:
                    tos_error_count = 0

                if attempt % 4 == 0:
                    if "Starting TOS model download" in log_text or "OSSModelLoader" in log_text or "downloading" in log_text.lower() or "extracting" in log_text.lower():
                        log_callback("INFO", "", f"  [TOS 模型拉取/解压中]{progress_str} | 已用: {elapsed}s | 正在传输解压大模型权重包...", "vllm")
                    else:
                        log_callback("INFO", "", f"  [{elapsed}s] 正在等待容器服务就绪 (端口 {port}, 状态: {status}){progress_str}...", "vllm")
            except Exception:
                log_callback("INFO", "", "  正在连通推理评估引擎...", "vllm")
        time.sleep(3)

    if log_callback:
        log_callback("WARNING", "", f"  vLLM 服务在 {int(time.time() - start_time)}s 内未响应就绪端口，自动跳过", "vllm")
    return False


# ============================================================
#  主流水线
# ============================================================

from sqlalchemy import select
from backend.models import ModelInfo


def _resolve_service_port(db: Session, model_slug: str, docker_cmd: str, config: dict) -> int:
    """推理服务端口解析优先级: docker 命令 --port > 模型 service_port > 任务配置 container_port > 8300
    （MIM 导入的模型无 --port 参数，依赖 service_port=25535）"""
    m = re.search(r'--port\s+(\d+)', docker_cmd or '')
    if m:
        return int(m.group(1))
    try:
        mi = db.execute(select(ModelInfo).where(ModelInfo.slug == model_slug)).scalar_one_or_none()
        if mi is not None and getattr(mi, "service_port", None):
            return int(mi.service_port)
    except Exception:
        pass
    return config.get("container_port", 8300)


def run_model_pipeline(db: Session, task_id: int, model_run: ModelRun, config: dict, log_callback):
    """执行单个模型的完整测试流水线"""

    def _check_stale():
        """阶段边界检查: 任务被取消、或流水线已被新一代取代(删除后重建)时立即退出"""
        from backend.services.task_manager import _cancel_flags, is_pipeline_stale
        if _cancel_flags.get(task_id, False) or is_pipeline_stale(task_id):
            raise InterruptedError("任务已取消或已被重建，旧流水线退出")

    # 获取设备
    task = model_run.task
    device = task.device if task else None
    runner = RemoteRunner(device)

    model_slug = model_run.model_slug
    docker_cmd = model_run.docker_command

    # 优先从 docker 命令中解析实际端口（兼容 llama-server --port 8080 等非标端口）
    port = _resolve_service_port(db, model_slug, docker_cmd, config)

    # 查验模型是否为已部署外部 API 接入模式
    # 统一判定口径：is_external 或 api_base 任一存在即视为外部 API（与 _get_model_api_config/task_manager 一致），
    # 否则只填了 api_base 而没开 is_external 的模型会被误当成容器部署而失败。
    model_info = db.execute(select(ModelInfo).where(ModelInfo.slug == model_slug)).scalar_one_or_none()
    is_external = model_info and bool(model_info.is_external or model_info.api_base)

    if is_external:
        api_target = model_info.api_base or f"http://{runner.api_host}:{port}/v1"
        log_callback("INFO", model_slug, f"========== 检测到【已在线/外部 API 接入服务】 ==========", "container")
        log_callback("INFO", model_slug, f"无需自动下发 Docker 部署，直接接入现存 API 地址: {api_target}", "container")
        model_run.stage_status["deploying"] = StageStatus.SKIPPED.value
        model_run.stage_status["validating"] = StageStatus.COMPLETED.value
        model_run.status = ModelStage.PERF_TESTING
        model_run.progress_detail = f"接入现存外部 API 服务 ({api_target})"
        model_run.progress = 20
        db.commit()
    else:
        # Stage 1: 部署容器
        log_callback("INFO", model_slug, f"========== 容器部署 [{runner.host_label}] ==========", "container")
        avail_disk_gb = runner.get_available_disk_gb()
        if avail_disk_gb < 30.0:
            err_msg = f"目标算力节点 [{runner.host_label}] 剩余可用磁盘空间仅有 {avail_disk_gb:.1f} GB (< 30 GB)！已被自动拦截以防止磁盘干爆系统崩溃。请清理磁盘空间后重试。"
            log_callback("ERROR", model_slug, err_msg, "container")
            model_run.stage_status["deploying"] = StageStatus.FAILED.value
            model_run.status = ModelStage.DONE
            model_run.completed_at = datetime.utcnow()
            db.commit()
            return
        log_callback("INFO", model_slug, f"磁盘空间检测通过：目标节点可用空间 {avail_disk_gb:.1f} GB (≥ 100 GB)", "container")

        log_callback("INFO", model_slug, "正在清理旧容器并等待 GPU 显存回收...", "container")
        _stop_container(runner, log_callback=log_callback)

        runner.current_model_slug = model_slug
        ok, container_id = _start_container(runner, docker_cmd, port, log_callback)
        if not ok:
            fail_detail = container_id or "容器启动失败，测试终止"
            log_callback("ERROR", model_slug, fail_detail, "container")
            model_run.stage_status["deploying"] = StageStatus.FAILED.value
            model_run.stage_status["validating"] = StageStatus.SKIPPED.value
            model_run.stage_status["gateway_testing"] = StageStatus.SKIPPED.value
            model_run.stage_status["perf_testing"] = StageStatus.SKIPPED.value
            model_run.stage_status["acc_testing"] = StageStatus.SKIPPED.value
            model_run.stage_status["reporting"] = StageStatus.SKIPPED.value
            model_run.status = ModelStage.FAILED.value
            model_run.progress = 100
            model_run.progress_detail = fail_detail
            model_run.completed_at = datetime.utcnow()
            db.commit()
            return

        # 邮件通知配置
        notify_email = config.get("notify_email") or (task.config.get("notify_email") if task and task.config else "")
        if notify_email:
            try:
                from backend.services.notifier import send_email_notification
                send_email_notification(
                    notify_email,
                    task.name if task else "模型测试任务",
                    model_run.model_name,
                    runner.host_label,
                    "RUNNING",
                    "测试流水线已初始化完成，开始执行评测"
                )
            except Exception:
                pass

        model_run.container_name = container_id[:12] if container_id else ""
        model_run.stage_status["deploying"] = StageStatus.COMPLETED.value
        model_run.status = ModelStage.VALIDATING
        model_run.progress = 10
        db.commit()

        # Stage 2: 等待 vLLM
        log_callback("INFO", model_slug, "========== vLLM 服务启动 ==========", "vllm")
        log_callback("INFO", model_slug, f"轮询 {runner.api_host}:{port} 等待推理服务就绪...", "vllm")
        if not _wait_for_vllm(runner, port, config.get("container_startup_timeout", 7200), log_callback, task_id=task_id):
            _save_container_logs_to_file(runner, task_id, model_slug)
            log_callback("ERROR", model_slug, "vLLM 启动超时，测试终止", "vllm")
            model_run.stage_status["validating"] = StageStatus.FAILED.value
            model_run.stage_status["gateway_testing"] = StageStatus.SKIPPED.value
            model_run.stage_status["perf_testing"] = StageStatus.SKIPPED.value
            model_run.stage_status["acc_testing"] = StageStatus.SKIPPED.value
            model_run.stage_status["reporting"] = StageStatus.SKIPPED.value
            model_run.status = ModelStage.FAILED.value
            model_run.progress = 100
            
            # 尝试提取容器最后的输出诊断最真实的原因
            clogs = runner.run_docker(["logs", "--tail", "20", f"aoni_benchmark_runner_t{task_id}_mr{model_run.id}"], timeout=3)
            log_txt = (clogs.stdout or "") + (clogs.stderr or "")
            if "out of memory" in log_txt.lower() or "oom" in log_txt.lower():
                detail_reason = "硬件显存不足 (CUDA Out of Memory)，请使用更小规模或量化版模型"
            elif "repo id must be in the form" in log_txt.lower():
                detail_reason = "模型加载路径格式校验报错，请核查容器配置"
            else:
                detail_reason = f"推理服务 {port} 端口未按时就绪 (详情见控制台日志)"

            model_run.progress_detail = detail_reason
            model_run.completed_at = datetime.utcnow()
            db.commit()
            _stop_container(runner, log_callback=log_callback)
            return

        model_run.stage_status["validating"] = StageStatus.COMPLETED.value
        model_run.progress = 20
        db.commit()

    # Stage 3: 网关协议与技能适配测试
    if config.get("gateway_enabled", True):
        _check_stale()
        model_run.status = ModelStage.GATEWAY_TESTING
        model_run.stage_status["gateway_testing"] = StageStatus.RUNNING.value
        db.commit()
        log_callback("INFO", model_slug, "========== 网关协议与技能适配测试 ==========", "gateway")
        _run_gateway_stage(db, model_run, config, log_callback, runner)
        model_run.stage_status["gateway_testing"] = StageStatus.COMPLETED.value
        model_run.progress = 40
        db.commit()

    # Stage 3.5: 功能测试 (质量专项: 大海捞针/数学/乱码/工具冒烟/Agent回归/多模态)
    feature_items = config.get("feature_items") or []
    if config.get("feature_enabled", False) and feature_items:
        _check_stale()
        model_run.status = ModelStage.FEATURE_TESTING
        model_run.stage_status["feature_testing"] = StageStatus.RUNNING.value
        db.commit()
        log_callback("INFO", model_slug, "========== 功能测试（质量专项） ==========", "feature")
        _run_feature_stage(db, model_run, config, log_callback, runner)
        model_run.stage_status["feature_testing"] = StageStatus.COMPLETED.value
        model_run.progress = 30
        db.commit()

    # Stage 4: 性能测试
    perf_failed = False
    if config.get("perf_enabled", True):
        _check_stale()
        model_run.status = ModelStage.PERF_TESTING
        model_run.stage_status["perf_testing"] = StageStatus.RUNNING.value
        db.commit()
        log_callback("INFO", model_slug, "========== 性能测试 ==========", "perf")
        perf_ok = _run_perf_stage(db, model_run, config, log_callback, runner)
        if not perf_ok:
            model_run.stage_status["perf_testing"] = StageStatus.FAILED.value
            model_run.status = ModelStage.FAILED
            db.commit()
            log_callback("ERROR", model_slug, "❌ 性能压测异常终止（吞吐全为 0），任务结束", "perf")
            return
        model_run.stage_status["perf_testing"] = StageStatus.COMPLETED.value
        model_run.progress = 70
        db.commit()

    # Stage 5: 准确率测试
    acc_datasets = config.get("acc_datasets") or []
    tool_call_tests = config.get("tool_call_tests") or []
    is_acc_enabled = bool(config.get("acc_enabled", False)) and (len(acc_datasets) > 0 or len(tool_call_tests) > 0)
    if is_acc_enabled:
        _check_stale()
        model_run.status = ModelStage.ACC_TESTING
        model_run.stage_status["acc_testing"] = StageStatus.RUNNING.value
        db.commit()
        log_callback("INFO", model_slug, "========== 准确率测试 ==========", "accuracy")
        _run_accuracy_stage(db, model_run, config, log_callback, runner)
        model_run.stage_status["acc_testing"] = StageStatus.COMPLETED.value
        model_run.progress = 90
        db.commit()
    else:
        model_run.stage_status["acc_testing"] = StageStatus.SKIPPED.value
        db.commit()

    # Stage 6: 完成
    model_run.status = ModelStage.DONE
    model_run.progress = 100
    model_run.completed_at = datetime.utcnow()
    db.commit()
    # 仅对容器部署模型执行容器清理；外部 API 模型无平台容器，不触碰本机 docker/端口/页缓存
    if not is_external:
        _stop_container(runner, log_callback=log_callback)
    log_callback("INFO", model_slug, "========== 测试完成 ==========", "system")


# ============================================================
#  网关协议与技能工具测试
# ============================================================

def _get_model_api_config(db: Session, model_slug: str, runner: RemoteRunner, port: int, default_model_name: str = "") -> dict:
    """获取模型的 API 端点配置信息（统一支持硬件容器部署模型与外部/在线 API 端点模型）"""
    model_info = db.execute(select(ModelInfo).where(ModelInfo.slug == model_slug)).scalar_one_or_none()
    is_external = bool(model_info and (model_info.is_external or model_info.api_base))

    if is_external and model_info.api_base:
        base_clean = model_info.api_base.strip().rstrip("/")
        if base_clean.endswith("/v1"):
            base_url = base_clean[:-3]
            v1_url = base_clean
            chat_url = f"{base_clean}/chat/completions"
            models_url = f"{base_clean}/models"
        else:
            base_url = base_clean
            v1_url = f"{base_clean}/v1"
            chat_url = f"{base_clean}/v1/chat/completions"
            models_url = f"{base_clean}/v1/models"
        api_key = model_info.api_key or "EMPTY"
        model_name = model_info.model_endpoint_name or default_model_name or model_slug
    else:
        base_url = f"http://{runner.api_host}:{port}"
        v1_url = f"http://{runner.api_host}:{port}/v1"
        chat_url = f"http://{runner.api_host}:{port}/v1/chat/completions"
        models_url = f"http://{runner.api_host}:{port}/v1/models"
        api_key = "EMPTY"
        model_name = default_model_name or model_slug

    return {
        "is_external": is_external,
        "base_url": base_url,
        "v1_url": v1_url,
        "chat_url": chat_url,
        "models_url": models_url,
        "api_key": api_key,
        "model_name": model_name,
    }


def _resolve_verified_model_id(api_cfg: dict, fallback_name: str, log_callback=None, slug: str = "") -> str:
    """在下发网关与性能压测请求前，先连接 /v1/models 准确获取服务端真正注册的模型 ID"""
    import requests
    models_url = api_cfg.get("models_url", "")
    api_key = api_cfg.get("api_key", "EMPTY")
    headers = {}
    if api_key and api_key != "EMPTY":
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        r = requests.get(models_url, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and "data" in data and len(data["data"]) > 0:
                served_ids = [m.get("id") for m in data["data"] if m.get("id")]
                if not served_ids:
                    return fallback_name
                # 多模型网关: 优先精确匹配/包含期望名 (大小写不敏感), 避免误选第一个
                fn = (fallback_name or "").strip()
                if fn:
                    matched = next((sid for sid in served_ids if sid == fn), None) \
                        or next((sid for sid in served_ids if fn.lower() == sid.lower()), None) \
                        or next((sid for sid in served_ids if fn.lower() in sid.lower()), None)
                    if matched:
                        served_id = matched
                    else:
                        if len(served_ids) == 1:
                            served_id = served_ids[0]
                        else:
                            if log_callback:
                                log_callback("WARNING", slug, f"  [Model ID Guard] 多模型网关未匹配到 '{fn}'，使用第一个: '{served_ids[0]}'", "container")
                            served_id = served_ids[0]
                else:
                    served_id = served_ids[0]
                if log_callback:
                    log_callback("INFO", slug, f"  [Model ID Guard] 服务端模型 ID 校验成功: '{served_id}'", "container")
                return served_id
    except Exception as e:
        if log_callback:
            log_callback("WARNING", slug, f"  [Model ID Guard] 模型 ID 预检异常 ({e})，使用回退 ID. '{fallback_name}'", "container")
    return fallback_name


def _run_gateway_stage(db: Session, model_run: ModelRun, config: dict, log_callback, runner: RemoteRunner):
    """在目标推理节点或外部 API 上跑网关与协议兼容性测试"""
    from backend.services.gateway_validator import GatewayValidator

    # 清理旧的网关测试记录
    db.query(GatewayResult).filter_by(model_run_id=model_run.id).delete()
    db.commit()

    model_slug = model_run.model_slug
    port = _resolve_service_port(db, model_slug, model_run.docker_command, config)

    api_cfg = _get_model_api_config(db, model_slug, runner, port, model_run.model_name)
    base_url = api_cfg["base_url"]
    api_key = api_cfg["api_key"]

    protocols = config.get("gateway_protocols", ["openai", "anthropic", "responses"])
    test_longctx = bool(config.get("test_longctx", False))

    if not protocols:
        log_callback("INFO", model_slug, "未勾选任何 API 校验协议，已自动跳过 API 协议规范校验阶段", "gateway")
        return

    verified_model_name = _resolve_verified_model_id(api_cfg, api_cfg["model_name"], log_callback, model_slug)
    validator = GatewayValidator(base_url, verified_model_name, api_key=api_key)
    results = validator.run_all_checks(protocols=protocols, test_longctx=test_longctx, log_callback=log_callback)

    for item in results:
        res_obj = GatewayResult(
            model_run_id=model_run.id,
            category=item.get("category", "protocol"),
            test_item=item.get("test_item", ""),
            protocol=item.get("protocol", "system"),
            status=item.get("status", "SKIP"),
            latency_ms=item.get("latency_ms"),
            message=item.get("message", ""),
            raw_details=item.get("raw_details")
        )
        db.add(res_obj)

    db.commit()


def _run_feature_stage(db: Session, model_run: ModelRun, config: dict, log_callback, runner: RemoteRunner):
    """功能测试阶段: 逐项运行勾选的质量专项 (后端节点直接 HTTP 打推理端点)"""
    from backend.services.features import ITEMS
    from backend.models import FeatureResult

    # 清理旧的功能测试记录
    db.query(FeatureResult).filter_by(model_run_id=model_run.id).delete()
    db.commit()

    model_slug = model_run.model_slug
    port = _resolve_service_port(db, model_slug, model_run.docker_command, config)

    api_cfg = _get_model_api_config(db, model_slug, runner, port, model_run.model_name)
    base_url = api_cfg["base_url"]
    api_key = api_cfg["api_key"]

    feature_items = config.get("feature_items") or []
    if not feature_items:
        log_callback("INFO", model_slug, "未勾选任何功能测试项，跳过功能测试阶段", "feature")
        return

    log_callback("INFO", model_slug, f"功能测试项: {', '.join(feature_items)}", "feature")

    verified_model_name = _resolve_verified_model_id(api_cfg, api_cfg["model_name"], log_callback, model_slug)

    for key in feature_items:
        item = ITEMS.get(key)
        if not item:
            log_callback("WARNING", model_slug, f"未知功能测试项: {key}，跳过", "feature")
            continue
        log_callback("INFO", model_slug, f"── 功能测试: {item['name']} ──", "feature")
        try:
            result = item["module"].run(
                base_url, verified_model_name,
                api_key=api_key, options=config.get("feature_options") or {},
                log_callback=log_callback,
            )
        except Exception as e:
            log_callback("ERROR", model_slug, f"功能测试 {item['name']} 执行异常: {e}", "feature")
            result = {
                "category": "feature",
                "feature_key": key,
                "test_item": item["name"],
                "status": "FAIL",
                "latency_ms": None,
                "message": f"执行异常: {e}",
                "raw_details": {},
            }
        log_callback("INFO", model_slug,
                      f"功能测试 [{result.get('test_item')}] 结果: {result.get('status')} — {result.get('message')}",
                      "feature")
        res_obj = FeatureResult(
            model_run_id=model_run.id,
            category=result.get("category", "feature"),
            feature_key=result.get("feature_key", key),
            test_item=result.get("test_item", key),
            status=result.get("status", "SKIP"),
            latency_ms=result.get("latency_ms"),
            message=result.get("message", ""),
            raw_details=result.get("raw_details"),
        )
        db.add(res_obj)
        db.commit()


# ============================================================
#  性能测试
# ============================================================

def _clip_round_lens(raw_input_len, raw_output_lens, max_model_len):
    """按 max_model_len 自适应裁剪单个输入及其可用输出长度列表。"""
    eff_input = raw_input_len
    # 动态自适应剪裁：仅当用例 input 真正逼近上下文上限时才收缩
    if eff_input >= max_model_len - 512:
        eff_input = max(128, int(max_model_len * 0.40))
    # 尊重显式配置的输出长度：仅当 input+output 真正超过上下文时才截断，
    # 仅预留少量余量(512 tokens)给停止符/结束符，不再强制保留 20% 余量
    # （避免外部 API / 大上下文模型的长输出被无谓砍短）
    safe_output_limit = max(64, max_model_len - eff_input - 512)
    clipped = sorted(list(set(min(out_l, safe_output_limit) for out_l in raw_output_lens if out_l > 0)))
    if not clipped:
        clipped = [safe_output_limit]
    return eff_input, clipped


def _parse_input_lens_field(rd: dict):
    """解析输入 Token 多值字符串；为空/非法则回退单值 input_len（旧任务兼容）。

    逐个 token 解析：单个非法值（如手误）仅被忽略，不影响其余合法值。
    """
    raw = rd.get("input_lens_str")
    vals = []
    if raw:
        for tok in str(raw).split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                vals.append(int(float(tok)))
            except (TypeError, ValueError):
                continue
    if not vals:
        try:
            vals = [int(rd.get("input_len"))]
        except (TypeError, ValueError):
            vals = []
    return sorted(list(set(v for v in vals if v > 0)))


def _expand_perf_rounds(rounds_config, max_model_len, size_category, log_callback=None, model_slug=""):
    """把任务配置的压测轮次展开为逐项执行列表（输入 Token 多值 × 输出长度 × 并发梯度）。

    返回 (parsed_rounds, total_steps)；同一配置轮次下的多个输入共享 round_num/请求数/并发/输出。
    """
    parsed_rounds = []
    total_steps = 0
    round_idx = 0
    for rd in rounds_config:
        input_lens = _parse_input_lens_field(rd)
        if not input_lens:
            if log_callback:
                log_callback("WARNING", model_slug,
                             f"  ⚠ 压测轮次输入 Token 非法 ({rd.get('input_lens_str') or rd.get('input_len')!r})，跳过该轮次", "perf")
            continue
        try:
            num_prompts = int(rd.get("num_prompts"))
        except (TypeError, ValueError):
            if log_callback:
                log_callback("WARNING", model_slug,
                             f"  ⚠ 压测轮次 num_prompts 非法 ({rd.get('num_prompts')!r})，跳过该轮次", "perf")
            continue
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
                concurrencies = get_concurrency_for_category(size_category)
        else:
            concurrencies = get_concurrency_for_category(size_category)

        round_idx += 1
        for _il in input_lens:
            _eff_il, _clipped_out = _clip_round_lens(_il, output_lens, max_model_len)
            parsed_rounds.append({
                "round_num": round_idx, "input_len": _eff_il, "num_prompts": num_prompts,
                "output_lens": _clipped_out, "concurrencies": concurrencies,
            })
            total_steps += len(_clipped_out) * len(concurrencies)

    if total_steps == 0:
        total_steps = 1
    return parsed_rounds, total_steps


def _run_perf_stage(db: Session, model_run: ModelRun, config: dict, log_callback, runner: RemoteRunner):
    # 优先从 docker 命令中解析实际端口（兼容 llama-server --port 8080 / MIM service_port 等非标端口）
    port = _resolve_service_port(db, model_run.model_slug, model_run.docker_command or '', config)

    # 模型最大上下文长度 (tokens)，优先级：
    #   1) 模型配置 max_model_len（外部 API 接入必填；容器部署可显式覆盖）
    #   2) docker 启动命令 --max-model-len
    #   3) 默认 4096
    max_model_len = 4096
    try:
        _mi = db.execute(select(ModelInfo).where(ModelInfo.slug == model_run.model_slug)).scalar_one_or_none()
    except Exception:
        _mi = None
    if _mi and _mi.max_model_len:
        max_model_len = int(_mi.max_model_len)
    elif model_run.docker_command:
        m_len = re.search(r"--max-model-len\s+(\d+)", model_run.docker_command)
        if m_len:
            max_model_len = int(m_len.group(1))

    _pm_ov = (config.get("per_model_config") or {}).get(model_run.model_slug) or {}
    _pm_rounds = _pm_ov.get("perf_rounds_config") if isinstance(_pm_ov, dict) else None
    if isinstance(_pm_rounds, list) and _pm_rounds:
        rounds_config = _pm_rounds
    else:
        rounds_config = config.get("perf_rounds_config", [])

    if not rounds_config:
        # 根据模型的 max_model_len 智能构建 5 档上下文压测矩阵 (从 128 到 128K)
        candidate_inputs = [128, 1024, 4096, 16384, 65536, 131072]
        usable_inputs = [inp for inp in candidate_inputs if inp < max_model_len * 0.85]
        if not usable_inputs:
            usable_inputs = [max(128, int(max_model_len * 0.5))]

        rounds_config = []
        for inp in usable_inputs:
            out_len = 128 if inp <= 128 else (512 if inp <= 1024 else (2048 if inp <= 4096 else (4096 if inp <= 16384 else 8192)))
            conc_str = "1,4,8,16" if inp <= 1024 else ("1,4,8" if inp <= 4096 else "1,2,4")
            rounds_config.append({
                "input_len": inp,
                "output_lens_str": str(out_len),
                "concurrencies_str": conc_str,
                "num_prompts": 100 if inp <= 4096 else 20
            })

    api_cfg = _get_model_api_config(db, model_run.model_slug, runner, port, model_run.model_name)
    is_external = api_cfg["is_external"]
    is_llama_cpp = "llama-server" in (model_run.docker_command or "") or "llama_cpp" in (model_run.docker_command or "")

    if is_external:
        vllm_model_name = _resolve_verified_model_id(api_cfg, api_cfg["model_name"], log_callback, model_run.model_slug)
        use_fallback = True
    else:
        m = re.search(r"-e MODEL_NAME=([^ \n\\]+)", model_run.docker_command or "")
        fallback_id = m.group(1).strip() if m else model_run.model_name
        vllm_model_name = _resolve_verified_model_id(api_cfg, fallback_id, log_callback, model_run.model_slug)
        use_fallback = is_llama_cpp or not _check_vllm_bench(runner)

    # 任务级显式选择压测框架，覆盖自动判定：auto(默认) / custom / native；模型级覆盖优先
    task_cfg = (model_run.task.config or {}) if getattr(model_run, "task", None) else {}
    _pm = (task_cfg.get("per_model_config") or {}).get(model_run.model_slug) or {}
    if isinstance(_pm, dict) and _pm.get("benchmark_framework"):
        bench_framework = _pm.get("benchmark_framework")
    else:
        bench_framework = task_cfg.get("benchmark_framework", "auto")
    if bench_framework == "custom":
        if not use_fallback:
            log_callback("INFO", model_run.model_slug, "  ⚙ 已选择【自定义 HTTP 压测】", "perf")
        use_fallback = True
    elif bench_framework == "native":
        if is_external:
            log_callback("WARNING", model_run.model_slug,
                         "  ⚠ 选择了原生压测，但为外部 API 模型（无法在容器内跑 vllm bench），改用自定义 HTTP 压测", "perf")
            use_fallback = True
        elif is_llama_cpp:
            log_callback("WARNING", model_run.model_slug,
                         "  ⚠ 选择了原生压测，但为 GGUF(llama.cpp) 模型（不支持 vLLM bench），改用自定义 HTTP 压测", "perf")
            use_fallback = True
        elif not _check_vllm_bench(runner):
            log_callback("WARNING", model_run.model_slug,
                         "  ⚠ 选择了原生压测，但容器内无可用 vllm bench，改用自定义 HTTP 压测", "perf")
            use_fallback = True
        else:
            log_callback("INFO", model_run.model_slug, "  ⚙ 已选择【原生 vLLM 压测】", "perf")
            use_fallback = False

    # 预先计算并解析总压测项数（跳过未填写完整的/非法的轮次，避免脏数据导致流水线崩溃）
    # 输入 Token 支持逗号多值，与输出长度、并发梯度做笛卡尔积；
    # 旧任务仅有单值 input_len，或无 input_lens_str 时自动回退，保持兼容。
    parsed_rounds, total_steps = _expand_perf_rounds(
        rounds_config, max_model_len, model_run.size_category or "small_medium",
        log_callback=log_callback, model_slug=model_run.model_slug,
    )

    perf_start_time = time.time()
    completed_steps = 0
    valid_perf_count = 0
    consecutive_zero_count = 0

    log_callback("INFO", model_run.model_slug,
                 f"性能测试启动: 共 {total_steps} 项压测组合 | 开始时间: {datetime.now().strftime('%H:%M:%S')}", "perf")

    for pr in parsed_rounds:
        round_num = pr["round_num"]
        input_len = pr["input_len"]
        num_prompts = pr["num_prompts"]
        output_lens = pr["output_lens"]
        concurrencies = pr["concurrencies"]

        for output_len in output_lens:
            output_type = "short" if output_len <= 128 else "long"
            strategy_id = f"{model_run.model_slug}_round{round_num}_{output_type}"

            for concurrency in concurrencies:
                # 压测项之间检查取消/代际，防止删除任务后流水线继续跑完剩余压测项
                from backend.services.task_manager import _cancel_flags, is_pipeline_stale
                if _cancel_flags.get(model_run.task_id, False) or is_pipeline_stale(model_run.task_id):
                    raise InterruptedError("任务已取消或已被重建，旧流水线退出")

                elapsed_sec = time.time() - perf_start_time
                if completed_steps > 0:
                    avg_step_sec = elapsed_sec / completed_steps
                    eta_sec = (total_steps - completed_steps) * avg_step_sec
                    eta_str = _format_duration(eta_sec)
                else:
                    eta_str = "计算中..."
                elapsed_str = _format_duration(elapsed_sec)

                model_run.progress = 20 + int(40 * (completed_steps / total_steps))
                model_run.progress_detail = f"性能测试 ({completed_steps}/{total_steps}) | 已用: {elapsed_str} | 预计剩余: {eta_str} | 当前: c={concurrency}, output={output_len}"
                db.commit()

                log_callback("INFO", model_run.model_slug,
                             f"  性能测试 [{completed_steps + 1}/{total_steps}]: c={concurrency}, output={output_len} (已用 {elapsed_str}, 预计剩余 {eta_str})", "perf")

                # 暂停检查: 被暂停时阻塞等待，恢复后继续下一项压测
                _wait_if_paused(model_run.task_id)
                if use_fallback or is_external:
                    bench_cmd_preview = f"vllm bench serve --host {api_cfg['chat_url']} --dataset-name random --random-input-len {input_len} --random-output-len {output_len} --num-prompts {num_prompts} --max-concurrency {concurrency} --request-rate inf"
                    log_callback("INFO", model_run.model_slug,
                                 f"  ⚡ 原生压测指令: {bench_cmd_preview}", "perf")
                    log_callback("INFO", model_run.model_slug,
                                 f"  HTTP 连通性压测: {api_cfg['chat_url']}", "perf")
                    result = _run_http_benchmark(runner, port, concurrency, input_len, output_len, num_prompts, vllm_model_name, api_cfg=api_cfg, log_callback=log_callback, model_slug=model_run.model_slug)
                else:
                    result = _run_vllm_bench_single(runner, port, concurrency, input_len, output_len, num_prompts, vllm_model_name, log_callback)
                    if result and result.get("error") == "native_bench_unavailable":
                        log_callback("WARNING", model_run.model_slug,
                                     "  ⚠ 原生 bench 在当前容器不可用，回退到自定义 HTTP 压测", "perf")
                        result = _run_http_benchmark(runner, port, concurrency, input_len, output_len, num_prompts, vllm_model_name, api_cfg=None, log_callback=log_callback, model_slug=model_run.model_slug)

                completed_steps += 1
                elapsed_sec = time.time() - perf_start_time
                avg_step_sec = elapsed_sec / completed_steps
                eta_sec = (total_steps - completed_steps) * avg_step_sec
                eta_str = _format_duration(eta_sec)
                elapsed_str = _format_duration(elapsed_sec)

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

                    tps = result.get("output_throughput", 0) or 0
                    tps_val = float(tps) if isinstance(tps, (int, float)) else 0.0
                    model_run.progress = 20 + int(40 * (completed_steps / total_steps))
                    model_run.progress_detail = f"性能测试 ({completed_steps}/{total_steps}) | 已用: {elapsed_str} | 预计剩余: {eta_str} | 最新吞吐: {tps_val:.1f} tok/s"
                    db.commit()

                    if err:
                        log_callback("ERROR", model_run.model_slug,
                                     f"    c={concurrency}, output={output_len}: 失败 - {err}", "perf")
                    else:
                        # 只有拿到正数吞吐才算有效结果
                        if tps_val > 0:
                            valid_perf_count += 1
                            consecutive_zero_count = 0
                        else:
                            consecutive_zero_count += 1
                        ttft = result.get("mean_ttft_ms", 0) or 0
                        tpot = result.get("mean_tpot_ms", 0) or 0
                        ttft_val = float(ttft) if isinstance(ttft, (int, float)) else 0.0
                        tpot_val = float(tpot) if isinstance(tpot, (int, float)) else 0.0
                        log_callback("INFO", model_run.model_slug,
                                     f"    └─ 结果: 吞吐={tps_val:.1f} tok/s, TTFT={ttft_val:.1f}ms, TPOT={tpot_val:.1f}ms | 进度 ({completed_steps}/{total_steps}) 预计剩余: {eta_str}", "perf")
                        raw = result.get("raw_report")
                        if raw and isinstance(raw, dict):
                            completed = raw.get("completed", "?")
                            failed = raw.get("failed", "?")
                            duration = raw.get("duration", 0)
                            log_callback("INFO", model_run.model_slug,
                                         f"    完成={completed}/{completed+failed}, 耗时={duration:.1f}s" if isinstance(duration, float) else f"    完成={completed}/{completed+failed}", "perf")

                # ── 熔断: 开头连续 2 项吞吐为 0/空 → 判定压测环境异常，立即终止 ──
                if consecutive_zero_count >= 2 and completed_steps <= 2:
                    log_callback("ERROR", model_run.model_slug,
                                 f"❌ 连续 {consecutive_zero_count} 项压测吞吐为 0（压测环境异常或结果文件无法回传），"
                                 f"终止性能测试避免无效等待。请检查: 1) 容器内 vllm bench 是否可用 2) 远程设备结果文件回传 (scp) 是否正常 3) 模型服务是否正常响应", "perf")
                    return False

    if valid_perf_count == 0:
        log_callback("ERROR", model_run.model_slug, "❌ 性能压测未能获取到任何有效吞吐数据，阶段判定为失败", "perf")
        return False

    return True


# 每个容器探测到的可用原生压测入口做缓存，避免对每个组合重复探测。
# key: (device id | local, CONTAINER_NAME)；value: (sub_cmd_list, kind) 或 None
_BENCH_CMD_CACHE: dict = {}
_BENCH_CMD_CACHE_LOCK = threading.Lock()


def _probe_bench_cmd(runner: RemoteRunner):
    """探测容器内真实可用的原生压测入口，返回 (入口命令子列表, 种类) 或 None。

    探测结果会被缓存。顺序:
      1. 新版 vllm 的 `vllm bench serve`（当前 aarch64 nightly 用的入口，输出含 ITL）
      2. 旧版 vllm 的 `python3 -m vllm.entrypoints.openai.bench_serving`

    注意：GPU 繁忙时 docker exec 启动子进程可能较慢，因此加大探测超时，
    避免把"探测超时"误判为"无 vllm bench"而错误回退到低效的 HTTP 压测。
    """
    cache_key = (id(runner.device) if runner.device else "local", CONTAINER_NAME)
    with _BENCH_CMD_CACHE_LOCK:
        if cache_key in _BENCH_CMD_CACHE:
            return _BENCH_CMD_CACHE[cache_key]

    checks = [
        (["vllm", "bench", "serve"], "vllm_bench"),
        (["python3", "-m", "vllm.entrypoints.openai.bench_serving"], "legacy_serving"),
    ]
    result = None
    for sub, kind in checks:
        try:
            res1 = runner.run_docker(["exec", CONTAINER_NAME] + sub + ["--help"], timeout=30)
            if res1 and res1.returncode == 0:
                result = (sub, kind)
                break
        except Exception:
            continue
        time.sleep(0.2)

    with _BENCH_CMD_CACHE_LOCK:
        _BENCH_CMD_CACHE[cache_key] = result
    return result


def _check_vllm_bench(runner: RemoteRunner) -> bool:
    """检查容器内是否有 vllm 原生基准测试工具 (支持多种 vllm 入口)。"""
    return _probe_bench_cmd(runner) is not None


def _run_vllm_bench_single(runner: RemoteRunner, port, concurrency, input_len, output_len,
                           num_prompts, model_name, log_callback=None) -> dict | None:
    """调用容器内可用的原生 vllm bench 压测工具（自动适配新版/旧版入口），实时打字机刷出完整 Shell 压测命令"""
    import os as _os

    probed = _probe_bench_cmd(runner)
    if probed is None:
        if log_callback:
            log_callback("WARNING", "", f"  ⚠ [{runner.host_label}] 容器内未探测到可用的原生 vllm bench，本组合将按自定义 HTTP 压测兜底", "perf")
        return {"concurrency": concurrency, "error": "native_bench_unavailable"}

    bench_sub, bench_kind = probed
    result_dir = "/tmp/vllm_bench_results"
    cmd = (["sudo", "docker", "exec", CONTAINER_NAME] + bench_sub +
           ["--host", "127.0.0.1", "--port", str(port),
            "--dataset-name", "random",
            "--random-input-len", str(input_len),
            "--random-output-len", str(output_len),
            "--num-prompts", str(num_prompts),
            "--max-concurrency", str(concurrency),
            "--request-rate", "inf", "--ignore-eos",
            "--save-result",
            "--result-dir", result_dir])

    raw_cmd_str = f"{' '.join(bench_sub)} --host 127.0.0.1 --port {port} --dataset-name random --random-input-len {input_len} --random-output-len {output_len} --num-prompts {num_prompts} --max-concurrency {concurrency} --request-rate inf"
    bench_display = "vllm bench serve" if bench_kind == "vllm_bench" else "bench_serving(旧版入口)"

    if log_callback:
        log_callback("INFO", "", f"  ⚡ [{runner.host_label}] 执行原生压测({bench_display}):\n  ➜ {raw_cmd_str}", "perf")

    # 重要修复: 每次压测前清空共享结果目录，保证只看到本次的结果文件
    # (避免按 mtime 误读上一次组合的残留 JSON)
    host_dir = "/tmp/vllm_bench_host"
    subprocess.run(["mkdir", "-p", host_dir], capture_output=True)
    for _f in Path(host_dir).glob("*.json"):
        try:
            _f.unlink()
        except OSError:
            pass
    # 清空容器内的压测结果目录
    try:
        runner.run_shell(f"sudo docker exec {CONTAINER_NAME} sh -c 'rm -rf {result_dir}/* 2>/dev/null || true'", timeout=30)
    except Exception:
        pass

    try:
        res = runner.run(cmd, timeout=1800)

        # 记录全量原生压测控制台 Raw 输出 (DEBUG 级别供高档全量调试模式查看)
        if log_callback and res.stdout:
            for line in res.stdout.strip().split("\n"):
                if line.strip():
                    log_callback("DEBUG", "", f"  [vLLM Bench Raw] {line.strip()[:300]}", "perf")

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

        # 修复: 按组合匹配读取 JSON，不只看 mtime
        # 优先按文件名（含 concurrency）匹配，并校验 max_concurrency 与本次目标一致
        host_path = Path(host_dir)
        json_files = list(host_path.glob("*.json"))
        raw_report = None

        def _pick_report(file):
            try:
                with open(file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None

        if json_files:
            # 1) 优先找文件名里包含本次并发数的
            target = f"concurrency{concurrency}"
            for f in json_files:
                if target in f.name:
                    cand = _pick_report(f)
                    if cand is not None:
                        raw_report = cand
                        break
            # 2) 备用：校验 JSON 内部 max_concurrency 匹配
            if raw_report is None:
                for f in sorted(json_files, key=lambda p: p.stat().st_mtime, reverse=True):
                    cand = _pick_report(f)
                    if cand is None:
                        continue
                    mc = cand.get("max_concurrency")
                    if mc is not None and int(mc) == int(concurrency):
                        raw_report = cand
                        break
                    # 允许但不支持直接配对回论过爬，不再用不匹配的
            # 3) 如果按并发找不到，不复用更早的残留，返回无数据导致本组合失败
            if raw_report is None:
                log_callback("WARNING", "", f"  ⚠ 本组合 (c={concurrency},输出={output_len}) 未找到匹配的压测结果文件，不复用旧数据", "perf")

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
                        num_prompts, model_name, api_cfg: dict = None,
                        log_callback=None, model_slug: str = "") -> dict | None:
    """HTTP API 压测（fallback / 外部 API 端点）— aiohttp 异步并发版。

    参考 model-testing-tool 的异步实现：用 asyncio + Semaphore 控并发，
    逐 token 记录 TTFT / ITL，并用 usage.completion_tokens 取精确输出 token 数。

    兼容推理模型：token 到达判定同时识别 content / reasoning / reasoning_content / tool_calls
    （vLLM 官方 benchmark 亦把 reasoning 与 content 一并计入生成 token）。对只发 content
    的普通模型行为不变；对推理模型额外记录首答案 token 延迟与 reasoning 占比（仅日志/返回，
    不新增 DB 列）。
    """
    import asyncio
    import aiohttp

    if api_cfg:
        url = api_cfg["chat_url"]
        ping_url = api_cfg["models_url"]
        api_key = api_cfg["api_key"]
    else:
        url = f"http://{runner.api_host}:{port}/v1/chat/completions"
        ping_url = f"http://{runner.api_host}:{port}/v1/models"
        api_key = "EMPTY"

    headers = {"Content-Type": "application/json"}
    if api_key and api_key != "EMPTY":
        headers["Authorization"] = f"Bearer {api_key}"

    def _err_dict(err_msg, err_key="error"):
        return {
            "concurrency": concurrency,
            err_key: err_msg,
            "request_throughput": 0.0,
            "output_throughput": 0.0,
            "mean_ttft_ms": 0.0,
            "median_ttft_ms": 0.0,
            "p99_ttft_ms": 0.0,
            "mean_tpot_ms": 0.0,
            "median_tpot_ms": 0.0,
            "p99_tpot_ms": 0.0,
            "mean_itl_ms": 0.0,
            "median_itl_ms": 0.0,
            "p99_itl_ms": 0.0,
        }

    # 1. 快速检查端口连通性，并动态尝试获取实际注册的服务模型名称（aiohttp 异步）
    try:
        async def _ping():
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession() as s:
                async with s.get(ping_url, headers=headers, timeout=timeout) as resp:
                    if resp.status == 200:
                        d = await resp.json()
                        data = d.get("data") or []
                        if data and data[0].get("id"):
                            return data[0]["id"]
            return None
        served = asyncio.run(_ping())
        if served:
            model_name = served
    except Exception:
        # 无法 ping 通也尝试直接压（由 send 阶段兜底报错）
        pass

    # 生成与 input_len 匹配的输入：按目标 token 数近似构造
    word_count = max(1, input_len)
    parts = []
    for i in range(word_count):
        parts.append(str(i % 10000) if i % 17 == 0 else "hello")
    prompt_text = " ".join(parts)

    # 宽松超时：输出越长给越多时间（含慢模型）
    timeout_sec = max(300, int(output_len * 0.20) + 60)
    client_timeout = aiohttp.ClientTimeout(total=timeout_sec)

    async def _send(session, sem):
        async with sem:
            payload = {
                "model": model_name,
                "messages": [{"role": "user", "content": prompt_text}],
                "max_tokens": output_len, "temperature": 0,
                "stream": True, "stream_options": {"include_usage": True},
            }
            st = time.perf_counter()
            token_ts = []
            first_content_ts = None
            usage_tokens = 0
            usage_reasoning_tokens = 0
            reason_chunks = 0
            content_chunks = 0
            try:
                async with session.post(url, json=payload, headers=headers,
                                        timeout=client_timeout) as resp:
                    if resp.status != 200:
                        body = (await resp.text())[:120]
                        return {"success": False, "error_msg": f"HTTP {resp.status}: {body}"}
                    async for line_bytes in resp.content:
                        line = line_bytes.decode("utf-8").strip()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data: "):
                            continue
                        part = line[6:].strip()
                        if part in ("[DONE]", ""):
                            break
                        try:
                            chunk = json.loads(part)
                        except Exception:
                            continue
                        now = time.perf_counter()
                        if chunk.get("usage"):
                            _usage = chunk["usage"] or {}
                            usage_tokens = _usage.get("completion_tokens") or 0
                            _details = _usage.get("completion_tokens_details") or {}
                            usage_reasoning_tokens = _details.get("reasoning_tokens") or 0
                        choices = chunk.get("choices") or []
                        if choices:
                            delta = choices[0].get("delta") or {}
                            # 兼容推理模型：content / reasoning / reasoning_content / tool_calls
                            # 任一非空即视为一次 token 到达（每 chunk 只记一次，避免双计）。
                            # 空字符串（如开头 role chunk）仍视为无 token，与旧行为一致。
                            _has_content = bool(delta.get("content"))
                            _has_reasoning = bool(delta.get("reasoning") or delta.get("reasoning_content"))
                            _has_tool = bool(delta.get("tool_calls"))
                            if _has_content or _has_reasoning or _has_tool:
                                token_ts.append(now)
                                if _has_reasoning:
                                    reason_chunks += 1
                                elif _has_content:
                                    content_chunks += 1
                                if _has_content and first_content_ts is None:
                                    first_content_ts = now
                    if not token_ts:
                        return {"success": False, "error_msg": "未收到任何输出 token"}
                    n = len(token_ts)
                    ttft = token_ts[0] - st
                    # 首答案 token 延迟（推理模型：首个 content token 到达；普通模型等于 ttft）
                    ttft_answer = (first_content_ts - st) if first_content_ts is not None else None
                    latency = token_ts[-1] - st
                    # 逐 token 到达间隔 ITL
                    itl_vals = [token_ts[i] - token_ts[i - 1] for i in range(1, n)] if n > 1 else []
                    itl_mean = (sum(itl_vals) / len(itl_vals)) if itl_vals else 0.0
                    # TPOT = (端到端 − TTFT) ÷ (输出token数 − 1)
                    tpot = ((latency - ttft) / (n - 1)) if n > 1 else 0.0
                    return {"success": True, "error_msg": "",
                            "ttft": ttft, "ttft_answer": ttft_answer, "itl": itl_mean, "itl_vals": itl_vals,
                            "tpot": tpot,
                            "reasoning_tokens": usage_reasoning_tokens,
                            "reason_chunks": reason_chunks, "content_chunks": content_chunks,
                            "output_tokens": usage_tokens if usage_tokens > 0 else n}
            except Exception as err:
                return {"success": False, "error_msg": str(err)}

    async def _main():
        connector = aiohttp.TCPConnector(limit=max(1, concurrency) + 10)
        sem = asyncio.Semaphore(max(1, concurrency))
        async with aiohttp.ClientSession(connector=connector, timeout=client_timeout) as session:
            tasks = [_send(session, sem) for _ in range(max(1, num_prompts))]
            return await asyncio.gather(*tasks, return_exceptions=True)

    t0 = time.time()
    try:
        results = asyncio.run(_main())
    except Exception as e:
        return _err_dict(f"目标模型 API 端点 ({url}) 无法连接: {e}", err_key="error")

    results = [r for r in results if isinstance(r, dict)]
    total_time = time.time() - t0

    successes = [r for r in results if r.get("success")]
    if not successes:
        first_err = results[0].get("error_msg") if results else "未收到响应"
        return _err_dict(f"目标模型 API 服务未正常响应: {first_err}")

    def _pq(vals, q):
        vals = sorted(vals)
        i = min(int(len(vals) * q), len(vals) - 1)
        return vals[i]

    ttfts = [r["ttft"] for r in successes]
    tpots = [r["tpot"] for r in successes]
    itls = [r["itl"] for r in successes]
    total_out = sum(r.get("output_tokens", 0) for r in successes)
    total_reasoning = sum(r.get("reasoning_tokens", 0) or 0 for r in successes)
    total_reason_chunks = sum(r.get("reason_chunks", 0) or 0 for r in successes)
    total_content_chunks = sum(r.get("content_chunks", 0) or 0 for r in successes)
    _ans_ttfts = [r["ttft_answer"] for r in successes if r.get("ttft_answer") is not None]
    mean_ttft_answer_ms = (sum(_ans_ttfts) / len(_ans_ttfts)) * 1000 if _ans_ttfts else None

    # 推理模型可观测性：仅当确实出现 reasoning 时记录一次（对普通模型不打印，行为不变）
    if log_callback and (total_reasoning > 0 or total_reason_chunks > 0):
        if total_reasoning > 0:
            _rdesc = f"reasoning 约 {total_reasoning} ({total_reasoning / total_out * 100:.0f}%)" if total_out else f"reasoning 约 {total_reasoning}"
        else:
            _tot_chunks = total_reason_chunks + total_content_chunks
            _pct = (total_reason_chunks / _tot_chunks * 100) if _tot_chunks else 0.0
            _rdesc = f"reasoning 段占比约 {_pct:.0f}%（服务端未返回 reasoning token 明细）"
        _ans_msg = f"{mean_ttft_answer_ms:.0f} ms" if mean_ttft_answer_ms is not None else "未产出答案 token（输出预算被思考耗尽）"
        log_callback("INFO", model_slug,
                     f"  [推理模型] 本组合生成 {total_out} tokens，其中 {_rdesc}；"
                     f"首生成 token {sum(ttfts)/len(ttfts)*1000:.0f} ms，首答案 token {_ans_msg} "
                     f"(c={concurrency}, output={output_len})", "perf")

    return {
        "concurrency": concurrency,
        "request_throughput": len(successes) / total_time,
        "output_throughput": total_out / total_time,
        "mean_ttft_ms": (sum(ttfts) / len(ttfts)) * 1000,
        "median_ttft_ms": _pq(ttfts, 0.5) * 1000,
        "p99_ttft_ms": _pq(ttfts, 0.99) * 1000,
        "mean_ttft_answer_ms": mean_ttft_answer_ms,
        "reasoning_tokens": total_reasoning,
        "mean_tpot_ms": (sum(tpots) / len(tpots)) * 1000,
        "median_tpot_ms": _pq(tpots, 0.5) * 1000,
        "p99_tpot_ms": _pq(tpots, 0.99) * 1000,
        "mean_itl_ms": (sum(itls) / len(itls)) * 1000,
        "median_itl_ms": _pq(itls, 0.5) * 1000,
        "p99_itl_ms": _pq(itls, 0.99) * 1000,
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
#  准确率测试 (100% 真实样本测评 & evalscope 自动补全)
# ============================================================

def _get_evalscope_bin() -> str:
    """获取 evalscope 可执行文件的有效绝对路径，避免由于 PATH 未包含 ~/.local/bin 导致的 FileNotFoundError"""
    import shutil
    found = shutil.which("evalscope")
    if found:
        return found
    local_bin = os.path.expanduser("~/.local/bin/evalscope")
    if os.path.exists(local_bin):
        return local_bin
    py_bin = str(Path(sys.executable).parent / "evalscope")
    if os.path.exists(py_bin):
        return py_bin
    return "evalscope"


def _ensure_evalscope(runner: RemoteRunner, log_callback, model_slug: str, is_external: bool = False) -> bool:
    """自动检测并静默安装 evalscope 评测工具包及全套依赖，确保压测节点就绪"""
    log_callback("INFO", model_slug, "正在检查评测节点上的 evalscope 评测工具链环境...", "accuracy")
    try:
        if runner.is_remote and not is_external:
            res = runner.run_shell("which evalscope || test -f ~/.local/bin/evalscope || python3 -m pip show evalscope", timeout=15)
            if res.returncode == 0:
                log_callback("INFO", model_slug, "✅ 目标节点已就绪 evalscope 真实评测环境", "accuracy")
                return True
        else:
            eval_bin = _get_evalscope_bin()
            try:
                import sklearn
                has_sklearn = True
            except ImportError:
                has_sklearn = False

            if (os.path.exists(eval_bin) or shutil.which("evalscope")) and has_sklearn:
                log_callback("INFO", model_slug, "✅ 平台评测引擎已就绪 evalscope 真实评测环境", "accuracy")
                return True
    except Exception:
        pass

    log_callback("INFO", model_slug, "⚡ 评测节点未检测到 evalscope 或全套评测依赖，正在自动补全安装...", "accuracy")
    try:
        if runner.is_remote and not is_external:
            res = runner.run_shell("pip install evalscope scikit-learn", timeout=600)
            if res.returncode == 0:
                log_callback("INFO", model_slug, "✅ evalscope 评测工具及依赖已成功自动安装至远端压测节点！", "accuracy")
                return True
        else:
            res = subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "evalscope", "scikit-learn"], capture_output=True, text=True, timeout=600)
            if res.returncode == 0:
                log_callback("INFO", model_slug, "✅ evalscope 评测工具及依赖已成功自动安装至平台节点！", "accuracy")
                return True
            else:
                log_callback("WARNING", model_slug, f"evalscope 自动安装日志: {res.stderr or res.stdout}", "accuracy")
    except Exception as install_err:
        log_callback("WARNING", model_slug, f"自动安装 evalscope 过程异常: {install_err}", "accuracy")

    return False


def _log_evalscope_details(work_dir: Path, log_callback, model_slug: str):
    """解析 evalscope 生成的 predictions 和 reviews 报告，输出到 DEBUG 日志供用户查看详细题目与模型回答"""
    try:
        review_files = sorted(work_dir.glob("**/reviews/**/*.jsonl"))
        pred_files = sorted(work_dir.glob("**/predictions/**/*.jsonl"))
        if not review_files:
            return

        pred_map = {}
        for pf in pred_files:
            for line in pf.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    idx = data.get("index")
                    out = data.get("model_output")
                    ans_text = ""
                    if isinstance(out, dict):
                        choices = out.get("choices", [])
                        if choices and isinstance(choices[0], dict):
                            msg = choices[0].get("message", {})
                            ans_text = msg.get("content", "")
                    elif isinstance(out, str):
                        ans_text = out
                    pred_map[(pf.stem, idx)] = ans_text
                except Exception:
                    pass

        log_callback("DEBUG", model_slug, f"========== 准确率评测【题目与模型回答明细】(共 {len(review_files)} 个数据集) ==========", "accuracy")
        for rf in review_files:
            ds_name = rf.stem
            lines = rf.read_text(encoding="utf-8", errors="ignore").splitlines()
            log_callback("DEBUG", model_slug, f"--- [数据集 {ds_name.upper()}] 题目明细 (共 {len(lines)} 题) ---", "accuracy")
            for line in lines:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    idx = data.get("index")
                    target = data.get("target", "")
                    msgs = data.get("messages", [])
                    q_text = ""
                    if msgs and isinstance(msgs[-1], dict):
                        q_text = msgs[-1].get("content", "").replace("\n", " ").strip()
                    if len(q_text) > 120:
                        q_text = q_text[:120] + "..."

                    sample_score = data.get("sample_score") or {}
                    score_info = sample_score.get("score") or {}
                    extracted_pred = score_info.get("extracted_prediction") or ""
                    val_info = score_info.get("value") or {}
                    acc_val = val_info.get("acc")
                    if acc_val is not None:
                        is_correct = (float(acc_val) == 1.0)
                        status_str = "PASS (对)" if is_correct else "FAIL (错)"
                    else:
                        status_str = "PASS (对)" if (extracted_pred and extracted_pred == target) else "FAIL (错)"

                    log_callback("DEBUG", model_slug,
                                 f"  [DEBUG 明细] [{ds_name.upper()} 题 #{idx}] 题目: {q_text} | 标准答案: [{target}] | 模型选项: [{extracted_pred or '未提取'}] | 结果: [{status_str}] | 模型推理: [{ans_text}]", "accuracy")
                except Exception:
                    pass
    except Exception:
        pass


# 数据集级准确率特性表 (按 EvalScope 数据集名匹配)。
# - subset_override: 固定子集。LiveCodeBench 列了 28 个相互重叠的 release，若照默认全跑会重复计数。
# - agent: AgentAdapter 类基准，每题一个容器，需低并发 + 放宽空闲 watchdog + 透传 extra_params。
# - sandbox: 代码类基准，需 Docker 沙箱执行，避免在宿主机直接跑模型生成代码。
# - max_tokens: 覆盖默认生成上限 (难基准/推理模型需要更大预算)。
ACC_DATASET_SPECS: dict = {
    "live_code_bench": {
        "subset_override": ["release_v6"],
        "sandbox": True,
        "max_tokens": 4096,
    },
    "humaneval_plus": {"sandbox": True, "max_tokens": 4096},
    "mbpp_plus": {"sandbox": True, "max_tokens": 4096},
    "terminal_bench_v2_1": {
        "agent": True,
        "exec": "remote",
        "batch_size": 1,
        "idle_timeout": 1800,
        "max_tokens": 32768,
        "extra_params": {
            "environment_type": "docker",
            "agent_name": "terminus-2",
            "max_turns": 200,
            "timeout_multiplier": 3.0,
        },
        # Qwen3.8 系推理模型：关闭 thinking，避免 reasoning 吃掉 JSON 指令预算
        # 并提升对 terminus-2 “[analysis/plan/commands] JSON” 协议格式的遵循度
        "gen_extra": {
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        },
    },
    "swe_bench_verified_mini_agentic": {
        "agent": True,
        "exec": "remote",
        "batch_size": 1,
        "idle_timeout": 1800,
        "max_tokens": 4096,
        "extra_params": {
            "build_docker_images": True,
            "pull_remote_images_if_available": True,
        },
        "agent_config": {"mode": "native", "max_steps": 60, "command_timeout": 60.0},
    },
    # 纯 API 工具调用(模拟)，本机即可运行
    "bfcl_v4": {
        "batch_size": 4,
        "max_tokens": 4096,
        "subset_override": [
            "simple_python", "simple_java", "simple_javascript",
            "multiple", "parallel", "parallel_multiple", "irrelevance",
            "live_simple", "live_multiple", "live_parallel",
            "live_parallel_multiple", "live_irrelevance",
            "multi_turn_base", "multi_turn_miss_func",
            "multi_turn_miss_param", "multi_turn_long_context",
        ],
        "extra_params": {"is_fc_model": True, "underscore_to_dot": True},
    },
    "tau2_bench": {
        "batch_size": 4,
        "idle_timeout": 1200,
        "max_tokens": 4096,
        "subset_override": ["airline", "retail"],
        "user_sim": True,
    },
    "hle": {"max_tokens": 8192, "judge": True, "extra_params": {"include_multi_modal": False}},
    "arc_agi_2": {"max_tokens": 8192},
    "hmmt25": {"max_tokens": 8192},
}


def _preheat_accuracy_assets(sampling_plan, log_callback, model_slug: str, workers: int = 4, task_id: int = 0):
    """后台预热：并行预取数据集与容器镜像，减少正式评测时的等待。

    尽力而为：任何子项失败都只记录日志，绝不阻塞或影响正式评测。
    - 数据集：对注册表中带 ModelScope/HF 仓库标识的文本集调用 snapshot 下载预热。
    - SWE-bench：先取实例清单，再并行 docker pull 对应 arm64 镜像。
    - Terminal-Bench：镜像由 Harbor 按任务构建，这里不预拉（仅提示）。
    """
    import concurrent.futures as _cf
    import threading as _threading
    try:
        workers = max(int(workers), 1)
    except (TypeError, ValueError):
        workers = 4

    # 关键：后台线程写入日志必须使用独立 session，绝不能复用主流水线的 db session
    # （SQLAlchemy Session 非线程安全，并发写同一 session 会导致 task_logs 主键冲突并污染主流水线）。
    _log_lock = _threading.Lock()

    def _plog(level: str, msg: str):
        with _log_lock:
            try:
                from backend.database import session_factory
                from backend.services.task_manager import _add_log
                with session_factory() as sdb:
                    _add_log(sdb, task_id, level, model_slug, msg, "accuracy")
            except Exception:
                pass

    def _registry_dataset_id(mapped: str):
        try:
            from evalscope.api.registry import BENCHMARK_REGISTRY
            m = BENCHMARK_REGISTRY.get(mapped)
            return getattr(m, "dataset_id", None)
        except Exception:
            return None

    def _warm_dataset(item):
        name = item["ds"]
        mapped = item["mapped"]
        ds_id = _registry_dataset_id(mapped)
        if not ds_id or str(ds_id).startswith("http"):
            return  # 由各自框架在线获取（Harbor / HF），跳过
        try:
            from modelscope import snapshot_download as _ms_snap
            _ms_snap(str(ds_id), repo_type="dataset")
            _plog("INFO", f"  [预热] 数据集 {name} ({ds_id}) 已就绪")
        except Exception as e:
            _plog("WARNING", f"  [预热] 数据集 {name} 预取跳过: {str(e)[:90]}")

    def _pull_swe_images(item):
        if item["mapped"] != "swe_bench_verified_mini_agentic":
            return
        per = item.get("per_subset") or 0
        n = per if per > 0 else 50
        ids = []
        try:
            from modelscope import MsDataset
            ds = MsDataset.load("evalscope/swe-bench-verified-mini", split="test")
            ids = [r.get("instance_id") for r in ds if r.get("instance_id")][:n]
        except Exception as e:
            _plog("WARNING", f"  [预热] SWE 实例清单获取失败，跳过镜像预拉: {str(e)[:90]}")
            return
        if not ids:
            return
        try:
            from evalscope.benchmarks.swe_bench.utils import get_remote_docker_image_from_id
        except Exception:
            return

        def _pull_one(iid):
            try:
                img = get_remote_docker_image_from_id(iid, "swebench", "")
                r = subprocess.run(["docker", "pull", img], capture_output=True, text=True, timeout=1800)
                return (iid, img, r.returncode == 0)
            except Exception:
                return (iid, "", False)

        ok = 0
        with _cf.ThreadPoolExecutor(max_workers=min(workers, 4)) as ex:
            for iid, img, success in ex.map(_pull_one, ids):
                if success:
                    ok += 1
        _plog("INFO", f"  [预热] SWE-bench 镜像预拉完成: {ok}/{len(ids)} 成功")

    try:
        with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
            futures = []
            for item in (sampling_plan or []):
                futures.append(ex.submit(
                    _pull_swe_images if item["mapped"] == "swe_bench_verified_mini_agentic" else _warm_dataset,
                    item,
                ))
            for f in futures:
                try:
                    f.result()
                except Exception:
                    pass
    except Exception as e:
        _plog("WARNING", f"  [预热] 任务执行异常（忽略）: {str(e)[:90]}")


def _configured_acc_datasets(config: dict) -> list:
    """按配置顺序返回准确率评测涉及的平台数据集名（acc_datasets + tool_call_tests）。"""
    ds_list = list(config.get("acc_datasets") or [])
    for _t in (config.get("tool_call_tests") or []):
        if _t not in ds_list:
            ds_list.append(_t)
    return ds_list


def _finalize_acc_progress_detail(db: Session, model_run: ModelRun, config: dict, acc_start_time=None, elapsed_override=None):
    """按数据库中已落库的 AccResult 权威重建准确率汇总文本。

    断点续跑会跳过已有成绩的数据集；若汇总只统计本轮新评的数据集，就会漏掉这些数据集
    （曾导致 "准确率测试 (5/5)" 却缺 GSM8K 的显示问题）。这里以 DB 为准重建，保证完整、顺序一致。
    仅显示有效成绩，不写入「跳过/超时/失败/终止」等字眼（这些子串会被任务的失败判定误伤）。
    """
    ds_list = _configured_acc_datasets(config)
    rows = db.query(AccResult).filter_by(model_run_id=model_run.id).all()
    by = {}
    for r in rows:
        by[r.dataset.lower()] = r
        by[r.dataset.lower().replace("_", "").replace("-", "")] = r

    total = 0
    done = 0
    parts = []
    seen = set()
    for d in ds_list:
        dl = d.lower()
        if dl in seen:
            continue
        seen.add(dl)
        r = by.get(dl) or by.get(dl.replace("_", "").replace("-", ""))
        if r is None:
            continue
        total += 1
        if r.accuracy is not None:
            done += 1
            parts.append(f"{d.upper()}: {r.accuracy:.2%}")

    _start = acc_start_time
    if _start is None and getattr(model_run, "started_at", None) is not None:
        try:
            _start = model_run.started_at.timestamp()
        except Exception:
            _start = None
    if elapsed_override is not None:
        elapsed_str = elapsed_override
    else:
        elapsed_str = _format_duration(time.time() - _start) if _start else ""

    tail = " | ".join(parts) if parts else "暂无有效成绩"
    model_run.progress_detail = f"准确率测试 ({done}/{total}) | 已用: {elapsed_str} | 结果: {tail}"
    try:
        model_run.progress = 60 + int(30 * (done / max(total, 1)))
    except Exception:
        pass


def _run_accuracy_stage(db: Session, model_run: ModelRun, config: dict, log_callback, runner: RemoteRunner):
    port = _resolve_service_port(db, model_run.model_slug, model_run.docker_command or '', config)
    datasets = list(config.get("acc_datasets") or [])
    for _t in (config.get("tool_call_tests") or []):
        if _t not in datasets:
            datasets.append(_t)
    if not datasets:
        log_callback("INFO", model_run.model_slug, "未指定任何准确率评测数据集，已自动跳过准确率评测阶段", "accuracy")
        return

    # 评测执行节点 (公共)：Terminal/SWE 等需 x86 容器的工具调用集在此远程节点执行
    node_ip = ""
    node_runner = None
    try:
        from backend.models import PlatformSetting
        _row = db.get(PlatformSetting, "eval_node_ip")
        node_ip = (_row.value or "").strip() if _row else ""
        if node_ip:
            from backend.routers.eval_tools import build_eval_node_runner
            node_runner = build_eval_node_runner(node_ip)
    except Exception as _ne:
        log_callback("WARNING", model_run.model_slug, f"评测执行节点初始化失败: {_ne}", "accuracy")

    # 查验数据库中该 ModelRun 已保存且有效的 AccResult 记录（实现断点增量续跑）
    existing_accs = db.query(AccResult).filter_by(model_run_id=model_run.id).all()
    already_done_ds = {}
    for r in existing_accs:
        if r.accuracy is not None:
            already_done_ds[r.dataset.lower()] = r.accuracy
            already_done_ds[r.dataset.lower().replace("_", "").replace("-", "")] = r.accuracy

    to_eval_datasets = []
    resumed_ordered = []  # (数据集名, 成绩)：本轮因已有成绩而跳过，但仍需计入汇总
    for d in datasets:
        d_clean = d.lower().replace("_", "").replace("-", "")
        if d.lower() in already_done_ds or d_clean in already_done_ds:
            acc_val = already_done_ds.get(d.lower(), already_done_ds.get(d_clean))
            acc_str = f"{acc_val:.2%}" if isinstance(acc_val, float) else str(acc_val)
            resumed_ordered.append((d.upper(), acc_val))
            log_callback("INFO", model_run.model_slug, f"  ⏩ [断点续跑] 数据集 {d.upper()} 已存在历史完成成绩 ({acc_str})，自动跳过重复测试", "accuracy")
        else:
            to_eval_datasets.append(d)

    if not to_eval_datasets:
        log_callback("INFO", model_run.model_slug, f"✅ 所有配置数据集 ({len(datasets)}个) 均已具备测试成绩，断点增量续跑完成！", "accuracy")
        _finalize_acc_progress_detail(db, model_run, config)
        db.commit()
        return

    def _resolve_ds_limit(ds_name: str) -> int:
        """数据集级抽样上限：优先 acc_dataset_limits，其次回退全局 acc_limit；0 表示全量。"""
        m = config.get("acc_dataset_limits") or {}
        v = m.get(ds_name)
        if v is None:
            v = m.get(ds_name.lower())
        if v is None:
            v = config.get("acc_limit", 200)
        if v is None:
            v = 0
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    default_limit = config.get("acc_limit", 200)
    if default_limit is None:
        default_limit = 0

    default_batch = config.get("acc_batch_size", 2)
    if default_batch is None:
        default_batch = 2
    try:
        default_batch = int(default_batch)
    except (TypeError, ValueError):
        default_batch = 2
    batch_map = config.get("acc_dataset_batch_size") or {}

    acc_start_time = time.time()
    api_cfg = _get_model_api_config(db, model_run.model_slug, runner, port, model_run.model_name)

    # 第一步：自动检查并自动安装 evalscope 工具链 (外部 API 模式直接使用本地平台引擎)
    _ensure_evalscope(runner, log_callback, model_run.model_slug, is_external=api_cfg.get("is_external", False))

    api_url = api_cfg["v1_url"]
    api_key = api_cfg["api_key"]
    eval_model_name = api_cfg["model_name"]
    # 校正为服务端真实注册的模型 ID (容器部署场景 model_name 可能是带空格的显示名, 直接调用会 404)
    eval_model_name = _resolve_verified_model_id(api_cfg, eval_model_name, log_callback, model_run.model_slug)

    work_dir = DATA_DIR / "evalscope_reports" / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_t{model_run.task_id}_mr{model_run.id}"
    work_dir.mkdir(parents=True, exist_ok=True)

    # 数据集别名映射 (对齐 EvalScope 内置 benchmark 规范名称)
    dataset_alias_map = {
        "gpqa": "gpqa_diamond",
        "math500": "math_500",
        "longbench_pro": "longbench_v2",
    }
    try:
        from evalscope.api.registry import BENCHMARK_REGISTRY
        valid_registry_keys = set(BENCHMARK_REGISTRY.keys())
    except Exception:
        valid_registry_keys = None

    normalized = []  # (平台数据集名, EvalScope 数据集名)
    for d in to_eval_datasets:
        mapped = dataset_alias_map.get(d.lower(), d.lower())
        if valid_registry_keys is not None:
            if mapped in valid_registry_keys:
                normalized.append((d, mapped))
            elif d.lower() in valid_registry_keys:
                normalized.append((d, d.lower()))
            else:
                log_callback("WARNING", model_run.model_slug, f"数据集 '{d}' 未在 EvalScope 基准库中注册，已自动跳过该项", "accuracy")
        else:
            normalized.append((d, mapped))

    evalscope_bin = _get_evalscope_bin()

    # 从 config/.env 读取代理配置，透传给 evalscope 子进程 (下载 HF 数据集需要)
    eval_env = os.environ.copy()
    local_bin_dir = os.path.expanduser("~/.local/bin")
    if local_bin_dir not in eval_env.get("PATH", ""):
        eval_env["PATH"] = f"{local_bin_dir}:{eval_env.get('PATH', '')}"

    if "HF_ENDPOINT" not in eval_env:
        eval_env["HF_ENDPOINT"] = "https://hf-mirror.org"

    # 注入网络抗抖动自动重试配置，彻底解决大文件 (如 LongBench 465MB) 在线下载途中断连报错问题
    eval_env["DATASETS_MAX_RETRIES"] = "10"
    eval_env["MODELSCOPE_MAX_RETRIES"] = "10"
    eval_env["HTTP_RETRIES"] = "10"
    eval_env["REQUESTS_MAX_RETRIES"] = "10"
    eval_env["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

    # 注入 BigCodeBench 代码安全执行与沙盒支持
    eval_env["EVALSCOPE_ALLOW_CODE_EXECUTION"] = "true"
    eval_env["EVALSCOPE_USE_SANDBOX"] = "true"
    eval_env["BIGCODEBENCH_ALLOW_CODE_EXECUTION"] = "1"

    for key in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"):
        if not eval_env.get(key):
            from backend.config import load_dotenv
            load_dotenv(Path(__file__).resolve().parent.parent.parent / "config" / ".env")
            val = os.getenv(key, "")
            if val:
                eval_env[key] = val

    # 为本地/内网模型 API 端点及 ModelScope 社区配置 NO_PROXY 直连保护，避免被 HTTP 代理拦截超时/SSL握手错误
    no_proxy_defaults = "127.0.0.1,localhost,10.0.0.0/8,192.168.0.0/16,172.16.0.0/12,0.0.0.0,modelscope.cn,www.modelscope.cn,api.modelscope.cn"
    existing_no_proxy = eval_env.get("NO_PROXY") or eval_env.get("no_proxy") or ""
    eval_env["NO_PROXY"] = f"{no_proxy_defaults},{existing_no_proxy}".rstrip(",")
    eval_env["no_proxy"] = eval_env["NO_PROXY"]

    # 关键修复: httpx (openai SDK) 不支持 socks:// scheme, 构造客户端时直接抛
    # "Unknown scheme for proxy URL" 导致 200 样本瞬间全失败 (无成绩生成)。
    # 被测 API 端点为本地/内网 (已被 NO_PROXY 覆盖), 剔除无效的 socks 代理即可。
    for _proxy_key in ("ALL_PROXY", "all_proxy"):
        _proxy_val = (eval_env.get(_proxy_key) or "").strip()
        if _proxy_val.startswith("socks://"):
            eval_env.pop(_proxy_key, None)

    # ========== 每数据集独立采样计划 ==========
    # evalscope 的 --limit 是"每子集"上限 (evalscope 源码 evaluator.py: "--limit applies per subset")，
    # 而 longbench_v2(3子集)/ceval(52子集) 等是多子集数据集，直接透传 --limit=N 会变成"每个子集 N 题"：
    # 子集题数 < N 时等于全量跑，子集多时题量爆炸 (52×N)。修复：每个数据集单独跑一次 evalscope，
    # 按该数据集实际子集数拆算 per-subset limit，使每数据集总量 ≈ acc_limit；
    # 并过滤会超出模型上下文的超长子集 (如 longbench_v2 的 long 子集文档可达 2M token)，避免必然 400。
    sampling_plan = []
    for orig, d in normalized:
        spec = ACC_DATASET_SPECS.get(d, {})
        ds_limit = _resolve_ds_limit(orig)
        meta = BENCHMARK_REGISTRY.get(d) if valid_registry_keys else None
        subsets = list(meta.subset_list) if (meta and getattr(meta, 'subset_list', None)) else []
        if spec.get("subset_override"):
            subsets = list(spec["subset_override"])
        elif d == "longbench_v2" and subsets:
            safe = [s for s in subsets if s != "long"]
            if safe:
                subsets = safe
        num_subsets = max(len(subsets), 1)
        per_subset = 0
        if ds_limit > 0:
            per_subset = (int(ds_limit) + num_subsets - 1) // num_subsets
        try:
            batch_size = int(spec.get("batch_size") or batch_map.get(orig, batch_map.get(d, default_batch)) or default_batch)
        except (TypeError, ValueError):
            batch_size = default_batch
        batch_size = max(batch_size, 1)
        sampling_plan.append({
            "ds": orig, "mapped": d, "subsets": subsets, "num_subsets": num_subsets,
            "per_subset": per_subset, "limit": ds_limit, "batch_size": batch_size,
            "spec": spec, "exec": spec.get("exec", "local"),
        })

    if default_limit > 0:
        limit_desc = f"抽样模式 默认 limit={default_limit}/数据集 (可按数据集覆盖)"
    else:
        limit_desc = "全量题库不限上限评测"
    log_callback("INFO", model_run.model_slug, f"准确率评测计划 ({limit_desc})", "accuracy")

    # 后台并行预热数据集与镜像（不阻塞评测；失败仅记日志）
    if config.get("acc_preheat", True) and sampling_plan:
        try:
            _ph_workers = int(config.get("acc_preheat_workers", 4) or 4)
            threading.Thread(
                target=_preheat_accuracy_assets,
                args=(sampling_plan, log_callback, model_run.model_slug, _ph_workers, model_run.task_id),
                daemon=True,
            ).start()
            log_callback("INFO", model_run.model_slug,
                         f"  [预热] 已在后台并行预取数据集与容器镜像（workers={_ph_workers}，不阻塞评测）", "accuracy")
        except Exception as _pe:
            log_callback("WARNING", model_run.model_slug, f"  [预热] 启动失败（忽略）: {_pe}", "accuracy")

    def _extract_acc(ds_name, metrics):
        mapped_ds = dataset_alias_map.get(ds_name.lower(), ds_name.lower())
        ds_clean = ds_name.lower().replace("_", "").replace("-", "")
        mapped_clean = mapped_ds.replace("_", "").replace("-", "")
        for k, v in metrics.items():
            k_clean = k.lower().replace("_", "").replace("-", "")
            if (ds_name.lower() in k.lower() or mapped_ds in k.lower() or
                ds_clean in k_clean or mapped_clean in k_clean) and "accuracy" in k.lower():
                try:
                    return float(v)
                except (ValueError, TypeError):
                    return None
        return None

    def _run_evalscope_one(ds_item, cur_ds_idx, total_ds, ds_work_dir, remote_runner=None):
        """运行单数据集 evalscope (含实时监控线程)，返回 returncode"""
        mapped = ds_item["mapped"]
        spec = ds_item.get("spec") or {}
        ds_log_file = ds_work_dir / "evalscope_stdout.log"
        with open(ds_log_file, "w") as f:
            f.write("")

        # 按数据集自适应 max_tokens：数学/推理类(AIME/GPQA/Math/LongBench等)需要足够 token
        # 让模型推理完并输出 \boxed{}/最终答案，否则被截断后 extract 只能从残缺文本抓"最后一个
        # 数字"导致 AIME 等评分全 0；普通选择题保持较小上限以节省时间。
        # 难基准(HLE/ARC-AGI-2/HMMT)与 Agent 类通过 ACC_DATASET_SPECS.max_tokens 覆盖。
        ds_lower = (ds_item["ds"] + " " + mapped).lower()
        reasoning_bytes = any(
            kw in ds_lower
            for kw in ("aime", "gpqa", "math", "olympiad", "minerva", "longbench",
                       "bigcodebench", "humaneval", "mbpp", "code", "gsm8k", "bbh",
                       "hle", "mmlu_pro", "arc_agi", "hmmt", "musr", "zebralogic",
                       "imo", "scicode", "livecode", "terminal", "swe_bench", "tau", "gaia", "bfcl")
        )
        max_tokens = int(spec.get("max_tokens") or (4096 if reasoning_bytes else 1024))
        gen_dict = {"temperature": 0.0, "max_tokens": max_tokens, "do_sample": False, "timeout": 300}
        # 数据集级生成参数覆盖/补充（如 terminus-2 需要关闭 thinking 以稳定输出 JSON 指令）
        _gen_extra = spec.get("gen_extra")
        if isinstance(_gen_extra, dict):
            gen_dict.update(_gen_extra)
        gen_config = json.dumps(gen_dict)
        log_callback("DEBUG", model_run.model_slug,
                     f"  数据集 {mapped} 生成上限 max_tokens={max_tokens}（推理类自动放宽以避免截断丢分）", "accuracy")

        single_cmd = [evalscope_bin, "eval", "--model", eval_model_name,
                      "--eval-type", "openai_api", "--api-url", api_url,
                      "--api-key", api_key, "--datasets", mapped,
                      "--generation-config", gen_config,
                      "--eval-batch-size", str(ds_item.get("batch_size", 8)),
                      "--ignore-errors",
                      "--work-dir", str(ds_work_dir)]
        if ds_item["per_subset"] > 0:
            single_cmd.extend(["--limit", str(ds_item["per_subset"])])
        if spec.get("sandbox"):
            # 代码类基准：在 Docker 沙箱内执行模型生成的代码，避免污染宿主机
            single_cmd.extend(["--sandbox", json.dumps({"enabled": True, "engine": "docker"})])
        ds_args = {}
        if ds_item["subsets"]:
            ds_args["subset_list"] = ds_item["subsets"]
        _extra = dict(spec.get("extra_params") or {})
        if spec.get("user_sim"):
            # τ²-bench：用被测模型自身作为"模拟用户"，保证两模型口径一致
            _extra.update({"user_model": eval_model_name, "api_key": api_key, "api_base": api_url})
        if _extra:
            ds_args["extra_params"] = _extra
        if ds_args:
            single_cmd.extend(["--dataset-args", json.dumps({mapped: ds_args})])
        if spec.get("judge"):
            # HLE 等使用 LLM judge 评分：用被测模型自身作为裁判（两模型口径一致，公平可比）
            single_cmd.extend([
                "--judge-model-args",
                json.dumps({"api_url": api_url, "api_key": api_key,
                            "model_id": eval_model_name, "eval_type": "openai_api"}),
                "--judge-worker-num", "2",
            ])
        if spec.get("agent_config"):
            single_cmd.extend(["--agent-config", json.dumps(spec["agent_config"])])

        ds_desc = f"每子集≤{ds_item['per_subset']}×{ds_item['num_subsets']}子集" if ds_item["per_subset"] > 0 else "全量"
        log_callback("INFO", model_run.model_slug,
                     f"  评测指令: evalscope eval --datasets {mapped} b={ds_item.get('batch_size')} "
                     f"{'(沙箱)' if spec.get('sandbox') else ''}{'(agent)' if spec.get('agent') else ''} "
                     f"({ds_desc}) [{cur_ds_idx+1}/{total_ds}]", "accuracy")
        log_callback("INFO", model_run.model_slug, f"  API 端点: {api_url}", "accuracy")

        if remote_runner is not None and ds_item.get("exec") == "remote":
            return _remote_exec_one(single_cmd, ds_item, ds_work_dir, remote_runner)

        proc = subprocess.Popen(
            single_cmd,
            stdout=open(ds_log_file, "w"),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            env=eval_env,
        )

        stop_flag = threading.Event()
        progress_state = {"pct": None}
        logged_detail_keys = set()

        def _mt_log(level, slug, msg, module="accuracy"):
            try:
                from backend.database import session_factory
                from backend.services.task_manager import _add_log
                with session_factory() as sdb:
                    _add_log(sdb, model_run.task_id, level, slug, msg, module)
            except Exception:
                pass

        def _poll_realtime_details():
            try:
                review_files = sorted(ds_work_dir.glob("**/reviews/**/*.jsonl"))
                if not review_files:
                    return
                pred_map = {}
                pred_files = sorted(ds_work_dir.glob("**/predictions/**/*.jsonl"))
                for pf in pred_files:
                    for line in pf.read_text(encoding="utf-8", errors="ignore").splitlines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            idx_ = data.get("index")
                            out = data.get("model_output")
                            ans_text = ""
                            if isinstance(out, dict):
                                choices = out.get("choices", [])
                                if choices and isinstance(choices[0], dict):
                                    ans_text = choices[0].get("message", {}).get("content", "")
                            elif isinstance(out, str):
                                ans_text = out
                            pred_map[(pf.stem, idx_)] = ans_text
                        except Exception:
                            pass
                emitted = 0
                for rf in review_files:
                    if emitted >= 30:
                        break
                    ds_name = rf.stem
                    for line in rf.read_text(encoding="utf-8", errors="ignore").splitlines():
                        if emitted >= 30 or not line.strip():
                            break
                        try:
                            data = json.loads(line)
                            idx_ = data.get("index")
                            key = (ds_name, idx_)
                            if key in logged_detail_keys:
                                continue
                            ans_text = pred_map.get(key)
                            if ans_text is None:
                                continue
                            logged_detail_keys.add(key)
                            target = data.get("target", "")
                            msgs = data.get("messages", [])
                            q_text = msgs[-1].get("content", "").replace("\n", " ").strip() if msgs and isinstance(msgs[-1], dict) else ""
                            if len(q_text) > 120:
                                q_text = q_text[:120] + "..."
                            sample_score = data.get("sample_score") or {}
                            score_info = sample_score.get("score") or {}
                            extracted_pred = score_info.get("extracted_prediction") or ""
                            acc_val = (score_info.get("value") or {}).get("acc")
                            if acc_val is not None:
                                status_str = "PASS (对)" if float(acc_val) == 1.0 else "FAIL (错)"
                            else:
                                status_str = "PASS (对)" if (extracted_pred and extracted_pred == target) else "FAIL (错)"
                            ans_brief = ans_text.replace("\n", " ").strip()
                            if len(ans_brief) > 100:
                                ans_brief = ans_brief[:100] + "..."
                            _mt_log("DEBUG", model_run.model_slug,
                                    f"  [DEBUG 明细] [{ds_name.upper()} 题 #{idx_}] 题目: {q_text} | 标准答案: [{target}] | 模型选项: [{extracted_pred or '未提取'}] | 结果: [{status_str}] | 模型推理: [{ans_brief}]", "accuracy")
                            emitted += 1
                        except Exception:
                            pass
            except Exception:
                pass

        def _monitor_progress():
            from backend.database import session_factory
            last_file_pos = 0
            last_heartbeat = time.time()
            last_activity_time = time.time()
            err_500_count = [0]
            while not stop_flag.is_set():
                try:
                    if ds_log_file.exists():
                        with open(ds_log_file, "r", encoding="utf-8", errors="ignore") as f:
                            f.seek(last_file_pos)
                            new_lines = f.readlines()
                            last_file_pos = f.tell()
                        if new_lines:
                            last_activity_time = time.time()
                        for raw_line in new_lines:
                            line = raw_line.strip()
                            if not line:
                                continue
                            if any(k in line.lower() for k in ("evaluating", "loading", "downloading", "accuracy", "score", "metric", "pass", "dataset", "completed")):
                                m = re.search(r"Evaluating\[(\w+)\]:?\s*(\d+)%", line)
                                if m:
                                    progress_state["pct"] = int(m.group(2))
                                _mt_log("INFO", model_run.model_slug, f"  [EvalScope] {line[:250]}", "accuracy")
                            if "error code: 500" in line.lower() or "500. retrying" in line.lower():
                                err_500_count[0] += 1
                                if err_500_count[0] >= 8:
                                    _mt_log("WARNING", model_run.model_slug,
                                            "  ⚠️ 被测 API 服务端持续返回 HTTP 500 内部服务异常，中断异常重试挂机并保存现有评测记录...", "accuracy")
                                    if proc and proc.poll() is None:
                                        proc.kill()
                                    break
                    _poll_realtime_details()
                    pct = progress_state["pct"]
                    now = time.time()
                    # 暂停期间不触发抗挂机检测（SIGSTOP 冻结的进程不会产生日志）
                    from backend.services.task_manager import _pause_flags as _pf
                    _idle_timeout = int(spec.get("idle_timeout", 600) or 600)
                    if now - last_activity_time > _idle_timeout and not _pf.get(model_run.task_id, False):
                        _mt_log("WARNING", model_run.model_slug,
                                f"  ⚠️ EvalScope 控制台超过 {_idle_timeout // 60} 分钟未产生任何新日志，自动终止子进程以启动重试...", "accuracy")
                        if proc and proc.poll() is None:
                            proc.kill()
                        break
                    if now - last_heartbeat >= 10:
                        last_heartbeat = now
                        elapsed_str = _format_duration(now - acc_start_time)
                        with session_factory() as mdb:
                            mr = mdb.get(ModelRun, model_run.id)
                            if mr is not None:
                            # 整体准确率进度: 60% 起，30% 给准确率阶段
                                overall = (cur_ds_idx + (pct or 0) / 100.0) / max(total_ds, 1)
                                mr.progress = max(mr.progress, 60 + int(30 * overall))
                                if pct is not None:
                                    mr.progress_detail = f"准确率测试中 | [{cur_ds_idx+1}/{total_ds}] {ds_item['ds'].upper()} ({pct}%) | 已用: {elapsed_str} | 实时推理中..."
                                else:
                                    mr.progress_detail = f"准确率测试中 | [{cur_ds_idx+1}/{total_ds}] {ds_item['ds'].upper()} | 已用: {elapsed_str} | 真实题库推理评测进行中..."
                                mdb.commit()
                except Exception:
                    pass
                time.sleep(3)

        monitor_thread = threading.Thread(target=_monitor_progress, daemon=True)
        monitor_thread.start()

        batch_timeout = max(86400, 14400)
        try:
            returncode = proc.wait(timeout=batch_timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            returncode = -1
        stop_flag.set()
        monitor_thread.join(timeout=2)

        with open(ds_log_file, encoding="utf-8", errors="ignore") as f:
            out_text = f.read()
        return returncode, out_text

    def _bootstrap_remote_eval(runner, log_callback, slug):
        """确保评测执行节点具备运行 evalscope (+harbor/swebench/sandbox) 的环境。"""
        marker = "$HOME/.aoni_eval_ready"
        try:
            chk = runner.run_shell(f"test -f {marker} && echo RDY || echo NOPE", timeout=20)
            if "RDY" in (chk.stdout or ""):
                return True
        except Exception:
            pass
        log_callback("INFO", slug, "  [远程] 首次准备评测节点环境（安装 evalscope/harbor/swebench，耗时较长）...", "accuracy")
        setup = (
            "set -e; "
            "python3 -m pip install --user --break-system-packages -q -U pip; "
            "python3 -m pip install --user --break-system-packages -q "
            "'evalscope==1.9.1' 'evalscope[terminal_bench]' 'evalscope[sandbox]' 'swebench==4.1.0'; "
            "touch $HOME/.aoni_eval_ready && echo BOOTSTRAP_OK"
        )
        try:
            r = runner.run_shell(setup, timeout=3000)
            if r.returncode == 0 and "BOOTSTRAP_OK" in (r.stdout or ""):
                log_callback("INFO", slug, "  [远程] 评测节点环境就绪", "accuracy")
                return True
            log_callback("WARNING", slug, f"  [远程] 环境安装可能未完成: {(r.stderr or r.stdout or '')[-300:]}", "accuracy")
            return False
        except Exception as e:
            log_callback("WARNING", slug, f"  [远程] 环境安装异常: {str(e)[:200]}", "accuracy")
            return False

    def _remote_exec_one(local_cmd, ds_item, ds_work_dir, remote_runner):
        """在评测执行节点上运行单数据集 evalscope：nohup 后台 + 轮询日志 + 拉回 report 分数。"""
        import shlex
        mapped = ds_item["mapped"]
        spec = ds_item.get("spec") or {}
        slug = model_run.model_slug

        if not _bootstrap_remote_eval(remote_runner, log_callback, slug):
            return -2, ""

        # 节点 Docker 可用性检查（agent/沙箱类必需）
        if spec.get("agent") or spec.get("sandbox"):
            try:
                d = remote_runner.run_shell("docker info >/dev/null 2>&1 && echo DOCKER_OK || echo NO_DOCKER", timeout=25)
                if "DOCKER_OK" not in (d.stdout or ""):
                    log_callback("WARNING", slug, "  [远程] 评测节点 Docker 不可用，无法运行容器类基准", "accuracy")
                    return -3, ""
            except Exception:
                pass

        tag = f"t{model_run.task_id}_mr{model_run.id}_{mapped}"
        remote_base = f"$HOME/aoni_acc/{tag}"
        remote_log_dir = "$HOME/aoni_acc/logs"
        remote_log = f"{remote_log_dir}/{tag}.log"

        # 改写命令：可执行文件指向远端 venv，work-dir 指向远端目录
        cmd = [str(x) for x in local_cmd]
        cmd[0] = "$HOME/.local/bin/evalscope"
        for i, a in enumerate(cmd):
            if a == "--work-dir" and i + 1 < len(cmd):
                cmd[i + 1] = remote_base
        env_keys = (
            "NO_PROXY", "no_proxy", "HF_ENDPOINT", "DATASETS_MAX_RETRIES", "MODELSCOPE_MAX_RETRIES",
            "HTTP_RETRIES", "REQUESTS_MAX_RETRIES", "HF_HUB_ENABLE_HF_TRANSFER",
            "EVALSCOPE_ALLOW_CODE_EXECUTION", "EVALSCOPE_USE_SANDBOX", "BIGCODEBENCH_ALLOW_CODE_EXECUTION",
        )
        # 刻意不转发 *_PROXY：本机代理监听 127.0.0.1，转发到远端会被解析为远端自身的 127.0.0.1
        # 导致连接被拒（远端节点本身可直连外网）。
        env_pairs = [f"{k}={shlex.quote(str(eval_env[k]))}" for k in env_keys if eval_env.get(k)]
        env_prefix = ("env " + " ".join(env_pairs)) if env_pairs else ""
        # 注意：可执行文件与 work-dir 含 $HOME，必须保持“可被远端 shell 展开”，不能用 shlex.quote
        # 单引号包裹（否则会变成字面量 $HOME 路径导致 env: ... 没有那个文件或目录）。
        def _tok(a: str) -> str:
            if a.startswith("$HOME/") or a == "$HOME":
                return a
            return shlex.quote(a)
        cmd_tokens = ["$HOME/.local/bin/evalscope"] + [_tok(a) for a in cmd[1:]]
        inner = (
            "unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy; "
            + " ".join(cmd_tokens)
            + f" > {remote_log} 2>&1; echo $? > {remote_log}.rc"
        )
        remote_launch = (
            f"mkdir -p {remote_base} {remote_log_dir} && rm -f {remote_log} {remote_log}.rc && cd $HOME && "
            f"nohup bash -c {shlex.quote((env_prefix + ' ' + inner).strip())} >/dev/null 2>&1 & echo LAUNCHED"
        )
        try:
            remote_runner.run_shell(remote_launch, timeout=60)
        except Exception as e:
            log_callback("WARNING", slug, f"  [远程] 启动失败: {str(e)[:200]}", "accuracy")
            return -1, ""

        log_callback("INFO", slug, f"  [远程] 已在评测节点启动 {mapped}（nohup 后台执行）", "accuracy")

        ds_log_file = ds_work_dir / "evalscope_stdout.log"
        with open(ds_log_file, "w", encoding="utf-8") as _f:
            _f.write("")

        idle_timeout = int(spec.get("idle_timeout", 600) or 600)
        last_off = 0
        last_activity = time.time()
        rc_code = -1
        while True:
            time.sleep(8)
            from backend.services.task_manager import _cancel_flags
            if _cancel_flags.get(model_run.task_id, False):
                try:
                    remote_runner.run_shell(f"pkill -f {shlex.quote('aoni_acc/' + tag)} || true", timeout=20)
                except Exception:
                    pass
                rc_code = -1
                break
            try:
                tail = remote_runner.run_shell(f"tail -c +{last_off + 1} {remote_log} 2>/dev/null; echo __AONI_END__", timeout=40)
                txt = tail.stdout or ""
                if "__AONI_END__" in txt:
                    txt = txt.rsplit("__AONI_END__", 1)[0]
                if txt:
                    last_off += len(txt.encode("utf-8", errors="ignore"))
                    last_activity = time.time()
                    with open(ds_log_file, "a", encoding="utf-8") as _f:
                        _f.write(txt)
                    for line in txt.splitlines():
                        if any(k in line.lower() for k in ("error", "evaluating", "failed", "finished", "score")):
                            log_callback("INFO", slug, f"  [远程·{mapped}] {line.strip()[:220]}", "accuracy")
                rc_probe = remote_runner.run_shell(f"cat {remote_log}.rc 2>/dev/null", timeout=20)
                rc_txt = (rc_probe.stdout or "").strip()
                if rc_txt.isdigit():
                    rc_code = int(rc_txt)
                    break
                if time.time() - last_activity > idle_timeout:
                    log_callback("WARNING", slug, f"  [远程] {mapped} 超过 {idle_timeout // 60} 分钟无新日志，终止远端任务", "accuracy")
                    try:
                        remote_runner.run_shell(f"pkill -f {shlex.quote('aoni_acc/' + tag)} || true", timeout=20)
                    except Exception:
                        pass
                    rc_code = -1
                    break
            except Exception:
                pass

        # 拉回 report 分数（写到本地 ds_work_dir/reports，供 _parse_evalscope_output 解析）
        try:
            find_res = remote_runner.run_shell(
                f"find {remote_base} -path '*/reports/*' -name '*.json' 2>/dev/null", timeout=40)
            remote_reports = [l.strip() for l in (find_res.stdout or "").splitlines() if l.strip().endswith(".json")]
            local_reports = ds_work_dir / "reports"
            local_reports.mkdir(parents=True, exist_ok=True)
            for rp in remote_reports:
                cat = remote_runner.run_shell(f"cat {shlex.quote(rp)}", timeout=40)
                if cat.returncode == 0 and cat.stdout:
                    (local_reports / Path(rp).name).write_text(cat.stdout, encoding="utf-8")
            # 题目明细（可选，用于 _log_evalscope_details）
            if not remote_reports:
                log_callback("WARNING", slug, f"  [远程] {mapped} 未找到 report JSON（可能未产出成绩）", "accuracy")
        except Exception as e:
            log_callback("WARNING", slug, f"  [远程] 拉取 report 失败: {str(e)[:200]}", "accuracy")

        try:
            with open(ds_log_file, encoding="utf-8", errors="ignore") as f:
                out_text = f.read()
        except Exception:
            out_text = ""
        return rc_code, out_text

    # ========== 逐数据集执行评测 ==========
    # 汇总分母/结果需覆盖「断点续跑跳过」的已完成数据集，否则会漏报（如 GSM8K）
    acc_map = {}
    for _dname, _acc in resumed_ordered:
        if isinstance(_acc, float):
            acc_map[_dname] = f"{_acc:.2%}"
    total_ds_count = len(sampling_plan) + len(resumed_ordered)
    completed_ds_count = len(resumed_ordered)
    recorded_datasets = set()

    def _render_acc_summary():
        _ordered = list(dict.fromkeys(x.upper() for x in datasets))
        return " | ".join(f"{k}: {acc_map[k]}" for k in _ordered if k in acc_map)

    try:
        for ds_idx, ds_item in enumerate(sampling_plan):
            ds = ds_item["ds"]
            # 暂停检查: 被暂停时阻塞等待，恢复后继续下一个数据集
            _wait_if_paused(model_run.task_id)
            from backend.services.task_manager import _cancel_flags
            if _cancel_flags.get(model_run.task_id, False):
                log_callback("INFO", model_run.model_slug, "准确率测试收到终止指令，评测任务已停止", "accuracy")
                return

            if "bigcodebench" in ds.lower():
                log_callback("WARNING", model_run.model_slug,
                             f"  ⚠️ 数据集 {ds.upper()} 评估需要代码执行沙盒环境支持，当前环境未开启，自动标定并顺畅推进后续数据集", "accuracy")
                db.add(AccResult(model_run_id=model_run.id, dataset=ds, accuracy=None, limit=ds_item["limit"], error="需要代码执行沙盒环境"))
                db.commit()
                recorded_datasets.add(ds.lower())
                completed_ds_count += 1
                continue

            ds_work_dir = work_dir / f"ds_{ds}"
            ds_work_dir.mkdir(parents=True, exist_ok=True)

            _ds_runner = None
            if ds_item.get("exec") == "remote":
                if node_runner is None:
                    log_callback("ERROR", model_run.model_slug,
                                 f"  ❌ {ds.upper()} 需在 x86 评测执行节点运行，但未配置节点 IP（请在设备/设置中配置）", "accuracy")
                    db.add(AccResult(model_run_id=model_run.id, dataset=ds, accuracy=None,
                                     limit=ds_item["limit"], error="未配置评测执行节点(需 x86)"))
                    db.commit()
                    recorded_datasets.add(ds.lower())
                    completed_ds_count += 1
                    continue
                _ds_runner = node_runner

            acc = None
            for attempt in range(1, 4):
                try:
                    log_callback("INFO", model_run.model_slug,
                                 f"  正在评测 {ds.upper()} (第 {attempt}/3 次尝试)...", "accuracy")
                    returncode, out_text = _run_evalscope_one(ds_item, ds_idx, total_ds_count, ds_work_dir, remote_runner=_ds_runner)
                    metrics = _parse_evalscope_output(out_text, work_dir=ds_work_dir, model_name=eval_model_name)
                    acc = _extract_acc(ds, metrics)
                    if acc is not None or returncode == 0:
                        break
                except Exception as se:
                    log_callback("WARNING", model_run.model_slug,
                                 f"  [隔离重试提示] 数据集 {ds.upper()} 第 {attempt} 次测试重试: {se}", "accuracy")
                time.sleep(5)

            if acc is not None:
                completed_ds_count += 1
                recorded_datasets.add(ds.lower())
                elapsed_str = _format_duration(time.time() - acc_start_time)
                acc_str = f"{acc:.2%}"
                acc_map[ds.upper()] = acc_str
                db.add(AccResult(model_run_id=model_run.id, dataset=ds, accuracy=acc, limit=ds_item["limit"], error=None))
                db.commit()
                model_run.progress = 60 + int(30 * (completed_ds_count / max(total_ds_count, 1)))
                model_run.progress_detail = f"准确率测试 ({completed_ds_count}/{total_ds_count}) | 已用: {elapsed_str} | 结果: {_render_acc_summary()}"
                db.commit()
                log_callback("INFO", model_run.model_slug,
                             f"  ✅ 准确率 {ds.upper()}: {acc_str} (成绩已自动保存入库)", "accuracy")
            else:
                # 已彻底禁用「伪造回退评测」(内置 canned 题)：评测未产出有效成绩时如实记录错误，
                # 绝不产出与真实题库无关的假分数。
                db.add(AccResult(model_run_id=model_run.id, dataset=ds, accuracy=None,
                                 limit=ds_item["limit"], error="评测未产出有效成绩(已禁用伪造回退)"))
                db.commit()
                recorded_datasets.add(ds.lower())
                completed_ds_count += 1
                log_callback("WARNING", model_run.model_slug,
                             f"  ❌ 数据集 {ds.upper()} 未产出有效成绩，已如实记录错误（未启用任何伪造回退）", "accuracy")

        _log_evalscope_details(work_dir, log_callback, model_run.model_slug)

    except Exception as e:
        from backend.services.task_manager import _cancel_flags
        if _cancel_flags.get(model_run.task_id, False):
            log_callback("INFO", model_run.model_slug, "准确率测试收到终止/重启指令，评测任务已停止", "accuracy")
            return
        log_callback("WARNING", model_run.model_slug,
                     f"EvalScope 评测遇到网络或长跑中断 ({e})，正在如实记录未完成数据集...", "accuracy")
        plan_by_ds = {item["ds"]: item for item in sampling_plan}
        unprocessed = [item["ds"] for item in sampling_plan if item["ds"].lower() not in recorded_datasets]
        for ds in unprocessed:
            ds_item = plan_by_ds.get(ds, {})
            db.add(AccResult(model_run_id=model_run.id, dataset=ds, accuracy=None,
                             limit=ds_item.get("limit", 0), error="长跑批处理网络中断/超时(已禁用伪造回退)"))
            db.commit()
            log_callback("WARNING", model_run.model_slug,
                         f"  ❌ 数据集 {ds.upper()} 自动记录中断，推进完成", "accuracy")

    # 阶段结束：以数据库为准重建完整汇总（覆盖续跑/异常/提前返回等所有路径）
    _finalize_acc_progress_detail(db, model_run, config, acc_start_time)
    db.commit()


def _run_real_http_accuracy_eval(db: Session, model_run: ModelRun, config: dict, log_callback, runner: RemoteRunner, datasets: list, limit: int, acc_start_time: float = None):
    """[已废弃·禁止调用] 历史上此函数用内置的少量 canned 题目冒充"真实评测"，会产出与真实题库无关的假分数。

    自 2026-09 起准确率阶段已彻底移除对它的调用：任何数据集未产出有效成绩时只记录 error。
    保留函数体仅为兼容历史引用，切勿在任何新代码路径中重新启用。
    """
    raise RuntimeError("_run_real_http_accuracy_eval 已废弃：禁止使用伪造 canned 题产出假分数")
    if not datasets:
        return

    import requests

    if not acc_start_time:
        acc_start_time = time.time()

    port = _resolve_service_port(db, model_run.model_slug, model_run.docker_command or '', config)
    api_cfg = _get_model_api_config(db, model_run.model_slug, runner, port, model_run.model_name)
    api_url = api_cfg["chat_url"]
    api_key = api_cfg["api_key"]
    eval_model_name = api_cfg["model_name"]
    # 校正为服务端真实注册的模型 ID (容器部署场景 model_name 可能是带空格的显示名, 直接调用会 404)
    eval_model_name = _resolve_verified_model_id(api_cfg, eval_model_name, log_callback, model_run.model_slug)

    headers = {}
    if api_key and api_key != "EMPTY":
        headers["Authorization"] = f"Bearer {api_key}"

    # 标准 Benchmark 验证题目样例库（真实学科测试题，含正确答案标答选项）
    eval_benchmark_samples = {
        "mmlu": [
            {"q": "What is the capital of France?\nA) London\nB) Paris\nC) Berlin\nD) Madrid", "ans": "B"},
            {"q": "Which particle has a negative electric charge?\nA) Proton\nB) Neutron\nC) Electron\nD) Photon", "ans": "C"},
            {"q": "What is the square root of 64?\nA) 6\nB) 7\nC) 8\nD) 9", "ans": "C"},
            {"q": "Which element has the chemical symbol 'O'?\nA) Gold\nB) Oxygen\nC) Osmium\nD) Zinc", "ans": "B"},
            {"q": "What is the chemical formula for water?\nA) CO2\nB) H2O\nC) NaCl\nD) CH4", "ans": "B"},
        ],
        "ceval": [
            {"q": "中国共有多少个直辖市？\nA) 3个\nB) 4个\nC) 5个\nD) 6个", "ans": "B"},
            {"q": "下列哪位科学家提出了万有引力定律？\nA) 爱因斯坦\nB) 伽利略\nC) 牛顿\nD) 居里夫人", "ans": "C"},
            {"q": "水在标准大气压下的沸点是多少摄氏度？\nA) 90℃\nB) 100℃\nC) 120℃\nD) 80℃", "ans": "B"},
            {"q": "光速大约是多少？\nA) 30万公里/秒\nB) 10万公里/秒\nC) 50万公里/秒\nD) 3万公里/秒", "ans": "A"},
        ],
        "gsm8k": [
            {"q": "Natalia sold cookies to 5 of her friends. If each friend bought 4 cookies, how many cookies did Natalia sell in total?\nA) 15\nB) 20\nC) 25\nD) 30", "ans": "B"},
            {"q": "Weng earns $12 an hour for babysitting. Yesterday, she babysat for 5 hours. How much money did she earn?\nA) $50\nB) $60\nC) $70\nD) $80", "ans": "B"},
            {"q": "Betty picked 16 apples. She gave 4 to her brother. How many apples does Betty have left?\nA) 10\nB) 12\nC) 14\nD) 8", "ans": "B"},
        ],
        "arc": [
            {"q": "Which tool is best used to measure the volume of a liquid?\nA) Ruler\nB) Graduated cylinder\nC) Thermometer\nD) Balance", "ans": "B"},
            {"q": "Which energy transformation occurs in a flashlight battery?\nA) Chemical to electrical\nB) Electrical to sound\nC) Mechanical to light\nD) Thermal to nuclear", "ans": "A"},
        ],
        "aime24": [
            {"q": "Let N be the number of positive integers n <= 1000 such that n^3 + 3n + 1 is divisible by 7. Compute the sum of the digits of N.\nA) 12\nB) 15\nC) 18\nD) 21", "ans": "B"},
            {"q": "Triangle ABC has side lengths AB = 13, BC = 14, and CA = 15. Circle omega passes through A and is tangent to BC at its midpoint. Find the radius of omega.\nA) 65 / 8\nB) 65 / 16\nC) 169 / 24\nD) 85 / 12", "ans": "A"},
        ],
        "math500": [
            {"q": "Evaluate the definite integral \int_0^{\pi/2} \sin^3(x)/(\sin^3(x) + \cos^3(x)) dx.\nA) \pi / 2\nB) \pi / 4\nC) \pi / 6\nD) 1", "ans": "B"},
        ],
        "arena_hard": [
            {"q": "Design a thread-safe lock-free LRU cache in Rust using Atomic pointers and Compare-And-Swap (CAS) primitives. Which memory ordering is optimal for pointer releases?\nA) Acquire/Release\nB) Mutex lock\nC) Relaxed\nD) Sequential Consistency only", "ans": "A"},
        ],
        "gpqa": [
            {"q": "In a two-level quantum system governed by Hamiltonian H = \hbar \omega (\sigma_z + \alpha \sigma_x) with \alpha = 0.75, what is the exact energy splitting between ground and excited states?\nA) 1.25 \hbar \omega\nB) 2.50 \hbar \omega\nC) 1.50 \hbar \omega\nD) 0.75 \hbar \omega", "ans": "B"},
        ],
        "bigcodebench": [
            {"q": "Which scipy function computes the exponentially weighted rolling copula tail dependence index?\nA) scipy.stats.kendalltau\nB) scipy.stats.rankdata\nC) pandas.Series.ewm\nD) scipy.optimize.minimize", "ans": "B"},
        ],
        "longbench_pro": [
            {"q": "In the 120k token audit log, what is the intercompany transfer pricing gap for Subsidiary Alpha?\nA) $500,000\nB) $1,200,000\nC) $850,000\nD) $2,000,000", "ans": "B"},
        ]
    }

    total_ds = len(datasets) if datasets else 1
    completed_ds = 0
    acc_summary = []

    for ds_idx, ds in enumerate(datasets):
        ds_lower = ds.lower()
        samples = eval_benchmark_samples.get(ds_lower, eval_benchmark_samples["mmlu"])
        correct_count = 0
        total_eval = 0
        if limit and limit > 0:
            total_samples_cnt = min(limit, len(samples))
        else:
            total_samples_cnt = len(samples)

        elapsed_sec = time.time() - acc_start_time
        if completed_ds > 0:
            avg_ds_sec = elapsed_sec / completed_ds
            eta_sec = (total_ds - completed_ds) * avg_ds_sec
            eta_str = _format_duration(eta_sec)
        else:
            eta_str = "计算中..."
        elapsed_str = _format_duration(elapsed_sec)

        model_run.progress = 60 + int(30 * (completed_ds / total_ds))
        model_run.progress_detail = f"准确率测试 ({completed_ds}/{total_ds}) | 已用: {elapsed_str} | 预计剩余: {eta_str} | 正在评测: {ds.upper()}"
        db.commit()

        log_callback("INFO", model_run.model_slug, f"[{ds.upper()}] 评测阶段启动 ({ds_idx+1}/{total_ds}) | 已用 {elapsed_str} | 预计剩余 {eta_str} | 评估样本: {total_samples_cnt} 题", "accuracy")

        log_step = max(1, total_samples_cnt // 10)
        for i in range(total_samples_cnt):
            sample = samples[i % len(samples)]
            prompt = f"Please answer the following multiple-choice question. Give ONLY the option letter (A, B, C, or D).\n\nQuestion:\n{sample['q']}\n\nAnswer:"
            payload = {
                "model": eval_model_name,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 16,
                "temperature": 0.0
            }
            try:
                r = requests.post(api_url, json=payload, headers=headers, timeout=30, proxies={"http": None, "https": None})
                if r.status_code == 200:
                    resp_json = r.json()
                    ans_text = resp_json["choices"][0]["message"]["content"].strip().upper()
                    is_correct = (sample["ans"] in ans_text) or (ans_text.startswith(sample["ans"]))
                    if is_correct:
                        correct_count += 1
                    total_eval += 1
                    status_flag = "PASS" if is_correct else "FAIL"
                    q_brief = sample['q'].replace('\n', ' ')
                    if len(q_brief) > 120:
                        q_brief = q_brief[:120] + "..."
                    current_accuracy = correct_count / total_eval
                    # 当切换到【调试 (全量/协议参数)】日志模式时，输出完整的题目内容、标准答案与模型回答
                    log_callback("DEBUG", model_run.model_slug,
                                 f"  [DEBUG 明细] [{ds.upper()} 题 #{i+1}/{total_samples_cnt}] 题目: {q_brief} | 标准答案: [{sample['ans']}] | 模型回答: [{ans_text}] | 结果: [{status_flag}]", "accuracy")
                    # 首尾题目及每 10% 打印 INFO 概览日志，避免数据库锁死与日志过载
                    if i == 0 or i == total_samples_cnt - 1 or (i + 1) % log_step == 0:
                        log_callback("INFO", model_run.model_slug,
                                     f"  └─ [{ds.upper()} 题 #{i+1}/{total_samples_cnt}] 实时准确率: {current_accuracy:.1%} ({correct_count}/{total_eval}) | 结果: [{status_flag}]", "accuracy")
                else:
                    log_callback("WARNING", model_run.model_slug, f"  └─ [{ds.upper()} 题 #{i+1}/{total_samples_cnt}] 接口响应异常: HTTP {r.status_code}", "accuracy")
            except Exception as req_err:
                log_callback("WARNING", model_run.model_slug, f"  └─ [{ds.upper()} 题 #{i+1}/{total_samples_cnt}] 请求超时: {req_err}", "accuracy")

        completed_ds += 1
        elapsed_sec = time.time() - acc_start_time
        avg_ds_sec = elapsed_sec / completed_ds
        eta_sec = (total_ds - completed_ds) * avg_ds_sec
        eta_str = _format_duration(eta_sec)
        elapsed_str = _format_duration(elapsed_sec)

        if total_eval > 0:
            final_acc = round(correct_count / total_eval, 4)
            acc_summary.append(f"{ds.upper()}: {final_acc:.2%}")
            log_callback("INFO", model_run.model_slug,
                         f"✅ [{ds.upper()}] 评测完成 | 正确数: {correct_count}/{total_eval} | 准确率: {final_acc:.2%} (已用 {elapsed_str}, 预计剩余 {eta_str})", "accuracy")
        else:
            final_acc = 0.0
            acc_summary.append(f"{ds.upper()}: 失败")
            log_callback("ERROR", model_run.model_slug, f"[{ds.upper()}] 评测失败 | 端点无有效响应", "accuracy")

        db.add(AccResult(
            model_run_id=model_run.id,
            dataset=ds_lower,
            accuracy=final_acc,
            limit=limit,
            error=None if total_eval > 0 else "模型 API 无法响应"
        ))
        model_run.progress = 60 + int(30 * (completed_ds / total_ds))
        model_run.progress_detail = f"准确率测试 ({completed_ds}/{total_ds}) | 已用: {elapsed_str} | 预计剩余: {eta_str} | 结果: {' | '.join(acc_summary)}"
        db.commit()


def _parse_evalscope_output(stdout: str, work_dir: Path = None, model_name: str = "") -> dict:
    """从 evalscope 输出中提取各数据集的准确率指标。

    优先从 EvalScope 生成的 reports/<model>/<dataset>.json 中读取真实 score (mean_acc)，
    该 JSON 由 evalscope 在评测成功后自动落盘，比解析控制台输出更可靠。
    读取不到时退化为解析 stdout 中的 accuracy 字段。
    """
    metrics = {}

    report_files = []
    if work_dir is not None and work_dir.exists():
        # EvalScope 可能会在 work_dir 下创建时间戳子目录 (如 work_dir/20260803_183017/reports/...)
        report_files.extend(sorted(work_dir.glob("**/reports/**/*.json")))
    
    # 兜底检索：若平台 ./outputs 目录存在，也进行 reports 通配符搜索
    outputs_dir = Path("./outputs")
    if outputs_dir.exists():
        for r in sorted(outputs_dir.glob("**/reports/**/*.json")):
            if r not in report_files:
                report_files.append(r)

    for report_file in report_files:
        try:
            data = json.loads(report_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        ds_raw = data.get("dataset_name") or report_file.stem
        ds = ds_raw.lower()
        score = data.get("score")
        if score is not None:
            try:
                metrics[f"{ds}_accuracy"] = float(score)
                metrics[f"{ds.replace('_', '')}_accuracy"] = float(score)
                metrics[f"{report_file.stem.lower()}_accuracy"] = float(score)
                metrics[f"{report_file.stem.lower().replace('_', '')}_accuracy"] = float(score)
            except (ValueError, TypeError):
                pass
        # 若无顶层 score，从 metrics 中找第一个含 acc 的指标
        if f"{ds}_accuracy" not in metrics and data.get("metrics"):
            for m in data["metrics"]:
                mname = str(m.get("name", "")).lower()
                if "acc" in mname and m.get("score") is not None:
                    try:
                        val = float(m["score"])
                        metrics[f"{ds}_accuracy"] = val
                        metrics[f"{ds.replace('_', '')}_accuracy"] = val
                        metrics[f"{report_file.stem.lower()}_accuracy"] = val
                        metrics[f"{report_file.stem.lower().replace('_', '')}_accuracy"] = val
                    except (ValueError, TypeError):
                        pass
                    break

    for m in re.findall(r"(\w+).*?accuracy.*?([\d.]+)", stdout, re.IGNORECASE):
        if m[0].lower() not in metrics:
            try:
                metrics[f"{m[0].lower()}_accuracy"] = float(m[1])
            except ValueError:
                pass
    return metrics


_running_evalscope_procs: dict[int, subprocess.Popen] = {}


def stop_task_containers(task):
    """强行清理该任务占用的 Docker 测试容器与关联的 evalscope 后台进程，彻底释放 GPU 显存与系统资源。

    仅当任务确实在平台下发过容器（有目标设备且存在非空 docker 命令的 model_run）时才执行容器清理；
    纯外部 API 接入的任务无平台容器，跳过容器清理，避免后端本机被 docker rm / fuser -k / 清页缓存误伤
    （该类任务仍会清理其关联的 evalscope 后台进程）。
    """
    try:
        device = task.device if task else None
        managed_any = bool(device) and any(
            (mr.docker_command or "").strip() for mr in (task.model_runs or [])
        )
        if managed_any:
            runner = RemoteRunner(device)
            _stop_container(runner)
    except Exception:
        pass
    try:
        if task and hasattr(task, "model_runs") and task.model_runs:
            for mr in task.model_runs:
                proc = _running_evalscope_procs.pop(mr.id, None)
                if proc and proc.poll() is None:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        if task and hasattr(task, "id"):
            # 根据 Task ID 精准销毁属于该任务的 evalscope 进程，防误杀其他任务
            res = subprocess.run(["pgrep", "-f", f"_t{task.id}_mr"], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                for pid in res.stdout.strip().split():
                    try:
                        os.kill(int(pid), 9)
                    except Exception:
                        pass
    except Exception:
        pass

    # 终止评测执行节点上属于该任务的远程 evalscope 进程
    try:
        if task and hasattr(task, "id"):
            from backend.models import PlatformSetting
            from backend.database import session_factory
            with session_factory() as sdb:
                row = sdb.get(PlatformSetting, "eval_node_ip")
                node_ip = (row.value or "").strip() if row else ""
            if node_ip:
                from backend.routers.eval_tools import build_eval_node_runner
                nr = build_eval_node_runner(node_ip)
                nr.run_shell(f"pkill -f 'aoni_acc/t{task.id}_mr' || true", timeout=25)
    except Exception:
        pass


def restart_task(db: Session, task_id: int, resume: bool = True):
    """一键重新运行 / 断点续跑指定测试任务"""
    task = db.get(Task, task_id)
    if not task:
        raise ValueError("任务不存在")

    # 1. 强行清理已存在的残留容器
    stop_task_containers(task)

    # 2. 重置主任务状态
    task.status = "running"
    task.started_at = datetime.utcnow()
    task.completed_at = None
    db.commit()

    # 3. 重置关联的所有 ModelRun 并保留有效结果
    for mr in task.model_runs:
        model_info = db.execute(select(ModelInfo).where(ModelInfo.slug == mr.model_slug)).scalar_one_or_none()
        is_ext = model_info and bool(model_info.is_external or model_info.api_base)
        mr.status = "deploying"
        mr.progress = 0
        mr.progress_detail = "恢复下发测试任务，正在接入外部 API 端点..." if is_ext else "恢复下发测试任务，正在启动容器..."
        mr.stage_status = {
            "deploying": "running",
            "validating": "pending",
            "gateway_testing": "pending",
            "perf_testing": "pending",
            "acc_testing": "pending",
            "reporting": "pending"
        }
        mr.started_at = datetime.utcnow()
        mr.completed_at = None
        db.query(GatewayResult).filter_by(model_run_id=mr.id).delete()
        db.query(PerfResult).filter_by(model_run_id=mr.id).delete()
        if resume:
            # 增量续跑模式：仅擦除未成功/错误的 AccResult 记录，保留已测试完成的数据集指标
            db.query(AccResult).filter(AccResult.model_run_id == mr.id, AccResult.accuracy.is_(None)).delete()
        else:
            db.query(AccResult).filter_by(model_run_id=mr.id).delete()

    db.query(TaskLog).filter_by(task_id=task.id).delete()
    db.commit()

    # 4. 异步拉起重新评测工作线程
    import threading
    from backend.services.task_manager import start_task
    t = threading.Thread(target=start_task, args=(task.id,), daemon=True)
    t.start()
    return task
