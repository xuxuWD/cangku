/**
 * 展示层时间格式化。
 *
 * 后端契约为 ISO 8601 字符串（如 `2026-09-19T09:20:00+08:00`）。
 * 不用 `toLocaleString`：输出随运行环境的语言与时区变化，截图与测试都不可复现。
 * 拿不到标准形态时**原样返回**（不编造时间）。
 */
export function formatDateTime(iso: string): string {
  const matched = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(iso)
  return matched ? `${matched[1]} ${matched[2]}` : iso
}