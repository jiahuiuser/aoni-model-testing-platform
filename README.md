# AONI 智能体模型平台

NVIDIA Jetson AGX Thor (T5000) 多设备模型运维与测试平台。支持 43 款 LLM/VLM 的自动化部署、vLLM 矩阵性能测试、EvalScope 准确率评测，并提供高颜值 Vue 3 Web 管理界面与多设备远程 SSH 调度管理。

---

## 🚀 核心特性

- **多设备 SSH 远程调度**：支持本机与远程 Jetson Thor 节点调度，集成基于 SSH (sshpass/密钥) 的远程 Docker 部署与健康度深度检测（GPU/CPU/内存/磁盘/vLLM）。
- **TOS 云端模型扫描与勾选导入**：集成火山引擎 TOS 存储，支持一键目录前缀扫描、模型文件预览与批量增量导入。
- **高阶性能矩阵与测试看板**：基于 vLLM Bench，支持不同并发梯度（1~64）、输入/输出 Token 长度等级（短/中/长）的吞吐量 (tok/s)、TTFT、TPOT、ITL 均值及 P99 折线图联动对比。
- **用户权限与酷炫交互**：支持 JWT 身份认证、用户管理 (Admin/User)、多套动态科技主题皮肤（Cyber Nebula, Neon Aurora, Sunset Gold, Glacier Crystal）及 Aoni 矢量青蛙 Mascot 交互动画。
- **并发稳定与自愈机制**：后端升级 SQLite WAL 模式、自动展开 `~` 绝对路径、无死锁非交互 Shell 调度及任务自愈检测。

---

## 🏗️ 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│             Vue3 Web 管理界面 (端口 5173 / Pinia / ECharts)  │
│ 任务管理 │ 模型管理 │ 设备管理 │ 凭证管理 │ 测试报告 │ 用户管理 │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API / SSE 流式日志
┌──────────────────────────┴──────────────────────────────────┐
│                  FastAPI 后端 (端口 8800)                    │
│  Task CRUD │ Model + TOS 扫描 │ JWT Auth │ 报告生成 (JSON/MD) │
│  RemoteRunner (本机免 sudo Docker / SSH 远程节点调度)          │
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

---

## 📂 目录结构

```
Aoni_Model_Testing_Platform/
├── backend/                        # FastAPI 后端
│   ├── main.py                     # 入口 (端口 8800)
│   ├── config.py                   # 全局配置 (自动加载 config/.env)
│   ├── database.py                 # SQLAlchemy WAL 模式连接管理
│   ├── auth.py                     # JWT 认证与密码 Hash
│   ├── requirements.txt            # Python 依赖
│   ├── models/
│   │   ├── __init__.py             # ORM: ModelInfo/Device/Credential/Task/PerfResult...
│   │   └── user.py                 # ORM: User 用户表
│   ├── schemas/
│   │   └── __init__.py             # Pydantic 请求/响应模型
│   ├── routers/
│   │   ├── auth.py                 # 登录/登出/当前用户信息
│   │   ├── tasks.py                # 任务 CRUD + 实时日志推送
│   │   ├── models.py               # 模型 CRUD + TOS 动态扫描 + 设备配置 + 一键测试
│   │   ├── devices.py              # 设备 CRUD + 凭证管理 + SSH 健康检测
│   │   └── reports.py              # 报告列表/详情/对比图表/Markdown 下载
│   └── services/
│       ├── executor.py             # 主执行器 (本地/SSH RemoteRunner + raw logs)
│       ├── task_manager.py         # 任务生命周期 (创建/暂停/恢复/取消/自愈)
│       ├── pipeline.py             # 模型分类 & 并发梯度策略
│       └── scheduler.py            # 执行排序 (小模型优先)
├── frontend/                       # Vue3 前端
│   ├── vite.config.js              # Vite 配置 (端口 5173, API 代理)
│   ├── package.json                # 依赖: Vue3/Element-Plus/ECharts/Pinia/Axios
│   └── src/
│       ├── App.vue                 # 主布局 (侧边栏 + 状态同步 + 探针Modal)
│       ├── router/index.js         # 8 个页面路由 (带路由守卫)
│       ├── api/index.js            # Axios 封装 (带 JWT 拦截)
│       ├── stores/                 # Pinia 状态库 (authStore, testStore)
│       └── views/
│           ├── Login.vue           # 炫酷登录页 (4套主题 + 青蛙 Mascot + 粒子)
│           ├── TaskList.vue        # 任务列表 (分视角展示)
│           ├── TaskCreate.vue      # 创建任务 (选设备→选模型→梯度参数配置)
│           ├── TaskDetail.vue      # 任务详情 (分模块 SSE 日志)
│           ├── ModelManagement.vue # 模型管理 + TOS 扫描导入 + 设备配置
│           ├── DeviceManagement.vue# 设备管理 + 凭证管理
│           ├── Reports.vue         # 报告列表 + 多模型对比看板
│           ├── ReportDetail.vue    # 报告详情 (矩阵图表联动/折线对比)
│           └── UserManagement.vue  # 用户权限管理 (仅管理员)
├── config/
│   └── .env                        # 本地敏感配置 (TOS AK/SK, HF Token, 代理)
├── data/
│   ├── aoni_platform.db            # SQLite 数据库 (WAL 模式)
│   └── benchmark_strategies.csv    # 性能测试策略矩阵
├── scripts/
│   ├── seed_demo_reports.py        # 评测报告演示数据播种脚本
│   └── migrate_add_model_group.py  # 数据库迁移脚本
└── README.md
```

