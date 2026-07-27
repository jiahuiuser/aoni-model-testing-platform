# NVIDIA\_Jetson\_AGX\_Thor\_AI\_Agent\_测试方案

**文档版本**：V1\.0
**编制日期**：2026年7月
**适用平台**：NVIDIA Jetson AGX Thor Developer Kit（128GB）
**测试范围**：40\+ 款主流开源大模型的边缘推理性能与准确率验证

---

## 目录

1. 测试概述

2. 硬件与软件环境

3. 测试模型清单

4. 性能测试方案

5. 准确率测试方案

6. 多推理引擎对比

7. 评估与判定标准

8. 测试执行计划

9. 风险与注意事项

10. 附录 A：vLLM 部署命令参考

11. 附录 B：压测与评测工具参数

---

## 1\. 测试概述

### 1\.1 测试背景

NVIDIA Jetson AGX Thor（T5000）基于 Blackwell GPU 架构，配备 128GB 统一内存，提供 2070 FP4 TFLOPS 的 AI 算力，是当前边缘侧最强的 AI 推理平台之一。本方案围绕边缘 AI Agent 典型场景，对 40\+ 款主流开源大语言模型开展系统性的性能与准确率测试，为边缘部署选型提供量化依据。

### 1\.2 测试目标

（1）**模型兼容性验证**：验证各参数量级模型在 Jetson Thor 统一内存架构下的可加载性与运行稳定性，明确平台支持的模型上限。

（2）**推理性能基准**：测试单模型在多种量化精度（FP16 / FP8 / W4A16）下的 Token 生成速度、首字延迟与并发吞吐能力。

（3）**准确率质量验证**：通过标准 Benchmark 评测模型推理输出质量，确认量化压缩后的精度保持度，建立边缘部署的精度基线。

（4）**AI Agent 场景适配**：测试多模型并行部署、工具调用模型、推理模型协同等典型 Agent 架构的可行性。

（5）**多引擎横向对比**：对比 vLLM、llama\.cpp / Ollama、TensorRT\-LLM 等推理引擎在 Thor 平台上的性能差异与适用场景。

（6）**能效比评估**：结合 130W 功耗上限，评估各模型的 Tokens / Watt 能效比，验证边缘部署的功耗合理性。

### 1\.3 测试范围

|分类|覆盖内容|
|---|---|
|**模型架构**|Dense 稠密模型、MoE 混合专家模型、VLM 视觉语言模型|
|**参数量级**|270M \~ 120B，四级模型谱系全覆盖|
|**量化精度**|FP16 / BF16、FP8、W8A8、W4A16（AWQ / GPTQ）|
|**推理引擎**|vLLM（主测）、llama\.cpp / Ollama、TensorRT\-LLM|
|**并发规模**|1 / 2 / 4 / 8 / 16 / 32 并发用户|
|**上下文长度**|512 / 2K / 4K / 8K / 32K tokens|
|**部署模式**|单模型独占、双模型并行（Agent 场景）|
|**评测维度**|性能基准、并发吞吐、长上下文、量化对比、准确率、能效比|

### 1\.4 边缘 AI Agent 典型场景

本方案重点验证以下 Agent 部署模式：

|场景|部署架构|说明|
|---|---|---|
|**单模型 Agent**|单个 7B / 8B 模型承担全部推理|简单对话型 Agent，资源占用低|
|**大小模型协同**|主模型 8B \+ 工具模型 3B 并行|思考 \+ 工具调用分离，典型 Agent 架构|
|**MoE 高吞吐 Agent**|MoE 30B\-A3B 单模型高吞吐部署|激活参数量小，吞吐接近小模型，能力接近大模型|
|**多模态 Agent**|VLM 模型 \+ LLM 模型协同|视觉理解 \+ 语言推理，面向具身智能 / 机器人场景|

---

## 2\. 硬件与软件环境

### 2\.1 Jetson AGX Thor 硬件规格

