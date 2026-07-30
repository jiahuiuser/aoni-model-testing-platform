<template>
  <div class="task-create-page">
    <h3>{{ editId ? '编辑测试任务' : '创建测试任务' }}</h3>

    <el-form :model="form" label-width="140px" style="max-width: 800px;">
      <el-divider content-position="left">基本信息</el-divider>
      <el-form-item label="任务名称" required>
        <el-input v-model="form.name" placeholder="例如: Qwen系列模型测试" />
      </el-form-item>
      <el-form-item label="测试 Profile">
        <el-select v-model="form.profile" @change="handleProfileChange">
          <template v-if="isExternalModelSelected">
            <el-option label="全量测试 (API 协议 + 准确率)" value="gateway" />
            <el-option label="仅 API 协议规范校验" value="gateway" />
            <el-option label="仅准确率测试" value="accuracy" />
            <el-option label="自定义" value="custom" />
          </template>
          <template v-else>
            <el-option label="全量测试 (API 协议 + 性能 + 准确率)" value="full" />
            <el-option label="仅 API 协议规范校验" value="gateway" />
            <el-option label="仅性能测试" value="perf" />
            <el-option label="仅准确率测试" value="accuracy" />
            <el-option label="快速冒烟测试" value="quick" />
            <el-option label="自定义" value="custom" />
          </template>
        </el-select>
      </el-form-item>

      <!-- 矩阵用例模板 -->
      <el-form-item v-if="!isExternalModelSelected" label="矩阵用例模板">
        <el-select
          v-model="selectedTemplateIds"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="选择测试模板（支持多选自动展开矩阵压测）"
          clearable
          style="width:100%"
          @change="handleTemplateSelect"
        >
          <el-option v-for="t in templates" :key="t.id" :label="`${t.name} (并发: ${(t.concurrencies||[]).join('/')})`" :value="t.id" />
        </el-select>
      </el-form-item>

      <!-- 目标设备 -->
      <el-form-item v-if="!isAllExternalSelected" label="目标设备">
        <el-select v-model="form.device_ids" multiple placeholder="选择目标在线节点设备（支持多选）" clearable style="width:100%">
          <el-option
            v-for="d in availableTaskDevices"
            :key="d.id"
            :label="`${d.name} (${d.host})`"
            :value="d.id"
          >
            <span>{{ d.name }}</span>
            <el-tag size="small" type="success" style="margin-left:8px">已验证 PASS</el-tag>
            <span style="color:#909399;margin-left:4px">{{ d.host }}</span>
          </el-option>
        </el-select>
        <div style="color:#909399;font-size:12px;margin-top:4px">
          💡 多选设备将自动并发批量下发独立测试任务。
        </div>
      </el-form-item>

      <el-divider content-position="left">选择模型</el-divider>

      <!-- 外部 API 模型模式提示 -->
      <div v-if="isExternalModelSelected" style="margin-bottom:16px">
        <el-alert
          type="info"
          show-icon
          :closable="false"
        >
          <template #title>
            <b>外部 API 端点模型模式</b>
          </template>
          <template #default>
            已为您隐藏目标设备、硬件压测配置与高级部署配置，将专注于【API 协议规范校验】与【学科准确率】测试。
          </template>
        </el-alert>
      </div>

      <el-form-item label="测试模型">
        <el-select
          v-model="form.config.model_slugs"
          multiple
          filterable
          collapse-tags
          collapse-tags-tooltip
          :max-collapse-tags="3"
          placeholder="请选择测试模型"
          style="width: 100%"
        >
          <el-option-group
            v-for="group in modelsByGroup"
            :key="group.label"
            :label="`${group.label} (${group.models.length})`"
          >
            <el-option
              v-for="m in group.models"
              :key="m.slug"
              :label="`#${m.idx} ${m.name}`"
              :value="m.slug"
              :disabled="isModelDisabled(m)"
            >
              <div style="display:flex; justify-content:space-between; align-items:center; width:100%">
                <span>#{{ m.idx }} {{ m.name }}</span>
                <div>
                  <el-tag size="small" type="info">{{ m.size_category }}</el-tag>
                  <el-tag v-if="isModelDisabled(m)" size="small" type="warning" style="margin-left:6px">不可混选</el-tag>
                </div>
              </div>
            </el-option>
          </el-option-group>
        </el-select>
        <div style="margin-top:8px; display:flex; gap:8px;">
          <el-button
            size="small"
            :disabled="isExternalModelSelected"
            @click="form.config.model_slugs = passContainerModels.map(m => m.slug)"
          >
            全选已验证节点模型 ({{ passContainerModels.length }})
          </el-button>
          <el-button
            size="small"
            type="primary"
            plain
            :disabled="hasDeviceSelected"
            @click="form.config.model_slugs = passExternalModels.map(m => m.slug)"
          >
            全选外部 API 端点模型 ({{ passExternalModels.length }})
          </el-button>
          <el-button size="small" @click="form.config.model_slugs = []">清空</el-button>
        </div>

        <!-- 外部 API 端点配置预览提醒 -->
        <div v-if="selectedExternalModels.length > 0" style="margin-top: 10px;">
          <el-alert type="success" :closable="false" show-icon>
            <template #title>
              <span style="font-weight: 600;">已自动载入【模型管理】中的 API 端点与鉴权密钥：</span>
            </template>
            <template #default>
              <div v-for="m in selectedExternalModels" :key="m.slug" style="font-size: 12px; margin-top: 4px;">
                • <b>{{ m.name }}</b> ➜ 端点地址: <code>{{ m.api_base || '未设置' }}</code> | 鉴权密钥 (API Key): <code>{{ maskKey(m.api_key) }}</code> | 远程模型标识: <code>{{ m.model_endpoint_name || m.slug }}</code>
              </div>
            </template>
          </el-alert>
        </div>
      </el-form-item>

      <!-- API 协议规范校验配置 -->
      <template v-if="form.config.gateway_enabled || form.profile === 'custom'">
        <el-divider content-position="left">API 协议规范校验配置</el-divider>
        <el-form-item v-if="form.profile === 'custom'" label="API 协议规范校验">
          <el-switch v-model="form.config.gateway_enabled" />
        </el-form-item>
        <template v-if="form.config.gateway_enabled">
          <el-form-item label="校验协议规范">
            <el-checkbox-group v-model="form.config.gateway_protocols">
              <el-checkbox label="openai">OpenAI Chat Completions (/v1/chat/completions)</el-checkbox>
              <el-checkbox label="responses">OpenAI Responses (/v1/responses)</el-checkbox>
              <el-checkbox label="anthropic">Anthropic Messages (/v1/messages)</el-checkbox>
            </el-checkbox-group>
          </el-form-item>
          <el-form-item label="长上下文测试">
            <el-switch v-model="form.config.test_longctx" />
            <span style="margin-left:12px;color:#909399;font-size:12px">评估 85% max_model_len 上下文边界行为</span>
          </el-form-item>
        </template>
      </template>

      <!-- 性能测试配置 (仅硬件容器模型) -->
      <template v-if="!isExternalModelSelected && (form.config.perf_enabled || form.profile === 'custom')">
        <el-divider content-position="left">性能压测配置</el-divider>
        <el-form-item v-if="form.profile === 'custom'" label="启用性能测试">
          <el-switch v-model="form.config.perf_enabled" />
        </el-form-item>
        <template v-if="form.config.perf_enabled">
          <div v-for="(round, index) in form.config.perf_rounds_config" :key="index" style="margin-bottom:16px">
            <el-card shadow="hover">
              <template #header>
                <div style="display:flex;justify-content:space-between;align-items:center">
                  <span><b>第 {{ index + 1 }} 轮策略</b></span>
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
                  <el-form-item label="输入 Token" label-width="90px">
                    <el-input v-model.number="round.input_len" size="small" placeholder="512" />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="输出 Token" label-width="90px">
                    <el-input v-model="round.output_lens_str" size="small" placeholder="如: 128,512" />
                  </el-form-item>
                </el-col>
              </el-row>

              <el-row :gutter="12">
                <el-col :span="12">
                  <el-form-item label="并发梯度" label-width="90px">
                    <el-input v-model="round.concurrencies_str" size="small" placeholder="如: 1,4,8,16" />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="单轮请求数" label-width="90px">
                    <el-input v-model.number="round.num_prompts" size="small" placeholder="100" />
                  </el-form-item>
                </el-col>
              </el-row>

              <div style="color:#909399;font-size:12px;margin-top:4px">
                单轮包含 {{ calcRoundTests(round) }} 个测试项 ({{ parseOutputLens(round).length }} 输出场景 × {{ parseConcurrencies(round).length }} 并发梯度)
              </div>
            </el-card>
          </div>

          <el-form-item>
            <el-button type="primary" plain @click="addPerfRound">
              <el-icon><Plus /></el-icon> 添加压测策略
            </el-button>
          </el-form-item>

          <el-form-item label="">
            <el-alert type="info" :closable="false" show-icon>
              <template #title>
                性能测试项总计: <b>{{ estimatedPerfTests }}</b> 项（共 {{ form.config.perf_rounds_config.length }} 轮）
              </template>
            </el-alert>
          </el-form-item>
        </template>
      </template>

      <!-- 准确率测试配置 -->
      <template v-if="form.config.acc_enabled || form.profile === 'custom'">
        <el-divider content-position="left">准确率测试配置</el-divider>
        <el-form-item v-if="form.profile === 'custom'" label="准确率测试">
          <el-switch v-model="form.config.acc_enabled" />
        </el-form-item>
        <template v-if="form.config.acc_enabled">
          <el-form-item label="快捷选集预设">
            <div style="display:flex; gap:8px; flex-wrap:wrap;">
              <el-button size="small" type="danger" plain @click="selectUltraDatasets">
                全选 300B+ 极高难度评测集 (AIME24 / Arena-Hard / GPQA)
              </el-button>
              <el-button size="small" type="warning" plain @click="selectHardDatasets">
                全选高难度进阶集 (MATH-500 / BigCodeBench / LongBench Pro)
              </el-button>
              <el-button size="small" type="info" plain @click="selectStandardDatasets">
                全选基础通用基准
              </el-button>
              <el-button size="small" @click="form.config.acc_datasets = []">清空</el-button>
            </div>
          </el-form-item>

          <el-form-item label="测评数据集矩阵">
            <el-checkbox-group v-model="form.config.acc_datasets" style="width:100%;">
              <div style="background:#fef2f2; border:1px solid #fecaca; border-radius:6px; padding:10px 14px; margin-bottom:10px;">
                <div style="font-weight:600; color:#dc2626; margin-bottom:6px;">
                  300B+ 极高难度旗舰评测集 (高阶符号推演 & 博士级学术问答)
                </div>
                <div style="display:flex; gap:16px; flex-wrap:wrap;">
                  <el-checkbox label="aime24">AIME24 (竞赛级数学多步推演)</el-checkbox>
                  <el-checkbox label="arena_hard">Arena-Hard (Chatbot Arena 严苛 Prompt)</el-checkbox>
                  <el-checkbox label="gpqa">GPQA (Google-Proof 博士级学术问答)</el-checkbox>
                </div>
              </div>

              <div style="background:#fffbeb; border:1px solid #fde68a; border-radius:6px; padding:10px 14px; margin-bottom:10px;">
                <div style="font-weight:600; color:#d97706; margin-bottom:6px;">
                  高难度工程与逻辑进阶集
                </div>
                <div style="display:flex; gap:16px; flex-wrap:wrap;">
                  <el-checkbox label="math500">MATH-500 (高阶竞赛数学 Level 4-5)</el-checkbox>
                  <el-checkbox label="bigcodebench">BigCodeBench (复杂库调用代码生成)</el-checkbox>
                  <el-checkbox label="longbench_pro">LongBench Pro (8k-256k 真实长文本)</el-checkbox>
                </div>
              </div>

              <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:10px 14px;">
                <div style="font-weight:600; color:#475569; margin-bottom:6px;">
                  基础通用评测集
                </div>
                <div style="display:flex; gap:16px; flex-wrap:wrap;">
                  <el-checkbox label="mmlu">MMLU (多任务学科知识)</el-checkbox>
                  <el-checkbox label="ceval">C-Eval (中文综合推理)</el-checkbox>
                  <el-checkbox label="gsm8k">GSM8K (小学数学应用题)</el-checkbox>
                  <el-checkbox label="arc">ARC (科学常识推理)</el-checkbox>
                  <el-checkbox label="humaneval">HumanEval (Python 代码生成)</el-checkbox>
                </div>
              </div>
            </el-checkbox-group>
          </el-form-item>

          <el-form-item label="数据集抽样数">
            <el-input v-model.number="form.config.acc_limit" placeholder="200" style="width: 200px;" />
            <span style="color:#909399;font-size:12px;margin-left:8px">推荐 50~200 题 (高难度评测集建议 50~100 题)</span>
          </el-form-item>
        </template>
      </template>

      <el-divider content-position="left">邮件通知</el-divider>
      <el-form-item label="通知邮箱">
        <el-input v-model="form.config.notify_email" placeholder="输入接收通知邮箱" clearable />
        <div style="color:#909399;font-size:12px;margin-top:4px">
          💡 任务状态变更或测试完成时自动向该邮箱发送结果通知卡片。
        </div>
      </el-form-item>

      <!-- 高级配置 (仅本地/远程容器硬件模型展示，外部 API 端点模型模式下隐藏) -->
      <template v-if="!isExternalModelSelected">
        <el-divider content-position="left">高级配置</el-divider>
        <el-form-item label="服务部署端口">
          <el-input v-model.number="form.config.container_port" placeholder="默认 8300" />
        </el-form-item>
        <el-form-item label="显存占用上限">
          <el-input v-model="form.config.gpu_memory_utilization" placeholder="默认 0.8" />
        </el-form-item>
      </template>

      <el-form-item>
        <el-button type="primary" @click="handleSubmit" :loading="creating">
          {{ editId ? '保存修改' : '创建并执行' }}
        </el-button>
        <el-button @click="$router.back()">取消</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import api, { apiListModels, apiListDevices, apiCreateTask, apiUpdateTask, apiGetTask } from '../api'

