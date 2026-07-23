<template>
  <div class="model-mgmt-page">
    <div class="page-header">
      <h3>模块管理 ({{ models.length }} 个模型)</h3>
      <div>
        <el-button type="primary" @click="showAddDialog">
          <el-icon><Plus /></el-icon> 添加模型
        </el-button>
      </div>
    </div>

    <el-table :data="models" v-loading="loading" stripe row-key="slug">
      <el-table-column prop="idx" label="#" width="55" sortable />
      <el-table-column prop="name" label="模型名称" min-width="160" />
      <el-table-column prop="slug" label="Slug" width="140" />
      <el-table-column label="默认状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'PASS' ? 'success' : row.status === 'FAIL' ? 'danger' : 'info'" size="small">
            {{ row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="设备配置" min-width="180">
        <template #default="{ row }">
          <div class="device-config-tags">
            <template v-if="row.device_configs && row.device_configs.length">
              <el-tag v-for="dc in row.device_configs" :key="dc.id" size="small"
                :type="dc.status === 'PASS' ? 'success' : dc.status === 'FAIL' ? 'danger' : 'warning'"
                style="margin:1px 2px"
              >
                {{ dc.device_name }}:{{ dc.status }}
              </el-tag>
            </template>
            <span v-else style="color:#909399;font-size:12px">仅默认配置</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="success" :loading="testing === row.slug" @click="handleTest(row)">
            {{ testing === row.slug ? '测试中...' : '测试' }}
          </el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" @click="openDeviceConfigs(row)">设备配置</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 添加/编辑模型对话框 -->
    <el-dialog v-model="dialogVisible" :title="editing ? '编辑模型' : '添加模型'" width="650px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="模型名称">
          <el-input v-model="form.name" placeholder="例如: FunctionGemma" />
        </el-form-item>
        <el-form-item label="Slug">
          <el-input v-model="form.slug" placeholder="例如: functiongemma" :disabled="!!editing" />
        </el-form-item>
        <el-form-item label="默认Docker命令">
          <el-input v-model="form.docker_command" type="textarea" :rows="6"
            placeholder="sudo docker run -it --rm --runtime=nvidia --network host -e MODEL_NAME=xxx ..."
          />
        </el-form-item>
        <el-form-item label="TOS路径">
          <el-input v-model="form.tos_path" placeholder="tos://ai-hub/models/..." />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave">{{ editing ? '保存' : '添加' }}</el-button>
      </template>
    </el-dialog>

    <!-- 测试结果对话框 -->
    <el-dialog v-model="testResultVisible" title="测试结果" width="600px">
      <div v-if="testResult">
        <el-tag :type="testResult.status === 'PASS' ? 'success' : 'danger'" size="large">
          {{ testResult.status }}
        </el-tag>
        <div v-if="testResult.device_name" style="margin-top:8px;color:#909399">设备: {{ testResult.device_name }}</div>
        <div style="margin-top:16px">
          <div><b>运行命令:</b></div>
          <pre class="cmd-block">{{ testResult.docker_command }}</pre>
        </div>
        <div style="margin-top:12px" v-if="testResult.container_id">
          <b>容器 ID:</b> {{ testResult.container_id }}
        </div>
        <div style="margin-top:12px" v-if="testResult.reply">
          <div><b>模型回复:</b></div>
          <div class="reply-box">{{ testResult.reply }}</div>
        </div>
        <div style="margin-top:12px;color:#909399" v-if="testResult.detail">
          {{ testResult.detail }}
        </div>
      </div>
      <template #footer>
        <el-button @click="testResultVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 设备配置对话框 -->
    <el-dialog v-model="dcDialogVisible" :title="`设备配置 - ${currentModel?.name || ''}`" width="700px">
      <div style="margin-bottom:12px">
        <el-select v-model="newDcDeviceId" placeholder="选择设备" style="width:200px">
          <el-option v-for="d in devices" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
        <el-button type="primary" size="small" style="margin-left:8px" @click="addDc" :disabled="!newDcDeviceId">
          添加设备配置
        </el-button>
      </div>
      <el-table :data="currentDeviceConfigs" size="small" stripe>
        <el-table-column prop="device_name" label="设备" width="160" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.status === 'PASS' ? 'success' : row.status === 'FAIL' ? 'danger' : 'warning'" size="small">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="docker_command" label="Docker命令" min-width="250" show-overflow-tooltip />
        <el-table-column label="操作" width="220">
          <template #default="{ row }">
            <el-button size="small" type="success" :loading="dcTesting === row.id" @click="handleDcTest(row)">
              {{ dcTesting === row.id ? '测试中...' : '测试' }}
            </el-button>
            <el-button size="small" @click="editDc(row)">编辑</el-button>
            <el-popconfirm title="确定删除？" @confirm="deleteDc(row.id)">
              <template #reference>
                <el-button size="small" type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 编辑设备配置命令对话框 -->
    <el-dialog v-model="dcEditVisible" title="编辑设备 Docker 命令" width="600px" append-to-body>
      <el-form label-width="100px">
        <el-form-item label="设备">
          <span>{{ editingDc?.device_name }}</span>
        </el-form-item>
        <el-form-item label="Docker命令">
          <el-input v-model="editingDcCommand" type="textarea" :rows="8" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dcEditVisible = false">取消</el-button>
        <el-button type="primary" @click="saveDcCommand">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { apiListModels, apiCreateModel, apiUpdateModel, apiDeleteModel } from '../api'
import axios from 'axios'

const models = ref([])
const devices = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref(null)
const testing = ref(null)
const dcTesting = ref(null)  // 正在测试的设备配置 ID
const testResult = ref(null)
const testResultVisible = ref(false)
const form = ref({ name: '', slug: '', docker_command: '', tos_path: '' })

// 设备配置相关
const dcDialogVisible = ref(false)
const dcEditVisible = ref(false)
const currentModel = ref(null)
const newDcDeviceId = ref(null)
const editingDc = ref(null)
const editingDcCommand = ref('')

const loadModels = async () => {
  loading.value = true
  try { models.value = await apiListModels() } catch (e) { console.error(e) }
  loading.value = false
}

const loadDevices = async () => {
  try { devices.value = (await axios.get('/api/devices')).data } catch (e) { /* 静默 */ }
}

const showAddDialog = () => {
  editing.value = null
  form.value = { name: '', slug: '', docker_command: '', tos_path: '' }
  dialogVisible.value = true
}

const openEdit = (row) => {
  editing.value = row.slug
  form.value = {
    name: row.name, slug: row.slug,
    docker_command: row.docker_command || '',
    tos_path: row.tos_path || '',
  }
  dialogVisible.value = true
}

const handleSave = async () => {
  try {
    if (editing.value) {
      await apiUpdateModel(editing.value, form.value)
    } else {
      await apiCreateModel(form.value)
    }
    dialogVisible.value = false
    await loadModels()
  } catch (e) { console.error(e) }
}

const handleTest = async (row) => {
  testing.value = row.slug
  testResult.value = null
  try {
    const resp = await axios.post(`/api/models/${row.slug}/test`)
    testResult.value = resp.data
    testResultVisible.value = true
    await loadModels()
  } catch (e) {
    testResult.value = { status: 'FAIL', detail: e.response?.data?.detail || String(e) }
    testResultVisible.value = true
  }
  testing.value = null
}

// 设备配置维度的测试（传入 device_id）
const handleDcTest = async (dc) => {
  if (!currentModel.value) return
  dcTesting.value = dc.id
  testResult.value = null
  try {
    const resp = await axios.post(`/api/models/${currentModel.value.slug}/test`, null, {
      params: { device_id: dc.device_id }
    })
    testResult.value = resp.data
    testResultVisible.value = true
    await refreshCurrentModel()
  } catch (e) {
    testResult.value = { status: 'FAIL', detail: e.response?.data?.detail || String(e) }
    testResultVisible.value = true
  }
  dcTesting.value = null
}

// ========== 设备配置管理 ==========

const currentDeviceConfigs = computed(() => {
  if (!currentModel.value) return []
  return currentModel.value.device_configs || []
})

const openDeviceConfigs = (row) => {
  currentModel.value = row
  newDcDeviceId.value = null
  dcDialogVisible.value = true
}

const addDc = async () => {
  if (!newDcDeviceId.value || !currentModel.value) return
  try {
    await axios.post(`/api/models/${currentModel.value.slug}/device-configs`, {
      device_id: newDcDeviceId.value,
      docker_command: currentModel.value.docker_command || '',
    })
    await refreshCurrentModel()
    newDcDeviceId.value = null
  } catch (e) { console.error(e) }
}

const editDc = (dc) => {
  editingDc.value = dc
  editingDcCommand.value = dc.docker_command || ''
  dcEditVisible.value = true
}

const saveDcCommand = async () => {
  if (!editingDc.value || !currentModel.value) return
  try {
    await axios.put(`/api/models/${currentModel.value.slug}/device-configs/${editingDc.value.id}`, {
      docker_command: editingDcCommand.value,
    })
    dcEditVisible.value = false
    await refreshCurrentModel()
  } catch (e) { console.error(e) }
}

const deleteDc = async (configId) => {
  if (!currentModel.value) return
  try {
    await axios.delete(`/api/models/${currentModel.value.slug}/device-configs/${configId}`)
    await refreshCurrentModel()
  } catch (e) { console.error(e) }
}

const refreshCurrentModel = async () => {
  if (!currentModel.value) return
  try {
    const resp = await apiListModels()
    const updated = resp.find(m => m.slug === currentModel.value.slug)
    if (updated) {
      currentModel.value = updated
      // 同步更新主列表
      const idx = models.value.findIndex(m => m.slug === currentModel.value.slug)
      if (idx >= 0) models.value[idx] = updated
    }
  } catch (e) { console.error(e) }
}

onMounted(() => { loadModels(); loadDevices() })
</script>

<style scoped>
.model-mgmt-page { padding: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h3 { font-size: 16px; }
.device-config-tags { display: flex; flex-wrap: wrap; gap: 2px; }
.cmd-block { background:#1e1e1e;color:#d4d4d4;padding:10px;border-radius:4px;font-size:12px;overflow-x:auto;white-space:pre-wrap;word-break:break-all; }
.reply-box { background:#f0f9eb;padding:12px;border-radius:4px;margin-top:4px;white-space:pre-wrap; }
</style>