|组件|规格参数|
|---|---|
|**GPU 架构**|NVIDIA Blackwell，2560 CUDA 核心|
|**AI 算力**|2070 TFLOPS（FP4 with sparsity）|
|**GPU 显存 / 系统内存**|128 GB 统一内存（256\-bit LPDDR5X）|
|**内存带宽**|273 GB/s|
|**CPU**|14 核 Arm Neoverse\-V3AE 64\-bit，16MB 共享 L3 Cache|
|**存储**|2 TB NVMe SSD（M\.2 Key M，PCIe Gen5 x4）|
|**视频编码**|6x 4Kp60 \(H\.265\) / 24x 1080p60|
|**网络接口**|1x 5GbE RJ45 \+ 1x QSFP28 \(4x 25G\)|
|**PCIe 扩展**|M\.2 Key M、PCIe Gen5|
|**功耗范围**|40W \~ 130W（MAXN 模式）|
|**散热方式**|主动风冷（原装散热器）|

**统一内存架构说明：**

Jetson Thor 采用统一内存（Unified Memory）架构，GPU 与 CPU 共享同一块 128GB LPDDR5X 物理内存，无独立显存。特点：

- 模型加载、KV Cache、系统运行共用内存池

- 无 CPU\-GPU 数据拷贝开销，但内存带宽相对独立显存较低

- 大模型部署需预留系统内存余量（建议 ≥ 10GB）

### 2\.2 软件环境

|软件组件|版本|说明|
|---|---|---|
|**JetPack SDK**|JetPack 7\.1|NVIDIA 官方 Jetson 软件开发包|
|**操作系统**|Ubuntu 24\.04\.3 LTS（Jetson Linux 38\.x）|ARM64 架构，基于 Canonical Ubuntu|
|**Linux 内核**|6\.8\.12\-tegra|支持实时抢占的 Tegra 定制内核|
|**CUDA**|13\.0\.0|GPU 通用计算平台|
|**cuDNN**|9\.12\.0|深度神经网络加速库|
|**TensorRT**|10\.13\.x|NVIDIA 推理优化引擎|
|**推理引擎（主）**|vLLM ≥ v0\.8\.0|高吞吐 LLM 推理，OpenAI API 兼容|
|**推理引擎（备）**|Ollama / llama\.cpp|轻量本地推理|
|**推理引擎（备）**|TensorRT\-LLM|NVIDIA 原生极致优化|
|**压测工具**|vllm bench serve \+ evalscope perf|性能基准与并发压测|
|**准确率评测**|EvalScope \+ LM\-Eval\-Harness|双框架交叉验证|
|**系统监控**|tegrastats|Jetson 官方系统状态监控工具|
|**容器运行时**|Docker \+ NVIDIA Container Toolkit|容器化部署|

### 2\.3 性能模式配置

测试前开启最高性能模式，确保结果稳定：

```bash
# 开启 MAXN 功耗模式
sudo nvpmodel -m 0

# 开启风扇最大转速与固定时钟
sudo jetson_clocks --fan

# 验证当前模式
sudo nvpmodel -q
```

### 2\.4 vLLM 推理服务基础配置

```bash
vllm serve ${MODEL_PATH} \
  --served-model-name ${MODEL_NAME} \
  --gpu-memory-utilization 0.80 \
  --max-model-len 4096 \
  --max-num-seqs 128 \
  --port 8000
```

**关键参数说明：**

|参数|推荐值|说明|
|---|---|---|
|`--gpu-memory-utilization`|0\.80|统一内存需预留更多系统余量，不建议超过 0\.85|
|`--max-model-len`|4096 / 8192|默认 4K，长上下文测试时上调，注意 KV Cache 占用|
|`--max-num-seqs`|128|最大并发调度序列数，边缘场景建议适中|
|`--quantization`|awq / fp8|W4A16 或 FP8 量化时指定|

---

## 3\. 测试模型清单

按参数量分为四级，结合 128GB 统一内存容量评估各模型的可运行性。

### 3\.1 超轻量模型（\< 4B）—— 边缘终端级

