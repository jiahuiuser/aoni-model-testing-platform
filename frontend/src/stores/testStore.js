import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useTestStore = defineStore('testStore', () => {
  const isRunning = ref(false)
  const isModalVisible = ref(false)
  const modelSlug = ref('')
  const modelName = ref('')
  const deviceName = ref('本机节点')

  const step = ref(1)
  const progress = ref(0)
  const logs = ref([])
  const finalResult = ref(null)

  let activeEventSource = null

  const startTest = (slug, name, deviceId = null, devName = '本机节点') => {
    stopTest()

    modelSlug.value = slug
    modelName.value = name
    deviceName.value = devName
    isRunning.value = true
    isModalVisible.value = true
    step.value = 1
    progress.value = 5
    logs.value = []
    finalResult.value = null

    let url = `/api/models/${slug}/test-stream`
    if (deviceId) {
      url += `?device_id=${deviceId}`
    }

    const es = new EventSource(url)
    activeEventSource = es

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.step) step.value = data.step
        if (data.progress) progress.value = data.progress
        if (data.msg) {
          logs.value.push({
            time: new Date().toLocaleTimeString(),
            stage: data.stage || 'INFO',
            msg: data.msg,
          })
        }
        if (data.stage === 'DONE') {
          finalResult.value = data
          progress.value = 100
          isRunning.value = false
          stopEventSourceOnly()
        }
      } catch (e) {
        console.error('SSE Error:', e)
      }
    }

    es.onerror = () => {
      stopEventSourceOnly()
      if (progress.value < 100) {
        logs.value.push({
          time: new Date().toLocaleTimeString(),
          stage: 'ERROR',
          msg: '日志传输连接已中断，关联测试容器已自动安全释放。',
        })
        isRunning.value = false
      }
    }
  }

  const stopEventSourceOnly = () => {
    if (activeEventSource) {
      activeEventSource.close()
      activeEventSource = null
    }
  }

  const stopTest = () => {
    stopEventSourceOnly()
    isRunning.value = false
  }

  const resetTest = () => {
    stopEventSourceOnly()
    isRunning.value = false
    isModalVisible.value = false
    modelSlug.value = ''
    modelName.value = ''
    deviceName.value = '本机节点'
    step.value = 1
    progress.value = 0
    logs.value = []
    finalResult.value = null
  }

  const openModal = () => {
    isModalVisible.value = true
  }

  const closeModal = () => {
    isModalVisible.value = false
  }

  return {
    isRunning,
    isModalVisible,
    modelSlug,
    modelName,
    deviceName,
    step,
    progress,
    logs,
    finalResult,
    startTest,
    stopTest,
    resetTest,
    openModal,
    closeModal,
  }
})
