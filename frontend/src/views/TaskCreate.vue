<template>
  <div class="task-create-page">
    <h3>创建测试任务</h3>

    <el-form :model="form" label-width="140px" style="max-width: 800px;">
      <el-divider content-position="left">基本信息</el-divider>
      <el-form-item label="任务名称" required>
        <el-input v-model="form.name" placeholder="例如: Qwen系列模型测试" />
      </el-form-item>
      <el-form-item label="测试 Profile">
        <el-select v-model="form.profile" @change="handleProfileChange">
          <el-option label="完整测试 (性能+准确率)" value="full" />
          <el-option label="仅性能测试" value="perf" />
          <el-option label="仅准确率测试" value="accuracy" />
          <el-option label="快速冒烟" value="quick" />
          <el-option label="自定义" value="custom" />
        </el-select>
      </el-form-item>
      <el-form-item label="目标设备">
        <el-select v-model="form.device_id" placeholder="选择执行设备" clearable style="width:100%">
          <el-option
            v-for="d in onlineDevices"
            :key="d.id"
            :label="`${d.name} (${d.host})`"
            :value="d.id"
          >
            <span>{{ d.name }}</span>
            <el-tag size="small" type="success" style="margin-left:8px">在线</el-tag>
            <span style="color:#909399;margin-left:4px">{{ d.host }}</span>
          </el-option>
        </el-select>
        <div style="color:#909399;font-size:12px;margin-top:4px">
          仅显示在线设备，离线设备不可选
        </div>
      </el-form-item>

      <el-divider content-position="left">选择模型</el-divider>
      <el-form-item label="测试模型">
        <el-select
          v-model="form.config.model_slugs"
          multiple
          filterable
          collapse-tags
          collapse-tags-tooltip
          :max-collapse-tags="3"
          placeholder="请选择需要测试的模型"
          style="width: 100%"
        >
          <el-option-group :label="`PASS 模型 (${passModels.length})`">
            <el-option
              v-for="m in passModels"
              :key="m.slug"
              :label="`#${m.idx} ${m.name}`"
              :value="m.slug"
            >
              <span>#{{ m.idx }} {{ m.name }}</span>
              <el-tag size="small" type="info" style="margin-left:8px">{{ m.size_category }}</el-tag>
            </el-option>
          </el-option-group>
        </el-select>
        <div style="margin-top:8px">
          <el-button size="small" @click="form.config.model_slugs = passModels.map(m => m.slug)">
            全选 PASS ({{ passModels.length }})
          </el-button>
          <el-button size="small" @click="form.config.model_slugs = []">清空</el-button>
        </div>
      </el-form-item>

      <el-divider content-position="left">性能测试配置</el-divider>
      <el-form-item label="启用性能测试">
        <el-switch v-model="form.config.perf_enabled" />
      </el-form-item>
      <template v-if="form.config.perf_enabled">
        <!-- 多轮策略列表 -->
        <div v-for="(round, index) in form.config.perf_rounds_config" :key="index" style="margin-bottom:16px">
          <el-card shadow="hover">
            <template #header>
              <div style="display:flex;justify-content:space-between;align-items:center">
                <span><b>第 {{ index + 1 }} 轮</b></span>
                <el-button
                  v-if="form.config.perf_rounds_config.length > 1"
                  type="danger" size="small" text
                  @click="removePerfRound(index)"
                >
                  <el-icon><Delete /></el-icon> 删除
                </el-button>
              </div>
            </template>

            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="输入长度" label-width="90px">
                  <el-input v-model.number="round.input_len" size="small" placeholder="512" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="输出长度" label-width="90px">
                  <el-input v-model="round.output_lens_str" size="small" placeholder="逗号分隔, 如: 128,512" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="并发梯度" label-width="90px">
                  <el-input v-model="round.concurrencies_str" size="small" placeholder="逗号分隔, 留空=默认策略" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="请求数量" label-width="90px">
                  <el-input v-model.number="round.num_prompts" size="small" placeholder="300" />
                </el-form-item>
              </el-col>
            </el-row>

            <div style="color:#909399;font-size:12px">
              预计用例: {{ calcRoundTests(round) }} 条 ({{ parseOutputLens(round).length }} 输出类型 × {{ parseConcurrencies(round).length }} 并发)
            </div>
          </el-card>
        </div>

        <el-form-item>
          <el-button type="primary" plain @click="addPerfRound">
            <el-icon><Plus /></el-icon> 添加一轮策略
          </el-button>
        </el-form-item>

        <el-form-item label="">
          <el-alert type="info" :closable="false" show-icon>
            <template #title>
              预计每模型性能测试用例总数: <b>{{ estimatedPerfTests }}</b> 条 (共 {{ form.config.perf_rounds_config.length }} 轮)
            </template>
          </el-alert>
        </el-form-item>
      </template>

      <el-divider content-position="left">准确率测试配置</el-divider>
      <el-form-item label="启用准确率测试">
        <el-switch v-model="form.config.acc_enabled" />
      </el-form-item>
      <template v-if="form.config.acc_enabled">
        <el-form-item label="评测数据集">
          <el-checkbox-group v-model="form.config.acc_datasets">
            <el-checkbox label="mmlu" value="mmlu">MMLU (57学科)</el-checkbox>
            <el-checkbox label="ceval" value="ceval">C-Eval (中文)</el-checkbox>
            <el-checkbox label="gsm8k" value="gsm8k">GSM8K (数学)</el-checkbox>
            <el-checkbox label="arc" value="arc">ARC-Challenge</el-checkbox>
            <el-checkbox label="humaneval" value="humaneval">HumanEval (代码)</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="抽样数量">
          <el-input v-model.number="form.config.acc_limit" placeholder="200" />
        </el-form-item>
      </template>

      <el-divider content-position="left">容器配置 (可选)</el-divider>
      <el-form-item label="容器端口">
        <el-input v-model.number="form.config.container_port" placeholder="8300" />
      </el-form-item>
      <el-form-item label="自定义 Docker 命令">
        <el-input
          v-model="form.config.docker_command"
          type="textarea"
          :rows="4"
          placeholder="保留为空则使用 CSV 中配置的命令"
        />
      </el-form-item>

      <el-form-item>
        <el-button type="primary" @click="handleCreate" :loading="creating">创建并执行</el-button>
        <el-button @click="$router.back()">取消</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { apiListModels, apiCreateTask } from '../api'
