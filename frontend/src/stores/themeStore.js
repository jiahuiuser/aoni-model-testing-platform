import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useThemeStore = defineStore('theme', () => {
  const skins = [
    { id: 'cyber', name: '赛博深空', label: '赛博深空 🌌', dotColor: 'linear-gradient(135deg, #6366f1, #3b82f6)' },
    { id: 'aurora', name: '缤纷极光', label: '缤纷极光 🌈', dotColor: 'linear-gradient(135deg, #10b981, #ec4899)' },
    { id: 'sunset', name: '暮光暖阳', label: '暮光暖阳 🌅', dotColor: 'linear-gradient(135deg, #f59e0b, #ef4444)' },
    { id: 'glacier', name: '极地水晶', label: '极地水晶 🧊', dotColor: 'linear-gradient(135deg, #38bdf8, #818cf8)' },
  ]

  const savedTheme = localStorage.getItem('aoni_theme') || localStorage.getItem('aoni_login_skin') || 'cyber'
  const currentTheme = ref(savedTheme)

  const setTheme = (themeId) => {
    currentTheme.value = themeId
    localStorage.setItem('aoni_theme', themeId)
    localStorage.setItem('aoni_login_skin', themeId)
    applyThemeClass(themeId)
  }

  const applyThemeClass = (themeId) => {
    const root = document.documentElement
    root.setAttribute('data-theme', themeId)
  }

  // 初始化设置
  applyThemeClass(currentTheme.value)

  return {
    skins,
    currentTheme,
    setTheme,
    applyThemeClass,
  }
})
