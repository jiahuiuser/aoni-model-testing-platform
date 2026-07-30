<template>
  <div class="data-mgmt-page">
    <div class="page-header">
      <div>
        <h2>数据管理</h2>
        <p class="subtitle">管理性能测试矩阵用例模板与准确率基准数据集</p>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="custom-tabs">
      <!-- Tab 1: 测试用例模板管理 -->
      <el-tab-pane label="性能测试模板" name="templates">
        <!-- 顶部统一 CRUD 操作工具栏 -->
        <div class="top-toolbar">
          <div class="toolbar-left">
            <el-button type="primary" @click="openCreateTemplate">
              <el-icon><Plus /></el-icon> 创建测试模板
            </el-button>
            <el-button
              type="warning"
              plain
              :disabled="selectedTemplates.length !== 1"
              @click="openEditTemplate(selectedTemplates[0])"
            >
              <el-icon><Edit /></el-icon> 编辑测试模板
            </el-button>
            <el-button
              type="success"
              plain
              :disabled="selectedTemplates.length !== 1"
              @click="exportCSV(selectedTemplates[0])"
            >
              <el-icon><Download /></el-icon> 导出模板 CSV
            </el-button>
            <el-button
              v-if="selectedTemplates.length > 0"
              type="danger"
              plain
              @click="confirmDeleteSelectedTemplates"
            >
              <el-icon><Delete /></el-icon> 批量删除 ({{ selectedTemplates.length }})
            </el-button>
          </div>
          <div class="toolbar-right">
            <el-button circle @click="loadTemplates"><el-icon><Refresh /></el-icon></el-button>
          </div>
        </div>

        <el-table
          ref="templateTableRef"
          :data="templates"
          stripe
          border
          style="width: 100%"
          @selection-change="handleTemplateSelectionChange"
          @row-click="handleTemplateRowClick"
          class="custom-table"
        >
          <el-table-column type="selection" width="50" align="center" />
          <el-table-column prop="id" label="ID" width="60" align="center" />
          <el-table-column prop="name" label="模板名称" min-width="180">
            <template #default="{ row }">
              <b style="color:#2563eb;">{{ row.name }}</b>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="说明描述" min-width="200" show-overflow-tooltip />
          <el-table-column label="并发梯度" min-width="180">
            <template #default="{ row }">
              <el-tag size="small" v-for="c in row.concurrencies" :key="c" type="info" style="margin-right:4px;">{{ c }}并发</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Token 长度 (In / Out)" width="180">
            <template #default="{ row }">
              <code>{{ (row.input_lens || []).join('/') }} in | {{ (row.output_lens || []).join('/') }} out</code>
            </template>
          </el-table-column>
          <el-table-column label="关联数据集" min-width="160">
            <template #default="{ row }">
              <el-tag size="small" v-for="d in row.datasets" :key="d" type="success" style="margin-right:4px;">{{ d }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- Tab 2: 准确率数据集管理 -->
      <el-tab-pane label="准确率数据集" name="datasets">
        <!-- 顶部统一 CRUD 操作与难度切片过滤工具栏 -->
        <div class="top-toolbar">
          <div class="toolbar-left" style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
            <el-radio-group v-model="difficultyFilter" size="default" @change="loadDatasets">
              <el-radio-button value="all">全部难度</el-radio-button>
              <el-radio-button value="ultra">极高难度 (300B+旗舰)</el-radio-button>
              <el-radio-button value="hard">高难度进阶</el-radio-button>
              <el-radio-button value="standard">基础通用</el-radio-button>
            </el-radio-group>

            <el-button type="success" @click="showDownloadDialog = true">
              <el-icon><Connection /></el-icon> 在线同步数据集
            </el-button>
            <el-button
              type="info"
              plain
              :disabled="selectedDatasets.length !== 1"
              @click="previewDatasetSamples(selectedDatasets[0])"
            >
              <el-icon><View /></el-icon> 样例数据预览
            </el-button>
            <el-button
              type="primary"
              plain
              :disabled="selectedDatasets.length !== 1"
              @click="reDownload(selectedDatasets[0])"
            >
              <el-icon><RefreshRight /></el-icon> 重新同步
            </el-button>
          </div>
          <div class="toolbar-right">
            <el-button circle @click="loadDatasets"><el-icon><Refresh /></el-icon></el-button>
          </div>
        </div>

        <el-table
          ref="datasetTableRef"
          :data="filteredDatasets"
          stripe
          border
          style="width: 100%"
          @selection-change="handleDatasetSelectionChange"
          @row-click="handleDatasetRowClick"
          class="custom-table"
        >
          <el-table-column type="selection" width="50" align="center" />
          <el-table-column prop="name" label="数据集标识" width="150">
            <template #default="{ row }">
              <b style="color:#2563eb; font-size: 14px;">{{ row.name.toUpperCase() }}</b>
            </template>
          </el-table-column>
          <el-table-column label="难度等级" width="160" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.difficulty === 'ultra'" type="danger" effect="dark" size="small" style="font-weight:600;">
                极高难度 (300B+)
              </el-tag>
              <el-tag v-else-if="row.difficulty === 'hard'" type="warning" effect="light" size="small" style="font-weight:600;">
                高难度进阶
              </el-tag>
              <el-tag v-else type="info" size="small">
                基础通用
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="category_group" label="分类领域" width="130" align="center">
            <template #default="{ row }">
              <el-tag type="primary" plain size="small">{{ row.category_group || '通用基准' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="source" label="来源仓库/模型" width="220" show-overflow-tooltip />
          <el-table-column label="样本总量" width="120" align="center">
            <template #default="{ row }">
              <el-tag type="info" size="small">{{ row.sample_count }} 条记录</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="就绪状态" width="110" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status === 'ready' ? 'success' : 'warning'" size="small">
                {{ row.status === 'ready' ? '已就绪' : '下载中' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="功能说明与定位" min-width="260" />
          <el-table-column label="操作" width="140" align="center">
            <template #default="{ row }">
              <el-button size="small" type="info" plain @click.stop="previewDatasetSamples(row)">查看样本</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 新增/修改模板 Dialog -->
    <el-dialog v-model="showTplDialog" :title="editingTplId ? '修改用例模板' : '创建用例模板'" width="620px">
      <el-form :model="tplForm" label-width="120px">
        <el-form-item label="模板名称">
          <el-input v-model="tplForm.name" placeholder="请输入用例模板名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="tplForm.description" type="textarea" placeholder="说明用例矩阵适用场景" />
        </el-form-item>
        <el-form-item label="并发梯度">
          <el-input v-model="concurrenciesStr" placeholder="以逗号分隔，如: 1, 4, 8, 16, 32" />
        </el-form-item>
        <el-form-item label="输入 Token Length">
          <el-input v-model="inputLensStr" placeholder="如: 128, 512, 1024" />
        </el-form-item>
        <el-form-item label="输出 Token Length">
          <el-input v-model="outputLensStr" placeholder="如: 128, 512" />
        </el-form-item>
        <el-form-item label="测试数据集">
          <el-checkbox-group v-model="tplForm.datasets">
            <div style="font-weight:600; color:#dc2626; margin-bottom:4px; font-size:12px;">300B+ 极高难度评测集：</div>
            <div style="display:flex; gap:8px; margin-bottom:8px; flex-wrap:wrap;">
              <el-checkbox label="aime24">aime24 (AIME竞赛数学)</el-checkbox>
              <el-checkbox label="arena_hard">arena_hard (Arena对战)</el-checkbox>
              <el-checkbox label="gpqa">gpqa (博士级问答)</el-checkbox>
            </div>
            <div style="font-weight:600; color:#d97706; margin-bottom:4px; font-size:12px;">高难度进阶数据集：</div>
            <div style="display:flex; gap:8px; margin-bottom:8px; flex-wrap:wrap;">
              <el-checkbox label="math500">math500</el-checkbox>
              <el-checkbox label="bigcodebench">bigcodebench</el-checkbox>
              <el-checkbox label="longbench_pro">longbench_pro</el-checkbox>
            </div>
            <div style="font-weight:600; color:#4b5563; margin-bottom:4px; font-size:12px;">基础通用数据集：</div>
            <div style="display:flex; gap:8px; flex-wrap:wrap;">
              <el-checkbox label="mmlu">mmlu</el-checkbox>
              <el-checkbox label="ceval">ceval</el-checkbox>
              <el-checkbox label="gsm8k">gsm8k</el-checkbox>
              <el-checkbox label="arc">arc</el-checkbox>
              <el-checkbox label="humaneval">humaneval</el-checkbox>
            </div>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showTplDialog = false">取消</el-button>
        <el-button type="primary" @click="saveTemplate">保存模板</el-button>
      </template>
    </el-dialog>

    <!-- 联网下载数据集 Dialog -->
    <el-dialog v-model="showDownloadDialog" title="联网在线下载评测数据集" width="500px">
      <el-form :model="downloadForm" label-width="110px">
        <el-form-item label="数据集标号">
          <el-input v-model="downloadForm.name" placeholder="例如: mmlu, ceval, gsm8k" />
        </el-form-item>
        <el-form-item label="来源 Repo ID">
          <el-input v-model="downloadForm.source" placeholder="ModelScope/evalscope_mmlu" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDownloadDialog = false">取消</el-button>
        <el-button type="success" :loading="downloading" @click="submitDownloadDataset">开始联网下载</el-button>
      </template>
    </el-dialog>

    <!-- 全量数据集题库查阅与预览 Dialog -->
    <el-dialog v-model="showSampleDialog" :title="`数据集 [${previewDatasetName.toUpperCase()}] 全量题库查阅 (全库共 ${totalSampleCount} 条)`" width="820px" top="6vh">
      <div class="sample-filter-bar">
        <el-input
          v-model="sampleSearch"
          placeholder="搜索题目关键词 / 选项 / 答案..."
          clearable
          style="width: 260px;"
          @clear="fetchDatasetSamples(1)"
          @keyup.enter="fetchDatasetSamples(1)"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>

        <el-select
          v-model="sampleCategory"
          placeholder="筛选学科/子分类"
          clearable
          style="width: 240px; margin-left: 10px;"
          @change="fetchDatasetSamples(1)"
        >
          <el-option v-for="c in sampleCategories" :key="c" :label="c" :value="c" />
        </el-select>

        <el-button type="primary" plain style="margin-left: 10px;" @click="fetchDatasetSamples(1)">
          搜索筛选
        </el-button>
      </div>

      <div v-loading="loadingSamples" style="max-height: 480px; overflow-y: auto; padding: 6px 4px; margin-top: 10px;">
        <div v-if="sampleList.length === 0" class="empty-tip">
          无匹配的题目样本数据
        </div>
        <div v-for="item in sampleList" :key="item.id" class="sample-item-card">
          <div class="sample-header">
            <el-tag size="small" type="primary" effect="dark">题目 ID: #{{ item.id }}</el-tag>
            <el-tag size="small" type="info" style="margin-left: 8px;">{{ item.category }}</el-tag>
          </div>
          <div class="sample-question">
            <b>题目:</b> {{ item.question }}
          </div>
          <div v-if="item.options && item.options.length" class="sample-options">
            <div v-for="opt in item.options" :key="opt" class="opt-line">{{ opt }}</div>
          </div>
          <div class="sample-target">
            <el-tag type="success" size="small" effect="dark">标准正确答案: {{ item.target }}</el-tag>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="dialog-footer-bar">
          <el-pagination
            v-model:current-page="samplePage"
            v-model:page-size="samplePageSize"
            :page-sizes="[10, 20, 50, 100]"
            :total="totalSampleCount"
            layout="total, sizes, prev, pager, next, jumper"
            @current-change="onSamplePageChange"
            @size-change="onSamplePageSizeChange"
          />
          <el-button type="primary" @click="showSampleDialog = false">关闭</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'
import { useDragSelect } from '../utils/dragSelect'

const templateTableRef = ref(null)
const datasetTableRef = ref(null)

const activeTab = ref('templates')
const templates = ref([])
const datasets = ref([])
const selectedTemplates = ref([])
const selectedDatasets = ref([])

const difficultyFilter = ref('all')

const filteredDatasets = computed(() => {
  if (!difficultyFilter.value || difficultyFilter.value === 'all') {
    return datasets.value
  }
  return datasets.value.filter(d => d.difficulty === difficultyFilter.value)
})

useDragSelect(templateTableRef, templates)
useDragSelect(datasetTableRef, datasets)

const handleTemplateSelectionChange = (val) => {
  selectedTemplates.value = val
}

const handleTemplateRowClick = (row) => {
  if (templateTableRef.value) {
    templateTableRef.value.toggleRowSelection(row)
  }
}

const handleDatasetSelectionChange = (val) => {
  selectedDatasets.value = val
}

const handleDatasetRowClick = (row) => {
  if (datasetTableRef.value) {
    datasetTableRef.value.toggleRowSelection(row)
  }
}

const showTplDialog = ref(false)
const editingTplId = ref(null)
const tplForm = ref({
  name: '',
  description: '',
  num_prompts: 300,
  datasets: ['mmlu', 'ceval'],
  acc_limit: 200,
})
const concurrenciesStr = ref('1, 4, 8, 16, 32')
const inputLensStr = ref('128, 512, 1024')
const outputLensStr = ref('128, 512')

const showDownloadDialog = ref(false)
const downloading = ref(false)
const downloadForm = ref({
  name: '',
  source: 'ModelScope/evalscope_mmlu',
})

const loadTemplates = async () => {
  try {
    const res = await api.get('/data/templates')
    templates.value = res.data
  } catch (err) {
    ElMessage.error('加载模板列表失败')
  }
}

const loadDatasets = async () => {
  try {
    const res = await api.get('/data/datasets')
    datasets.value = res.data
  } catch (err) {
    ElMessage.error('加载数据集失败')
  }
}

const openCreateTemplate = () => {
  editingTplId.value = null
  tplForm.value = { name: '', description: '', num_prompts: 300, datasets: ['mmlu', 'ceval'], acc_limit: 200 }
  concurrenciesStr.value = '1, 4, 8, 16, 32'
  inputLensStr.value = '128, 512'
  outputLensStr.value = '128, 512'
  showTplDialog.value = true
}

const openEditTemplate = (tpl) => {
  if (!tpl) return
  editingTplId.value = tpl.id
  tplForm.value = {
    name: tpl.name,
    description: tpl.description,
    num_prompts: tpl.num_prompts,
    datasets: tpl.datasets || ['mmlu'],
    acc_limit: tpl.acc_limit || 200,
  }
  concurrenciesStr.value = (tpl.concurrencies || []).join(', ')
  inputLensStr.value = (tpl.input_lens || []).join(', ')
  outputLensStr.value = (tpl.output_lens || []).join(', ')
  showTplDialog.value = true
}

const saveTemplate = async () => {
  if (!tplForm.value.name.trim()) return ElMessage.warning('请填写模板名称')
  const concurrencies = concurrenciesStr.value.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n))
  const input_lens = inputLensStr.value.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n))
  const output_lens = outputLensStr.value.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n))

  const payload = {
    ...tplForm.value,
    concurrencies,
    input_lens,
    output_lens,
  }

  try {
    if (editingTplId.value) {
      await api.put(`/data/templates/${editingTplId.value}`, payload)
      ElMessage.success('模板更新成功')
    } else {
      await api.post('/data/templates', payload)
      ElMessage.success('用例模板创建成功')
    }
    showTplDialog.value = false
    loadTemplates()
  } catch (err) {
    ElMessage.error('保存失败')
  }
}

