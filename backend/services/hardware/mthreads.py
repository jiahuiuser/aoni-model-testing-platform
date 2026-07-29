"""
摩尔线程 MUSA 芯片驱动实现 — 支持 摩尔线程 GPU 算力卡 (musa-smi)
"""
from backend.services.hardware.base import BaseHardwareDriver


class MThreadsDriver(BaseHardwareDriver):

    @property
    def chip_name(self) -> str:
        return "摩尔线程 MThreads (MUSA Architecture)"

    @property
    def smi_command(self) -> str:
        return "musa-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv,noheader 2>/dev/null || musa-smi -L 2>/dev/null"

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
            elif "MT-" in line or "MUSA" in line or "Moore" in line:
                gpu_names.append(line)
        result["gpu_info"] = ", ".join(gpu_names) if gpu_names else f"摩尔线程 MUSA GPU ({len(lines)}卡)"
        return result

    def get_docker_runtime_flags(self) -> list[str]:
        return ["--device", "/dev/musa0", "--device", "/dev/musa_ctl"]

    def run_doctor_check(self, runner) -> dict:
        """针对 摩尔线程 MUSA 算力卡的专项排障检查"""
        res = runner.run_shell("musa-smi 2>/dev/null || which musa-smi", timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            return {
                "ok": True,
                "name": "摩尔线程 (MUSA) 驱动与 musa-smi 识别",
                "detail": f"成功检测到 摩尔线程 算力工具链 musa-smi: {res.stdout.strip()[:150]}",
                "remediation": None
            }
        return {
            "ok": False,
            "name": "摩尔线程 (MUSA) 驱动与 musa-smi 识别",
            "detail": "未检测到 musa-smi 管理工具，摩尔线程 MUSA 驱动可能未装载",
            "remediation": "请确认已安装 摩尔线程 MUSA SDK 与内核驱动:\nsudo systemctl restart musa-daemon && export PATH=$PATH:/usr/local/musa/bin"
        }
