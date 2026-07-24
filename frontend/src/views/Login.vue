<template>
  <div class="login-page" :class="`theme-${currentSkin}`" @mousemove="handleMouseMove">
    <!-- 1. 交互式 Canvas 神经网络粒子与光斑背景 -->
    <canvas ref="canvasRef" class="particle-canvas"></canvas>

    <!-- 2. 背景多重矢量图案与扫描线 -->
    <div class="login-bg">
      <div class="wallpaper-layer"></div>
      <div class="scanline"></div>
      <svg class="bg-pattern-svg" xmlns="http://www.w3.org/2000/svg" width="100%" height="100%">
        <defs>
          <pattern id="grid-pattern" width="60" height="60" patternUnits="userSpaceOnUse">
            <path d="M 60 0 L 0 0 0 60" fill="none" stroke="rgba(255, 255, 255, 0.05)" stroke-width="1"/>
            <circle cx="60" cy="0" r="1.5" fill="rgba(255, 255, 255, 0.2)"/>
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#grid-pattern)" />
      </svg>
      <div class="bg-orb orb-1"></div>
      <div class="bg-orb orb-2"></div>
      <div class="bg-orb orb-3"></div>
    </div>

    <!-- 3. 顶部皮肤主题切换胶囊 -->
    <div class="skin-switcher-pill">
      <span class="switcher-label">🎨 皮肤主题:</span>
      <div
        v-for="s in skins"
        :key="s.id"
        class="skin-chip"
        :class="{ active: currentSkin === s.id }"
        @click="setSkin(s.id)"
        :title="s.name"
      >
        <span class="skin-color-dot" :style="{ background: s.dotColor }"></span>
        <span class="skin-name">{{ s.label }}</span>
      </div>
    </div>

    <!-- 4. 登录卡片容器 (带 3D 悬浮科技徽章) -->
    <div class="card-container">
      <!-- 3D 悬浮徽章 1 (左侧算力) -->
      <div class="floating-badge badge-left">
        <span class="pulse-dot green"></span>
        <span class="badge-icon">⚡</span>
        <div class="badge-text">
          <div class="badge-title">NVIDIA AGX Thor</div>
          <div class="badge-sub">8x Cluster Engine</div>
        </div>
      </div>

      <!-- 3D 悬浮徽章 2 (右侧安全) -->
      <div class="floating-badge badge-right">
        <span class="pulse-dot blue"></span>
        <span class="badge-icon">🛡️</span>
        <div class="badge-text">
          <div class="badge-title">20min 心跳机制</div>
          <div class="badge-sub">单设备在线防护</div>
        </div>
      </div>

      <!-- 3D 悬浮徽章 3 (底部基准) -->
      <div class="floating-badge badge-bottom">
        <span class="pulse-dot purple"></span>
        <span class="badge-icon">🔥</span>
        <div class="badge-text">
          <div class="badge-title">vLLM & Accuracy</div>
          <div class="badge-sub">基准测试矩阵</div>
        </div>
      </div>

      <!-- 登录极简 Glassmorphism 卡片 -->
      <div class="login-card" :class="{ 'card-bounce': isBouncing }">
        <!-- 流光微边框 -->
        <div class="shimmer-border"></div>

        <!-- 🐸 核心企业标识：aoni 奥尼 互动科技萌蛙 (完全对称无缺块) -->
        <div class="frog-mascot-wrapper" ref="frogRef">
          <!-- 对话气泡 (萌蛙提示) -->
          <transition name="pop">
            <div class="frog-speech-bubble" v-if="speechText">
              <span>{{ speechText }}</span>
              <div class="bubble-arrow"></div>
            </div>
          </transition>

          <!-- 奥尼青蛙头 SVG (眼睛跟随鼠标 & 密码遮眼保密 & 欢快眨眼) -->
          <div class="frog-svg-container" :class="{ 'stealth-mode': isPasswordFocused, 'blinking': isBlinking }">
            <svg viewBox="0 0 260 130" class="aoni-frog-svg" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <linearGradient id="frogGlow" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#1e293b"/>
                  <stop offset="100%" stop-color="#0f172a"/>
                </linearGradient>
                <linearGradient id="frogStroke" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#3b82f6"/>
                  <stop offset="50%" stop-color="#60a5fa"/>
                  <stop offset="100%" stop-color="#93c5fd"/>
                </linearGradient>
                <filter id="neonShadow" x="-20%" y="-20%" width="140%" height="140%">
                  <feGaussianBlur stdDeviation="3" result="blur" />
                  <feComposite in="SourceGraphic" in2="blur" operator="over" />
                </filter>
              </defs>

              <!-- 青蛙轮廓弧线头部 (左右完全对称 260px 宽度，无任何遮挡缺块) -->
              <path
                d="M 20 120 C 10 90 25 70 45 70 C 50 20 105 20 110 70 C 120 70 140 70 150 70 C 155 20 210 20 215 70 C 235 70 250 90 240 120 Z"
                fill="url(#frogGlow)"
                stroke="url(#frogStroke)"
                stroke-width="3.5"
                filter="url(#neonShadow)"
              />

              <!-- 左眼眼白 (cx=77) -->
              <ellipse cx="77" cy="52" rx="25" ry="25" fill="#ffffff" stroke="#1e293b" stroke-width="2.5" />
              <!-- 右眼眼白 (cx=183) -->
              <ellipse cx="183" cy="52" rx="25" ry="25" fill="#ffffff" stroke="#1e293b" stroke-width="2.5" />

              <!-- 普通模式：鼠标追随灵动黑眼珠 (Normal Mode) -->
              <g v-if="!isPasswordFocused">
                <!-- 左黑眼珠 -->
                <circle
                  cx="77" cy="46" r="11" fill="#0f172a"
                  :style="{ transform: `translate(${pupilOffset.x}px, ${pupilOffset.y}px)` }"
                  class="pupil-transition"
                >
                  <!-- 瞳孔高光小白点 -->
                  <circle cx="-3.5" cy="-3.5" r="4" fill="#ffffff" />
                </circle>

                <!-- 右黑眼珠 -->
                <circle
                  cx="183" cy="46" r="11" fill="#0f172a"
                  :style="{ transform: `translate(${pupilOffset.x}px, ${pupilOffset.y}px)` }"
                  class="pupil-transition"
                >
                  <circle cx="-3.5" cy="-3.5" r="4" fill="#ffffff" />
                </circle>
              </g>

              <!-- 密码输入模式：眯眯眼/保密笑眼 (Password Stealth Mode) -->
              <g v-else class="stealth-eyes">
                <!-- 左遮眼笑线 -->
                <path d="M 62 54 Q 77 38 92 54" fill="none" stroke="#0f172a" stroke-width="4.5" stroke-linecap="round" />
                <!-- 右遮眼笑线 -->
                <path d="M 168 54 Q 183 38 198 54" fill="none" stroke="#0f172a" stroke-width="4.5" stroke-linecap="round" />
              </g>
            </svg>
          </div>
        </div>

        <!-- 统一洗练标题：消除文本重复 -->
        <h1 class="login-title">AONI 模型测试平台</h1>
        <p class="login-subtitle">NVIDIA AGX Thor · 大模型性能与准确率评测矩阵</p>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          @submit.prevent="handleLogin"
          class="login-form"
        >
          <el-form-item prop="username">
            <el-input
              v-model="form.username"
              placeholder="用户名"
              size="large"
              prefix-icon="User"
              class="login-input"
              @focus="onUsernameFocus"
              @blur="onInputBlur"
              @keyup.enter="handleLogin"
            />
          </el-form-item>

          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="登录密码"
              show-password
              size="large"
              prefix-icon="Lock"
              class="login-input"
              @focus="onPasswordFocus"
              @blur="onInputBlur"
              @keyup.enter="handleLogin"
            />
          </el-form-item>

          <el-button
            type="primary"
            size="large"
            :loading="loading"
            class="login-btn"
            @click="handleLogin"
          >
            <span v-if="!loading" class="btn-inner">
              登 录 <el-icon class="arrow-icon"><Right /></el-icon>
            </span>
            <span v-else>身份验证中...</span>
          </el-button>

          <div v-if="errorMsg" class="login-error">
            <el-icon><Warning /></el-icon> {{ errorMsg }}
          </div>
        </el-form>

        <div class="login-footer">
          <span>AONI System v2.5</span>
          <span>·</span>
          <span>智算中心专属平台</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/authStore'

