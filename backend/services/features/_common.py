"""功能测试模块共享工具"""


def chat_url(base_url):
    """规范化 chat completions URL: 兼容 base 带 /v1 与不带两种写法"""
    b = (base_url or "").rstrip("/")
    if b.endswith("/v1"):
        return f"{b}/chat/completions"
    return f"{b}/v1/chat/completions"


def models_url(base_url):
    """规范化 models URL"""
    b = (base_url or "").rstrip("/")
    if b.endswith("/v1"):
        return f"{b}/models"
    return f"{b}/v1/models"
