"""
大模型测试平台 — 数据库模型 (SQLAlchemy)
"""
import datetime
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, JSON, ForeignKey, Enum as SAEnum, BigInteger, Boolean
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    pass


# 导入所有模型，确保 metadata 已注册
from backend.models.user import User  # noqa: F401, E402


# ---------- 模型注册表 ----------

class ModelInfo(Base):
    __tablename__ = "models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    idx = Column(Integer, nullable=False)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False, index=True)
    docker_command = Column(Text, nullable=True, comment="默认 docker 命令（无设备配置时使用）")
    tos_path = Column(String(500), nullable=True)
    group_name = Column(String(100), default="NVIDIA_jetson_AGX_Thor", nullable=True, comment="所属硬件组/模块")
    size_category = Column(String(50), nullable=True)
    status = Column(String(20), default="NEW", comment="默认测试状态")
    result_detail = Column(String(500), nullable=True)
    is_external = Column(Integer, default=0, comment="是否为已部署外部 API 接入模式 (0: 否, 1: 是)")
    api_base = Column(String(500), nullable=True, comment="外部 API Base URL，如 http://192.168.1.40:8000/v1")
    api_key = Column(String(255), nullable=True, default="EMPTY", comment="API Key")
    model_endpoint_name = Column(String(255), nullable=True, comment="远程 API 服务模型标识名")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    device_configs = relationship("ModelDeviceConfig", back_populates="model", cascade="all, delete-orphan")


# ---------- 模型-设备配置 ----------

class ModelDeviceConfig(Base):
    """每个模型在不同设备上的专属配置和测试状态"""
    __tablename__ = "model_device_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_id = Column(Integer, ForeignKey("models.id", ondelete="CASCADE"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)

    docker_command = Column(Text, nullable=True, comment="该设备专属的 docker 命令")
    status = Column(String(20), default="NEW", comment="NEW / PASS / FAIL")  # 该设备上的测试结果
    result_detail = Column(String(500), nullable=True)

    tested_at = Column(DateTime, nullable=True, comment="最近一次测试时间")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    model = relationship("ModelInfo", back_populates="device_configs")
    device = relationship("Device")


# ---------- 凭证管理 ----------

class Credential(Base):
    """SSH 凭证：支持密钥文件或密码两种方式"""
    __tablename__ = "credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, comment="凭证名称，如 nv5000-key")
    type = Column(String(20), nullable=False, default="ssh_key", comment="ssh_key / password")
    ssh_username = Column(String(100), nullable=False, comment="SSH 登录用户名")
    ssh_port = Column(Integer, default=22, comment="SSH 端口")

    # 密钥方式
    ssh_key_path = Column(String(500), nullable=True, comment="SSH 私钥文件路径，如 /home/sd1/.ssh/id_rsa")

    # 密码方式 (仅 type=password 时使用)
    password = Column(String(255), nullable=True, comment="SSH 密码 (加密存储)")

    description = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ---------- 设备管理 ----------

class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, comment="设备名称")
    host = Column(String(255), nullable=False, comment="IP 地址或主机名")
    device_type = Column(String(50), default="jetson", comment="设备类型: jetson / server / cloud")
    chip_type = Column(String(50), default="nvidia_thor", comment="芯片类型: nvidia_thor / metax_c500_n260 / nvidia_rtx5090 / mthreads_musa")
    port = Column(Integer, default=8800, comment="vLLM 默认端口")

    # SSH 凭证 (nullable = 本机设备无需凭证)
    credential_id = Column(Integer, ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True)

    # 资源信息
    cpu_cores = Column(Integer, nullable=True)
    memory_gb = Column(Float, nullable=True)
    gpu_info = Column(String(255), nullable=True, comment="GPU 型号/显存")
    gpu_count = Column(Integer, nullable=True, comment="GPU 数量")

    status = Column(String(20), default="online")  # online / offline / busy
    description = Column(String(500), nullable=True)

    last_checked_at = Column(DateTime, nullable=True)
    last_check_detail = Column(JSON, nullable=True, comment="最近一次检测详情")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    bound_image_id = Column(Integer, ForeignKey("docker_images.id", ondelete="SET NULL"), nullable=True)

    # 关联
    credential = relationship("Credential")
    tasks = relationship("Task", back_populates="device")
    model_runs = relationship("ModelRun", back_populates="device")
    bound_image = relationship("DockerImage")


