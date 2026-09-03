"""
沐曦软星（MetaX SoftNova）鉴权服务

- 新窗口跳转 authing 登录（用户自助输账号/验证码），回调回填临时会话
- 会话仅存内存（含过期时间），不落库、不持久化账号密码
- 凭临时会话为指定镜像获取 docker pull 命令
"""
import time
import uuid
from datetime import datetime

from backend import config

# 内存会话表: {session_id: {"token": str, "expires_at": float, "username": str}}
_SESSIONS: dict = {}

SESSION_TTL_SECONDS = 3600  # 会话有效期 1 小时


def create_session(token: str, username: str = "") -> str:
    """登录回调成功后存入内存会话，返回 session_id"""
    session_id = uuid.uuid4().hex
    _SESSIONS[session_id] = {
        "token": token,
        "username": username,
        "expires_at": time.time() + SESSION_TTL_SECONDS,
    }
    # 简单清理过期会话
    now = time.time()
    for sid in list(_SESSIONS.keys()):
        if _SESSIONS[sid]["expires_at"] < now:
            _SESSIONS.pop(sid, None)
    return session_id


def get_session(session_id: str) -> dict | None:
    """读取会话（过期返回 None）"""
    sess = _SESSIONS.get(session_id)
    if not sess:
        return None
    if sess["expires_at"] < time.time():
        _SESSIONS.pop(session_id, None)
        return None
    return sess


def drop_session(session_id: str):
    _SESSIONS.pop(session_id, None)


def get_login_url() -> dict:
    """
    构造软星登录跳转信息:
    前端 GET /client/api/user/authing/login?redirect_uri=<回调> 会返回 {data: <authing授权URL>}
    """
    return {
        "base_url": config.METAX_BASE_URL,
        "api_prefix": config.METAX_API_PREFIX,
        "redirect_uri": config.METAX_OAUTH_REDIRECT,
        "chip_name": config.METAX_CHIP_NAME,
        "package_kind": config.METAX_PACKAGE_KIND,
        "dimension": config.METAX_DIMENSION,
        "deliver_type": config.METAX_DELIVER_TYPE,
        "system": config.METAX_SYSTEM,
        "arch": config.METAX_ARCH,
    }


def fetch_catalog(session_id: str, filters: dict | None = None) -> dict:
    """
    凭会话调用软星 package_info 拉取镜像清单。
    GET {METAX_BASE_URL}{METAX_API_PREFIX}/v2/dlhub/package_info/

    filters 可覆盖默认筛选: chip_name / package_kind / dimension / deliver_type / system / arch
    """
    import httpx

    sess = get_session(session_id)
    if not sess:
        raise PermissionError("沐曦会话已过期或不存在，请重新连接")

    tpl = get_login_url()
    params = {
        "chip_name": (filters or {}).get("chip_name") or tpl["chip_name"],
        "package_kind": (filters or {}).get("package_kind") or tpl["package_kind"],
        "dimension": (filters or {}).get("dimension") or tpl["dimension"],
        "deliver_type": (filters or {}).get("deliver_type") or tpl["deliver_type"],
        "system": (filters or {}).get("system") or tpl["system"],
        "arch": (filters or {}).get("arch") or tpl["arch"],
    }
    url = f"{config.METAX_BASE_URL}{config.METAX_API_PREFIX}/v2/dlhub/package_info/"
    try:
        resp = httpx.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {sess['token']}",
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
                "Referer": f"{config.METAX_BASE_URL}/softnova/docker",
            },
            timeout=30,
        )
    except Exception as e:
        raise RuntimeError(f"连接沐曦软星失败: {e}")

    ctype = resp.headers.get("content-type", "")
    if resp.status_code != 200 or "json" not in ctype:
        raise RuntimeError(f"沐曦软星返回异常 (HTTP {resp.status_code}), 请重新登录后再试")
    try:
        return resp.json()
    except Exception:
        raise RuntimeError("沐曦软星返回内容无法解析, 请重新登录")


async def fetch_pull_command(session_id: str, image_ref: str) -> str:
    """
    凭会话获取指定镜像的 docker pull 命令。
    POST {METAX_BASE_URL}{METAX_API_PREFIX}/image/download

    image_ref: 沐曦镜像标识（id / 完整 tag）
    """
    import httpx

    sess = get_session(session_id)
    if not sess:
        raise PermissionError("沐曦会话已过期或不存在，请重新登录")

    url = f"{config.METAX_BASE_URL}{config.METAX_API_PREFIX}/image/download"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                json={"image": image_ref},
                headers={"Authorization": f"Bearer {sess['token']}"},
            )
            data = resp.json()
    except Exception as e:
        raise RuntimeError(f"获取 docker pull 命令失败: {e}")

    if resp.status_code != 200:
        raise RuntimeError(f"获取 docker pull 命令失败: HTTP {resp.status_code}")

    pull_cmd = (data.get("data") or {}).get("pull_command") or data.get("data") or ""
    if isinstance(pull_cmd, dict):
        pull_cmd = pull_cmd.get("command") or pull_cmd.get("cmd") or ""
    return str(pull_cmd)