|模型名称|参数量|架构|W4A16 内存|FP16 内存|运行可行性|
|---|---|---|---|---|---|
|gemma\-3\-270m|270M|Dense|\~0\.2 GB|\~0\.6 GB|✅ 轻松运行，可多实例|
|gemma\-3\-1b|1B|Dense|\~0\.7 GB|\~2 GB|✅|
|cosmos\-reason\-2\-2b|2B|Reasoning|\~1\.5 GB|\~4 GB|✅|
|llama\-3\-2\-3b|3B|Dense|\~2 GB|\~6 GB|✅|
|gemma\-3\-4b|4B|Dense|\~2\.5 GB|\~8 GB|✅|
|qwen3\-4b|4B|Dense|\~2\.5 GB|\~8 GB|✅|
|qwen3\-5\-4b|4B|Dense|\~2\.5 GB|\~8 GB|✅|
|ministral\-3\-3b\-instruct|3B|Dense|\~2 GB|\~6 GB|✅|
|ministral\-3\-3b\-reasoning|3B|Reasoning|\~2 GB|\~6 GB|✅|
|nemotron3\-nano\-4b|4B|Dense|\~2\.5 GB|\~8 GB|✅|
|functiongemma|\~3B|Tool Use|\~2 GB|\~6 GB|✅ 工具调用专用|

### 3\.2 中小模型（7B \~ 14B）—— 边侧主力级

|模型名称|参数量|架构|W4A16 内存|FP16 内存|运行可行性|
|---|---|---|---|---|---|
|cosmos\-reason\-1\-7b|7B|Reasoning|\~4\.5 GB|\~14 GB|✅ 推荐主力|
|cosmos\-reason\-2\-8b|8B|Reasoning|\~5 GB|\~16 GB|✅|
|llama\-3\-1\-8b|8B|Dense|\~5 GB|\~16 GB|✅ 基准模型|
|qwen3\-8b|8B|Dense|\~5 GB|\~16 GB|✅ 中文主力|
|qwen3\-5\-0\-8b|8B|Dense|\~5 GB|\~16 GB|✅|
|qwen3\-5\-9b|9B|Dense|\~5\.5 GB|\~18 GB|✅|
|gemma\-3\-12b|12B|Dense|\~7 GB|\~24 GB|✅|
|ministral\-3\-8b\-instruct|8B|Dense|\~5 GB|\~16 GB|✅|
|ministral\-3\-8b\-reasoning|8B|Reasoning|\~5 GB|\~16 GB|✅|
|ministral\-3\-14b\-instruct|14B|Dense|\~8\.5 GB|\~28 GB|✅|
|ministral\-3\-14b\-reasoning|14B|Reasoning|\~8\.5 GB|\~28 GB|✅|
|minimax\-m2\-7|7B|Dense|\~4\.5 GB|\~14 GB|✅|
|nemotron\-nano\-9b\-v2|9B|Dense|\~5\.5 GB|\~18 GB|✅ NVIDIA 优化|

### 3\.3 中大型模型（20B \~ 35B）—— 边侧高端级

#### Dense 架构

|模型名称|参数量|W4A16 内存|FP16 内存|运行可行性|
|---|---|---|---|---|
|gpt\-oss\-20b|20B|\~12 GB|\~40 GB|✅ W4A16 流畅|
|gemma\-3\-27b|27B|\~16 GB|\~54 GB|✅ W4A16|
|qwen3\-5\-27b|27B|\~16 GB|\~54 GB|✅ W4A16|
|qwen3\-6\-27b|27B|\~16 GB|\~54 GB|✅ W4A16|
|qwen3\-32b|32B|\~19 GB|\~64 GB|✅ W4A16|
|gemma\-4\-31b|31B|\~18\.5 GB|\~62 GB|✅ W4A16|

#### MoE 架构（边缘高吞吐首选）

|模型名称|总参数量|激活参数|W4A16 内存|运行可行性|
|---|---|---|---|---|
|qwen3\-30b\-a3b|30B|3B|\~10 GB|✅⭐ 高吞吐推荐|
|qwen3\-5\-35b\-a3b|35B|3B|\~11 GB|✅|
|qwen3\-6\-35b\-a3b|35B|3B|\~11 GB|✅|
|gemma\-4\-26b\-a4b|26B|4B|\~12 GB|✅|
|gemma\-4\-e2b|MoE|2B|\~7 GB|✅ 超高效|
|gemma\-4\-e4b|MoE|4B|\~12 GB|✅|
|nemotron3\-nano\-30b\-a3b|30B|3B|\~10 GB|✅|

### 3\.4 大模型（70B \~ 120B）—— 边侧极限级