# ---------- 任务状态枚举 ----------

class TaskStatus(str, enum.Enum):
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StageStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ModelStage(str, enum.Enum):
    DEPLOYING = "deploying"
    VALIDATING = "validating"
    GATEWAY_TESTING = "gateway_testing"
    FEATURE_TESTING = "feature_testing"
    PERF_TESTING = "perf_testing"
    ACC_TESTING = "acc_testing"
    REPORTING = "reporting"
    DONE = "done"
    FAILED = "failed"


# ---------- 任务 ----------

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    status = Column(String(50), default="queued", comment="任务状态: queued/running/paused/completed/failed/cancelled")
    profile = Column(String(50), default="full")  # quick / perf / accuracy / full / custom

    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # 关联设备
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)

    # 任务配置 (JSON)
    config = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    scheduled_at = Column(DateTime, nullable=True, comment="定时下发执行时间")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # 关联
    user = relationship("User", foreign_keys=[user_id])
    device = relationship("Device", back_populates="tasks")
    model_runs = relationship("ModelRun", back_populates="task", cascade="all, delete-orphan")
    logs = relationship("TaskLog", back_populates="task", cascade="all, delete-orphan")


# ---------- 模型执行记录 ----------

class ModelRun(Base):
    __tablename__ = "model_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"))

    model_idx = Column(Integer, nullable=False)
    model_name = Column(String(255), nullable=False)
    model_slug = Column(String(255), nullable=False)
    size_category = Column(String(50), nullable=True)

    # 关联设备（标识该测试在哪台设备上运行）
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    device_name = Column(String(255), nullable=True)

    status = Column(String(50), default="deploying", comment="模型测试阶段: deploying/validating/gateway_testing/perf_testing/acc_testing/reporting/done/failed")
    stage_status = Column(JSON, default=dict)

    # 容器信息
    docker_command = Column(Text, nullable=True)
    container_name = Column(String(255), nullable=True)
    port = Column(Integer, nullable=True)

    # 进度
    progress = Column(Integer, default=0)
    progress_detail = Column(String(255), nullable=True)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    task = relationship("Task", back_populates="model_runs")
    device = relationship("Device", back_populates="model_runs")
    gateway_results = relationship("GatewayResult", back_populates="model_run", cascade="all, delete-orphan")
    feature_results = relationship("FeatureResult", back_populates="model_run", cascade="all, delete-orphan")
    perf_results = relationship("PerfResult", back_populates="model_run", cascade="all, delete-orphan")
    acc_results = relationship("AccResult", back_populates="model_run", cascade="all, delete-orphan")


# ---------- 镜像版本（离线采集, 报告直接查库） ----------

class ImageVersion(Base):
    """部署镜像的运行时版本快照，按 (image_repo, image_tag) 唯一。
    由 scripts/capture_image_versions.py 离线采集写入；报告生成时据此展示真实 vLLM/llama.cpp 版本。"""
    __tablename__ = "image_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    image_repo = Column(String(500), nullable=False)
    image_tag = Column(String(255), nullable=False)
    engine = Column(String(50), default="vllm")          # vllm / llama_cpp
    vllm_version = Column(String(100), nullable=True)     # 语义版号, 如 v0.22.1 / 0.8.3
    llama_cpp_build = Column(String(100), nullable=True)  # llama.cpp build 号
    python_version = Column(String(100), nullable=True)
    torch_version = Column(String(100), nullable=True)
    cuda_version = Column(String(100), nullable=True)
    build_commit = Column(String(100), nullable=True)
    source = Column(String(255), default="image")         # image-run / image-label
    captured_at = Column(DateTime, default=datetime.datetime.utcnow)


# ---------- 性能测试结果 ----------

