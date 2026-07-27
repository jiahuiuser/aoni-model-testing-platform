<template>
  <div class="model-mgmt-page">
    <!-- 顶部统一 CRUD 操作工具栏 -->
    <div class="top-toolbar">
      <div class="toolbar-left">
        <el-button type="primary" @click="showAddDialog">
          <el-icon><Plus /></el-icon> 新增模型
        </el-button>
        <el-button type="success" plain @click="openScanTOSDialog">
          <el-icon><Cloudy /></el-icon> 扫描 TOS 仓库导入
        </el-button>
        <el-button type="success" plain :disabled="selectedModels.length !== 1" @click="openRunTestDialog">
          <el-icon><VideoPlay /></el-icon> 模型验证
        </el-button>
        <el-button type="warning" plain :disabled="selectedModels.length !== 1" @click="openEditSelected">
          <el-icon><Edit /></el-icon> 编辑模型
        </el-button>
        <el-button type="primary" plain :disabled="selectedModels.length !== 1" @click="openDeviceConfigsSelected">
          <el-icon><Setting /></el-icon> 设备专属配置
        </el-button>
        <el-popconfirm
          v-if="selectedModels.length > 0"
          :title="`确定删除选中的 ${selectedModels.length} 个模型？`"
          confirm-button-text="确认删除"
          cancel-button-text="取消"
          confirm-button-type="danger"
          placement="bottom"
          :teleported="true"
          @confirm="handleDeleteSelected"
        >
          <template #reference>
            <el-button type="danger" plain>
              <el-icon><Delete /></el-icon> 批量删除 ({{ selectedModels.length }})
            </el-button>
          </template>
        </el-popconfirm>

        <!-- 批量划归硬件组 -->
        <el-popover placement="bottom-start" :width="280" trigger="click" v-if="selectedModels.length > 0">
          <template #reference>
            <el-button type="info" plain>
              <el-icon><Connection /></el-icon> 划归硬件组 ({{ selectedModels.length }})
            </el-button>
          </template>
          <div>
            <div style="font-weight:bold;margin-bottom:8px;font-size:13px">将选中的 {{ selectedModels.length }} 个模型移动至:</div>
            <el-select v-model="batchTargetGroup" placeholder="选择目标硬件组" style="width:100%;margin-bottom:10px">
              <el-option label="🚀 NVIDIA_jetson_AGX_Thor" value="NVIDIA_jetson_AGX_Thor" />
              <el-option label="⚡ 沐曦C500/N260" value="沐曦C500/N260" />
              <el-option label="🖥️ 英伟达服务器" value="英伟达服务器" />
            </el-select>
            <el-button type="primary" size="small" style="width:100%" :loading="batchUpdatingGroup" @click="handleBatchUpdateGroup">
              确认划归
            </el-button>
          </div>
        </el-popover>
      </div>

      <div class="toolbar-right">
        <el-popover placement="bottom-end" :width="300" trigger="click">
          <template #reference>
            <el-button type="danger" plain size="small">
              <el-icon><Delete /></el-icon> 清理残留容器
            </el-button>
          </template>
          <div>
            <div style="font-weight:bold;margin-bottom:8px;font-size:13px">清理目标设备上的残留容器:</div>
            <el-select v-model="cleanDeviceId" placeholder="选择目标设备 (默认本机)" style="width:100%;margin-bottom:8px" clearable>
              <el-option v-for="d in devices" :key="d.id" :label="d.name" :value="d.id" />
            </el-select>
            <el-button type="danger" size="small" style="width:100%" :loading="cleaning" @click="handleStopContainer">
              释放显存资源
            </el-button>
          </div>
        </el-popover>
        <el-button circle @click="loadModels"><el-icon><Refresh /></el-icon></el-button>
      </div>
    </div>

    <!-- 硬件组/模块分类 Tab 切换栏 -->
    <div class="group-tab-bar">
      <div
        v-for="grp in groupOptions"
        :key="grp.value"
        class="group-tab-item"
        :class="{ active: activeGroup === grp.value }"
        @click="activeGroup = grp.value"
      >
        <span class="group-tab-emoji">{{ grp.emoji }}</span>
        <span class="group-tab-label">{{ grp.label }}</span>
        <span class="group-tab-count">{{ groupCounts[grp.value] || 0 }}</span>
      </div>
    </div>

    <!-- 模型表格 -->
    <el-table
      ref="tableRef"
      :data="filteredModels"
      v-loading="loading"
      stripe
      border
      @selection-change="handleSelectionChange"
      @row-click="handleRowClick"
      @row-dblclick="openRunTestDialog"
      class="custom-table"
      row-key="slug"
    >
      <el-table-column type="selection" width="50" align="center" />
      <el-table-column prop="idx" label="#" width="50" align="center" />
      <el-table-column prop="name" label="模型名称" min-width="170" show-overflow-tooltip />

      <!-- 所属硬件组/模块 -->
      <el-table-column label="所属硬件组" width="165" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.group_name === '沐曦C500/N260'" type="warning" size="small" effect="dark">
            ⚡ 沐曦C500/N260
          </el-tag>
          <el-tag v-else-if="row.group_name === '英伟达服务器'" type="danger" size="small" effect="dark">
            🖥️ 英伟达服务器
          </el-tag>
          <el-tag v-else type="primary" size="small" effect="dark">
            🚀 Jetson AGX Thor
          </el-tag>
        </template>
      </el-table-column>

      <!-- 规格分类 -->
      <el-table-column label="规格分类" width="110" align="center">
        <template #default="{ row }">
          <el-tag v-if="getSpecCategory(row) === 'small'" type="success" size="small" effect="light">Small</el-tag>
          <el-tag v-else-if="getSpecCategory(row) === 'medium'" type="warning" size="small" effect="light">Medium</el-tag>
          <el-tag v-else type="danger" size="small" effect="light">Large</el-tag>
        </template>
      </el-table-column>

      <el-table-column label="验证状态" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="row.status === 'PASS' ? 'success' : row.status === 'FAIL' ? 'danger' : 'info'" size="small">
            {{ row.status === 'PASS' ? '通过' : row.status === 'FAIL' ? '失败' : '待验证' }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column label="设备绑定情况" min-width="200">
        <template #default="{ row }">
          <div class="device-config-tags">
            <template v-if="row.device_configs && row.device_configs.length">
              <el-tag
                v-for="dc in row.device_configs"
                :key="dc.id"
                size="small"
                :type="dc.status === 'PASS' ? 'success' : dc.status === 'FAIL' ? 'danger' : 'warning'"
                style="margin:2px;cursor:pointer"
                @click.stop="openDeviceConfigs(row)"
              >
                {{ dc.device_name }}: {{ dc.status === 'PASS' ? 'PASS' : dc.status === 'FAIL' ? 'FAIL' : 'NEW' }}
              </el-tag>
            </template>
            <span v-else style="color:#bbb;font-size:12px">使用通用配置</span>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <!-- 选择模型验证设备 Modal -->
    <el-dialog v-model="runTestModalVisible" :title="`选择验证目标设备 — ${selectedModel?.name || ''}`" width="500px">
      <template v-if="boundDevices.length > 0">
        <el-form label-width="110px">
          <el-form-item label="已绑定节点" required>
            <el-select v-model="targetRunDeviceId" placeholder="请选择已绑定的验证节点" style="width:100%">
              <el-option
                v-for="d in boundDevices"
                :key="d.id"
                :label="`${d.name} (${d.host})`"
                :value="d.id"
              />
            </el-select>
          </el-form-item>
        </el-form>
      </template>
      <template v-else>
        <el-alert
          type="warning"
          title="当前模型尚未绑定任何算力设备"
          description="设备未绑定，无法进行模型验证。请先为该模型添加目标算力节点的专属 Docker 运行命令与设备绑定。"
          show-icon
          :closable="false"
        />
      </template>
      <template #footer>
        <el-button @click="runTestModalVisible = false">取消</el-button>
        <el-button v-if="boundDevices.length > 0" type="success" :disabled="!targetRunDeviceId" @click="confirmRunTest">
          <el-icon><VideoPlay /></el-icon> 开始执行验证
        </el-button>
        <el-button v-else type="primary" @click="openDeviceConfigsSelected">
          <el-icon><Setting /></el-icon> 去绑定设备配置
        </el-button>
      </template>
    </el-dialog>

    <!-- ☁️ 交互式 TOS 仓库扫描与勾选导入 Modal -->
    <el-dialog v-model="scanModalVisible" title="☁️ 扫描 TOS 云端仓库模型并勾选导入" width="860px">
      <el-form inline label-width="110px" style="margin-bottom:12px">
        <el-form-item label="TOS 存储桶">
          <el-input v-model="scanForm.bucket_name" placeholder="ai-hub" style="width:130px" />
        </el-form-item>
        <el-form-item label="扫描路径/前缀">
          <el-input v-model="scanForm.prefix" placeholder="如 models/ 或 models/qwen/" style="width:210px" />
        </el-form-item>
        <el-form-item label="划归硬件组">
          <el-select v-model="scanForm.group_name" style="width:200px">
            <el-option label="🚀 NVIDIA_jetson_AGX_Thor" value="NVIDIA_jetson_AGX_Thor" />
            <el-option label="⚡ 沐曦C500/N260" value="沐曦C500/N260" />
            <el-option label="🖥️ 英伟达服务器" value="英伟达服务器" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="scanningTOS" @click="handlePreviewTOS">
            <el-icon><Search /></el-icon> 开始扫描路径
          </el-button>
        </el-form-item>
      </el-form>

      <div v-if="scannedItems.length > 0">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;font-size:13px">
          <span>共探测到 <b style="color:#409eff">{{ scannedItems.length }}</b> 个模型文件，请勾选需要导入至平台的模型：</span>
          <span>已勾选: <b style="color:#67c23a;font-size:15px">{{ selectedScanItems.length }}</b> 项</span>
        </div>

        <el-table
          :data="scannedItems"
          max-height="360px"
          border
          size="small"
          @selection-change="handleScanSelectionChange"
        >
          <el-table-column type="selection" width="45" />
          <el-table-column prop="display_name" label="模型显示名" min-width="160" show-overflow-tooltip />
          <el-table-column prop="size_human" label="文件大小" width="100" />
          <el-table-column prop="key" label="TOS 云端完整路径" min-width="260" show-overflow-tooltip />
          <el-table-column label="导入状态" width="130">
            <template #default="scope">
              <el-tag v-if="scope.row.is_existing" type="info" size="small">
                已在平台 ({{ scope.row.existing_group }})
              </el-tag>
              <el-tag v-else type="success" size="small">未导入 (新模型)</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div v-else-if="hasScanned" style="text-align:center;padding:40px;color:#909399;font-size:14px">
        🔍 在指定路径 <code>{{ scanForm.prefix }}</code> 下未找到匹配的模型文件 (.tar.gz / .gguf / .tar)
      </div>
      <div v-else style="text-align:center;padding:40px;color:#909399;font-size:13px">
        💡 请输入想要扫描的 TOS 路径前缀（如 <code>models/</code> 或 <code>models/muxi/</code>），点击【开始扫描路径】按钮
      </div>

      <template #footer>
        <el-button @click="scanModalVisible = false">取消</el-button>
        <el-button
          type="success"
          :disabled="selectedScanItems.length === 0"
          :loading="importingTOS"
          @click="handleConfirmImportTOS"
        >
          <el-icon><Check /></el-icon> 确认导入选中的模型 ({{ selectedScanItems.length }})
        </el-button>
      </template>
    </el-dialog>

    <!-- 新增/编辑模型对话框 -->
    <el-dialog v-model="dialogVisible" :title="editing ? '编辑模型' : '新增模型'" width="650px">
      <el-form :model="form" label-width="120px">
        <el-form-item label="模型名称">
          <el-input v-model="form.name" placeholder="例如: FunctionGemma" />
        </el-form-item>
        <el-form-item label="所属硬件组">
          <el-select v-model="form.group_name" placeholder="请选择归属硬件架构组" style="width:100%">
            <el-option label="🚀 NVIDIA_jetson_AGX_Thor (Jetson Thor 算力节点)" value="NVIDIA_jetson_AGX_Thor" />
            <el-option label="⚡ 沐曦C500/N260 (沐曦国产算力卡)" value="沐曦C500/N260" />
            <el-option label="🖥️ 英伟达服务器 (数据中心 / 服务器 GPU)" value="英伟达服务器" />
          </el-select>
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

    <!-- 设备配置对话框 -->
    <el-dialog v-model="dcDialogVisible" :title="`设备专属配置 — ${currentModel?.name || ''}`" width="780px">
      <div style="background:#f4f4f5;padding:12px;border-radius:6px;margin-bottom:16px">
        <div style="font-size:13px;font-weight:bold;margin-bottom:8px;color:#303133">为该模型添加新设备配置:</div>
        <div style="display:flex;gap:12px;align-items:center">
          <el-select v-model="newDcDeviceId" placeholder="选择目标设备" style="width:220px">
            <el-option v-for="d in availableDevices" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
          <el-button type="primary" size="small" @click="addDc" :disabled="!newDcDeviceId">
            添加配置
          </el-button>
        </div>
      </div>

      <el-table :data="currentDeviceConfigs" size="small" stripe border>
        <el-table-column prop="device_name" label="设备名称" width="150" />
        <el-table-column label="验证状态" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === 'PASS' ? 'success' : row.status === 'FAIL' ? 'danger' : 'warning'" size="small">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="Docker 运行指令" min-width="260">
          <template #default="{ row }">
            <el-popover placement="top" :width="540" trigger="hover">
              <template #reference>
                <div class="cmd-pill-trigger">
                  <span class="cmd-text-ellipsis">{{ row.docker_command || '未配置独立指令，使用模型默认指令' }}</span>
                  <el-icon class="cmd-copy-icon"><CopyDocument /></el-icon>
                </div>
              </template>
              <div class="popover-cmd-box">
                <div class="popover-header">
                  <span class="popover-title">🚀 {{ row.device_name }} 运行指令</span>
                  <el-button size="small" type="primary" link @click="copyCmd(row.docker_command)">
                    <el-icon><CopyDocument /></el-icon> 复制运行指令
                  </el-button>
                </div>
                <pre class="cmd-block-pretty">{{ formatCmdPretty(row.docker_command) }}</pre>
              </div>
            </el-popover>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="160" align="center">
          <template #default="{ row }">
            <div class="dc-action-row">
              <el-button size="small" type="primary" plain @click="editDc(row)">
                <el-icon><Edit /></el-icon> 编辑
              </el-button>
              <el-popconfirm
                title="确定删除该设备专属配置？"
                confirm-button-text="确认删除"
                cancel-button-text="取消"
                confirm-button-type="danger"
                placement="top"
                :teleported="true"
                @confirm="deleteDc(row.id)"
              >
                <template #reference>
                  <el-button size="small" type="danger" plain>
                    <el-icon><Delete /></el-icon> 删除
                  </el-button>
                </template>
              </el-popconfirm>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 编辑设备配置命令对话框 -->
    <el-dialog v-model="dcEditVisible" title="编辑设备专属 Docker 命令" width="650px" append-to-body>
      <el-form label-width="100px">
        <el-form-item label="目标设备">
          <strong>{{ editingDc?.device_name }}</strong>
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
import { useTestStore } from '../stores/testStore'
import { apiListModels, apiCreateModel, apiUpdateModel, apiDeleteModel } from '../api'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import { useDragSelect } from '../utils/dragSelect'

const testStore = useTestStore()
const tableRef = ref(null)
const models = ref([])
const devices = ref([])
const loading = ref(false)
const selectedModels = ref([])
const singleSelected = computed(() => selectedModels.value.length === 1 ? selectedModels.value[0] : null)
const selectedModel = computed(() => singleSelected.value)

useDragSelect(tableRef, models)

const dialogVisible = ref(false)
const editing = ref(null)

const runTestModalVisible = ref(false)
const targetRunDeviceId = ref(null)

const cleanDeviceId = ref(null)
const cleaning = ref(false)

const dcDialogVisible = ref(false)
const dcEditVisible = ref(false)
const currentModel = ref(null)
const newDcDeviceId = ref(null)
const editingDc = ref(null)
const editingDcCommand = ref('')
const activeGroup = ref('NVIDIA_jetson_AGX_Thor')
const groupOptions = [
  { label: 'NVIDIA_jetson_AGX_Thor', value: 'NVIDIA_jetson_AGX_Thor', emoji: '🚀' },
  { label: '沐曦C500/N260', value: '沐曦C500/N260', emoji: '⚡' },
  { label: '英伟达服务器', value: '英伟达服务器', emoji: '🖥️' },
  { label: '全部硬件组', value: 'ALL', emoji: '🌐' },
]

const batchTargetGroup = ref('NVIDIA_jetson_AGX_Thor')
const batchUpdatingGroup = ref(false)

const filteredModels = computed(() => {
  let list
  if (activeGroup.value === 'ALL') {
    list = models.value
  } else {
    list = models.value.filter(m => (m.group_name || 'NVIDIA_jetson_AGX_Thor') === activeGroup.value)
  }
  // 重新生成当前视图内 1-based 序号，不使用全局 ID
  return list.map((m, i) => ({ ...m, idx: i + 1 }))
})

const groupCounts = computed(() => {
  const counts = {
    'NVIDIA_jetson_AGX_Thor': 0,
    '沐曦C500/N260': 0,
    '英伟达服务器': 0,
    'ALL': models.value.length
  }
  models.value.forEach(m => {
    const g = m.group_name || 'NVIDIA_jetson_AGX_Thor'
    if (counts[g] !== undefined) {
      counts[g]++
    }
  })
  return counts
})

const form = ref({ name: '', slug: '', group_name: 'NVIDIA_jetson_AGX_Thor', docker_command: '', tos_path: '' })

const handleBatchUpdateGroup = async () => {
  if (selectedModels.value.length === 0) return
  batchUpdatingGroup.value = true
  try {
    const slugs = selectedModels.value.map(m => m.slug)
    await axios.post('/api/models/batch-group', {
      slugs,
      group_name: batchTargetGroup.value
    })
    ElMessage.success(`已将选中的 ${slugs.length} 个模型划归至 [${batchTargetGroup.value}]`)
    selectedModels.value = []
    await loadModels()
  } catch (e) {
    ElMessage.error('批量划归硬件组失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    batchUpdatingGroup.value = false
  }
}

const handleSelectionChange = (val) => {
  selectedModels.value = val
}

const handleRowClick = (row) => {
  if (tableRef.value) {
    tableRef.value.toggleRowSelection(row)
  }
}

const getSpecCategory = (row) => {
  const name = (row.name || '').toLowerCase()
  if (name.includes('2b') || name.includes('1.5b') || name.includes('0.5b') || name.includes('1b') || name.includes('3b')) return 'small'
  if (name.includes('7b') || name.includes('8b') || name.includes('13b') || name.includes('9b') || name.includes('14b')) return 'medium'
  return 'large'
}

const formatCmdPretty = (cmd) => {
  if (!cmd) return '未配置命令'
  let formatted = cmd.trim()
  formatted = formatted
    .replace(/\s+--/g, ' \\\n  --')
    .replace(/\s+-e\s+/g, ' \\\n  -e ')
    .replace(/\s+-v\s+/g, ' \\\n  -v ')
  return formatted
}

const copyCmd = (cmd) => {
  if (!cmd) return
  navigator.clipboard.writeText(cmd)
  ElMessage.success('运行指令已成功复制到剪贴板')
}

const scanModalVisible = ref(false)
const scanningTOS = ref(false)
const importingTOS = ref(false)
const hasScanned = ref(false)
const scanForm = ref({
  bucket_name: 'ai-hub',
  prefix: 'models/',
  group_name: 'NVIDIA_jetson_AGX_Thor'
})
const scannedItems = ref([])
const selectedScanItems = ref([])

const openScanTOSDialog = () => {
  scanForm.value.group_name = activeGroup.value === 'ALL' ? 'NVIDIA_jetson_AGX_Thor' : activeGroup.value
  scannedItems.value = []
  selectedScanItems.value = []
  hasScanned.value = false
  scanModalVisible.value = true
}

const handlePreviewTOS = async () => {
  scanningTOS.value = true
  try {
    const resp = await axios.post('/api/models/preview-tos-scan', scanForm.value)
    scannedItems.value = resp.data.items || []
    hasScanned.value = true
    if (scannedItems.value.length === 0) {
      ElMessage.info('该路径下未扫描到匹配的模型文件')
    } else {
      ElMessage.success(`扫描完成，找到 ${scannedItems.value.length} 个模型文件`)
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '扫描 TOS 仓库失败')
  } finally {
    scanningTOS.value = false
  }
}

const handleScanSelectionChange = (selection) => {
  selectedScanItems.value = selection
}

const handleConfirmImportTOS = async () => {
  if (selectedScanItems.value.length === 0) return
  importingTOS.value = true
  try {
    const resp = await axios.post('/api/models/import-tos-selected', {
      group_name: scanForm.value.group_name,
      bucket_name: scanForm.value.bucket_name,
      selected_items: selectedScanItems.value.map(item => ({
        key: item.key,
        model_name: item.model_name,
        slug: item.slug,
        tos_path: item.tos_path
      }))
    })
    ElMessage.success(resp.data.message || '选中的模型导入成功')
    scanModalVisible.value = false
    await loadModels()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '导入模型失败')
  } finally {
    importingTOS.value = false
  }
}

const loadModels = async () => {
  loading.value = true
  try {
    models.value = await apiListModels()
  } catch (e) { console.error(e) }
  loading.value = false
}

const loadDevices = async () => {
  try { devices.value = (await axios.get('/api/devices')).data } catch (e) { /* */ }
}

const showAddDialog = () => {
  editing.value = null
  const defaultGrp = activeGroup.value === 'ALL' ? 'NVIDIA_jetson_AGX_Thor' : activeGroup.value
  form.value = { name: '', slug: '', group_name: defaultGrp, docker_command: '', tos_path: '' }
  dialogVisible.value = true
}

const openEditSelected = () => {
  if (!selectedModel.value) return
  editing.value = selectedModel.value.slug
  form.value = {
    name: selectedModel.value.name,
    slug: selectedModel.value.slug,
    group_name: selectedModel.value.group_name || 'NVIDIA_jetson_AGX_Thor',
    docker_command: selectedModel.value.docker_command || '',
    tos_path: selectedModel.value.tos_path || '',
  }
  dialogVisible.value = true
}

const handleSave = async () => {
  try {
    if (!form.value.slug && form.value.name) {
      form.value.slug = form.value.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '')
    }
    if (editing.value) {
      await apiUpdateModel(editing.value, form.value)
    } else {
      await apiCreateModel(form.value)
    }
    dialogVisible.value = false
    await loadModels()
    ElMessage.success('模型信息已成功保存')
  } catch (e) { ElMessage.error(e.response?.data?.detail || '保存模型失败') }
}

