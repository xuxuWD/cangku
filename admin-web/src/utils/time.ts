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
