import { centsToYuanInput, crmErrorFromStatus, formatCents, formatDays, formatRatio, parseYuanToCents, scalarEntries } from './state'

describe('crm state（金额整数分与展示口径）', () => {
  it('formats integer cents with pure integer arithmetic and thousands separators', () => {
    expect(formatCents(0)).toBe('¥0.00')
    expect(formatCents(1)).toBe('¥0.01')
    expect(formatCents(1234)).toBe('¥12.34')
    expect(formatCents(100000)).toBe('¥1,000.00')
    expect(formatCents(1250000)).toBe('¥12,500.00')
    expect(formatCents(55800000)).toBe('¥558,000.00')
    expect(formatCents(999999999999)).toBe('¥9,999,999,999.99')
    // 正负号位置保持原样：符号在最前，千分位只作用于整数部分。
    expect(formatCents(-123456)).toBe('-¥1,234.56')
    expect(formatCents(-5)).toBe('-¥0.05')
    // 缺值不显示 0，避免把「未计算 / 未登记」伪装成零金额。
    expect(formatCents(null)).toBe('—')
    expect(formatCents(undefined)).toBe('—')
  })

  it('parses yuan input into integer cents without float multiplication', () => {
    // 0.1 × 3 这类浮点误差样本必须以字符串解析得到精确整数分。
    expect(parseYuanToCents('0.1')).toBe(10)
    expect(parseYuanToCents('12.34')).toBe(1234)
    expect(parseYuanToCents('1234567.89')).toBe(123456789)
    expect(parseYuanToCents('12000')).toBe(1200000)
    // 输入框口径：**不带千分位**；含逗号的输入一律拒绝（展示格式只用于展示，不回流输入框）。
    expect(parseYuanToCents('1,234.56')).toBeNull()
    expect(parseYuanToCents('12,000')).toBeNull()
    expect(parseYuanToCents('1,23.00')).toBeNull()
    expect(parseYuanToCents('1,23456.00')).toBeNull()
    expect(parseYuanToCents('1.')).toBeNull()
    expect(parseYuanToCents('1.234')).toBeNull()
    expect(parseYuanToCents('-1')).toBeNull()
    expect(parseYuanToCents('')).toBeNull()
  })

  it('round-trips cents back to a yuan input value', () => {
    expect(centsToYuanInput(1234)).toBe('12.34')
    expect(centsToYuanInput(5)).toBe('0.05')
    // 输入框回填**不带千分位**（可编辑原始形态）；千分位只在展示函数 `formatCents` 生效。
    expect(centsToYuanInput(123456789)).toBe('1234567.89')
    expect(centsToYuanInput(null)).toBe('0.00')
    // 回填值必须能原样解析回同等的整数分，否则「打开草稿直接保存」会被误判为非法。
    expect(parseYuanToCents(centsToYuanInput(123456789))).toBe(123456789)
  })

  it('renders null ratios as a dash instead of zero', () => {
    expect(formatRatio(null, 'percent')).toBe('—')
    expect(formatRatio(0.5, 'percent')).toBe('50.00%')
    expect(formatRatio(3.25, 'multiple')).toBe('3.25×')
    expect(formatDays(null)).toBe('—')
    expect(formatDays(12.5)).toBe('12.5 天')
  })

  it('maps statuses to fixed Chinese messages without leaking server detail', () => {
    expect(crmErrorFromStatus(403).message).toBe('当前账号没有执行该操作的权限。')
    expect(crmErrorFromStatus(404).message).toBe('没有找到该记录，或你没有访问权限。')
    expect(crmErrorFromStatus(409).message).toBe('状态已变化，请刷新后重试。')
    expect(crmErrorFromStatus(401).retryable).toBe(false)
    expect(crmErrorFromStatus(502).retryable).toBe(true)
    expect(crmErrorFromStatus(503).retryable).toBe(true)
    expect(crmErrorFromStatus(0).retryable).toBe(true)
  })

  it('collapses nested custom fields instead of dumping structures', () => {
    expect(scalarEntries({ a: 'x', b: 2, c: true, d: null, e: { nested: 1 } })).toEqual([
      { key: 'a', text: 'x' },
      { key: 'b', text: '2' },
      { key: 'c', text: '是' },
      { key: 'd', text: '—' },
      { key: 'e', text: '…' },
    ])
  })
})