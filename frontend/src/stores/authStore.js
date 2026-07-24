import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('aoni_token') || '')
  const user = ref(JSON.parse(localStorage.getItem('aoni_user') || 'null'))

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => user.value?.role === 'admin')

  let inactivityTimer = null
  let heartbeatTimer = null
  const INACTIVITY_TIMEOUT_MS = 20 * 60 * 1000 // 20 分钟无操作强制下线

  // 设置 axios 全局 Authorization Header
  const setAxiosAuth = (t) => {
    if (t) {
      axios.defaults.headers.common['Authorization'] = `Bearer ${t}`
    } else {
      delete axios.defaults.headers.common['Authorization']
    }
  }

  const resetInactivityTimer = () => {
    if (!token.value) return
    if (inactivityTimer) clearTimeout(inactivityTimer)

    inactivityTimer = setTimeout(() => {
      if (token.value) {
        ElMessage.warning({
          message: '由于您已连续 20 分钟没有任何操作，登录已超时强制退出，请重新登录！',
          duration: 5000,
        })
        logout()
        window.location.href = '#/login'
      }
    }, INACTIVITY_TIMEOUT_MS)
  }

  const startHeartbeat = () => {
    stopHeartbeat()
    if (!token.value) return

    heartbeatTimer = setInterval(async () => {
      if (!token.value) return
      try {
        await axios.get('/api/auth/me')
      } catch (e) {
        // 401 拦截器已自动处理 SINGLE_DEVICE_KICKED 强制下线
      }
    }, 30000) // 每 30 秒轮询一次心跳
  }

  const stopHeartbeat = () => {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  const initActivityListener = () => {
    const events = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart']
    events.forEach(event => {
      window.addEventListener(event, resetInactivityTimer, { passive: true })
    })
    resetInactivityTimer()
    startHeartbeat()
  }

  // 初始化时恢复 token 并启动保活与心跳
  if (token.value) {
    setAxiosAuth(token.value)
    initActivityListener()
  }

  const login = async (username, password) => {
    const params = new URLSearchParams()
    params.append('username', username)
    params.append('password', password)

    const resp = await axios.post('/api/auth/login', params, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })

    token.value = resp.data.access_token
    user.value = resp.data.user

    localStorage.setItem('aoni_token', token.value)
    localStorage.setItem('aoni_user', JSON.stringify(user.value))
    setAxiosAuth(token.value)

    initActivityListener()
    return user.value
  }

  const logout = () => {
    token.value = ''
    user.value = null
    localStorage.removeItem('aoni_token')
    localStorage.removeItem('aoni_user')
    setAxiosAuth(null)
    if (inactivityTimer) clearTimeout(inactivityTimer)
    stopHeartbeat()
  }

  return { token, user, isLoggedIn, isAdmin, login, logout, resetInactivityTimer }
})
