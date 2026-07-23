<template>
  <div class="task-list-page">
    <div class="page-header">
      <h3>任务列表</h3>
      <el-button type="primary" @click="$router.push('/create')">
        <el-icon><Plus /></el-icon> 创建任务
      </el-button>
    </div>

    <el-table :data="tasks" v-loading="loading" stripe>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="name" label="任务名称" min-width="200" />
      <el-table-column prop="profile" label="Profile" width="100" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="进度" width="150">
        <template #default="{ row }">
          <el-progress
            :percentage="row.model_count ? Math.round(row.completed_count / row.model_count * 100) : 0"
            :status="row.status === 'completed' ? 'success' : ''"
          />
        </template>
      </el-table-column>
      <el-table-column label="模型" width="120">
        <template #default="{ row }">{{ row.completed_count }}/{{ row.model_count }}</template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="$router.push(`/task/${row.id}`)">详情</el-button>
          <el-button
            v-if="row.status === 'running'"
            size="small" type="warning"
            @click="handleAction(row.id, 'pause')"
          >暂停</el-button>
          <el-button
            v-if="row.status === 'paused'"
            size="small" type="success"
            @click="handleAction(row.id, 'resume')"
          >继续</el-button>
          <el-popconfirm title="确定删除？" @confirm="handleDelete(row.id)">
            <template #reference>
              <el-button size="small" type="danger">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { apiListTasks, apiTaskAction, apiDeleteTask } from '../api'

const tasks = ref([])
const loading = ref(false)

const statusType = (s) => {
  const map = { running: 'primary', completed: 'success', failed: 'danger', paused: 'warning', cancelled: 'info' }
  return map[s] || 'info'
}
const statusLabel = (s) => {
  const map = { queued: '排队中', running: '运行中', completed: '已完成', failed: '失败', paused: '已暂停', cancelled: '已取消' }
  return map[s] || s
}
const formatTime = (t) => t ? new Date(t).toLocaleString() : '-'

const loadTasks = async () => {
  loading.value = true
  try { tasks.value = await apiListTasks() } catch (e) { console.error(e) }
  loading.value = false
}

const handleAction = async (id, action) => {
  try { await apiTaskAction(id, action); await loadTasks() } catch (e) { console.error(e) }
}

const handleDelete = async (id) => {
  try { await apiDeleteTask(id); await loadTasks() } catch (e) { console.error(e) }
}

onMounted(loadTasks)
</script>

<style scoped>
.task-list-page { padding: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h3 { font-size: 16px; }
</style>
