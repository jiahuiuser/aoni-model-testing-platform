# AONI 智能体模型平台

NVIDIA Jetson AGX Thor (T5000) 多设备模型运维与测试平台。支持 43 款 LLM/VLM 的自动化部署、性能测试、准确率评测，并提供 Web 管理界面进行多设备调度管理。

---

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                    Vue3 Web 管理界面                         │
│               http://192.168.1.40:5173                      │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌───────┐ │
│  │ 任务管理 │ │ 模型管理 │ │ 设备管理 │ │ 凭证管理 │ │ 报告  │ │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └───────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API
┌──────────────────────────┴──────────────────────────────────┐
│                  FastAPI 后端 (端口 8800)                    │
│  ┌────────────┐ ┌──────────────┐ ┌───────────────────────┐  │
│  │ Task CRUD  │ │ Model + 设备 │ │ 报告生成 (JSON/MD)     │  │
│  │ 后台线程   │ │ 专属配置     │ │ 性能/准确率对比        │  │
│  └────────────┘ └──────────────┘ └───────────────────────┘  │
│                            │                                 │
│  ┌─────────────────────────┴─────────────────────────────┐  │
│  │                 RemoteRunner                           │  │
│  │   本地 sudo docker  ←→  SSH 远程执行 (sshpass/ssh-key) │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────────┐
│                    设备层                                    │
│  ┌─────────────────┐  ┌─────────────────────────────────┐   │
│  │ Jetson Thor #1  │  │ Jetson AGX Thor #2 (192.168.1.16)│  │
│  │ (本机, 127.0.0.1)│  │ SSH: nv5000, CUDA 13.0, 122Gi   │  │
│  └─────────────────┘  └─────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 目录结构

```
aoni-model-platform/
├── backend/                        # FastAPI 后端
│   ├── main.py                     # 入口 (端口 8800)
│   ├── config.py                   # 配置 (SQLite/Redis/vLLM 参数)
│   ├── database.py                 # SQLAlchemy 连接管理
│   ├── requirements.txt            # Python 依赖
│   ├── models/
│   │   └── __init__.py             # ORM: ModelInfo/Device/Credential/Task/PerfResult...
│   ├── schemas/
│   │   └── __init__.py             # Pydantic 请求/响应模型
│   ├── routers/
│   │   ├── tasks.py                # 任务 CRUD + WebSocket 日志推送
│   │   ├── models.py               # 模型 CRUD + 设备配置 + 一键测试
│   │   ├── devices.py              # 设备 CRUD + 凭证管理 + 健康检查(SSH)
│   │   └── reports.py              # 报告列表/详情/下载/对比图表
│   └── services/
│       ├── executor.py             # 主执行器 (本地/SSH RemoteRunner)
│       ├── task_manager.py         # 任务生命周期 (创建/暂停/恢复/取消)
│       ├── pipeline.py             # 模型分类 & 并发梯度策略
│       └── scheduler.py            # 执行排序 (小模型优先)
├── frontend/                       # Vue3 前端
│   ├── vite.config.js              # Vite 配置 (端口 5173, API 代理)
│   ├── package.json                # 依赖: Vue3/Element-Plus/ECharts/Axios
│   └── src/
│       ├── App.vue                 # 主布局 (侧边栏 + 路由)
│       ├── router/index.js         # 7 个页面路由
│       ├── api/index.js            # Axios API 封装
│       └── views/
│           ├── TaskList.vue        # 任务列表
│           ├── TaskCreate.vue      # 创建任务 (选设备→选模型→配置)
│           ├── TaskDetail.vue      # 任务详情 (分模块日志)
│           ├── ModelManagement.vue # 模型管理 + 设备配置
│           ├── DeviceManagement.vue# 设备管理 + 凭证管理
│           ├── Reports.vue         # 报告列表 (按设备筛选)
│           └── ReportDetail.vue    # 报告详情 (性能/准确率图表)
├── src/                            # 遗留 CLI 工具 (离线模型下载/测试)
│   ├── downloader.py               # ModelScope 16线程下载 + pigz 打包
│   ├── uploader.py                 # 火山引擎 TOS 分片上传
│   ├── test_runner.py              # Docker 自动化测试
│   ├── benchmark/
│   │   ├── perf_runner.py          # vLLM bench 性能基准
│   │   ├── accuracy_runner.py      # EvalScope 准确率评测
│   │   └── report_generator.py     # Markdown 报告生成
│   └── csv_handler.py              # CSV 读写
├── data/
│   ├── aoni_platform.db            # SQLite 数据库 (运行时)
│   ├── aoni_models_thor128g.csv    # 43 款模型 CSV (已迁移到 DB)
│   └── benchmark_strategies.csv    # 性能测试策略矩阵
├── migrate_csv_to_db.py            # CSV → SQLite 一次性迁移脚本
├── main.py                         # CLI 总控 (sync/test/perf/accuracy/report)
└── config/.env                     # 敏感凭证 (TOS/HF/代理)
```

## 数据库设计

9 张核心表：

| 表 | 说明 |
|----|------|
| `models` | 模型注册 (name/slug/docker_command/tos_path/size/status) |
| `model_device_configs` | 模型-设备多对多配置 (每设备专属 docker 命令+测试状态) |
| `credentials` | SSH 凭证 (支持密钥路径 ssh_key 或密码 password 两种) |
| `devices` | 设备注册 (IP/类型/GPU/CPU/内存 + credential_id) |
| `tasks` | 测试任务 (queued→running→completed/failed/cancelled) |
| `model_runs` | 单模型执行记录 (deploying→validating→perf_testing→acc_testing→done) |
| `perf_results` | 性能明细 (吞吐/ TTFT/TPOT/ITL 均值及 P99) |
| `acc_results` | 准确率 (按数据集 mmlu/ceval/gsm8k/arc) |
| `task_logs` | 模块化日志 (container/vllm/perf/accuracy/system) |

