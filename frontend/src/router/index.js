import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/authStore'

const routes = [
  // 登录页（无需认证）
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue'), meta: { public: true } },

  // 主业务页（需登录）
  { path: '/',          name: 'TaskList',         component: () => import('../views/TaskList.vue') },
  { path: '/create',    name: 'TaskCreate',        component: () => import('../views/TaskCreate.vue') },
  { path: '/task/:id',  name: 'TaskDetail',        component: () => import('../views/TaskDetail.vue') },
  { path: '/models',    name: 'ModelManagement',   component: () => import('../views/ModelManagement.vue') },
  { path: '/devices',   name: 'DeviceManagement',  component: () => import('../views/DeviceManagement.vue') },
  { path: '/reports',   name: 'Reports',            component: () => import('../views/Reports.vue') },
  { path: '/reports/:id', name: 'ReportDetail',    component: () => import('../views/ReportDetail.vue') },

  // 用户管理（需管理员）
  { path: '/users',     name: 'UserManagement',    component: () => import('../views/UserManagement.vue'), meta: { requireAdmin: true } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 全局路由守卫
router.beforeEach((to, _from, next) => {
  const authStore = useAuthStore()

  if (to.meta.public) {
    // 已登录则跳过登录页
    if (authStore.isLoggedIn && to.name === 'Login') {
      return next('/')
    }
    return next()
  }

  if (!authStore.isLoggedIn) {
    return next({ name: 'Login', query: { redirect: to.fullPath } })
  }

  if (to.meta.requireAdmin && !authStore.isAdmin) {
    return next('/')
  }

  next()
})

export default router