|模型名称|参数量|W4A16 内存|FP16 内存|运行可行性|
|---|---|---|---|---|
|llama\-3\-1\-70b|70B|\~42 GB|\~140 GB|⚠️ W4A16 可运行，需控制并发|
|gpt\-oss\-120b|120B|\~72 GB|\~240 GB|⚠️ W4A16 极限尝试，KV Cache 需严格限制|

### 3\.5 视觉语言模型（VLM）

|模型名称|参数量|类型|W4A16 内存|运行可行性|
|---|---|---|---|---|
|qwen3\-vl\-4b|4B|VLM|\~3 GB|✅|
|qwen3\-vl\-8b|8B|VLM|\~5\.5 GB|✅|
|nemotron\-nano\-12b\-vl|12B|VLM|\~7\.5 GB|✅|
|nemotron\-3\-nano\-omni|\~12B|多模态 Omni|\~8 GB|✅|

### 3\.6 内存占用估算说明

- **权重公式**：FP16 ≈ 参数量\(B\) × 2 GB；FP8 ≈ 参数量\(B\) × 1 GB；W4A16 ≈ 参数量\(B\) × 0\.5 GB

- **统一内存特性**：模型权重 \+ KV Cache \+ 系统运行共用 128GB，建议预留 ≥ 10GB 给系统

- **KV Cache 估算**：8K 上下文约占权重的 15\~25%，32K 上下文可达权重的 50%\+

- **安全阈值**：模型权重 \+ KV Cache 峰值 ≤ 总内存的 85%（约 108GB），避免系统 OOM

---

## 4\. 性能测试方案

### 4\.1 性能测试指标

|类别|指标|缩写|单位|说明|
|---|---|---|---|---|
|**时延指标**|首 Token 延迟|TTFT|ms|Avg / P50 / P90 / P99|
||Token 间延迟|ITL / TPOT|ms|平均每 Token 生成耗时|
||端到端延迟|E2E|ms|请求完整响应总耗时|
|**吞吐指标**|输出吞吐量|Throughput|tokens/s|系统每秒生成 Token 总数|
||请求吞吐率|Request Rate|req/s|每秒完成请求数|
||单请求速度|TPS|tokens/s|单并发下单请求生成速度|
|**稳定性指标**|成功率|Success Rate|%|无报错请求占比|
||性能衰减率|Decay Rate|%|长跑前后吞吐下降比例|
|**资源指标**|内存占用|Memory|GB|模型 \+ KV Cache 总内存消耗|
||系统功耗|Power|W|整机实时功耗（tegrastats 采集）|
||GPU 利用率|GPU Util|%|GPU 核心负载率|
|**能效指标**|能效比|Tokens/Joule|tok/J|每焦耳能耗生成的 Token 数|

### 4\.2 性能测试用例矩阵

#### 用例 1：单模型基线测试

**目的**：建立各模型单并发下的基础性能基线。

|配置项|参数|
|---|---|
|并发数|1|
|输入长度|512 tokens|
|输出长度|256 tokens|
|重复轮次|3 轮取平均|
|覆盖模型|全量 40\+ 款（按可行性分级）|
|核心指标|单请求 TPS、TTFT、加载时间、内存占用、功耗|

#### 用例 2：并发吞吐扫描

**目的**：评估多用户并发场景下的吞吐能力与延迟恶化。

|配置项|参数|
|---|---|
|并发梯度|1, 2, 4, 8, 16, 32|
|输入长度|512 tokens|
|输出长度|128 tokens|
|每级请求数|200 条|
|抽样模型|每级别 2\~3 款代表模型|
|核心指标|饱和吞吐点、TTFT 曲线、ITL 稳定性、成功率|

#### 用例 3：量化精度对比

**目的**：对比 FP16 / FP8 / W4A16 不同精度的性能与内存收益。

|配置项|参数|
|---|---|
|精度梯度|FP16, FP8, W4A16|
|并发场景|单并发 \+ 8 并发|
|输入/输出|512 / 256 tokens|
|抽样模型|代表模型 4\~6 款|
|核心指标|性能加速比、内存节省率、（配合准确率用例）精度损失|

#### 用例 4：长上下文性能

**目的**：验证长上下文场景下的 Prefill 速度与 KV Cache 压力。

|配置项|参数|
|---|---|
|并发数|1|
|输入梯度|512, 2K, 4K, 8K, 32K|
|输出长度|128 tokens|
|抽样模型|主力 7B / 8B 模型 \+ MoE 模型|
|核心指标|TTFT 线性度、KV Cache 内存增长、是否 OOM|

