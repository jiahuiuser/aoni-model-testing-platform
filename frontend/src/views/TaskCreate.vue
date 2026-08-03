<template>
  <div class="task-create-page">
    <!-- 顶部页头 -->
    <div class="page-header">
      <div class="header-title">
        <h2>{{ editId ? '编辑测试任务' : '创建测试任务' }}</h2>
        <p class="header-desc">配置模型压测矩阵、API 协议规范校验与自动化学科评测策略</p>
      </div>
      <div class="header-actions">
        <el-button @click="$router.back()">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleSubmit">
          {{ editId ? '保存修改' : '创建并执行' }}
        </el-button>
      </div>
    </div>

    <!-- 左右 50/50 双列分布表单 -->
    <el-form :model="form" label-width="120px" label-position="left">
      <el-row :gutter="20">
        <!-- 左列：基础信息、调度节点与模型选择 (50%) -->
        <el-col :xs="24" :lg="12">
          <div class="column-wrapper">
            <!-- 1. 基础信息与调度配置 -->
            <el-card shadow="never" class="config-card">
              <template #header>
                <div class="card-header-title">
                  <span class="card-icon-tag">1</span>
                  <span>基础信息与调度配置</span>
                </div>
              </template>

              <el-form-item label="任务名称" required>
                <el-input v-model="form.name" placeholder="例如: Qwen系列模型测试" />
              </el-form-item>

              <el-form-item label="测试 Profile">
                <el-select v-model="form.profile" style="width: 100%" @change="handleProfileChange">
                  <template v-if="isExternalModelSelected">
                    <el-option label="全量测试 (API 协议 + 准确率)" value="full" />
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

              <el-form-item v-if="!isExternalModelSelected" label="矩阵用例模板">
                <el-select
                  v-model="selectedTemplateIds"
                  multiple
                  collapse-tags
                  collapse-tags-tooltip
                  placeholder="选择测试模板（支持多选）"
                  clearable
                  style="width: 100%"
                  @change="handleTemplateSelect"
                >
                  <el-option
                    v-for="t in templates"
                    :key="t.id"
                    :label="`${t.name} (并发: ${(t.concurrencies || []).join('/')})`"
                    :value="t.id"
                  />
                </el-select>
              </el-form-item>

              <el-form-item v-if="!isAllExternalSelected" label="目标设备">
                <el-select
                  v-model="form.device_ids"
                  multiple
                  placeholder="选择目标在线节点设备（支持多选）"
                  clearable
                  style="width: 100%"
                >
                  <el-option
                    v-for="d in availableTaskDevices"
                    :key="d.id"
                    :label="`${d.name} (${d.host})`"
                    :value="d.id"
                  >
                    <span>{{ d.name }}</span>
                    <el-tag size="small" type="success" style="margin-left: 8px">已验证 PASS</el-tag>
                    <span style="color: #909399; margin-left: 4px">{{ d.host }}</span>
                  </el-option>
                </el-select>
                <div class="form-tip">
                  多选设备将自动并发批量下发独立测试任务。
                </div>
              </el-form-item>

              <el-form-item label="定时下发">
                <div style="display: flex; align-items: center; gap: 12px">
                  <el-switch v-model="form.is_scheduled" />
                  <el-date-picker
                    v-if="form.is_scheduled"
                    v-model="form.scheduled_at"
                    type="datetime"
                    placeholder="选择定时下发时间"
                    format="YYYY-MM-DD HH:mm:ss"
                    value-format="YYYY-MM-DD HH:mm:ss"
                    style="width: 220px"
                  />
                </div>
                <div v-if="form.is_scheduled" class="form-tip">
                  设定时间到达前，任务将保持在【定时等待中】队列。
                </div>
              </el-form-item>
            </el-card>

            <!-- 2. 测试模型选择 -->
            <el-card shadow="never" class="config-card">
              <template #header>
                <div class="card-header-title">
                  <span class="card-icon-tag">2</span>
                  <span>测试模型选择</span>
                </div>
              </template>

              <div v-if="isExternalModelSelected" style="margin-bottom: 12px">
                <el-alert type="info" show-icon :closable="false">
                  <template #title>
                    <b>外部 API 端点模型模式</b>
                  </template>
                  <template #default>
                    已自动隐藏节点设备与部署参数，专注于【API 协议校验】与【学科准确率】测试。
                  </template>
                </el-alert>
              </div>

              <el-form-item label="测试模型" required>
                <el-select
                  v-model="form.config.model_slugs"
                  multiple
                  filterable
                  collapse-tags
                  collapse-tags-tooltip
                  :max-collapse-tags="2"
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
                      <div style="display: flex; justify-content: space-between; align-items: center; width: 100%">
                        <span>#{{ m.idx }} {{ m.name }}</span>
                        <div>
                          <el-tag size="small" type="info">{{ m.size_category }}</el-tag>
                          <el-tag v-if="isModelDisabled(m)" size="small" type="warning" style="margin-left: 6px">不可混选</el-tag>
                        </div>
                      </div>
                    </el-option>
                  </el-option-group>
                </el-select>
                <div class="model-quick-actions">
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

                <div v-if="selectedExternalModels.length > 0" style="margin-top: 10px">
                  <el-alert type="success" :closable="false" show-icon>
                    <template #title>
                      <span style="font-weight: 600">已载入 API 端点与鉴权密钥：</span>
                    </template>
                    <template #default>
                      <div v-for="m in selectedExternalModels" :key="m.slug" style="font-size: 12px; margin-top: 4px">
                        • <b>{{ m.name }}</b> ➜ 端点: <code>{{ m.api_base || '未设置' }}</code> | Key: <code>{{ maskKey(m.api_key) }}</code>
                      </div>
                    </template>
                  </el-alert>
                </div>
              </el-form-item>
            </el-card>

            <!-- 3. 高级配置与通知 -->
            <el-card shadow="never" class="config-card">
              <template #header>
                <div class="card-header-title">
                  <span class="card-icon-tag">3</span>
                  <span>高级参数与结果通知</span>
                </div>
              </template>

              <el-form-item label="通知邮箱">
                <el-input v-model="form.config.notify_email" placeholder="输入接收通知邮箱" clearable />
              </el-form-item>

              <template v-if="!isExternalModelSelected">
                <el-form-item label="部署端口">
                  <el-input v-model.number="form.config.container_port" placeholder="默认 8300" />
                </el-form-item>
                <el-form-item label="显存占用">
                  <el-input v-model="form.config.gpu_memory_utilization" placeholder="默认 0.8" />
                </el-form-item>
              </template>
            </el-card>
          </div>
        </el-col>

        <!-- 右列：测试模块与策略配置 (50%) -->
        <el-col :xs="24" :lg="12">
          <div class="column-wrapper">
            <!-- 4. API 协议规范校验 -->
            <el-card shadow="never" class="config-card">
              <template #header>
                <div class="card-header-title">
                  <span class="card-icon-tag">4</span>
                  <span>API 协议规范校验</span>
                  <el-switch
                    v-if="form.profile === 'custom'"
                    v-model="form.config.gateway_enabled"
                    style="margin-left: auto"
                  />
                </div>
              </template>

              <template v-if="form.config.gateway_enabled">
                <el-form-item label="校验协议">
                  <el-checkbox-group v-model="form.config.gateway_protocols">
                    <el-checkbox label="openai">OpenAI Chat (/v1/chat/completions)</el-checkbox>
                    <el-checkbox label="responses">OpenAI Responses (/v1/responses)</el-checkbox>
                    <el-checkbox label="anthropic">Anthropic Messages (/v1/messages)</el-checkbox>
                  </el-checkbox-group>
                </el-form-item>
                <el-form-item label="长上下文">
                  <el-switch v-model="form.config.test_longctx" />
                  <span style="margin-left: 12px; color: #909399; font-size: 12px">评估 85% max_model_len 上下文边界</span>
                </el-form-item>
              </template>
              <template v-else>
                <div class="disabled-tip">API 协议校验模块未激活</div>
              </template>
            </el-card>

            <!-- 5. 性能矩阵压测 -->
            <el-card shadow="never" class="config-card">
              <template #header>
                <div class="card-header-title">
                  <span class="card-icon-tag">5</span>
                  <span>性能矩阵压测</span>
                  <el-switch
                    v-if="form.profile === 'custom' && !isExternalModelSelected"
                    v-model="form.config.perf_enabled"
                    style="margin-left: auto"
                  />
                </div>
              </template>

              <template v-if="isExternalModelSelected">
                <el-alert type="info" show-icon :closable="false">
                  外部 API 端点模型不支持本地硬件容器级别的性能压测，该模块已自动停用。
                </el-alert>
              </template>
              <template v-else-if="form.config.perf_enabled">
                <div v-for="(round, index) in form.config.perf_rounds_config" :key="index" style="margin-bottom: 10px">
                  <div class="round-box">
                    <div class="round-header">
                      <span><b>第 {{ index + 1 }} 轮压测策略</b></span>
                      <el-button
                        v-if="form.config.perf_rounds_config.length > 1"
                        type="danger"
                        size="small"
                        text
                        @click="removePerfRound(index)"
                      >
                        删除
                      </el-button>
                    </div>

                    <el-row :gutter="10">
                      <el-col :span="12">
                        <el-form-item label="输入 Token" label-width="85px">
                          <el-input v-model.number="round.input_len" size="small" placeholder="512" />
                        </el-form-item>
                      </el-col>
                      <el-col :span="12">
                        <el-form-item label="输出 Token" label-width="85px">
                          <el-input v-model="round.output_lens_str" size="small" placeholder="128,512" />
                        </el-form-item>
                      </el-col>
                    </el-row>

                    <el-row :gutter="10">
                      <el-col :span="12">
                        <el-form-item label="并发梯度" label-width="85px">
                          <el-input v-model="round.concurrencies_str" size="small" placeholder="1,4,8,16" />
                        </el-form-item>
                      </el-col>
                      <el-col :span="12">
                        <el-form-item label="请求总数" label-width="85px">
                          <el-input v-model.number="round.num_prompts" size="small" placeholder="100" />
                        </el-form-item>
                      </el-col>
                    </el-row>
                  </div>
                </div>

                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px">
                  <el-button type="primary" plain size="small" @click="addPerfRound">
                    <el-icon><Plus /></el-icon> 添加轮次
                  </el-button>
                  <span style="font-size: 12px; color: #4b5563">
                    压测场景总计: <b>{{ estimatedPerfTests }}</b> 项
                  </span>
                </div>
              </template>
              <template v-else>
                <div class="disabled-tip">性能压测模块未激活</div>
              </template>
            </el-card>

            <!-- 6. 自动化学科准确率评测 -->
            <el-card shadow="never" class="config-card">
              <template #header>
                <div class="card-header-title">
                  <span class="card-icon-tag">6</span>
                  <span>自动化学科准确率评测</span>
                  <el-switch
                    v-if="form.profile === 'custom'"
                    v-model="form.config.acc_enabled"
                    style="margin-left: auto"
                  />
                </div>
              </template>

              <template v-if="form.config.acc_enabled">
                <el-form-item label="快捷选集">
                  <div style="display: flex; gap: 6px; flex-wrap: wrap">
                    <el-button size="small" type="danger" plain @click="selectUltraDatasets">全选高阶综合推理集</el-button>
                    <el-button size="small" type="warning" plain @click="selectHardDatasets">全选专项能力扩展集</el-button>
                    <el-button size="small" type="info" plain @click="selectStandardDatasets">全选基础通用基准集</el-button>
                    <el-button size="small" @click="form.config.acc_datasets = []">清空</el-button>
                  </div>
                </el-form-item>

                <el-form-item label="评测集">
                  <el-checkbox-group v-model="form.config.acc_datasets" style="width: 100%">
                    <div class="dataset-group-box ultra">
                      <div class="group-title">高阶综合推理集 (High-Order Reasoning)</div>
                      <div class="checkbox-row">
                        <el-checkbox label="aime24">AIME24 (数学推演 · 30 题)</el-checkbox>
                        <el-checkbox label="arena_hard">Arena-Hard (Query 对战 · 500 题)</el-checkbox>
                        <el-checkbox label="gpqa">GPQA (学术问答 · 198 题)</el-checkbox>
                      </div>
                    </div>

                    <div class="dataset-group-box hard">
                      <div class="group-title">专项能力扩展集 (Specialized Benchmarks)</div>
                      <div class="checkbox-row">
                        <el-checkbox label="math500">MATH-500 (竞赛数学 · 500 题)</el-checkbox>
                        <el-checkbox label="bigcodebench">BigCodeBench (代码生成 · 1,140 题)</el-checkbox>
                        <el-checkbox label="longbench_pro">LongBench Pro (长文本分析 · 1,500 题)</el-checkbox>
                      </div>
                    </div>

                    <div class="dataset-group-box standard">
                      <div class="group-title">基础通用基准集 (Standard Benchmarks)</div>
                      <div class="checkbox-row">
                        <el-checkbox label="mmlu">MMLU (学科知识 · 14,042 题)</el-checkbox>
                        <el-checkbox label="ceval">C-Eval (中文推理 · 13,948 题)</el-checkbox>
                        <el-checkbox label="gsm8k">GSM8K (应用题推理 · 1,319 题)</el-checkbox>
                        <el-checkbox label="arc">ARC (科学常识 · 2,590 题)</el-checkbox>
                        <el-checkbox label="humaneval">HumanEval (Python 编程 · 164 题)</el-checkbox>
                      </div>
                    </div>
                  </el-checkbox-group>
                </el-form-item>

                <el-form-item label="数据集抽样">
                  <div style="display: flex; align-items: center; gap: 16px; flex-wrap: wrap;">
                    <el-checkbox
                      v-model="form.is_full_acc"
                      @change="handleFullAccChange"
                    >
                      <span style="font-weight: 600;">全量评测 (不限定额全题库)</span>
                    </el-checkbox>

                    <div v-if="!form.is_full_acc" style="display: flex; align-items: center; gap: 8px;">
                      <span style="font-size: 13px; color: #475569;">自定义抽样数量:</span>
                      <el-input-number
                        v-model="form.config.acc_limit"
                        :min="1"
                        :max="100000"
                        size="small"
                        placeholder="如 200"
                        style="width: 140px"
                      />
                      <span style="font-size: 12px; color: #94a3b8;">题 / 数据集</span>
                    </div>
                  </div>
                  <div style="font-size: 12px; color: #64748b; margin-top: 4px;">
                    <span v-if="form.is_full_acc">
                      <el-tag size="small" type="success" effect="dark" style="margin-right: 4px;">全量模式</el-tag>
                      已启用全量评测，将 100% 遍历评估数据集内全部题目。
                    </span>
                    <span v-else>
                      <el-tag size="small" type="info" style="margin-right: 4px;">抽样模式</el-tag>
                      每个已选数据集抽取 <b>{{ form.config.acc_limit || 200 }}</b> 题进行评测。
                    </span>
                  </div>
                </el-form-item>
              </template>
              <template v-else>
                <div class="disabled-tip">准确率评测模块未激活</div>
              </template>
            </el-card>
          </div>
        </el-col>
      </el-row>
    </el-form>

    <!-- 底部固定吸底提交工具栏 -->
    <div class="bottom-action-bar">
      <div class="action-bar-info">
        <span class="info-label">任务准备就绪：</span>
        <span class="info-tag">已选 <b>{{ form.config.model_slugs.length }}</b> 款模型</span>
        <span class="info-tag">调度 <b>{{ isExternalModelSelected ? '外部 API' : (form.device_ids?.length || 0) }}</b> 台节点</span>
        <span class="info-tag"> Profile: <b>{{ profileLabelMap[form.profile] || form.profile }}</b></span>
      </div>
      <div class="action-bar-buttons">
        <el-button @click="$router.back()">取消返回</el-button>
        <el-button type="primary" size="large" :loading="creating" @click="handleSubmit">
          {{ editId ? '保存修改' : '创建并执行测试任务' }}
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import api, { apiListModels, apiListDevices, apiCreateTask, apiUpdateTask, apiGetTask } from '../api'

