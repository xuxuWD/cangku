/**
 * 用量与费用：金额格式化 / 过期判定 / 错误口径。
 *
 * **来源**：由 `admin-web/src/features/billing/state.ts` 合并移植。
 *
 * ⚠️ **为什么不复用基座的 `utils/format.ts::formatBudgetCents`（如实登记）**：
 * 基座那个函数对**负数**直接 `String(cents)` 原样返回；而本页账本**发生过冲正时累计费用为负**
 * 是**合法态**（`types.ts` 契约写明），必须正常渲染成 `-¥12.34`。
 * ⇒ 本模块保留原实现的**整数运算**换算（不用浮点除法），并对负值正确加符号。
 */

/** 账本以**整数分**记账：整数运算换算成元，绝不用浮点除法（避免 0.1+0.2 那类误差）。 */
export function formatCents(cents: number): string {
  const safe = Number.isFinite(cents) ? Math.trunc(cents) : 0
  const sign = safe < 0 ? '-' : ''
  const absolute = Math.abs(safe)
  return `${sign}¥${Math.floor(absolute / 100)}.${String(absolute % 100).padStart(2, '0')}`
}

/** 过期判定与服务端同口径：`expires_at <= 当前时刻` 即过期（正点即过期）。 */
export function isPackageExpired(expiresAt: string, now: number = Date.now()): boolean {
  const parsed = new Date(expiresAt).getTime()
  // 时间不可解析时按「不可下载」处理（宁可保守，也不放出一个可能已过期的包）
  if (Number.isNaN(parsed)) return true
  return parsed <= now
}
