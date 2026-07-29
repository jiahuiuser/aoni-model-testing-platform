"""
硬件抽象层基类 — BaseHardwareDriver
定义算力芯片硬件检测、Docker 挂载标志与健康排障的标准接口
"""
from abc import ABC, abstractmethod


class BaseHardwareDriver(ABC):

    @property
    @abstractmethod
    def chip_name(self) -> str:
        """芯片类型识别名"""
        pass

    @property
    @abstractmethod
    def smi_command(self) -> str:
        """用于检测硬件监控状态的工具 Shell 命令 (如 nvidia-smi, mx-smi, musa-smi)"""
        pass

    @abstractmethod
    def parse_gpu_metrics(self, stdout: str) -> dict:
        """解析工具输出，返回标准化的 GPU/NPU 指标字典"""
        pass

    @abstractmethod
    def get_docker_runtime_flags(self) -> list[str]:
        """获取适配该芯片架构的 Docker 运行标志位 (如 --runtime=nvidia 或 --device /dev/mx0)"""
        pass

    @abstractmethod
    def run_doctor_check(self, runner) -> dict:
        """针对该芯片的专属排障自检，返回诊断结果字典"""
        pass
