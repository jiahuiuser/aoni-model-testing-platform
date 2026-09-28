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

              <el-form-item label="测试类型">
                <el-select v-model="form.profile" style="width: 100%" @change="handleProfileChange">
                  <el-option label="全量测试 (API 协议 + 性能 + 准确率)" value="full" />
                  <el-option label="API 协议规范校验" value="gateway" />
                  <el-option label="性能测试" value="perf" />
                  <el-option label="准确率测试" value="accuracy" />
                  <el-option label="自定义" value="custom" />
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
                          <el-tag v-if="isModelDisabled(m)" size="small" type="warning" style="margin-left: 6px">{{ modelDisableReason(m) }}</el-tag>
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

                <!-- 已选模型配置查看 -->
                <div v-if="selectedContainerModels.length > 0" class="selected-model-detail-box" style="margin-top: 12px">
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px">
                    <span style="font-weight: 600; font-size: 13px; color: #1f2937">
                      已选模型配置速览 ({{ selectedContainerModels.length }})
                    </span>
                    <el-button size="small" text type="primary" @click="pmListCollapsed = !pmListCollapsed">
                      {{ pmListCollapsed ? '展开全部' : '收起' }}
                    </el-button>
                  </div>
                  <div v-show="!pmListCollapsed" class="pm-chip-wrap">
                    <div v-for="m in selectedContainerModels" :key="m.slug" class="pm-chip"
                         :class="{ 'pm-chip-configured': isPmConfigured(m.slug) }">
                      <span class="pm-chip-name" :title="m.name">#{{ m.idx }} {{ m.name }}</span>
                      <el-tag v-if="isPmConfigured(m.slug)" size="small" type="success" effect="dark">单独配置</el-tag>
                      <div class="pm-chip-actions">
                        <el-button size="small" text type="primary" @click.stop="openPmConfig(m)">用例</el-button>
                        <el-button size="small" text @click.stop="openModelConfig(m)">详情</el-button>
                      </div>
                    </div>
                  </div>
                  <div style="font-size:12px;color:#909399;margin-top:6px">点击【用例】可单独设置该模型的矩阵与压测框架；【详情】查看部署与上下文。</div>
                </div>
              </el-form-item>
            </el-card>

            <!-- 3. 高级配置与通知 -->
            <el-card shadow="never" class="config-card">
              <template #header>
                <div class="card-header-title">
                  <span class="card-icon-tag">3</span>
                  <span>结果通知</span>
                </div>
              </template>

              <el-form-item label="通知邮箱">
                <el-input v-model="form.config.notify_email" placeholder="输入接收通知邮箱" clearable />
              </el-form-item>
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

            <!-- 5. 功能测试（质量专项） -->
            <el-card shadow="never" class="config-card">
              <template #header>
                <div class="card-header-title">
                  <span class="card-icon-tag">5</span>
                  <span>功能测试（质量专项）</span>
                  <el-switch
                    v-model="form.config.feature_enabled"
                    style="margin-left: auto"
                  />
                </div>
              </template>

              <template v-if="form.config.feature_enabled">
                <el-form-item label="测试项">
                  <el-checkbox-group v-model="form.config.feature_items">
                    <el-checkbox label="needle">大海捞针（长上下文检索）</el-checkbox>
                    <el-checkbox label="math">数学正确性</el-checkbox>
                    <el-checkbox label="garble">长上下文乱码检测</el-checkbox>
                    <el-checkbox label="tool_smoke">工具调用冒烟快筛</el-checkbox>
                    <el-checkbox label="agent_replay">Agent 多工具决定性回归</el-checkbox>
                    <el-checkbox label="multimodal" :disabled="!isVisionModelSelected">多模态图片输入测试（仅 VL 模型）</el-checkbox>
                  </el-checkbox-group>
                </el-form-item>
                <div class="form-tip">
                  大海捞针：长文本中嵌入关键信息，验证检索正确性；数学正确性：确定性运算校验；乱码检测：分层扫描 U+FFFD/重复符号；
                  工具冒烟/Agent 回归：验证工具调用能力（Agent 回归用 39 工具+33K 上下文真实请求重放）；多模态：仅图片输入模型可勾选。
                </div>
              </template>
              <template v-else>
                <div class="disabled-tip">功能测试模块未激活</div>
              </template>
            </el-card>

            <!-- 6. 性能矩阵压测 -->
            <el-card shadow="never" class="config-card">
              <template #header>
                <div class="card-header-title">
                  <span class="card-icon-tag">6</span>
                  <span>性能矩阵压测</span>
                  <el-switch
                    v-if="form.profile === 'custom'"
                    v-model="form.config.perf_enabled"
                    style="margin-left: auto"
                  />
                </div>
              </template>

              <el-alert v-if="isExternalModelSelected && form.config.perf_enabled" type="info" show-icon :closable="false" style="margin-bottom: 10px">
                外部 API 端点模型将使用【自定义 HTTP】异步流式压测（同样输出 ITL/TPOT 指标），无法使用容器内原生 vLLM bench。
              </el-alert>
              <template v-if="form.config.perf_enabled">
                <el-form-item label="矩阵用例模板">
                  <el-select
                    v-model="selectedTemplateIds"
                    multiple
                    collapse-tags
                    collapse-tags-tooltip
                    placeholder="选择测试模板（支持多选），自动填充下方轮次策略"
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

                <el-form-item label="压测框架">
                  <el-radio-group v-model="form.config.benchmark_framework">
                    <el-radio label="auto">自动</el-radio>
                    <el-radio label="native" :disabled="isExternalModelSelected">原生 vLLM</el-radio>
                    <el-radio label="custom">自定义 HTTP</el-radio>
                  </el-radio-group>
                  <div class="form-tip">
                    自动：GGUF(llama.cpp)/外部 → 自定义 HTTP，其余 → 原生 vLLM。<br>
                    原生 vLLM：容器内执行 <code>vllm bench serve</code>，最准确，推荐。<br>
                    自定义 HTTP：aiohttp 异步流式压测（fallback/GGUF/外部路径，同样输出 ITL/TPOT）。
                  </div>
                </el-form-item>

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
                          <el-input v-model="round.input_lens_str" size="small" placeholder="512,2048" />
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

            <!-- 7. 自动化学科准确率评测 -->
            <el-card shadow="never" class="config-card">
              <template #header>
                <div class="card-header-title">
                  <span class="card-icon-tag">7</span>
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
                        <el-tooltip
                          v-for="ds in accDatasetsByBand.ultra"
                          :key="ds.name"
                          :content="tooltipText(ds)"
                          placement="top"
                          effect="dark"
                          :show-after="200"
                        >
                          <el-checkbox :label="ds.name">{{ datasetLabel(ds) }}</el-checkbox>
                        </el-tooltip>
                      </div>
                    </div>

                    <div class="dataset-group-box hard">
                      <div class="group-title">专项能力扩展集 (Specialized Benchmarks)</div>
                      <div class="checkbox-row">
                        <el-tooltip
                          v-for="ds in accDatasetsByBand.hard"
                          :key="ds.name"
                          :content="tooltipText(ds)"
                          placement="top"
                          effect="dark"
                          :show-after="200"
                        >
                          <el-checkbox :label="ds.name">{{ datasetLabel(ds) }}</el-checkbox>
                        </el-tooltip>
                      </div>
                    </div>

                    <div class="dataset-group-box standard">
                      <div class="group-title">基础通用基准集 (Standard Benchmarks)</div>
                      <div class="checkbox-row">
                        <el-tooltip
                          v-for="ds in accDatasetsByBand.standard"
                          :key="ds.name"
                          :content="tooltipText(ds)"
                          placement="top"
                          effect="dark"
                          :show-after="200"
                        >
                          <el-checkbox :label="ds.name">{{ datasetLabel(ds) }}</el-checkbox>
                        </el-tooltip>
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

                    <div style="display: flex; align-items: center; gap: 8px;">
                      <span style="font-size: 13px; color: #475569;">并发数:</span>
                      <el-input-number
                        v-model="form.config.acc_batch_size"
                        :min="1"
                        :max="128"
                        size="small"
                        placeholder="如 2"
                        style="width: 120px"
                      />
                      <span style="font-size: 12px; color: #94a3b8;">请求 / 容器</span>
                    </div>
                  </div>
                  <div style="font-size: 12px; color: #64748b; margin-top: 4px;">
                    <span v-if="form.is_full_acc">
                      <el-tag size="small" type="success" effect="dark" style="margin-right: 4px;">全量模式</el-tag>
                      已启用全量评测，将 100% 遍历评估数据集内全部题目。
                    </span>
                    <span v-else>
                      <el-tag size="small" type="info" style="margin-right: 4px;">抽样模式</el-tag>
                      每个已选数据集默认抽取 <b>{{ form.config.acc_limit }}</b> 题（可在下方按数据集单独覆盖）。
                    </span>
                  </div>
                </el-form-item>

                <el-form-item label="数据集级配置" v-if="form.config.acc_datasets && form.config.acc_datasets.length">
                  <div style="width: 100%; border: 1px solid #e5e7eb; border-radius: 6px; overflow: hidden;">
                    <div style="display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: 8px; padding: 6px 12px; background: #f8fafc; font-size: 12px; color: #64748b; font-weight: 600;">
                      <span>数据集</span><span>抽样数（留空=全局）</span><span>并发（留空=全局）</span>
                    </div>
                    <div
                      v-for="ds in form.config.acc_datasets"
                      :key="ds"
                      style="display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: 8px; padding: 6px 12px; align-items: center; border-top: 1px solid #f1f5f9;"
                    >
                      <span style="font-size: 13px; color: #334155;">{{ ds }}</span>
                      <el-input-number
                        v-model="form.config.acc_dataset_limits[ds]"
                        :min="0"
                        :max="100000"
                        size="small"
                        controls-position="right"
                        placeholder="全局"
                        style="width: 130px"
                      />
                      <el-input-number
                        v-model="form.config.acc_dataset_batch_size[ds]"
                        :min="1"
                        :max="128"
                        size="small"
                        controls-position="right"
                        placeholder="全局"
                        style="width: 130px"
                      />
                    </div>
                  </div>
                  <div style="font-size: 12px; color: #94a3b8; margin-top: 4px;">
                    抽样数填 <b>0</b> 表示该数据集全量；留空沿用全局。Agent/Terminal/SWE-bench 建议并发 1~2，普通文本集可调高（受网关承受能力限制）。
                  </div>
                </el-form-item>

                <el-form-item label="工具调用测试">
                  <div style="width: 100%;">
                    <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 6px;">
                      <el-tag v-if="evalNode.online" type="success" size="small">评测执行节点在线 · {{ evalNode.arch }}</el-tag>
                      <el-tag v-else-if="evalNode.configured" type="danger" size="small">评测执行节点离线</el-tag>
                      <el-tag v-else type="info" size="small">未配置评测执行节点</el-tag>
                      <span style="font-size: 12px; color: #94a3b8;">{{ evalNode.message }}</span>
                    </div>
                    <el-checkbox-group v-model="form.config.tool_call_tests" style="width: 100%">
                      <div class="dataset-group-box hard">
                        <div class="group-title">真实环境 Agent（需 x86 评测执行节点）</div>
                        <div class="checkbox-row">
                          <el-tooltip
                            v-for="ds in agentEnvDatasets"
                            :key="ds.name"
                            :content="tooltipText(ds)"
                            placement="top"
                            effect="dark"
                            :show-after="200"
                          >
                            <el-checkbox :label="ds.name">{{ datasetLabel(ds) }}</el-checkbox>
                          </el-tooltip>
                        </div>
                      </div>
                      <div class="dataset-group-box standard">
                        <div class="group-title">模拟工具调用（纯 API · 本机运行）</div>
                        <div class="checkbox-row">
                          <el-tooltip
                            v-for="ds in agentSimDatasets"
                            :key="ds.name"
                            :content="tooltipText(ds)"
                            placement="top"
                            effect="dark"
                            :show-after="200"
                          >
                            <el-checkbox :label="ds.name">{{ datasetLabel(ds) }}</el-checkbox>
                          </el-tooltip>
                        </div>
                      </div>
                    </el-checkbox-group>
                    <div style="font-size: 12px; color: #94a3b8; margin-top: 4px;">
                      工具调用测试与常规测评集相互独立；Terminal/SWE 自动使用公共评测执行节点（x86），BFCL/τ² 在本机运行。
                    </div>
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

    <!-- 模型配置详情弹窗 -->
    <el-dialog v-model="configDialogVisible" :title="`模型部署与配置详情 — ${configDialogModel?.name || ''}`" width="720px" append-to-body>
      <template v-if="configDialogModel">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="模型名称">{{ configDialogModel.name }}</el-descriptions-item>
          <el-descriptions-item label="标识 (slug)">{{ configDialogModel.slug }}</el-descriptions-item>
          <el-descriptions-item label="推理引擎">{{ configDialogModel.engine || '-' }}</el-descriptions-item>
          <el-descriptions-item label="硬件分组">{{ configDialogModel.group_name }}</el-descriptions-item>
          <el-descriptions-item label="大小类别">{{ configDialogModel.size_category }}</el-descriptions-item>
          <el-descriptions-item label="量化精度">{{ configDialogModel.quantization || '未标注' }}</el-descriptions-item>
          <el-descriptions-item label="最大上下文 (Max Len)">
            <el-tag type="warning" effect="dark">{{ configDialogModel.max_context_length || '未设置' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="GPU 显存利用率">{{ configDialogModel.gpu_memory_utilization }}</el-descriptions-item>
          <el-descriptions-item label="端口">{{ configDialogModel.docker_port || '-' }}</el-descriptions-item>
          <el-descriptions-item label="多模态">{{ configDialogModel.is_multimodal ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="部署镜像" :span="2">
            <span style="word-break: break-all">{{ configDialogModel.docker_image || '-' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="模型权重路径" :span="2">
            <span style="word-break: break-all">{{ configDialogModel.model_path || '-' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="TOS 云端权重" :span="2">
            <span style="word-break: break-all">{{ configDialogModel.engine_uri || (configDialogModel.tos_path || '-') }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <!-- 本地 config.json 详情 -->
        <template v-if="configDialogModel.model_config && Object.keys(configDialogModel.model_config).some(k => configDialogModel.model_config[k])">
          <h4 style="margin-top: 20px">📄 模型 config.json 配置</h4>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item v-if="configDialogModel.model_config.max_model_len" label="config 最大上下文">
              {{ configDialogModel.model_config.max_model_len }}
            </el-descriptions-item>
            <el-descriptions-item v-if="configDialogModel.model_config.hidden_size" label="隐藏层维度">
              {{ configDialogModel.model_config.hidden_size }}
            </el-descriptions-item>
            <el-descriptions-item v-if="configDialogModel.model_config.num_attention_heads" label="注意力头数">
              {{ configDialogModel.model_config.num_attention_heads }}
            </el-descriptions-item>
            <el-descriptions-item v-if="configDialogModel.model_config.num_hidden_layers" label="层数">
              {{ configDialogModel.model_config.num_hidden_layers }}
            </el-descriptions-item>
            <el-descriptions-item v-if="configDialogModel.model_config.num_key_value_heads" label="KV 头数">
              {{ configDialogModel.model_config.num_key_value_heads }}
            </el-descriptions-item>
            <el-descriptions-item v-if="configDialogModel.model_config.num_local_experts" label="专家数 (MoE)">
              {{ configDialogModel.model_config.num_local_experts }}
            </el-descriptions-item>
            <el-descriptions-item v-if="configDialogModel.model_config.vocab_size" label="词表大小">
              {{ configDialogModel.model_config.vocab_size }}
            </el-descriptions-item>
            <el-descriptions-item v-if="configDialogModel.model_config.model_type" label="模型类型">
              {{ configDialogModel.model_config.model_type }}
            </el-descriptions-item>
            <el-descriptions-item v-if="configDialogModel.model_config.torch_dtype" label="精度 (dtype)">
              {{ configDialogModel.model_config.torch_dtype }}
            </el-descriptions-item>
            <el-descriptions-item v-if="configDialogModel.model_config.sliding_window" label="滑窗大小">
              {{ configDialogModel.model_config.sliding_window }}
            </el-descriptions-item>
            <el-descriptions-item v-if="configDialogModel.model_config.architectures && configDialogModel.model_config.architectures.length" label="架构" :span="2">
              {{ configDialogModel.model_config.architectures.join(', ') }}
            </el-descriptions-item>
          </el-descriptions>
        </template>

        <!-- Docker 部署命令 -->
        <h4 style="margin-top: 20px">🐳 Docker 部署命令</h4>
        <div class="command-code-block">
          <pre style="white-space: pre-wrap; word-break: break-all; background: #0f172a; color: #38bdf8; padding: 12px; border-radius: 6px; font-size: 12px; line-height: 1.5; margin: 0;">{{ configDialogModel.docker_command || '（外部 API 模型，无容器部署命令）' }}</pre>
        </div>

        <!-- 设备专属配置 -->
        <template v-if="configDialogModel.device_configs && configDialogModel.device_configs.length">
          <h4 style="margin-top: 20px">🖥️ 设备专属配置 ({{ configDialogModel.device_configs.length }})</h4>
          <el-table :data="configDialogModel.device_configs" size="small" border stripe>
            <el-table-column prop="device_name" label="设备" min-width="140" />
            <el-table-column prop="status" label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.status === 'PASS' ? 'success' : (row.status === 'FAIL' ? 'danger' : 'info')" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="命令" min-width="300" show-overflow-tooltip>
              <template #default="{ row }">
                <span style="font-family: monospace; font-size: 11px">{{ row.docker_command }}</span>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </template>
    </el-dialog>

    <!-- 单模型单独配置弹窗 -->
    <el-dialog v-model="pmDialogVisible" :title="`单独配置 — ${pmDialogModel?.name || ''}`" width="640px" append-to-body>
      <el-form label-width="90px" label-position="left">
        <el-form-item label="压测框架">
          <el-radio-group v-model="pmForm.benchmark_framework">
            <el-radio label="auto">跟随任务</el-radio>
            <el-radio label="native">原生 vLLM</el-radio>
            <el-radio label="custom">自定义 HTTP</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="单独用例矩阵">
          <div style="width: 100%">
            <div v-for="(round, index) in pmForm.perf_rounds_config" :key="index" class="round-box" style="margin-bottom: 8px">
              <div class="round-header">
                <span><b>第 {{ index + 1 }} 轮</b></span>
                <el-button
                  v-if="pmForm.perf_rounds_config.length > 1"
                  type="danger" size="small" text @click="removePmRound(index)">删除</el-button>
              </div>
              <el-row :gutter="10">
                <el-col :span="8"><el-form-item label="输入" label-width="50px">
                  <el-input v-model="round.input_lens_str" size="small" placeholder="512,2048" /></el-form-item>
                </el-col>
                <el-col :span="8"><el-form-item label="输出" label-width="50px">
                  <el-input v-model="round.output_lens_str" size="small" placeholder="128,512" /></el-form-item>
                </el-col>
                <el-col :span="8"><el-form-item label="并发" label-width="50px">
                  <el-input v-model="round.concurrencies_str" size="small" placeholder="1,4,8" /></el-form-item>
                </el-col>
              </el-row>
              <el-form-item label="请求数"><el-input v-model.number="round.num_prompts" size="small" placeholder="100" /></el-form-item>
            </div>
            <el-button type="primary" plain size="small" @click="addPmRound">
              <el-icon><Plus /></el-icon> 添加轮次
            </el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pmDialogVisible = false">取消</el-button>
        <el-button v-if="isPmConfigured(pmDialogModel?.slug)" @click="removePmConfig">清除单独配置</el-button>
        <el-button type="primary" @click="savePmConfig">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
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
  perf: '性能测试',
  accuracy: '准确率测试',
  quick: '快速冒烟测试',
  custom: '自定义测试',
}

function makeDefaultRound() {
  return {
    input_lens_str: '',
    output_lens_str: '',
    concurrencies_str: '',
    num_prompts: '',
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
    input_lens_str: (tpl.input_lens && tpl.input_lens.length ? tpl.input_lens : [512]).join(','),
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

  // 合并模板里的数据集级抽样/并发覆盖
  const dsLimits = {}
  const dsBatch = {}
  let maxBatch = form.config.acc_batch_size || 2
  selectedList.forEach((t) => {
    Object.entries(t.acc_dataset_limits || {}).forEach(([k, v]) => { if (v !== null && v !== undefined) dsLimits[k] = v })
    Object.entries(t.acc_dataset_batch_size || {}).forEach(([k, v]) => { if (v !== null && v !== undefined) dsBatch[k] = v })
    if (t.acc_batch_size) maxBatch = Math.max(maxBatch, t.acc_batch_size)
  })
  form.config.acc_dataset_limits = { ...(form.config.acc_dataset_limits || {}), ...dsLimits }
  form.config.acc_dataset_batch_size = { ...(form.config.acc_dataset_batch_size || {}), ...dsBatch }
  form.config.acc_batch_size = maxBatch

  ElMessage.success(`已成功应用 ${selectedList.length} 个测试模板的矩阵配置`)
}

const form = reactive({
  name: '',
  profile: 'custom',
  device_id: null,
  device_ids: [],
  template_id: null,
  template_ids: [],
  is_scheduled: false,
  scheduled_at: null,
  is_full_acc: false,
  config: {
    model_slugs: [],
    gateway_enabled: false,
    gateway_protocols: [],
    test_longctx: false,
    feature_enabled: false,
    feature_items: [],
    perf_enabled: false,
    benchmark_framework: 'auto',
    perf_rounds_config: [],
    per_model_config: {},
    acc_enabled: false,
    acc_datasets: [],
    acc_limit: null,
    acc_dataset_limits: {},
    acc_batch_size: 2,
    acc_dataset_batch_size: {},
    tool_call_tests: [],
    notify_email: '',
  },
})

const evalNode = reactive({ configured: false, online: false, arch: '', message: '未检测', tools: [] })
const loadEvalNode = async () => {
  try {
    const res = await api.get('/eval-tools/status')
    Object.assign(evalNode, res.data || {})
  } catch (e) {
    evalNode.message = '评测执行节点状态获取失败'
  }
}

// ===== 评测集注册表 (动态渲染, 与后端 dataset_infos 同步) =====
const AGENT_CATEGORY = 'Agent/工具调用'
const AGENT_ENV_KEYS = ['terminal_bench_v2_1', 'swe_bench_verified_mini_agentic']

// 分组维度与后端难度词表对齐：ultra = high + extreme
const DATASET_BANDS = {
  ultra: ['high', 'extreme'],
  hard: ['hard'],
  standard: ['standard'],
}

const allDatasets = ref([])

// 后端不可用时的兜底列表，保证页面可用
const FALLBACK_ACC_DATASETS = [
  { name: 'aime24', difficulty: 'high', sample_count: 30, description: 'AIME 2024 美国数学邀请赛' },
  { name: 'arena_hard', difficulty: 'high', sample_count: 500, description: 'Arena-Hard-Auto 真实 Query 对战' },
  { name: 'gpqa', difficulty: 'high', sample_count: 198, description: 'GPQA Diamond 学术问答' },
  { name: 'math500', difficulty: 'hard', sample_count: 500, description: 'MATH-500 竞赛数学' },
  { name: 'bigcodebench', difficulty: 'hard', sample_count: 1140, description: 'BigCodeBench 代码生成' },
  { name: 'longbench_pro', difficulty: 'hard', sample_count: 1500, description: 'LongBench Pro 长文本分析' },
  { name: 'mmlu', difficulty: 'standard', sample_count: 14042, description: 'MMLU 多任务语言理解' },
  { name: 'ceval', difficulty: 'standard', sample_count: 13948, description: 'C-Eval 中文推理' },
  { name: 'gsm8k', difficulty: 'standard', sample_count: 1319, description: 'GSM8K 应用题推理' },
  { name: 'arc', difficulty: 'standard', sample_count: 2590, description: 'ARC 科学常识' },
  { name: 'humaneval', difficulty: 'standard', sample_count: 164, description: 'HumanEval Python 编程' },
]

const AGENT_ENV_FALLBACK = [
  { name: 'terminal_bench_v2_1', sample_count: 89, description: 'Terminal-Bench 2.1 真实终端多步任务（容器）' },
  { name: 'swe_bench_verified_mini_agentic', sample_count: 50, description: 'SWE-bench Verified Mini 软件工程 agent' },
]
const AGENT_SIM_FALLBACK = [
  { name: 'bfcl_v4', sample_count: 2000, description: 'BFCL-v4 函数调用（模拟工具）' },
  { name: 'tau2_bench', sample_count: 165, description: 'τ²-bench 工具对话（模拟工具+用户）' },
]

const loadDatasets = async () => {
  try {
    const res = await api.get('/data/datasets')
    allDatasets.value = Array.isArray(res.data) ? res.data : []
  } catch (e) {
    console.error('加载数据集注册表失败', e)
    allDatasets.value = []
  }
}

// 普通评测集（非 Agent 类），按难度 band 分组；并入已配置但注册表缺失的旧数据集
const accDatasetsByBand = computed(() => {
  const byBand = { ultra: [], hard: [], standard: [] }
  let pool = allDatasets.value.filter((d) => d.category_group !== AGENT_CATEGORY)
  if (pool.length === 0) pool = FALLBACK_ACC_DATASETS
  const known = new Set(pool.map((d) => d.name))
  const extras = (form.config.acc_datasets || [])
    .filter((n) => !known.has(n) && n !== null && n !== undefined)
    .map((n) => ({ name: n, difficulty: 'standard', sample_count: 0, description: '（历史配置项）' }))
  ;[...pool, ...extras].forEach((d) => {
    for (const [band, diffs] of Object.entries(DATASET_BANDS)) {
      if (diffs.includes(d.difficulty)) { byBand[band].push(d); break }
    }
  })
  return byBand
})

const agentEnvDatasets = computed(() => {
  const pool = allDatasets.value.filter((d) => d.category_group === AGENT_CATEGORY && AGENT_ENV_KEYS.includes(d.name))
  return pool.length ? pool : AGENT_ENV_FALLBACK
})
const agentSimDatasets = computed(() => {
  const pool = allDatasets.value.filter((d) => d.category_group === AGENT_CATEGORY && !AGENT_ENV_KEYS.includes(d.name))
  return pool.length ? pool : AGENT_SIM_FALLBACK
})

const datasetLabel = (d) => {
  const n = d.sample_count ? ` · ${d.sample_count} 题` : ''
  return `${(d.name || '').toUpperCase()}${n}`
}

const tooltipText = (d) => {
  const n = d.sample_count ? `共 ${d.sample_count} 题` : ''
  const desc = d.description && d.description !== '（历史配置项）' ? d.description : ''
  return [desc, n].filter(Boolean).join(' · ') || (d.name || '').toUpperCase()
}

const handleFullAccChange = (val) => {
  if (val) {
    form.config.acc_limit = 0
  } else {
    form.config.acc_limit = null
  }
}

// 数据集级配置：选中数据集时补齐键，取消时清理
watch(
  () => [...(form.config.acc_datasets || [])],
  (list) => {
    if (!form.config.acc_dataset_limits) form.config.acc_dataset_limits = {}
    if (!form.config.acc_dataset_batch_size) form.config.acc_dataset_batch_size = {}
    list.forEach((ds) => {
      if (!(ds in form.config.acc_dataset_limits)) form.config.acc_dataset_limits[ds] = null
      if (!(ds in form.config.acc_dataset_batch_size)) form.config.acc_dataset_batch_size[ds] = null
    })
    Object.keys(form.config.acc_dataset_limits).forEach((k) => { if (!list.includes(k)) delete form.config.acc_dataset_limits[k] })
    Object.keys(form.config.acc_dataset_batch_size).forEach((k) => { if (!list.includes(k)) delete form.config.acc_dataset_batch_size[k] })
  },
  { immediate: true }
)

// 归一化数据集级配置：剔除留空/非数字项（留空=沿用全局）
const normalizeAccMaps = (cfg) => {
  const out = { ...cfg }
  const clean = (m) => {
    const o = {}
    Object.keys(m || {}).forEach((k) => {
      const v = m[k]
      if (v === null || v === undefined || v === '') return
      const n = Number(v)
      if (!Number.isFinite(n)) return
      o[k] = n
    })
    return o
  }
  out.acc_dataset_limits = clean(out.acc_dataset_limits)
  out.acc_dataset_batch_size = clean(out.acc_dataset_batch_size)
  if (out.acc_batch_size !== null && out.acc_batch_size !== undefined && out.acc_batch_size !== '') {
    const n = Number(out.acc_batch_size)
    if (Number.isFinite(n)) out.acc_batch_size = n
  }
  return out
}

const onlineDevices = computed(() =>
  (Array.isArray(devices.value) ? devices.value : []).filter((d) => d && d.status === 'online')
)

const availableTaskDevices = computed(() => {
  const containerModels = selectedModelObjects.value.filter((m) => m && !m.is_external && !m.api_base)
  if (containerModels.length === 0) {
    return onlineDevices.value
  }
  return onlineDevices.value.filter((d) => containerModels.every((m) => isModelPassOnDevice(m, d.id)))
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

const selectedContainerModels = computed(() => {
  return selectedModelObjects.value.filter((m) => !m.is_external && !m.api_base)
})

const configDialogVisible = ref(false)
const configDialogModel = ref(null)
const openModelConfig = (m) => {
  configDialogModel.value = m
  configDialogVisible.value = true
}

/* ---------- 单模型单独配置 ---------- */
const pmDialogVisible = ref(false)
const pmDialogModel = ref(null)
const pmListCollapsed = ref(false)
const pmForm = reactive({
  benchmark_framework: 'auto',
  perf_rounds_config: [makeDefaultRound()],
})

const isPmConfigured = (slug) => {
  return Boolean(form.config.per_model_config && form.config.per_model_config[slug])
}

const openPmConfig = (m) => {
  pmDialogModel.value = m
  const exist = form.config.per_model_config && form.config.per_model_config[m.slug]
  if (exist) {
    pmForm.benchmark_framework = exist.benchmark_framework || 'auto'
    pmForm.perf_rounds_config = exist.perf_rounds_config && exist.perf_rounds_config.length
      ? exist.perf_rounds_config.map((r) => normalizePerfRound(r))
      : [makeDefaultRound()]
  } else {
    pmForm.benchmark_framework = 'auto'
    pmForm.perf_rounds_config = [makeDefaultRound()]
  }
  pmDialogVisible.value = true
}

function addPmRound() {
  pmForm.perf_rounds_config.push(makeDefaultRound())
}

function removePmRound(index) {
  pmForm.perf_rounds_config.splice(index, 1)
}

const savePmConfig = () => {
  if (!pmDialogModel.value) return
  const badRound = pmForm.perf_rounds_config.some((r) =>
    !parseInputLens(r).length
    || !r.output_lens_str || !r.concurrencies_str
    || !Number.isInteger(Number(r.num_prompts)) || Number(r.num_prompts) < 1
  )
  if (badRound) return ElMessage.warning('轮次参数不完整，请填写输入/输出 Token、并发梯度与请求总数')
  if (!form.config.per_model_config) form.config.per_model_config = {}
  form.config.per_model_config[pmDialogModel.value.slug] = {
    benchmark_framework: pmForm.benchmark_framework,
    perf_rounds_config: pmForm.perf_rounds_config.map((r) => normalizePerfRound(r)),
  }
  ElMessage.success(`已为 ${pmDialogModel.value.name} 单独配置`)
  pmDialogVisible.value = false
}

const removePmConfig = () => {
  if (!pmDialogModel.value) return
  if (form.config.per_model_config) {
    delete form.config.per_model_config[pmDialogModel.value.slug]
  }
  ElMessage.success('已清除该模型的单独配置')
  pmDialogVisible.value = false
}

const isExternalModelSelected = computed(() => {
  return selectedExternalModels.value.length > 0
})

// 是否选中了 VL (多模态) 模型 —— 决定多模态图片测试项是否可勾选
const isVisionModelSelected = computed(() => {
  return selectedModelObjects.value.some((m) => {
    const slug = (m.slug || '').toLowerCase()
    return slug.includes('-vl') || slug.includes('vision') || slug.includes('omni')
  })
})

const hasDeviceSelected = computed(() => {
  return selectedModelObjects.value.some((m) => !m.is_external && !m.api_base)
})

function maskKey(key) {
  if (!key || key === 'EMPTY') return '未设置 (EMPTY)'
  if (key.length <= 8) return '******'
  return key.slice(0, 4) + '****' + key.slice(-4)
}

function isModelPassOnDevice(m, deviceId) {
  // 与后端 create_task 校验规则完全一致: 必须存在该设备的专属配置且状态为 PASS
  const dc = (m.device_configs || []).find((c) => c.device_id === deviceId)
  return Boolean(dc) && dc.status === 'PASS'
}

function modelDisableReason(m) {
  const selectedSlugs = form.config.model_slugs || []
  const mIsExternal = Boolean(m.is_external) || Boolean(m.api_base)
  // 选了目标设备: 容器模型必须在所有已选设备上验证 PASS
  const deviceIds = form.device_ids || []
  if (!mIsExternal && deviceIds.length > 0) {
    if (!deviceIds.every((id) => isModelPassOnDevice(m, id))) {
      return '未在该设备验证'
    }
  }
  if (selectedSlugs.length > 0) {
    if (isExternalModelSelected.value && !mIsExternal) {
      return '不可混选'
    }
    if (hasDeviceSelected.value && mIsExternal) {
      return '不可混选'
    }
  }
  return ''
}

function isModelDisabled(m) {
  return modelDisableReason(m) !== ''
}

// 切换目标设备时，自动移除已选但未在新设备验证 PASS 的模型
watch(() => form.device_ids, () => {
  const deviceIds = form.device_ids || []
  if (deviceIds.length === 0 || !form.config.model_slugs || form.config.model_slugs.length === 0) return
  const valid = form.config.model_slugs.filter((slug) => {
    const m = (models.value || []).find((x) => x.slug === slug)
    if (!m) return true
    const mIsExternal = Boolean(m.is_external) || Boolean(m.api_base)
    if (mIsExternal) return true
    return deviceIds.every((id) => isModelPassOnDevice(m, id))
  })
  if (valid.length !== form.config.model_slugs.length) {
    const removed = form.config.model_slugs.filter((s) => !valid.includes(s))
    form.config.model_slugs = valid
    ElMessage.warning(`已自动移除未在所选设备验证 PASS 的模型: ${removed.join('、')}`)
  }
})

const isAllExternalSelected = computed(() => {
  return (
    selectedModelObjects.value.length > 0 &&
    selectedModelObjects.value.every((m) => Boolean(m.is_external) || Boolean(m.api_base))
  )
})

watch(isExternalModelSelected, (isExt) => {
  if (isExt) {
    if (form.profile === 'full') {
      form.config.gateway_enabled = true
      form.config.acc_enabled = true
    }
    form.device_ids = []
    form.device_id = null
  }
})

function parseInputLens(round) {
  const raw = round.input_lens_str
  let vals = []
  if (raw !== undefined && raw !== null && String(raw).trim() !== '') {
    vals = String(raw).split(',').map(Number).filter((v) => v > 0)
  }
  if (!vals.length && round.input_len !== undefined && round.input_len !== null && round.input_len !== '') {
    const legacy = Number(round.input_len)
    if (legacy > 0) vals = [legacy]
  }
  return Array.from(new Set(vals))
}

function parseOutputLens(round) {
  return (round.output_lens_str || '').split(',').map(Number).filter((v) => v > 0)
}

function parseConcurrencies(round) {
  return (round.concurrencies_str || '').split(',').map(Number).filter((v) => v > 0)
}

function calcRoundTests(round) {
  if (!round) return 0
  const inLens = parseInputLens(round)
  const outLens = parseOutputLens(round)
  const concs = parseConcurrencies(round)
  return (inLens.length || 1) * (outLens.length || 1) * (concs.length || 1)
}

function normalizePerfRound(r) {
  const inLens = parseInputLens(r)
  const toInt = (v, dflt) => {
    const n = Number.parseInt(v, 10)
    return Number.isNaN(n) ? dflt : n
  }
  return {
    ...r,
    input_lens_str: inLens.join(','),
    input_len: inLens.length ? Math.min(...inLens) : 512,
    num_prompts: toInt(r.num_prompts, 300),
  }
}

const applyBand = (band) => {
  const keys = (accDatasetsByBand.value[band] || []).map((d) => d.name)
  form.config.acc_datasets = Array.from(new Set([...(form.config.acc_datasets || []), ...keys]))
}

const selectUltraDatasets = () => applyBand('ultra')
const selectHardDatasets = () => applyBand('hard')
const selectStandardDatasets = () => applyBand('standard')

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
    form.config.perf_rounds_config = [
      { input_lens_str: '512', output_lens_str: '128', concurrencies_str: '1,4', num_prompts: 100 },
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
    form.config.perf_enabled = true
    form.config.acc_enabled = true
    form.config.perf_rounds_config = [makeDefaultRound()]
  }
}

const handleSubmit = async () => {
  if (!form.name) return ElMessage.warning('请输入任务名称')
  if (form.config.gateway_enabled && (!form.config.gateway_protocols || form.config.gateway_protocols.length === 0)) {
    return ElMessage.warning('已开启网关校验，请至少勾选一个协议')
  }
  if (form.config.perf_enabled && (!form.config.perf_rounds_config || form.config.perf_rounds_config.length === 0)) {
    return ElMessage.warning('已开启性能压测，请先添加轮次策略')
  }
  if (form.config.perf_enabled) {
    const badRound = (form.config.perf_rounds_config || []).some((r) =>
      !parseInputLens(r).length
      || !r.output_lens_str || !r.concurrencies_str
      || !Number.isInteger(Number(r.num_prompts)) || Number(r.num_prompts) < 1
    )
    if (badRound) return ElMessage.warning('压测轮次参数不完整（输入 Token / 输出 Token / 并发梯度 / 请求总数需为正整数）')
  }
  const hasAccDs = form.config.acc_datasets && form.config.acc_datasets.length > 0
  const hasToolTests = form.config.tool_call_tests && form.config.tool_call_tests.length > 0
  if (form.config.acc_enabled && !hasAccDs && !hasToolTests) {
    return ElMessage.warning('已开启准确率评测，请勾选常规评测集或工具调用测试')
  }
  if (form.config.acc_enabled && hasAccDs && !form.is_full_acc && (!form.config.acc_limit || form.config.acc_limit < 1)) {
    return ElMessage.warning('已开启准确率评测，请填写数据集抽样数量（或勾选全量评测）')
  }
  if (hasToolTests) {
    const needNode = form.config.tool_call_tests.some((t) => ['terminal_bench_v2_1', 'swe_bench_verified_mini_agentic'].includes(t))
    if (needNode && !evalNode.online) {
      try {
        await ElMessageBox.confirm(
          `已勾选需要真实环境的 agent 测试（Terminal-Bench / SWE-bench），但评测执行节点当前${evalNode.configured ? '离线' : '未配置'}。这些项将无法运行（会记录为错误）。仍要下发吗？`,
          '评测执行节点未就绪',
          { type: 'warning', confirmButtonText: '仍然下发', cancelButtonText: '取消' }
        )
      } catch (e) {
        return
      }
    }
  }
  creating.value = true
  try {
    // 下发前在线检测：外部 API 模型不在线则强提示（避免下发给离线模型浪费时间）
    const extSlugs = selectedModelObjects.value
      .filter((m) => m && (m.is_external || m.api_base))
      .map((m) => m.slug)
    if (extSlugs.length > 0) {
      try {
        const res = await api.post('/models/check-online', { slugs: extSlugs })
        const offline = (res.data?.results || []).filter((r) => r.status !== 'online')
        if (offline.length > 0) {
          const msg = offline.map((r) => `${r.slug}（${r.message || '不可达'}）`).join('；')
          try {
            await ElMessageBox.confirm(
              `以下外部模型当前不在线：${msg}。仍要下发测试任务吗？`,
              '模型在线检测',
              { type: 'warning', confirmButtonText: '仍然下发', cancelButtonText: '取消' }
            )
          } catch (e) {
            creating.value = false
            return
          }
        }
      } catch (e) {
        // 探测接口异常不阻断下发
        console.warn('模型在线检测失败（忽略）', e)
      }
    }

    const finalConfig = { ...form.config }
    Object.assign(finalConfig, normalizeAccMaps(finalConfig))
    if ((!finalConfig.acc_datasets || finalConfig.acc_datasets.length === 0) &&
        (!finalConfig.tool_call_tests || finalConfig.tool_call_tests.length === 0)) {
      finalConfig.acc_enabled = false
    }
    finalConfig.tool_call_tests = Array.isArray(finalConfig.tool_call_tests) ? finalConfig.tool_call_tests : []
    // 压测轮次字段归一化：输入 Token 多值整理为 input_lens_str，同时写入兼容字段 input_len（首值）；
    // 数字字段强制转整数，避免 v-model 残留字符串导致后端 422。
    if (Array.isArray(finalConfig.perf_rounds_config)) {
      finalConfig.perf_rounds_config = finalConfig.perf_rounds_config.map((r) => normalizePerfRound(r))
    }
    if (finalConfig.per_model_config) {
      const pmc = {}
      for (const k of Object.keys(finalConfig.per_model_config)) {
        const v = finalConfig.per_model_config[k] || {}
        const rounds = Array.isArray(v.perf_rounds_config) ? v.perf_rounds_config : []
        pmc[k] = {
          ...v,
          perf_rounds_config: rounds.map((r) => normalizePerfRound(r)),
        }
      }
      finalConfig.per_model_config = pmc
    }
    const allExternal = isAllExternalSelected.value
    const payload = {
      name: form.name,
      profile: form.profile,
      device_id: allExternal
        ? null
        : (form.device_ids && form.device_ids.length > 0 ? form.device_ids[0] : form.device_id),
      device_ids: allExternal ? [] : form.device_ids,
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
    const d = e.response?.data?.detail
    let msg
    if (typeof d === 'string') msg = d
    else if (Array.isArray(d)) msg = d.map((x) => `${(x.loc || []).join('.')}: ${x.msg}`).join('; ')
    else msg = e.message
    ElMessage.error((editId.value ? '更新' : '创建') + '失败: ' + msg)
  } finally {
    creating.value = false
  }
}

onMounted(async () => {
  loadTemplates()
  loadEvalNode()
  loadDatasets()
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
        form.config.perf_enabled = cfg.perf_enabled ?? false
        form.config.benchmark_framework = cfg.benchmark_framework || 'auto'
        form.config.per_model_config = (cfg.per_model_config && typeof cfg.per_model_config === 'object')
          ? Object.fromEntries(Object.entries(cfg.per_model_config).map(([k, v]) => [
              k,
              {
                ...v,
                perf_rounds_config: (Array.isArray(v?.perf_rounds_config) ? v.perf_rounds_config : [])
                  .map((r) => normalizePerfRound(r)),
              },
            ]))
          : {}
        form.config.perf_rounds_config =
          cfg.perf_rounds_config && cfg.perf_rounds_config.length
            ? cfg.perf_rounds_config.map((r) => normalizePerfRound(r))
            : []
        form.config.acc_enabled = cfg.acc_enabled ?? false
        form.config.acc_datasets = cfg.acc_datasets || []
        form.config.acc_limit = cfg.acc_limit ?? null
        form.config.acc_dataset_limits = (cfg.acc_dataset_limits && typeof cfg.acc_dataset_limits === 'object') ? { ...cfg.acc_dataset_limits } : {}
        form.config.acc_batch_size = cfg.acc_batch_size ?? 2
        form.config.acc_dataset_batch_size = (cfg.acc_dataset_batch_size && typeof cfg.acc_dataset_batch_size === 'object') ? { ...cfg.acc_dataset_batch_size } : {}
        form.config.tool_call_tests = Array.isArray(cfg.tool_call_tests) ? [...cfg.tool_call_tests] : []
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

/* 已选模型：紧凑标签流 */
.pm-chip-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  max-height: 220px;
  overflow-y: auto;
  padding: 4px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fafafa;
}
.pm-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #ffffff;
}
.pm-chip-configured {
  border-color: #67c23a;
  background: #f0f9eb;
}
.pm-chip-name {
  font-size: 12px;
  font-weight: 600;
  color: #1f2937;
  white-space: nowrap;
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pm-chip-actions {
  display: flex;
  gap: 2px;
}
.pm-chip-actions .el-button {
  padding: 0 4px;
  font-size: 12px;
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
