import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截器：自动注入 JWT token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('aoni_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

import { ElMessage } from 'element-plus'

// 响应拦截器：401 自动清理与单设备强退提醒
let isRedirecting = false
api.interceptors.response.use(
  res => res,
  err => {
    if (err.response?.status === 401) {
      // 401 由拦截器统一处理：清理 token、提示用户、跳转登录
      // 返回永不 resolve 的 Promise，防止业务层 catch 重复弹出错误 toast
      if (!isRedirecting) {
        isRedirecting = true
        localStorage.removeItem('aoni_token')
        localStorage.removeItem('aoni_user')

        const detail = err.response?.data?.detail || ''
        if (detail.includes('SINGLE_DEVICE_KICKED')) {
          ElMessage.error('您的账号已在另一台设备登录，当前会话已被强制下线！')
        } else if (!window.location.hash.includes('/login')) {
          ElMessage.warning('会话失效或已超时，请重新登录')
        }

        setTimeout(() => {
          isRedirecting = false
          window.location.href = '#/login'
        }, 1000)
      }
      // 返回永不 resolve 的 Promise，让业务层 catch 不被触发
      return new Promise(() => {})
    }
    return Promise.reject(err)
  }
)

// 健康检查
export const apiHealth = () => api.get('/health').then(r => r.data)

// 模型管理 CRUD
export const apiListModels = () => api.get('/models').then(r => r.data)
export const apiCreateModel = (data) => api.post('/models', data).then(r => r.data)
export const apiUpdateModel = (slug, data) => api.put(`/models/${slug}`, data).then(r => r.data)
export const apiDeleteModel = (slug) => api.delete(`/models/${slug}`).then(r => r.data)

// 任务
export const apiCreateTask = (data) => api.post('/tasks', data).then(r => r.data)
export const apiUpdateTask = (id, data) => api.patch(`/tasks/${id}`, data).then(r => r.data)
export const apiListTasks = () => api.get('/tasks').then(r => r.data)
export const apiGetTask = (id) => api.get(`/tasks/${id}`).then(r => r.data)
export const apiTaskAction = (id, action) => api.post(`/tasks/${id}/action`, { action }).then(r => r.data)
export const apiDeleteTask = (id) => api.delete(`/tasks/${id}`).then(r => r.data)
export const apiGetTaskLogs = (id, model_slug, limit = 200) =>
  api.get(`/tasks/${id}/logs`, { params: { model_slug, limit } }).then(r => r.data)

// 设备管理 API
export const apiListDevices = () => api.get('/devices').then(r => r.data)
export const apiCheckDevice = (id) => api.post(`/devices/${id}/check`).then(r => r.data)
export const apiDoctorDevice = (id) => api.post(`/devices/${id}/doctor`).then(r => r.data)

// 报告
export const apiListReports = (params) => api.get('/reports', { params }).then(r => r.data)
export const apiGetReport = (id) => api.get(`/reports/${id}`).then(r => r.data)
export const apiDeleteReport = (id) => api.delete(`/reports/${id}`).then(r => r.data)
export const apiCompareThroughput = () => api.get('/reports/compare/throughput').then(r => r.data)
export const apiCompareAccuracy = (dataset = 'mmlu') =>
  api.get('/reports/compare/accuracy', { params: { dataset } }).then(r => r.data)

// WebSocket 地址构建
export function wsUrl(path) {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${path}`
}

export default api
