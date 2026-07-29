"""
AONI 模型测试平台 — FastAPI 后端配置
"""
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 优先加载 config/.env 配置文件
load_dotenv(PROJECT_ROOT / "config" / ".env")
load_dotenv(PROJECT_ROOT / ".env")
DATA_DIR = PROJECT_ROOT / "data"
SRC_DIR = PROJECT_ROOT / "src"
REPORTS_DIR = PROJECT_ROOT / "reports"
LOGS_DIR = PROJECT_ROOT / "logs"

DATABASE_URL = os.getenv("AONI_DATABASE_URL", f"sqlite+aiosqlite:///{PROJECT_ROOT}/data/aoni_platform.db")
DATABASE_URL_SYNC = os.getenv("AONI_DATABASE_SYNC", f"sqlite:///{PROJECT_ROOT}/data/aoni_platform.db")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

# vLLM 默认端口
VLLM_DEFAULT_PORT = 8300
VLLM_STARTUP_TIMEOUT = 7200

# 测试默认参数
DEFAULT_NUM_PROMPTS = 300
DEFAULT_INPUT_LEN = 512
DEFAULT_OUTPUT_SHORT = 128
DEFAULT_OUTPUT_LONG = 512

# 准确率评测默认参数
DEFAULT_ACC_LIMIT = 200
DEFAULT_DATASETS = ["mmlu", "ceval", "gsm8k", "arc", "humaneval"]

# SMTP 邮件服务配置
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_SENDER = os.getenv("SMTP_SENDER", "")
