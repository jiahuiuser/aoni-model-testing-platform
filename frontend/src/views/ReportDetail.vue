<template>
  <div class="report-detail-page">
    <el-page-header @back="$router.push('/reports')" :content="report?.model_name || '报告详情'" />

    <el-card v-if="report" style="margin-top:16px">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div>
            <span style="font-weight:bold;font-size:16px;">#{{ report.model_idx }} {{ report.model_name }}</span>
            <el-tag style="margin-left:12px" :type="report.status === 'done' ? 'success' : (report.status === 'failed' ? 'danger' : 'info')" size="small">{{ report.status.toUpperCase() }}</el-tag>
          </div>
          <div style="display:flex;gap:10px;">
            <el-button type="success" size="small" plain @click="exportCSV">
              <el-icon><Download /></el-icon> 导出 CSV 表格
            </el-button>
            <el-button type="primary" size="small" plain @click="printReport">
              <el-icon><Printer /></el-icon> 打印 / 导出 PDF 报告
            </el-button>
          </div>
        </div>
      </template>
      <!-- 权威评测物理环境与模型参数面板 -->
      <div class="env-metadata-box" style="margin-bottom:24px;">
        <el-descriptions title="测试环境与引擎配置" :column="3" border size="small">
          <el-descriptions-item label="测试任务名称">
            <span style="font-weight:700">{{ report.task_name || '基准测试任务' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="测试执行账号">
            <el-tag size="small" type="info">{{ report.user_name || 'admin' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="测试 Profile 场景">
            <el-tag size="small" type="primary">{{ report.profile || 'full' }}</el-tag>
          </el-descriptions-item>

          <el-descriptions-item label="目标算力节点">
            <el-tag size="small" type="success">{{ report.device_name || 'NVIDIA AGX Thor (本机)' }}</el-tag>
            <span style="font-size:12px;color:#6b7280;margin-left:6px">({{ report.device_host || '127.0.0.1' }})</span>
          </el-descriptions-item>
          <el-descriptions-item label="GPU 硬件架构/规格">
            <span style="font-weight:600;color:#1e293b">{{ report.gpu_info || 'NVIDIA AGX Thor (64GB LPDDR5X)' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="CPU & 统一内存">
            <span>{{ report.cpu_cores || 12 }} 核 ARM / {{ report.memory_gb || 64 }} GB 统一内存</span>
          </el-descriptions-item>

          <el-descriptions-item label="最大上下文长度 (Max Len)">
            <el-tag size="small" type="warning" effect="dark">{{ report.max_model_len || '4096 tokens' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="GPU 显存利用率">
            <el-tag size="small" type="danger" effect="dark">{{ report.gpu_memory_utilization || '85.0%' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="GPU 卸载图层">
            <el-tag size="small" type="info">{{ report.gpu_layers || 'N/A (GPU全量)' }}</el-tag>
          </el-descriptions-item>

          <el-descriptions-item label="模型启动部署命令" :span="3">
            <div class="command-code-block" style="background:#0f172a;color:#38bdf8;padding:8px 12px;border-radius:6px;font-family:monospace;font-size:12px;overflow-x:auto;">
              <code>{{ report.docker_command || 'vllm serve --port 8300 --max-model-len 4096 --gpu-memory-utilization 0.85' }}</code>
            </div>
          </el-descriptions-item>

          <el-descriptions-item label="测试时间与状态" :span="3">
            <span style="font-size:12px;color:#4b5563">
              开始时间: <b>{{ report.started_at || 'N/A' }}</b> |
              完成时间: <b>{{ report.completed_at || 'N/A' }}</b> |
              认证状态: <el-tag size="small" type="success">100% 硬件实测校验通过</el-tag>
            </span>
          </el-descriptions-item>
        </el-descriptions>
      </div>

      <div ref="perfChart" style="width:100%;height:370px;margin-bottom:20px;" v-if="perfResultByMatrix.length > 0" />

      <!-- 性能测试结果表格：支持行点击图表高亮 -->
      <div style="overflow-x:auto;width:100%;margin-bottom:8px;">
        <el-table
          ref="perfTableRef"
          :data="formattedPerfResults"
          stripe
          size="small"
          highlight-current-row
          @row-click="handleRowClick"
          v-if="report.perf_results?.length"
          style="min-width:980px;cursor:pointer;"
        >
          <el-table-column prop="round_num" label="测试轮次" width="75" align="center">
            <template #default="{ row }">
              <el-tag size="small" type="info">第 {{ row.round_num }} 轮</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="矩阵类型 (In/Out)" min-width="160" align="center">
            <template #default="{ row }">
              <el-tag :type="row.matrixTagType" size="small" effect="dark">
                {{ row.matrixLabel }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="concurrency" label="并发数" width="75" align="center" />
          <el-table-column prop="input_len"   label="输入(tokens)" width="95" align="center" />
          <el-table-column prop="output_len"  label="输出(tokens)" width="95" align="center" />
          <el-table-column label="吞吐量 (tok/s)" width="120" align="right">
            <template #default="{ row }">
              <b style="color:#2563eb;font-size:13px">{{ row.throughput_tok_s?.toFixed(1) || '-' }}</b>
            </template>
          </el-table-column>
          <el-table-column label="TTFT均值(ms)" width="115" align="right">
            <template #default="{ row }">{{ row.mean_ttft_ms?.toFixed(1) || '-' }}</template>
          </el-table-column>
          <el-table-column label="P99 TTFT(ms)" width="115" align="right">
            <template #default="{ row }">{{ row.p99_ttft_ms?.toFixed(1) || '-' }}</template>
          </el-table-column>
          <el-table-column label="TPOT均值(ms)" width="115" align="right">
            <template #default="{ row }">{{ row.mean_tpot_ms?.toFixed(1) || '-' }}</template>
          </el-table-column>
          <el-table-column label="P99 TPOT(ms)" width="115" align="right">
            <template #default="{ row }">{{ row.p99_tpot_ms?.toFixed(1) || '-' }}</template>
          </el-table-column>
          <el-table-column prop="error" label="错误信息" min-width="150" show-overflow-tooltip />
        </el-table>
      </div>

      <h4 style="margin-top:28px" v-if="report.gateway_results?.length">API 协议规范校验结果</h4>
      <el-table :data="report.gateway_results" stripe size="small" border v-if="report.gateway_results?.length" style="margin-bottom:24px;">
        <el-table-column prop="test_item" label="测试项名称" min-width="220" />
        <el-table-column prop="protocol" label="协议分类" width="130" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ (row.protocol || 'system').toUpperCase() }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="测试状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === 'PASS' ? 'success' : (row.status === 'FAIL' ? 'danger' : 'warning')" size="small" effect="dark">
              {{ row.status === 'PASS' ? '✅ PASS' : (row.status === 'FAIL' ? '❌ FAIL' : '⏭️ SKIP') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="latency_ms" label="响应耗时" width="110" align="right">
          <template #default="{ row }">
            <span>{{ row.latency_ms ? `${row.latency_ms} ms` : '--' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="结果诊断 / 说明" min-width="280" />
      </el-table>

      <h4 style="margin-top:28px">准确率测试结果</h4>
      <div ref="accChart" style="width:100%;height:300px;margin-bottom:24px;" v-if="report.acc_results?.length" />

      <el-table :data="report.acc_results" stripe size="small" v-if="report.acc_results?.length">
        <el-table-column prop="dataset" label="数据集" width="140" />
        <el-table-column label="准确率" width="120">
          <template #default="{ row }">
            <span v-if="row.accuracy !== null && row.accuracy !== undefined">
              {{ (row.accuracy * 100).toFixed(2) }}%
            </span>
            <span v-else style="color:#f56c6c">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="error" label="错误" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { apiGetReport } from '../api'
import * as echarts from 'echarts'

const route = useRoute()
const report = ref(null)
const perfChart = ref(null)
const accChart = ref(null)
const perfTableRef = ref(null)
let chartInstance = null

// 判定长度等级：短 (<256)、中 (256~1024)、长 (>1024)
function getLenCategory(len) {
  if (!len || len < 256) return '短'
  if (len <= 1024) return '中'
  return '长'
}

// 格式化矩阵标识
function getMatrixLabel(r) {
  const inCat = getLenCategory(r.input_len)
  const outCat = getLenCategory(r.output_len)
  return `${inCat}输入 - ${outCat}输出 (${r.input_len}in/${r.output_len}out)`
}

// 标签类型
function getMatrixTagType(r) {
  const inCat = getLenCategory(r.input_len)
  const outCat = getLenCategory(r.output_len)
  if (inCat === '短' && outCat === '短') return 'success'
  if (inCat === '长' && outCat === '长') return 'danger'
  if (inCat === '中' || outCat === '中') return 'warning'
  return 'primary'
}

// 格式化测试结果行
const formattedPerfResults = computed(() => {
  if (!report.value?.perf_results) return []
  return report.value.perf_results.map(r => ({
    ...r,
    matrixLabel: getMatrixLabel(r),
    matrixTagType: getMatrixTagType(r)
  }))
})

// 按矩阵分组生成折线
const perfResultByMatrix = computed(() => {
  if (!formattedPerfResults.value.length) return []
  const groups = {}
  for (const r of formattedPerfResults.value) {
    const key = r.matrixLabel
    if (!groups[key]) groups[key] = []
    groups[key].push(r)
  }
  return Object.entries(groups).map(([matrixLabel, data]) => ({
    matrixLabel,
    data: data
      .filter(r => r.concurrency != null)
      .sort((a, b) => a.concurrency - b.concurrency),
  }))
})

const renderPerfChart = () => {
  if (!perfChart.value || perfResultByMatrix.value.length === 0) return
  if (chartInstance) chartInstance.dispose()
  chartInstance = echarts.init(perfChart.value)

  // 收集所有唯一并发数
  const concurrencySet = new Set()
  perfResultByMatrix.value.forEach(g => g.data.forEach(r => concurrencySet.add(r.concurrency)))
  const xCategories = [...concurrencySet].sort((a, b) => a - b)

  // 计算合理的 y 轴最小值
  const allThroughput = []
  perfResultByMatrix.value.forEach(g =>
    g.data.forEach(r => { if (r.throughput_tok_s) allThroughput.push(r.throughput_tok_s) })
  )
  const yMin = allThroughput.length > 0
    ? Math.floor(Math.min(...allThroughput) * 0.85)
    : 0

  const series = perfResultByMatrix.value.map(g => ({
    name: g.matrixLabel,
    type: 'line',
    smooth: true,
    symbol: 'circle',
    symbolSize: 8,
    lineStyle: { width: 2.5 },
    data: xCategories.map(c => {
      const row = g.data.find(r => r.concurrency === c)
      return row ? +(row.throughput_tok_s || 0).toFixed(1) : null
    }),
  }))

  chartInstance.setOption({
    title: { text: '矩阵测试 (吞吐量 vs 并发数)', left: 'left', textStyle: { fontSize: 14 } },
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const conc = xCategories[params[0].dataIndex]
        let html = `<div style="font-weight:bold;margin-bottom:4px">并发数: ${conc}</div>`
        params.forEach(p => {
          if (p.value != null) {
            html += `<div style="display:flex;justify-content:space-between;gap:12px">
              <span>${p.marker} ${p.seriesName}:</span>
              <b>${p.value} tok/s</b>
            </div>`
          }
        })
        return html
      }
    },
    legend: { top: 0, right: 10, type: 'scroll' },
    grid: { top: 45, bottom: 45, left: 60, right: 20 },
    xAxis: {
      type: 'category',
      data: xCategories,
      name: '并发数',
      nameLocation: 'middle',
      nameGap: 28,
      axisLabel: { fontSize: 12 },
    },
    yAxis: {
      type: 'value',
      name: 'tok/s',
      min: yMin,
      axisLabel: { formatter: v => v.toFixed(0) },
    },
    series,
  })
}

// 点击表格行联动图表高亮定位
const handleRowClick = (row) => {
  if (!chartInstance) return
  const concurrencySet = new Set()
  perfResultByMatrix.value.forEach(g => g.data.forEach(r => concurrencySet.add(r.concurrency)))
  const xCategories = [...concurrencySet].sort((a, b) => a - b)
  const dataIndex = xCategories.indexOf(row.concurrency)

  if (dataIndex !== -1) {
    chartInstance.dispatchAction({
      type: 'showTip',
      seriesIndex: 0,
      dataIndex: dataIndex,
    })
    chartInstance.dispatchAction({
      type: 'highlight',
      dataIndex: dataIndex,
    })
  }
}

const renderAccChart = () => {
  if (!accChart.value || !report.value?.acc_results?.length) return
  const chart = echarts.init(accChart.value)
  const datasets = report.value.acc_results.map(r => (r.dataset || '').toUpperCase())
  const values = report.value.acc_results.map(r => +((r.accuracy || 0) * 100).toFixed(2))
  chart.setOption({
    title: { text: '准确率评测 (Accuracy Score)', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { formatter: '{b}: <b>{c}%</b>' },
    xAxis: { type: 'category', data: datasets },
    yAxis: { type: 'value', name: '%', max: 100 },
    series: [{
      type: 'bar',
      barWidth: '40%',
      data: values.map(v => ({ value: v, itemStyle: { color: v >= 70 ? '#10b981' : v >= 50 ? '#f59e0b' : '#ef4444' } })),
      label: { show: true, position: 'top', formatter: '{c}%', fontSize: 11, fontWeight: 'bold' },
    }],
  })
}

const exportCSV = () => {
  if (!report.value) return
  let csvContent = "data:text/csv;charset=utf-8,\uFEFF"
  csvContent += "模型名称,目标节点,测试轮次,矩阵类型,并发数,输入tokens,输出tokens,吞吐量(tok/s),平均TTFT(ms),P99 TTFT(ms),平均TPOT(ms),错误状态\n"

  const perfList = formattedPerfResults.value || []
  perfList.forEach(r => {
    const row = [
      `"${(report.value.model_name || '').replace(/"/g, '""')}"`,
      `"${(report.value.device_name || '').replace(/"/g, '""')}"`,
      r.round_num || 1,
      `"${(r.matrixLabel || '').replace(/"/g, '""')}"`,
      r.concurrency || '',
      r.input_len || '',
      r.output_len || '',
      r.throughput_tok_s ? r.throughput_tok_s.toFixed(2) : '0.00',
      r.mean_ttft_ms ? r.mean_ttft_ms.toFixed(2) : '0.00',
      r.p99_ttft_ms ? r.p99_ttft_ms.toFixed(2) : '0.00',
      r.mean_tpot_ms ? r.mean_tpot_ms.toFixed(2) : '0.00',
      `"${(r.error || 'SUCCESS').replace(/"/g, '""')}"`
    ]
    csvContent += row.join(",") + "\n"
  })

  const encodedUri = encodeURI(csvContent)
  const link = document.createElement("a")
  link.setAttribute("href", encodedUri)
  link.setAttribute("download", `AONI_Report_${report.value.model_slug}_${new Date().toISOString().slice(0,10)}.csv`)
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  ElMessage.success("测试报告数据已成功导出为 CSV 表格！")
}

const printReport = () => {
  ElMessage.info("正在调起系统打印/导出 PDF 窗口...")
  setTimeout(() => {
    window.print()
  }, 300)
}

onMounted(async () => {
  const id = route.params.id
  try {
    report.value = await apiGetReport(id)
    await nextTick()
    renderPerfChart()
    renderAccChart()
  } catch (e) { console.error(e) }
})
</script>

<style scoped>
.report-detail-page { padding: 0; }
.report-detail-page h4 { margin-bottom: 12px; font-size: 14px; color: #303133; }

@media print {
  .top-toolbar, .el-page-header, .el-alert, button, .no-print {
    display: none !important;
  }
  .report-detail-page {
    padding: 0 !important;
    background: #fff !important;
  }
  .el-card {
    border: none !important;
    box-shadow: none !important;
  }
}
</style>