const router = useRouter()
const route = useRoute()
const models = ref([])
const devices = ref([])
const creating = ref(false)
const editId = computed(() => (route.query.edit ? parseInt(route.query.edit) : null))

const profileLabelMap = {
  full: '全量测试',
  gateway: 'API 协议校验',
  perf: '仅性能测试',
  accuracy: '仅准确率测试',
  quick: '快速冒烟测试',
  custom: '自定义测试',
}

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
  const selectedList = templates.value.filter((t) => tplIds.includes(t.id))
  if (selectedList.length === 0) return

  form.template_ids = [...tplIds]
  form.template_id = tplIds[0]

  form.config.perf_rounds_config = selectedList.map((tpl) => ({
    input_len: tpl.input_lens ? tpl.input_lens[0] : 512,
    output_lens_str: (tpl.output_lens || [128, 512]).join(','),
    concurrencies_str: (tpl.concurrencies || [1, 4, 8, 16, 32]).join(','),
    num_prompts: tpl.num_prompts || 300,
  }))

  const datasetSet = new Set()
  selectedList.forEach((tpl) => {
    if (tpl.datasets) tpl.datasets.forEach((d) => datasetSet.add(d))
  })
  if (datasetSet.size > 0) {
    form.config.acc_datasets = [...datasetSet]
  }

  const maxAccLimit = Math.max(...selectedList.map((t) => t.acc_limit || 200))
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
  is_scheduled: false,
  scheduled_at: null,
  is_full_acc: false,
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

