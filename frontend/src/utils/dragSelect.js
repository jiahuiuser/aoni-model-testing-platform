/**
 * 全局表格拖拽划选 (Box Selection) 工具
 */
import { onMounted, onUnmounted } from 'vue'

export function useDragSelect(tableRef, dataList) {
  let isDragging = false
  let startX = 0
  let startY = 0
  let selectBox = null

  const handleMouseDown = (e) => {
    // 排除右键、表头、按钮、弹窗、表单控制件上的点击
    if (
      e.button !== 0 ||
      e.target.closest('thead') ||
      e.target.closest('.el-button') ||
      e.target.closest('.el-input') ||
      e.target.closest('.el-select') ||
      e.target.closest('.el-popconfirm') ||
      e.target.closest('.el-dialog')
    ) {
      return
    }

    const tableEl = tableRef.value?.$el
    if (!tableEl) return

    const tbody = tableEl.querySelector('tbody')
    if (!tbody || !tbody.contains(e.target)) return

    isDragging = false
    startX = e.clientX
    startY = e.clientY

    const onMouseMove = (moveEvent) => {
      const dx = Math.abs(moveEvent.clientX - startX)
      const dy = Math.abs(moveEvent.clientY - startY)

      // 拖拽距离超过 5px 时触发长按框选模式
      if (!isDragging && (dx > 5 || dy > 5)) {
        isDragging = true
        if (!selectBox) {
          selectBox = document.createElement('div')
          selectBox.className = 'drag-select-box'
          document.body.appendChild(selectBox)
        }
      }

      if (isDragging && selectBox) {
        const left = Math.min(startX, moveEvent.clientX)
        const top = Math.min(startY, moveEvent.clientY)
        const width = Math.abs(moveEvent.clientX - startX)
        const height = Math.abs(moveEvent.clientY - startY)

        selectBox.style.left = `${left}px`
        selectBox.style.top = `${top}px`
        selectBox.style.width = `${width}px`
        selectBox.style.height = `${height}px`
        selectBox.style.display = 'block'

        const boxRect = { left, top, right: left + width, bottom: top + height }
        const trs = Array.from(tbody.querySelectorAll('tr'))

        trs.forEach((tr, index) => {
          const trRect = tr.getBoundingClientRect()
          const isIntersect = !(
            trRect.right < boxRect.left ||
            trRect.left > boxRect.right ||
            trRect.bottom < boxRect.top ||
            trRect.top > boxRect.bottom
          )

          if (dataList.value[index] && tableRef.value) {
            tableRef.value.toggleRowSelection(dataList.value[index], isIntersect)
          }
        })
      }
    }

    const onMouseUp = () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
      if (selectBox) {
        selectBox.remove()
        selectBox = null
      }
      setTimeout(() => {
        isDragging = false
      }, 50)
    }

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
  }

  onMounted(() => {
    window.addEventListener('mousedown', handleMouseDown)
  })

  onUnmounted(() => {
    window.removeEventListener('mousedown', handleMouseDown)
  })
}