const deleteTemplate = (id) => {
  ElMessageBox.confirm('确认删除该用例模板？', '提示', { type: 'warning' }).then(async () => {
    await api.delete(`/data/templates/${id}`)
    ElMessage.success('已删除')
    loadTemplates()
  })
}

const confirmDeleteSelectedTemplates = () => {
  if (selectedTemplates.value.length === 0) return
  ElMessageBox.confirm(
    `确定要永久删除选中的 ${selectedTemplates.value.length} 个测试模板吗？此操作不可撤销！`,
    '危险删除确认',
    {
      confirmButtonText: '确认永久删除',
      cancelButtonText: '取消',
      type: 'warning',
      center: true,
    }
  ).then(() => {
    handleBatchDeleteTemplates()
  }).catch(() => {})
}

const handleBatchDeleteTemplates = async () => {
  try {
    for (const tpl of selectedTemplates.value) {
      await api.delete(`/data/templates/${tpl.id}`)
    }
    ElMessage.success(`已删除选中的 ${selectedTemplates.value.length} 个模板`)
    selectedTemplates.value = []
    loadTemplates()
  } catch (err) {
    ElMessage.error('批量删除失败')
  }
}

const exportCSV = (tpl) => {
  if (!tpl) return
  window.open(`/api/data/templates/${tpl.id}/export-csv`, '_blank')
}

