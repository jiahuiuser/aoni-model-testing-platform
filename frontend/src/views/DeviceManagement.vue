<template>
  <div class="device-page">
    <div class="page-header">
      <h3>设备管理 ({{ devices.length }} 台)</h3>
      <div>
        <el-button @click="showCredDialog = true">
          <el-icon><Key /></el-icon> 凭证管理
        </el-button>
        <el-button type="primary" @click="showAddDialog">
          <el-icon><Plus /></el-icon> 添加设备
        </el-button>
      </div>
    </div>

    <el-table :data="devices" v-loading="loading" stripe>
      <el-table-column prop="id" label="ID" width="50" />
      <el-table-column prop="name" label="设备名称" min-width="140" />
      <el-table-column prop="host" label="地址" width="150" />
      <el-table-column prop="device_type" label="类型" width="80" />
      <el-table-column label="凭证" width="120">
        <template #default="{ row }">
          <el-tag v-if="row.credential_name" size="small" :type="row.credential_type === 'ssh_key' ? '' : 'warning'">
            {{ row.credential_name }}
          </el-tag>
          <el-tag v-else size="small" type="info">本机</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'online' ? 'success' : 'danger'" size="small">
            {{ row.status === 'online' ? '在线' : '离线' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="资源" min-width="220">
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
            <el-tag v-if="row.last_check_detail.docker_ok !== undefined" size="small"
                    :type="row.last_check_detail.docker_ok ? 'success' : 'danger'" effect="plain">
              Docker
            </el-tag>
            <el-tag v-if="row.last_check_detail.gpu_info" size="small" type="warning" effect="plain">
              GPU
            </el-tag>
            <el-tag v-if="row.last_check_detail.vllm" size="small" effect="plain">
              vLLM {{ row.last_check_detail.vllm }}
            </el-tag>
          </div>
          <span v-else style="color:#909399">点击"检测"获取</span>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="描述" min-width="120" show-overflow-tooltip />
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="success" :loading="checking === row.id" @click="handleCheck(row)">
            {{ checking === row.id ? '检测中...' : '检测' }}
          </el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-popconfirm title="确定删除？" @confirm="handleDelete(row.id)">
            <template #reference>
              <el-button size="small" type="danger">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <!-- 检测详情对话框 -->
    <el-dialog v-model="detailVisible" title="设备检测详情" width="650px">
      <div v-if="currentDetail" class="check-detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="SSH 连接">
            <el-tag :type="currentDetail.ssh_ok ? 'success' : 'danger'" size="small">
              {{ currentDetail.ssh_ok ? '成功' : '失败' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Docker">
            <el-tag :type="currentDetail.docker_ok ? 'success' : 'danger'" size="small">
              {{ currentDetail.docker_ok ? '可用' : '不可用' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="GPU">
            {{ currentDetail.gpu_info || '未检测到' }} ({{ currentDetail.gpu_count || 0 }}块)
          </el-descriptions-item>
          <el-descriptions-item label="vLLM">
            {{ currentDetail.vllm || '未安装' }}
          </el-descriptions-item>
          <el-descriptions-item label="CPU 核心">
            {{ currentDetail.cpu_cores || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="平台 API">
            {{ currentDetail.platform_api || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="内存" :span="2">
            <span v-if="currentDetail.memory?.total">
              {{ currentDetail.memory.used }} / {{ currentDetail.memory.total }} (可用: {{ currentDetail.memory.available }})
            </span>
            <span v-else>-</span>
          </el-descriptions-item>
          <el-descriptions-item label="磁盘" :span="2">
            <span v-if="currentDetail.disk?.total">
              {{ currentDetail.disk.used }} / {{ currentDetail.disk.total }} (已用: {{ currentDetail.disk.use_pct }})
            </span>
            <span v-else>-</span>
          </el-descriptions-item>
          <el-descriptions-item v-if="currentDetail.docker_containers?.length" label="运行容器" :span="2">
            <el-tag v-for="c in currentDetail.docker_containers" :key="c" size="small" style="margin-right:4px">{{ c }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item v-if="currentDetail.errors?.length" label="异常" :span="2">
            <div v-for="(e, i) in currentDetail.errors" :key="i" style="color:#F56C6C">{{ e }}</div>
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
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
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
      <el-table :data="credentials" size="small" stripe>
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
        <el-form-item label="描述">
          <el-input v-model="credForm.description" type="textarea" :rows="2" />
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
import axios from 'axios'

const devices = ref([])
const credentials = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const detailVisible = ref(false)
const showCredDialog = ref(false)
const credFormVisible = ref(false)
const editing = ref(null)
const credEditing = ref(null)
const checking = ref(null)
const currentDetail = ref(null)

const form = ref({
  name: '', host: '', device_type: 'jetson', port: 8800,
  credential_id: null, description: ''
})

const credForm = ref({
  name: '', type: 'ssh_key', ssh_username: '', ssh_port: 22,
  ssh_key_path: '', password: '', description: ''
})

const loadDevices = async () => {
  loading.value = true
  try { devices.value = (await axios.get('/api/devices')).data } catch (e) { console.error(e) }
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

const openEdit = (row) => {
  editing.value = row.id
  form.value = { ...row }
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
  } catch (e) { console.error(e) }
}

const handleDelete = async (id) => {
  try { await axios.delete(`/api/devices/${id}`); await loadDevices() } catch (e) { console.error(e) }
}

const handleCheck = async (row) => {
  checking.value = row.id
  try {
    await axios.post(`/api/devices/${row.id}/check`)
    await loadDevices()
    const updated = devices.value.find(d => d.id === row.id)
    if (updated && updated.last_check_detail) {
      currentDetail.value = updated.last_check_detail
      detailVisible.value = true
    }
  } catch (e) { console.error(e) }
  checking.value = null
}

// 凭证管理
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
  } catch (e) { console.error(e) }
}

const deleteCred = async (id) => {
  try { await axios.delete(`/api/credentials/${id}`); await loadCredentials() } catch (e) { console.error(e) }
}

onMounted(() => { loadDevices(); loadCredentials() })
</script>

<style scoped>
.device-page { padding: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h3 { font-size: 16px; }
.page-header > div { display: flex; gap: 8px; }
.resource-badges { display: flex; flex-wrap: wrap; gap: 4px; }
.check-detail { max-height: 60vh; overflow-y: auto; }
</style>
