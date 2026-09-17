import type { CrmErrorShape } from './types'

const DEFAULT_CRM_ERROR = 'CRM 服务暂时不可用，请检查网络后重新尝试。'
const DEFAULT_CREDENTIAL_ERROR = '登录态已失效，请重新登录。'

export const CRM_LIMIT_OPTIONS = [20, 50, 100, 200]

// 按 HTTP 状态码映射为固定中文提示，不把服务端 detail、堆栈、URL 或原始异常文本透到界面。
// `409` 保留「状态冲突」语义（非法迁移 / 冻结改单 / 重复转化 / 回款超限），页面按业务再细化文案。
export function crmErrorFromStatus(status: number): CrmErrorShape {
  if (status === 401) return { status, message: DEFAULT_CREDENTIAL_ERROR, retryable: false }
  if (status === 403) return { status, message: '当前账号没有执行该操作的权限。', retryable: false }
  if (status === 404) return { status, message: '没有找到该记录，或你没有访问权限。', retryable: false }
  if (status === 409) return { status, message: '状态已变化，请刷新后重试。', retryable: false }
  if (status === 422) return { status, message: '请求参数不被接受，请检查填写内容。', retryable: false }
  if (status === 502) return { status, message: '智能生成服务暂时不可用，请稍后重新尝试。', retryable: true }
  if (status === 0 || status >= 500) return { status, message: DEFAULT_CRM_ERROR, retryable: true }
  return { status, message: `请求不被接受（${status}）。`, retryable: false }
}

// 把任意异常规整成页面可直接展示的中文提示。
export function asCrmError(error: unknown): CrmErrorShape {
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const candidate = error as { status?: unknown; message?: unknown; retryable?: unknown }
    const status = typeof candidate.status === 'number' ? candidate.status : 0
    const message = typeof candidate.message === 'string' && candidate.message ? candidate.message : DEFAULT_CRM_ERROR
    return { status, message, retryable: candidate.retryable !== false }
  }
  return { status: 0, message: DEFAULT_CRM_ERROR, retryable: true }
}

// 千分位只作用于**已字符串化的整数部分**：正则插入分隔符，全程整数运算，不引入浮点做金额计算。
function groupThousands(integerText: string): string {
  return integerText.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

// 金额一律**整数分**：展示时用整数运算换算成元，绝不用浮点除法（避免 0.1+0.2 那类误差）。
export function formatCents(cents: number | null | undefined): string {
  if (typeof cents !== 'number' || !Number.isFinite(cents)) return '—'
  const safe = Math.trunc(cents)
  const sign = safe < 0 ? '-' : ''
  const absolute = Math.abs(safe)
  return `${sign}¥${groupThousands(String(Math.floor(absolute / 100)))}.${String(absolute % 100).padStart(2, '0')}`
}

// 整数分 → 「元」输入框回填值（不带 ¥、**不带千分位**——输入框保持可编辑原始形态，展示格式只用于展示）。
export function centsToYuanInput(cents: number | null | undefined): string {
  const safe = typeof cents === 'number' && Number.isFinite(cents) ? Math.trunc(cents) : 0
  const sign = safe < 0 ? '-' : ''
  const absolute = Math.abs(safe)
  return `${sign}${Math.floor(absolute / 100)}.${String(absolute % 100).padStart(2, '0')}`
}

// 「元」输入换算为整数分：纯字符串解析（不用浮点乘法），非法输入返回 null（含逗号的输入一律拒绝）。
export function parseYuanToCents(input: string): number | null {
  const text = input.trim()
  if (!/^\d+(\.\d{1,2})?$/.test(text)) return null
  const [whole, fraction = ''] = text.split('.')
  return Number(whole) * 100 + Number(fraction.padEnd(2, '0'))
}

// 比例展示：`percent`（赢率 / 回款进度 / 目标达成度）与 `multiple`（管线覆盖率 ×目标倍数）。
// 分母为零时后端返回 null ⇒ 统一显示「—」（不编造 0）。
export function formatRatio(value: number | null | undefined, kind: 'percent' | 'multiple'): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  const rounded = Math.round(value * 10000) / 10000
  return kind === 'percent' ? `${(rounded * 100).toFixed(2)}%` : `${rounded.toFixed(2)}×`
}

export function formatDays(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return `${value} 天`
}

// 「当前阶段停留天数」：由 `stage_entered_at` 与当前时间差整日向下取整。
// 时间解析失败 / 缺失一律返回 null（界面显示「—」，不伪造 0）；未来时间按 0 天处理。
export function daysSince(value: string | null | undefined, now: Date = new Date()): number | null {
  if (!value) return null
  const start = new Date(value)
  if (Number.isNaN(start.getTime())) return null
  const diff = now.getTime() - start.getTime()
  if (!Number.isFinite(diff)) return null
  return Math.max(0, Math.floor(diff / 86400000))
}

export function formatCount(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return String(value)
}

// 自定义字段渲染：只渲染一层标量；嵌套结构折叠为「…」，不 dump 未知结构到界面。
export function scalarEntries(fields: Record<string, unknown> | null | undefined): Array<{ key: string; text: string }> {
  return Object.entries(fields ?? {}).map(([key, value]) => {
    if (typeof value === 'string') return { key, text: value }
    if (typeof value === 'number') return { key, text: String(value) }
    if (typeof value === 'boolean') return { key, text: value ? '是' : '否' }
    if (value === null || value === undefined) return { key, text: '—' }
    return { key, text: '…' }
  })
}