<template>
  <div id="app-container">
    <!-- 登录页：全屏独立渲染，不带侧边栏和头部 -->
    <router-view v-if="isLoginPage" />

    <!-- 主应用布局 -->
    <el-container v-else style="height:100vh">
      <!-- 左侧科技感侧边栏 -->
      <el-aside width="220px" class="app-sidebar">
        <div class="sidebar-brand">
          <div class="logo-icon-wrapper">
            <svg class="chip-svg" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect x="5" y="5" width="14" height="14" rx="2" stroke="url(#paint0_linear)" stroke-width="2"/>
              <path d="M9 9H15V15H9V9Z" fill="url(#paint1_linear)"/>
              <path d="M2 9H5M2 15H5M19 9H22M19 15H22M9 2V5M15 2V5M9 19V22M15 19V22" stroke="url(#paint2_linear)" stroke-width="2" stroke-linecap="round"/>
              <defs>
                <linearGradient id="paint0_linear" x1="5" y1="5" x2="19" y2="19" gradientUnits="userSpaceOnUse">
                  <stop stop-color="#60A5FA"/>
                  <stop offset="1" stop-color="#3B82F6"/>
                </linearGradient>
                <linearGradient id="paint1_linear" x1="9" y1="9" x2="15" y2="15" gradientUnits="userSpaceOnUse">
                  <stop stop-color="#3B82F6"/>
                  <stop offset="1" stop-color="#1D4ED8"/>
                </linearGradient>
                <linearGradient id="paint2_linear" x1="2" y1="2" x2="22" y2="22" gradientUnits="userSpaceOnUse">
                  <stop stop-color="#93C5FD"/>
                  <stop offset="1" stop-color="#3B82F6"/>
                </linearGradient>
              </defs>
            </svg>
          </div>
          <div class="brand-text">
            <h2 class="title">AONI 模型测试平台</h2>
            <span class="subtitle">Jetson Thor 运维评测</span>
          </div>
        </div>

        <div class="status-box">
          <div class="status-item">
            <span class="pulse-dot" :class="backendStatus === 'ok' ? 'online' : 'offline'"></span>
            <span class="status-label">核心后端服务: {{ backendStatus === 'ok' ? '正常运行' : '连接异常' }}</span>
          </div>
        </div>

        <el-menu :default-active="activeMenu" router class="sidebar-menu">
          <el-menu-item index="/">
            <el-icon><List /></el-icon>
            <span>任务管理</span>
          </el-menu-item>
          <el-menu-item index="/models">
            <el-icon><Cpu /></el-icon>
            <span>模型管理</span>
          </el-menu-item>
          <el-menu-item index="/devices">
            <el-icon><Monitor /></el-icon>
            <span>设备管理</span>
          </el-menu-item>
          <el-menu-item index="/reports">
            <el-icon><DataAnalysis /></el-icon>
            <span>测试报告</span>
          </el-menu-item>
          <el-menu-item v-if="authStore.isAdmin" index="/users">
            <el-icon><User /></el-icon>
            <span>用户管理</span>
          </el-menu-item>
        </el-menu>

        <div class="sidebar-user-bar">
          <div class="user-avatar-mini">{{ (authStore.user?.display_name || authStore.user?.username || 'U')[0].toUpperCase() }}</div>
          <div class="user-meta">
            <div class="user-name">{{ authStore.user?.display_name || authStore.user?.username }}</div>
            <div class="user-role">{{ authStore.user?.role === 'admin' ? '管理员' : '普通用户' }}</div>
          </div>
          <el-tooltip content="退出登录" placement="right">
            <el-button circle size="small" class="logout-btn" @click="handleLogout">
              <el-icon><SwitchButton /></el-icon>
            </el-button>
          </el-tooltip>
        </div>
      </el-aside>

      <!-- 右侧主区域 -->
      <el-container>
        <el-header height="64px" class="app-header">
          <div class="kpi-bar">
            <div class="kpi-card">
              <div class="kpi-icon-box blue"><el-icon><Monitor /></el-icon></div>
              <div class="kpi-info">
                <span class="kpi-value">{{ onlineDeviceCount }} / {{ totalDeviceCount }}</span>
                <span class="kpi-label">在线设备数</span>
              </div>
            </div>

            <div class="kpi-card">
              <div class="kpi-icon-box purple"><el-icon><Cpu /></el-icon></div>
              <div class="kpi-info">
                <span class="kpi-value">{{ passModelCount }} / {{ modelCount }}</span>
                <span class="kpi-label">已验证模型</span>
              </div>
            </div>

            <div class="kpi-card">
              <div class="kpi-icon-box green"><el-icon><List /></el-icon></div>
              <div class="kpi-info">
                <span class="kpi-value">{{ runningTaskCount }} / {{ taskCount }}</span>
                <span class="kpi-label">运行 / 总任务数</span>
              </div>
            </div>

            <div class="kpi-card">
              <div class="kpi-icon-box orange"><el-icon><DataAnalysis /></el-icon></div>
              <div class="kpi-info">
                <span class="kpi-value">{{ reportCount }}</span>
                <span class="kpi-label">已生成评测报告</span>
              </div>
            </div>
          </div>
        </el-header>

        <el-main class="app-main">
          <router-view @refresh-kpi="loadStats" />
        </el-main>
      </el-container>
    </el-container>

    <!-- 右下角悬浮后台运行控制面板 -->
    <div
      v-if="testStore.modelName && !testStore.isModalVisible"
      class="floating-test-widget"
      @click="testStore.openModal"
    >
      <div class="widget-header">
        <span class="pulse-dot" :class="testStore.isRunning ? 'online' : 'done'"></span>
        <span class="widget-title">{{ testStore.isRunning ? '模型验证后台执行中' : '模型验证已完成' }}</span>
        <div class="widget-actions">
          <el-icon class="widget-icon" title="展开控制台" @click.stop="testStore.openModal"><FullScreen /></el-icon>
          <el-icon class="widget-icon close-icon" title="关闭并清除" @click.stop="testStore.resetTest"><Close /></el-icon>
        </div>
      </div>
      <div class="widget-body">
        <div class="widget-model-name">{{ testStore.modelName }} ({{ testStore.deviceName }})</div>
        <el-progress
          :percentage="testStore.progress"
          :status="testStore.progress === 100 ? (testStore.finalResult?.status === 'PASS' ? 'success' : 'exception') : ''"
          :stroke-width="6"
        />
      </div>
      <div class="widget-footer">点击展开查看实时控制台与日志</div>
    </div>

    <!-- 模型连通性验证控制台 Modal -->
    <el-dialog
      v-model="testStore.isModalVisible"
      :title="`模型验证控制台 — ${testStore.modelName}`"
      width="750px"
      :close-on-click-modal="false"
    >
      <div class="stream-dialog-body">
        <el-steps :active="testStore.step" finish-status="success" align-center style="margin-bottom:20px">
          <el-step title="环境准备" description="清理历史容器" />
          <el-step title="启动容器" description="容器实例初始化" />
          <el-step title="加载引擎" description="等待推理服务" />
          <el-step title="探针测试" description="响应格式校验" />
        </el-steps>

        <el-progress
          :percentage="testStore.progress"
          :status="testStore.progress === 100 ? (testStore.finalResult?.status === 'PASS' ? 'success' : 'exception') : ''"
          style="margin-bottom:16px"
        />

        <div class="terminal-box" ref="terminalBoxRef">
          <div v-for="(log, idx) in testStore.logs" :key="idx" class="log-line" :class="log.stage.toLowerCase()">
            <span class="log-time">[{{ log.time }}]</span>
            <span class="log-stage">[{{ log.stage }}]</span>
            <span class="log-msg">{{ log.msg }}</span>
          </div>
          <div v-if="testStore.isRunning" class="log-loading">
            <el-icon class="is-loading"><Loading /></el-icon>
            <span v-if="currentStageIsExtract" style="color:#c084fc;font-weight:bold">
              📦 正在解压模型文件包并写入磁盘，请稍候...
            </span>
            <span v-else-if="currentStageIsDownload" style="color:#38bdf8;font-weight:bold">
              ☁️ 正在自动从 TOS 云端下载模型文件，请稍候...
            </span>
            <span v-else>实时日志与响应推送中...</span>
          </div>
        </div>

        <div v-if="testStore.finalResult" class="test-final-card" :class="testStore.finalResult.status.toLowerCase()">
          <div class="final-header">
            <el-tag :type="testStore.finalResult.status === 'PASS' ? 'success' : 'danger'" size="large" style="font-size:14px;padding:4px 12px">
              {{ testStore.finalResult.status === 'PASS' ? '验证通过' : '验证未通过' }}
            </el-tag>
            <span style="font-size:13px;color:#303133">目标节点: <b>{{ testStore.finalResult.device_name || testStore.deviceName }}</b></span>
            <el-tag type="info" size="small">容器资源已成功归零释放</el-tag>
          </div>

          <div v-if="testStore.finalResult.reply" class="chat-bubble-wrapper">
            <div class="chat-row user-row">
              <div class="avatar user-avatar">User</div>
              <div class="bubble user-bubble">你好，请简要介绍一下你的模型架构与特点。</div>
            </div>

            <div class="chat-row ai-row">
              <div class="avatar ai-avatar">AI</div>
              <div class="bubble ai-bubble">
                <div class="ai-model-tag">{{ testStore.finalResult.model || testStore.modelName }}</div>
                <div v-if="testStore.finalResult.reasoning" class="reasoning-box">
                  <div class="reasoning-title">Thinking Process:</div>
                  {{ testStore.finalResult.reasoning }}
                </div>
                <div class="ai-reply-text">{{ testStore.finalResult.reply }}</div>
              </div>
            </div>
          </div>

          <div v-if="testStore.finalResult.detail && testStore.finalResult?.status === 'FAIL'" class="err-section">
            <div style="font-weight:bold;margin-bottom:4px;color:#c45656">异常详情:</div>
            <div class="err-content">{{ testStore.finalResult.detail }}</div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button v-if="testStore.isRunning" type="info" @click="testStore.closeModal">后台运行</el-button>
        <el-button v-if="!testStore.isRunning" @click="testStore.closeModal">保留横幅</el-button>
        <el-button type="primary" @click="testStore.resetTest">完成并关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTestStore } from './stores/testStore'
