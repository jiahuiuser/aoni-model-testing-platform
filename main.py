#!/usr/bin/env python3
"""
AONI 智能体模型平台运维总控工具 (main.py)
"""
import os
import argparse
import logging
from pathlib import Path

# 配置基本日志格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# 获取当前项目的根路径
PROJECT_ROOT = Path(__file__).resolve().parent

def run_sync_action(args):
    """从 ModelScope 同步模型，先在本地进行 Docker 部署验证；测试 PASS 后才打包上传 TOS，避免无效上传"""
    from src.downloader import download_with_modelscope, download_with_huggingface, create_tarball, check_disk_space
    from src.uploader import load_tos_client, upload_to_tos
    from src.csv_handler import update_csv_result
    from src.test_runner import (
        verify_sudo, stop_existing_container, start_container,
        wait_for_vllm, chat_test
    )
    from datetime import datetime

    env_path = PROJECT_ROOT / "config" / ".env"
    csv_path = PROJECT_ROOT / "data" / "aoni_models_thor128g.csv"
    os.makedirs(csv_path.parent, exist_ok=True)
    if not csv_path.exists() and Path("/home/sd1/Desktop/aoni_models_thor128g.csv").exists():
        import shutil
        shutil.copy("/home/sd1/Desktop/aoni_models_thor128g.csv", csv_path)

    log_dir = PROJECT_ROOT / "logs"
    os.makedirs(log_dir, exist_ok=True)

    models_dir = Path("/home/sd1/models")
    os.makedirs(models_dir, exist_ok=True)

    # 磁盘空间 100G 安全预检
    check_disk_space(str(models_dir), min_free_gb=100.0)

    # 验证 sudo
    verify_sudo()

    # 初始化 TOS 客户端
    client, bucket = load_tos_client(str(env_path))
    log.info(f"TOS 客户端认证成功 (存储桶: {bucket})")

    tasks = [
        # #40 Qwen3.6 35B-A3B (ModelScope GGUF Q4_K_M)
        {
            "row_idx": "40",
            "name": "Qwen3.6-35B-A3B-GGUF",
            "source": "ms",
            "ms_repo": "unsloth/Qwen3.6-35B-A3B-GGUF",
            "ms_include": ["*Qwen3.6-35B-A3B-UD-Q4_K_M.gguf*"],
            "tos_key": "models/qwen/Qwen3.6-35B-A3B.tar.gz",
            "port": 8300,
            "model_name": "Qwen3.6-35B-A3B-UD-Q4_K_M.gguf",
            "docker_cmd_fn": lambda tmp_dir: f"docker run -it --rm --runtime=nvidia --network host -v {tmp_dir}:/models ghcr.io/nvidia-ai-iot/llama_cpp:latest-jetson-thor llama-server -m /models/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf -ngl 999 -c 8192 --host 0.0.0.0 --port 8300"
        },
        # #10 Gemma 4 26B-A4B (ModelScope GGUF Q4_K_XL)
        {
            "row_idx": "10",
            "name": "Gemma-4-26B-A4B-GGUF",
            "source": "ms",
            "ms_repo": "unsloth/gemma-4-26B-A4B-it-qat-GGUF",
            "ms_include": ["*gemma-4-26B-A4B-it-qat-UD-Q4_K_XL.gguf*"],
            "tos_key": "models/gemma/Gemma-4-26B-A4B.tar.gz",
            "port": 8300,
            "model_name": "gemma-4-26B-A4B-it-qat-UD-Q4_K_XL.gguf",
            "docker_cmd_fn": lambda tmp_dir: f"docker run -it --rm --runtime=nvidia --network host -v {tmp_dir}:/models ghcr.io/nvidia-ai-iot/llama_cpp:latest-jetson-thor llama-server -m /models/gemma-4-26B-A4B-it-qat-UD-Q4_K_XL.gguf -ngl 999 -c 8192 --host 0.0.0.0 --port 8300"
        },
        # #14 GPT OSS 120B (ModelScope GGUF Q4_K_M)
        {
            "row_idx": "14",
            "name": "GPT-OSS-120B-GGUF",
            "source": "ms",
            "ms_repo": "unsloth/gpt-oss-120b-GGUF",
            "ms_include": ["Q4_K_M/*"],
            "tos_key": "models/openai/GPT-OSS-120B.tar.gz",
            "port": 8300,
            "model_name": "gpt-oss-120b-Q4_K_M-00001-of-00002.gguf",
            "docker_cmd_fn": lambda tmp_dir: f"docker run -it --rm --runtime=nvidia --network host -v {tmp_dir}:/models ghcr.io/nvidia-ai-iot/llama_cpp:latest-jetson-thor llama-server -m /models/Q4_K_M/gpt-oss-120b-Q4_K_M-00001-of-00002.gguf -ngl 999 -c 4096 --host 0.0.0.0 --port 8300"
        },
        # #19 MiniMax M2.7 (ModelScope GGUF Q4_K_M)
        {
            "row_idx": "19",
            "name": "MiniMax-M2.7-GGUF",
            "source": "ms",
            "ms_repo": "unsloth/MiniMax-M2.7-GGUF",
            "ms_include": ["UD-Q4_K_M/*"],
            "tos_key": "models/minimax/MiniMax-M2.7.tar.gz",
            "port": 8300,
            "model_name": "MiniMax-M2.7-UD-Q4_K_M-00001-of-00004.gguf",
            "docker_cmd_fn": lambda tmp_dir: f"docker run -it --rm --runtime=nvidia --network host -v {tmp_dir}:/models ghcr.io/nvidia-ai-iot/llama_cpp:latest-jetson-thor llama-server -m /models/UD-Q4_K_M/MiniMax-M2.7-UD-Q4_K_M-00001-of-00004.gguf -ngl 999 -c 4096 --host 0.0.0.0 --port 8300"
        },
    ]

    # 按需过滤或全部跑完
    if args.task:
        tasks = [t for t in tasks if args.task.lower() in t["name"].lower()]
        if not tasks:
            log.error(f"未找到匹配的任务: {args.task}")
            return

    for task in tasks:
        name = task["name"]
        row_idx = task["row_idx"]
        log.info(f"\n==================== 【#{row_idx} {name}】本地下载-测试-上架开始 ====================")
        
        # 100G 磁盘空间校验
        check_disk_space(str(models_dir), min_free_gb=100.0)

        tmp_dir = models_dir / f".tmp_{name}"
        tarball_path = models_dir / f"{name}.tar.gz"
        task_log = log_dir / f"sync_test_{name}.log"

        try:
            # 1. 本地 ModelScope 下载
            needs_download = True
            if tmp_dir.exists():
                completed_files = [
                    os.path.join(dp, f)
                    for dp, dn, fn in os.walk(tmp_dir)
                    for f in fn
                    if not any(f.endswith(ext) for ext in ['.incomplete', '.temp', '.parallel_tmp', '.tmp'])
                ]
                downloaded_size = sum(os.path.getsize(f) for f in completed_files) / (1024**3)
                expected_size = 30.0 if "MiniMax" in name or "Llama" in name else 5.0
                if downloaded_size > expected_size:
                    log.info(f"  本地已存在完整的模型文件 (%.2f GB)，跳过下载直接开始本地测试", downloaded_size)
                    needs_download = False

            if needs_download:
                if task.get("source") == "hf":
                    download_with_huggingface(
                        repo_id=task["repo_id"],
                        local_dir=str(tmp_dir),
                        include=task.get("include"),
                        min_free_gb=100.0
                    )
                else:
                    download_with_modelscope(
                        repo_id=task["ms_repo"],
                        local_dir=str(tmp_dir),
                        include=task.get("ms_include"),
                        min_free_gb=100.0
                    )

            # 2. 本地拉起 Docker 容器验证测试
            log.info("  [Local Test] 启动本地容器校验推理服务...")
            stop_existing_container()

            local_cmd = task["docker_cmd_fn"](str(tmp_dir))
            started = start_container(local_cmd, task_log)

            test_passed = False
            error_reason = "CONTAINER_START_FAILED"

            if started:
                ready = wait_for_vllm(task_log, port=task["port"])
                if ready:
                    ok, result_msg = chat_test(task["model_name"], task_log, port=task["port"])
                    if ok:
                        test_passed = True
                        log.info(f"  ✓ 本地推理部署测试 PASS！回答: {result_msg}")
                    else:
                        error_reason = result_msg
                else:
                    error_reason = "VLLM_STARTUP_TIMEOUT"

            stop_existing_container()

            # 3. 根据测试结果分支处理
            if not test_passed:
                log.error(f"  ❌ 本地测试失败 ({error_reason})，放弃打包与 TOS 上传，节省带宽与空间！")
                update_csv_result(csv_path, row_idx, f"FAIL: {error_reason}")
            else:
                # 4. 测试 PASS 后打包与上传 TOS
                log.info("  [Tarball & Upload] 本地验证通过，开始打包并上传 TOS...")
                if tarball_path.exists():
                    os.remove(tarball_path)
                create_tarball(str(tmp_dir), str(tarball_path), label=name, min_free_gb=100.0)

                upload_to_tos(
                    client=client,
                    bucket=bucket,
                    local_path=str(tarball_path),
                    remote_key=task["tos_key"],
                    label=name
                )

                # 更新 CSV 文件状态与时间戳
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                update_csv_result(csv_path, row_idx, f"PASS ({now_str})")
                log.info(f"  ✓ CSV 记录更新完成: #{row_idx} -> PASS ({now_str})")

        except Exception as e:
            log.error(f"❌ 【{name}】流程异常: {e}")
            update_csv_result(csv_path, row_idx, f"FAIL: {e}")
        finally:
            # 清理临时文件，保护磁盘空间
            stop_existing_container()
            if tarball_path.exists():
                os.remove(tarball_path)
            if tmp_dir.exists():
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
            log.info(f"【{name}】本地测试与清理完成 🧹\n")


