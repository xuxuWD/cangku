// 时间展示统一入口：把后端返回的 ISO 串格式化为本地「YYYY/MM/DD HH:mm」。
// 解析失败时返回空串，避免把原始 ISO 串直接摊到界面上。
export function formatLocalTime(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

/** 相对时间（侧栏会话 / 首页动态共用）：刚刚 / N 分钟前 / N 小时前 / N 天前；解析失败回空串。 */
export function relativeTime(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const minutes = Math.floor(Math.max(0, Date.now() - date.getTime()) / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}