const handleDeleteSelected = async () => {
  if (selectedModels.value.length === 0) return
  loading.value = true
  try {
    for (const m of selectedModels.value) {
      await apiDeleteModel(m.slug)
    }
    selectedModels.value = []
    await loadModels()
    ElMessage.success('选中的模型已成功删除')
  } catch (e) {
    ElMessage.error('删除过程发生异常: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

const boundDevices = computed(() => {
  if (!selectedModel.value || !selectedModel.value.device_configs || selectedModel.value.device_configs.length === 0) {
    return []
  }
  const boundIds = selectedModel.value.device_configs.map(dc => dc.device_id)
  return devices.value.filter(d => boundIds.includes(d.id))
})

const openRunTestDialog = () => {
  if (!selectedModel.value) return
  if (boundDevices.value.length === 0) {
    ElMessage.warning(`模型【${selectedModel.value.name}】暂未绑定任何算力设备，无法执行模型验证！已为您打开设备绑定对话框。`)
    openDeviceConfigsSelected()
    return
  }
  targetRunDeviceId.value = boundDevices.value[0].id
  runTestModalVisible.value = true
}

const confirmRunTest = () => {
  if (!selectedModel.value || !targetRunDeviceId.value) return
  runTestModalVisible.value = false
  const targetDev = devices.value.find(d => d.id === targetRunDeviceId.value)
  const devName = targetDev ? targetDev.name : '未知设备'
  
  testStore.startTest(selectedModel.value.slug, selectedModel.value.name, targetRunDeviceId.value, devName)
}

const openDeviceConfigsSelected = () => {
  if (!selectedModel.value) return
  openDeviceConfigs(selectedModel.value)
}

const openDeviceConfigs = (row) => {
  currentModel.value = row
  newDcDeviceId.value = null
  dcDialogVisible.value = true
}

const handleStopContainer = async () => {
  cleaning.value = true
  try {
    const params = cleanDeviceId.value ? { device_id: cleanDeviceId.value } : {}
    const resp = await axios.post('/api/models/stop-test-container', null, { params })
    ElMessage.success(resp.data.message || '残留容器与资源已被清理')
  } catch (e) { ElMessage.error('清理容器失败') }
  cleaning.value = false
}

const currentDeviceConfigs = computed(() => currentModel.value?.device_configs || [])
const availableDevices = computed(() => {
  if (!currentModel.value) return devices.value
  const configuredIds = (currentModel.value.device_configs || []).map(dc => dc.device_id)
  return devices.value.filter(d => !configuredIds.includes(d.id))
})

const addDc = async () => {
  if (!newDcDeviceId.value || !currentModel.value) return
  try {
    await axios.post(`/api/models/${currentModel.value.slug}/device-configs`, {
      device_id: newDcDeviceId.value,
      docker_command: currentModel.value.docker_command || '',
    })
    await refreshCurrentModel()
    newDcDeviceId.value = null
    ElMessage.success('设备专属配置添加成功')
  } catch (e) { ElMessage.error('添加设备配置失败') }
}

const editDc = (dc) => {
  editingDc.value = dc
  editingDcCommand.value = dc.docker_command || currentModel.value?.docker_command || ''
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
    ElMessage.success('设备指令配置已成功保存')
  } catch (e) { ElMessage.error('保存失败') }
}

const deleteDc = async (configId) => {
  if (!currentModel.value) return
  try {
    await axios.delete(`/api/models/${currentModel.value.slug}/device-configs/${configId}`)
    await refreshCurrentModel()
    ElMessage.success('设备专属配置已成功删除')
  } catch (e) { ElMessage.error('删除失败') }
}

const refreshCurrentModel = async () => {
  if (!currentModel.value) return
  try {
    const resp = await apiListModels()
    const updated = resp.find(m => m.slug === currentModel.value.slug)
    if (updated) {
      currentModel.value = updated
      const idx = models.value.findIndex(m => m.slug === currentModel.value.slug)
      if (idx >= 0) models.value[idx] = updated
    }
  } catch (e) { console.error(e) }
}

onMounted(() => { loadModels(); loadDevices() })
</script>

<style scoped>
.model-mgmt-page { padding: 0; }

.top-toolbar {
  background: #ffffff; padding: 12px 16px; border-radius: 8px; border: 1px solid #e5e7eb;
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;
}
.toolbar-left, .toolbar-right { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }

/* 硬件组/模块分类 Tab 样式 */
.group-tab-bar {
  display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap;
}
.group-tab-item {
  background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px;
  padding: 8px 16px; font-size: 13px; font-weight: 600; color: #4b5563;
  display: flex; align-items: center; gap: 8px; cursor: pointer;
  transition: all 0.2s ease; box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}
.group-tab-item:hover {
  border-color: #3b82f6; color: #2563eb; transform: translateY(-1px);
}
.group-tab-item.active {
  background: #111827; color: #60a5fa; border-color: #1f2937;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}
.group-tab-emoji { font-size: 14px; }
.group-tab-label { flex: 1; }
.group-tab-count {
  background: rgba(96, 165, 250, 0.15); color: #3b82f6; border-radius: 12px;
  padding: 2px 8px; font-size: 11px; font-weight: 700;
}
.group-tab-item.active .group-tab-count {
  background: rgba(96, 165, 250, 0.25); color: #93c5fd;
}

.custom-table { background: #ffffff; border-radius: 8px; cursor: pointer; width: 100%; }
.device-config-tags { display: flex; flex-wrap: wrap; gap: 3px; }

/* 操作列横排布局 */
.dc-action-row {
  display: flex;
  gap: 6px;
  align-items: center;
  justify-content: center;
}

/* 命令行 Pill */
.cmd-pill-trigger {
  background: #111827; color: #60a5fa; border-radius: 6px; padding: 5px 10px;
  font-family: monospace; font-size: 11px; display: inline-flex; align-items: center;
  gap: 8px; cursor: pointer; width: 100%; transition: all 0.2s ease;
}
.cmd-pill-trigger:hover { background: #1f2937; color: #93c5fd; }
.cmd-text-ellipsis {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  flex: 1; min-width: 0;
}
.cmd-copy-icon { font-size: 13px; color: #9ca3af; flex-shrink: 0; }

.popover-cmd-box { background: #111827; padding: 12px; border-radius: 8px; color: #e5e7eb; }
.popover-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; border-bottom: 1px solid #1f2937; padding-bottom: 6px; }
.popover-title { font-size: 13px; font-weight: 700; color: #60a5fa; }

.cmd-block-pretty {
  background: #030712; color: #38bdf8; padding: 10px 12px; border-radius: 6px;
  font-family: monospace; font-size: 11px; line-height: 1.6; max-height: 260px;
  overflow-y: auto; white-space: pre-wrap; word-break: break-all; margin: 0;
}
</style>

<style>
/* 模型表格选中行高亮（非 scoped） */
.custom-table .selected-row td {
  background: #eff6ff !important;
}
</style>