import { useAuthStore } from './stores/authStore'
import { apiHealth } from './api/index.js'
import axios from 'axios'

const route = useRoute()
const router = useRouter()
const testStore = useTestStore()
const authStore = useAuthStore()
const backendStatus = ref('unknown')
const terminalBoxRef = ref(null)

// 判断当前是否在登录页
const isLoginPage = computed(() => route.name === 'Login')

const currentStageIsDownload = computed(() => {
  const logs = testStore.logs
  if (!logs || logs.length === 0) return false
  const lastLog = logs[logs.length - 1]
  const stage = (lastLog.stage || '').toUpperCase()
  const msg = lastLog.msg || ''
  return stage === 'DOWNLOADING' || stage === 'TOS_CLOUD' || msg.includes('Downloading') || msg.includes('.tar')
})

const currentStageIsExtract = computed(() => {
  const logs = testStore.logs
  if (!logs || logs.length === 0) return false
  const lastLog = logs[logs.length - 1]
  const stage = (lastLog.stage || '').toUpperCase()
  const msg = lastLog.msg || ''
  return stage === 'EXTRACTING' || msg.includes('Extracting') || msg.includes('Archive opened') || msg.includes('模型压缩包解压中')
})

// axios 401 自动登出
axios.interceptors.response.use(
  res => res,
  err => {
    if (err.response?.status === 401) {
      authStore.logout()
      router.push('/login')
    }
    return Promise.reject(err)
  }
)

