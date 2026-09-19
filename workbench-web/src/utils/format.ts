/**
 * 展示层格式化（跨模块共享）。
 *
 * - 不用 `toLocaleString`：输出随运行环境的语言与时区变化，截图与测试都不可复现；
 * - 金额**按整数分存储**（契约口径），这里只做展示换算，不参与计算；
 * - 拿不到标准形态时**原样返回**（不编造时间 / 金额）。
 */

/** `2026-09-19T09:20:00+08:00` → `2026-09-19 09:20`。 */
export function formatDateTime(iso: string): string {
  const matched = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(iso)
  return matched ? `${matched[1]} ${matched[2]}` : iso
}

/** 整数分 → `¥50.00`（仅展示换算；金额本身始终是整数分，不用浮点存储）。 */
export function formatBudgetCents(cents: number): string {
  if (!Number.isInteger(cents) || cents < 0) return String(cents)
  return `¥${(cents / 100).toFixed(2)}`
}

/**
 * 比率（0–1）→ `91.7%`。
 * 说明：**只用于"就绪"的比率**；未配置 / 样本不足 / 未验证的数据不得经此渲染成 0% 或 100%。
 */
export function formatPercent(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`
}