const router = useRouter()
const authStore = useAuthStore()

const formRef = ref(null)
const frogRef = ref(null)
const loading = ref(false)
const errorMsg = ref('')

const canvasRef = ref(null)
let ctx = null
let animationFrameId = null
let particles = []
const mouse = { x: null, y: null, radius: 140 }

// 青蛙互动状态
const pupilOffset = reactive({ x: 0, y: -4 })
const isPasswordFocused = ref(false)
const isBlinking = ref(false)
const isBouncing = ref(false)
const speechText = ref('你好！我是奥尼智能小蛙 🐸')

let speechTimer = null

const triggerSpeech = (text, duration = 3000) => {
  speechText.value = text
  if (speechTimer) clearTimeout(speechTimer)
  speechTimer = setTimeout(() => {
    speechText.value = ''
  }, duration)
}

// 鼠标位置与黑眼珠追随计算
const handleMouseMove = (e) => {
  mouse.x = e.clientX
  mouse.y = e.clientY

  if (isPasswordFocused.value || !frogRef.value) return

  const rect = frogRef.value.getBoundingClientRect()
  const frogX = rect.left + rect.width / 2
  const frogY = rect.top + rect.height / 2

  const dx = e.clientX - frogX
  const dy = e.clientY - frogY
  const angle = Math.atan2(dy, dx)
  const distance = Math.min(Math.sqrt(dx * dx + dy * dy) / 25, 7.5)

  pupilOffset.x = Math.cos(angle) * distance
  pupilOffset.y = Math.sin(angle) * distance - 2
}

