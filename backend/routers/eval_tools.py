"""
评测执行节点 (公共) API
- 唯一一台用于「工具调用测试」中需要 x86/Docker 容器的基准 (Terminal-Bench / SWE-bench) 的远程执行节点。
- 平台只需配置节点 IP；SSH 用户名/密码/端口在代码中给出默认值 (可用环境变量覆盖)。
"""
import os
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import PlatformSetting
from backend.auth import get_current_user
from backend.services.executor import RemoteRunner

router = APIRouter(prefix="/api/eval-tools", tags=["EvalTools"])

NODE_IP_KEY = "eval_node_ip"

DEFAULT_EVAL_NODE_USER = os.getenv("EVAL_NODE_USER", "dev")
DEFAULT_EVAL_NODE_PASSWORD = os.getenv("EVAL_NODE_PASSWORD", "000000")
DEFAULT_EVAL_NODE_PORT = int(os.getenv("EVAL_NODE_PORT", "22"))

# Terminal/SWE 需要 x86 容器；BFCL/τ² 为纯 API，可在本机运行。
REMOTE_TOOL_IDS = ("terminal_bench_v2_1", "swe_bench_verified_mini_agentic")
LOCAL_TOOL_IDS = ("bfcl_v4", "tau2_bench")
ALL_TOOL_IDS = REMOTE_TOOL_IDS + LOCAL_TOOL_IDS


def get_eval_node_ip(db: Session) -> str:
    row = db.get(PlatformSetting, NODE_IP_KEY)
    return (row.value or "").strip() if row else ""


def set_eval_node_ip(db: Session, ip: str) -> None:
    row = db.get(PlatformSetting, NODE_IP_KEY)
    if row is None:
        row = PlatformSetting(key=NODE_IP_KEY, value=ip)
        db.add(row)
    else:
        row.value = ip
    db.commit()


def build_eval_node_runner(ip: str) -> RemoteRunner:
    """按节点 IP 构造 RemoteRunner；用户名/密码/端口用代码默认值。"""
    cred = SimpleNamespace(
        ssh_username=DEFAULT_EVAL_NODE_USER,
        ssh_port=DEFAULT_EVAL_NODE_PORT,
        type="password",
        ssh_key_path=None,
        password=DEFAULT_EVAL_NODE_PASSWORD,
    )
    dev = SimpleNamespace(host=ip, credential=cred, name=f"eval-node({ip})", status="unknown")
    return RemoteRunner(dev)


class NodeConfig(BaseModel):
    ip: str = ""


@router.get("/node")
def api_get_node(db: Session = Depends(get_db)):
    ip = get_eval_node_ip(db)
    return {
        "ip": ip,
        "configured": bool(ip),
        "default_user": DEFAULT_EVAL_NODE_USER,
        "default_port": DEFAULT_EVAL_NODE_PORT,
    }


@router.put("/node")
def api_set_node(data: NodeConfig, db: Session = Depends(get_db), _=Depends(get_current_user)):
    ip = (data.ip or "").strip()
    set_eval_node_ip(db, ip)
    return {"status": "ok", "ip": ip, "configured": bool(ip)}


def _local_evalscope_ready() -> bool:
    import shutil
    if shutil.which("evalscope"):
        return True
    return os.path.exists(os.path.expanduser("~/.local/bin/evalscope"))


@router.get("/status")
def api_status(db: Session = Depends(get_db)):
    """探测评测执行节点可用性，供 UI 渲染在线徽标。"""
    ip = get_eval_node_ip(db)
    local_ok = _local_evalscope_ready()
    tools = {tid: {"id": tid, "ready": False, "needs_node": tid in REMOTE_TOOL_IDS} for tid in ALL_TOOL_IDS}
    # 本机纯 API 工具（BFCL/τ²）不依赖节点
    for tid in LOCAL_TOOL_IDS:
        tools[tid]["ready"] = local_ok
    if not ip:
        return {
            "configured": False,
            "online": False,
            "arch": "",
            "message": "未配置评测执行节点 IP",
            "tools": list(tools.values()),
        }
    runner = build_eval_node_runner(ip)
    try:
        arch_res = runner.run_shell("uname -m", timeout=12)
        arch = (arch_res.stdout or "").strip()
        if arch_res.returncode != 0:
            return {
                "configured": True, "online": False, "arch": "",
                "message": f"SSH 连接失败: {(arch_res.stderr or arch_res.stdout or '').strip()[:150]}",
                "tools": list(tools.values()),
            }
        docker_res = runner.run_shell("docker info --format '{{.ServerVersion}}' 2>/dev/null || echo NO_DOCKER", timeout=20)
        docker_ok = docker_res.returncode == 0 and "NO_DOCKER" not in (docker_res.stdout or "")
        ev_res = runner.run_shell("test -f $HOME/.aoni_eval_ready && echo EVREADY || echo EVMISSING", timeout=12)
        env_ready = (ev_res.stdout or "").strip().endswith("EVREADY")
        online = bool(arch) and docker_ok
        for tid in REMOTE_TOOL_IDS:
            tools[tid]["ready"] = online and arch == "x86_64" and docker_ok
        msg = f"在线 · {arch}" + (" · Docker 就绪" if docker_ok else " · Docker 不可用")
        if arch != "x86_64":
            msg += " · 非 x86_64，无法运行 Terminal/SWE"
        return {
            "configured": True,
            "online": online,
            "arch": arch,
            "docker": docker_ok,
            "env_ready": env_ready,
            "message": msg,
            "tools": list(tools.values()),
        }
    except Exception as e:
        return {
            "configured": True, "online": False, "arch": "",
            "message": f"节点探测异常: {str(e)[:150]}",
            "tools": list(tools.values()),
        }
