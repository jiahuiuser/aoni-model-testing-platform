# 本地模型 vs 官网 —— 精度对比与量化权重下载对照

> 本文档记录 大模型测试平台本地 43 个模型与 NVIDIA Jetson AI Lab 官网（Thor 主线）的**版本/精度一致性**。
> 参考官网：[Jetson AI Lab Models](https://www.jetson-ai-lab.com/models/)
> 说明：官网模型页默认展示的 GGUF 只是 API-model / llama.cpp 备选，**Thor vLLM 主线程实际 serve 的量化 repo 见下表**（来源：官网页面内嵌 `inference-panel-config` 的 `thor_t5000::vLLM`）。
> 更新日期：2026-08-18

---

## 一、本地 vs 官网 43 模型对比总表

> 状态：`✅已对齐`（本地已量化且与官网一致） · `🔄已替换`（本次已从全精度替换为官网量化版） · `保留`（官网即全精度/无量化收益，本地维持） · `新增`（官网部署、本地原先未下载）

| # | 模型 | 本地实际 | 官网 Thor 量化 repo | 精度 | 状态 |
|---|------|---------|--------------------|------|------|
| 1 | Cosmos Reason 1 7B | `nvidia/Cosmos-Reason1-7B` | `nvidia/Cosmos-Reason1-7B` | FP16 | 新增 |
| 2 | Cosmos Reason 2 2B | GGUF (Kbenkhaled) | llama.cpp `Kbenkhaled/Cosmos-Reason2-2B-GGUF:Q8_0` | GGUF | 保留 |
| 3 | Cosmos Reason 2 8B | GGUF (Kbenkhaled) | llama.cpp `Kbenkhaled/Cosmos-Reason2-8B-GGUF:Q4_K_M` | GGUF | 保留 |
| 4 | FunctionGemma | `ggml-org/functiongemma-270m-it-GGUF` | llama.cpp `ggml-org/functiongemma-270m-it-GGUF` | FP8/GGUF | 🔄替换 |
| 5 | Gemma 3 12B | `RedHatAI/gemma-3-12b-it-quantized.w4a16` | `RedHatAI/gemma-3-12b-it-quantized.w4a16` | W4A16 | 🔄替换 |
| 6 | Gemma 3 1B | `google/gemma-3-1b-it` (bf16) | `google/gemma-3-1b-it` | FP16 | 保留 |
| 7 | Gemma 3 270M | `google/gemma-3-270m-it` (bf16) | `google/gemma-3-270m-it` | FP16 | 保留 |
| 8 | Gemma 3 27B | `RedHatAI/gemma-3-27b-it-quantized.w4a16` | `RedHatAI/gemma-3-27b-it-quantized.w4a16` | W4A16 | 🔄替换 |
| 9 | Gemma 3 4B | `RedHatAI/gemma-3-4b-it-quantized.w4a16` | `RedHatAI/gemma-3-4b-it-quantized.w4a16` | W4A16 | 🔄替换 |
| 10 | Gemma 4 26B-A4B | NVFP4 | `RedHatAI/gemma-4-26B-A4B-it-NVFP4` | NVFP4 | ✅已对齐 |
| 11 | Gemma 4 31B | `nvidia/Gemma-4-31B-IT-NVFP4` | `nvidia/Gemma-4-31B-IT-NVFP4` | NVFP4 | 🔄替换 |
| 12 | Gemma 4 E2B | `unsloth/gemma-4-E2B-it-NVFP4` | `unsloth/gemma-4-E2B-it-NVFP4` | NVFP4 | 🔄替换(GGUF→NVFP4) |
| 13 | Gemma 4 E4B | `unsloth/gemma-4-E4B-it-NVFP4` | `unsloth/gemma-4-E4B-it-NVFP4` | NVFP4 | 🔄替换(GGUF→NVFP4) |
| 14 | GPT OSS 120B | `openai/gpt-oss-120b` (mxfp4/NVFP4) | `openai/gpt-oss-120b` | NVFP4 | ✅已对齐 |
| 15 | GPT OSS 20B | `openai/gpt-oss-20b` (mxfp4/W4A16) | `openai/gpt-oss-20b` | W4A16 | ✅已对齐 |
| 16 | Llama 3.1 70B | `RedHatAI/Meta-Llama-3.1-70B-Instruct-quantized.w4a16` | `RedHatAI/Meta-Llama-3.1-70B-Instruct-quantized.w4a16` | W4A16 | ✅已对齐 |
| 17 | Llama 3.1 8B | `RedHatAI/Meta-Llama-3.1-8B-Instruct-quantized.w4a16` | `RedHatAI/Meta-Llama-3.1-8B-Instruct-quantized.w4a16` | W4A16 | 🔄替换 |
| 18 | Llama 3.2 3B | `espressor/meta-llama.Llama-3.2-3B-Instruct_W4A16` | `espressor/meta-llama.Llama-3.2-3B-Instruct_W4A16` | W4A16 | 🔄替换 |
| 19 | MiniMax M2.7 | GGUF (UD-Q4_K_M) | llama.cpp `unsloth/MiniMax-M2.7-GGUF`(UD-IQ4_XS) | GGUF | 保留(量化粒度不同) |
| 20 | Ministral 3 14B Instruct | FP8 | `mistralai/Ministral-3-14B-Instruct-2512` | FP8 | ✅已对齐 |
| 21 | Ministral 3 14B Reasoning | FP16 | `mistralai/Ministral-3-14B-Reasoning-2512` | FP16 | 保留(官方FP16) |
| 22 | Ministral 3 3B Instruct | FP8 | `mistralai/Ministral-3-3B-Instruct-2512` | FP8 | ✅已对齐 |
| 23 | Ministral 3 3B Reasoning | FP16 | `mistralai/Ministral-3-3B-Reasoning-2512` | FP16 | 保留(官方FP16) |
| 24 | Ministral 3 8B Instruct | FP8 | `mistralai/Ministral-3-8B-Instruct-2512` | FP8 | ✅已对齐 |
| 25 | Ministral 3 8B Reasoning | FP16 | `mistralai/Ministral-3-8B-Reasoning-2512` | FP16 | 保留(官方FP16) |
| 26 | Nemotron-3-Nano-Omni | NVFP4(Q4_K_M备选) | vLLM `nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4` / llama.cpp GGUF | NVFP4 | 🔄替换 |
| 27 | Nemotron Nano 12B VL | `nvidia/NVIDIA-Nemotron-Nano-12B-v2-VL-NVFP4-QAD` | `nvidia/NVIDIA-Nemotron-Nano-12B-v2-VL-NVFP4-QAD` | NVFP4-QAD | 🔄替换 |
| 28 | Nemotron Nano 9B v2 | `nvidia/NVIDIA-Nemotron-Nano-9B-v2-NVFP4` | `nvidia/NVIDIA-Nemotron-Nano-9B-v2-NVFP4` | NVFP4 | 🔄替换(并去重) |
| 29 | Nemotron3 Nano 30B-A3B | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4` | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4` | NVFP4 | 🔄替换 |
| 30 | Nemotron3 Nano 4B | GGUF Q4_K_M | llama.cpp `nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF` | Q4_K_M GGUF | 保留 |
| 31 | Qwen3 30B-A3B | `RedHatAI/Qwen3-30B-A3B-quantized.w4a16` | `RedHatAI/Qwen3-30B-A3B-quantized.w4a16` | W4A16 | 🔄替换 |
| 32 | Qwen3 32B | `RedHatAI/Qwen3-32B-quantized.w4a16` | `RedHatAI/Qwen3-32B-quantized.w4a16` | W4A16 | 🔄替换 |
| 33 | Qwen3 4B | `RedHatAI/Qwen3-4B-quantized.w4a16` | `RedHatAI/Qwen3-4B-quantized.w4a16` | W4A16 | 🔄替换 |
| 34 | Qwen3.5 0.8B | `Qwen/Qwen3.5-0.8B` (bf16) | `Qwen/Qwen3.5-0.8B` | BF16 | 保留(官方BF16) |
| 35 | Qwen3.5 27B | `Kbenkhaled/Qwen3.5-27B-NVFP4` | `Kbenkhaled/Qwen3.5-27B-NVFP4` | NVFP4 | 🔄替换 |
| 36 | Qwen3.5 35B-A3B | `AxionML/Qwen3.5-35B-A3B-NVFP4` | `AxionML/Qwen3.5-35B-A3B-NVFP4` | NVFP4 | 🔄替换 |
| 37 | Qwen3.5 4B | `AxionML/Qwen3.5-4B-NVFP4` | `AxionML/Qwen3.5-4B-NVFP4` | NVFP4 | 🔄替换 |
| 38 | Qwen3.5 9B | `AxionML/Qwen3.5-9B-NVFP4` | `AxionML/Qwen3.5-9B-NVFP4` | NVFP4 | 🔄替换 |
| 39 | Qwen3.6 27B | `nvidia/Qwen3.6-27B-NVFP4` | `nvidia/Qwen3.6-27B-NVFP4` | NVFP4 | 🔄替换 |
| 40 | Qwen3.6 35B-A3B | `nvidia/Qwen3.6-35B-A3B-NVFP4` | `nvidia/Qwen3.6-35B-A3B-NVFP4` | NVFP4 | ✅已对齐 |
| 41 | Qwen3-8B | `RedHatAI/Qwen3-8B-quantized.w4a16` | `RedHatAI/Qwen3-8B-quantized.w4a16` | W4A16 | 🔄替换 |
| 42 | Qwen3 VL 4B | `cpatonn/Qwen3-VL-4B-Instruct-AWQ-4bit` | `cpatonn/Qwen3-VL-4B-Instruct-AWQ-4bit` | AWQ-4bit | 🔄替换 |
| 43 | Qwen3 VL 8B | `cpatonn/Qwen3-VL-8B-Instruct-AWQ-4bit` | `cpatonn/Qwen3-VL-8B-Instruct-AWQ-4bit` | AWQ-4bit | 🔄替换 |

> 备注 #26/#27：Nemotron-3-Nano-Omni 与 Nemotron-Nano-12B-VL 官网部署为 NVFP4；本地若原本缺失则按官网 NVFP4 下载。

---

## 二、本次替换清单与下载来源（2026-08-18）

替换策略：**ModelScope 优先（RedHatAI w4a16 系），其余走 HF（原生 Xet，经 127.0.0.1:7897 代理）**。

### ModelScope 下载（RedHatAI W4A16）
Qwen3-8B、Qwen3-4B、Qwen3-30B-A3B、Qwen3-32B、gemma3-4b、gemma3-12b、gemma3-27b、Llama-3.1-8B

### HuggingFace 下载（NVFP4 / AWQ / GGUF / FP16）
Qwen3.5-27B/35B-A3B/9B/4B (NVFP4)、Qwen3.6-27B (NVFP4)、Qwen3-VL-4B/8B (AWQ)、Gemma-4-31B (NVFP4)、Gemma-4-E2B/E4B (NVFP4)、functiongemma (GGUF)、Llama-3.2-3B (W4A16)、Nemotron-Nano-9B-v2 (NVFP4)、Nemotron3-Nano-30B-A3B (NVFP4)、Cosmos-Reason1-7B (FP16)

---

## 三、本地核实记录（磁盘 2026-08-18）

- **磁盘现状**：替换前占 1.2T / 剩 ~235G；替换完成后可用空间升至 ~598G（旧全精度已删，磁盘明显释放）。
- **中途清理**：
  - 删除 `qwen/Qwen3-4B-quantized.w4a16` 中断残留(`.incomplete`)。
  - 删除 `qwen/Qwen3.5-35B-A3B-NVFP4` 289M 半成品后重下。
  - 去除 `nemotron/Nemotron-Nano-9B-v2` 与 `nvidia/Nemotron-Nano-9B-v2` 重复拷贝（去重）。
- **悬空链接处理**：`qwen3-32b`、`google/gemma-3-{4b,12b,27b}`、`google/functiongemma-270m-it`、`google/Gemma-4-31B` 已重指到新量化目录；无残留悬空链接。
- **未处理（保留原样）**：Cosmos-Reason2-2B/8B（GGUF=官网 llama.cpp 主线）、Qwen3.5-0.8B(BF16)、Ministral-\*-Reasoning(FP16)、gemma3-1b/270m(FP16)、MiniMax-M2.7(GGUF)。

---

## 四、【附录】执行流程纪要

1. **下载工具**：ModelScope（`MODELSCOPE_DOWNLOAD_PARALLELS=16`）；HF 走**官方 hf_xet**（VPN/代理必须开启保证 Xet 端可达）；`hf_transfer` 在 v1.24 已废弃故关闭。
2. **每模型流程**：下载官网量化 → 校验（config 量化字段/权重完整/`repo` 一致）→ 通过后删除本地旧全精度 → 同步重指相关符号链接。
3. **磁盘安全**：剩余 < 60GB 立即暂停；增量「下量化→删旧」逐模型回收，绝不批量堆积、杜绝占满。
4. **故障与修复**：曾遇 ModelScope 后台卡死（改前台）、HF Xet 卡死（根因 VPN 未开，开启后恢复正常）、下载 BrokenPipe（脚本增加 3 次自动重试、HF 缓存续传）。
5. **进度日志**：`logs/PROGRESS_model_replace_20260818.md`（逐模型表格）+ `logs/model_replace_20260818.log`（详细执行日志）。
6. **TOS 上传**：23 个量化模型打包为 `models/<vendor>/<model>.tar.gz` 上传至 TOS 桶，全部成功、0 失败，共约 **220 GB**。

---

## 五、TOS 上传清单（2026-08-19 完成，23 项 · 共约 220 GB）

| 本地模型 | TOS key | 上传大小 |
|---|---|---|
| Qwen3-32B-quantized.w4a16 | `models/qwen/Qwen3-32B-quantized.w4a16.tar.gz` | 15.18 GB |
| Qwen3-30B-A3B-quantized.w4a16 | `models/qwen/Qwen3-30B-A3B-quantized.w4a16.tar.gz` | 13.27 GB |
| Qwen3-8B-quantized.w4a16 | `models/qwen/Qwen3-8B-quantized.w4a16.tar.gz` | 4.86 GB |
| Qwen3-4B-quantized.w4a16 | `models/qwen/Qwen3-4B-quantized.w4a16.tar.gz` | 2.70 GB |
| Qwen3.5-27B-NVFP4 | `models/qwen/Qwen3.5-27B-NVFP4.tar.gz` | 16.52 GB |
| Qwen3.5-35B-A3B-NVFP4 | `models/qwen/Qwen3.5-35B-A3B-NVFP4.tar.gz` | 20.02 GB |
| Qwen3.5-9B-NVFP4 | `models/qwen/Qwen3.5-9B-NVFP4.tar.gz` | 7.47 GB |
| Qwen3.5-4B-NVFP4 | `models/qwen/Qwen3.5-4B-NVFP4.tar.gz` | 3.39 GB |
| Qwen3.6-27B-NVFP4 | `models/qwen/Qwen3.6-27B-NVFP4.tar.gz` | 17.87 GB |
| Qwen3-VL-8B-AWQ | `models/qwen/Qwen3-VL-8B-AWQ.tar.gz` | 5.98 GB |
| Qwen3-VL-4B-AWQ | `models/qwen/Qwen3-VL-4B-AWQ.tar.gz` | 3.49 GB |
| gemma-3-27b-w4a16 | `models/gemma/gemma-3-27b-w4a16.tar.gz` | 15.72 GB |
| gemma-3-12b-w4a16 | `models/gemma/gemma-3-12b-w4a16.tar.gz` | 8.19 GB |
| gemma-3-4b-w4a16 | `models/gemma/gemma-3-4b-w4a16.tar.gz` | 6.88 GB |
| Gemma-4-31B-NVFP4 | `models/gemma/Gemma-4-31B-NVFP4.tar.gz` | 25.80 GB |
| Gemma-4-E2B-NVFP4 | `models/gemma/Gemma-4-E2B-NVFP4.tar.gz` | 3.98 GB |
| Gemma-4-E4B-NVFP4 | `models/gemma/Gemma-4-E4B-NVFP4.tar.gz` | 5.99 GB |
| functiongemma-270m-it-GGUF | `models/gemma/functiongemma-270m-it-GGUF.tar.gz` | 0.65 GB |
| Meta-Llama-3.1-8B-Instruct-quantized.w4a16 | `models/llama/Meta-Llama-3.1-8B-Instruct-quantized.w4a16.tar.gz` | 4.43 GB |
| Llama-3.2-3B-w4a16 | `models/llama/Llama-3.2-3B-w4a16.tar.gz` | 2.34 GB |
| Nemotron-Nano-9B-v2-NVFP4 | `models/nvidia/Nemotron-Nano-9B-v2-NVFP4.tar.gz` | 6.28 GB |
| Nemotron3-Nano-30B-A3B-NVFP4 | `models/nvidia/Nemotron3-Nano-30B-A3B-NVFP4.tar.gz` | 16.69 GB |
| Cosmos-Reason1-7B | `models/nvidia/Cosmos-Reason1-7B.tar.gz` | 12.27 GB |

---

## 六、下载方式与代码总结

### 6.1 核心工具脚本
| 脚本 | 作用 | 用法 |
|---|---|---|
| `scripts/replace_models_to_official.py` | 逐模型：下载官网量化 → 校验 → 删旧全精度 → 重指链接 | `python3 scripts/replace_models_to_official.py <model_key>` |
| `scripts/run_all_replace.py` | 后台顺序批量执行（仅建议前台逐模型用于 ModelScope） | `python3 scripts/run_all_replace.py` |
| `scripts/upload_to_official_tos.py` | 打包量化模型为 `.tar.gz` 并上传 TOS | `python3 scripts/upload_to_official_tos.py [model_key]` |
| `src/downloader.py` | 底层下载（`download_with_modelscope` / `download_with_huggingface`） | 库 |
| `src/uploader.py` | 底层 TOS 上传（`load_tos_client` / `upload_to_tos`） | 库 |

### 6.2 下载方式（双通道 · 官方工具）
- **ModelScope（RedHatAI W4A16 系优先）**：`MODELSCOPE_DOWNLOAD_PARALLELS=16` 并行下载。
  - 用于：Qwen3-8B/4B/30B-A3B/32B、gemma3-4b/12b/27b、Llama-3.1-8B。
- **HuggingFace（NVFP4 / AWQ / GGUF / FP16）**：走**官方 `hf_xet`** 高速通道（`HF_HOME=/home/sd1/models/.hf_cache`）。
  - 前置：**VPN/代理 `127.0.0.1:7897` 必须开启**（Xet 端点依赖其可达；此前卡死即因代理未开）。
  - `HF_HUB_ENABLE_HF_TRANSFER=0`（v1.24 已废弃，避免与 Xet 冲突）。
  - 用于：Qwen3.5 全系 NVFP4、Qwen3.6-27B、Qwen3-VL-AWQ、Gemma-4 全系 NVFP4、functiongemma GGUF、Llama-3.2-3B、Nemotron 系 NVFP4、Cosmos-Reason1-7B。

### 6.3 下载关键实现要点
```python
# 1) HF 下载（原生 Xet，经代理，关闭 hf_transfer）
def hf_download(repo, target):
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
    os.environ["HF_HOME"] = "/home/sd1/models/.hf_cache"
    os.environ["HTTP_PROXY"] = "http://127.0.0.1:7897"   # VPN代理
    os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7897"
    download_with_huggingface(repo, target)

# 2) ModelScope 下载（并行）
def ms_download(repo, target):
    os.environ["MODELSCOPE_DOWNLOAD_PARALLELS"] = "16"
    # 先清理陈旧 .ms_cache/.lock，避免卡死
    download_with_modelscope(repo, target)

# 3) 下载自动重试（HF 基于 .hf_cache 缓存续传）
for attempt in range(1, 4):
    try:
        (ms_download if m["ms"] else hf_download)(repo, src); break
    except Exception as e:
        shutil.rmtree(src, ignore_errors=True)   # 清残留
        time.sleep(30)                            # 30s 后重试
```

### 6.4 安全与校验约定
- **下载前磁盘预检**：剩余 < 60GB 即跳过该模型，先删已校验旧全精度回收空间。
- **逐模型内存安全**：先下量化 → 校验通过 → **再删**旧全精度，绝不堆积、杜绝占满。
- **校验**：目标目录含权重文件（safetensors/gguf）且无 `.incomplete` 才算通过；失败则**保留原样并标注**，不擅自删。
- **符号链接**：删旧后同步重指 root 与 `google/` 别名到新量化目录，避免悬空。
- **故障案例**：ModelScope 后台卡死（改前台）、HF Xet 卡死（根因 VPN 未开）、BrokenPipe（脚本 3 次重试 + 缓存续传）。

### 6.5 打包上传 TOS
```python
def process(client, bucket, local_dir, tos_key):
    check_disk_space(MODELS, min_free_gb=60.0)
    create_tarball(local_dir, tarball, label=name, min_free_gb=60.0)  # 打包 .tar.gz
    upload_to_tos(client, bucket, tarball, tos_key, label=name)        # 断点续传+并发
    os.remove(tarball)                                                 # 上传后清本地 tarball
```
- TOS key 统一为 `models/<vendor>/<model>.tar.gz`，与平台 CSV 的 `ENGINE_URI` 对齐。

> （注：部分内容可能由 AI 生成）