const handleFullAccChange = (val) => {
  if (val) {
    form.config.acc_limit = 0
  } else {
    form.config.acc_limit = 200
  }
}

const onlineDevices = computed(() =>
  (Array.isArray(devices.value) ? devices.value : []).filter((d) => d && d.status === 'online')
)

const availableTaskDevices = computed(() => {
  const containerModels = selectedModelObjects.value.filter((m) => m && !m.is_external && !m.api_base)
  if (containerModels.length === 0) {
    return onlineDevices.value
  }
  return onlineDevices.value.filter((d) => {
    return containerModels.every((m) => {
      if (!m.device_configs || m.device_configs.length === 0) {
        return m.status === 'PASS'
      }
      const dc = m.device_configs.find((c) => c.device_id === d.id)
      return dc ? dc.status === 'PASS' : m.status === 'PASS'
    })
  })
})

const passModels = computed(() =>
  (Array.isArray(models.value) ? models.value : []).filter(
    (m) => m && (m.status === 'PASS' || Boolean(m.is_external) || Boolean(m.api_base))
  )
)

const passContainerModels = computed(() =>
  (Array.isArray(models.value) ? models.value : []).filter(
    (m) => m && m.status === 'PASS' && !m.is_external && !m.api_base
  )
)

const passExternalModels = computed(() =>
  (Array.isArray(models.value) ? models.value : []).filter(
    (m) => m && (m.status === 'PASS' || m.is_external || m.api_base) && (Boolean(m.is_external) || Boolean(m.api_base))
  )
)