const submitDownloadDataset = async () => {
  if (!downloadForm.value.name) return ElMessage.warning('请输入数据集标号')
  downloading.value = true
  try {
    await api.post('/data/datasets/download', downloadForm.value)
    ElMessage.success('数据集已加载成功')
    showDownloadDialog.value = false
    loadDatasets()
  } catch (err) {
    ElMessage.error('网络下载失败')
  } finally {
    downloading.value = false
  }
}

const showSampleDialog = ref(false)
const loadingSamples = ref(false)
const previewDatasetName = ref('')
const sampleList = ref([])
const totalSampleCount = ref(0)
const samplePage = ref(1)
const samplePageSize = ref(10)
const sampleSearch = ref('')
const sampleCategory = ref('')
const sampleCategories = ref([])

const previewDatasetSamples = (row) => {
  if (!row) return
  previewDatasetName.value = row.name
  sampleSearch.value = ''
  sampleCategory.value = ''
  showSampleDialog.value = true
  fetchDatasetSamples(1)
}

const fetchDatasetSamples = async (p = 1) => {
  if (!previewDatasetName.value) return
  samplePage.value = p
  loadingSamples.value = true
  try {
    const params = {
      page: samplePage.value,
      page_size: samplePageSize.value,
    }
    if (sampleSearch.value.trim()) params.search = sampleSearch.value.trim()
    if (sampleCategory.value) params.category = sampleCategory.value

    const res = await api.get(`/data/datasets/${previewDatasetName.value}/samples`, { params })
    sampleList.value = res.data.samples || []
    totalSampleCount.value = res.data.total || 0
    sampleCategories.value = res.data.categories || []
  } catch (err) {
    ElMessage.error('获取数据集题目失败')
  } finally {
    loadingSamples.value = false
  }
}