def run_test_action(args):
    """运行多模型自动化部署与对话测试校验"""
    from src.test_runner import run_tests_loop

    csv_path = PROJECT_ROOT / "data" / "aoni_models_thor128g.csv"
    log_dir = PROJECT_ROOT / "logs"
    models_dir = Path("/home/sd1/models")

    run_tests_loop(
        csv_path=csv_path,
        log_dir=log_dir,
        models_dir=models_dir,
        start_idx=args.start,
        end_idx=args.end,
        resume=args.resume
    )

def run_perf_action(args):
    """对 PASS 模型执行矩阵化性能测试"""
    from src.benchmark.perf_runner import run_perf_benchmark

    csv_path = PROJECT_ROOT / "data" / "aoni_models_thor128g.csv"
    strategy_csv = PROJECT_ROOT / "data" / "benchmark_strategies.csv"
    log_dir = PROJECT_ROOT / "logs" / "perf"
    report_dir = PROJECT_ROOT / "reports" / "perf"

    run_perf_benchmark(
        csv_path=csv_path,
        strategy_csv=strategy_csv,
        log_dir=log_dir,
        report_dir=report_dir,
        model_slug=args.model,
        resume=args.resume,
    )


def run_accuracy_action(args):
    """对 PASS 模型执行准确率评测"""
    from src.benchmark.accuracy_runner import run_accuracy_benchmark

    csv_path = PROJECT_ROOT / "data" / "aoni_models_thor128g.csv"
    log_dir = PROJECT_ROOT / "logs" / "accuracy"
    report_dir = PROJECT_ROOT / "reports" / "accuracy"

    datasets = None
    if args.datasets:
        datasets = [d.strip() for d in args.datasets.split(",")]

    run_accuracy_benchmark(
        csv_path=csv_path,
        log_dir=log_dir,
        report_dir=report_dir,
        datasets=datasets,
        limit=args.limit,
        model_slug=args.model,
    )