const modelsByGroup = computed(() => {
  const groupsMap = {
    外部API模型: { label: '外部 API 端点模型', models: [] },
    NVIDIA_jetson_AGX_Thor: { label: 'NVIDIA AGX Thor', models: [] },
    '沐曦C500/N260': { label: '沐曦 C500 / N260', models: [] },
    英伟达服务器: { label: 'NVIDIA GPU 服务器', models: [] },
  }

  passModels.value.forEach((m) => {
    let g = m.group_name || 'NVIDIA_jetson_AGX_Thor'
    if (m.is_external || m.api_base) {
      g = '外部API模型'
    }
    if (!groupsMap[g]) {
      groupsMap[g] = { label: m.group_name || '其他硬件节点', models: [] }
    }
    groupsMap[g].models.push(m)
  })

  return Object.values(groupsMap).filter((g) => g.models.length > 0)
})

const selectedModelObjects = computed(() => {
  const selectedSlugs = form.config.model_slugs || []
  return (Array.isArray(models.value) ? models.value : []).filter((m) => m && selectedSlugs.includes(m.slug))
})

const selectedExternalModels = computed(() => {
  return selectedModelObjects.value.filter((m) => Boolean(m.is_external) || Boolean(m.api_base))
})

const isExternalModelSelected = computed(() => {
  return selectedExternalModels.value.length > 0
})