#### 用例 5：AI Agent 多模型并行

**目的**：验证 Agent 场景下多模型共享内存的稳定性。

|配置项|参数|
|---|---|
|部署组合|主模型 8B\(W4A16\) \+ 工具模型 3B\(W4A16\)|
|并发模式|两路并发，各模型独立接收请求|
|输入/输出|512 / 256 tokens|
|测试时长|≥ 10 分钟持续并发|
|核心指标|互相干扰程度、总吞吐、内存峰值、稳定性|

#### 用例 6：稳定性长跑

**目的**：验证边缘长时间运行的可靠性。

|配置项|参数|
|---|---|
|并发数|饱和吞吐的 70%|
|总请求数|≥ 3000 条（持续 ≥ 30 分钟）|
|输入/输出|512 / 256 tokens|
|抽样模型|核心部署候选 2\~3 款|
|核心指标|性能衰减率、内存泄漏、崩溃次数、温度稳定性|

### 4\.3 测试工具与执行方法

#### 工具一：vllm bench serve（官方基准）

```bash
vllm bench serve \
  --host localhost --port 8000 \
  --dataset-name random \
  --request-rate inf \
  --ignore-eos \
  --random-input-len 512 \
  --random-output-len 256 \
  --num-prompts 300 \
  --max-concurrency 16 \
  --save-result \
  --metadata "model=${MODEL_NAME},device=jetson-thor"
```

#### 工具二：evalscope perf（场景压测）

```bash
evalscope perf \
  --url 'http://localhost:8000/v1/chat/completions' \
  --parallel 8 \
  --model "${MODEL_NAME}" \
  -n 200 \
  --max-prompt-length 2048 \
  --api openai \
  --dataset openqa \
  --stream
```

#### 系统监控：tegrastats

Jetson 官方监控工具，以 1Hz 采集 CPU、GPU、内存、功耗、温度：

```bash
# 后台运行监控，输出到文件
tegrastats --interval 1000 --logfile tegrastats.log &
```

---

## 5\. 准确率测试方案

### 5\.1 测试目标

- 验证各模型在 Jetson Thor 推理链路上的输出准确率，建立边缘侧能力基线；

- 对比 FP16 与 W4A16 / FP8 量化后的精度损失，确定边缘部署的最优量化策略；

- 验证中文与英文场景下的综合表现，为本地化 Agent 选型提供依据；

- 建立准确率回归基线，用于后续 JetPack 版本升级的质量验证。

### 5\.2 评测数据集

|数据集|规模|语言|覆盖维度|评测指标|
|---|---|---|---|---|
|**MMLU**|14,042 题|英文|57 学科综合知识|Accuracy|
|**C\-Eval**|13,948 题|中文|52 学科中文知识|Accuracy|
|**CMMLU**|\~11,500 题|中文|中文语言与理解|Accuracy|
|**GSM8K**|8,500 题|英文|数学多步推理|Accuracy|
|**HumanEval**|164 题|英文/代码|Python 代码生成|Pass@1|
|**ARC\-Challenge**|1,172 题|英文|科学推理|Accuracy|

### 5\.3 评测执行方式

采用 vLLM 在线 API 评测方式，与性能测试使用完全一致的推理服务链路，结果贴近真实部署。

```bash
# Step 1：启动 vLLM 服务（参数与性能测试完全一致）
vllm serve ${MODEL_PATH} \
  --served-model-name target_model \
  --port 8801 \
  --gpu-memory-utilization 0.80

# Step 2：EvalScope 在线评测
evalscope eval \
  --model target_model \
  --eval-type openai_api \
  --api-url http://localhost:8801/v1 \
  --api-key EMPTY \
  --datasets mmlu ceval gsm8k humaneval arc \
  --limit 500 \
  --generation-config '{"temperature": 0.0, "max_tokens": 512, "do_sample": false}'
```

### 5\.4 量化精度损失对比

对核心模型执行多精度横向评测，建立精度\-性能权衡曲线：