import axios from 'axios'

const router = useRouter()
const models = ref([])
const devices = ref([])
const creating = ref(false)

function makeDefaultRound() {
  return {
    input_len: 512,
    output_lens_str: '128,512',
    concurrencies_str: '',
    num_prompts: 300,
  }
}

const form = reactive({
  name: '',
  profile: 'full',
  device_id: null,
  config: {
    model_slugs: [],
    perf_enabled: true,
    perf_rounds_config: [makeDefaultRound()],
    acc_enabled: true,
    acc_datasets: ['mmlu', 'ceval', 'gsm8k', 'arc'],
    acc_limit: 200,
    container_port: 8300,
    container_startup_timeout: 7200,
    docker_command: '',
  },
})

const onlineDevices = computed(() =>
  devices.value.filter(d => d.status === 'online')
)

// 只有 PASS 模型才能在任务中选择
const passModels = computed(() =>
  models.value.filter(m => m.status === 'PASS')
)

function parseOutputLens(round) {
  return (round.output_lens_str || '').split(',').map(Number).filter(v => v > 0)
}

function parseConcurrencies(round) {
  return (round.concurrencies_str || '').split(',').map(Number).filter(v => v > 0)
}

function calcRoundTests(round) {
  const ol = parseOutputLens(round).length
  const cc = parseConcurrencies(round).length || 5  // 默认 5 级并发
  return ol * cc
}

function addPerfRound() {
  form.config.perf_rounds_config.push(makeDefaultRound())
}

function removePerfRound(index) {
  form.config.perf_rounds_config.splice(index, 1)
}

const estimatedPerfTests = computed(() => {
  let total = 0
  for (const r of form.config.perf_rounds_config) {
    total += calcRoundTests(r)
  }
  return total
})

const handleProfileChange = (profile) => {
  if (profile === 'quick') {
    form.config.perf_enabled = true
    form.config.perf_rounds_config = [{ input_len: 512, output_lens_str: '128', concurrencies_str: '1,4', num_prompts: 100 }]
    form.config.acc_enabled = false
  } else if (profile === 'perf') {
    form.config.perf_enabled = true
    form.config.perf_rounds_config = [makeDefaultRound()]
    form.config.acc_enabled = false
  } else if (profile === 'accuracy') {
    form.config.perf_enabled = false
    form.config.acc_enabled = true
  } else if (profile === 'full') {
    form.config.perf_enabled = true
    form.config.acc_enabled = true
    form.config.perf_rounds_config = [makeDefaultRound()]
  }
}

const handleCreate = async () => {
  if (!form.name) return ElMessage.warning('请输入任务名称')
  creating.value = true
  try {
    const payload = {
      name: form.name,
      profile: form.profile,
      device_id: form.device_id,
      config: { ...form.config },
    }
    const task = await apiCreateTask(payload)
    ElMessage.success('任务已创建，开始执行')
    router.push(`/task/${task.id}`)
  } catch (e) {
    ElMessage.error('创建失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    creating.value = false
  }
}

onMounted(async () => {
  try { models.value = await apiListModels() } catch (e) { console.error(e) }
  try { devices.value = (await axios.get('/api/devices')).data } catch (e) { /* 静默 */ }
})
</script>

<style scoped>
.task-create-page { padding: 0; max-width: 900px; }
.task-create-page h3 { margin-bottom: 20px; font-size: 16px; }
</style>