const hasDeviceSelected = computed(() => {
  return selectedModelObjects.value.some((m) => !m.is_external && !m.api_base)
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
  return (
    selectedModelObjects.value.length > 0 &&
    selectedModelObjects.value.every((m) => Boolean(m.is_external) || Boolean(m.api_base))
  )
})

watch(isExternalModelSelected, (isExt) => {
  if (isExt) {
    form.config.perf_enabled = false
    if (form.profile === 'perf') {
      form.profile = 'gateway'
    }
    if (form.profile === 'full') {
      form.config.gateway_enabled = true
      form.config.acc_enabled = true
    }
    form.device_ids = []
    form.device_id = null
  }
})

function parseOutputLens(round) {
  return (round.output_lens_str || '').split(',').map(Number).filter((v) => v > 0)
}

function parseConcurrencies(round) {
  return (round.concurrencies_str || '').split(',').map(Number).filter((v) => v > 0)
}

function calcRoundTests(round) {
  if (!round) return 0
  const outLens = parseOutputLens(round)
  const concs = parseConcurrencies(round)
  return (outLens.length || 1) * (concs.length || 1)
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
    form.config.perf_enabled = !isExternalModelSelected.value
    form.config.perf_rounds_config = [
      { input_len: 512, output_lens_str: '128', concurrencies_str: '1,4', num_prompts: 100 },
    ]
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
    form.config.perf_enabled = !isExternalModelSelected.value
    form.config.acc_enabled = true
    if (!isExternalModelSelected.value) {
      form.config.perf_rounds_config = [makeDefaultRound()]
    }
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
      scheduled_at: form.is_scheduled && form.scheduled_at ? form.scheduled_at : null,
      config: finalConfig,
    }
    if (editId.value) {
      await apiUpdateTask(editId.value, payload)
      ElMessage.success('任务已更新')
      router.push('/tasks')
    } else {
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
  } catch (e) {
    console.error('加载模型列表失败', e)
  }

  try {
    const resp = await apiListDevices()
    devices.value = Array.isArray(resp) ? resp : []
  } catch (e) {
    console.error('加载设备列表失败', e)
  }

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
        form.config.perf_rounds_config =
          cfg.perf_rounds_config && cfg.perf_rounds_config.length
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
.task-create-page {
  width: 100%;
  max-width: 1440px;
  margin: 0 auto;
  padding: 0 8px 70px 8px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 14px;
  border-bottom: 1px solid #e5e7eb;
}

