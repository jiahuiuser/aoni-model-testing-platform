<template>
  <div class="task-detail-page">
    <el-page-header @back="$router.push('/')" :content="task ? `任务 #${task.id} — ${task.name}` : '加载中...'" />

    <div style="margin-top: 16px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
      <el-tag :type="statusType(task?.status)" size="large" effect="dark">{{ statusLabel(task?.status) }}</el-tag>
      <el-tag type="info" size="large">执行设备: {{ task?.device_name || 'Jetson Thor' }}</el-tag>
      <span style="color:#6b7280;font-size:14px">测试 Profile: <b>{{ task?.profile }}</b></span>
      <span style="color:#6b7280;font-size:14px">模型完成进度: <b>{{ task?.completed_count }}/{{ task?.model_count }}</b></span>
      <el-tag v-if="taskTimeSummary" type="warning" size="large" effect="plain" style="font-weight: bold;">
        {{ taskTimeSummary }}
      </el-tag>
      <el-button
        v-if="task && ['failed', 'completed', 'cancelled', 'paused'].includes(task.status)"
        type="primary"
        size="small"
        style="margin-left: auto;"
        @click="handleRerunTask"
      >
        <el-icon><RefreshRight /></el-icon> 重新运行任务
      </el-button>
    </div>

    <!-- 顶部大 Tab 区分配置与日志 -->
    <el-tabs v-model="mainTab" style="margin-top: 16px;" type="border-card">
      <el-tab-pane label="运行日志与模型进度" name="execution">
        <!-- 模型执行状态 -->
        <el-card style="margin-bottom: 16px;" shadow="never">
          <template #header><span style="font-weight:700">模型测试列表与阶段进度</span></template>
          <el-table :data="modelRuns" stripe size="small" border>
            <el-table-column prop="model_idx" label="#" width="45" align="center" />
            <el-table-column prop="model_name" label="模型名称" min-width="160" />
            <el-table-column label="阶段状态" width="110" align="center">
              <template #default="{ row }">
                <el-tag :type="modelStatusType(row.status)" size="small">
                  {{ modelStatusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="阶段进度" width="150">
              <template #default="{ row }">
                <el-progress :percentage="row.progress" :stroke-width="8" :status="row.status === 'done' ? 'success' : (row.status === 'failed' ? 'exception' : '')" />
              </template>
            </el-table-column>
            <el-table-column label="时间消耗 & 预估剩余 (ETA)" width="220">
              <template #default="{ row }">
                <div v-if="parseDetail(row.progress_detail).elapsed || parseDetail(row.progress_detail).eta" style="display:flex; gap:6px; flex-wrap:wrap; align-items:center;">
                  <el-tag v-if="parseDetail(row.progress_detail).elapsed" size="small" type="info" effect="plain">
                    已用: {{ parseDetail(row.progress_detail).elapsed }}
                  </el-tag>
                  <el-tag v-if="parseDetail(row.progress_detail).eta && row.status !== 'done' && row.status !== 'failed'" size="small" type="danger" effect="plain">
                    预计剩余: {{ parseDetail(row.progress_detail).eta }}
                  </el-tag>
                  <el-tag v-if="row.status === 'done'" size="small" type="success">
                    耗时完成
                  </el-tag>
                  <el-tag v-else-if="row.status === 'failed'" size="small" type="danger">
                    测试失败
                  </el-tag>
                </div>
                <span v-else style="color:#909399; font-size:12px;">--</span>
              </template>
            </el-table-column>
            <el-table-column label="最新实时指标与进度" min-width="240">
              <template #default="{ row }">
                <div v-if="parseDetail(row.progress_detail).info" style="font-size: 13px; font-weight: 500; color: #303133;">
                  {{ parseDetail(row.progress_detail).info }}
                </div>
                <div v-else-if="row.progress_detail" style="font-size: 12px; color: #606266;">
                  {{ row.progress_detail }}
                </div>
                <div v-else style="color:#909399; font-size:12px;">等待执行...</div>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <!-- API 协议规范校验明细 (按接口协议分为独立测试套件用例) -->
        <el-card v-if="hasGatewayResults" style="margin-bottom: 16px;" shadow="never">
          <template #header>
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-weight:700">API 协议规范校验测试套件结论</span>
              <el-tag type="info" size="small">按接口协议独立用例集拆分展示</el-tag>
            </div>
          </template>

          <div v-for="mr in modelRuns" :key="mr.id" style="margin-bottom: 24px;">
            <div v-if="mr.gateway_results && mr.gateway_results.length > 0">
              <div style="margin-bottom: 12px; display:flex; align-items:center; gap:8px;">
                <span style="font-weight: 600; font-size: 14px; color: #1e293b;">测试模型：{{ formatModelDisplayName(mr) }}</span>
              </div>

              <!-- 按协议套件卡片列表 -->
              <div v-for="suite in getProtocolSuites(mr.gateway_results)" :key="suite.protocol" style="margin-bottom: 14px; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; background: #fafafa;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                  <div style="display: flex; align-items: center; gap: 8px;">
                    <el-tag size="small" type="primary" effect="dark">{{ suite.protocol }}</el-tag>
                    <span style="font-weight: 600; font-size: 13px; color: #334155;">{{ suite.name }}</span>
                    <span style="color: #64748b; font-size: 12px;">({{ suite.items.length }} 个测试用例)</span>
                  </div>
                  <div>
                    <el-tag
                      :type="suite.items.every(i => i.status === 'PASS') ? 'success' : (suite.items.some(i => i.status === 'FAIL') ? 'danger' : 'warning')"
                      size="small"
                      effect="dark"
                    >
                      {{ suite.items.every(i => i.status === 'PASS') ? '全量 PASS' : (suite.items.some(i => i.status === 'FAIL') ? '存在 FAIL' : '部分 SKIP') }}
                    </el-tag>
                  </div>
                </div>

                <el-table :data="suite.items" size="small" border stripe>
                  <el-table-column prop="test_item" label="用例名称 / 校验点" min-width="200" />
                  <el-table-column prop="status" label="结论" width="90" align="center">
                    <template #default="{ row }">
                      <el-tag :type="row.status === 'PASS' ? 'success' : (row.status === 'FAIL' ? 'danger' : 'warning')" size="small" effect="dark">
                        {{ row.status === 'PASS' ? '通过' : (row.status === 'FAIL' ? '失败' : '跳过') }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="latency_ms" label="耗时" width="95" align="right">
                    <template #default="{ row }">
                      <span>{{ row.latency_ms ? `${row.latency_ms} ms` : '--' }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="message" label="校验诊断与依据" min-width="260" />
                </el-table>
              </div>
            </div>
          </div>
        </el-card>

        <!-- 分模块日志 -->
        <el-card shadow="never">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
              <span style="font-weight:700">实时控制台日志</span>
              <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 13px; color: #606266; font-weight: 600;">日志输出档次:</span>
                <el-radio-group v-model="logVerbosity" size="small">
                  <el-radio-button label="low">精简 (摘要级)</el-radio-button>
                  <el-radio-button label="medium">标准 (业务级)</el-radio-button>
                  <el-radio-button label="high">调试 (全量/协议参数)</el-radio-button>
                </el-radio-group>
              </div>
            </div>
          </template>
          <el-tabs v-model="logTab" type="card">
            <el-tab-pane label="全部" name="all" />
            <el-tab-pane label="容器" name="container" />
            <el-tab-pane label="vLLM" name="vllm" />
            <el-tab-pane label="网关测试" name="gateway" />
            <el-tab-pane label="性能测试" name="perf" />
            <el-tab-pane label="准确率测试" name="accuracy" />
          </el-tabs>
          <div style="position: relative;">
            <div ref="logContainer" class="log-viewer" @scroll="handleLogScroll">
              <div v-for="log in filteredLogs" :key="log.id" :class="`log-line log-${log.level?.toLowerCase()}`">
                <span class="log-time">{{ formatTime(log.created_at) }}</span>
                <span class="log-module">{{ moduleLabel(log.module) }}</span>
                <span v-if="log.model_slug" class="log-model">[{{ log.model_slug }}]</span>
                <span class="log-level" :class="`level-${log.level?.toLowerCase()}`">{{ log.level }}</span>
                <span class="log-msg">{{ log.message }}</span>
              </div>
              <div v-if="filteredLogs.length === 0" style="color:#909399; text-align:center; padding:40px;">
                {{ task ? '当前档次分类下暂无日志记录' : '加载中...' }}
              </div>
            </div>
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="任务参数配置" name="config">
        <div v-if="task" style="padding: 8px;">
          <el-descriptions :column="1" border size="medium">
            <el-descriptions-item label="任务名称"><b>{{ task.name }}</b></el-descriptions-item>
            <el-descriptions-item label="任务 ID">#{{ task.id }}</el-descriptions-item>
            <el-descriptions-item label="执行设备">
              <el-tag type="success">{{ task.device_name || 'Jetson Thor (本机)' }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="测试 Profile">{{ task.profile }}</el-descriptions-item>
            <el-descriptions-item label="测试模型列表">
              <el-tag v-for="slug in (task.config?.model_slugs || [])" :key="slug" style="margin-right:6px">
                {{ slug }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="网关协议校验">
              <el-tag :type="task.config?.gateway_enabled !== false ? 'success' : 'info'">
                {{ task.config?.gateway_enabled !== false ? '已开启 (全量 OpenAI/Anthropic/Responses 规范校验)' : '已关闭' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="性能测试开关">
              <el-tag :type="task.config?.perf_enabled ? 'success' : 'info'">
                {{ task.config?.perf_enabled ? '已开启' : '已关闭' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="并发与场景配置">
              <div v-for="(rd, idx) in (task.config?.perf_rounds_config || [])" :key="idx" style="margin-bottom:4px">
                <span>输入长度: <b>{{ rd.input_len }}</b> | </span>
                <span>输出场景: <b>{{ rd.output_lens_str }}</b> (短/长文本) | </span>
                <span>并发梯度: <b>{{ rd.concurrencies_str || '阶梯并发' }}</b> | </span>
                <span>单轮请求数: <b>{{ rd.num_prompts || 100 }}</b></span>
              </div>
            </el-descriptions-item>
            <el-descriptions-item label="准确率测试开关">
              <el-tag :type="task.config?.acc_enabled ? 'success' : 'info'">
                {{ task.config?.acc_enabled ? '已开启' : '已关闭' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="样本评估模式/限制">
              <el-tag type="danger" effect="plain" style="font-weight: 600">
                {{ getAccLimitText(task.config) }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="勾选评测数据集与题量">
              <div style="display:flex; flex-wrap:wrap; gap:6px; margin-top:4px">
                <el-tag v-for="ds in (task.config?.acc_datasets || [])" :key="ds" type="warning">
                  <b>{{ ds.toUpperCase() }}</b>: {{ getDatasetSampleText(ds) }}
                </el-tag>
              </div>
            </el-descriptions-item>
            <el-descriptions-item label="超时与通知配置">
              <span>容器启动超时: <b>{{ task.config?.container_startup_timeout || 7200 }}秒</b> | </span>
              <span>通知邮箱: <b>{{ task.config?.notify_email || '未配置' }}</b></span>
            </el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ formatTime(task.created_at) }}</el-descriptions-item>
          </el-descriptions>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { apiGetTask, apiGetTaskLogs, apiTaskAction } from '../api'
import { formatTime } from '../utils/format'
import { ElMessage } from 'element-plus'

const route = useRoute()
const taskId = computed(() => route.params.id)
const task = ref(null)
const logs = ref([])
const modelRuns = ref([])
const logContainer = ref(null)
const mainTab = ref('execution')
const logTab = ref('all')
const logVerbosity = ref('medium') // 'low' | 'medium' | 'high'
const isUserScrolledUp = ref(false)

const DATASET_SAMPLE_COUNTS = {
  mmlu: '14,042 题 (全量 57 子集)',
  ceval: '13,948 题 (全量 52 科目)',
  gsm8k: '1,319 题 (全量)',
  arc: '1,172 题 (全量)',
  math500: '500 题 (全量)',
  humaneval: '164 题 (全量)',
  bigcodebench: '1,140 题 (全量)',
  longbench_pro: '3,000 题 (全量)',
  gpqa: '198 题 (全量)',
  aime24: '30 题 (全量)',
  arena_hard: '500 题 (全量)',
  math_500: '500 题 (全量)',
  longbench_v2: '3,000 题 (全量)',
  gpqa_diamond: '198 题 (全量)',
}

const getDatasetSampleText = (ds) => {
  const key = (ds || '').toLowerCase()
  return DATASET_SAMPLE_COUNTS[key] || '真实样本库'
}

const getAccLimitText = (cfg) => {
  if (!cfg) return '全量测试 (不限上限)'
  const limit = cfg.acc_limit
  if (limit === 0 || limit === undefined || limit === null) {
    return '全量测试模式 (全量题库不限上限评估)'
  }
  return `抽样测试模式 (每数据集评估上限 ${limit} 题)`
}

const lastLogId = ref(0)

let pollTimer = null

const moduleLabel = (m) => {
  const map = { container: '[容器]', vllm: '[vLLM]', perf: '[性能]', accuracy: '[准确率]', system: '[系统]' }
  return map[m] || ''
}

const filteredLogs = computed(() => {
  let list = logs.value

  // 1. 模块分类 Tab 过滤
  if (logTab.value !== 'all') {
    list = list.filter(l => l.module === logTab.value)
  }

  // 2. 日志输出档次 (Verbosity Level) 过滤
  if (logVerbosity.value === 'low') {
    // 精简 (摘要级): 仅显示大阶段标头、核心测试里程碑结论与告警报错
    list = list.filter(l => {
      const lvl = (l.level || '').toUpperCase()
      if (lvl === 'WARNING' || lvl === 'ERROR') return true
      const msg = l.message || ''
      return msg.includes('==========') || msg.includes('--- Layer') || msg.includes('测试完成') || msg.includes('结论:')
    })
  } else if (logVerbosity.value === 'medium') {
    // 标准 (业务级): 展示 INFO, WARNING, ERROR 业务关键流程，过滤 DEBUG 级别的底层请求 Payload 与 Raw Console 堆栈
    list = list.filter(l => {
      const lvl = (l.level || '').toUpperCase()
      return lvl !== 'DEBUG'
    })
  }
  // 调试 (全量/协议参数): 包含 DEBUG 级别的完整请求 Payload、Raw Console、底层 Trace 堆栈

  return list
})

const handleLogScroll = () => {
  if (!logContainer.value) return
  const { scrollTop, scrollHeight, clientHeight } = logContainer.value
  isUserScrolledUp.value = scrollHeight - (scrollTop + clientHeight) > 60
}

const scrollToBottom = (force = false) => {
  nextTick(() => {
    if (logContainer.value && (force || !isUserScrolledUp.value)) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
      if (force) isUserScrolledUp.value = false
    }
  })
}

const statusType = (s) => ({ running: 'primary', completed: 'success', failed: 'danger', paused: 'warning', cancelled: 'info', queued: '' })[s] || 'info'
const statusLabel = (s) => ({ queued: '排队中', running: '运行中', completed: '已完成', failed: '失败', paused: '已暂停', cancelled: '已取消' })[s] || s

const parseDetail = (detail) => {
  if (!detail) return { elapsed: '', eta: '', info: '' }
  const parts = detail.split('|').map(s => s.trim())
  let elapsed = ''
  let eta = ''
  const infoParts = []
  
  for (const part of parts) {
    if (part.startsWith('已用:')) {
      elapsed = part.replace('已用:', '').trim()
    } else if (part.startsWith('预计剩余:')) {
      eta = part.replace('预计剩余:', '').trim()
    } else {
      infoParts.push(part)
    }
  }
  return {
    elapsed,
    eta,
    info: infoParts.join(' | ')
  }
}

const taskTimeSummary = computed(() => {
  if (!modelRuns.value || modelRuns.value.length === 0) return ''
  const runningRun = modelRuns.value.find(r => r.status && r.status !== 'done')
  if (runningRun) {
    const detail = parseDetail(runningRun.progress_detail)
    if (detail.eta) {
      return `当前模型 [${runningRun.model_name}]: 预估剩余 ${detail.eta}`
    }
    if (detail.elapsed) {
      return `当前模型 [${runningRun.model_name}]: 已用 ${detail.elapsed}`
    }
    return `当前模型 [${runningRun.model_name}] 正在测试`
  }
  return '所有模型测试已全部完成'
})

const hasGatewayResults = computed(() => {
  return modelRuns.value.some(r => r.gateway_results && r.gateway_results.length > 0)
})

function getProtocolSuites(gatewayResults) {
  if (!gatewayResults || gatewayResults.length === 0) return []
  const groupMap = {
    system: { name: '系统与服务可达性测试套件', protocol: 'SYSTEM', items: [] },
    openai: { name: 'OpenAI 接口规范测试套件 (/v1/chat/completions)', protocol: 'OPENAI', items: [] },
    responses: { name: 'OpenAI Responses 接口规范测试套件 (/v1/responses)', protocol: 'RESPONSES', items: [] },
    anthropic: { name: 'Anthropic Messages 接口规范测试套件 (/v1/messages)', protocol: 'ANTHROPIC', items: [] },
  }
  
  gatewayResults.forEach(gr => {
    const proto = (gr.protocol || 'system').toLowerCase()
    if (!groupMap[proto]) {
      groupMap[proto] = { name: `${proto.toUpperCase()} 接口协议测试套件`, protocol: proto.toUpperCase(), items: [] }
    }
    groupMap[proto].items.push(gr)
  })
  
  return Object.values(groupMap).filter(g => g.items.length > 0)
}

const modelStatusType = (s) => ({ deploying: 'warning', validating: 'warning', gateway_testing: 'primary', perf_testing: 'primary', acc_testing: 'primary', reporting: '', done: 'success' })[s] || 'info'
const modelStatusLabel = (s) => ({ deploying: '容器部署', validating: '服务就绪', gateway_testing: '网关测试', perf_testing: '性能测试', acc_testing: '准确率测试', reporting: '生成报告', done: '完成' })[s] || s

const loadTask = async () => {
  try {
    task.value = await apiGetTask(taskId.value)
    modelRuns.value = task.value.model_runs || []
  } catch (e) { console.error(e) }
}

const handleRerunTask = async () => {
  if (!task.value) return
  try {
    await apiTaskAction(task.value.id, 'rerun')
    ElMessage.success('已重置并重新下发测试任务！')
    await loadTask()
    startPolling()
  } catch (e) {
    ElMessage.error('重新运行任务失败: ' + (e.response?.data?.detail || e.message))
  }
}

const MAX_LOGS_DISPLAY = 2000

const pollLogs = async () => {
  try {
    const afterId = lastLogId.value > 0 ? lastLogId.value : null
    const newLogs = await apiGetTaskLogs(taskId.value, null, 500, afterId)
    if (newLogs && newLogs.length > 0) {
      if (lastLogId.value > 0 && newLogs[0].id < lastLogId.value) {
        logs.value = []
        lastLogId.value = 0
      }
      for (const log of newLogs) {
        if (log.id > lastLogId.value) {
          logs.value.push(log)
          lastLogId.value = log.id
        }
      }
      if (logs.value.length > MAX_LOGS_DISPLAY) {
        logs.value = logs.value.slice(logs.value.length - MAX_LOGS_DISPLAY)
      }
      scrollToBottom(false)
    }
  } catch (e) { /* 静默 */ }
}

const startPolling = () => {
  pollTimer = setInterval(async () => {
    await loadTask()
    await pollLogs()
    if (task.value && ['completed', 'failed', 'cancelled'].includes(task.value.status)) {
      stopPolling()
      await pollLogs()
    }
  }, 2000)
}

const stopPolling = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

onMounted(async () => {
  await loadTask()
  await pollLogs()
  scrollToBottom(true)
  startPolling()
})

function formatModelDisplayName(mr) {
  if (!mr) return ''
  const name = mr.model_name || ''
  const slug = mr.model_slug || ''
  if (!slug || name.toLowerCase() === slug.toLowerCase()) {
    return name || slug
  }
  return `${name} (${slug})`
}

onUnmounted(() => { stopPolling() })
</script>

<style scoped>
.task-detail-page { padding: 0; }

.log-viewer {
  background: #1e1e1e; color: #d4d4d4; font-family: 'Courier New', monospace;
  font-size: 13px; padding: 12px; border-radius: 0 0 4px 4px; height: 400px; overflow-y: auto;
}
.log-line { padding: 2px 0; white-space: pre-wrap; word-break: break-all; }
.log-time { color: #858585; margin-right: 8px; }
.log-module { color: #ce9178; margin-right: 4px; font-weight: bold; }
.log-model { color: #4ec9b0; margin-right: 4px; }
.log-level { margin-right: 8px; }
.level-debug { color: #c586c0; font-weight: bold; }
.level-info { color: #569cd6; }
.level-warning { color: #ce9178; }
.level-error { color: #f44747; }
.log-line.log-debug .log-msg { color: #9cdcfe; }
.log-msg { color: #d4d4d4; }
</style>