const handleLogout = () => {
  authStore.logout()
  router.push('/login')
}

const totalDeviceCount = ref(0)
const onlineDeviceCount = ref(0)
const modelCount = ref(0)
const passModelCount = ref(0)
const taskCount = ref(0)
const runningTaskCount = ref(0)
const reportCount = ref(0)

const activeMenu = computed(() => {
  if (route.path.startsWith('/models')) return '/models'
  if (route.path.startsWith('/devices')) return '/devices'
  if (route.path.startsWith('/reports')) return '/reports'
  return '/'
})

watch(() => testStore.logs.length, () => {
  nextTick(() => {
    if (terminalBoxRef.value) {
      terminalBoxRef.value.scrollTop = terminalBoxRef.value.scrollHeight
    }
  })
})

const loadStats = async () => {
  try {
    const res = await apiHealth()
    backendStatus.value = res.status
  } catch {
    backendStatus.value = 'error'
  }

  try {
    const devs = (await axios.get('/api/devices')).data
    totalDeviceCount.value = devs.length
    onlineDeviceCount.value = devs.filter(d => d.status === 'online').length
  } catch {}

  try {
    const mdls = (await axios.get('/api/models')).data
    modelCount.value = mdls.length
    passModelCount.value = mdls.filter(m => m.status === 'PASS').length
  } catch {}

  try {
    const tsks = (await axios.get('/api/tasks')).data
    taskCount.value = tsks.length
    runningTaskCount.value = tsks.filter(t => t.status === 'running').length
  } catch {}

  try {
    const rpts = (await axios.get('/api/reports')).data
    reportCount.value = rpts.length
  } catch {}
}

