<template>
  <div class="reports-page">
    <!-- 顶部统一 CRUD 操作工具栏 -->
    <div class="top-toolbar">
      <div class="toolbar-left">
        <el-button type="primary" :disabled="selectedReports.length !== 1" @click="viewReportSelected(selectedReports[0])">
          <el-icon><View /></el-icon> 查看报告
        </el-button>
        <el-button type="success" plain @click="exportSummaryCSV">
          <el-icon><Download /></el-icon> 导出汇总 CSV
        </el-button>
        <el-button type="warning" plain :disabled="selectedReports.length < 2" @click="compareSelectedReportsInTable">
          <el-icon><DataAnalysis /></el-icon> 对比选中报告 ({{ selectedReports.length }})
        </el-button>
        <el-button
          v-if="selectedReports.length > 0"
          type="danger"
          plain
          @click="confirmDeleteSelectedReports"
        >
          <el-icon><Delete /></el-icon> 批量删除 ({{ selectedReports.length }})
        </el-button>
      </div>

      <div class="toolbar-right">
        <el-select v-model="filterDeviceId" placeholder="按设备筛选" clearable style="width:200px" @change="loadReports">
          <el-option v-for="d in devices" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
        <el-button circle @click="loadReports"><el-icon><Refresh /></el-icon></el-button>
      </div>
    </div>


    <!-- 顶部多模型深度基准对比控制台 -->
    <div class="charts-section">
      <div class="compare-control-bar">
        <div class="control-group">
          <span class="control-label">自选对比模型:</span>
          <el-select
            v-model="compareModelSlugs"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="默认对比全部已测试模型"
            clearable
            style="width: 320px"
          >
            <el-option v-for="m in availableModelOptions" :key="m.slug" :label="m.name" :value="m.slug" />
          </el-select>
        </div>

        <div class="control-group">
          <span class="control-label">测试并发:</span>
          <el-radio-group v-model="compareConcurrency" size="small">
            <el-radio-button :label="1">并发 1</el-radio-button>
            <el-radio-button :label="4">并发 4</el-radio-button>
            <el-radio-button :label="8">并发 8</el-radio-button>
            <el-radio-button :label="16">并发 16</el-radio-button>
          </el-radio-group>
        </div>

        <div class="control-group">
          <span class="control-label">生成场景:</span>
          <el-radio-group v-model="compareOutputType" size="small">
            <el-radio-button label="short">128 (短生成)</el-radio-button>
            <el-radio-button label="long">512 (长生成)</el-radio-button>
          </el-radio-group>
        </div>

        <div class="control-actions">
          <el-button type="primary" size="small" @click="triggerCompareChart">
            <el-icon><DataAnalysis /></el-icon> 生成对比看板
          </el-button>
          <el-button size="small" plain @click="resetCompare">
            <el-icon><RefreshRight /></el-icon> 重置
          </el-button>
        </div>
      </div>

      <el-row :gutter="16">
        <!-- 1. 吞吐量对比 -->
        <el-col :span="9">
          <div class="chart-card">
            <div class="chart-header">
              <span class="chart-title">模型 Token 吞吐量对比 (Tokens/s)</span>
            </div>
            <v-chart class="chart-box" :option="throughputChartOption" :autoresize="true" />
          </div>
        </el-col>

        <!-- 2. 首字延迟对比 -->
        <el-col :span="8">
          <div class="chart-card">
            <div class="chart-header">
              <span class="chart-title">首字响应延迟 (TTFT ms)</span>
            </div>
            <v-chart class="chart-box" :option="ttftChartOption" :autoresize="true" />
          </div>
        </el-col>

        <!-- 3. Token 间隔耗时与连贯度 -->
        <el-col :span="7">
          <div class="chart-card">
            <div class="chart-header">
              <span class="chart-title">🌊 Token 生成间隔 (Inter-Token Latency ms/tok)</span>
            </div>
            <v-chart class="chart-box" :option="itlChartOption" :autoresize="true" />
          </div>
        </el-col>
      </el-row>
    </div>

    <!-- 报告列表与细分数据 Tabs -->
    <el-tabs v-model="activeTab" class="custom-tabs">
      <el-tab-pane label="测试报告列表" name="list">
        <el-table
          ref="tableRef"
          :data="reports"
          v-loading="loading"
          stripe
          border
          @selection-change="handleSelectionChange"
          @row-click="handleRowClick"
          @row-dblclick="(row) => viewReportSelected(row)"
          class="custom-table"
        >
          <el-table-column type="selection" width="50" align="center" />
          <el-table-column prop="id" label="报告ID" width="70" align="center" />
          <el-table-column label="所属任务" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <span style="font-weight:600;color:#2563eb">#{{ row.task_id }}</span> {{ row.task_name || '已归档任务' }}
            </template>
          </el-table-column>
          <el-table-column prop="model_name" label="测试模型" min-width="190" show-overflow-tooltip />
          <el-table-column label="执行设备" width="160">
            <template #default="{ row }">
              <el-tag size="small" type="info">🖥️ {{ row.device_name || 'Jetson Thor' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="所属用户" width="100" align="center">
            <template #default="{ row }">
              <el-tag size="small" type="primary" effect="plain">
                👤 {{ row.username || 'admin' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status === 'done' ? 'success' : 'info'" size="small">{{ row.status.toUpperCase() }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="性能用例" width="95" align="center">
            <template #default="{ row }">
              <el-tag size="small" type="primary" effect="plain">{{ row.perf_results_count }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="准确率用例" width="100" align="center">
            <template #default="{ row }">
              <el-tag size="small" type="warning" effect="plain">{{ row.acc_results_count }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="完成时间" width="180">
            <template #default="{ row }">{{ formatTime(row.completed_at) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="吞吐量排行榜" name="tput">
        <el-table :data="throughputData" stripe border>
          <el-table-column type="index" label="排名" width="60" align="center" />
          <el-table-column prop="model_name" label="模型" min-width="200" />
          <el-table-column prop="concurrency" label="并发" width="70" align="center" />
          <el-table-column prop="throughput_tok_s" label="吞吐量 (tok/s)" width="150">
            <template #default="{ row }">
              <strong style="color:#10b981">{{ row.throughput_tok_s?.toFixed(1) }}</strong>
            </template>
          </el-table-column>
          <el-table-column prop="mean_ttft_ms" label="首字延迟 Mean (ms)" width="160">
            <template #default="{ row }">{{ row.mean_ttft_ms?.toFixed(1) }}</template>
          </el-table-column>
          <el-table-column prop="p99_ttft_ms" label="P99 TTFT (ms)" width="140">
            <template #default="{ row }">{{ row.p99_ttft_ms?.toFixed(1) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="准确率排行榜" name="acc">
        <div style="margin-bottom:12px;display:flex;align-items:center;gap:12px">
          <span style="font-size:13px;color:#4b5563;font-weight:600">选择数据集:</span>
          <el-select v-model="accDataset" style="width:160px">
            <el-option label="MMLU" value="mmlu" />
            <el-option label="C-Eval" value="ceval" />
            <el-option label="GSM8K" value="gsm8k" />
            <el-option label="ARC" value="arc" />
          </el-select>
        </div>
        <el-table :data="accuracyData" stripe border>
          <el-table-column type="index" label="排名" width="60" align="center" />
          <el-table-column prop="model_name" label="模型" min-width="200" />
          <el-table-column prop="dataset" label="数据集" width="100" />
          <el-table-column prop="accuracy" label="准确率 Score" width="140">
            <template #default="{ row }">
              <strong style="color:#2563eb">{{ (row.accuracy * 100).toFixed(2) }}%</strong>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, watch, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { apiListReports, apiDeleteReport, apiCompareThroughput, apiCompareAccuracy } from '../api'
import { formatTime } from '../utils/format'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import { useAuthStore } from '../stores/authStore'
import { useDragSelect } from '../utils/dragSelect'

use([CanvasRenderer, BarChart, LineChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent])

const authStore = useAuthStore()

const router = useRouter()
const tableRef = ref(null)
const activeTab = ref('list')
const reports = ref([])
const devices = ref([])
const selectedReports = ref([])
const filterDeviceId = ref(null)
const loading = ref(false)
const throughputData = ref([])
const accuracyData = ref([])
const accDataset = ref('mmlu')

useDragSelect(tableRef, reports)

const handleSelectionChange = (val) => {
  selectedReports.value = val
}

const handleRowClick = (row) => {
  if (tableRef.value) {
    tableRef.value.toggleRowSelection(row)
  }
}

const viewReportSelected = (target) => {
  const item = target || (selectedReports.value.length === 1 ? selectedReports.value[0] : null)
  if (item) {
    router.push(`/reports/${item.id}`)
  }
}

const exportSummaryCSV = () => {
  const targetList = selectedReports.value.length > 0 ? selectedReports.value : reports.value
  if (!targetList || targetList.length === 0) return ElMessage.warning("暂无可用测试报告数据导出")

  let csvContent = "data:text/csv;charset=utf-8,\uFEFF"
  csvContent += "报告ID,所属任务ID,任务名称,测试模型,执行节点,测试账号,状态,性能用例数,准确率用例数,开始时间,完成时间\n"

  targetList.forEach(r => {
    const row = [
      r.id,
      r.task_id,
      `"${(r.task_name || '').replace(/"/g, '""')}"`,
      `"${(r.model_name || '').replace(/"/g, '""')}"`,
      `"${(r.device_name || 'Jetson Thor').replace(/"/g, '""')}"`,
      `"${(r.username || 'admin').replace(/"/g, '""')}"`,
      r.status,
      r.perf_results_count || 0,
      r.acc_results_count || 0,
      `"${r.started_at || ''}"`,
      `"${r.completed_at || ''}"`
    ]
    csvContent += row.join(",") + "\n"
  })

  const encodedUri = encodeURI(csvContent)
  const link = document.createElement("a")
  link.setAttribute("href", encodedUri)
  link.setAttribute("download", `AONI_Reports_Summary_${new Date().toISOString().slice(0,10)}.csv`)
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  ElMessage.success(`已导出 ${targetList.length} 份测试报告的汇总 CSV 数据！`)
}

const downloadReportSelected = (target) => {
  const item = target || (selectedReports.value.length === 1 ? selectedReports.value[0] : null)
  if (!item) return
  const link = document.createElement('a')
  link.href = `/api/reports/${item.id}/download`
  link.download = `${item.model_slug}_report.md`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

const handleSingleDelete = async (report) => {
  try {
    await apiDeleteReport(report.id)
    await loadReports()
    ElMessage.success('报告已删除')
  } catch (e) {
    ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

const confirmDeleteSelectedReports = () => {
  if (selectedReports.value.length === 0) return
  ElMessageBox.confirm(
    `确定要永久删除选中的 ${selectedReports.value.length} 份测试报告吗？此操作不可撤销！`,
    '危险删除确认',
    {
      confirmButtonText: '确认永久删除',
      cancelButtonText: '取消',
      type: 'warning',
      center: true,
    }
  ).then(() => {
    handleBatchDelete()
  }).catch(() => {})
}

const handleBatchDelete = async () => {
  if (selectedReports.value.length === 0) return
  loading.value = true
  try {
    for (const r of selectedReports.value) {
      await apiDeleteReport(r.id)
    }
    selectedReports.value = []
    await loadReports()
    ElMessage.success('选中的测试报告已成功删除')
  } catch (e) {
    ElMessage.error('批量删除失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

const compareModelSlugs = ref([])
const compareConcurrency = ref(8)
const compareOutputType = ref('short')

const triggerCompareChart = () => {
  const count = compareModelSlugs.value.length || availableModelOptions.value.length
  ElMessage.success(`已生成 ${count} 个模型的同框对比看板！`)
}

const resetCompare = () => {
  compareModelSlugs.value = []
  compareConcurrency.value = 8
  compareOutputType.value = 'short'
  ElMessage.info('已重置对比条件')
}

const compareSelectedReportsInTable = () => {
  if (selectedReports.value.length < 2) {
    ElMessage.warning('请至少在表格中勾选 2 份测试报告进行对比')
    return
  }
  const slugs = Array.from(new Set(selectedReports.value.map(r => r.model_slug).filter(Boolean)))
  compareModelSlugs.value = slugs
  window.scrollTo({ top: 0, behavior: 'smooth' })
  ElMessage.success(`已提取表格勾选的 ${slugs.length} 个模型，成功生成对比看板！`)
}

const availableModelOptions = computed(() => {
  const map = new Map()
  ;(reports.value || []).forEach(r => {
    if (r.model_slug && !map.has(r.model_slug)) {
      map.set(r.model_slug, { slug: r.model_slug, name: r.model_name || r.model_slug })
    }
  })
  return Array.from(map.values())
})

const filteredPerfData = computed(() => {
  let list = throughputData.value || []
  if (compareModelSlugs.value.length > 0) {
    list = list.filter(d => compareModelSlugs.value.includes(d.model_slug))
  }
  return list
})

const throughputChartOption = computed(() => {
  const topData = (filteredPerfData.value || []).slice(0, 8).reverse()
  const modelNames = topData.map(d => d.model_name || 'Unknown')
  const tputs = topData.map(d => d.throughput_tok_s ? parseFloat(d.throughput_tok_s.toFixed(1)) : 0)

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '12%', bottom: '3%', top: '4%', containLabel: true },
    xAxis: { type: 'value', name: 'tok/s', splitLine: { lineStyle: { type: 'dashed', color: '#E5E7EB' } } },
    yAxis: { type: 'category', data: modelNames, axisLabel: { fontSize: 11, color: '#374151' } },
    series: [
      {
        name: '吞吐量 (tok/s)',
        type: 'bar',
        data: tputs,
        itemStyle: {
          borderRadius: [0, 4, 4, 0],
          color: {
            type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
            colorStops: [{ offset: 0, color: '#3B82F6' }, { offset: 1, color: '#10B981' }]
          }
        },
        label: { show: true, position: 'right', formatter: '{c} tok/s', fontSize: 10, color: '#10B981', fontWeight: 'bold' }
      }
    ]
  }
})

const ttftChartOption = computed(() => {
  const topData = (filteredPerfData.value || []).slice(0, 6)
  const modelNames = topData.map(d => (d.model_name || '').substring(0, 12))
  const meanTtft = topData.map(d => d.mean_ttft_ms ? parseFloat(d.mean_ttft_ms.toFixed(1)) : 0)
  const p99Ttft = topData.map(d => d.p99_ttft_ms ? parseFloat(d.p99_ttft_ms.toFixed(1)) : 0)

  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Mean TTFT', 'P99 TTFT'], top: '0%', textStyle: { fontSize: 10 } },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '18%', containLabel: true },
    xAxis: { type: 'category', data: modelNames, axisLabel: { fontSize: 10, rotate: 15 } },
    yAxis: { type: 'value', name: 'ms' },
    series: [
      { name: 'Mean TTFT', type: 'bar', data: meanTtft, itemStyle: { color: '#6366F1' } },
      { name: 'P99 TTFT', type: 'bar', data: p99Ttft, itemStyle: { color: '#EC4899' } }
    ]
  }
})

const itlChartOption = computed(() => {
  const topData = (filteredPerfData.value || []).slice(0, 6)
  const modelNames = topData.map(d => (d.model_name || '').substring(0, 12))
  // 计算 Inter-Token Latency (ms/tok) = 1000 / Throughput
  const itls = topData.map(d => {
    if (d.throughput_tok_s && d.throughput_tok_s > 0) {
      return parseFloat((1000 / d.throughput_tok_s).toFixed(2))
    }
    return 0
  })

  return {
    tooltip: { trigger: 'axis', formatter: '{b}<br/>Token 生成间隔: <b>{c} ms/tok</b>' },
    grid: { left: '3%', right: '5%', bottom: '3%', top: '12%', containLabel: true },
    xAxis: { type: 'category', data: modelNames, axisLabel: { fontSize: 10, rotate: 15 } },
    yAxis: { type: 'value', name: 'ms/tok' },
    series: [
      {
        name: 'Inter-Token Latency',
        type: 'line',
        smooth: true,
        data: itls,
        symbolSize: 6,
        itemStyle: { color: '#F59E0B' },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [{ offset: 0, color: 'rgba(245, 158, 11, 0.4)' }, { offset: 1, color: 'rgba(245, 158, 11, 0.05)' }]
          }
        },
        label: { show: true, position: 'top', formatter: '{c}ms', fontSize: 10, color: '#D97706' }
      }
    ]
  }
})

const loadReports = async () => {
  loading.value = true
  try {
    const params = filterDeviceId.value ? { device_id: filterDeviceId.value } : {}
    reports.value = await apiListReports(params)
  } catch (e) {
    console.error(e)
    ElMessage.error('加载测试报告列表失败: ' + (e.response?.data?.detail || e.message))
  }
  loading.value = false
}

const loadCompare = async () => {
  try {
    throughputData.value = await apiCompareThroughput()
    accuracyData.value = await apiCompareAccuracy(accDataset.value)
  } catch (e) { console.error(e) }
}

watch(accDataset, () => { apiCompareAccuracy(accDataset.value).then(r => accuracyData.value = r) })

onMounted(async () => {
  try { devices.value = (await axios.get('/api/devices')).data } catch (e) { /* */ }
  await loadReports(); await loadCompare()
})
</script>

<style scoped>
.reports-page { padding: 0; }

.top-toolbar {
  background: #ffffff; padding: 12px 16px; border-radius: 8px; border: 1px solid #e5e7eb;
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;
}
.toolbar-left, .toolbar-right { display: flex; gap: 10px; align-items: center; }

.charts-section { margin-bottom: 16px; }
.compare-control-bar {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 16px;
  margin-bottom: 12px;
  display: flex;
  gap: 20px;
  align-items: center;
  flex-wrap: wrap;
}
.control-group { display: flex; align-items: center; gap: 8px; }
.control-label { font-size: 12px; font-weight: 700; color: #475569; }

.chart-card { background: #ffffff; border-radius: 10px; border: 1px solid #e5e7eb; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.chart-header { margin-bottom: 10px; }
.chart-title { font-size: 13px; font-weight: 700; color: #111827; }
.chart-box { height: 260px; width: 100%; }

.custom-tabs { background: #ffffff; padding: 16px; border-radius: 10px; border: 1px solid #e5e7eb; }
.custom-table { cursor: pointer; }
</style>

<style>
.custom-table .selected-row td {
  background: #eff6ff !important;
}
</style>
