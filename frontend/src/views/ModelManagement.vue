<template>
  <div class="model-mgmt-page">
    <!-- 顶部操作工具栏 -->
    <div class="top-toolbar">
      <div class="toolbar-left">
        <el-button type="primary" @click="showAddDialog">
          <el-icon><Plus /></el-icon> 创建模型配置
        </el-button>
        <el-button type="success" plain @click="openImportSyncDialog">
          <el-icon><Cloudy /></el-icon> 模型同步与导入
        </el-button>
        <el-button type="warning" plain @click="openHardwareGroupsDialog">
          <el-icon><Cpu /></el-icon> 硬件架构组
        </el-button>
        <el-button
          v-if="selectedModels.length > 0"
          type="danger"
          plain
          @click="confirmDeleteSelected"
        >
          <el-icon><Delete /></el-icon> 批量删除 ({{ selectedModels.length }})
        </el-button>

        <!-- 批量划归硬件组 -->
        <el-popover placement="bottom-start" :width="280" trigger="click" v-if="selectedModels.length > 0">
          <template #reference>
            <el-button type="info" plain>
              <el-icon><Connection /></el-icon> 划归硬件组 ({{ selectedModels.length }})
            </el-button>
          </template>
          <div>
            <div style="font-weight:600;margin-bottom:8px;font-size:13px;color:#374151">将选中的 {{ selectedModels.length }} 个模型划归至：</div>
            <el-select v-model="batchTargetGroup" placeholder="选择目标硬件组" style="width:100%;margin-bottom:10px">
              <el-option
                v-for="grp in groupOptions.filter(g => g.value !== 'ALL')"
                :key="grp.value"
                :label="grp.label"
                :value="grp.value"
              />
            </el-select>
            <el-button type="primary" size="small" style="width:100%" :loading="batchUpdatingGroup" @click="handleBatchUpdateGroup">
              确认划归
            </el-button>
          </div>
        </el-popover>
      </div>

      <div class="toolbar-right">
        <el-popover placement="bottom-end" :width="300" trigger="click">
          <template #reference>
            <el-button type="danger" plain size="small">
              <el-icon><Delete /></el-icon> 清理残留容器
            </el-button>
          </template>
          <div>
            <div style="font-weight:600;margin-bottom:8px;font-size:13px;color:#374151">清理目标设备上的残留容器与显存：</div>
            <el-select v-model="cleanDeviceId" placeholder="选择目标设备 (默认本机)" style="width:100%;margin-bottom:8px" clearable>
              <el-option v-for="d in devices" :key="d.id" :label="d.name" :value="d.id" />
            </el-select>
            <el-button type="danger" size="small" style="width:100%" :loading="cleaning" @click="handleStopContainer">
              释放显存资源
            </el-button>
          </div>
        </el-popover>
        <el-button circle @click="loadModels"><el-icon><Refresh /></el-icon></el-button>
      </div>
    </div>

    <!-- 硬件架构组 Tab 切换栏 -->
    <div class="group-tab-bar">
      <div
        v-for="grp in groupOptions"
        :key="grp.value"
        class="group-tab-item"
        :class="{ active: activeGroup === grp.value }"
        @click="activeGroup = grp.value"
      >
        <span class="group-tab-label">{{ grp.label }}</span>
        <span class="group-tab-count">{{ groupCounts[grp.value] || 0 }}</span>
      </div>
    </div>

    <!-- 模型数据表格 -->
    <el-table
      ref="tableRef"
      :data="filteredModels"
      v-loading="loading"
      stripe
      border
      @selection-change="handleSelectionChange"
      @row-click="handleRowClick"
      @row-dblclick="openRunTestDialog"
      class="custom-table"
      row-key="slug"
    >
      <el-table-column type="selection" width="50" align="center" />
      <el-table-column prop="idx" label="#" width="50" align="center" />
      <el-table-column prop="name" label="模型名称" min-width="180" show-overflow-tooltip />

      <!-- 所属硬件组 -->
      <el-table-column label="所属硬件组" width="170" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.group_name === '沐曦C500/N260'" type="warning" size="small" effect="dark">
            沐曦 C500 / N260
          </el-tag>
          <el-tag v-else-if="row.group_name === '英伟达服务器'" type="danger" size="small" effect="dark">
            NVIDIA GPU 服务器
          </el-tag>
          <el-tag v-else type="primary" size="small" effect="dark">
            {{ row.group_name || 'Jetson AGX Thor' }}
          </el-tag>
        </template>
      </el-table-column>

      <!-- 接入模式 -->
      <el-table-column label="接入模式" width="140" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.is_external" type="success" size="small" effect="dark">
            外部 API 端点
          </el-tag>
          <el-tag v-else type="info" size="small" effect="plain">
            容器镜像部署
          </el-tag>
        </template>
      </el-table-column>

      <!-- 规格分类 -->
      <el-table-column label="规格分类" width="110" align="center">
        <template #default="{ row }">
          <el-tag v-if="getSpecCategory(row) === 'small'" type="success" size="small" effect="light">Small</el-tag>
          <el-tag v-else-if="getSpecCategory(row) === 'medium'" type="warning" size="small" effect="light">Medium</el-tag>
          <el-tag v-else type="danger" size="small" effect="light">Large</el-tag>
        </template>
      </el-table-column>

      <el-table-column label="验证状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="row.status === 'PASS' ? 'success' : row.status === 'FAIL' ? 'danger' : 'info'" size="small">
            {{ row.status === 'PASS' ? '通过' : row.status === 'FAIL' ? '失败' : '待验证' }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column label="设备绑定情况" min-width="210">
        <template #default="{ row }">
          <div class="device-config-tags">
            <template v-if="row.device_configs && row.device_configs.length">
              <el-tag
                v-for="dc in row.device_configs"
                :key="dc.id"
                size="small"
                :type="dc.status === 'PASS' ? 'success' : dc.status === 'FAIL' ? 'danger' : 'warning'"
                style="margin:2px;cursor:pointer"
                @click.stop="openEditModel(row)"
              >
                {{ dc.device_name }}: {{ dc.status === 'PASS' ? 'PASS' : dc.status === 'FAIL' ? 'FAIL' : 'NEW' }}
              </el-tag>
            </template>
            <span v-else style="color:#9ca3af;font-size:12px">通用配置</span>
          </div>
        </template>
      </el-table-column>

      <!-- 快捷操作列 -->
      <el-table-column label="操作" width="200" align="center">
        <template #default="{ row }">
          <div style="display:flex;gap:6px;justify-content:center;">
            <el-button size="small" type="success" plain @click.stop="openRunTestDialog(row)">
              <el-icon><Promotion /></el-icon> 验证
            </el-button>
            <el-button size="small" type="primary" plain @click.stop="openEditModel(row)">
              <el-icon><Edit /></el-icon> 配置
            </el-button>
            <el-popconfirm title="确定删除该模型配置？" @confirm="handleSingleDelete(row.slug)">
              <template #reference>
                <el-button size="small" type="danger" plain @click.stop>
                  <el-icon><Delete /></el-icon>
                </el-button>
              </template>
            </el-popconfirm>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <!-- 模型配置与设备参数控制台 Modal -->
    <el-dialog v-model="dialogVisible" :title="editing ? `模型与设备配置 — ${form.name}` : '新增模型配置'" width="780px">
      <el-tabs v-model="activeEditTab">
        <el-tab-pane label="基础配置" name="basic">
          <el-form :model="form" label-width="130px" style="margin-top:12px">
            <el-form-item label="模型名称">
              <el-input v-model="form.name" placeholder="例如: Qwen2.5-7B-Instruct" />
            </el-form-item>
            <el-form-item label="所属硬件架构">
              <el-select v-model="form.group_name" placeholder="请选择归属硬件架构组" style="width:100%">
                <el-option
                  v-for="grp in groupOptions.filter(g => g.value !== 'ALL')"
                  :key="grp.value"
                  :label="grp.label"
                  :value="grp.value"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="部署与接入模式">
              <el-radio-group v-model="form.is_external">
                <el-radio-button :value="false">容器镜像部署</el-radio-button>
                <el-radio-button :value="true">外部 API 端点</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <template v-if="form.is_external">
              <el-form-item label="API Base URL">
                <el-input v-model="form.api_base" placeholder="例如: http://192.168.1.40:8000/v1" />
              </el-form-item>
              <el-form-item label="API Key">
                <el-input v-model="form.api_key" placeholder="例如: EMPTY 或 sk-xxxx" />
              </el-form-item>
              <el-form-item label="远程模型标识">
                <div style="display:flex;gap:10px;width:100%;">
                  <el-input v-model="form.model_endpoint_name" placeholder="例如: Qwen/Qwen2.5-7B-Instruct" />
                  <el-button type="success" plain :loading="testingConnection" @click="handleTestConnection">
                    连通性测试
                  </el-button>
                </div>
              </el-form-item>
            </template>

            <template v-else>
              <el-form-item label="全局默认 Docker 命令">
                <el-input v-model="form.docker_command" type="textarea" :rows="5"
                  placeholder="sudo docker run -it --rm --runtime=nvidia --network host -e MODEL_NAME=xxx ..."
                />
              </el-form-item>
              <el-form-item label="TOS 路径">
                <el-input v-model="form.tos_path" placeholder="tos://ai-hub/models/..." />
              </el-form-item>
            </template>
          </el-form>
        </el-tab-pane>

        <!-- 绑定设备专属配置 Tab -->
        <el-tab-pane v-if="editing && !form.is_external" label="设备专属参数" name="devices">
          <div style="background:#f8fafc;padding:12px;border-radius:6px;margin-bottom:14px;border:1px solid #e2e8f0;">
            <div style="font-size:13px;font-weight:600;margin-bottom:8px;color:#374151">绑定算力设备节点：</div>
            <div style="display:flex;gap:12px;align-items:center">
              <el-select v-model="newDcDeviceId" placeholder="选择目标设备" style="width:240px">
                <el-option v-for="d in availableDevices" :key="d.id" :label="d.name" :value="d.id" />
              </el-select>
              <el-button type="primary" size="small" @click="addDc" :disabled="!newDcDeviceId">
                绑定设备并继承默认指令
              </el-button>
            </div>
          </div>

          <el-table :data="currentDeviceConfigs" size="small" stripe border>
            <el-table-column prop="device_name" label="设备名称" width="150" />
            <el-table-column label="验证状态" width="90" align="center">
              <template #default="{ row }">
                <el-tag :type="row.status === 'PASS' ? 'success' : row.status === 'FAIL' ? 'danger' : 'warning'" size="small">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>

            <el-table-column label="专属 Docker 运行指令" min-width="260">
              <template #default="{ row }">
                <el-popover placement="top" :width="540" trigger="hover">
                  <template #reference>
                    <div class="cmd-pill-trigger">
                      <span class="cmd-text-ellipsis">{{ row.docker_command || '继承全局默认指令' }}</span>
                      <el-icon class="cmd-copy-icon"><CopyDocument /></el-icon>
                    </div>
                  </template>
                  <div class="popover-cmd-box">
                    <div class="popover-header">
                      <span class="popover-title">{{ row.device_name }} 运行指令</span>
                      <el-button size="small" type="primary" link @click="copyCmd(row.docker_command || form.docker_command)">
                        <el-icon><CopyDocument /></el-icon> 复制指令
                      </el-button>
                    </div>
                    <pre class="cmd-block-pretty">{{ formatCmdPretty(row.docker_command || form.docker_command) }}</pre>
                  </div>
                </el-popover>
              </template>
            </el-table-column>

            <el-table-column label="操作" width="140" align="center">
              <template #default="{ row }">
                <div class="dc-action-row">
                  <el-button size="small" type="primary" plain @click="editDc(row)">编辑</el-button>
                  <el-button size="small" type="danger" plain @click="deleteDc(row.id)">解绑</el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave">保存配置</el-button>
      </template>
    </el-dialog>

    <!-- 编辑设备专属命令弹窗 -->
    <el-dialog v-model="dcEditVisible" title="编辑设备专属 Docker 命令" width="600px" append-to-body>
      <el-form label-width="90px">
        <el-form-item label="目标设备">
          <strong>{{ editingDc?.device_name }}</strong>
        </el-form-item>
        <el-form-item label="Docker 命令">
          <div style="margin-bottom: 6px;">
            <el-button type="warning" size="small" plain @click="applySmartRecommendation">
              推荐参数配置 (优化显存与并行数)
            </el-button>
          </div>
          <el-input v-model="editingDcCommand" type="textarea" :rows="7" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dcEditVisible = false">取消</el-button>
        <el-button type="primary" @click="saveDcCommand">保存配置</el-button>
      </template>
    </el-dialog>

    <!-- 模型同步与导入控制台 (TOS 扫描 + 在线 ModelScope/HF 下载) -->
    <el-dialog v-model="importSyncModalVisible" title="模型同步与导入" width="850px">
      <el-tabs v-model="activeSyncTab">
        <!-- Tab 1: TOS 存储库扫描导入 -->
        <el-tab-pane label="TOS 存储库扫描" name="tos">
          <div style="background:#f8fafc;padding:14px;border-radius:8px;margin-bottom:16px;border:1px solid #e2e8f0;margin-top:10px">
            <el-form :inline="true" :model="scanForm" class="scan-form-inline">
              <el-form-item label="Bucket 名称">
                <el-input v-model="scanForm.bucket_name" placeholder="ai-hub" style="width:140px" />
              </el-form-item>
              <el-form-item label="TOS 前缀">
                <el-input v-model="scanForm.prefix" placeholder="models/" style="width:180px" />
              </el-form-item>
              <el-form-item label="目标硬件组">
                <el-select v-model="scanForm.group_name" style="width:200px">
                  <el-option
                    v-for="grp in groupOptions.filter(g => g.value !== 'ALL')"
                    :key="grp.value"
                    :label="grp.label"
                    :value="grp.value"
                  />
                </el-select>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="scanningTOS" @click="handlePreviewTOS">
                  <el-icon><Search /></el-icon> 开始扫描
                </el-button>
              </el-form-item>
            </el-form>
          </div>

          <div v-if="scannedItems.length > 0">
            <div style="margin-bottom:8px;font-size:13px;color:#64748b;display:flex;justify-content:space-between;align-items:center;">
              <span>已检测到 <b>{{ scannedItems.length }}</b> 项模型文件：</span>
              <el-tag type="info">选择需要导入的模型项</el-tag>
            </div>
            <el-table
              :data="scannedItems"
              size="small"
              stripe
              border
              max-height="350"
              @selection-change="handleScanSelectionChange"
            >
              <el-table-column type="selection" width="45" align="center" :selectable="(row) => !row.is_existing" />
              <el-table-column prop="display_name" label="模型文件名称" min-width="180">
                <template #default="{ row }">
                  <b>{{ row.display_name }}</b>
                </template>
              </el-table-column>
              <el-table-column prop="size_human" label="文件大小" width="100" align="center" />
              <el-table-column prop="tos_path" label="TOS 路径" min-width="260" show-overflow-tooltip />
              <el-table-column label="状态" width="120" align="center">
                <template #default="{ row }">
                  <el-tag v-if="row.is_existing" type="info" size="small">已存在</el-tag>
                  <el-tag v-else type="success" size="small">未导入</el-tag>
                </template>
              </el-table-column>
            </el-table>
            <div style="margin-top:12px;text-align:right">
              <el-button type="primary" :loading="importingTOS" @click="handleConfirmImportTOS">确认导入所选项</el-button>
            </div>
          </div>
        </el-tab-pane>

        <!-- Tab 2: ModelScope / HuggingFace 在线同步 -->
        <el-tab-pane label="在线开源仓库同步" name="online">
          <el-form :model="onlineForm" label-width="130px" style="margin-top:16px">
            <el-form-item label="模型来源">
              <el-radio-group v-model="onlineForm.source">
                <el-radio-button label="ModelScope">ModelScope (魔搭社区)</el-radio-button>
                <el-radio-button label="HuggingFace">HuggingFace</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="仓库 Repo ID">
              <el-input v-model="onlineForm.repo_id" placeholder="例如: Qwen/Qwen2.5-7B-Instruct" />
            </el-form-item>
            <el-form-item label="归属硬件组">
              <el-select v-model="onlineForm.group_name" style="width:100%;">
                <el-option
                  v-for="grp in groupOptions.filter(g => g.value !== 'ALL')"
                  :key="grp.value"
                  :label="grp.label"
                  :value="grp.value"
                />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="success" :loading="onlineDownloading" @click="submitOnlineDownload">提交在线同步任务</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>

    <!-- 硬件架构组管理 Modal -->
    <el-dialog v-model="showHgDialog" title="硬件架构组管理" width="650px">
      <div style="margin-bottom:14px;display:flex;gap:8px;">
        <el-input v-model="newHgName" placeholder="硬件组名称，如: NVIDIA_RTX_4090" style="width:260px;" />
        <el-input v-model="newHgDesc" placeholder="功能描述" style="flex:1;" />
        <el-button type="primary" @click="createHardwareGroup">添加硬件组</el-button>
      </div>
      <el-table :data="customHardwareGroups" stripe size="small" style="width:100%;">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="硬件组名称" width="200">
          <template #default="{ row }">
            <b>{{ row.name }}</b>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="说明" min-width="200" />
        <el-table-column label="操作" width="120" align="center">
          <template #default="{ row }">
            <el-button size="small" type="danger" plain @click="deleteHardwareGroup(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 模型测试验证 Modal -->
    <el-dialog
      v-model="runTestModalVisible"
      :title="`模型连通性与响应验证 — ${probeTargetModel?.name || ''}`"
      width="680px"
      destroy-on-close
    >
      <div style="margin-bottom: 16px;">
        <el-descriptions border :column="2" size="small">
          <el-descriptions-item label="测试模型">
            <strong>{{ probeTargetModel?.name }}</strong>
            <el-tag size="small" style="margin-left: 6px;" :type="probeTargetModel?.is_external ? 'success' : 'primary'">
              {{ probeTargetModel?.is_external ? '外部 API 端点' : '容器镜像部署' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="验证端点 (API Base)">
            <code style="color:#2563eb">{{ effectiveProbeApiBase }}</code>
          </el-descriptions-item>
        </el-descriptions>
      </div>

      <div v-if="!probeTargetModel?.is_external && boundDevices.length > 0" style="margin-bottom: 14px;">
        <label style="font-weight: 600; font-size: 13px; display: block; margin-bottom: 6px; color:#374151">
          验证目标节点设备
        </label>
        <el-select v-model="probeDeviceId" placeholder="选择验证节点设备（默认端口 8300）" style="width: 100%" clearable>
          <el-option
            v-for="d in boundDevices"
            :key="d.id"
            :label="`${d.name} (${d.host}:8300)`"
            :value="d.id"
          >
            <span>{{ d.name }}</span>
            <el-tag size="small" type="success" style="margin-left: 8px">在线</el-tag>
            <span style="color: #909399; margin-left: 4px">{{ d.host }}</span>
          </el-option>
        </el-select>
      </div>

      <div style="margin-bottom: 14px;">
        <label style="font-weight: 600; font-size: 13px; display: block; margin-bottom: 6px; color:#374151">
          测试提示词 (Prompt)
        </label>
        <el-input
          v-model="probePrompt"
          type="textarea"
          :rows="3"
          placeholder="请输入测试对话文本..."
        />
      </div>

      <!-- AI 响应结果区 -->
      <div v-if="probeResult" style="margin-top: 16px; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px; background: #f8fafc;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
          <span style="font-weight: 600; font-size: 13px;">
            <span v-if="probeResult.status === 'PASS'" style="color: #10b981;">验证通过 (已更新状态为 PASS)</span>
            <span v-else style="color: #ef4444;">模型验证失败</span>
          </span>
          <div>
            <el-tag size="small" type="info" style="margin-right: 6px;">响应延迟: {{ probeResult.latency_ms }} ms</el-tag>
            <el-tag size="small" type="success">生成 Token 数: {{ probeResult.completion_tokens || 0 }}</el-tag>
          </div>
        </div>
        <div style="background: #0f172a; color: #38bdf8; padding: 14px; border-radius: 6px; font-family: consolas, monospace; font-size: 13px; white-space: pre-wrap; word-break: break-all; max-height: 240px; overflow-y: auto;">
          {{ probeResult.reply_text || probeResult.message }}
        </div>
      </div>

      <template #footer>
        <el-button @click="runTestModalVisible = false">关闭</el-button>
        <el-button
          type="success"
          :loading="probing"
          @click="submitProbeChat"
        >
          <el-icon><Promotion /></el-icon>
          {{ probeTargetModel?.is_external ? '发送测试请求' : '部署并开启实时控制台' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { useTestStore } from '../stores/testStore'
import { apiListModels, apiCreateModel, apiUpdateModel, apiDeleteModel } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import { useDragSelect } from '../utils/dragSelect'

const api = axios.create({ baseURL: '/api' })
const testStore = useTestStore()
const tableRef = ref(null)
const models = ref([])
const devices = ref([])
const loading = ref(false)
const selectedModels = ref([])

useDragSelect(tableRef, models)

const dialogVisible = ref(false)
const activeEditTab = ref('basic')
const editing = ref(null)
const currentModel = ref(null)

const importSyncModalVisible = ref(false)
const activeSyncTab = ref('tos')

const runTestModalVisible = ref(false)
const probeTargetModel = ref(null)
const probePrompt = ref('你好！请做个简要的自我介绍，并说明你的核心技能。')
const probeResult = ref(null)
const probing = ref(false)
const probeDeviceId = ref(null)

const effectiveProbeApiBase = computed(() => {
  if (!probeTargetModel.value) return ''
  if (probeTargetModel.value.api_base) {
    return probeTargetModel.value.api_base
  }
  if (probeDeviceId.value) {
    const dev = devices.value.find(d => d.id === probeDeviceId.value)
    if (dev) return `http://${dev.host}:8300/v1`
  }
  const firstOnline = devices.value.find(d => d.status === 'online') || devices.value[0]
  if (firstOnline) return `http://${firstOnline.host}:8300/v1`
  return 'http://127.0.0.1:8300/v1'
})

const cleanDeviceId = ref(null)
const cleaning = ref(false)

const dcEditVisible = ref(false)
const newDcDeviceId = ref(null)
const editingDc = ref(null)
const editingDcCommand = ref('')

const onlineDownloading = ref(false)
const onlineForm = ref({
  source: 'ModelScope',
  repo_id: '',
  group_name: 'NVIDIA_jetson_AGX_Thor'
})

const showHgDialog = ref(false)
const customHardwareGroups = ref([])
const newHgName = ref('')
const newHgDesc = ref('')

const loadCustomHardwareGroups = async () => {
  try {
    const res = await api.get('/hardware-groups')
    customHardwareGroups.value = res.data
  } catch (err) {
    console.error(err)
  }
}

const openHardwareGroupsDialog = () => {
  loadCustomHardwareGroups()
  showHgDialog.value = true
}

const createHardwareGroup = async () => {
  if (!newHgName.value.trim()) return ElMessage.warning('请输入硬件组名称')
  try {
    await api.post('/hardware-groups', {
      name: newHgName.value.trim(),
      description: newHgDesc.value.trim()
    })
    ElMessage.success('硬件组添加成功')
    newHgName.value = ''
    newHgDesc.value = ''
    loadCustomHardwareGroups()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '创建硬件组失败')
  }
}

const deleteHardwareGroup = async (id) => {
  try {
    await api.delete(`/hardware-groups/${id}`)
    ElMessage.success('已删除硬件组')
    loadCustomHardwareGroups()
  } catch (err) {
    ElMessage.error('删除硬件组失败')
  }
}

const openImportSyncDialog = () => {
  scanForm.value.group_name = activeGroup.value === 'ALL' ? 'NVIDIA_jetson_AGX_Thor' : activeGroup.value
  onlineForm.value.group_name = scanForm.value.group_name
  scannedItems.value = []
  selectedScanItems.value = []
  importSyncModalVisible.value = true
}

const submitOnlineDownload = async () => {
  if (!onlineForm.value.repo_id.trim()) return ElMessage.warning('请输入仓库 Repo ID')
  onlineDownloading.value = true
  try {
    const res = await api.post('/models/download-online', onlineForm.value)
    ElMessage.success(res.data.message || '已提交联网下载')
    importSyncModalVisible.value = false
    loadModels()
  } catch (err) {
    ElMessage.error('提交失败')
  } finally {
    onlineDownloading.value = false
  }
}

const activeGroup = ref('ALL')
const defaultGroupOptions = [
  { label: '全部硬件组', value: 'ALL' },
  { label: 'NVIDIA AGX Thor', value: 'NVIDIA_jetson_AGX_Thor' },
  { label: '沐曦 C500 / N260', value: '沐曦C500/N260' },
  { label: 'NVIDIA GPU 服务器', value: '英伟达服务器' },
]

const groupOptions = computed(() => {
  const list = [...defaultGroupOptions]
  const existingValues = new Set(list.map(g => g.value))
  customHardwareGroups.value.forEach(cg => {
    if (!existingValues.has(cg.name)) {
      list.push({ label: cg.name, value: cg.name })
    }
  })
  return list
})

const batchTargetGroup = ref('NVIDIA_jetson_AGX_Thor')
const batchUpdatingGroup = ref(false)

const filteredModels = computed(() => {
  let list
  if (activeGroup.value === 'ALL') {
    list = models.value
  } else {
    list = models.value.filter(m => (m.group_name || 'NVIDIA_jetson_AGX_Thor') === activeGroup.value)
  }
  return list.map((m, i) => ({ ...m, idx: i + 1 }))
})

const groupCounts = computed(() => {
  const counts = { 'ALL': models.value.length }
  groupOptions.value.forEach(g => {
    if (g.value !== 'ALL') counts[g.value] = 0
  })
  models.value.forEach(m => {
    const g = m.group_name || 'NVIDIA_jetson_AGX_Thor'
    counts[g] = (counts[g] || 0) + 1
  })
  return counts
})

const handleBatchUpdateGroup = async () => {
  if (selectedModels.value.length === 0) return
  batchUpdatingGroup.value = true
  try {
    const slugs = selectedModels.value.map(m => m.slug)
    await api.post('/models/batch-group', {
      slugs,
      group_name: batchTargetGroup.value
    })
    ElMessage.success(`已将选中的 ${slugs.length} 个模型划归至 [${batchTargetGroup.value}]`)
    selectedModels.value = []
    await loadModels()
  } catch (e) {
    ElMessage.error('批量划归硬件组失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    batchUpdatingGroup.value = false
  }
}

const handleSelectionChange = (val) => {
  selectedModels.value = val
}

const handleRowClick = (row) => {
  if (tableRef.value) {
    tableRef.value.toggleRowSelection(row)
  }
}

const getSpecCategory = (row) => {
  const name = (row.name || '').toLowerCase()
  if (name.includes('2b') || name.includes('1.5b') || name.includes('0.5b') || name.includes('1b') || name.includes('3b')) return 'small'
  if (name.includes('7b') || name.includes('8b') || name.includes('13b') || name.includes('9b') || name.includes('14b')) return 'medium'
  return 'large'
}

const formatCmdPretty = (cmd) => {
  if (!cmd) return '未配置命令'
  let formatted = cmd.trim()
  formatted = formatted
    .replace(/\s+--/g, ' \\\n  --')
    .replace(/\s+-e\s+/g, ' \\\n  -e ')
    .replace(/\s+-v\s+/g, ' \\\n  -v ')
  return formatted
}

const copyCmd = (cmd) => {
  if (!cmd) return
  navigator.clipboard.writeText(cmd)
  ElMessage.success('运行指令已成功复制到剪贴板')
}

const scanningTOS = ref(false)
const importingTOS = ref(false)
const scanForm = ref({
  bucket_name: 'ai-hub',
  prefix: 'models/',
  group_name: 'NVIDIA_jetson_AGX_Thor'
})
const scannedItems = ref([])
const selectedScanItems = ref([])

const handlePreviewTOS = async () => {
  scanningTOS.value = true
  try {
    const resp = await api.post('/models/preview-tos-scan', scanForm.value)
    scannedItems.value = resp.data.items || []
    if (scannedItems.value.length === 0) {
      ElMessage.info('该路径下未扫描到匹配的模型文件')
    } else {
      ElMessage.success(`扫描完成，找到 ${scannedItems.value.length} 个模型文件`)
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '扫描 TOS 仓库失败')
  } finally {
    scanningTOS.value = false
  }
}

const handleScanSelectionChange = (selection) => {
  selectedScanItems.value = selection
}

const handleConfirmImportTOS = async () => {
  if (selectedScanItems.value.length === 0) return
  importingTOS.value = true
  try {
    const resp = await api.post('/models/import-tos-selected', {
      group_name: scanForm.value.group_name,
      bucket_name: scanForm.value.bucket_name,
      selected_items: selectedScanItems.value.map(item => ({
        key: item.key,
        model_name: item.model_name,
        slug: item.slug,
        tos_path: item.tos_path
      }))
    })
    ElMessage.success(resp.data.message || '选中的模型导入成功')
    importSyncModalVisible.value = false
    await loadModels()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '导入模型失败')
  } finally {
    importingTOS.value = false
  }
}

const loadModels = async () => {
  loading.value = true
  try {
    models.value = await apiListModels()
  } catch (e) { console.error(e) }
  loading.value = false
}

const loadDevices = async () => {
  try { devices.value = (await api.get('/devices')).data } catch (e) { /* */ }
}

const testingConnection = ref(false)
const form = ref({
  name: '',
  slug: '',
  group_name: 'NVIDIA_jetson_AGX_Thor',
  docker_command: '',
  tos_path: '',
  is_external: false,
  api_base: '',
  api_key: 'EMPTY',
  model_endpoint_name: '',
})

const handleTestConnection = async () => {
  if (!form.value.api_base) return ElMessage.warning('请先填写 API Base URL')
  testingConnection.value = true
  try {
    const res = await api.post('/models/test-connection', {
      api_base: form.value.api_base,
      api_key: form.value.api_key || 'EMPTY',
      model_endpoint_name: form.value.model_endpoint_name,
    })
    ElMessage.success(res.data.message || 'API 连通性测试通过！')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '无法连接到指定的 API 服务')
  } finally {
    testingConnection.value = false
  }
}

const showAddDialog = () => {
  editing.value = null
  currentModel.value = null
  activeEditTab.value = 'basic'
  const defaultGrp = activeGroup.value === 'ALL' ? 'NVIDIA_jetson_AGX_Thor' : activeGroup.value
  form.value = {
    name: '',
    slug: '',
    group_name: defaultGrp,
    docker_command: '',
    tos_path: '',
    is_external: false,
    api_base: '',
    api_key: 'EMPTY',
    model_endpoint_name: '',
  }
  dialogVisible.value = true
}

const openEditModel = (row) => {
  const target = row || models.value[0]
  if (!target) return
  editing.value = target.slug
  currentModel.value = target
  activeEditTab.value = 'basic'
  form.value = {
    name: target.name,
    slug: target.slug,
    group_name: target.group_name || 'NVIDIA_jetson_AGX_Thor',
    docker_command: target.docker_command || '',
    tos_path: target.tos_path || '',
    is_external: Boolean(target.is_external),
    api_base: target.api_base || '',
    api_key: target.api_key || 'EMPTY',
    model_endpoint_name: target.model_endpoint_name || '',
  }
  dialogVisible.value = true
}

const handleSave = async () => {
  try {
    if (!form.value.slug && form.value.name) {
      form.value.slug = form.value.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '')
    }
    if (editing.value) {
      await apiUpdateModel(editing.value, form.value)
    } else {
      await apiCreateModel(form.value)
    }
    dialogVisible.value = false
    await loadModels()
    ElMessage.success('模型配置已保存')
  } catch (e) { ElMessage.error(e.response?.data?.detail || '保存模型失败') }
}

const handleSingleDelete = async (slug) => {
  try {
    await apiDeleteModel(slug)
    await loadModels()
    ElMessage.success('模型配置已成功删除')
  } catch (e) {
    ElMessage.error('删除过程发生异常')
  }
}

const confirmDeleteSelected = () => {
  if (selectedModels.value.length === 0) return
  ElMessageBox.confirm(
    `确定要永久删除选中的 ${selectedModels.value.length} 个模型配置吗？删除后相关测试数据及配置将被清除，此操作不可撤销！`,
    '删除确认',
    {
      confirmButtonText: '确认永久删除',
      cancelButtonText: '取消',
      type: 'warning',
      center: true,
    }
  ).then(() => {
    handleDeleteSelected()
  }).catch(() => {})
}

const handleDeleteSelected = async () => {
  if (selectedModels.value.length === 0) return
  loading.value = true
  try {
    for (const m of selectedModels.value) {
      await apiDeleteModel(m.slug)
    }
    selectedModels.value = []
    await loadModels()
    ElMessage.success('选中的模型已成功删除')
  } catch (e) {
    ElMessage.error('删除过程发生异常: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

const boundDevices = computed(() => {
  if (!probeTargetModel.value) return devices.value
  if (probeTargetModel.value.device_configs && probeTargetModel.value.device_configs.length > 0) {
    const boundIds = probeTargetModel.value.device_configs.map(dc => dc.device_id)
    const list = devices.value.filter(d => boundIds.includes(d.id))
    if (list.length > 0) return list
  }
  return devices.value
})

const openRunTestDialog = (row) => {
  const target = row || models.value[0]
  if (!target) return
  probeTargetModel.value = target
  probePrompt.value = '你好！请做个简要的自我介绍，并说明你的核心技能。'
  probeResult.value = null
  probeDeviceId.value = target.device_configs?.[0]?.device_id || (boundDevices.value[0]?.id || null)
  runTestModalVisible.value = true
}

const submitProbeChat = async () => {
  if (!probeTargetModel.value) return

  if (!probeTargetModel.value.is_external) {
    const targetDev = devices.value.find(d => d.id === probeDeviceId.value)
    const devName = targetDev ? targetDev.name : '目标算力节点'
    runTestModalVisible.value = false
    testStore.startTest(probeTargetModel.value.slug, probeTargetModel.value.name, probeDeviceId.value, devName)
    return
  }

  probing.value = true
  probeResult.value = null
  try {
    const res = await api.post('/models/probe-chat', {
      model_slug: probeTargetModel.value.slug,
      prompt: probePrompt.value,
      api_base: effectiveProbeApiBase.value,
      device_id: probeDeviceId.value,
      api_key: probeTargetModel.value.api_key || 'EMPTY',
      model_endpoint_name: probeTargetModel.value.model_endpoint_name || probeTargetModel.value.slug,
    })
    probeResult.value = res.data
    if (res.data.status === 'PASS') {
      ElMessage.success('模型连通性验证成功，已被标记为 PASS')
      loadModels()
    } else {
      ElMessage.error(res.data.message || '模型连通性验证未通过')
    }
  } catch (e) {
    probeResult.value = {
      status: 'FAIL',
      message: e.response?.data?.detail || e.message,
      reply_text: '模型验证失败: ' + (e.response?.data?.detail || e.message),
      latency_ms: 0,
      completion_tokens: 0,
    }
    ElMessage.error('模型验证失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    probing.value = false
  }
}

watch(() => testStore.finalResult, (res) => {
  if (res && res.status === 'PASS') {
    loadModels()
  }
})

const handleStopContainer = async () => {
  cleaning.value = true
  try {
    const params = cleanDeviceId.value ? { device_id: cleanDeviceId.value } : {}
    const resp = await api.post('/models/stop-test-container', null, { params })
    ElMessage.success(resp.data.message || '残留容器与资源已被清理')
  } catch (e) { ElMessage.error('清理容器失败') }
  cleaning.value = false
}

const currentDeviceConfigs = computed(() => currentModel.value?.device_configs || [])
const availableDevices = computed(() => {
  if (!currentModel.value) return devices.value
  const configuredIds = (currentModel.value.device_configs || []).map(dc => dc.device_id)
  return devices.value.filter(d => !configuredIds.includes(d.id))
})

const addDc = async () => {
  if (!newDcDeviceId.value || !currentModel.value) return
  try {
    await api.post(`/models/${currentModel.value.slug}/device-configs`, {
      device_id: newDcDeviceId.value,
      docker_command: currentModel.value.docker_command || '',
    })
    await refreshCurrentModel()
    newDcDeviceId.value = null
    ElMessage.success('设备专属配置添加成功')
  } catch (e) { ElMessage.error('添加设备配置失败') }
}

const editDc = (dc) => {
  editingDc.value = dc
  editingDcCommand.value = dc.docker_command || currentModel.value?.docker_command || ''
  dcEditVisible.value = true
}

const applySmartRecommendation = () => {
  let cmd = editingDcCommand.value || currentModel.value?.docker_command || form.value.docker_command || ''
  const mName = (currentModel.value?.name || form.value.name || '').toLowerCase()

  let maxLen = 4096
  let memoryUtil = 0.85
  let tpSize = 1

  if (mName.includes('70b') || mName.includes('72b')) {
    tpSize = 4
    maxLen = 4096
    memoryUtil = 0.90
  } else if (mName.includes('30b') || mName.includes('32b') || mName.includes('35b')) {
    tpSize = 2
    maxLen = 8192
    memoryUtil = 0.88
  } else if (mName.includes('14b')) {
    tpSize = 1
    maxLen = 8192
    memoryUtil = 0.85
  } else {
    tpSize = 1
    maxLen = 8192
    memoryUtil = 0.85
  }

  if (cmd.includes('--max-model-len')) {
    cmd = cmd.replace(/--max-model-len\s+\d+/, `--max-model-len ${maxLen}`)
  } else {
    cmd += ` \\\n  --max-model-len ${maxLen}`
  }

  if (cmd.includes('--gpu-memory-utilization')) {
    cmd = cmd.replace(/--gpu-memory-utilization\s+[\d\.]+/, `--gpu-memory-utilization ${memoryUtil}`)
  } else {
    cmd += ` \\\n  --gpu-memory-utilization ${memoryUtil}`
  }

  if (cmd.includes('--tensor-parallel-size')) {
    cmd = cmd.replace(/--tensor-parallel-size\s+\d+/, `--tensor-parallel-size ${tpSize}`)
  } else {
    cmd += ` \\\n  --tensor-parallel-size ${tpSize}`
  }

  editingDcCommand.value = cmd
  ElMessage.success(`推荐配置已应用: max_model_len=${maxLen}, gpu_mem=${memoryUtil}, tp=${tpSize}`)
}

const saveDcCommand = async () => {
  if (!editingDc.value || !currentModel.value) return
  try {
    await api.put(`/models/${currentModel.value.slug}/device-configs/${editingDc.value.id}`, {
      docker_command: editingDcCommand.value,
    })
    dcEditVisible.value = false
    await refreshCurrentModel()
    ElMessage.success('设备指令配置已保存')
  } catch (e) { ElMessage.error('保存失败') }
}

const deleteDc = async (configId) => {
  if (!currentModel.value) return
  try {
    await api.delete(`/models/${currentModel.value.slug}/device-configs/${configId}`)
    await refreshCurrentModel()
    ElMessage.success('设备专属配置已解除')
  } catch (e) { ElMessage.error('解绑失败') }
}

const refreshCurrentModel = async () => {
  if (!currentModel.value) return
  try {
    const resp = await apiListModels()
    const updated = resp.find(m => m.slug === currentModel.value.slug)
    if (updated) {
      currentModel.value = updated
      const idx = models.value.findIndex(m => m.slug === currentModel.value.slug)
      if (idx >= 0) models.value[idx] = updated
    }
  } catch (e) { console.error(e) }
}

onMounted(() => { loadModels(); loadDevices(); loadCustomHardwareGroups() })
</script>

<style scoped>
.model-mgmt-page { padding: 0; }

.top-toolbar {
  background: #ffffff; padding: 14px 18px; border-radius: 8px; border: 1px solid #e2e8f0;
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.03);
}
.toolbar-left, .toolbar-right { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }

.group-tab-bar {
  display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap;
}
.group-tab-item {
  background: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px;
  padding: 8px 16px; font-size: 13px; font-weight: 500; color: #475569;
  display: flex; align-items: center; gap: 8px; cursor: pointer;
  transition: all 0.2s ease; box-shadow: 0 1px 2px rgba(0,0,0,0.02);
}
.group-tab-item:hover {
  border-color: #2563eb; color: #1d4ed8; background: #f8fafc;
}
.group-tab-item.active {
  background: #0f172a; color: #38bdf8; border-color: #0f172a;
  box-shadow: 0 2px 8px rgba(15,23,42,0.15); font-weight: 600;
}
.group-tab-label { flex: 1; }
.group-tab-count {
  background: rgba(56, 189, 248, 0.12); color: #0284c7; border-radius: 10px;
  padding: 2px 8px; font-size: 11px; font-weight: 700;
}
.group-tab-item.active .group-tab-count {
  background: rgba(56, 189, 248, 0.25); color: #7dd3fc;
}

.custom-table { background: #ffffff; border-radius: 8px; cursor: pointer; width: 100%; }
.device-config-tags { display: flex; flex-wrap: wrap; gap: 3px; }

.dc-action-row {
  display: flex;
  gap: 6px;
  align-items: center;
  justify-content: center;
}

.cmd-pill-trigger {
  background: #0f172a; color: #38bdf8; border-radius: 6px; padding: 5px 10px;
  font-family: monospace; font-size: 11px; display: inline-flex; align-items: center;
  gap: 8px; cursor: pointer; width: 100%; transition: all 0.2s ease;
}
.cmd-pill-trigger:hover { background: #1e293b; color: #7dd3fc; }
.cmd-text-ellipsis {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  flex: 1; min-width: 0;
}
.cmd-copy-icon { font-size: 13px; color: #94a3b8; flex-shrink: 0; }

.popover-cmd-box { background: #0f172a; padding: 12px; border-radius: 8px; color: #e2e8f0; }
.popover-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; border-bottom: 1px solid #1e293b; padding-bottom: 6px; }
.popover-title { font-size: 13px; font-weight: 600; color: #38bdf8; }

.cmd-block-pretty {
  background: #020617; color: #38bdf8; padding: 10px 12px; border-radius: 6px;
  font-family: monospace; font-size: 11px; line-height: 1.6; max-height: 260px;
  overflow-y: auto; white-space: pre-wrap; word-break: break-all; margin: 0;
}
</style>

<style>
.custom-table .selected-row td {
  background: #f0f9ff !important;
}
</style>