const router = useRouter()
const route = useRoute()
const models = ref([])
const devices = ref([])
const creating = ref(false)
const editId = computed(() => route.query.edit ? parseInt(route.query.edit) : null)

function makeDefaultRound() {
  return {
    input_len: 512,
    output_lens_str: '128,512',
    concurrencies_str: '',
    num_prompts: 100,
  }
}

const templates = ref([])
const selectedTemplateIds = ref([])

const loadTemplates = async () => {
  try {
    const res = await api.get('/data/templates')
    templates.value = Array.isArray(res.data) ? res.data : []
  } catch (err) {
    console.error(err)
    templates.value = []
  }
}

const handleTemplateSelect = (tplIds) => {
  if (!tplIds || tplIds.length === 0) return
  const selectedList = templates.value.filter(t => tplIds.includes(t.id))
  if (selectedList.length === 0) return

  form.template_ids = [...tplIds]
  form.template_id = tplIds[0]

  // 将选择的每一个模板映射为一轮性能测试配置
  form.config.perf_rounds_config = selectedList.map(tpl => ({
    input_len: tpl.input_lens ? tpl.input_lens[0] : 512,
    output_lens_str: (tpl.output_lens || [128, 512]).join(','),
    concurrencies_str: (tpl.concurrencies || [1, 4, 8, 16, 32]).join(','),
    num_prompts: tpl.num_prompts || 300,
  }))

  // 收集融合所有模板的数据集
  const datasetSet = new Set()
  selectedList.forEach(tpl => {
    if (tpl.datasets) tpl.datasets.forEach(d => datasetSet.add(d))
  })
  if (datasetSet.size > 0) {
    form.config.acc_datasets = [...datasetSet]
  }

  const maxAccLimit = Math.max(...selectedList.map(t => t.acc_limit || 200))
  form.config.acc_limit = maxAccLimit

  ElMessage.success(`已成功应用 ${selectedList.length} 个测试模板的矩阵配置`)
}