const onUsernameFocus = () => {
  isPasswordFocused.value = false
  triggerSpeech('正在输入用户名... 🧐')
}

const onPasswordFocus = () => {
  isPasswordFocused.value = true
  triggerSpeech('嘘！密码保密中，我不看哦 🙈')
}

const onInputBlur = () => {
  isPasswordFocused.value = false
}

// 4 大色彩丰富的皮肤主题定义
const skins = [
  { id: 'cyber', name: '赛博深空', label: '赛博深空 🌌', dotColor: 'linear-gradient(135deg, #6366f1, #3b82f6)' },
  { id: 'aurora', name: '缤纷极光', label: '缤纷极光 🌈', dotColor: 'linear-gradient(135deg, #10b981, #ec4899)' },
  { id: 'sunset', name: '暮光暖阳', label: '暮光暖阳 🌅', dotColor: 'linear-gradient(135deg, #f59e0b, #ef4444)' },
  { id: 'glacier', name: '极地水晶', label: '极地水晶 🧊', dotColor: 'linear-gradient(135deg, #38bdf8, #818cf8)' },
]

const currentSkin = ref('cyber')

const setSkin = (skinId) => {
  currentSkin.value = skinId
  localStorage.setItem('aoni_login_skin', skinId)
}

// HTML5 Canvas 交互神经网络粒子动画逻辑
const initCanvas = () => {
  const canvas = canvasRef.value
  if (!canvas) return
  ctx = canvas.getContext('2d')

  const resize = () => {
    canvas.width = window.innerWidth
    canvas.height = window.innerHeight
  }
  resize()
  window.addEventListener('resize', resize)

  particles = []
  const count = Math.min(Math.floor(window.innerWidth / 18), 85)
  for (let i = 0; i < count; i++) {
    particles.push({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      vx: (Math.random() - 0.5) * 1.2,
      vy: (Math.random() - 0.5) * 1.2,
      radius: Math.random() * 2.2 + 1,
      baseAlpha: Math.random() * 0.5 + 0.3
    })
  }

  const animate = () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height)

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i]
      p.x += p.vx
      p.y += p.vy

      if (p.x < 0 || p.x > canvas.width) p.vx *= -1
      if (p.y < 0 || p.y > canvas.height) p.vy *= -1

      ctx.beginPath()
      ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2)
      ctx.fillStyle = currentSkin.value === 'aurora' ? 'rgba(52, 211, 153, 0.7)' :
                      currentSkin.value === 'sunset' ? 'rgba(251, 191, 36, 0.7)' :
                      currentSkin.value === 'glacier' ? 'rgba(56, 189, 248, 0.7)' : 'rgba(96, 165, 250, 0.7)'
      ctx.fill()

      for (let j = i + 1; j < particles.length; j++) {
        const p2 = particles[j]
        const dx = p.x - p2.x
        const dy = p.y - p2.y
        const dist = Math.sqrt(dx * dx + dy * dy)

        if (dist < 130) {
          ctx.beginPath()
          ctx.moveTo(p.x, p.y)
          ctx.lineTo(p2.x, p2.y)
          const alpha = (1 - dist / 130) * 0.25
          ctx.strokeStyle = currentSkin.value === 'aurora' ? `rgba(236, 72, 153, ${alpha})` :
                            currentSkin.value === 'sunset' ? `rgba(245, 158, 11, ${alpha})` :
                            `rgba(99, 102, 241, ${alpha})`
          ctx.lineWidth = 0.8
          ctx.stroke()
        }
      }

      if (mouse.x && mouse.y) {
        const mdx = p.x - mouse.x
        const mdy = p.y - mouse.y
        const mdist = Math.sqrt(mdx * mdx + mdy * mdy)
        if (mdist < mouse.radius) {
          ctx.beginPath()
          ctx.moveTo(p.x, p.y)
          ctx.lineTo(mouse.x, mouse.y)
          ctx.strokeStyle = 'rgba(255, 255, 255, 0.35)'
          ctx.lineWidth = 1.2
          ctx.stroke()
        }
      }
    }

    animationFrameId = requestAnimationFrame(animate)
  }

  animate()
}

