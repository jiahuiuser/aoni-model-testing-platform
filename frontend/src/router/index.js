import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'TaskList', component: () => import('../views/TaskList.vue') },
  { path: '/create', name: 'TaskCreate', component: () => import('../views/TaskCreate.vue') },
  { path: '/task/:id', name: 'TaskDetail', component: () => import('../views/TaskDetail.vue') },
  { path: '/models', name: 'ModelManagement', component: () => import('../views/ModelManagement.vue') },
  { path: '/devices', name: 'DeviceManagement', component: () => import('../views/DeviceManagement.vue') },
  { path: '/reports', name: 'Reports', component: () => import('../views/Reports.vue') },
  { path: '/reports/:id', name: 'ReportDetail', component: () => import('../views/ReportDetail.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
