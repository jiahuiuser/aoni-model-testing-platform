<template>
  <div id="app-container">
    <el-container style="height:100vh">
      <!-- 左侧侧边栏 -->
      <el-aside width="200px" class="app-sidebar">
        <div class="sidebar-header">
          <h2>AONI 模型测试平台</h2>
          <el-tag v-if="backendStatus === 'ok'" type="success" size="small">已连接</el-tag>
          <el-tag v-else type="danger" size="small">断开</el-tag>
        </div>
        <el-menu :default-active="activeMenu" router class="sidebar-menu">
          <el-menu-item index="/">
            <el-icon><List /></el-icon>
            <span>任务管理</span>
          </el-menu-item>
          <el-menu-item index="/models">
            <el-icon><Setting /></el-icon>
            <span>模块管理</span>
          </el-menu-item>
          <el-menu-item index="/devices">
            <el-icon><Monitor /></el-icon>
            <span>设备管理</span>
          </el-menu-item>
          <el-menu-item index="/reports">
            <el-icon><Document /></el-icon>
            <span>测试报告</span>
          </el-menu-item>
        </el-menu>
      </el-aside>

      <!-- 右侧主内容 -->
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { apiHealth } from './api'

const route = useRoute()
const backendStatus = ref('unknown')

const activeMenu = computed(() => {
  if (route.path.startsWith('/reports')) return '/reports'
  return '/'
})

onMounted(async () => {
  try {
    const res = await apiHealth()
    backendStatus.value = res.status
  } catch {
    backendStatus.value = 'error'
  }
})
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
#app-container { min-height: 100vh; background: #f5f7fa; }

.app-sidebar {
  background: #fff;
  box-shadow: 1px 0 4px rgba(0,0,0,.08);
  display: flex; flex-direction: column;
}
.sidebar-header {
  padding: 20px 16px 12px;
  display: flex; flex-direction: column; gap: 8px;
}
.sidebar-header h2 {
  font-size: 16px; color: #303133; white-space: nowrap;
}
.sidebar-menu {
  border-right: none; flex: 1;
}

.app-main {
  padding: 20px 24px;
  overflow-y: auto;
}
</style>