class PerfResult(Base):
    __tablename__ = "perf_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_run_id = Column(Integer, ForeignKey("model_runs.id", ondelete="CASCADE"))

    round_num = Column(Integer, default=1)  # 多轮测试编号
    strategy_id = Column(String(255))
    output_type = Column(String(50))  # short / long
    concurrency = Column(Integer)
    input_len = Column(Integer)
    output_len = Column(Integer)

    throughput_tok_s = Column(Float, nullable=True)
    request_throughput = Column(Float, nullable=True)
    mean_ttft_ms = Column(Float, nullable=True)
    median_ttft_ms = Column(Float, nullable=True)
    p99_ttft_ms = Column(Float, nullable=True)
    mean_tpot_ms = Column(Float, nullable=True)
    median_tpot_ms = Column(Float, nullable=True)
    p99_tpot_ms = Column(Float, nullable=True)
    mean_itl_ms = Column(Float, nullable=True)
    median_itl_ms = Column(Float, nullable=True)
    p99_itl_ms = Column(Float, nullable=True)

    # vLLM bench 完整 JSON 报告
    raw_report = Column(JSON, nullable=True)

    error = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    model_run = relationship("ModelRun", back_populates="perf_results")


# ---------- 准确率测试结果 ----------

class AccResult(Base):
    __tablename__ = "acc_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_run_id = Column(Integer, ForeignKey("model_runs.id", ondelete="CASCADE"))

    dataset = Column(String(100), nullable=False)
    accuracy = Column(Float, nullable=True)
    limit = Column(Integer, default=200)

    error = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    model_run = relationship("ModelRun", back_populates="acc_results")


# ---------- 网关协议与工具测试结果 ----------

class GatewayResult(Base):
    __tablename__ = "gateway_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_run_id = Column(Integer, ForeignKey("model_runs.id", ondelete="CASCADE"))

    category = Column(String(50), nullable=False)  # reachability / protocol / feature
    test_item = Column(String(255), nullable=False)  # 测试项名称
    protocol = Column(String(50), default="system")  # openai / anthropic / responses / system
    status = Column(String(20), default="SKIP")  # PASS / FAIL / SKIP
    latency_ms = Column(Float, nullable=True)
    message = Column(Text, nullable=True)
    raw_details = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    model_run = relationship("ModelRun", back_populates="gateway_results")


# ---------- 功能/质量专项测试结果 ----------

class FeatureResult(Base):
    """功能测试结果 (PASS/FAIL/SKIP)，由 backend/services/features/ 各模块产出"""
    __tablename__ = "feature_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_run_id = Column(Integer, ForeignKey("model_runs.id", ondelete="CASCADE"))

    category = Column(String(50), default="feature")       # feature / vision
    feature_key = Column(String(50), nullable=False)       # needle / math / garble / tool_smoke / agent_replay / multimodal
    test_item = Column(String(255), nullable=False)        # 展示名，如 "大海捞针（长上下文检索）"
    status = Column(String(20), default="SKIP")            # PASS / FAIL / SKIP
    latency_ms = Column(Float, nullable=True)
    message = Column(Text, nullable=True)
    raw_details = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    model_run = relationship("ModelRun", back_populates="feature_results")


# ---------- 硬件组管理 ----------

class HardwareGroup(Base):
    __tablename__ = "hardware_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False, comment="硬件组名称")
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ---------- 测试用例模板 ----------

class TestTemplate(Base):
    __tablename__ = "test_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, comment="模板名称")
    description = Column(String(500), nullable=True)
    num_prompts = Column(Integer, default=300)
    input_lens = Column(JSON, default=list, comment="输入 Token 长度数组，如 [128, 512, 1024]")
    output_lens = Column(JSON, default=list, comment="输出 Token 长度数组，如 [128, 512]")
    concurrencies = Column(JSON, default=list, comment="并发数梯度数组，如 [1, 4, 8, 16, 32]")
    datasets = Column(JSON, default=list, comment="测试数据集，如 ['mmlu', 'ceval']")
    acc_limit = Column(Integer, default=200)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ---------- 数据集明细管理 ----------

class DatasetInfo(Base):
    __tablename__ = "dataset_infos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False, comment="数据集名称: mmlu/ceval/gsm8k等")
    source = Column(String(100), default="ModelScope/EvalScope", comment="来源库或仓库ID")
    difficulty = Column(String(50), default="standard", comment="难度分级: standard/hard/ultra")
    category_group = Column(String(50), default="通用基准", comment="分类分组: 竞赛数学/真实对战/博士问答/长文本/代码编程/通用基准")
    status = Column(String(20), default="ready", comment="ready / downloading / failed")
    download_progress = Column(Float, default=100.0)
    sample_count = Column(Integer, default=0, comment="样本总量")
    description = Column(String(500), nullable=True)
    file_path = Column(String(500), nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)



