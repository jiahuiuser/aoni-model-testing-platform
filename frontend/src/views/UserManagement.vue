<template>
  <div class="user-mgmt-page">
    <div class="top-toolbar">
      <div class="toolbar-left">
        <el-button type="primary" @click="showAddDialog">
          <el-icon><Plus /></el-icon> 新增用户
        </el-button>
        <el-button type="warning" plain :disabled="selectedUsers.length !== 1" @click="openEditSelected">
          <el-icon><Edit /></el-icon> 编辑用户
        </el-button>
        <el-button
          type="danger"
          plain
          :disabled="selectedUsers.length === 0 || selectedUsers.some(u => u.id === authStore.user?.id)"
          @click="deleteSelectedUser"
        >
          <el-icon><Delete /></el-icon> 批量删除 ({{ selectedUsers.length }})
        </el-button>
      </div>
      <div class="toolbar-right">
        <el-button circle @click="loadUsers"><el-icon><Refresh /></el-icon></el-button>
      </div>
    </div>

    <el-table
      ref="tableRef"
      :data="users"
      v-loading="loading"
      stripe
      border
      @selection-change="handleSelectionChange"
      @row-click="handleRowClick"
      class="custom-table"
    >
      <el-table-column type="selection" width="50" align="center" />
      <el-table-column prop="id" label="ID" width="60" align="center" />
      <el-table-column prop="username" label="用户名" width="140" />
      <el-table-column prop="display_name" label="显示名称" width="160" />
      <el-table-column label="角色" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="row.role === 'admin' ? 'danger' : 'primary'" size="small" effect="dark">
            {{ row.role === 'admin' ? '管理员' : '普通用户' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '正常' : '已禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最近登录" min-width="170">
        <template #default="{ row }">
          {{ row.last_login ? new Date(row.last_login).toLocaleString() : '从未登录' }}
        </template>
      </el-table-column>
      <el-table-column label="创建时间" min-width="170">
        <template #default="{ row }">
          {{ new Date(row.created_at).toLocaleString() }}
        </template>
      </el-table-column>
    </el-table>

    <!-- 新增/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="editing ? '编辑用户信息' : '新增用户账号'" width="480px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="用户名">
          <el-input v-model="form.username" :disabled="!!editing" placeholder="登录账号（不可更改）" />
        </el-form-item>
        <el-form-item label="显示名称">
          <el-input v-model="form.display_name" placeholder="展示给用户的名称" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width:100%">
            <el-option label="普通用户" value="user" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item :label="editing ? '重置密码' : '初始密码'">
          <el-input v-model="form.password" type="password" show-password :placeholder="editing ? '留空则不修改密码' : '设置初始登录密码'" />
        </el-form-item>
        <el-form-item v-if="editing" label="账号状态">
          <el-switch v-model="form.is_active" active-text="正常" inactive-text="已禁用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave">{{ editing ? '保存更改' : '创建账号' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '../stores/authStore'
import { useDragSelect } from '../utils/dragSelect'
import axios from 'axios'

const authStore = useAuthStore()
const tableRef = ref(null)
const users = ref([])
const loading = ref(false)
const selectedUsers = ref([])
const singleSelected = computed(() => selectedUsers.value.length === 1 ? selectedUsers.value[0] : null)
const selectedUser = computed(() => singleSelected.value)

const dialogVisible = ref(false)
const editing = ref(null)
const form = ref({ username: '', display_name: '', role: 'user', password: '', is_active: true })

useDragSelect(tableRef, users)

const handleSelectionChange = (val) => {
  selectedUsers.value = val
}

const handleRowClick = (row) => {
  if (tableRef.value) {
    tableRef.value.toggleRowSelection(row)
  }
}

const loadUsers = async () => {
  loading.value = true
  try {
    users.value = (await axios.get('/api/auth/users')).data
  } catch (e) {
    ElMessage.error('获取用户列表失败')
  }
  loading.value = false
}

const showAddDialog = () => {
  editing.value = null
  form.value = { username: '', display_name: '', role: 'user', password: '', is_active: true }
  dialogVisible.value = true
}

const openEditSelected = () => {
  if (!selectedUser.value) return
  editing.value = selectedUser.value.id
  form.value = {
    username: selectedUser.value.username,
    display_name: selectedUser.value.display_name || '',
    role: selectedUser.value.role,
    password: '',
    is_active: selectedUser.value.is_active,
  }
  dialogVisible.value = true
}

const handleSave = async () => {
  try {
    if (editing.value) {
      const payload = { display_name: form.value.display_name, role: form.value.role, is_active: form.value.is_active }
      if (form.value.password) payload.password = form.value.password
      await axios.put(`/api/auth/users/${editing.value}`, payload)
      ElMessage.success('用户信息已成功更新')
    } else {
      if (!form.value.password) { ElMessage.warning('请设置初始登录密码'); return }
      await axios.post('/api/auth/users', form.value)
      ElMessage.success('用户账号已成功创建')
    }
    dialogVisible.value = false
    await loadUsers()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

const deleteSelectedUser = async () => {
  if (selectedUsers.value.length === 0) return
  try {
    await ElMessageBox.confirm(
      `确定要永久删除选中的 ${selectedUsers.value.length} 个用户账号吗？此操作不可恢复。`,
      '批量删除确认',
      { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning', center: true }
    )
    for (const u of selectedUsers.value) {
      if (u.id !== authStore.user?.id) {
        await axios.delete(`/api/auth/users/${u.id}`)
      }
    }
    selectedUsers.value = []
    await loadUsers()
    ElMessage.success('选中的用户账号已成功删除')
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

onMounted(loadUsers)
</script>

<style scoped>
.user-mgmt-page { padding: 0; }
.top-toolbar {
  background: #fff; padding: 12px 16px; border-radius: 8px; border: 1px solid #e5e7eb;
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;
}
.toolbar-left, .toolbar-right { display: flex; gap: 8px; align-items: center; }
.custom-table { cursor: pointer; }
</style>

<style>
/* 选中行高亮（非 scoped） */
.custom-table .selected-row td {
  background: #eff6ff !important;
}
.custom-table .el-table__row:hover td {
  background: #f5f7fa !important;
  cursor: pointer;
}
</style>
