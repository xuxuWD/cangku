/**
 * 「审计日志」页用例（第 10 轮）。
 *
 * 覆盖口径（见 `docs/contracts/audit-log-api.md` §2 / §3）：
 *  - **两视图 + 整页无权限**：`audit.scope.tenant`（department_lead / ceo / super_admin）⇒ 本租户视图；
 *    `audit.view`（employee）⇒ 我的操作视图（**不渲染操作人筛选** + 自限说明）；
 *    `customer_admin` ⇒ 整页无权限 + 原因，**不请求任何数据**；
 *  - 空态**区分**"没有记录"与"筛选未命中"，且员工档文案不同；
 *  - 筛选提交后**重新取数**（断言传给适配层的条件）；分页按服务端语义传 `offset`；
 *  - 详情抽屉呈现元数据 + `detail` 键值对（无明细时给如实文案）；
 *  - **导出（第 13 轮接入）**：`super_admin` 有「导出」按钮 ⇒ 按**当前筛选条件**调 `exportAudits` + 触发下载
 *    + 用服务端条数提示；`ceo` / `department_lead` / `employee` **无按钮但给"仅超级管理员可用"说明**（不静默隐藏）；
 *    超限 `422` 与失败各自如实呈现、且**不假装成功**；
 *  - 错误态可重试、403 ⇒ 无权限态（两者分开）。
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders, signInAs, signOutForTest } from '../../../test/renderWithProviders'
import { AuditLogPage } from '../AuditLogPage'
import { NOT_SET_TEXT } from '../components/AuditDetailDrawer'
import {
  AUDIT_EXPORT_HINT,
  AUDIT_EXPORT_ONLY_ADMIN_NOTE,
  AUDITS_EMPTY_NOTE,
  AUDITS_NO_MATCH_NOTE,
  AuditError,
  MY_AUDITS_EMPTY_NOTE,
  SELF_SCOPE_NOTE,
  exportAudits,
  fetchAuditActions,
  fetchAudits,
} from '../services/auditService'
import type { AuditActionCatalog, AuditPage, AuditRecord } from '../types'
import type { AuditExportOutcome } from '../services/auditService'

vi.mock('../services/auditService', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/auditService')>()
  return {
    ...actual,
    fetchAudits: vi.fn(actual.fetchAudits),
    fetchAuditActions: vi.fn(actual.fetchAuditActions),
    exportAudits: vi.fn(actual.exportAudits),
  }
})

function record(over: Partial<AuditRecord> = {}): AuditRecord {
  return {
    record_id: '1856',
    action: 'skill.enabled',
    actor_id: 'acct-1',
    target_type: 'skill',
    target_id: 'summarize@1.0.0',
    phone_masked: null,
    detail: { skill_key: 'summarize' },
    occurred_at: '2026-09-20T18:00:12.092031Z',
    ...over,
  }
}

function page(items: AuditRecord[], total = items.length): AuditPage {
  return { sample: false, items, total, limit: 50, offset: 0 }
}

const CATALOG: AuditActionCatalog = { sample: false, items: ['skill.enabled', 'plan.approved'], total: 2 }

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchAudits).mockResolvedValue(page([record()]))
  vi.mocked(fetchAuditActions).mockResolvedValue(CATALOG)
})

afterEach(() => {
  signOutForTest()
})

describe('本租户视图（department_lead / ceo / super_admin）', () => {
  it('渲染筛选（含操作人）、记录列表与详情抽屉', async () => {
    signInAs('super_admin')
    renderWithProviders(<AuditLogPage />)

    expect(await screen.findByText('skill.enabled')).toBeInTheDocument()
    expect(screen.getByLabelText('操作人')).toBeInTheDocument()
    expect(screen.getByLabelText('目标类型')).toBeInTheDocument()
    expect(screen.getByText('skill:summarize@1.0.0')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /详\s*情/ }))

    expect(await screen.findByText('审计记录详情：skill.enabled')).toBeInTheDocument()
    expect(await screen.findByDisplayValue('1856')).toBeInTheDocument()
    // `detail` 按**键值对**渲染（键名可见、值可读；详情字段无 `name` ⇒ 用文本与值断言，不用 getByLabelText）
    expect(screen.getByText('skill_key')).toBeInTheDocument()
    expect(await screen.findByDisplayValue('summarize')).toBeInTheDocument()
  })

  it('筛选提交后按新条件重新取数（动作多选 + 目标 + 操作人）', async () => {
    signInAs('ceo')
    renderWithProviders(<AuditLogPage />)
    await screen.findByText('skill.enabled')
    const before = vi.mocked(fetchAudits).mock.calls.length

    await userEvent.click(screen.getByLabelText('动作'))
    await userEvent.click(await screen.findByTitle('plan.approved'))
    await userEvent.type(screen.getByLabelText('目标类型'), 'skill')
    await userEvent.type(screen.getByLabelText('操作人'), 'acct-9')
    await userEvent.click(screen.getByRole('button', { name: /查\s*询/ }))

    await waitFor(() => {
      expect(vi.mocked(fetchAudits).mock.calls.length).toBeGreaterThan(before)
    })
    const calls = vi.mocked(fetchAudits).mock.calls
    const [filters, params] = calls[calls.length - 1]
    expect(filters).toMatchObject({ actions: ['plan.approved'], target_type: 'skill', actor_id: 'acct-9' })
    expect(params).toMatchObject({ limit: 50, offset: 0 })
  })

  it('空态：无记录 vs 筛选未命中（文案不同）', async () => {
    vi.mocked(fetchAudits).mockResolvedValue(page([]))
    signInAs('super_admin')
    renderWithProviders(<AuditLogPage />)
    expect(await screen.findByText(AUDITS_EMPTY_NOTE)).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('目标标识'), 'nope')
    await userEvent.click(screen.getByRole('button', { name: /查\s*询/ }))
    expect(await screen.findByText(AUDITS_NO_MATCH_NOTE)).toBeInTheDocument()
  })

  it('分页：翻页按服务端语义传 offset（不在前端切片）', async () => {
    vi.mocked(fetchAudits).mockResolvedValue(page([record()], 120))
    signInAs('super_admin')
    renderWithProviders(<AuditLogPage />)
    await screen.findByText('skill.enabled')

    await userEvent.click(screen.getByTitle('2'))

    await waitFor(() => {
      const calls = vi.mocked(fetchAudits).mock.calls
      const [, params] = calls[calls.length - 1]
      expect(params).toMatchObject({ limit: 50, offset: 50 })
    })
  })

  it('命中总数可见（走查发现缺口的回归锚点）', async () => {
    vi.mocked(fetchAudits).mockResolvedValue(page([record()], 140))
    signInAs('super_admin')
    renderWithProviders(<AuditLogPage />)

    expect(await screen.findByText('共 140 条记录，本页显示 1 条（单页上限 200 条，请用分页查看）。')).toBeInTheDocument()
  })

  it('导出：超管有按钮，点击后按**当前筛选条件**导出并提示服务端条数', async () => {
    vi.mocked(exportAudits).mockResolvedValue({
      downloaded: true,
      rows: 3,
      filename: 'audit-t-1-20260921T000000Z.csv',
      blob: null,
      note: '',
    } as AuditExportOutcome)
    signInAs('super_admin')
    renderWithProviders(<AuditLogPage />)
    await screen.findByText('skill.enabled')

    expect(screen.getByText(AUDIT_EXPORT_HINT)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /导\s*出/ }))

    // 无筛选时导出的就是"全量"（空条件），条数提示取自服务端回读值
    await waitFor(() => {
      expect(vi.mocked(exportAudits)).toHaveBeenCalledWith({ actions: [] })
    })
    expect(await screen.findByText(/已导出 3 条：audit-t-1-20260921T000000Z\.csv/)).toBeInTheDocument()
  })

  it('导出：筛选后导出带当前条件（不是忽略筛选导全量）', async () => {
    vi.mocked(exportAudits).mockResolvedValue({
      downloaded: true,
      rows: 1,
      filename: 'audit-t-1-20260921T000001Z.csv',
      blob: null,
      note: '',
    } as AuditExportOutcome)
    signInAs('super_admin')
    renderWithProviders(<AuditLogPage />)
    await screen.findByText('skill.enabled')

    await userEvent.type(screen.getByLabelText('目标类型'), 'skill')
    await userEvent.click(screen.getByRole('button', { name: /查\s*询/ }))
    await waitFor(() => {
      expect(vi.mocked(fetchAudits).mock.calls.length).toBeGreaterThan(1)
    })
    await userEvent.click(screen.getByRole('button', { name: /导\s*出/ }))

    await waitFor(() => {
      expect(vi.mocked(exportAudits)).toHaveBeenCalledWith(
        expect.objectContaining({ target_type: 'skill' }),
      )
    })
  })

  it('导出超限（422）：如实呈现服务端原文 + 「没有生成任何文件」，不假装成功', async () => {
    vi.mocked(exportAudits).mockRejectedValue(
      new AuditError('命中 5821 条，超过单次导出上限 5000 条；请缩小时间范围后重试', 'failed'),
    )
    signInAs('super_admin')
    renderWithProviders(<AuditLogPage />)
    await screen.findByText('skill.enabled')

    await userEvent.click(screen.getByRole('button', { name: /导\s*出/ }))

    expect(
      await screen.findByText(/未能导出：命中 5821 条，超过单次导出上限 5000 条；请缩小时间范围后重试/),
    ).toBeInTheDocument()
    expect(screen.getByText(/本次没有生成任何文件/)).toBeInTheDocument()
    expect(screen.queryByText(/已导出 /)).not.toBeInTheDocument()
  })

  it('导出失败（网络类）：可重试，且不写成"没有记录"', async () => {
    vi.mocked(exportAudits).mockRejectedValueOnce(new AuditError('服务不可达：请检查网络后重试。', 'failed'))
    signInAs('super_admin')
    renderWithProviders(<AuditLogPage />)
    await screen.findByText('skill.enabled')

    await userEvent.click(screen.getByRole('button', { name: /导\s*出/ }))
    expect(await screen.findByText(/未能导出：服务不可达/)).toBeInTheDocument()

    vi.mocked(exportAudits).mockResolvedValue({
      downloaded: true,
      rows: 2,
      filename: 'audit-t-1-20260921T000002Z.csv',
      blob: null,
      note: '',
    } as AuditExportOutcome)
    await userEvent.click(screen.getByRole('button', { name: /导\s*出/ }))

    expect(await screen.findByText(/已导出 2 条/)).toBeInTheDocument()
  })

  it('导出：非超管（能查不能导）**无按钮但给"仅超级管理员可用"的说明**（不静默隐藏）', async () => {
    for (const role of ['ceo', 'department_lead', 'employee'] as const) {
      signOutForTest()
      signInAs(role)
      const { unmount } = renderWithProviders(<AuditLogPage />)
      await screen.findByText('skill.enabled')

      expect(screen.getByText(AUDIT_EXPORT_ONLY_ADMIN_NOTE)).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /导\s*出/ })).not.toBeInTheDocument()
      unmount()
    }
  })

  it('错误态可重试（与"没有记录"分开）', async () => {
    vi.mocked(fetchAudits).mockRejectedValueOnce(new AuditError('服务暂时不可用，请稍后重试。', 'failed'))
    signInAs('super_admin')
    renderWithProviders(<AuditLogPage />)

    expect(await screen.findByText('审计记录加载失败，请稍后重试。')).toBeInTheDocument()
    vi.mocked(fetchAudits).mockResolvedValue(page([record()]))
    await userEvent.click(screen.getByRole('button', { name: /重\s*试/ }))

    expect(await screen.findByText('skill.enabled')).toBeInTheDocument()
  })

  it('403：记录列表进入无权限态（不当成"没有记录"）', async () => {
    vi.mocked(fetchAudits).mockRejectedValue(new AuditError('当前岗位不能查看审计日志', 'forbidden'))
    signInAs('super_admin')
    renderWithProviders(<AuditLogPage />)

    expect(await screen.findByText('无权限查看审计记录。')).toBeInTheDocument()
  })

  it('详情：无明细时给如实文案（不显示空区域）', async () => {
    vi.mocked(fetchAudits).mockResolvedValue(page([record({ detail: {}, phone_masked: null, target_id: null })]))
    signInAs('super_admin')
    renderWithProviders(<AuditLogPage />)
    await screen.findByText('skill.enabled')

    await userEvent.click(screen.getByRole('button', { name: /详\s*情/ }))

    expect(await screen.findByText('该记录没有明细。')).toBeInTheDocument()
    // 缺省字段给"未记录"，不编造（手机号 / 目标）
    expect(screen.getAllByDisplayValue(NOT_SET_TEXT).length).toBeGreaterThan(0)
  })
})

describe('我的操作视图（employee：矩阵 ⚠️ 仅本人相关）', () => {
  it('不渲染操作人筛选，并给出"服务端强制自限"的如实说明', async () => {
    signInAs('employee')
    renderWithProviders(<AuditLogPage />)

    expect(await screen.findByText('skill.enabled')).toBeInTheDocument()
    expect(screen.queryByLabelText('操作人')).not.toBeInTheDocument()
    expect(screen.getByText(SELF_SCOPE_NOTE)).toBeInTheDocument()
    // 真机走查修正的回归钉（2026-09-21）：渲染处是**纯文本**，文案里写 `**` 会让星号原样显示
    const rendered = screen
      .getAllByText(/此处只显示/)
      .map((el) => el.textContent ?? '')
      .join('')
    expect(rendered).not.toContain('**')
    expect(rendered).toContain('「你自己」')
    // 导出（矩阵给 super_admin）在员工视图**不给按钮**，但如实说明"仅超级管理员可用"
    expect(screen.getByText(AUDIT_EXPORT_ONLY_ADMIN_NOTE)).toBeInTheDocument()
    expect(screen.queryByText(AUDIT_EXPORT_HINT)).not.toBeInTheDocument()
  })

  it('空态用"我的"口径文案', async () => {
    vi.mocked(fetchAudits).mockResolvedValue(page([]))
    signInAs('employee')
    renderWithProviders(<AuditLogPage />)

    expect(await screen.findByText(MY_AUDITS_EMPTY_NOTE)).toBeInTheDocument()
  })

  it('请求里**不带** actor_id（自限由服务端注入，前端不假装能筛）', async () => {
    signInAs('employee')
    renderWithProviders(<AuditLogPage />)
    await screen.findByText('skill.enabled')

    const calls = vi.mocked(fetchAudits).mock.calls
    const [filters] = calls[calls.length - 1]
    expect(filters).toMatchObject({ actions: [] })
    expect((filters as { actor_id?: string }).actor_id).toBeUndefined()
  })
})

describe('整页无权限（customer_admin）', () => {
  it('矩阵 §3 末列 ❌：整页无权限 + 原因，且**不请求任何数据**', async () => {
    signInAs('customer_admin')
    renderWithProviders(<AuditLogPage />)

    expect(
      await screen.findByText(/审计日志不向客户管理员开放：员工可查看本人操作记录/),
    ).toBeInTheDocument()
    expect(vi.mocked(fetchAudits)).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: /查\s*询/ })).not.toBeInTheDocument()
  })
})