const form = reactive({
  name: '',
  profile: 'full',
  device_id: null,
  device_ids: [],
  template_id: null,
  template_ids: [],
  config: {
    model_slugs: [],
    gateway_enabled: true,
    gateway_protocols: ['openai', 'anthropic', 'responses'],
    test_longctx: false,
    perf_enabled: true,
    perf_rounds_config: [makeDefaultRound()],
    acc_enabled: true,
    acc_datasets: ['mmlu', 'ceval', 'gsm8k', 'arc'],
    acc_limit: 200,
    notify_email: '',
    container_port: 8300,
    container_startup_timeout: 7200,
  },
})

const onlineDevices = computed(() =>
  (Array.isArray(devices.value) ? devices.value : []).filter(d => d && d.status === 'online')
)

// 针对所选模型仅展示已绑定且通过验证 (PASS) 的在线设备节点
const availableTaskDevices = computed(() => {
  const containerModels = selectedModelObjects.value.filter(m => m && !m.is_external && !m.api_base)
  if (containerModels.length === 0) {
    return onlineDevices.value
  }
  return onlineDevices.value.filter(d => {
    return containerModels.every(m => {
      if (!m.device_configs || m.device_configs.length === 0) {
        return m.status === 'PASS'
      }
      const dc = m.device_configs.find(c => c.device_id === d.id)
      return dc ? dc.status === 'PASS' : m.status === 'PASS'
    })
  })
})

