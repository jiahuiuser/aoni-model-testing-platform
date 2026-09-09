# 项目协作约定

## 工作方式
- 激进使用子 agent：凡是可并行、可独立拆分的任务（代码探索、搜索、审查、多个互不依赖的修改），主动派 general/explore 子 agent 并行执行，不要等用户要求
- 小改动、强上下文任务直接自己做，不派发
- 修改前先确认用户真实意图，方案有分歧时先问再动手，不要自作主张扩大改动范围

## 项目速览
- 大模型测试平台：FastAPI 后端 (backend/, 端口 8800, 无热重载，改代码需手动重启) + Vue3/ElementPlus 前端 (frontend/, vite dev 端口 5173)
- 数据库: data/aoni_platform.db (SQLite)
- 前端构建: cd frontend && npx vite build