```bash
# 依次评测 FP16、FP8、W4A16 三种精度
for precision in fp16 fp8 w4a16; do
  evalscope eval \
    --model target_model \
    --eval-type openai_api \
    --api-url http://localhost:8801/v1 \
    --datasets mmlu,ceval,gsm8k \
    --limit 500 \
    --generation-config '{"temperature": 0.0}'
done
```

### 5\.5 执行控制规范

|规范项|要求|目的|
|---|---|---|
|随机种子|seed = 42|消除随机性，确保可复现|
|采样参数|temperature=0, do\_sample=False|确定性输出，减少评测波动|
|环境对齐|与性能测试相同 vLLM 启动参数|保证算子路径一致|
|基线对比|所有结果与 FP16 基线相对对比|量化损失评估准确|
|数据落盘|保存 prompt/response/gold/score 五元组|支持问题定位与复核|

### 5\.6 精度损失判定标准

|量化方式|相对 FP16 准确率下降|等级|边缘部署建议|
|---|---|---|---|
|FP8|\< 1%|**A 级 优秀**|优先推荐，性能精度最佳平衡|
|W4A16|\< 3%|**B 级 良好**|推荐，边缘主流选择|
|W4A16|3% \~ 5%|**C 级 谨慎**|需评估业务精度敏感度|
|任意精度|\> 5%|**D 级 不通过**|不建议该精度上线|

---

## 6\. 多推理引擎对比

### 6\.1 测试引擎清单

|推理引擎|定位|Thor 适配度|适用场景|
|---|---|---|---|
|**vLLM**|高吞吐服务端推理|⭐⭐⭐⭐⭐ 主测|LLM 高并发服务、Agent 后端|
|**llama\.cpp / Ollama**|轻量本地推理|⭐⭐⭐⭐ 良好|快速验证、单机对话、低资源|
|**TensorRT\-LLM**|NVIDIA 原生优化|⭐⭐⭐⭐ 良好|极致性能、生产部署|

### 6\.2 横向对比方法

选择基准模型（如 llama\-3\-1\-8b 或 qwen3\-8b），统一 W4A16 量化，在并发 1 和并发 8 两个场景下对比。

|对比维度|vLLM|llama\.cpp|TensorRT\-LLM|
|---|---|---|---|
|单并发 TPS|基准|\-10% \~ \+10%|\+10% \~ \+30%|
|8 并发吞吐|基准|\-20% \~ \-30%|\+15% \~ \+35%|
|TTFT|基准|\-10% \~ \-20%|\-10% \~ \-20%|
|内存占用|基准|略低|相近|
|部署复杂度|低（OpenAI API）|极低（一行命令）|高（需编译 Engine）|
|多模态支持|VLM 完善|有限|VLA 最佳|
|社区模型支持|最广|广泛|需手动转换|

**选型建议：**

- **开发与快速验证**：Ollama / llama\.cpp，部署最简

- **生产服务与 Agent 后端**：vLLM，功能最全、API 兼容最好

- **极致性能追求**：TensorRT\-LLM，NVIDIA 硬件原生优化最佳

---

## 7\. 评估与判定标准

### 7\.1 LLM 推理性能标准（并发=8，ISL=512，OSL=128）

|参数量级|A 级（优秀）|B 级（合格）|C 级（偏弱）|
|---|---|---|---|
|4B 以下|TPS \> 120|TPS 60 \~ 120|TPS \< 60|
|7B \~ 8B|TPS \> 80|TPS 40 \~ 80|TPS \< 40|
|14B|TPS \> 50|TPS 25 \~ 50|TPS \< 25|
|27B \~ 32B \(Dense\)|TPS \> 25|TPS 12 \~ 25|TPS \< 12|
|MoE \(激活3B\)|TPS \> 100|TPS 60 \~ 100|TPS \< 60|
|70B|TPS \> 8|TPS 4 \~ 8|TPS \< 4|

### 7\.2 并发承载能力标准

|指标|A 级|B 级|C 级|
|---|---|---|---|
|稳定并发用户数|\> 16 同时在线|8 \~ 16 同时在线|\< 8 同时在线|
|P99 TTFT|\< 500 ms|500 \~ 1000 ms|\> 1000 ms|
|P99 TPOT|\< 50 ms|50 \~ 100 ms|\> 100 ms|
|内存利用率|\> 75%|55% \~ 75%|\< 55%|

### 7\.3 准确率评测标准