.header-title h2 {
  margin: 0 0 4px 0;
  font-size: 20px;
  font-weight: 600;
  color: #111827;
}

.header-desc {
  margin: 0;
  font-size: 13px;
  color: #6b7280;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.column-wrapper {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.config-card {
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  background: #ffffff;
}

.card-header-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
}

.card-icon-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #2563eb;
  color: #ffffff;
  font-size: 11px;
  font-weight: 600;
}

.form-tip {
  color: #909399;
  font-size: 12px;
  margin-top: 4px;
}

.model-quick-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}

.round-box {
  border-radius: 6px;
  border: 1px solid #e5e7eb;
  background: #fafafa;
  padding: 10px 12px;
}

.round-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 13px;
}

.dataset-group-box {
  border-radius: 6px;
  padding: 8px 12px;
  margin-bottom: 8px;
}

.dataset-group-box.ultra {
  background: #fef2f2;
  border: 1px solid #fecaca;
}

.dataset-group-box.hard {
  background: #fffbeb;
  border: 1px solid #fde68a;
}

.dataset-group-box.standard {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.group-title {
  font-weight: 600;
  font-size: 12px;
  margin-bottom: 4px;
}

.dataset-group-box.ultra .group-title { color: #dc2626; }
.dataset-group-box.hard .group-title { color: #d97706; }
.dataset-group-box.standard .group-title { color: #475569; }

.checkbox-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.disabled-tip {
  font-size: 13px;
  color: #9ca3af;
  font-style: italic;
  padding: 12px 0;
  text-align: center;
}

/* 底部固定吸底操作栏 */
.bottom-action-bar {
  position: fixed;
  bottom: 0;
  left: 235px;
  right: 0;
  height: 60px;
  background: #ffffff;
  border-top: 1px solid #e5e7eb;
  box-shadow: 0 -2px 10px rgba(0, 0, 0, 0.05);
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 24px;
  z-index: 99;
}

.action-bar-info {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  color: #4b5563;
}

.info-label {
  font-weight: 600;
  color: #111827;
}

.info-tag {
  background: #f3f4f6;
  padding: 4px 10px;
  border-radius: 4px;
}

.action-bar-buttons {
  display: flex;
  gap: 12px;
}
</style>