const onSamplePageChange = (p) => {
  fetchDatasetSamples(p)
}

const onSamplePageSizeChange = (sz) => {
  samplePageSize.value = sz
  fetchDatasetSamples(1)
}

const reDownload = (row) => {
  if (!row) return
  downloadForm.value = { name: row.name, source: row.source }
  submitDownloadDataset()
}

onMounted(() => {
  loadTemplates()
  loadDatasets()
})
</script>

<style scoped>
.data-mgmt-page { padding: 20px; }
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

.sample-filter-bar {
  display: flex;
  align-items: center;
  background: #f1f5f9;
  padding: 10px 14px;
  border-radius: 8px;
}

.empty-tip {
  text-align: center;
  color: #94a3b8;
  padding: 40px 0;
  font-size: 13px;
}

.sample-item-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
}
.sample-header { display: flex; align-items: center; margin-bottom: 8px; }
.sample-question { font-size: 13px; color: #0f172a; line-height: 1.6; margin-bottom: 8px; white-space: pre-wrap; font-family: monospace, sans-serif; }
.sample-options { background: #ffffff; border-radius: 6px; padding: 8px 12px; border: 1px solid #cbd5e1; margin-bottom: 8px; }
.opt-line { font-size: 12px; color: #334155; line-height: 1.5; font-family: monospace, sans-serif; }
.sample-target { display: flex; justify-content: flex-end; }

.dialog-footer-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}
</style>