|评测集|A 级（优秀）|B 级（合格）|C 级（偏弱）|
|---|---|---|---|
|MMLU|Accuracy \> 65%|45% \~ 65%|\< 45%|
|C\-Eval|Accuracy \> 70%|50% \~ 70%|\< 50%|
|GSM8K|Accuracy \> 55%|35% \~ 55%|\< 35%|
|HumanEval|Pass@1 \> 30%|15% \~ 30%|\< 15%|
|量化精度损失|\< 2%|2% \~ 4%|\> 4%|

### 7\.4 能效比标准（边缘特有）

|能效等级|Tokens / Joule|说明|
|---|---|---|
|优秀|\> 1\.0 tok/J|高能效边缘部署|
|良好|0\.5 \~ 1\.0 tok/J|可接受的功耗水平|
|一般|0\.2 \~ 0\.5 tok/J|需评估供电与散热条件|

### 7\.5 模型部署推荐分级

综合性能、准确率、内存占用、稳定性，将模型分为四级部署推荐：

|等级|说明|适用场景|
|---|---|---|
|⭐⭐⭐⭐⭐ 强烈推荐|性能优秀 \+ 准确率高 \+ 内存占用合理|生产环境首选|
|⭐⭐⭐⭐ 推荐|性能良好 \+ 准确率达标|多数场景适用|
|⭐⭐⭐ 可用|基本满足需求，有一定局限|特定场景可选|
|⭐⭐ 谨慎|性能或准确率不达标，或稳定性存疑|仅验证用途，不建议生产|

---

## 8\. 测试执行计划

### 8\.1 整体时间规划

全量测试预计 **3\~4 周**，按优先级分级执行。

|阶段|内容|预计周期|
|---|---|---|
|**Phase 0**|JetPack 刷机、环境配置、工具链验证、冒烟测试|2 天|
|**Phase 1**|全模型基线遍历（用例 1）|3\~5 天|
|**Phase 2**|代表模型深度性能测试（用例 2 \~ 6）|7\~10 天|
|**Phase 3**|准确率评测（核心模型 \+ 量化对比）|5\~7 天|
|**Phase 4**|多引擎对比、数据汇总、报告输出|3 天|

### 8\.2 单模型测试流程

|步骤|内容|预计耗时|
|---|---|---|
|1|模型下载与加载验证|5 \~ 30 分钟（视模型大小）|
|2|单并发基线测试（用例 1）|10 \~ 15 分钟|
|3|并发吞吐扫描（用例 2）|30 \~ 60 分钟|
|4|量化精度对比（用例 3）|1 \~ 2 小时|
|5|长上下文测试（用例 4）|30 分钟|
|6|稳定性长跑（用例 6）|≥ 30 分钟|
|7|准确率评测（核心数据集）|2 \~ 6 小时|

### 8\.3 测试优先级

|优先级|模型范围|测试内容|
|---|---|---|
|**P0 必测**|主力 7B/8B 模型 \+ MoE 代表模型（共 6\~8 款）|完整用例矩阵 \+ 全量准确率 \+ 多引擎对比|
|**P1 抽测**|其余中小模型 \+ 中大型模型|基线测试 \+ 并发扫描 \+ 准确率子集|
|**P2 可选**|70B\+ 大模型、小众模型|仅验证可加载性 \+ 单并发基线|

---

## 9\. 风险与注意事项

|风险项|描述|应对措施|
|---|---|---|
|**统一内存 OOM**|大模型 FP16 超出 128GB，或并发过高导致 KV Cache 溢出|默认使用 W4A16 量化，监控内存水位，逐步提升并发|
|**内存带宽瓶颈**|LPDDR5X 273GB/s 相对 HBM 较低，大并发下可能带宽受限|对比带宽利用率与 SM 利用率，识别带宽墙场景|
|**模型下载失败**|HuggingFace 访问不稳定，大模型下载耗时长|使用国内镜像、提前批量下载、本地 SSD 持久化缓存|
|**量化精度损失**|INT4 量化可能导致部分模型质量下降明显|对比 FP16 基线，使用 EvalScope 评测，不达标则升精度|
|**散热降频**|持续 130W 高负载下温度过高触发降频|使用原装散热器，监控温度，必要时降低功耗模式|
|**长上下文内存激增**|32K\+ 上下文 KV Cache 占用指数增长|限制 max\-model\-len，使用 KV Cache 量化|
|**vLLM 版本兼容**|部分新模型需特定版本 vLLM 支持|准备多个版本容器，按模型适配切换|
|**评测耗时过长**|全量 MMLU \+ C\-Eval 单模型可能数小时|使用 \-\-limit 控制样本数，先抽样后全量|
|**多实例冲突**|多 vLLM 进程共享统一内存可能引发 CUDA 错误|Agent 多模型场景使用单实例多模型服务，或严格控制内存|

