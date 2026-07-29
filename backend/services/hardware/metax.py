"""
沐曦 MetaX 芯片驱动实现 — 支持 沐曦 C500 与 N260 算力卡 (mx-smi)
"""
from backend.services.hardware.base import BaseHardwareDriver


class MetaXDriver(BaseHardwareDriver):

    @property
    def chip_name(self) -> str:
        return "沐曦 MetaX (C500 / N260)"

    @property
    def smi_command(self) -> str:
        return "mx-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv,noheader 2>/dev/null || mx-smi -L 2>/dev/null"

    def parse_gpu_metrics(self, stdout: str) -> dict:
        result = {"gpu_info": "", "gpu_count": 0, "gpu_details": []}
        if not stdout:
            return result
        lines = [l.strip() for l in stdout.strip().split("\n") if l.strip()]
        result["gpu_count"] = len(lines)
        gpu_names = []
        for line in lines:
            if "," in line:
                parts = [p.strip() for p in line.split(",")]
                gpu_names.append(parts[0])
            elif "GPU" in line or "MetaX" in line:
                gpu_names.append(line)
        result["gpu_info"] = ", ".join(gpu_names) if gpu_names else f"沐曦 MetaX GPGPU ({len(lines)}卡)"
        return result

    def get_docker_runtime_flags(self) -> list[str]:
        return ["--device", "/dev/mx0", "--device", "/dev/mx_ctl"]

    def run_doctor_check(self, runner) -> dict:
        """针对 沐曦 C500 / N260 算力卡的专项排障检查"""
        res = runner.run_shell("mx-smi 2>/dev/null || which mx-smi", timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            return {
                "ok": True,
                "name": "沐曦 (MetaX) 驱动与 mx-smi 识别",
                "detail": f"成功检测到 沐曦 算力工具链 mx-smi: {res.stdout.strip()[:150]}",
                "remediation": None
            }
        return {
            "ok": False,
            "name": "沐曦 (MetaX) 驱动与 mx-smi 识别",
            "detail": "未检测到 mx-smi 管理工具，沐曦 C500/N260 驱动可能未装载或环境变量未配置",
            "remediation": "请确认已安装 沐曦 MXM/Macs 驱动包，并加载 mx-smi:\nsudo modprobe metax && export PATH=$PATH:/usr/local/metax/bin"
        }
