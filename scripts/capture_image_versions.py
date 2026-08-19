#!/usr/bin/env python3
"""
离线采集推理镜像的运行时版本，写入 image_versions 表，供报告生成直接查库。

用法:
  python3 scripts/capture_image_versions.py            # 采集全部候选镜像
  python3 scripts/capture_image_versions.py <repo>:<tag>   # 只采集指定镜像

原理:
  - 优先从 docker inspect 的 label/ENV 读取 build commit、image tag、CUDA 版本（离线、零副作用）。
  - 语义版号(vllm.__version__ / llama-server --version)需运行一次
    `docker run --rm <image> ...` 获取；仅打印版本，不起服务。
  - 结果 upsert 进 image_versions 表（repo:tag 唯一）。
"""
import os, sys, json, subprocess, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.models import ImageVersion
from backend.database import session_factory, init_db

init_db()  # 确保 image_versions 等表已创建

# 平台实际用到的候选镜像（也可单独传入 repo:tag）
CANDIDATES = [
    ("aoni-docker-cn-guangzhou.cr.volces.com/public/llm", "vllm-openai-nightly-aarch64", "vllm"),
    ("aoni-docker-cn-guangzhou.cr.volces.com/public/llm", "nightly-aarch64", "vllm"),
    ("aoni/vllm/vllm-openai", "nightly-aarch64", "vllm"),
    ("aoni/vllm/vllm-openai", "v0.20.0-ubuntu2404", "vllm"),
    ("aoni/nvidia-ai-iot/vllm", "latest-jetson-thor", "vllm"),
    ("ghcr.io/nvidia-ai-iot/llama_cpp", "latest-jetson-thor", "llama_cpp"),
]


def _sh(args, timeout=30):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return r.stdout.strip()
    except Exception:
        return ""


def inspect_image(image):
    """返回 image labels + env 里的版本线索（离线）。"""
    labels_s = _sh(["sudo", "docker", "inspect", image, "--format", "{{json .Config.Labels}}"])
    env_s = _sh(["sudo", "docker", "inspect", image, "--format", "{{range .Config.Env}}{{println .}}{{end}}"])
    labels, env = {}, {}
    try:
        labels = json.loads(labels_s) if labels_s else {}
    except Exception:
        pass
    for line in env_s.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            env[k] = v
    return labels, env


def run_version(image, engine):
    """跑一次容器打印语义版本（离线、仅查版本；覆盖镜像 ENTRYPOINT 以免吞参）。"""
    if engine == "llama_cpp":
        # llama-server 依赖命中断言 GPU stub 不能直接跑；build 号从库文件名离线读取(bNNNN)
        out = _sh(
            ["sudo", "docker", "run", "--rm", "--entrypoint", "sh", image, "-c",
             "ls /usr/local/lib/libllama-common.so.0.0.* 2>/dev/null || ls /opt/llama.cpp/install/lib/libllama-common.so.0.0.* 2>/dev/null"],
            timeout=40)
        build = None
        for line in out.splitlines():
            parts = line.strip().rstrip("/").split(".")
            if parts:
                try:
                    build = "b" + parts[-1]
                except Exception:
                    pass
        return {"llama_cpp_build": build}
    py = (
        "import vllm,sys,torch;"
        "print('VLLM='+str(vllm.__version__));"
        "print('PY='+sys.version.split()[0]);"
        "print('TORCH='+str(torch.__version__))"
    )
    out = _sh(["sudo", "docker", "run", "--rm", "--entrypoint", "python3",
               image, "-c", py], timeout=60)
    d = {}
    for line in out.splitlines():
        if line.startswith("VLLM="):
            d["vllm_version"] = line.split("=", 1)[1]
        elif line.startswith("PY="):
            d["python_version"] = line.split("=", 1)[1]
        elif line.startswith("TORCH="):
            d["torch_version"] = line.split("=", 1)[1]
    return d


def capture(repo, tag, engine):
    image = f"{repo}:{tag}"
    full = f"{repo}:{tag}"
    labels, env = inspect_image(image)
    if not labels and not env:
        return f"⚠️ 镜像不存在或无法读取: {full}"

    build_commit = (labels.get("ai.vllm.build.commit") or
                    env.get("VLLM_BUILD_COMMIT") or
                    labels.get("org.opencontainers.image.revision"))
    image_tag_hint = (labels.get("ai.vllm.image.tag") or
                      env.get("VLLM_IMAGE_TAG") or
                      labels.get("org.opencontainers.image.version"))
    cuda = env.get("CUDA_VERSION")

    # 语义版本（一次离线 run）
    sem = run_version(image, engine)

    rec = dict(
        image_repo=repo, image_tag=tag, engine=engine,
        build_commit=build_commit,
        cuda_version=cuda,
        vllm_version=sem.get("vllm_version"),
        python_version=sem.get("python_version"),
        torch_version=sem.get("torch_version"),
        llama_cpp_build=sem.get("llama_cpp_build"),
        source="image-run",
    )
    with session_factory() as db:
        row = db.query(ImageVersion).filter_by(image_repo=repo, image_tag=tag).first()
        if row is None:
            row = ImageVersion()
            db.add(row)
        for k, v in rec.items():
            setattr(row, k, v)
        db.commit()
        rid = row.id
    return (f"✅ {full} | commit={build_commit or '-'} | tag_hint={image_tag_hint or '-'} "
            f"| vllm={sem.get('vllm_version') or '-'} | llama={sem.get('llama_cpp_build') or '-'} "
            f"| py={sem.get('python_version') or '-'} | torch={sem.get('torch_version') or '-'} "
            f"| cuda={cuda or '-'}  -> id={rid}")


def main():
    if len(sys.argv) > 1:
        spec = sys.argv[1]
        if ":" in spec:
            repo, _, tag = spec.rpartition(":")
            engine = "llama_cpp" if "llama_cpp" in repo or "llama.cpp" in repo else "vllm"
            print(capture(repo, tag, engine))
        else:
            print("用法: capture_image_versions.py [repo:tag]")
        return
    for repo, tag, engine in CANDIDATES:
        print(capture(repo, tag, engine))


if __name__ == "__main__":
    main()