**测试前检查清单：**

1. JetPack 版本与 CUDA 版本已确认正确

2. 模型文件完整下载并校验

3. NVMe 剩余空间 ≥ 500GB

4. 已开启 MAXN 性能模式与 jetson\_clocks

5. 内存余量充足，无其他占用进程

6. 评测时设置 temperature=0，确保结果可复现

---

## 附录 A：vLLM 部署命令参考

### 常用模型启动命令（W4A16）

```bash
# Qwen3-8B
vllm serve qwen3-8b-awq --served-model-name qwen3-8b \
  --quantization awq --gpu-memory-utilization 0.8 --port 8000

# Llama 3.1 8B
vllm serve llama-3.1-8b-instruct-awq --served-model-name llama-3.1-8b \
  --quantization awq --gpu-memory-utilization 0.8 --port 8000

# Qwen3-30B-A3B (MoE)
vllm serve qwen3-30b-a3b --served-model-name qwen3-30b-a3b \
  --gpu-memory-utilization 0.8 --trust-remote-code --port 8000

# Llama 3.1 70B (W4A16)
vllm serve llama-3.1-70b-instruct-w4a16 --served-model-name llama-3.1-70b \
  --quantization awq --gpu-memory-utilization 0.85 --max-num-seqs 64 --port 8000

# GPT-OSS-20B
vllm serve gpt-oss-20b --served-model-name gpt-oss-20b \
  --gpu-memory-utilization 0.8 --port 8000

# Nemotron Nano 9B v2 (FP8)
vllm serve nemotron-nano-9b-v2 --served-model-name nemotron-9b \
  --quantization fp8 --gpu-memory-utilization 0.8 --port 8000
```

---

## 附录 B：压测与评测工具参数

### vllm bench serve 核心参数

|参数|说明|示例值|
|---|---|---|
|`--host / --port`|服务地址|localhost / 8000|
|`--dataset-name`|数据集类型|random / sharegpt|
|`--random-input-len`|随机输入长度|512|
|`--random-output-len`|随机输出长度|256|
|`--num-prompts`|总请求数|300|
|`--max-concurrency`|最大并发|16|
|`--request-rate`|请求速率|inf（极限压测）|
|`--save-result`|保存 JSON 结果|布尔开关|

### evalscope perf 核心参数

|参数|说明|示例值|
|---|---|---|
|`--url`|OpenAI API 地址|http://localhost:8000/v1/chat/completions|
|`--parallel`|并发数|8 / 16|
|`-n`|总请求数|200|
|`--model`|模型名称|与 serve 一致|
|`--dataset`|数据集类型|openqa / random|
|`--max-prompt-length`|最大输入长度|2048|
|`--stream`|流式输出|精确测 TTFT 时开启|

### EvalScope 评测核心参数

|参数|说明|示例值|
|---|---|---|
|`--model`|模型名称|target\_model|
|`--eval-type`|评测类型|openai\_api|
|`--api-url`|API 地址|http://localhost:8801/v1|
|`--datasets`|数据集列表|mmlu ceval gsm8k|
|`--limit`|每集抽样数|500|
|`--generation-config`|生成参数|temperature=0, max\_tokens=512|

### 输出指标说明

- **Request throughput \(req/s\)**：每秒完成请求数

- **Output token throughput \(tok/s\)**：每秒生成 Token 总数

- **Mean TTFT \(ms\)**：平均首 Token 时间

- **Mean TPOT \(ms\)**：平均每 Token 处理时间

- **P99 TTFT / P99 TPOT**：99 分位延迟指标

- **accuracy / weighted\_avg**：评测准确率与加权平均分

> （注：部分内容可能由 AI 生成）