def run_download_datasets_action(args):
    """从 ModelScope 下载评测数据集"""
    from src.benchmark.dataset_downloader import download_all_datasets, get_available_datasets

    save_dir = PROJECT_ROOT / "data" / "datasets"

    if args.list:
        available = get_available_datasets()
        log.info(f"可用评测数据集: {', '.join(available)}")
        return

    datasets = None
    if args.datasets:
        datasets = [d.strip() for d in args.datasets.split(",")]

    results = download_all_datasets(save_dir, datasets)
    success = sum(1 for v in results.values() if v)
    log.info(f"数据集下载完成: {success}/{len(results)} 成功")


def run_report_action(args):
    """基于已有测试结果生成模型报告"""
    from src.benchmark.report_generator import batch_generate_reports

    perf_report_dir = PROJECT_ROOT / "reports" / "perf"
    acc_report_dir = PROJECT_ROOT / "reports" / "accuracy"
    output_dir = PROJECT_ROOT / "reports"
    strategy_csv = PROJECT_ROOT / "data" / "benchmark_strategies.csv"

    batch_generate_reports(
        perf_report_dir=perf_report_dir,
        acc_report_dir=acc_report_dir,
        output_dir=output_dir,
        strategy_csv=strategy_csv,
    )
    log.info("所有报告已生成到 reports/ 目录")