// PASS 的容器模型以及所有已接入的外部 API 端点模型均可选择
const passModels = computed(() =>
  (Array.isArray(models.value) ? models.value : []).filter(m => m && (m.status === 'PASS' || Boolean(m.is_external) || Boolean(m.api_base)))
)

const passContainerModels = computed(() =>
  (Array.isArray(models.value) ? models.value : []).filter(m => m && m.status === 'PASS' && !m.is_external && !m.api_base)
)

const passExternalModels = computed(() =>
  (Array.isArray(models.value) ? models.value : []).filter(m => m && (m.status === 'PASS' || m.is_external || m.api_base) && (Boolean(m.is_external) || Boolean(m.api_base)))
)

const modelsByGroup = computed(() => {
  const groupsMap = {
    '外部API模型': { label: '外部 API 端点模型', models: [] },
    'NVIDIA_jetson_AGX_Thor': { label: 'NVIDIA AGX Thor', models: [] },
    '沐曦C500/N260': { label: '沐曦 C500 / N260', models: [] },
    '英伟达服务器': { label: 'NVIDIA GPU 服务器', models: [] },
  }
  
  passModels.value.forEach(m => {
    let g = m.group_name || 'NVIDIA_jetson_AGX_Thor'
    if (m.is_external || m.api_base) {
      g = '外部API模型'
    }
    if (!groupsMap[g]) {
      groupsMap[g] = { label: m.group_name || '其他硬件节点', models: [] }
    }
    groupsMap[g].models.push(m)
  })

  return Object.values(groupsMap).filter(g => g.models.length > 0)
})