onMounted(() => {
  loadStats()
  setInterval(loadStats, 15000)
})
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
#app-container { min-height: 100vh; background: #f3f4f6; position: relative; }

/* 侧边栏样式 */
.app-sidebar {
  background: #111827; color: #fff; display: flex; flex-direction: column;
  box-shadow: 2px 0 10px rgba(0,0,0,0.15); z-index: 10; overflow: hidden;
}
.sidebar-brand { padding: 20px 16px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid #1f2937; }
.logo-icon-wrapper { width: 38px; height: 38px; background: rgba(59, 130, 246, 0.15); border: 1px solid rgba(59, 130, 246, 0.3); border-radius: 8px; display: flex; align-items: center; justify-content: center; }
.chip-svg { width: 26px; height: 26px; }
.brand-text .title { font-size: 15px; font-weight: 700; color: #f9fafb; letter-spacing: 0.5px; }
.brand-text .subtitle { font-size: 11px; color: #9ca3af; }

.status-box { padding: 10px 16px; background: #1f2937; margin: 12px 12px 6px; border-radius: 6px; }
.status-item { display: flex; align-items: center; gap: 8px; }
.status-label { font-size: 12px; color: #d1d5db; }

.pulse-dot { width: 8px; height: 8px; border-radius: 50%; position: relative; }
.pulse-dot.online { background: #10b981; box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); animation: pulse-green 2s infinite; }
.pulse-dot.offline { background: #ef4444; }
.pulse-dot.done { background: #3b82f6; }

@keyframes pulse-green {
  0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
  70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
  100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}

.sidebar-menu { background: transparent !important; border-right: none !important; padding: 8px; flex: 1; }
.sidebar-menu .el-menu-item { color: #9ca3af !important; border-radius: 6px; margin-bottom: 4px; height: 44px; line-height: 44px; }
.sidebar-menu .el-menu-item:hover { color: #f3f4f6 !important; background: #1f2937 !important; }
.sidebar-menu .el-menu-item.is-active { color: #ffffff !important; background: #2563eb !important; font-weight: 600; }

/* 侧边栏底部用户信息条 */
.sidebar-user-bar {
  padding: 12px 14px;
  border-top: 1px solid #1f2937;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.user-avatar-mini {
  width: 32px; height: 32px; border-radius: 50%;
  background: linear-gradient(135deg, #2563eb, #7c3aed);
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 700; color: #fff; flex-shrink: 0;
}
.user-meta { flex: 1; min-width: 0; }
.user-name { font-size: 13px; font-weight: 600; color: #f3f4f6; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.user-role { font-size: 10px; color: #6b7280; margin-top: 1px; }
.logout-btn {
  background: transparent !important;
  border: 1px solid #374151 !important;
  color: #9ca3af !important;
  flex-shrink: 0;
}
.logout-btn:hover { border-color: #ef4444 !important; color: #ef4444 !important; }

.sidebar-footer { padding: 16px; border-top: 1px solid #1f2937; }
.footer-badge { background: #1f2937; padding: 10px 12px; border-radius: 6px; display: flex; flex-direction: column; }
.badge-title { font-size: 12px; font-weight: 600; color: #60a5fa; }
.badge-desc { font-size: 10px; color: #9ca3af; }

.app-header { background: #ffffff; border-bottom: 1px solid #e5e7eb; padding: 0 24px; display: flex; align-items: center; }
.kpi-bar { display: flex; align-items: center; gap: 24px; width: 100%; }
.kpi-card { display: flex; align-items: center; gap: 12px; background: #f9fafb; padding: 8px 16px; border-radius: 8px; border: 1px solid #f3f4f6; min-width: 180px; }
.kpi-icon-box { width: 36px; height: 36px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 18px; }
.kpi-icon-box.blue { background: #eff6ff; color: #2563eb; }
.kpi-icon-box.purple { background: #f5f3ff; color: #7c3aed; }
.kpi-icon-box.green { background: #ecfdf5; color: #059669; }
.kpi-icon-box.orange { background: #fff7ed; color: #ea580c; }
.kpi-info { display: flex; flex-direction: column; }
.kpi-value { font-size: 16px; font-weight: 700; color: #111827; }
.kpi-label { font-size: 11px; color: #6b7280; }

.app-main { padding: 20px 24px; overflow-y: auto; }

/* 右下角悬浮跑通测试卡片 Widget */
.floating-test-widget {
  position: fixed; right: 24px; bottom: 24px; width: 320px;
  background: #111827; color: #ffffff; border-radius: 10px; padding: 12px 14px;
  box-shadow: 0 10px 25px rgba(0,0,0,0.3); border: 1px solid #374151;
  cursor: pointer; z-index: 9999; transition: all 0.3s ease;
}
.floating-test-widget:hover { transform: translateY(-4px); border-color: #3b82f6; }
.widget-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.widget-title { font-size: 12px; font-weight: 700; color: #60a5fa; flex: 1; }
.widget-actions { display: flex; align-items: center; gap: 8px; }
.widget-icon { color: #9ca3af; font-size: 14px; cursor: pointer; transition: color 0.2s; }
.widget-icon:hover { color: #ffffff; }
.widget-icon.close-icon:hover { color: #ef4444; }
.widget-model-name { font-size: 13px; font-weight: 600; color: #f9fafb; margin-bottom: 6px; }
.widget-footer { font-size: 10px; color: #9ca3af; margin-top: 6px; text-align: right; }

/* 实时控制台样式 */
.stream-dialog-body { padding: 4px 0; }
.terminal-box {
  background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 6px;
  font-family: monospace; font-size: 12px; max-height: 220px; overflow-y: auto;
  line-height: 1.6; margin-bottom: 16px; border: 1px solid #333;
}
.log-line { white-space: pre-wrap; word-break: break-all; margin-bottom: 4px; }
.log-time { color: #858585; margin-right: 6px; }
.log-stage { color: #569cd6; font-weight: bold; margin-right: 6px; }
.log-line.error { color: #f48771; }
.log-line.done { color: #89d185; }
.log-line.downloading { color: #38bdf8; font-weight: 600; }
.log-line.tos_cloud { color: #c084fc; font-weight: 600; }
.log-line.extracting { color: #c084fc; font-weight: 600; }
.log-loading { color: #e5c07b; font-size: 12px; margin-top: 6px; display: flex; align-items: center; gap: 6px; }

.test-final-card { background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 8px; padding: 14px 16px; }
.test-final-card.pass { border-color: #b7eb8f; background: #f6ffed; }
.test-final-card.fail { border-color: #ffa39e; background: #fff2f0; }

.final-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.chat-bubble-wrapper { display: flex; flex-direction: column; gap: 12px; margin-top: 10px; }
.chat-row { display: flex; gap: 10px; align-items: flex-start; }
.avatar { width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: bold; color: #fff; flex-shrink: 0; }
.user-avatar { background: #4b5563; }
.ai-avatar { background: #10b981; }

.bubble { padding: 10px 14px; border-radius: 10px; font-size: 13px; line-height: 1.5; max-width: 88%; }
.user-bubble { background: #e5e7eb; color: #1f2937; }
.ai-bubble { background: #ffffff; color: #111827; border: 1px solid #d1d5db; }
.ai-model-tag { font-size: 11px; font-weight: 700; color: #2563eb; margin-bottom: 4px; }
.reasoning-box { background: #f3f4f6; border-left: 3px solid #9ca3af; padding: 6px 10px; font-size: 11px; color: #4b5563; margin-bottom: 6px; }
.ai-reply-text { font-size: 13px; color: #1F2937; white-space: pre-wrap; }

.err-content { background: #fff; padding: 10px 14px; border-radius: 4px; border: 1px solid #ffccc7; font-size: 13px; color: #c45656; }

/* 全局删除确认框美化 */
.el-popconfirm__main {
  padding: 6px 0 12px;
}
.el-popconfirm .el-popconfirm__action {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.el-popper.is-light.el-popconfirm__popper {
  border-radius: 10px !important;
  box-shadow: 0 8px 24px rgba(0,0,0,0.12) !important;
  border: 1px solid #e5e7eb !important;
  padding: 14px 16px !important;
  min-width: 220px !important;
}

/* 全局表格长按拖拽划选/框选样式 */
.drag-select-box {
  position: fixed;
  z-index: 99999;
  background: rgba(37, 99, 235, 0.18);
  border: 1px dashed #2563eb;
  border-radius: 4px;
  pointer-events: none;
  box-shadow: 0 0 12px rgba(37, 99, 235, 0.25);
}
</style>
