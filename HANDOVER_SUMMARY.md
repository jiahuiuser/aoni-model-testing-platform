# 🚀 AONI 模型测试平台 (Jetson Thor 运维评测) — 研发项目总结与交接文档

> **文档生成时间**: 2026-07-24  
> **适用场景**: 研发会话归档 / 新窗口接续研发 / 部署与维护指南  

---

## 📌 一、 项目概述

本平台（`AONI 模型测试平台`）专为 **NVIDIA Jetson AGX Thor / Orin** 等边缘计算与算力节点打造，具备大模型 (LLM / VLM) 部署、多设备任务调度、vLLM / llama-server 压测基准评测、实时连通性打字机验证控制台、多维评测报告对比看板及企业级 UI/UX 体验。

### 🛠️ 核心技术栈
- **后端 (Backend)**: Python 3.12 + FastAPI + SQLAlchemy + SQLite (WAL 模式) + Uvicorn + Server-Sent Events (SSE)
- **前端 (Frontend)**: Vue 3 + Pinia + Vue Router + Element Plus + ECharts + Vite + Canvas Particle FX
- **底层引擎**: vLLM, llama-server (`llama.cpp`), Docker Containers, SSH Remote Runner

---

## 📝 二、 用户需求与完成功能总结 (Chronological Tasks)

在本次开发会话中，完成了以下全部用户需求与系统改进：

| 序号 | 用户需求 directive | 完成状态 | 核心实现 / 变动点 |
| :--- | :--- | :---: | :--- |
| 1 | **任务管理和测试报告 ID 倒序** | ✅ 已完成 | 任务管理列表调整为升序排序 (`asc(Task.id)`)，报告列表按完成时间排序。 |
| 2 | **使用 vLLM Bench 去压测并记录命令** | ✅ 已完成 | 增强 `executor.py`，自动检测 `vllm bench` 入口点并输出 Raw Shell 命令日志。 |
| 3 | **测试报告按完成时间排序** | ✅ 已完成 | `api_list_reports` 接口调整为 `desc(ModelRun.completed_at), desc(ModelRun.id)`。 |
| 4 | **报告对比功能与手动触发按钮** | ✅ 已完成 | 在 `Reports.vue` 中增加了 `⚡ 生成对比看板` 和表格行勾选后 `⚡ 对比选中的报告` 显性按钮。 |
| 5 | **数据播种演示** | ✅ 已完成 | 编写并运行 `scripts/seed_demo_reports.py`，注入 5 大主流模型在多设备上的 Cross-Benchmark 样例数据。 |
| 6 | **登录界面背景与皮肤切换** | ✅ 已完成 | 打造了 4 套动态科技皮肤（Cyber Nebula, Neon Aurora, Sunset Gold, Glacier Crystal）及右上角一键切肤 Pill。 |
| 7 | **图案与动画效果** | ✅ 已完成 | 增加 Canvas 粒子网格、量子轨道环、3D 浮动 Badge 标签等现代动态视觉体验。 |
| 8 | **奥尼 (Aoni) 企业 Logo 趣味动画** | ✅ 已完成 | 打造了矢量 SVG 青蛙 Mascot 形象，支持鼠标视线追踪 (`pupilOffset`) 与密码输入防窥视 (Stealth Mode `^__^`)。 |
| 9 | **Logo 右侧截断与重复文字修复** | ✅ 已完成 | 修正 viewBox (`0 0 260 130`) 消除右侧截断，并去除了重复的品牌文本。 |
| 10 | **Cosmos Reason 2 2B 模型验证控制台未响应** | ✅ 已完成 | 修复 `App.vue` 模板变量拼写错误；展平 Docker 命令与展开波浪号绝对路径，解决死锁与容器异常退出。 |

---

## 🐞 三、 关键硬核 Bug 诊断与修复记录 (Root Cause & Fixes)

### 1. SQLite 数据库并发死锁 (Database Locked)
- **现象**: 异步任务与 Web 请求并发写入 SQLite 时抛出 `sqlite3.OperationalError: database is locked`。
- **根因**: SQLite 默认 Journal 模式在写入时会对整个数据库文件加排他锁。
- **修复**: 在 `backend/database.py` 中开启 `PRAGMA journal_mode=WAL` 并配置 `connect_args={"timeout": 30}`。

### 2. `sudo` 在 Python 非交互进程中挂起死锁
- **现象**: 执行一键验证时，接口停滞卡死 120 秒超时。
- **根因**: `_build_test_command` 强行添加了 `sudo` 前缀，在 Uvicorn 无 tty 终端的进程中调用 `sudo docker run` 会停在 `[sudo] password for sd1:` 提示符等待键盘输入。
- **修复**: 移除了命令中的 `sudo` 前缀，直接使用当前 `sd1` 用户（属 `docker` 用户组）执行原生 `docker run`。

### 3. Docker 挂载路径波浪号 `~` 未展开导致容器 0.1 秒崩溃退出
- **现象**: 后端看似拉起了容器，但用 `docker ps` 查看时容器不存在。
- **根因**: 命令中包含 `-v ~/models:/models`，Python `subprocess` 未在字符串中展开 `~` 为 `/home/sd1`，容器因找不到模型权重文件汁源瞬间崩溃退出；随后 `finally:` 触发了清理代码。
- **修复**: 在 `_build_test_command` 中通过 `os.path.expanduser("~")` 将 `~/models` 自动替换为绝对路径 `/home/sd1/models`；并将多行命令展平为干净的单行 Shell 命令。

