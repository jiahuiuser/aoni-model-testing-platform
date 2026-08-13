# 恢复：Qwen 8 模型部署配置（--max-model-len / --gpu-memory-utilization）

> **日期**：2026-08-13　**原因**：为 task #43 `Qwen 8模型性能矩阵 (max32K)` 压测提升上下文与显存配置
> 配置修改后，若某模型部署 OOM 起不来，可按此文件恢复原值。

## 修改内容

下列 8 款 Qwen 模型的部署命令：
- `--max-model-len` 统一提升为 **32768**（此前部分模型仅 8K/16K）
- `--gpu-memory-utilization` 采用平台分档经验值（中大 0.80 / 小 0.70），而非过高的 0.95，避免 OOM

同时作用在 `models` 表与 `model_device_configs`（设备 1）两处的 `docker_command`。

## 修改前后对照

| slug | 旧 max-model-len | 新 max-model-len | 旧 gpu-mem | 新 gpu-mem |
|------|----------------:|----------------:|----------:|----------:|
| qwen3-8b        | 16384 | 32768 | 0.70 | 0.70 |
| qwen3-5-9b      | 16384 | 32768 | 0.80 | 0.80 |
| qwen3-32b       | 16384 | 32768 | 0.80 | 0.80 |
| qwen3-5-4b      |  8192 | 32768 | 0.70 | 0.70 |
| qwen3-6-27b     | 32768 | 32768 | 0.80 | 0.80 |
| qwen3-6-35b-a3b | 32768 | 32768 | 0.80 | 0.80 |
| qwen3-vl-4b     |  8192 | 32768 | 0.70 | 0.70 |
| qwen3-vl-8b     | 16384 | 32768 | 0.70 | 0.70 |

> 说明：Qwen3.5/3.6/VL 系列 config.json 真实上下文可达 262144，但因 Jetson Thor 122G 统一内存的 KV cache 限制，本次采用安全值 32768 而非真实极限，以确保部署稳定。
> 显存按平台已验证经验值分档（中大 0.80 / 小 0.70），未采用过高的 0.95。

## 如何恢复

将 `--max-model-len` / `--gpu-memory-utilization` 改回上表"旧"栏数值即可（各改两次：`models` 表 + `model_device_configs` 表）。

也可用变更前数据库完整备份整体恢复：
```bash
# 备份当前库
cp data/aoni_platform.db /tmp/opencode/aoni_platform.db.revert_$(date +%s)
# 用备份覆盖（备份文件：aoni_platform.backup-20260813.db）
cp /path/to/aoni_platform.backup-20260813.db data/aoni_platform.db
rm -f data/aoni_platform.db-wal data/aoni_platform.db-shm
# 重启后端服务
```
