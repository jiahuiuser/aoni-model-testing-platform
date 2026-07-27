/**
 * 通用标准时间格式化函数 (处理 UTC -> 本地 +08:00 时区)
 */
export function formatTime(t) {
  if (!t) return '-'
  try {
    let str = String(t).trim()
    // 如果没有包含 Z 或 +08:00，补充 Z 确保以 UTC 时间格式解析
    if (!str.includes('Z') && !str.includes('+') && str.includes('T')) {
      str += 'Z'
    }
    const d = new Date(str)
    if (isNaN(d.getTime())) return String(t)
    return d.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  } catch (e) {
    return String(t)
  }
}
