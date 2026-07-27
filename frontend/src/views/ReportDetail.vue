<template>
  <div class="report-detail-page">
    <el-page-header @back="$router.push('/reports')" :content="report?.model_name || '报告详情'" />

    <el-card v-if="report" style="margin-top:16px">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div>
            <span style="font-weight:bold;font-size:16px;">#{{ report.model_idx }} {{ report.model_name }}</span>
            <el-tag style="margin-left:12px" :type="report.status === 'done' ? 'success' : 'info'" size="small">{{ report.status }}</el-tag>
          </div>
          <el-alert type="info" :closable="false" show-icon style="padding:4px 12px;max-width:520px;">
            <template #title>
              <span style="font-size:12px;">💡 点击表格任意数据行，图表将自动高亮定位对应并发与矩阵指标。</span>
            </template>
          </el-alert>
        </div>
      </template>

      <h4>性能矩阵测试结果 (吞吐量 vs 并发数)</h4>
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
</style>