---

## 🗄️ 数据库设计

基于 SQLite (WAL 模式)，包含 10 张核心表：

| 表名 | 说明 |
|------|------|
| `users` | 用户账号表 (username/password_hash/role: admin/user) |
| `models` | 模型注册 (name/slug/group_name/docker_command/tos_path/size/status) |
| `model_device_configs` | 模型-设备专属配置 (设备专属 docker 命令 + PASS/FAIL 状态) |
| `credentials` | SSH 凭证 (密钥路径 `ssh_key` 或密码 `password`) |
| `devices` | 设备注册 (IP/GPU/CPU/内存/ credential_id) |
| `tasks` | 测试任务生命周期 (queued → running → completed/failed/cancelled) |
| `model_runs` | 单模型执行记录 (deploying → validating → perf_testing → acc_testing → done) |
| `perf_results` | 性能评测明细 (输入输出长度/并发/吞吐 tok/s/ TTFT/TPOT/ITL P99) |
| `acc_results` | 准确率明细 (mmlu/ceval/gsm8k/arc) |
| `task_logs` | 模块化日志 (container/vllm/perf/accuracy/system) |

---

## ⚡ 快速启动

### 1. 环境要求
- Python 3.10+
- Node.js 18+
- Docker + `nvidia-container-toolkit`
- `sshpass` (远程节点调度需要)

### 2. 配置文件说明
复制或编辑 `config/.env`（已加 `.gitignore` 保护）：
```env
# TOS 凭证
TOS_ACCESS_KEY=your_access_key
TOS_SECRET_KEY=your_secret_key
TOS_ENDPOINT=https://tos-cn-guangzhou.volces.com
TOS_BUCKET=ai-hub

# HuggingFace Token
HF_TOKEN=your_hf_token

# 代理配置 (可选)
HTTP_PROXY=http://127.0.0.1:7897
HTTPS_PROXY=http://127.0.0.1:7897
```

### 3. 安装依赖与启动服务

```bash
# 启动后端 (端口 8800)
pip install -r backend/requirements.txt
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8800
```

在另一个终端启动前端：

```bash
# 启动前端开发服务 (端口 5173)
cd frontend
npm install
npm run dev -- --host 0.0.0.0
```

访问链接：
- **前端 Web 界面**: `http://<服务器IP>:5173`
- **后端 API 文档**: `http://<服务器IP>:8800/docs`

---

## 🛠️ 技术栈

| 层级 | 技术栈 |
|------|------|
| **前端** | Vue 3 + Vite + Element Plus + ECharts + Pinia + Canvas Particle FX |
| **后端** | FastAPI + SQLAlchemy (WAL Mode) + Uvicorn + Server-Sent Events (SSE) |
| **安全认证** | JWT Token + Passlib (Bcrypt Password Hashing) |
| **远程执行** | SSH RemoteRunner (sshpass / OpenSSH) + 本地免 sudo Docker 进程 |
| **推理与评测** | vLLM (vllm bench serve) + EvalScope |
| **云端存储** | 火山引擎 TOS (Model Weight Sync) |