### 4. 前端 Vue 模板变量拼写错误
- **现象**: 测试完成后，验证结果卡片无法正常渲染。
- **根因**: `App.vue` 208 行误写了 `testFinalResult`（正确应为 `testStore.finalResult`）。
- **修复**: 在 `App.vue` 中修复变量引用，恢复完整的 Thinking Process 思考过程与探针对话显示。

### 5. `sudo sysctl` 与 `run_docker` 强制加 `sudo` 导致非交互式密码询问阻塞死锁
- **现象**: 模型验证启动容器时界面卡住/停滞，后台没有成功启动容器或显示卡死在第一步。
- **根因**: 
  1. 后端代码中途调用 `sudo sysctl -w vm.drop_caches=3` 未加 `-n` 参数，在 FastAPI 无 tty 终端的子进程中触发了 `[sudo] password for sd1:` 阻塞。
  2. `RemoteRunner.run_docker` 与 `_start_container` 对所有节点（包含本机）一律前置 `sudo`，导致已在 `docker` 用户组的本机账户因 `sudo` 鉴权阻塞。
- **修复**: 
  - 在 `models.py` 与 `executor.py` 中使用 `sudo -n` 防止非交互式密码阻塞。
  - 区分本机与远程节点：本机直连一律使用原生 `docker` 指令（免 `sudo`），远程 SSH 节点根据凭证自动处理 `sudo` 鉴权。

---

## 📂 四、 核心代码修改清单

| 文件路径 | 修改内容与目的 |
| :--- | :--- |
| [backend/database.py](file:///home/sd1/Desktop/Aoni_Model_Testing_Platform/backend/database.py) | 配置 SQLite WAL 模式与 30s 写入超时，解决并发锁死问题。 |
| [backend/routers/tasks.py](file:///home/sd1/Desktop/Aoni_Model_Testing_Platform/backend/routers/tasks.py) | 添加任务自动完结 Self-Healing 逻辑与升序排序 (`asc(Task.id)`)。 |
| [backend/routers/reports.py](file:///home/sd1/Desktop/Aoni_Model_Testing_Platform/backend/routers/reports.py) | 调整评测报告列表 API 按照完成时间倒序。 |
| [backend/routers/models.py](file:///home/sd1/Desktop/Aoni_Model_Testing_Platform/backend/routers/models.py) | 展平 Docker 指令、展开 `~` 绝对路径、移除 `sudo` 死锁、优化 SSE 流式实时打字机日志推送。 |
| [backend/services/executor.py](file:///home/sd1/Desktop/Aoni_Model_Testing_Platform/backend/services/executor.py) | 增强 vLLM Bench Serve 命令检测与 Raw Shell Command 实时日志捕获。 |
| [frontend/src/App.vue](file:///home/sd1/Desktop/Aoni_Model_Testing_Platform/frontend/src/App.vue) | 修复 `testStore.finalResult` 变量引用；整合模型验证控制台 Modal 与右下角悬浮面板。 |
| [frontend/src/views/Login.vue](file:///home/sd1/Desktop/Aoni_Model_Testing_Platform/frontend/src/views/Login.vue) | 重构极具视觉冲击力的登录页，实现 Aoni 矢量青蛙 mascot（眼球追踪、密码隐身）、4 套主题皮肤与 Canvas 粒子系统。 |
| [frontend/src/views/Reports.vue](file:///home/sd1/Desktop/Aoni_Model_Testing_Platform/frontend/src/views/Reports.vue) | 增加显性生成对比看板按钮与表格行多选对比触发按钮。 |
| [scripts/seed_demo_reports.py](file:///home/sd1/Desktop/Aoni_Model_Testing_Platform/scripts/seed_demo_reports.py) | 丰富评测报告样例数据的自动化播种脚本。 |

---

## 🚀 五、 新窗口继续研发启动指南

如果您在新窗口或新会话中打开本项目，请执行以下命令检查并启动服务：

### 1. 检查后端服务 (FastAPI on Port 8800)
```bash
# 检查后端服务状态
curl -s http://127.0.0.1:8800/api/health

# 如果后端未运行，启动后端：
cd /home/sd1/Desktop/Aoni_Model_Testing_Platform
nohup python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8800 > /tmp/backend.log 2>&1 &
```

### 2. 检查前端服务 (Vite on Port 5173)
```bash
# 启动前端 Dev 开发服务器：
cd /home/sd1/Desktop/Aoni_Model_Testing_Platform/frontend
nohup npm run dev -- --host 0.0.0.0 > /tmp/frontend.log 2>&1 &
```

### 3. 访问链接
- **前端 Web 界面**: [http://192.168.1.40:5173](http://192.168.1.40:5173)
- **后端 API 文档**: [http://192.168.1.40:8800/docs](http://192.168.1.40:8800/docs)

---

## 🎯 六、 建议后续研发方向 (Roadmap & Next Steps)

1. **分布式多节点 SSH 监控增强**: 针对远程 Jetson 节点，可进一步增强 GPU/NPU 实时利用率、温度与功耗（Jetson Power Mode）的 WebSocket 流式推送。
2. **自定义测试数据集上传**: 在压测任务配置中增加数据集 CSV/JSONL 上传与 Token 长度分布分析。
3. **导出 PDF 评测报告**: 为测试报告对比看板增加一键导出 PDF / Markdown 运维评测简报功能。

---
