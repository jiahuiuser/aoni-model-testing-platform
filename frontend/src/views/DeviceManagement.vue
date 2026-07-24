<template>
  <div class="device-page">
    <!-- 顶部统一 CRUD 操作工具栏 -->
    <div class="top-toolbar">
      <div class="toolbar-left">
        <el-button type="primary" @click="showAddDialog">
          <el-icon><Plus /></el-icon> 添加设备
        </el-button>
        <el-button type="success" plain :disabled="!selectedDevice" :loading="checking === selectedDevice?.id" @click="handleCheckSelected">
          <el-icon><Refresh /></el-icon> 节点健康检查
        </el-button>
        <el-button type="warning" plain :disabled="!selectedDevice" @click="openEditSelected">
          <el-icon><Edit /></el-icon> 编辑设备
        </el-button>
        <el-button @click="showCredDialog = true">
          <el-icon><Key /></el-icon> 凭证管理
        </el-button>
        <el-popconfirm v-if="selectedDevice" title="确定删除选中设备？" @confirm="handleDeleteSelected">
          <template #reference>
            <el-button type="danger" plain>
              <el-icon><Delete /></el-icon> 删除设备
            </el-button>
          </template>
        </el-popconfirm>
      </div>

      <div class="toolbar-right">
        <el-radio-group v-model="viewMode" size="small">
          <el-radio-button label="cards"><el-icon><Menu /></el-icon> 算力卡片</el-radio-button>
          <el-radio-button label="table"><el-icon><List /></el-icon> 表格视图</el-radio-button>
        </el-radio-group>
        <el-button circle @click="loadDevices"><el-icon><Refresh /></el-icon></el-button>
      </div>
    </div>

    <!-- 1. 算力卡片墙视图 (点击可高亮选中) -->
    <div v-if="viewMode === 'cards'" v-loading="loading" class="card-wall-grid">
      <div
        v-for="dev in devices"
        :key="dev.id"
        class="hardware-card"
        :class="[dev.status, { selected: selectedDevice?.id === dev.id }]"
        @click="selectedDevice = dev"
        @dblclick="handleCheckSelected"
      >
        <div class="card-header-bar">
          <div class="chip-avatar">
            <svg viewBox="0 0 32 32" fill="none" class="chip-icon">
              <rect x="4" y="4" width="24" height="24" rx="4" fill="#1F2937" stroke="#10B981" stroke-width="2"/>
              <path d="M10 10H22V22H10V10Z" fill="#10B981" fill-opacity="0.2" stroke="#10B981" stroke-width="1.5"/>
              <circle cx="16" cy="16" r="3" fill="#10B981"/>
              <path d="M4 11H1M4 21H1M31 11H28M31 21H28M11 4V1M21 4V1M11 31V28M21 31V28" stroke="#6B7280" stroke-width="2"/>
            </svg>
          </div>
          <div class="dev-main-info">
            <div class="dev-name-row">
              <span class="dev-name">{{ dev.name }}</span>
              <span class="status-badge" :class="dev.status">
                <span class="badge-dot"></span> {{ dev.status === 'online' ? '在线' : '离线' }}
              </span>
            </div>
            <div class="dev-host-row">
              <code>{{ dev.host }}</code>
              <el-tag size="small" type="info" style="margin-left:6px">{{ dev.device_type.toUpperCase() }}</el-tag>
            </div>
          </div>
        </div>

        <div class="card-body-metrics">
          <template v-if="dev.last_check_detail">
            <div class="metric-row">
              <div class="metric-label">
                <span>内存 (RAM)</span>
                <span class="metric-val">{{ dev.last_check_detail.memory?.used || '-' }} / {{ dev.last_check_detail.memory?.total || '-' }}</span>
              </div>
              <el-progress :percentage="parseMemPercent(dev.last_check_detail.memory)" :color="memProgressColor" :stroke-width="6" />
            </div>

            <div class="metric-row">
              <div class="metric-label">
                <span>磁盘 (Disk)</span>
                <span class="metric-val">{{ dev.last_check_detail.disk?.use_pct || '-' }}</span>
              </div>
              <el-progress :percentage="parseDiskPercent(dev.last_check_detail.disk?.use_pct)" :stroke-width="6" color="#8B5CF6" />
            </div>

            <div class="tags-row">
              <el-tag v-if="dev.last_check_detail.cpu_cores" size="small" type="info" effect="dark">
                CPU: {{ dev.last_check_detail.cpu_cores }}核
              </el-tag>
              <el-tag v-if="dev.last_check_detail.gpu_info" size="small" type="warning" effect="dark">
                GPU: {{ dev.last_check_detail.gpu_info }}
              </el-tag>
              <el-tag v-if="dev.last_check_detail.docker_ok" size="small" type="success" effect="dark">
                Docker 正常
              </el-tag>
            </div>
          </template>
          <div v-else class="empty-metric-tip">
            未进行诊断，选择节点并点击“节点健康检查”
          </div>
        </div>
      </div>
    </div>

    <!-- 2. 表格视图 -->
    <el-table
      ref="tableRef"
      v-else
      :data="devices"
      v-loading="loading"
      stripe
      border
      @selection-change="handleSelectionChange"
      @row-click="handleRowClick"
      @row-dblclick="handleCheckSelected"
      class="custom-table"
    >
      <el-table-column type="selection" width="50" align="center" />
      <el-table-column prop="id" label="ID" width="55" align="center" />
      <el-table-column prop="name" label="设备名称" min-width="160" />
      <el-table-column prop="host" label="地址 (Host)" width="150" />
      <el-table-column prop="device_type" label="类型" width="90" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'online' ? 'success' : 'danger'" size="small">
            {{ row.status === 'online' ? '在线' : '离线' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="硬件算力与资源概览" min-width="260">
        <template #default="{ row }">
          <div v-if="row.last_check_detail" class="resource-badges">
            <el-tag v-if="row.last_check_detail.cpu_cores" size="small" type="info" effect="plain">
              CPU: {{ row.last_check_detail.cpu_cores }}核
            </el-tag>
            <el-tag v-if="row.last_check_detail.memory?.total" size="small" type="info" effect="plain">
              内存: {{ row.last_check_detail.memory.used }}/{{ row.last_check_detail.memory.total }}
            </el-tag>
            <el-tag v-if="row.last_check_detail.disk?.use_pct" size="small" type="info" effect="plain">
              磁盘: {{ row.last_check_detail.disk.use_pct }}
            </el-tag>
            <el-tag v-if="row.last_check_detail.gpu_info" size="small" type="warning" effect="plain">
              GPU
            </el-tag>
          </div>
          <span v-else style="color:#909399">双击行发起诊断检查</span>
        </template>
      </el-table-column>
    </el-table>

    <!-- 检测详情对话框 -->
    <el-dialog v-model="detailVisible" title="节点诊断详情" width="650px">
      <div v-if="currentDetail" class="check-detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="SSH 连接">
            <el-tag :type="currentDetail.ssh_ok ? 'success' : 'danger'" size="small">
              {{ currentDetail.ssh_ok ? '连通正常' : '连接失败' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Docker 引擎">
            <el-tag :type="currentDetail.docker_ok ? 'success' : 'danger'" size="small">
              {{ currentDetail.docker_ok ? '服务可用' : '服务异常' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="GPU 架构">
            {{ currentDetail.gpu_info || '未检测到' }} ({{ currentDetail.gpu_count || 0 }}块)
          </el-descriptions-item>
          <el-descriptions-item label="vLLM 版本">
            {{ currentDetail.vllm || '未安装' }}
          </el-descriptions-item>
          <el-descriptions-item label="CPU 核心">
            {{ currentDetail.cpu_cores || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="内存" :span="2">
            <span v-if="currentDetail.memory?.total">
              {{ currentDetail.memory.used }} / {{ currentDetail.memory.total }} (可用: {{ currentDetail.memory.available }})
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="磁盘" :span="2">
            <span v-if="currentDetail.disk?.total">
              {{ currentDetail.disk.used }} / {{ currentDetail.disk.total }} (已用: {{ currentDetail.disk.use_pct }})
            </span>
          </el-descriptions-item>
        </el-descriptions>
      </div>
    </el-dialog>

    <!-- 添加/编辑设备对话框 -->
    <el-dialog v-model="dialogVisible" :title="editing ? '编辑设备' : '添加设备'" width="550px">
      <el-form :model="form" label-width="110px">
        <el-form-item label="设备名称">
          <el-input v-model="form.name" placeholder="例如: Jetson Thor #1" />
        </el-form-item>
        <el-form-item label="IP/主机名">
          <el-input v-model="form.host" placeholder="192.168.1.16" />
        </el-form-item>
        <el-form-item label="设备类型">
          <el-select v-model="form.device_type">
            <el-option label="Jetson" value="jetson" />
            <el-option label="Server" value="server" />
            <el-option label="Cloud" value="cloud" />
          </el-select>
        </el-form-item>
        <el-form-item label="vLLM 端口">
          <el-input v-model.number="form.port" placeholder="8800" />
        </el-form-item>
        <el-form-item label="SSH 凭证">
          <el-select v-model="form.credential_id" placeholder="选择凭证（留空=本机）" clearable style="width:100%">
            <el-option v-for="c in credentials" :key="c.id" :label="`${c.name} (${c.type === 'ssh_key' ? '密钥' : '密码'})`" :value="c.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave">{{ editing ? '保存' : '添加' }}</el-button>
      </template>
    </el-dialog>

    <!-- 凭证管理对话框 -->
    <el-dialog v-model="showCredDialog" title="凭证管理" width="700px">
      <div style="margin-bottom:12px">
        <el-button size="small" type="primary" @click="showCredForm(null)">添加凭证</el-button>
      </div>
      <el-table :data="credentials" size="small" stripe border>
        <el-table-column prop="id" label="ID" width="50" />
        <el-table-column prop="name" label="名称" width="160" />
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            <el-tag :type="row.type === 'ssh_key' ? '' : 'warning'" size="small">
              {{ row.type === 'ssh_key' ? '密钥' : '密码' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ssh_username" label="用户名" width="100" />
        <el-table-column prop="ssh_port" label="端口" width="60" />
        <el-table-column prop="ssh_key_path" label="密钥路径" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button size="small" @click="showCredForm(row)">编辑</el-button>
            <el-popconfirm title="确定删除？" @confirm="deleteCred(row.id)">
              <template #reference>
                <el-button size="small" type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 凭证编辑对话框 -->
    <el-dialog v-model="credFormVisible" :title="credEditing ? '编辑凭证' : '添加凭证'" width="500px" append-to-body>
      <el-form :model="credForm" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="credForm.name" placeholder="例如: nv5000-key" />
        </el-form-item>
        <el-form-item label="认证方式">
          <el-radio-group v-model="credForm.type">
            <el-radio value="ssh_key">SSH 密钥</el-radio>
            <el-radio value="password">密码</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="SSH 用户名">
          <el-input v-model="credForm.ssh_username" placeholder="root 或 nv5000" />
        </el-form-item>
        <el-form-item label="SSH 端口">
          <el-input v-model.number="credForm.ssh_port" placeholder="22" />
        </el-form-item>
        <el-form-item v-if="credForm.type === 'ssh_key'" label="密钥路径">
          <el-input v-model="credForm.ssh_key_path" placeholder="/home/user/.ssh/id_rsa" />
        </el-form-item>
        <el-form-item v-if="credForm.type === 'password'" label="SSH 密码">
          <el-input v-model="credForm.password" type="password" show-password placeholder="设备登录密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="credFormVisible = false">取消</el-button>
        <el-button type="primary" @click="saveCred">{{ credEditing ? '保存' : '添加' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import { useDragSelect } from '../utils/dragSelect'

const tableRef = ref(null)
const viewMode = ref('cards')
const devices = ref([])
const credentials = ref([])
const loading = ref(false)
const selectedDevices = ref([])
const selectedDevice = ref(null)

useDragSelect(tableRef, devices)

const handleSelectionChange = (val) => {
  selectedDevices.value = val
  if (val.length === 1) {
    selectedDevice.value = val[0]
  } else if (val.length === 0) {
    selectedDevice.value = null
  }
}

const handleRowClick = (row) => {
  if (tableRef.value) {
    tableRef.value.toggleRowSelection(row)
  } else {
    selectedDevice.value = row
  }
}

const dialogVisible = ref(false)
const detailVisible = ref(false)
const showCredDialog = ref(false)
const credFormVisible = ref(false)
const editing = ref(null)
const credEditing = ref(null)
const checking = ref(null)
const currentDetail = ref(null)

const form = ref({ name: '', host: '', device_type: 'jetson', port: 8800, credential_id: null, description: '' })
const credForm = ref({ name: '', type: 'ssh_key', ssh_username: '', ssh_port: 22, ssh_key_path: '', password: '', description: '' })

const memProgressColor = [
  { color: '#10B981', percentage: 60 },
  { color: '#F59E0B', percentage: 80 },
  { color: '#EF4444', percentage: 100 },
]

const parseMemPercent = (mem) => {
  if (!mem || !mem.total || !mem.used) return 0
  const parseVal = (s) => parseFloat(s) * (s.includes('Gi') || s.includes('GB') ? 1024 : 1)
  const u = parseVal(String(mem.used))
  const t = parseVal(String(mem.total))
  return t ? Math.min(100, Math.round((u / t) * 100)) : 0
}

const parseDiskPercent = (pctStr) => {
  if (!pctStr) return 0
  const n = parseInt(pctStr.replace('%', ''))
  return isNaN(n) ? 0 : n
}

const handleRowSelect = (val) => {
  selectedDevice.value = val
}

const loadDevices = async () => {
  loading.value = true
  try {
    devices.value = (await axios.get('/api/devices')).data
    if (selectedDevice.value) {
      selectedDevice.value = devices.value.find(d => d.id === selectedDevice.value.id) || null
    }
  } catch (e) { console.error(e) }
  loading.value = false
}

const loadCredentials = async () => {
  try { credentials.value = (await axios.get('/api/credentials')).data } catch (e) { console.error(e) }
}

const showAddDialog = () => {
  editing.value = null
  form.value = { name: '', host: '', device_type: 'jetson', port: 8800, credential_id: null, description: '' }
  dialogVisible.value = true
}

const openEditSelected = () => {
  if (!selectedDevice.value) return
  editing.value = selectedDevice.value.id
  form.value = { ...selectedDevice.value }
  dialogVisible.value = true
}

const handleSave = async () => {
  try {
    if (editing.value) {
      await axios.put(`/api/devices/${editing.value}`, form.value)
    } else {
      await axios.post('/api/devices', form.value)
    }
    dialogVisible.value = false
    await loadDevices()
    ElMessage.success('设备配置已成功保存')
  } catch (e) { ElMessage.error('保存设备信息失败') }
}

const handleDeleteSelected = async () => {
  if (!selectedDevice.value) return
  try {
    await axios.delete(`/api/devices/${selectedDevice.value.id}`)
    selectedDevice.value = null
    await loadDevices()
    ElMessage.success('设备节点已成功删除')
  } catch (e) { ElMessage.error('删除设备失败') }
}

const handleCheckSelected = async () => {
  if (!selectedDevice.value) return
  checking.value = selectedDevice.value.id
  try {
    await axios.post(`/api/devices/${selectedDevice.value.id}/check`)
    await loadDevices()
    if (selectedDevice.value && selectedDevice.value.last_check_detail) {
      currentDetail.value = selectedDevice.value.last_check_detail
      detailVisible.value = true
    }
    ElMessage.success(`设备 [${selectedDevice.value.name}] 诊断完成`)
  } catch (e) { ElMessage.error('设备诊断失败') }
  checking.value = null
}

// 凭证
const showCredForm = (row) => {
  if (row) {
    credEditing.value = row.id
    credForm.value = { ...row }
  } else {
    credEditing.value = null
    credForm.value = { name: '', type: 'ssh_key', ssh_username: '', ssh_port: 22, ssh_key_path: '', password: '', description: '' }
  }
  credFormVisible.value = true
}

const saveCred = async () => {
  try {
    if (credEditing.value) {
      await axios.put(`/api/credentials/${credEditing.value}`, credForm.value)
    } else {
      await axios.post('/api/credentials', credForm.value)
    }
    credFormVisible.value = false
    await loadCredentials()
    ElMessage.success('凭证信息已成功保存')
  } catch (e) { ElMessage.error('保存凭证失败') }
}

const deleteCred = async (id) => {
  try { await axios.delete(`/api/credentials/${id}`); await loadCredentials(); ElMessage.success('凭证已成功删除') } catch (e) { ElMessage.error('删除凭证失败') }
}

onMounted(() => { loadDevices(); loadCredentials() })
</script>

<style scoped>
.device-page { padding: 0; }

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
.toolbar-left, .toolbar-right { display: flex; gap: 10px; align-items: center; }

.card-wall-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.hardware-card {
  background: #ffffff; border-radius: 10px; border: 2px solid #e5e7eb;
  padding: 14px; cursor: pointer; transition: all 0.2s ease;
}
.hardware-card.selected {
  border-color: #2563eb; background: #f0f6ff; box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
}

.card-header-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.chip-avatar { width: 40px; height: 40px; border-radius: 8px; background: #1f2937; display: flex; align-items: center; justify-content: center; }
.chip-icon { width: 28px; height: 28px; }
.dev-main-info { flex: 1; }
.dev-name-row { display: flex; justify-content: space-between; align-items: center; }
.dev-name { font-size: 14px; font-weight: 700; color: #111827; }
.dev-host-row { font-size: 12px; color: #6b7280; margin-top: 2px; }

.status-badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 12px; display: inline-flex; align-items: center; gap: 4px; }
.status-badge.online { background: #d1fae5; color: #065f46; }
.status-badge.offline { background: #fee2e2; color: #991b1b; }
.badge-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

.card-body-metrics { background: #ffffff; border-radius: 6px; padding: 10px; border: 1px solid #f3f4f6; }
.metric-row { margin-bottom: 8px; }
.metric-label { display: flex; justify-content: space-between; font-size: 11px; color: #4b5563; margin-bottom: 2px; }
.tags-row { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.empty-metric-tip { font-size: 11px; color: #9ca3af; text-align: center; padding: 8px 0; }

.custom-table { background: #ffffff; border-radius: 8px; cursor: pointer; }
</style>