# ---------- Docker 镜像管理 ----------

class ImageCategory(Base):
    """镜像分类（文件夹式目录，支持层级）"""
    __tablename__ = "image_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, comment="分类/文件夹名称")
    parent_id = Column(Integer, ForeignKey("image_categories.id", ondelete="SET NULL"), nullable=True, comment="父分类 ID（一级目录为 NULL）")
    description = Column(String(500), nullable=True)
    sort_order = Column(Integer, default=0, comment="排序权重，越小越靠前")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class DockerImage(Base):
    __tablename__ = "docker_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, comment="镜像显示名称")
    image_tag = Column(String(255), nullable=False, comment="Docker 镜像标签，如 nvcr.io/nvidia/vllm:v0.6.3-thor")
    download_url = Column(String(500), nullable=True, comment="镜像文件/仓库下载 URL")
    hardware_group = Column(String(100), default="NVIDIA_jetson_AGX_Thor", nullable=True)
    status = Column(String(20), default="ready", comment="ready / downloading / failed / deployed")
    description = Column(String(500), nullable=True)

    # ---- 重构新增字段（迁移脚本补充，保留旧数据） ----
    category_id = Column(Integer, ForeignKey("image_categories.id", ondelete="SET NULL"), nullable=True, comment="所属分类（文件夹）")
    source = Column(String(30), default="custom", nullable=True, comment="来源: official(沐曦等官方目录) / registry(内网registry) / tar(离线文件) / custom(自定义)")
    chip_type = Column(String(50), nullable=True, comment="适配芯片类型: metax_c500 / nvidia_thor 等，部署时与设备 chip_type 匹配")
    arch = Column(String(20), default="amd64", nullable=True, comment="架构: amd64 / arm64 / aarch64")
    source_ref = Column(String(500), nullable=True, comment="外部来源标识（沐曦镜像 ID / 下载地址）")
    size_bytes = Column(BigInteger, nullable=True, comment="镜像大小(字节)")
    pull_command = Column(Text, nullable=True, comment="完整 docker pull 命令（沐曦登录后获取）")
    install_step = Column(Text, nullable=True, comment="安装/使用说明")
    pulled = Column(Boolean, default=False, nullable=True, comment="是否已在设备上完成拉取")
    pulled_at = Column(DateTime, nullable=True, comment="最近一次拉取完成时间")
    sync_at = Column(DateTime, nullable=True, comment="最近一次从外部目录同步时间")
    latest = Column(Boolean, default=True, nullable=True, comment="同来源下是否最新版本")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class DeviceImageBinding(Base):
    """镜像-设备 多对多绑定与部署状态跟踪"""
    __tablename__ = "device_image_bindings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    image_id = Column(Integer, ForeignKey("docker_images.id", ondelete="CASCADE"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), default="pending", comment="pending / pulling / ready / failed")
    message = Column(Text, nullable=True, comment="最近一次部署输出（脱敏后）")
    pulled_at = Column(DateTime, nullable=True, comment="最近一次拉取成功时间")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class ImageDeployLog(Base):
    """镜像部署历史日志（脱敏后落库，后台可查）"""
    __tablename__ = "image_deploy_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    image_id = Column(Integer, ForeignKey("docker_images.id", ondelete="CASCADE"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=True)
    binding_id = Column(Integer, ForeignKey("device_image_bindings.id", ondelete="SET NULL"), nullable=True)
    level = Column(String(20), default="INFO", comment="INFO / WARNING / ERROR")
    message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)


# ---------- 日志 ----------

class TaskLog(Base):
    __tablename__ = "task_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"))

    level = Column(String(20), default="INFO")  # INFO / WARNING / ERROR
    model_slug = Column(String(255), nullable=True)
    module = Column(String(30), default="system")  # system / container / vllm / perf / accuracy
    message = Column(Text, nullable=False)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    task = relationship("Task", back_populates="logs")
