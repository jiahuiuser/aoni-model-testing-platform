"""
Pydantic 数据模型 — API 请求/响应
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ========== 模型列表 ==========

class ModelInfoOut(BaseModel):
    idx: int
    name: str
    slug: str
    size_category: str
    status: str
    tos_path: str

    class Config:
        from_attributes = True


# ========== 任务 ==========

class PerfRoundConfig(BaseModel):
    input_len: int = 512
    output_lens_str: str = "128,512"
    concurrencies_str: str = ""
    num_prompts: int = 300


class TaskConfig(BaseModel):
    model_slugs: List[str] = Field(default_factory=list)
    gateway_enabled: bool = True
    gateway_protocols: List[str] = Field(default_factory=lambda: ["openai", "anthropic", "responses"])
    test_longctx: bool = False
    perf_enabled: bool = True
    perf_rounds_config: List[PerfRoundConfig] = Field(default_factory=lambda: [
        PerfRoundConfig()
    ])
    acc_enabled: bool = True
    acc_datasets: List[str] = ["mmlu", "ceval", "gsm8k", "arc"]
    acc_limit: int = 200
    container_port: int = 8300
    container_startup_timeout: int = 7200
    docker_command: Optional[str] = None


class TaskCreate(BaseModel):
    name: str
    profile: str = "custom"
    device_id: Optional[int] = None
    device_ids: Optional[List[int]] = None  # 支持选择多台设备下发测试
    template_id: Optional[int] = None      # 关联测试模板 ID
    scheduled_at: Optional[datetime] = None # 定时下发执行时间
    config: TaskConfig = Field(default_factory=TaskConfig)


# ========== 硬件组 / 测试模板 / 数据集 / 镜像 Schema ==========

class HardwareGroupCreate(BaseModel):
    name: str
    description: Optional[str] = None


class TestTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    num_prompts: int = 300
    input_lens: List[int] = Field(default_factory=lambda: [128, 512])
    output_lens: List[int] = Field(default_factory=lambda: [128, 512])
    concurrencies: List[int] = Field(default_factory=lambda: [1, 4, 8, 16, 32])
    datasets: List[str] = Field(default_factory=lambda: ["mmlu", "ceval"])
    acc_limit: int = 200


class DockerImageCreate(BaseModel):
    name: str
    image_tag: str
    download_url: Optional[str] = None
    hardware_group: str = "NVIDIA_jetson_AGX_Thor"
    description: Optional[str] = None


class DatasetDownloadRequest(BaseModel):
    name: str
    source: str = "ModelScope/EvalScope"


class TaskOut(BaseModel):
    id: int
    name: str
    status: str
    profile: str
    user_id: Optional[int] = None
    username: Optional[str] = None
    device_id: Optional[int] = None
    device_name: Optional[str] = None
    config: dict
    created_at: datetime
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    model_count: int = 0
    completed_count: int = 0

    class Config:
        from_attributes = True


class GatewayResultOut(BaseModel):
    id: int
    category: str = "protocol"
    test_item: str = ""
    protocol: str = "system"
    status: str = "SKIP"
    latency_ms: Optional[float] = None
    message: Optional[str] = None
    raw_details: Optional[dict] = None

    class Config:
        from_attributes = True


class PerfResultOut(BaseModel):
    id: int
    round_num: int = 1
    strategy_id: str = ""
    output_type: str = ""
    concurrency: int = 0
    input_len: int = 0
    output_len: int = 0
    throughput_tok_s: Optional[float] = None
    mean_ttft_ms: Optional[float] = None
    p99_ttft_ms: Optional[float] = None
    mean_tpot_ms: Optional[float] = None
    p99_tpot_ms: Optional[float] = None
    raw_report: Optional[dict] = None
    error: Optional[str] = None

    class Config:
        from_attributes = True


class AccResultOut(BaseModel):
    id: int
    dataset: str = ""
    accuracy: Optional[float] = None
    error: Optional[str] = None

    class Config:
        from_attributes = True


class ModelRunOut(BaseModel):
    id: int
    model_idx: int
    model_name: str
    model_slug: str
    status: str
    device_id: Optional[int] = None
    device_name: Optional[str] = None
    progress: int = 0
    progress_detail: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    gateway_results: List[GatewayResultOut] = []
    perf_results: List[PerfResultOut] = []
    acc_results: List[AccResultOut] = []

    class Config:
        from_attributes = True


class TaskDetailOut(TaskOut):
    model_runs: List[ModelRunOut] = []


class TaskLogOut(BaseModel):
    id: int
    level: str
    model_slug: Optional[str] = None
    module: str = "system"
    message: str
    created_at: datetime

    class Config:
        from_attributes = True


class TaskAction(BaseModel):
    action: str  # pause / resume / cancel
