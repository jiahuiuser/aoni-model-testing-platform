<template>
  <div class="image-mgmt-page">
    <div class="page-header">
      <div>
        <h2>镜像管理</h2>
        <p class="subtitle">管理云端 Docker 推理镜像、硬件组绑定与目标设备一键部署拉取</p>
      </div>
    </div>

    <!-- 顶部统一 CRUD 操作工具栏 -->
    <div class="top-toolbar">
      <div class="toolbar-left">
        <el-button type="primary" @click="openCreateImage">
          <el-icon><Plus /></el-icon> 注册镜像
        </el-button>
        <el-button
          type="warning"
          plain
          :disabled="selectedImages.length !== 1"
          @click="openEditImage(selectedImages[0])"
        >
          <el-icon><Edit /></el-icon> 编辑镜像
        </el-button>
        <el-button
          type="primary"
          plain
          :disabled="selectedImages.length !== 1"
          @click="openDeploy(selectedImages[0])"
        >
          <el-icon><Promotion /></el-icon> 下发部署
        </el-button>
        <el-button
          type="success"
          plain
          :disabled="selectedImages.length !== 1"
          @click="pullImage(selectedImages[0])"
        >
          <el-icon><Download /></el-icon> 拉取镜像
        </el-button>
        <el-button
          v-if="selectedImages.length > 0"
          type="danger"
          plain
          @click="confirmDeleteSelectedImages"
        >
          <el-icon><Delete /></el-icon> 批量删除 ({{ selectedImages.length }})
        </el-button>
      </div>

      <div class="toolbar-right">
        <el-button circle @click="loadImages"><el-icon><Refresh /></el-icon></el-button>
      </div>
    </div>

    <!-- 表格视图 -->
    <el-table
      ref="tableRef"
      :data="images"
      stripe
      border
      style="width: 100%"
      @selection-change="handleSelectionChange"
      @row-click="handleRowClick"
      class="custom-table"
    >
      <el-table-column type="selection" width="50" align="center" />
      <el-table-column prop="id" label="ID" width="60" align="center" />
      <el-table-column prop="name" label="镜像显示名称" min-width="180">
        <template #default="{ row }">
          <b style="color:#2563eb;">{{ row.name }}</b>
        </template>
      </el-table-column>
      <el-table-column prop="image_tag" label="Docker Image Tag" min-width="240">
        <template #default="{ row }">
          <code style="background:#f1f5f9;padding:2px 6px;border-radius:4px;color:#0f172a;">{{ row.image_tag }}</code>
        </template>
      </el-table-column>
      <el-table-column prop="hardware_group" label="绑定硬件组" width="180">
        <template #default="{ row }">
          <el-tag type="info">{{ row.hardware_group }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="110" align="center">
        <template #default="{ row }">
          <el-tag :type="row.status === 'ready' ? 'success' : 'warning'">{{ row.status === 'ready' ? '就绪' : '下载中' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="描述" min-width="220" show-overflow-tooltip />
    </el-table>

    <!-- 添加/编辑镜像 Dialog -->
    <el-dialog v-model="showAddDialog" :title="editingImgId ? '编辑 Docker 镜像信息' : '添加/绑定 Docker 镜像'" width="550px">
      <el-form :model="imgForm" label-width="120px">
        <el-form-item label="镜像名称">
          <el-input v-model="imgForm.name" placeholder="例: vLLM Jetson Thor 专用镜像" />
        </el-form-item>
        <el-form-item label="Docker Image Tag">
          <el-input v-model="imgForm.image_tag" placeholder="例: aoni/vllm/vllm-openai:v0.20.0-ubuntu2404" />
        </el-form-item>
        <el-form-item label="镜像 URL (可选)">
          <el-input v-model="imgForm.download_url" placeholder="例: http://10.10.250.214:5000/..." />
        </el-form-item>
        <el-form-item label="绑定硬件组">
          <el-select v-model="imgForm.hardware_group" style="width:100%;">
            <el-option v-for="g in hardwareGroups" :key="g.id" :label="g.name" :value="g.name" />
          </el-select>
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

    <!-- 部署到指定设备 Dialog -->
    <el-dialog v-model="showDeployDialog" title="部署 Docker 镜像到目标设备" width="500px">
      <el-form label-width="100px">
        <el-form-item label="已选镜像">
          <b>{{ selectedImg?.name }}</b> ({{ selectedImg?.image_tag }})
        </el-form-item>
        <el-form-item label="目标设备">
          <el-select v-model="selectedDeviceId" placeholder="请选择目标设备" style="width:100%;">
            <el-option v-for="d in devices" :key="d.id" :label="`${d.name} (${d.host})`" :value="d.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDeployDialog = false">取消</el-button>
        <el-button type="primary" :loading="deploying" @click="confirmDeploy">开始下发部署</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'
import { useDragSelect } from '../utils/dragSelect'

const tableRef = ref(null)
const images = ref([])
const hardwareGroups = ref([])
const devices = ref([])
const selectedImages = ref([])

useDragSelect(tableRef, images)

const handleSelectionChange = (val) => {
  selectedImages.value = val
}

const handleRowClick = (row) => {
  if (tableRef.value) {
    tableRef.value.toggleRowSelection(row)
  }
}

const showAddDialog = ref(false)
const editingImgId = ref(null)
const imgForm = ref({
  name: '',
  image_tag: '',
  download_url: '',
  hardware_group: 'NVIDIA_jetson_AGX_Thor',
  description: '',
})

const showDeployDialog = ref(false)
const selectedImg = ref(null)
const selectedDeviceId = ref(null)
const deploying = ref(false)

const loadImages = async () => {
  try {
    const res = await api.get('/images')
    images.value = res.data
  } catch (err) {
    ElMessage.error('加载镜像列表失败')
  }
}

const loadHardwareGroups = async () => {
  try {
    const res = await api.get('/hardware-groups')
    hardwareGroups.value = res.data
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
    name: '',
    image_tag: '',
    download_url: '',
    hardware_group: 'NVIDIA_jetson_AGX_Thor',
    description: '',
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
      ElMessage.success('添加镜像绑定成功')
    }
    showAddDialog.value = false
    loadImages()
  } catch (err) {
    ElMessage.error(editingImgId.value ? '修改失败' : '创建失败')
  }
}

const pullImage = async (row) => {
  if (!row) return
  try {
    await api.post(`/images/${row.id}/download`)
    ElMessage.success(`已下发镜像 ${row.image_tag} 拉取任务`)
    loadImages()
  } catch (err) {
    ElMessage.error('拉取失败')
  }
}

const openDeploy = (row) => {
  if (!row) return
  selectedImg.value = row
  selectedDeviceId.value = devices.value[0]?.id || null
  showDeployDialog.value = true
}

const confirmDeploy = async () => {
  if (!selectedDeviceId.value) return ElMessage.warning('请选择目标设备')
  deploying.value = true
  try {
    const res = await api.post(`/images/${selectedImg.value.id}/deploy-to-device`, {
      device_id: selectedDeviceId.value,
    })
    ElMessage.success(res.data.message || '已成功发起部署')
    showDeployDialog.value = false
  } catch (err) {
    ElMessage.error('部署失败')
  } finally {
    deploying.value = false
  }
}

const deleteImage = (id) => {
  ElMessageBox.confirm('确认删除该镜像记录？', '提示', { type: 'warning' }).then(async () => {
    await api.delete(`/images/${id}`)
    ElMessage.success('已删除')
    loadImages()
  })
}

const confirmDeleteSelectedImages = () => {
  if (selectedImages.value.length === 0) return
  ElMessageBox.confirm(
    `确定要永久删除选中的 ${selectedImages.value.length} 个镜像配置吗？此操作不可撤销！`,
    '危险删除确认',
    {
      confirmButtonText: '确认永久删除',
      cancelButtonText: '取消',
      type: 'warning',
      center: true,
    }
  ).then(() => {
    handleBatchDeleteImages()
  }).catch(() => {})
}

const handleBatchDeleteImages = async () => {
  try {
    for (const img of selectedImages.value) {
      await api.delete(`/images/${img.id}`)
    }
    ElMessage.success(`已删除选中的 ${selectedImages.value.length} 个镜像绑定`)
    selectedImages.value = []
    loadImages()
  } catch (err) {
    ElMessage.error('批量删除失败')
  }
}

onMounted(() => {
  loadImages()
  loadHardwareGroups()
  loadDevices()
})
</script>

<style scoped>
.image-mgmt-page { padding: 20px; }
.page-header h2 { margin: 0; font-size: 20px; color: #1e293b; }
.page-header .subtitle { color: #64748b; font-size: 13px; margin: 4px 0 16px 0; }

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
</style>
