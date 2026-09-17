import { centsToYuanInput, crmErrorFromStatus, formatCents, formatDays, formatRatio, parseYuanToCents, scalarEntries } from './state'

describe('crm state（金额整数分与展示口径）', () => {
  it('formats integer cents with pure integer arithmetic', () => {
    expect(formatCents(0)).toBe('¥0.00')
    expect(formatCents(1)).toBe('¥0.01')
    expect(formatCents(1234)).toBe('¥12.34')
    expect(formatCents(100000)).toBe('¥1000.00')
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
    expect(parseYuanToCents('1.')).toBeNull()
    expect(parseYuanToCents('1.234')).toBeNull()
    expect(parseYuanToCents('-1')).toBeNull()
    expect(parseYuanToCents('')).toBeNull()
  })

  it('round-trips cents back to a yuan input value', () => {
    expect(centsToYuanInput(1234)).toBe('12.34')
    expect(centsToYuanInput(5)).toBe('0.05')
    expect(centsToYuanInput(null)).toBe('0.00')
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