def main():
    parser = argparse.ArgumentParser(description="AONI 智能体模型平台运维总控工具")
    subparsers = parser.add_subparsers(dest="command", help="支持的操作命令")

    # 1. sync 量化拉取同步命令
    sync_parser = subparsers.add_parser("sync", help="同步量化模型并打包上传到 TOS 存储")
    sync_parser.add_argument("--task", type=str, default="", help="仅执行指定的任务名模糊匹配，默认执行全部")

    # 2. test 自动化测试运行命令
    test_parser = subparsers.add_parser("test", help="执行自动化容器模型测试与 CSV 更新")
    test_parser.add_argument("--start", type=int, default=1, help="测试起始行序号 (默认 1)")
    test_parser.add_argument("--end", type=int, default=9999, help="测试截止行序号 (默认 9999)")
    test_parser.add_argument("--resume", action="store_true", help="启用断点续测模式，跳过已 PASS 的模型")

    # 3. perf 性能基准测试命令
    perf_parser = subparsers.add_parser("perf", help="矩阵化性能基准测试 (vLLM bench serve)")
    perf_parser.add_argument("--model", type=str, default=None, help="指定单个模型 slug 测试 (默认全部 PASS 模型)")
    perf_parser.add_argument("--resume", action="store_true", help="启用断点续测")

    # 4. accuracy 准确率测试命令
    acc_parser = subparsers.add_parser("accuracy", help="准确率评测 (EvalScope + ModelScope 数据集)")
    acc_parser.add_argument("--model", type=str, default=None, help="指定单个模型 slug 测试")
    acc_parser.add_argument("--datasets", type=str, default=None, help="指定数据集 (逗号分隔, 如 mmlu,ceval,gsm8k)")
    acc_parser.add_argument("--limit", type=int, default=500, help="每数据集抽样数 (默认 500)")

    # 5. download-datasets 数据集下载命令
    ds_parser = subparsers.add_parser("download-datasets", help="从 ModelScope 下载评测数据集")
    ds_parser.add_argument("--datasets", type=str, default=None, help="指定数据集 (逗号分隔, 默认全部)")
    ds_parser.add_argument("--list", action="store_true", help="列出可用数据集")

    # 6. report 报告生成命令
    report_parser = subparsers.add_parser("report", help="基于测试结果生成模型评测报告")

    args = parser.parse_args()

    if args.command == "sync":
        run_sync_action(args)
    elif args.command == "test":
        run_test_action(args)
    elif args.command == "perf":
        run_perf_action(args)
    elif args.command == "accuracy":
        run_accuracy_action(args)
    elif args.command == "download-datasets":
        run_download_datasets_action(args)
    elif args.command == "report":
        run_report_action(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
