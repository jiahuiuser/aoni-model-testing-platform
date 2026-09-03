<template>
  <div class="image-mgmt-page">
    <div class="page-header">
      <div>
        <h2>镜像管理</h2>
        <p class="subtitle">分类目录 · 沐曦推理镜像 · vLLM 官网镜像 · 一键 docker pull 下发到设备</p>
      </div>
    </div>

    <!-- 主视图切换: 平台镜像 / 沐曦资源 -->
    <el-tabs v-model="mainView" class="main-tabs">
      <el-tab-pane label="平台镜像" name="platform">

    <!-- 一级分类（文件夹）导航 -->
    <div class="category-bar">
      <el-button
        :type="activeCategory === null ? 'primary' : 'default'"
        round
        @click="activeCategory = null"
      >全部镜像</el-button>
      <el-button
        v-for="c in categories"
        :key="c.id"
        :type="activeCategory === c.id ? 'primary' : 'default'"
        round
        @click="activeCategory = c.id"
      >
        {{ c.name }}
        <el-badge :value="c.image_count" type="info" class="cat-badge" v-if="c.image_count" />
      </el-button>
      <el-button round type="success" plain @click="openCreateCategory">
        <el-icon><FolderAdd /></el-icon> 新建目录
      </el-button>
    </div>

    <!-- 顶部工具栏 -->
    <div class="top-toolbar">
      <div class="toolbar-left">
        <el-button type="primary" @click="openCreateImage">
          <el-icon><Plus /></el-icon> 注册镜像
        </el-button>
        <el-button type="warning" plain :disabled="selectedImages.length !== 1" @click="openEditImage(selectedImages[0])">
          <el-icon><Edit /></el-icon> 编辑镜像
        </el-button>
        <el-button type="success" plain :disabled="selectedImages.length !== 1" @click="openDeploy(selectedImages[0])">
          <el-icon><Promotion /></el-icon> docker pull 下发
        </el-button>
        <el-button v-if="selectedImages.length > 0" type="danger" plain @click="confirmDeleteSelectedImages">
          <el-icon><Delete /></el-icon> 批量删除 ({{ selectedImages.length }})
        </el-button>
      </div>
      <div class="toolbar-right">
        <el-input v-model="searchKw" placeholder="搜索名称/Tag/描述" clearable style="width: 220px; margin-right: 10px" @keyup.enter="loadImages" />
        <el-button circle @click="loadImages"><el-icon><Refresh /></el-icon></el-button>
      </div>
    </div>

    <!-- 镜像表格 -->
    <el-table
      ref="tableRef"
      :data="images"
      stripe border style="width: 100%"
      class="custom-table"
      @selection-change="handleSelectionChange"
      @row-click="handleRowClick"
    >
      <el-table-column type="selection" width="45" align="center" />
      <el-table-column prop="id" label="ID" width="55" align="center" />
      <el-table-column prop="name" label="镜像名称" min-width="160">
        <template #default="{ row }">
          <b style="color:#2563eb;">{{ row.name }}</b>
        </template>
      </el-table-column>
      <el-table-column prop="image_tag" label="Docker Image Tag" min-width="200">
        <template #default="{ row }">
          <code style="background:#f1f5f9;padding:2px 6px;border-radius:4px;color:#0f172a;word-break:break-all;">{{ row.image_tag }}</code>
        </template>
      </el-table-column>
      <el-table-column label="来源" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="row.source === 'official' ? 'warning' : row.source === 'registry' ? 'primary' : 'info'">
            {{ sourceLabel(row.source) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="芯片" width="110" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.chip_type" type="success" size="small">{{ chipLabel(row.chip_type) }}</el-tag>
          <span v-else style="color:#94a3b8;">-</span>
        </template>
      </el-table-column>
      <el-table-column label="架构" width="80" align="center">
        <template #default="{ row }">
          <span>{{ row.arch || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip />
      <el-table-column label="操作" width="170" align="center" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="success" @click.stop="openDeploy(row)">docker pull</el-button>
          <el-button size="small" type="info" plain @click.stop="openLogs(row)">日志</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 添加/编辑镜像 Dialog -->
    <el-dialog v-model="showAddDialog" :title="editingImgId ? '编辑 Docker 镜像信息' : '注册 Docker 镜像'" width="580px">
      <el-form :model="imgForm" label-width="130px">
        <el-form-item label="镜像名称">
          <el-input v-model="imgForm.name" placeholder="例: vLLM Jetson Thor 专用镜像" />
        </el-form-item>
        <el-form-item label="Docker Image Tag">
          <el-input v-model="imgForm.image_tag" placeholder="例: aoni/vllm/vllm-openai:v0.20.0-ubuntu2404" />
        </el-form-item>
        <el-form-item label="所属分类">
          <el-select v-model="imgForm.category_id" clearable placeholder="选择分类（可空）" style="width:100%">
            <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源">
          <el-select v-model="imgForm.source" style="width:100%">
            <el-option label="自定义" value="custom" />
            <el-option label="内网 Registry" value="registry" />
            <el-option label="官方目录(沐曦等)" value="official" />
            <el-option label="离线文件(tar)" value="tar" />
          </el-select>
        </el-form-item>
        <el-form-item label="适配芯片">
          <el-select v-model="imgForm.chip_type" clearable placeholder="部署时按芯片匹配设备" style="width:100%">
            <el-option label="不限" :value="null" />
            <el-option label="沐曦 曦云C500" value="metax_c500" />
            <el-option label="NVIDIA Jetson Thor" value="nvidia_thor" />
            <el-option label="NVIDIA RTX 5090" value="nvidia_rtx5090" />
            <el-option label="摩尔线程" value="mthreads_musa" />
          </el-select>
        </el-form-item>
        <el-form-item label="架构">
          <el-select v-model="imgForm.arch" style="width:100%">
            <el-option label="amd64" value="amd64" />
            <el-option label="arm64" value="arm64" />
            <el-option label="aarch64" value="aarch64" />
          </el-select>
        </el-form-item>
        <el-form-item label="镜像 URL (可选)">
          <el-input v-model="imgForm.download_url" placeholder="例: http://10.10.250.214:5000/..." />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="imgForm.description" type="textarea" placeholder="描述镜像特性与适用架构" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="saveImage">{{ editingImgId ? '保存修改' : '提交保存' }}</el-button>
      </template>
    </el-dialog>

    <!-- 新建分类 Dialog -->
    <el-dialog v-model="showCategoryDialog" title="新建分类目录" width="450px">
      <el-form :model="categoryForm" label-width="90px">
        <el-form-item label="分类名称">
          <el-input v-model="categoryForm.name" placeholder="例: 沐曦推理镜像" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="categoryForm.description" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCategoryDialog = false">取消</el-button>
        <el-button type="primary" @click="saveCategory">创建</el-button>
      </template>
    </el-dialog>

    <!-- docker pull 下发到设备 Dialog -->
    <el-dialog v-model="showDeployDialog" title="Docker Pull 下发到目标设备" width="560px">
      <el-form label-width="100px">
        <el-form-item label="已选镜像">
          <div>
            <b>{{ deployImg?.name }}</b>
            <div style="margin-top:4px">
              <code style="background:#f1f5f9;padding:2px 6px;border-radius:4px;font-size:12px;">{{ deployImg?.image_tag }}</code>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="目标设备">
          <el-select v-model="selectedDeviceIds" multiple placeholder="选择要下发的设备（可多选）" style="width:100%">
            <el-option
              v-for="d in devices"
              :key="d.id"
              :label="`${d.name} (${d.host})${d.chip_type ? ' [' + d.chip_type + ']' : ''}`"
              :value="d.id"
            />
          </el-select>
          <div v-if="deployImg?.chip_type" style="font-size:12px;color:#e6a23c;margin-top:4px">
            提示: 该镜像适配芯片「{{ chipLabel(deployImg.chip_type) }}」，请选择对应设备的设备
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDeployDialog = false">取消</el-button>
        <el-button type="primary" :loading="deploying" @click="confirmDeploy">开始下发 docker pull</el-button>
      </template>
    </el-dialog>

    <!-- 部署状态/日志 Dialog（实时 + 后台历史） -->
    <el-dialog v-model="showLogsDialog" :title="`部署日志 — ${logsImg?.name || ''}`" width="760px">
      <div v-if="logsImg" style="margin-bottom:10px;color:#64748b;font-size:13px;">
        <code style="background:#f1f5f9;padding:2px 6px;border-radius:4px;">{{ logsImg.image_tag }}</code>
      </div>
      <div v-if="deployBindings.length" style="margin-bottom:12px">
        <b style="font-size:13px;color:#1e293b;">设备部署状态</b>
        <el-table :data="deployBindings" size="small" style="margin-top:6px">
          <el-table-column label="绑定ID" prop="id" width="70" />
          <el-table-column label="设备ID" prop="device_id" width="70" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 'ready' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'">
                {{ bindingStatusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最近输出（脱敏）" prop="message" min-width="300" show-overflow-tooltip />
          <el-table-column label="完成时间" width="160">
            <template #default="{ row }">{{ row.pulled_at || '-' }}</template>
          </el-table-column>
        </el-table>
      </div>
      <b style="font-size:13px;color:#1e293b;">历史日志（脱敏后落库）</b>
      <div class="log-panel">
        <div v-for="l in deployLogs" :key="l.id" class="log-line">
          <span class="log-time">{{ (l.created_at || '').replace('T', ' ').slice(0, 19) }}</span>
          <span :class="['log-level', `level-${(l.level || 'INFO').toLowerCase()}`]">{{ l.level }}</span>
          <span class="log-msg">{{ l.message }}</span>
        </div>
        <div v-if="!deployLogs.length" style="color:#94a3b8;text-align:center;padding:20px 0">暂无日志</div>
      </div>
      <template #footer>
        <el-button @click="showLogsDialog = false">关闭</el-button>
        <el-button type="primary" plain @click="refreshLogs">刷新</el-button>
      </template>
    </el-dialog>
    </el-tab-pane>

    <el-tab-pane label="沐曦资源中心" name="metax">
      <!-- 未连接状态 -->
      <div v-if="!metaxSessionId" class="metax-connect">
        <el-icon style="font-size: 42px; color: #94a3b8;"><Connection /></el-icon>
        <p style="color: #475569; margin: 12px 0 4px;">浏览沐曦软星推理镜像需要先登录授权</p>
        <p style="color: #94a3b8; font-size: 12px; margin: 0 0 16px;">将打开新窗口跳转沐曦官方登录，授权后自动返回，平台不保存您的账号信息</p>
        <el-button type="primary" @click="connectMetax">
          <el-icon><Link /></el-icon> 连接沐曦软星
        </el-button>
      </div>

      <!-- 已连接: 镜像清单 -->
      <div v-else>
        <div class="metax-toolbar">
          <el-button size="small" @click="loadMetaxCatalog"><el-icon><Refresh /></el-icon> 刷新</el-button>
          <span class="metax-user" v-if="metaxUsername">已连接: {{ metaxUsername }}</span>
          <el-button size="small" type="danger" plain @click="disconnectMetax">断开</el-button>
        </div>
        <el-alert v-if="metaxError" :title="metaxError" type="error" show-icon style="margin-bottom:10px" />

        <el-table :data="metaxImages" v-loading="metaxLoading" stripe border class="custom-table">
          <el-table-column prop="name" label="镜像名称" min-width="220">
            <template #default="{ row }">
              <b style="color:#c2410c;">{{ row.name }}</b>
            </template>
          </el-table-column>
          <el-table-column prop="version" label="版本" width="130" />
          <el-table-column prop="arch" label="架构" width="90" />
          <el-table-column prop="size" label="大小" width="100" />
          <el-table-column prop="description" label="说明" min-width="220" show-overflow-tooltip />
          <el-table-column label="操作" width="170" align="center" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="success" @click="openMetaxDeploy(row)">docker pull 下发</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-tab-pane>
    </el-tabs>

  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'
import { useDragSelect } from '../utils/dragSelect'

const tableRef = ref(null)
const images = ref([])
const categories = ref([])
const devices = ref([])
const selectedImages = ref([])
const activeCategory = ref(null)
const searchKw = ref('')
const mainView = ref('platform')

// ---------- 沐曦软星会话与清单 ----------
const metaxSessionId = ref(localStorage.getItem('metax_session_id') || '')
const metaxUsername = ref('')
const metaxImages = ref([])
const metaxLoading = ref(false)
const metaxError = ref('')
const metaxConfig = ref({})

const checkMetaxSession = async () => {
  if (!metaxSessionId.value) return
  try {
    const res = await api.get('/images/metax/oauth/status', { params: { session_id: metaxSessionId.value } })
    if (res.data.logged_in) {
      metaxUsername.value = res.data.username || ''
      await loadMetaxCatalog()
    } else {
      metaxSessionId.value = ''
      localStorage.removeItem('metax_session_id')
    }
  } catch (err) { /* ignore */ }
}

const connectMetax = async () => {
  try {
    const res = await api.get('/images/metax/config')
    metaxConfig.value = res.data
    const base = res.data.base_url
    const prefix = res.data.api_prefix || '/client/api'
    // 新窗口打开软星 authing 登录，回调到平台前端 #/metax-callback
    const redirectUri = encodeURIComponent(`${window.location.origin}${window.location.pathname}#/metax-callback`)
    window.open(`${base}${prefix}/user/authing/login?redirect_uri=${redirectUri}`, '_blank', 'width=720,height=640')
    ElMessage.info('已打开沐曦官方登录窗口，登录完成后会自动返回')
  } catch (err) {
    ElMessage.error('获取沐曦配置失败')
  }
}

const handleMetaxCallback = async (params) => {
  const token = params.access_token || params.token
  if (!token) {
    ElMessage.error('登录回调缺少 token')
    return
  }
  try {
    const res = await api.post('/images/metax/oauth/callback', {
      access_token: token,
      username: params.username || params.name || '',
    })
    metaxSessionId.value = res.data.session_id
    localStorage.setItem('metax_session_id', metaxSessionId.value)
    ElMessage.success('沐曦软星连接成功')
    await checkMetaxSession()
  } catch (err) {
    ElMessage.error('建立会话失败')
  }
}

const disconnectMetax = () => {
  metaxSessionId.value = ''
  metaxUsername.value = ''
  metaxImages.value = []
  localStorage.removeItem('metax_session_id')
  ElMessage.success('已断开沐曦连接')
}

const loadMetaxCatalog = async () => {
  if (!metaxSessionId.value) return
  metaxLoading.value = true
  metaxError.value = ''
  try {
    const res = await api.post('/images/metax/catalog', { session_id: metaxSessionId.value })
    metaxImages.value = normalizeMetaxList(res.data)
  } catch (err) {
    const detail = err.response?.data?.detail || ''
    metaxError.value = detail || '拉取沐曦镜像清单失败'
    if (err.response?.status === 401) {
      metaxSessionId.value = ''
      localStorage.removeItem('metax_session_id')
    }
  } finally {
    metaxLoading.value = false
  }
}

// 把软星返回结构拍平成表格行（兼容 list / items / data 等常见字段）
const normalizeMetaxList = (data) => {
  let rows = []
  if (Array.isArray(data)) rows = data
  else if (Array.isArray(data?.Data)) rows = data.Data
  else if (Array.isArray(data?.data)) rows = data.data
  else if (Array.isArray(data?.items)) rows = data.items
  else if (Array.isArray(data?.list)) rows = data.list
  return rows.map((r, i) => ({
    name: r.name || r.Name || r.display_name || r.title || `镜像-${i + 1}`,
    version: r.version || r.Version || r.tag || '-',
    arch: r.arch || r.Arch || '-',
    size: r.size || r.Size || '',
    description: r.description || r.Description || r.desc || '',
    raw: r,
  }))
}

// 沐曦镜像下发: 登记入库 → 打开设备选择 → 部署
const openMetaxDeploy = async (row) => {
  try {
    // 先登记入库（归入「沐曦推理镜像」分类）
    const reg = await api.post('/images/metax/register', {
      name: row.name,
      image_tag: row.version && row.version !== '-'
        ? `metax/${row.name}:${row.version}`.replace(/\s+/g, '-')
        : `metax/${row.name}`.replace(/\s+/g, '-'),
      chip_type: 'metax_c500',
      arch: row.arch && row.arch !== '-' ? row.arch : 'amd64',
      source_ref: row.name,
      description: row.description,
      pull_command: row.raw?.pull_command || row.raw?.docker_pull || '',
    })
    deployImg.value = reg.data
    selectedDeviceIds.value = []
    showDeployDialog.value = true
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '镜像登记失败')
  }
}

const showAddDialog = ref(false)
const editingImgId = ref(null)
const imgForm = ref({
  name: '', image_tag: '', download_url: '', hardware_group: 'NVIDIA_jetson_AGX_Thor',
  description: '', category_id: null, source: 'custom', chip_type: null, arch: 'amd64',
})

const showCategoryDialog = ref(false)
const categoryForm = ref({ name: '', description: '' })

const showDeployDialog = ref(false)
const deployImg = ref(null)
const selectedDeviceIds = ref([])
const deploying = ref(false)

const showLogsDialog = ref(false)
const logsImg = ref(null)
const deployBindings = ref([])
const deployLogs = ref([])
let logTimer = null

useDragSelect(tableRef, images)

const handleSelectionChange = (val) => { selectedImages.value = val }
const handleRowClick = (row) => {
  if (tableRef.value) tableRef.value.toggleRowSelection(row)
}
watch(activeCategory, () => loadImages())

const sourceLabel = (s) => ({ official: '官方目录', registry: '内网Registry', tar: '离线文件', custom: '自定义' }[s] || s || '自定义')
const chipLabel = (c) => ({
  metax_c500: '沐曦C500', nvidia_thor: 'Jetson Thor', nvidia_rtx5090: 'RTX 5090', mthreads_musa: '摩尔线程',
}[c] || c)
const statusLabel = (s) => ({ ready: '就绪', downloading: '下载中', failed: '失败', deployed: '已部署' }[s] || s)
const statusTagType = (s) => (s === 'ready' ? 'success' : s === 'failed' ? 'danger' : 'warning')
const bindingStatusLabel = (s) => ({ pending: '排队中', pulling: '拉取中', ready: '已完成', failed: '失败' }[s] || s)

const loadImages = async () => {
  try {
    const params = {}
    if (activeCategory.value) params.category_id = activeCategory.value
    if (searchKw.value) params.search = searchKw.value
    const res = await api.get('/images', { params })
    images.value = res.data.items || []
  } catch (err) {
    ElMessage.error('加载镜像列表失败')
  }
}

const loadCategories = async () => {
  try {
    const res = await api.get('/image-categories')
    categories.value = res.data
  } catch (err) {
    console.error(err)
  }
}

const loadDevices = async () => {
  try {
    const res = await api.get('/devices')
    devices.value = res.data
  } catch (err) {
    console.error(err)
  }
}

const openCreateImage = () => {
  editingImgId.value = null
  imgForm.value = {
    name: '', image_tag: '', download_url: '', hardware_group: 'NVIDIA_jetson_AGX_Thor',
    description: '', category_id: activeCategory.value, source: 'custom', chip_type: null, arch: 'amd64',
  }
  showAddDialog.value = true
}

const openEditImage = (row) => {
  if (!row) return
  editingImgId.value = row.id
  imgForm.value = {
    name: row.name,
    image_tag: row.image_tag,
    download_url: row.download_url || '',
    hardware_group: row.hardware_group || 'NVIDIA_jetson_AGX_Thor',
    description: row.description || '',
    category_id: row.category_id || null,
    source: row.source || 'custom',
    chip_type: row.chip_type || null,
    arch: row.arch || 'amd64',
  }
  showAddDialog.value = true
}

const saveImage = async () => {
  if (!imgForm.value.name.trim() || !imgForm.value.image_tag.trim()) {
    return ElMessage.warning('请填写镜像名称和 Tag')
  }
  try {
    if (editingImgId.value) {
      await api.put(`/images/${editingImgId.value}`, imgForm.value)
      ElMessage.success('镜像信息修改成功')
    } else {
      await api.post('/images', imgForm.value)
      ElMessage.success('镜像注册成功')
    }
    showAddDialog.value = false
    loadImages()
    loadCategories()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || (editingImgId.value ? '修改失败' : '创建失败'))
  }
}

const openCreateCategory = () => {
  categoryForm.value = { name: '', description: '' }
  showCategoryDialog.value = true
}

const saveCategory = async () => {
  if (!categoryForm.value.name.trim()) return ElMessage.warning('请填写分类名称')
  try {
    await api.post('/image-categories', categoryForm.value)
    ElMessage.success('分类创建成功')
    showCategoryDialog.value = false
    loadCategories()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '创建失败')
  }
}

const openDeploy = (row) => {
  if (!row) return
  deployImg.value = row
  selectedDeviceIds.value = []
  showDeployDialog.value = true
}

const confirmDeploy = async () => {
  if (!selectedDeviceIds.value.length) return ElMessage.warning('请选择目标设备')
  deploying.value = true
  try {
    const res = await api.post(`/images/${deployImg.value.id}/deploy-to-device`, {
      device_ids: selectedDeviceIds.value,
    })
    ElMessage.success(res.data.message || '已下发')
    showDeployDialog.value = false
    openLogs(deployImg.value)
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '部署失败')
  } finally {
    deploying.value = false
  }
}

const openLogs = (row) => {
  logsImg.value = row
  showLogsDialog.value = true
  refreshLogs()
  if (logTimer) clearInterval(logTimer)
  logTimer = setInterval(refreshLogs, 5000)
}

const refreshLogs = async () => {
  if (!logsImg.value) return
  try {
    const [bRes, lRes] = await Promise.all([
      api.get(`/images/${logsImg.value.id}/deploy-status`),
      api.get(`/images/${logsImg.value.id}/deploy-logs`, { params: { limit: 200 } }),
    ])
    deployBindings.value = bRes.data
    deployLogs.value = lRes.data
  } catch (err) {
    console.error(err)
  }
}

const confirmDeleteSelectedImages = () => {
  if (selectedImages.value.length === 0) return
  ElMessageBox.confirm(
    `确定要永久删除选中的 ${selectedImages.value.length} 个镜像配置吗？此操作不可撤销！`,
    '危险删除确认',
    { confirmButtonText: '确认永久删除', cancelButtonText: '取消', type: 'warning', center: true }
  ).then(async () => {
    try {
      for (const img of selectedImages.value) {
        await api.delete(`/images/${img.id}`)
      }
      ElMessage.success(`已删除选中的 ${selectedImages.value.length} 个镜像`)
      selectedImages.value = []
      loadImages()
      loadCategories()
    } catch (err) {
      ElMessage.error('批量删除失败')
    }
  }).catch(() => {})
}

onMounted(() => {
  loadImages()
  loadCategories()
  loadDevices()
  checkMetaxSession()

  // 处理沐曦登录回调: #/metax-callback?access_token=xxx
  if (window.location.hash.startsWith('#/metax-callback')) {
    const qs = new URLSearchParams(window.location.hash.split('?')[1] || '')
    const params = Object.fromEntries(qs.entries())
    handleMetaxCallback(params)
    window.location.hash = '#/images'
  }
})

onBeforeUnmount(() => {
  if (logTimer) clearInterval(logTimer)
})
</script>

<style scoped>
.image-mgmt-page { padding: 20px; }
.page-header h2 { margin: 0; font-size: 20px; color: #1e293b; }
.page-header .subtitle { color: #64748b; font-size: 13px; margin: 4px 0 16px 0; }

.main-tabs { background: transparent; }

.metax-connect {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 60px 0; background: #fff; border-radius: 8px; border: 1px solid #e5e7eb;
}
.metax-toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
.metax-user { color: #16a34a; font-size: 13px; }


.category-bar { margin-bottom: 14px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.cat-badge { margin-left: 4px; }

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

.custom-table { background: #ffffff; border-radius: 8px; cursor: pointer; }

.log-panel {
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  max-height: 420px;
  overflow-y: auto;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
}
.log-line { display: flex; gap: 8px; padding: 2px 0; line-height: 1.5; }
.log-time { color: #64748b; flex-shrink: 0; }
.log-level { flex-shrink: 0; width: 54px; }
.level-info { color: #38bdf8; }
.level-warning { color: #fbbf24; }
.level-error { color: #f87171; }
.log-msg { white-space: pre-wrap; word-break: break-all; }
</style>
