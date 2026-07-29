"""
AONI 平台 — 多芯片硬件抽象层 (Hardware Abstraction Layer - HAL)
支持 NVIDIA Jetson AGX Thor, 沐曦 MetaX C500/N260, 服务器 RTX 5090, 摩尔线程 MUSA
"""
from backend.services.hardware.base import BaseHardwareDriver
from backend.services.hardware.nvidia import NvidiaDriver
from backend.services.hardware.metax import MetaXDriver
from backend.services.hardware.mthreads import MThreadsDriver


def get_hardware_driver(chip_type: str) -> BaseHardwareDriver:
    """根据 chip_type 动态实例化对应的硬件驱动程序"""
    chip_lower = (chip_type or "nvidia_thor").lower()
    if "metax" in chip_lower or "c500" in chip_lower or "n260" in chip_lower:
        return MetaXDriver()
    elif "mthreads" in chip_lower or "musa" in chip_lower or "摩尔" in chip_lower:
        return MThreadsDriver()
    elif "5090" in chip_lower or "rtx" in chip_lower:
        return NvidiaDriver(chip_variant="rtx5090")
    else:
        # 默认 NVIDIA Jetson AGX Thor
        return NvidiaDriver(chip_variant="thor")