const selectedModelObjects = computed(() => {
  const selectedSlugs = form.config.model_slugs || []
  return (Array.isArray(models.value) ? models.value : []).filter(m => m && selectedSlugs.includes(m.slug))
})

const selectedExternalModels = computed(() => {
  return selectedModelObjects.value.filter(m => Boolean(m.is_external) || Boolean(m.api_base))
})

const isExternalModelSelected = computed(() => {
  return selectedExternalModels.value.length > 0
})

const hasDeviceSelected = computed(() => {
  return selectedModelObjects.value.some(m => !m.is_external && !m.api_base)
})

function maskKey(key) {
  if (!key || key === 'EMPTY') return '未设置 (EMPTY)'
  if (key.length <= 8) return '******'
  return key.slice(0, 4) + '****' + key.slice(-4)
}

function isModelDisabled(m) {
  const selectedSlugs = form.config.model_slugs || []
  if (selectedSlugs.length === 0) return false
  const mIsExternal = Boolean(m.is_external) || Boolean(m.api_base)
  if (isExternalModelSelected.value && !mIsExternal) {
    return true
  }
  if (hasDeviceSelected.value && mIsExternal) {
    return true
  }
  return false
}

const isAllExternalSelected = computed(() => {
  return selectedModelObjects.value.length > 0 && selectedModelObjects.value.every(m => Boolean(m.is_external) || Boolean(m.api_base))
})

watch(isExternalModelSelected, (isExt) => {
  if (isExt) {
    form.config.perf_enabled = false
    if (form.profile === 'perf' || form.profile === 'full') {
      form.profile = 'gateway'
    }
    form.device_ids = []
    form.device_id = null
  }
})

function parseOutputLens(round) {
  return (round.output_lens_str || '').split(',').map(Number).filter(v => v > 0)
}

function parseConcurrencies(round) {
  return (round.concurrencies_str || '').split(',').map(Number).filter(v => v > 0)
}

const selectUltraDatasets = () => {
  const ultraKeys = ['aime24', 'arena_hard', 'gpqa']
  form.config.acc_datasets = Array.from(new Set([...(form.config.acc_datasets || []), ...ultraKeys]))
}

