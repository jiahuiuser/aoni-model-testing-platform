<template>
  <div class="task-detail-page">
    <el-page-header @back="$router.push('/')" :content="task?.name || '加载中...'" />

    <div style="margin-top: 16px; display: flex; gap: 16px; align-items: center;">
      <el-tag :type="statusType(task?.status)">{{ statusLabel(task?.status) }}</el-tag>
      <span style="color:#909399">Profile: {{ task?.profile }}</span>
      <span style="color:#909399">进度: {{ task?.completed_count }}/{{ task?.model_count }}</span>
    </div>

    <!-- 分模块日志 -->
    <el-card style="margin-top: 16px;">
      <template #header>
        <span style="font-weight:600">日志输出</span>
      </template>
      <el-tabs v-model="logTab" type="card">
        <el-tab-pane label="全部" name="all" />
        <el-tab-pane label="容器" name="container" />
        <el-tab-pane label="vLLM" name="vllm" />
        <el-tab-pane label="性能测试" name="perf" />
        <el-tab-pane label="准确率测试" name="accuracy" />
      </el-tabs>
      <div ref="logContainer" class="log-viewer">
        <div v-for="log in filteredLogs" :key="log.id" :class="`log-line log-${log.level?.toLowerCase()}`">
          <span class="log-time">{{ formatTime(log.created_at) }}</span>
          <span class="log-module">{{ moduleLabel(log.module) }}</span>
          <span v-if="log.model_slug" class="log-model">[{{ log.model_slug }}]</span>
          <span class="log-level" :class="`level-${log.level?.toLowerCase()}`">{{ log.level }}</span>
          <span class="log-msg">{{ log.message }}</span>
        </div>
        <div v-if="filteredLogs.length === 0" style="color:#909399; text-align:center; padding:40px;">
          {{ task ? '暂无该模块日志' : '加载中...' }}
        </div>
      </div>
    </el-card>

    <!-- 模型执行状态 -->
    <el-card style="margin-top: 16px;">
      <template #header>模型执行状态</template>
      <el-table :data="modelRuns" stripe size="small">
        <el-table-column prop="model_idx" label="#" width="50" />
        <el-table-column prop="model_name" label="模型" min-width="180" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="modelStatusType(row.status)" size="small">
              {{ modelStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="160">
          <template #default="{ row }">
            <el-progress :percentage="row.progress" :stroke-width="6" />
          </template>
        </el-table-column>
        <el-table-column prop="progress_detail" label="详情" min-width="200" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { apiGetTask, apiGetTaskLogs } from '../api'

const route = useRoute()
const taskId = computed(() => route.params.id)
const task = ref(null)
const logs = ref([])
const modelRuns = ref([])
const logContainer = ref(null)
const logTab = ref('all')
const lastLogId = ref(0)

let pollTimer = null

const moduleLabel = (m) => {
  const map = { container: '[容器]', vllm: '[vLLM]', perf: '[性能]', accuracy: '[准确率]', system: '[系统]' }
  return map[m] || ''
}

const filteredLogs = computed(() => {
  if (logTab.value === 'all') return logs.value
  return logs.value.filter(l => l.module === logTab.value)
})

const statusType = (s) => ({ running: 'primary', completed: 'success', failed: 'danger', paused: 'warning', cancelled: 'info', queued: '' })[s] || 'info'
const statusLabel = (s) => ({ queued: '排队中', running: '运行中', completed: '已完成', failed: '失败', paused: '已暂停', cancelled: '已取消' })[s] || s

const modelStatusType = (s) => ({ deploying: 'warning', validating: 'warning', perf_testing: 'primary', acc_testing: 'primary', reporting: '', done: 'success' })[s] || 'info'
const modelStatusLabel = (s) => ({ deploying: '容器部署', validating: '服务就绪', perf_testing: '性能测试', acc_testing: '准确率测试', reporting: '生成报告', done: '完成' })[s] || s

const formatTime = (t) => t ? new Date(t).toLocaleTimeString() : ''

const loadTask = async () => {
  try {
    task.value = await apiGetTask(taskId.value)
    modelRuns.value = task.value.model_runs || []
  } catch (e) { console.error(e) }
}

const scrollToBottom = () => {
  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
}

const pollLogs = async () => {
  try {
    const newLogs = await apiGetTaskLogs(taskId.value)
    if (newLogs && newLogs.length > 0) {
      const sorted = [...newLogs].reverse()
      for (const log of sorted) {
        if (log.id > lastLogId.value) {
          logs.value.push(log)
          lastLogId.value = log.id
        }
      }
      scrollToBottom()
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
  scrollToBottom()
  startPolling()
})

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
.level-info { color: #569cd6; }
.level-warning { color: #ce9178; }
.level-error { color: #f44747; }
.log-msg { color: #d4d4d4; }
</style>
