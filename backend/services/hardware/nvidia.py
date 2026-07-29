"""
NVIDIA 芯片驱动实现 — 支持 Jetson AGX Thor 与 服务器 RTX 5090
"""
from backend.services.hardware.base import BaseHardwareDriver


class NvidiaDriver(BaseHardwareDriver):

    def __init__(self, chip_variant: str = "thor"):
        self.variant = chip_variant  # thor / rtx5090 / generic

    @property
    def chip_name(self) -> str:
        if self.variant == "thor":
            return "NVIDIA Jetson AGX Thor (T5000)"
        elif self.variant == "rtx5090":
            return "NVIDIA GeForce RTX 5090"
        return "NVIDIA GPU"

    @property
    def smi_command(self) -> str:
        return "nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv,noheader 2>/dev/null"

    def parse_gpu_metrics(self, stdout: str) -> dict:
        result = {"gpu_info": "", "gpu_count": 0, "gpu_details": []}
        if not stdout:
            return result
        lines = [l.strip() for l in stdout.strip().split("\n") if l.strip()]
        result["gpu_count"] = len(lines)
        gpu_names = []
        for line in lines:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 1:
                gpu_names.append(parts[0])
            if len(parts) >= 4:
                result["gpu_details"].append({
                    "name": parts[0],
                    "memory_total": parts[1],
                    "memory_used": parts[2],
                    "utilization": parts[3]
                })
        result["gpu_info"] = ", ".join(gpu_names) if gpu_names else stdout
        return result

    def get_docker_runtime_flags(self) -> list[str]:
        return ["--runtime=nvidia"]

    def run_doctor_check(self, runner) -> dict:
        """针对 NVIDIA 算力节点的专项检查"""
        res = runner.run_shell("nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null", timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            return {
                "ok": True,
                "name": "NVIDIA 驱动与 GPU 识别",
                "detail": f"成功识别 GPU 硬件: {res.stdout.strip().replace('\n', ', ')}",
                "remediation": None
            }
        # 如果是 Jetson Thor，检测 tegrastats
        teg = runner.run_shell("cat /proc/device-tree/model 2>/dev/null", timeout=5)
        if teg.returncode == 0 and teg.stdout.strip():
            return {
                "ok": True,
                "name": "NVIDIA Jetson 硬件识别",
                "detail": f"成功识别 Jetson 板卡: {teg.stdout.strip()}",
                "remediation": None
            }
        return {
            "ok": False,
            "name": "NVIDIA 驱动与 GPU 识别",
            "detail": f"未检测到 nvidia-smi 或 CUDA 驱动不可用: {res.stderr[:100]}",
            "remediation": "请确认宿主机已正确安装 NVIDIA 驱动与 nvidia-container-toolkit:\nsudo apt-get install -y nvidia-container-toolkit && sudo systemctl restart docker"
        }
