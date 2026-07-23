<template>
  <div class="reports-page">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <h3>测试报告</h3>
      <el-select v-model="filterDeviceId" placeholder="筛选设备" clearable style="width:200px" @change="loadReports">
        <el-option v-for="d in devices" :key="d.id" :label="d.name" :value="d.id" />
      </el-select>
    </div>

    <el-tabs v-model="activeTab" style="margin-top:16px">
      <el-tab-pane label="报告列表" name="list">
        <el-table :data="reports" v-loading="loading" stripe>
          <el-table-column prop="model_idx" label="#" width="50" />
          <el-table-column prop="model_name" label="模型" min-width="200" />
          <el-table-column prop="model_slug" label="Slug" width="150" />
          <el-table-column label="设备" width="120">
            <template #default="{ row }">{{ row.device_name || '-' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.status === 'done' ? 'success' : 'info'" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="性能用例" width="80">
            <template #default="{ row }">{{ row.perf_results_count }}</template>
          </el-table-column>
          <el-table-column label="准确率用例" width="100">
            <template #default="{ row }">{{ row.acc_results_count }}</template>
          </el-table-column>
          <el-table-column label="时间" width="180">
            <template #default="{ row }">{{ formatTime(row.completed_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="200">
            <template #default="{ row }">
              <el-button size="small" @click="$router.push(`/reports/${row.id}`)">查看</el-button>
              <el-button size="small" @click="downloadReport(row)">
                <el-icon><Download /></el-icon>
              </el-button>
              <el-popconfirm title="确定删除？" @confirm="handleDelete(row.id)">
                <template #reference>
                  <el-button size="small" type="danger">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="吞吐排名" name="tput">
        <el-table :data="throughputData" stripe>
          <el-table-column type="index" label="排名" width="60" />
          <el-table-column prop="model_name" label="模型" min-width="200" />
          <el-table-column prop="concurrency" label="并发" width="60" />
          <el-table-column prop="throughput_tok_s" label="吞吐 (tok/s)" width="150">
            <template #default="{ row }">{{ row.throughput_tok_s?.toFixed(1) }}</template>
          </el-table-column>
          <el-table-column prop="mean_ttft_ms" label="TTFT (ms)" width="120">
            <template #default="{ row }">{{ row.mean_ttft_ms?.toFixed(1) }}</template>
          </el-table-column>
          <el-table-column prop="p99_ttft_ms" label="P99 TTFT (ms)" width="130">
            <template #default="{ row }">{{ row.p99_ttft_ms?.toFixed(1) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="准确率排名" name="acc">
        <el-select v-model="accDataset" style="margin-bottom:12px">
          <el-option label="MMLU" value="mmlu" />
          <el-option label="C-Eval" value="ceval" />
          <el-option label="GSM8K" value="gsm8k" />
          <el-option label="ARC" value="arc" />
          <el-option label="HumanEval" value="humaneval" />
        </el-select>
        <el-table :data="accuracyData" stripe>
          <el-table-column type="index" label="排名" width="60" />
          <el-table-column prop="model_name" label="模型" min-width="200" />
          <el-table-column prop="dataset" label="数据集" width="100" />
          <el-table-column prop="accuracy" label="准确率" width="120">
            <template #default="{ row }">{{ (row.accuracy * 100).toFixed(2) }}%</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { apiListReports, apiDeleteReport, apiCompareThroughput, apiCompareAccuracy } from '../api'
import axios from 'axios'

const activeTab = ref('list')
const reports = ref([])
const devices = ref([])
const filterDeviceId = ref(null)
const loading = ref(false)
const throughputData = ref([])
const accuracyData = ref([])
const accDataset = ref('mmlu')

const formatTime = (t) => t ? new Date(t).toLocaleString() : '-'

const loadReports = async () => {
  loading.value = true
  try {
    const params = filterDeviceId.value ? { device_id: filterDeviceId.value } : {}
    reports.value = await apiListReports(params)
  } catch (e) { console.error(e) }
  loading.value = false
}

const handleDelete = async (id) => {
  try { await apiDeleteReport(id); await loadReports() } catch (e) { console.error(e) }
}

const downloadReport = (row) => {
  const link = document.createElement('a')
  link.href = `/api/reports/${row.id}/download`
  link.download = `${row.model_slug}_report.md`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
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
.reports-page h3 { font-size: 16px; }
</style>