const selectHardDatasets = () => {
  const hardKeys = ['math500', 'bigcodebench', 'longbench_pro']
  form.config.acc_datasets = Array.from(new Set([...(form.config.acc_datasets || []), ...hardKeys]))
}

const selectStandardDatasets = () => {
  const stdKeys = ['mmlu', 'ceval', 'gsm8k', 'arc', 'humaneval']
  form.config.acc_datasets = Array.from(new Set([...(form.config.acc_datasets || []), ...stdKeys]))
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
  if (profile === 'gateway') {
    form.config.gateway_enabled = true
    form.config.perf_enabled = false
    form.config.acc_enabled = false
  } else if (profile === 'quick') {
    form.config.gateway_enabled = true
    form.config.perf_enabled = true
    form.config.perf_rounds_config = [{ input_len: 512, output_lens_str: '128', concurrencies_str: '1,4', num_prompts: 100 }]
    form.config.acc_enabled = false
  } else if (profile === 'perf') {
    form.config.gateway_enabled = false
    form.config.perf_enabled = true
    form.config.perf_rounds_config = [makeDefaultRound()]
    form.config.acc_enabled = false
  } else if (profile === 'accuracy') {
    form.config.gateway_enabled = false
    form.config.perf_enabled = false
    form.config.acc_enabled = true
  } else if (profile === 'full') {
    form.config.gateway_enabled = true
    form.config.perf_enabled = true
    form.config.acc_enabled = true
    form.config.perf_rounds_config = [makeDefaultRound()]
  }
}

const handleSubmit = async () => {
  if (!form.name) return ElMessage.warning('请输入任务名称')
  creating.value = true
  try {
    const finalConfig = { ...form.config }
    if (!finalConfig.acc_datasets || finalConfig.acc_datasets.length === 0) {
      finalConfig.acc_enabled = false
    }
    const payload = {
      name: form.name,
      profile: form.profile,
      device_id: form.device_ids && form.device_ids.length > 0 ? form.device_ids[0] : form.device_id,
      device_ids: form.device_ids,
      template_id: form.template_id,
      config: finalConfig,
    }
    if (editId.value) {
      // 编辑模式：PATCH 更新
      await apiUpdateTask(editId.value, payload)
      ElMessage.success('任务已更新')
      router.push('/tasks')
    } else {
      // 创建模式：POST 新建并跳转到详情
      const task = await apiCreateTask(payload)
      ElMessage.success('任务已创建并开始执行')
      router.push(`/task/${task.id}`)
    }
  } catch (e) {
    ElMessage.error((editId.value ? '更新' : '创建') + '失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    creating.value = false
  }
}

onMounted(async () => {
  loadTemplates()
  try {
    const resp = await apiListModels()
    models.value = Array.isArray(resp) ? resp : []
  } catch (e) { console.error('加载模型列表失败', e) }

  try {
    const resp = await apiListDevices()
    devices.value = Array.isArray(resp) ? resp : []
  } catch (e) { console.error('加载设备列表失败', e) }

  // 编辑模式：加载现有任务数据填充表单
  if (editId.value) {
    try {
      const task = await apiGetTask(editId.value)
      if (task) {
        form.name = task.name || ''
        form.profile = task.profile || 'full'
        form.device_id = task.device_id || null
        const cfg = task.config || {}
        form.config.model_slugs = cfg.model_slugs || []
        form.config.perf_enabled = cfg.perf_enabled ?? true
        form.config.perf_rounds_config = (cfg.perf_rounds_config && cfg.perf_rounds_config.length)
          ? cfg.perf_rounds_config
          : [makeDefaultRound()]
        form.config.acc_enabled = cfg.acc_enabled ?? true
        form.config.acc_datasets = cfg.acc_datasets || ['mmlu', 'ceval', 'gsm8k', 'arc']
        form.config.acc_limit = cfg.acc_limit || 200
        form.config.container_port = cfg.container_port || 8300
        form.config.gpu_memory_utilization = cfg.gpu_memory_utilization || ''
        form.config.notify_email = cfg.notify_email || ''
      }
    } catch (e) {
      ElMessage.error('加载任务数据失败: ' + e.message)
    }
  }
})
</script>

<style scoped>
.task-create-page { padding: 0; max-width: 900px; }
.task-create-page h3 { margin-bottom: 20px; font-size: 16px; }
</style>
