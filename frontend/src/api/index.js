import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 健康检查
export const apiHealth = () => api.get('/health').then(r => r.data)

// 模型管理 CRUD
export const apiListModels = () => api.get('/models').then(r => r.data)
export const apiCreateModel = (data) => api.post('/models', data).then(r => r.data)
export const apiUpdateModel = (slug, data) => api.put(`/models/${slug}`, data).then(r => r.data)
export const apiDeleteModel = (slug) => api.delete(`/models/${slug}`).then(r => r.data)

// 任务
export const apiCreateTask = (data) => api.post('/tasks', data).then(r => r.data)
export const apiListTasks = () => api.get('/tasks').then(r => r.data)
export const apiGetTask = (id) => api.get(`/tasks/${id}`).then(r => r.data)
export const apiTaskAction = (id, action) => api.post(`/tasks/${id}/action`, { action }).then(r => r.data)
export const apiDeleteTask = (id) => api.delete(`/tasks/${id}`).then(r => r.data)
export const apiGetTaskLogs = (id, model_slug, limit = 200) =>
  api.get(`/tasks/${id}/logs`, { params: { model_slug, limit } }).then(r => r.data)

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
