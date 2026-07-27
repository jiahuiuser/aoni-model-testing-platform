<template>
  <div class="task-list-page">
    <!-- 顶部统一 CRUD 操作工具栏 -->
    <div class="top-toolbar">
      <div class="toolbar-left">
        <el-button type="primary" @click="$router.push('/create')">
          <el-icon><Plus /></el-icon> 新建任务
        </el-button>
        <el-button type="info" plain :disabled="selectedTasks.length !== 1" @click="viewDetail(selectedTasks[0])">
          <el-icon><View /></el-icon> 查看详情与日志
        </el-button>
        <el-button type="warning" plain :disabled="selectedTasks.length !== 1 || singleSelected?.status === 'running'" @click="handleEditTask">
          <el-icon><Edit /></el-icon> 编辑任务
        </el-button>
        <el-button type="success" plain :disabled="selectedTasks.length !== 1" @click="showConfigDialog(selectedTasks[0])">
          <el-icon><Setting /></el-icon> 任务参数配置
        </el-button>
        <el-button v-if="singleSelected?.status === 'running'" type="warning" plain @click="handleAction('pause')">
          <el-icon><VideoPause /></el-icon> 暂停任务
        </el-button>
        <el-button v-if="singleSelected?.status === 'paused'" type="success" plain @click="handleAction('resume')">
          <el-icon><VideoPlay /></el-icon> 继续任务
        </el-button>
        <el-popconfirm
          v-if="selectedTasks.length > 0"
          :title="`确定删除选中的 ${selectedTasks.length} 个任务？`"
          confirm-button-text="确认删除"
          cancel-button-text="取消"
          confirm-button-type="danger"
          placement="bottom"
          :teleported="true"
          @confirm="handleBatchDelete"
        >
          <template #reference>
            <el-button type="danger" plain>
              <el-icon><Delete /></el-icon> 批量删除 ({{ selectedTasks.length }})
            </el-button>
          </template>
        </el-popconfirm>
      </div>

      <div class="toolbar-right">
        <el-button circle @click="loadTasks"><el-icon><Refresh /></el-icon></el-button>
      </div>
    </div>

    <!-- 顶部任务状态 Summary Cards -->
    <div class="task-summary-cards">
      <div class="summary-card blue">
        <div class="card-num">{{ runningCount }}</div>
        <div class="card-title"><span class="dot-pulse"></span> 运行中任务</div>
      </div>
      <div class="summary-card green">
        <div class="card-num">{{ completedCount }}</div>
        <div class="card-title">已完成任务</div>
      </div>
      <div class="summary-card yellow">
        <div class="card-num">{{ pausedCount }}</div>
        <div class="card-title">已暂停任务</div>
      </div>
      <div class="summary-card gray">
        <div class="card-num">{{ totalCount }}</div>
        <div class="card-title">历史任务总量</div>
      </div>
    </div>

    <!-- 管理员视角全览 Alert 提示 -->
    <el-alert
      v-if="authStore.isAdmin"
      type="success"
      show-icon
      :closable="false"
      style="margin-bottom: 14px;"
    >
      <template #title>
        <span style="font-size:13px;font-weight:600;">
          👑 管理员视角全览模式：您当前正查看全平台所有账号下创建的测试任务 (包含 admin / tjh / 新建立账号)。
        </span>
      </template>
    </el-alert>

    <!-- 多选表格 -->
    <el-table
      ref="tableRef"
      :data="tasks"
      v-loading="loading"
      stripe
      border
      @selection-change="handleSelectionChange"
      @row-click="handleRowClick"
      @row-dblclick="(row) => viewDetail(row)"
      class="custom-table"
    >
      <el-table-column type="selection" width="50" align="center" />
      <el-table-column prop="id" label="ID" width="65" align="center" />
      <el-table-column prop="name" label="任务名称" min-width="220" show-overflow-tooltip />
      <el-table-column label="执行设备" width="165">
        <template #default="{ row }">
          <el-tag size="small" type="info">🖥️ {{ row.device_name || 'Jetson Thor (本机)' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="所属账号" width="125" align="center">
        <template #default="{ row }">
          <el-tag
            size="small"
            :type="(row.username === 'admin' || !row.username) ? 'danger' : 'success'"
            effect="dark"
          >
            {{ (row.username === 'admin' || !row.username) ? '👑 admin' : `👤 ${row.username}` }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="测试进度" min-width="180">
        <template #default="{ row }">
          <el-progress
            :percentage="row.model_count ? Math.round(row.completed_count / row.model_count * 100) : 0"
            :status="row.status === 'completed' ? 'success' : ''"
            :stroke-width="8"
          />
        </template>
      </el-table-column>
      <el-table-column label="模型进度" width="100" align="center">
        <template #default="{ row }">
          <span style="font-weight:600;color:#2563eb">{{ row.completed_count }}</span> / {{ row.model_count }}
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="180">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
    </el-table>

    <!-- 任务配置参数详情弹窗 (问题 3) -->
    <el-dialog v-model="configDialogVisible" title="⚙️ 任务完整参数配置" width="600px" destroy-on-close>
      <div v-if="currentConfigTask" class="config-detail-box">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="任务 ID & 名称">
            <span style="font-weight:700">#{{ currentConfigTask.id }} {{ currentConfigTask.name }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="执行目标设备">
            <el-tag size="small" type="success">{{ currentConfigTask.device_name || 'Jetson Thor (本机)' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="测试 Profile">
            <el-tag size="small" type="primary">{{ currentConfigTask.profile }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="包含模型 Slugs">
            <div class="tag-wrap">
              <el-tag v-for="slug in (currentConfigTask.config?.model_slugs || [])" :key="slug" size="small" style="margin:2px">
                {{ slug }}
              </el-tag>
            </div>
          </el-descriptions-item>
          <el-descriptions-item label="性能测试开关">
            <el-tag :type="currentConfigTask.config?.perf_enabled ? 'success' : 'info'" size="small">
              {{ currentConfigTask.config?.perf_enabled ? '已开启' : '未开启' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="并发与 Token 轮次设置">
            <div v-for="(rd, idx) in (currentConfigTask.config?.perf_rounds_config || [])" :key="idx" class="round-detail-item">
              <span>输入长度: <b>{{ rd.input_len }}</b> tokens</span> |
              <span>输出场景: <b>{{ rd.output_lens_str }}</b> (短/长文本)</span> |
              <span>并发梯度: <b>{{ rd.concurrencies_str || '自动阶梯并发' }}</b></span> |
              <span>单轮请求数: <b>{{ rd.num_prompts || 100 }}</b></span>
            </div>
          </el-descriptions-item>
          <el-descriptions-item label="准确率测试开关">
            <el-tag :type="currentConfigTask.config?.acc_enabled ? 'success' : 'info'" size="small">
              {{ currentConfigTask.config?.acc_enabled ? '已开启' : '未开启' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="评测数据集与 Limit">
            <div class="tag-wrap">
              <el-tag v-for="ds in (currentConfigTask.config?.acc_datasets || [])" :key="ds" size="small" type="warning" style="margin:2px">
                {{ ds.toUpperCase() }}
              </el-tag>
            </div>
            <span style="font-size:12px;color:#6b7280;margin-top:4px;display:block">
              每数据集评测样本上限: <b>{{ currentConfigTask.config?.acc_limit || 200 }}</b> 条
            </span>
          </el-descriptions-item>
        </el-descriptions>
      </div>
      <template #footer>
        <el-button type="primary" @click="configDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onActivated } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Edit } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/authStore'
import { apiListTasks, apiTaskAction, apiDeleteTask } from '../api'
import { formatTime } from '../utils/format'
import { useDragSelect } from '../utils/dragSelect'

const router = useRouter()
const authStore = useAuthStore()
const tableRef = ref(null)
const tasks = ref([])
const loading = ref(false)
const selectedTasks = ref([])
const singleSelected = computed(() => selectedTasks.value.length === 1 ? selectedTasks.value[0] : null)

useDragSelect(tableRef, tasks)

const handleSelectionChange = (val) => {
  selectedTasks.value = val
}

const handleRowClick = (row) => {
  if (tableRef.value) {
    tableRef.value.toggleRowSelection(row)
  }
}

const configDialogVisible = ref(false)
const currentConfigTask = ref(null)

const runningCount = computed(() => tasks.value.filter(t => t.status === 'running').length)
const completedCount = computed(() => tasks.value.filter(t => t.status === 'completed').length)
const pausedCount = computed(() => tasks.value.filter(t => t.status === 'paused').length)
const totalCount = computed(() => tasks.value.length)

const statusType = (s) => {
  const map = { running: 'primary', completed: 'success', failed: 'danger', paused: 'warning', cancelled: 'info' }
  return map[s] || 'info'
}
const statusLabel = (s) => {
  const map = { queued: '排队中', running: '运行中', completed: '已完成', failed: '失败', paused: '已暂停', cancelled: '已取消' }
  return map[s] || s
}



const showConfigDialog = (task) => {
  currentConfigTask.value = task
  configDialogVisible.value = true
}

const handleEditTask = () => {
  if (!singleSelected.value) return
  router.push(`/create?edit=${singleSelected.value.id}`)
}

const viewDetail = (task) => {
  const target = task || singleSelected.value
  if (target) {
    router.push(`/task/${target.id}`)
  }
}

const loadTasks = async () => {
  loading.value = true
  try {
    tasks.value = await apiListTasks()
  } catch (e) { console.error(e) }
  loading.value = false
}

const handleAction = async (action) => {
  if (!singleSelected.value) return
  try {
    await apiTaskAction(singleSelected.value.id, action)
    await loadTasks()
    ElMessage.success('操作成功')
  } catch (e) { ElMessage.error('操作失败') }
}

const handleBatchDelete = async () => {
  if (selectedTasks.value.length === 0) return
  loading.value = true
  try {
    for (const t of selectedTasks.value) {
      await apiDeleteTask(t.id)
    }
    selectedTasks.value = []
    await loadTasks()
    ElMessage.success('选中的任务已成功删除')
  } catch (e) {
    ElMessage.error('删除过程发生异常: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

onMounted(loadTasks)
onActivated(loadTasks)
</script>

<style scoped>
.task-list-page { padding: 0; }

.top-toolbar {
  background: #ffffff;
  padding: 12px 16px;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.toolbar-left { display: flex; gap: 10px; align-items: center; }

.task-summary-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}
.summary-card {
  background: #ffffff; border-radius: 8px; padding: 12px 16px;
  border: 1px solid #e5e7eb; display: flex; flex-direction: column;
}
.summary-card.blue { border-left: 4px solid #3b82f6; }
.summary-card.green { border-left: 4px solid #10b981; }
.summary-card.yellow { border-left: 4px solid #f59e0b; }
.summary-card.gray { border-left: 4px solid #6b7280; }

.card-num { font-size: 20px; font-weight: 700; color: #111827; }
.card-title { font-size: 12px; color: #6b7280; display: flex; align-items: center; gap: 6px; }

.dot-pulse {
  width: 6px; height: 6px; border-radius: 50%; background: #3b82f6;
  box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.7); animation: pulse-blue 2s infinite;
}
@keyframes pulse-blue {
  0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.7); }
  70% { transform: scale(1); box-shadow: 0 0 0 5px rgba(59, 130, 246, 0); }
  100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(59, 130, 246, 0); }
}

.custom-table { background: #ffffff; border-radius: 8px; cursor: pointer; }
</style>

<style>
.custom-table .selected-row td {
  background: #eff6ff !important;
}
</style>