onMounted(() => {
  const savedSkin = localStorage.getItem('aoni_login_skin')
  if (savedSkin && skins.some(s => s.id === savedSkin)) {
    currentSkin.value = savedSkin
  }
  initCanvas()
  triggerSpeech('欢迎来到奥尼模型测试平台！🐸', 4000)
})

onBeforeUnmount(() => {
  if (animationFrameId) cancelAnimationFrame(animationFrameId)
})

const form = reactive({ username: '', password: '' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入登录密码', trigger: 'blur' }],
}

const handleLogin = async () => {
  try {
    await formRef.value.validate()
  } catch {
    return
  }

  loading.value = true
  errorMsg.value = ''
  isBouncing.value = true
  triggerSpeech('正在进行身份验证... 🚀', 5000)

  setTimeout(() => { isBouncing.value = false }, 600)

  try {
    const ok = await authStore.login(form.username, form.password)
    if (ok) {
      triggerSpeech('验证成功！即将进入测试矩阵 🎉')
      setTimeout(() => { router.push('/') }, 500)
    } else {
      errorMsg.value = authStore.error || '登录失败，请检查用户名或密码'
      triggerSpeech('登录失败，请检查用户名或密码 😅')
    }
  } catch (e) {
    errorMsg.value = '连接服务器失败: ' + (e.message || e)
    triggerSpeech('连接失败，请检查网络设置 ⚠️')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  position: relative;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', sans-serif;
  transition: all 0.6s cubic-bezier(0.4, 0, 0.2, 1);
}

.particle-canvas {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
}

.login-bg {
  position: absolute;
  inset: 0;
  z-index: 0;
}

.wallpaper-layer {
  position: absolute;
  inset: 0;
  background-size: cover;
  background-position: center;
  opacity: 0;
  transition: opacity 0.8s ease;
}

.theme-cyber .wallpaper-layer {
  background-image: url('/images/login_bg.png');
  opacity: 0.38;
}

.scanline {
  position: absolute;
  inset: 0;
  background: linear-gradient(to bottom, transparent 50%, rgba(0, 0, 0, 0.25) 51%);
  background-size: 100% 4px;
  pointer-events: none;
  opacity: 0.4;
}

.bg-pattern-svg {
  position: absolute;
  inset: 0;
  z-index: 0;
}

.bg-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.55;
  animation: orbFloat 18s ease-in-out infinite alternate;
  transition: all 0.8s ease;
}

@keyframes orbFloat {
  0% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(70px, -50px) scale(1.2); }
  100% { transform: translate(-50px, 60px) scale(0.85); }
}

