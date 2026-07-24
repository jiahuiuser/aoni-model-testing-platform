<template>
  <div class="report-detail-page">
    <el-page-header @back="$router.push('/reports')" :content="report?.model_name || '报告详情'" />

    <el-card v-if="report" style="margin-top:16px">
      <template #header>
        <span>#{{ report.model_idx }} {{ report.model_name }}</span>
        <el-tag style="margin-left:12px" :type="report.status === 'done' ? 'success' : 'info'" size="small">{{ report.status }}</el-tag>
      </template>

      <h4>性能测试结果</h4>
      <div ref="perfChart" style="width:100%;height:350px;margin-bottom:24px;" v-if="perfResultByOutput.length > 0" />

      <el-table :data="report.perf_results" stripe size="small" v-if="report.perf_results?.length">
        <el-table-column prop="round_num" label="轮次" width="50" />
        <el-table-column prop="output_type" label="输出类型" width="80" />
        <el-table-column prop="concurrency" label="并发" width="60" />
        <el-table-column prop="input_len" label="输入" width="60" />
        <el-table-column prop="output_len" label="输出" width="60" />
        <el-table-column label="吞吐(tok/s)" width="120">
          <template #default="{ row }">{{ row.throughput_tok_s?.toFixed(1) || '-' }}</template>
        </el-table-column>
        <el-table-column label="TTFT均值(ms)" width="120">
          <template #default="{ row }">{{ row.mean_ttft_ms?.toFixed(1) || '-' }}</template>
        </el-table-column>
        <el-table-column label="P99 TTFT(ms)" width="120">
          <template #default="{ row }">{{ row.p99_ttft_ms?.toFixed(1) || '-' }}</template>
        </el-table-column>
        <el-table-column label="TPOT均值(ms)" width="120">
          <template #default="{ row }">{{ row.mean_tpot_ms?.toFixed(1) || '-' }}</template>
        </el-table-column>
        <el-table-column label="P99 TPOT(ms)" width="120">
          <template #default="{ row }">{{ row.p99_tpot_ms?.toFixed(1) || '-' }}</template>
        </el-table-column>
        <el-table-column prop="error" label="错误" min-width="150" />
      </el-table>

      <h4 style="margin-top:24px">准确率测试结果</h4>
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

const perfResultByOutput = computed(() => {
  if (!report.value?.perf_results) return []
  const groups = {}
  for (const r of report.value.perf_results) {
    const key = r.output_type
    if (!groups[key]) groups[key] = []
    groups[key].push(r)
  }
  return Object.entries(groups).map(([type, data]) => ({
    type,
    data: data
      .filter(r => r.concurrency != null)
      .sort((a, b) => a.concurrency - b.concurrency),
  }))
})

const renderPerfChart = () => {
  if (!perfChart.value || perfResultByOutput.value.length === 0) return
  const chart = echarts.init(perfChart.value)
  const series = perfResultByOutput.value.map(g => ({
    name: g.type === 'short' ? '短输出 (128 tokens)' : '长输出 (512 tokens)',
    type: 'line',
    smooth: true,
    data: g.data.map(r => [r.concurrency, +(r.throughput_tok_s || 0).toFixed(0)]),
  }))
  chart.setOption({
    title: { text: '吞吐量 vs 并发数', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0 },
    xAxis: { type: 'value', name: '并发数', nameLocation: 'middle', nameGap: 28 },
    yAxis: { type: 'value', name: 'tok/s' },
    series,
  })
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