### 设备管理架构

```
Device ──credential_id──> Credential
  │                         ├── type: ssh_key → ssh_key_path
  │                         └── type: password → password
  │
  └── ModelDeviceConfig (每个设备专属的 docker 命令和测试状态)
```

- **本机设备**: credential_id = null，所有命令本地执行
- **远程设备**: 通过 SSH (sshpass 密码 或 ssh -i 密钥) 连接并执行 docker 命令
- 设备健康检查会探测: SSH/Docker/GPU/内存/磁盘/CPU/vLLM

### 模型-设备配置

每个模型可以有多个设备配置，不同设备可以有不同的 docker 命令：

```
ModelInfo ──< ModelDeviceConfig >── Device
              ├── docker_command (该设备专属)
              └── status (NEW/PASS/FAIL)
```

任务创建时选择设备后，只显示**该设备上有配置且 PASS** 的模型。

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET/POST | `/api/models` | 模型列表/创建，支持 `?device_id=` 按设备筛选 |
| PUT/DELETE | `/api/models/{slug}` | 模型编辑/删除 |
| GET/POST | `/api/models/{slug}/device-configs` | 设备配置列表/添加 |
| PUT/DELETE | `/api/models/{slug}/device-configs/{id}` | 设备配置编辑/删除 |
| POST | `/api/models/{slug}/test?device_id=` | 一键测试 (启动容器→等待vLLM→对话验证) |
| GET/POST | `/api/devices` | 设备列表/添加 |
| PUT/DELETE | `/api/devices/{id}` | 设备编辑/删除 |
| POST | `/api/devices/{id}/check` | 健康检测 (SSH/Docker/GPU/Mem/Disk/CPU/vLLM) |
| GET/POST | `/api/credentials` | 凭证列表/创建 |
| PUT/DELETE | `/api/credentials/{id}` | 凭证编辑/删除 |
| GET/POST | `/api/tasks` | 任务列表/创建 |
| GET | `/api/tasks/{id}` | 任务详情 |
| POST | `/api/tasks/{id}/start` | 启动任务 |
| POST | `/api/tasks/{id}/pause` | 暂停任务 |
| POST | `/api/tasks/{id}/resume` | 恢复任务 |
| POST | `/api/tasks/{id}/cancel` | 取消任务 |
| GET | `/api/tasks/{id}/logs` | 任务日志 |
| GET | `/api/reports` | 报告列表，支持 `?device_id=` 筛选 |
| GET | `/api/reports/{id}` | 报告详情 |
| GET | `/api/reports/{id}/download` | 下载 Markdown 报告 |
| GET | `/api/reports/throughput-compare` | 吞吐量对比数据 |
| GET | `/api/reports/accuracy-compare` | 准确率对比数据 |

## 快速启动

### 环境要求

- Python 3.10+
- Node.js 18+
- Docker + nvidia-container-toolkit
- sshpass (远程设备管理需要)
- pigz, pigz (CLI 工具需要)

### 1. 安装后端依赖

```bash
cd aoni-model-platform
pip install -r backend/requirements.txt
```

### 2. 安装前端依赖

```bash
cd frontend
npm install
```

### 3. 初始化数据库 & 迁移数据

```bash
# 创建表结构并导入 CSV 中的 43 个模型
python3 migrate_csv_to_db.py
```

### 4. 启动后端

```bash
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8800
```

### 5. 启动前端开发服务器

```bash
cd frontend
npm run dev -- --host 0.0.0.0
```

前端: `http://<IP>:5173`  
后端: `http://<IP>:8800`

## 使用流程

### 添加远程设备

1. 打开 **设备管理** → "凭证管理" → 添加 SSH 凭证 (密钥路径或密码)
2. "添加设备" → 填写 IP → 选择凭证 → 保存
3. 点击 "检测" 验证设备连通性 (SSH/Docker/GPU/内存)

### 模型设备配置

1. 打开 **模块管理** → 点击模型的 "设备配置" 按钮
2. 选择设备 → 填写该设备专属的 docker 命令
3. 在目标设备上测试通过后，status 变为 PASS

### 创建任务

1. 打开 **任务管理** → "创建任务"
2. 选择执行设备 → 系统自动显示该设备上 PASS 的模型
3. 勾选要测试的模型 → 配置测试参数 → 创建
4. 启动任务，实时查看分模块日志

### 查看报告

1. 打开 **测试报告** → 可按设备筛选
2. 点击报告查看性能/准确率详细图表
3. 可下载 Markdown 格式报告

## CLI 工具 (遗留)

```bash
# 同步模型到 TOS
python3 main.py sync --task gemma

# 批量测试
python3 main.py test --start 1 --end 43

# 断点续测
python3 main.py test --resume

# 性能测试
python3 main.py perf --model functiongemma

# 准确率评测
python3 main.py accuracy --model qwen2.5-7b --datasets mmlu,ceval --limit 200

# 生成报告
python3 main.py report
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + Vite + Element Plus + ECharts + Axios |
| 后端 | FastAPI + SQLAlchemy + SQLite + subprocess |
| 远程执行 | sshpass / OpenSSH (密码或密钥认证) |
| 容器 | Docker + nvidia-container-toolkit |
| 推理 | vLLM (vllm bench serve) |
| 评测 | EvalScope + ModelScope 数据集 |
| 存储 | 火山引擎 TOS (模型权重) |