.theme-cyber { background: #080c16; }
.theme-cyber .orb-1 { width: 550px; height: 550px; background: #4f46e5; top: -10%; left: -10%; }
.theme-cyber .orb-2 { width: 480px; height: 480px; background: #0284c7; bottom: -10%; right: -5%; }
.theme-cyber .orb-3 { width: 380px; height: 380px; background: #7c3aed; top: 40%; right: 30%; }

.theme-aurora { background: #041612; }
.theme-aurora .orb-1 { width: 580px; height: 580px; background: #10b981; top: -15%; left: 10%; }
.theme-aurora .orb-2 { width: 500px; height: 500px; background: #ec4899; bottom: -10%; right: 10%; }
.theme-aurora .orb-3 { width: 420px; height: 420px; background: #06b6d4; top: 35%; left: -10%; }

.theme-sunset { background: #1a0b08; }
.theme-sunset .orb-1 { width: 550px; height: 550px; background: #f59e0b; top: -10%; right: -5%; }
.theme-sunset .orb-2 { width: 480px; height: 480px; background: #dc2626; bottom: -15%; left: 5%; }
.theme-sunset .orb-3 { width: 400px; height: 400px; background: #b45309; top: 45%; right: 25%; }

.theme-glacier { background: #0b1329; }
.theme-glacier .orb-1 { width: 550px; height: 550px; background: #38bdf8; top: -10%; left: -5%; }
.theme-glacier .orb-2 { width: 480px; height: 480px; background: #818cf8; bottom: -10%; right: 5%; }
.theme-glacier .orb-3 { width: 380px; height: 380px; background: #0284c7; top: 30%; left: 30%; }

.skin-switcher-pill {
  position: absolute;
  top: 24px;
  right: 28px;
  z-index: 100;
  background: rgba(15, 23, 42, 0.75);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 40px;
  padding: 6px 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
}

.switcher-label {
  font-size: 12px;
  font-weight: 700;
  color: #94a3b8;
  margin-right: 4px;
}

.skin-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 20px;
  cursor: pointer;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid transparent;
  transition: all 0.3s ease;
}

.skin-chip:hover {
  background: rgba(255, 255, 255, 0.15);
  transform: translateY(-1px);
}

.skin-chip.active {
  background: rgba(255, 255, 255, 0.22);
  border-color: rgba(255, 255, 255, 0.45);
  box-shadow: 0 0 14px rgba(255, 255, 255, 0.25);
}

.skin-color-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.skin-name {
  font-size: 12px;
  font-weight: 600;
  color: #f1f5f9;
}

.card-container {
  position: relative;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;
}

.floating-badge {
  position: absolute;
  z-index: 20;
  background: rgba(15, 23, 42, 0.85);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 14px;
  padding: 10px 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4);
  animation: floatBadge 5s ease-in-out infinite alternate;
  pointer-events: none;
}

.badge-left { top: 30px; left: -170px; animation-delay: 0s; }
.badge-right { top: 140px; right: -170px; animation-delay: 1.5s; }
.badge-bottom { bottom: -25px; left: -80px; animation-delay: 3s; }

@keyframes floatBadge {
  0% { transform: translateY(0px) rotate(0deg); }
  100% { transform: translateY(-14px) rotate(1deg); }
}

.pulse-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  box-shadow: 0 0 10px currentColor;
  animation: pulse 1.8s infinite;
}
.pulse-dot.green { background: #10b981; color: #10b981; }
.pulse-dot.blue { background: #3b82f6; color: #3b82f6; }
.pulse-dot.purple { background: #a855f7; color: #a855f7; }

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(1.3); }
}

.badge-icon { font-size: 18px; }
.badge-title { font-size: 12px; font-weight: 700; color: #ffffff; line-height: 1.2; }
.badge-sub { font-size: 10px; color: #94a3b8; }

.login-card {
  position: relative;
  width: 430px;
  padding: 34px 38px;
  background: rgba(15, 23, 42, 0.72);
  backdrop-filter: blur(28px);
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 24px;
  box-shadow: 0 30px 60px -12px rgba(0, 0, 0, 0.6), inset 0 1px 0 rgba(255, 255, 255, 0.15);
  text-align: center;
  overflow: hidden;
  transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}

.card-bounce {
  animation: frogBounce 0.6s cubic-bezier(0.68, -0.55, 0.27, 1.55);
}

@keyframes frogBounce {
  0% { transform: scale(1); }
  30% { transform: scale(0.92) translateY(12px); }
  60% { transform: scale(1.06) translateY(-18px); }
  100% { transform: scale(1) translateY(0); }
}

.shimmer-border {
  position: absolute;
  top: 0; left: 0; right: 0; height: 2px;
  background: linear-gradient(90deg, transparent, #3b82f6, #a855f7, transparent);
  animation: shimmer 3s linear infinite;
}

@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

.frog-mascot-wrapper {
  position: relative;
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  margin-bottom: 2px;
}

.frog-speech-bubble {
  position: absolute;
  top: -36px;
  background: rgba(30, 41, 59, 0.94);
  border: 1px solid rgba(255, 255, 255, 0.25);
  border-radius: 12px;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 600;
  color: #60a5fa;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35);
  white-space: nowrap;
  z-index: 30;
}

.bubble-arrow {
  position: absolute;
  bottom: -5px;
  left: 50%;
  transform: translateX(-50%) rotate(45deg);
  width: 8px;
  height: 8px;
  background: rgba(30, 41, 59, 0.94);
  border-right: 1px solid rgba(255, 255, 255, 0.25);
  border-bottom: 1px solid rgba(255, 255, 255, 0.25);
}

.pop-enter-active, .pop-leave-active {
  transition: all 0.3s cubic-bezier(0.68, -0.55, 0.27, 1.55);
}
.pop-enter-from, .pop-leave-to {
  opacity: 0;
  transform: translateY(10px) scale(0.8);
}

.frog-svg-container {
  width: 155px;
  height: 78px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.3s ease;
}

.aoni-frog-svg {
  width: 100%;
  height: 100%;
  overflow: visible;
}

.pupil-transition {
  transition: transform 0.08s ease-out;
}

.login-title {
  font-size: 24px;
  font-weight: 900;
  color: #ffffff;
  letter-spacing: 0.8px;
  margin-bottom: 4px;
  margin-top: 4px;
}

.login-subtitle {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 24px;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

:deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.08) !important;
  border: 1px solid rgba(255, 255, 255, 0.18) !important;
  box-shadow: none !important;
  border-radius: 12px !important;
  padding: 4px 14px !important;
  transition: all 0.3s ease !important;
}

:deep(.el-input__wrapper:hover),
:deep(.el-input__wrapper.is-focus) {
  border-color: #3b82f6 !important;
  background: rgba(255, 255, 255, 0.14) !important;
  box-shadow: 0 0 16px rgba(59, 130, 246, 0.4) !important;
}

:deep(.el-input__inner) {
  color: #ffffff !important;
  font-size: 14px !important;
}

:deep(.el-input__prefix-icon) {
  color: #94a3b8 !important;
}

.login-btn {
  width: 100%;
  height: 46px;
  border-radius: 12px;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 1px;
  border: none;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  box-shadow: 0 4px 20px rgba(37, 99, 235, 0.45);
  transition: all 0.3s ease;
  margin-top: 4px;
}

.btn-inner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.arrow-icon {
  transition: transform 0.3s ease;
}

.login-btn:hover .arrow-icon {
  transform: translateX(4px);
}

.theme-aurora .login-btn {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  box-shadow: 0 4px 20px rgba(16, 185, 129, 0.45);
}

.theme-sunset .login-btn {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
  box-shadow: 0 4px 20px rgba(245, 158, 11, 0.45);
}

.theme-glacier .login-btn {
  background: linear-gradient(135deg, #38bdf8 0%, #0284c7 100%);
  box-shadow: 0 4px 20px rgba(56, 189, 248, 0.45);
}

.login-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 28px rgba(37, 99, 235, 0.65);
}

.login-error {
  font-size: 12px;
  color: #f87171;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: rgba(248, 113, 113, 0.1);
  padding: 8px;
  border-radius: 8px;
}

.login-footer {
  margin-top: 22px;
  font-size: 11px;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
</style>
