/**
 * 「权限配置」页用例（第 6 轮）。
 *
 * 覆盖口径（见 `docs/contracts/permissions-config-plan.md` §5 验收标准）：
 *  - 三块齐备（角色知识范围 / 数字员工知识范围 / 最近变更）；
 *  - 四态齐备（加载 / 空 / 错误可重试 / 无权限），且**无权限时不渲染任何编辑控件**；
 *  - 空态必须"解释为什么空"，不得用"0 条绑定"冒充内容；审计为空是真实语义（不是加载失败）；
 *  - 写失败（409 / 422）**就地呈现、不关闭抽屉、不假装成功**；写成功后按服务端口径重新取数。
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppShell } from '../../../app/AppShell'
import { SAMPLE_DATA_BADGE, ServiceError } from '../../../utils/serviceKit'
import { renderWithProviders, signInAs, signOutForTest } from '../../../test/renderWithProviders'
import { PermissionsPage } from '../PermissionsPage'
import {
  AGENT_EMPTY_NOTE,
  ROLE_EMPTY_NOTE,
  ScopeWriteError,
  fetchAgentScopes,
  fetchAudits,
  fetchRoleScopes,
  saveScopeBinding,
  setServiceMode,
} from '../services/permissionsService'
import type { AuditPage, ScopePage } from '../types'

/** 真实实现：每个用例按需恢复，避免用例之间互相污染。 */
const REAL = await vi.importActual<typeof import('../services/permissionsService')>(
  '../services/permissionsService',
)

vi.mock('../services/permissionsService', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/permissionsService')>()
  return {
    ...actual,
    fetchRoleScopes: vi.fn(actual.fetchRoleScopes),
    fetchAgentScopes: vi.fn(actual.fetchAgentScopes),
    fetchAudits: vi.fn(actual.fetchAudits),
    saveScopeBinding: vi.fn(actual.saveScopeBinding),
  }
})

const ROLE_ROWS: ScopePage = {
  sample: true,
  rows: [
    { binding_type: 'role', binding_key: 'ops', name: '运营', status: 'active', knowledge_base_ids: ['kb-a'] },
    { binding_type: 'role', binding_key: 'finance', name: '财务', status: 'disabled', knowledge_base_ids: [] },
  ],
}

const AGENT_ROWS: ScopePage = {
  sample: true,
  rows: [
    {
      binding_type: 'agent',
      binding_key: 'content-ops',
      name: '内容运营助手',
      status: 'active',
      knowledge_base_ids: ['kb-a', 'kb-c'],
    },
  ],
}

const AUDITS: AuditPage = {
  sample: true,
  items: [
    {
      binding_type: 'role',
      binding_key: 'ops',
      old_knowledge_base_ids: [],
      new_knowledge_base_ids: ['kb-a'],
      actor_id: 'acct-0001',
      occurred_at: '2026-09-19T10:25:43Z',
    },
  ],
}

function asAdmin(): void {
  signInAs('super_admin')
}

/** 某一行（按岗位 / 员工名称定位）。 */
function rowOf(name: string): HTMLElement {
  return screen.getByText(name).closest('tr') as HTMLElement
}

describe('PermissionsPage（权限配置）', () => {
  beforeEach(() => {
    asAdmin()
    vi.mocked(fetchRoleScopes).mockImplementation(REAL.fetchRoleScopes)
    vi.mocked(fetchAgentScopes).mockImplementation(REAL.fetchAgentScopes)
    vi.mocked(fetchAudits).mockImplementation(REAL.fetchAudits)
    vi.mocked(saveScopeBinding).mockImplementation(REAL.saveScopeBinding)
  })

  afterEach(() => {
    setServiceMode('mock')
    signOutForTest()
  })

  it('① 三块齐备：角色知识范围 / 数字员工知识范围 / 最近变更（含未绑定的如实呈现）', async () => {
    vi.mocked(fetchRoleScopes).mockResolvedValue(ROLE_ROWS)
    vi.mocked(fetchAgentScopes).mockResolvedValue(AGENT_ROWS)
    vi.mocked(fetchAudits).mockResolvedValue(AUDITS)

    renderWithProviders(<PermissionsPage />)

    for (const title of ['角色知识范围', '数字员工知识范围', '最近变更']) {
      expect(screen.getByRole('heading', { level: 3, name: title })).toBeInTheDocument()
    }

    // 角色块：绑定的标识逐个列出；未绑定的行如实写"尚未绑定"，**不写 0 条**
    const opsRow = await screen.findByText('运营')
    expect(within(opsRow.closest('tr') as HTMLElement).getByText('kb-a')).toBeInTheDocument()
    expect(within(rowOf('财务')).getByText('尚未绑定任何知识库')).toBeInTheDocument()
    expect(screen.queryByText(/0 条绑定/)).not.toBeInTheDocument()

    // 数字员工块
    expect(screen.getByText('内容运营助手')).toBeInTheDocument()
    expect(within(rowOf('内容运营助手')).getByText('kb-c')).toBeInTheDocument()

    // 最近变更：只读，`old → new` 两列 + 操作者 + 时间
    expect(screen.getByText('岗位「ops」')).toBeInTheDocument()
    expect(screen.getByText('acct-0001')).toBeInTheDocument()
    expect(screen.getByText('2026-09-19 10:25')).toBeInTheDocument()

    // 样例数据必须一眼可辨（不允许含糊）
    expect(screen.getAllByText(SAMPLE_DATA_BADGE).length).toBeGreaterThanOrEqual(1)
  })

  it('② 加载态：骨架屏（组件库口径：加载中不出现文字，避免与空态混淆），且无失败/空文案', async () => {
    vi.mocked(fetchRoleScopes).mockImplementation(() => new Promise(() => {}))
    vi.mocked(fetchAgentScopes).mockResolvedValue(AGENT_ROWS)
    vi.mocked(fetchAudits).mockResolvedValue(AUDITS)

    renderWithProviders(<PermissionsPage />)

    expect(document.querySelectorAll('.ant-skeleton').length).toBeGreaterThan(0)
    expect(screen.queryByText(ROLE_EMPTY_NOTE)).not.toBeInTheDocument()
    expect(screen.queryByText('岗位知识范围加载失败，请稍后重试。')).not.toBeInTheDocument()
    expect(screen.queryByText('财务')).not.toBeInTheDocument()
  })

  it('② 空 / 错误（可重试）/ 无权限各自可辨，且都不显示样例行', async () => {
    const cases: { mock: () => void; text: string }[] = [
      {
        mock: () => vi.mocked(fetchRoleScopes).mockResolvedValue({ sample: true, rows: [] }),
        text: ROLE_EMPTY_NOTE,
      },
      {
        mock: () =>
          vi.mocked(fetchRoleScopes).mockRejectedValue(new ServiceError('加载失败', 'failed')),
        text: '岗位知识范围加载失败，请稍后重试。',
      },
      {
        mock: () =>
          vi.mocked(fetchRoleScopes).mockRejectedValue(new ServiceError('无权限', 'forbidden')),
        text: '无权限查看知识范围：只有超级管理员可以调整知识库范围。',
      },
    ]

    for (const item of cases) {
      item.mock()
      vi.mocked(fetchAgentScopes).mockResolvedValue(AGENT_ROWS)
      vi.mocked(fetchAudits).mockResolvedValue(AUDITS)
      const { unmount } = renderWithProviders(<PermissionsPage />)

      expect((await screen.findAllByText(item.text)).length).toBeGreaterThanOrEqual(1)
      // 角色块处在非就绪态时不得渲染角色样例行
      expect(screen.queryByText('财务')).not.toBeInTheDocument()
      unmount()
      vi.mocked(fetchRoleScopes).mockImplementation(REAL.fetchRoleScopes)
    }
  })

  it('② 错误态可重试：点"重试"会重新取数', async () => {
    vi.mocked(fetchAgentScopes).mockResolvedValue(AGENT_ROWS)
    vi.mocked(fetchAudits).mockResolvedValue(AUDITS)
    vi.mocked(fetchRoleScopes).mockRejectedValueOnce(new ServiceError('加载失败', 'failed'))
    vi.mocked(fetchRoleScopes).mockResolvedValue(ROLE_ROWS)

    renderWithProviders(<PermissionsPage />)

    expect(await screen.findByText('岗位知识范围加载失败，请稍后重试。')).toBeInTheDocument()
    const before = vi.mocked(fetchRoleScopes).mock.calls.length
    await userEvent.click(screen.getAllByRole('button', { name: /重\s*试/ })[0])

    expect(await screen.findByText('运营')).toBeInTheDocument()
    expect(vi.mocked(fetchRoleScopes).mock.calls.length).toBeGreaterThan(before)
  })

  it('③ 无权限（员工）：整页无权限态，**不渲染任何编辑控件、也不请求数据**', () => {
    signInAs('employee')

    renderWithProviders(<PermissionsPage />)

    expect(screen.getByText('无访问权限')).toBeInTheDocument()
    expect(screen.getByText(/没有「权限配置」权限/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '编辑范围' })).not.toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByText('最近变更')).not.toBeInTheDocument()
    expect(vi.mocked(fetchRoleScopes)).not.toHaveBeenCalled()
    expect(vi.mocked(saveScopeBinding)).not.toHaveBeenCalled()
  })

  it('④ 空态解释为什么空（两块各自说清楚），不用"0 条绑定"冒充内容', async () => {
    vi.mocked(fetchRoleScopes).mockResolvedValue({ sample: true, rows: [] })
    vi.mocked(fetchAgentScopes).mockResolvedValue({ sample: true, rows: [] })
    vi.mocked(fetchAudits).mockResolvedValue({ sample: true, items: [] })

    renderWithProviders(<PermissionsPage />)

    expect(
      await screen.findByText(ROLE_EMPTY_NOTE),
    ).toBeInTheDocument()
    expect(screen.getByText(AGENT_EMPTY_NOTE)).toBeInTheDocument()
    // 审计为空是**真实语义**，不是加载失败
    expect(screen.getByText('暂无变更记录。')).toBeInTheDocument()
    expect(screen.queryByText('变更记录加载失败，请稍后重试。')).not.toBeInTheDocument()
    expect(screen.queryByText(/0 条绑定/)).not.toBeInTheDocument()
  })

  it('⑤ 保存成功：请求参数逐字正确 → 关闭抽屉 → 如实提示 → 按服务端口径重新取数', async () => {
    vi.mocked(fetchRoleScopes).mockResolvedValue(ROLE_ROWS)
    vi.mocked(fetchAgentScopes).mockResolvedValue(AGENT_ROWS)
    vi.mocked(fetchAudits).mockResolvedValue(AUDITS)
    vi.mocked(saveScopeBinding).mockResolvedValue({
      binding: { binding_type: 'role', binding_key: 'ops', knowledge_base_ids: ['kb-a', 'kb-new'] },
      written: true,
      note: '已保存：知识范围已更新。',
    })

    renderWithProviders(<PermissionsPage />)
    await screen.findByText('运营')

    await userEvent.click(within(rowOf('运营')).getByRole('button', { name: '编辑范围' }))
    expect(await screen.findByText('编辑知识范围：运营')).toBeInTheDocument()

    const before = vi.mocked(fetchRoleScopes).mock.calls.length
    await userEvent.type(screen.getByLabelText('知识库标识'), 'kb-new{enter}')
    await userEvent.click(screen.getByRole('button', { name: '保存范围' }))

    await waitFor(() => {
      expect(vi.mocked(saveScopeBinding)).toHaveBeenCalledWith({
        binding_type: 'role',
        binding_key: 'ops',
        knowledge_base_ids: ['kb-a', 'kb-new'],
      })
    })
    expect(screen.getByText(/已保存/)).toBeInTheDocument()
    // 写成功后不本地猜结果：重新取数（含变更记录）
    await waitFor(() => {
      expect(vi.mocked(fetchRoleScopes).mock.calls.length).toBeGreaterThan(before)
    })
    expect(vi.mocked(fetchAudits).mock.calls.length).toBeGreaterThan(1)
    await waitFor(() => {
      expect(screen.queryByText('编辑知识范围：运营')).not.toBeInTheDocument()
    })
  })

  it('⑥ 409（未纳管）：服务端原文就地呈现，抽屉不关闭，也不显示"已保存"', async () => {
    vi.mocked(fetchRoleScopes).mockResolvedValue(ROLE_ROWS)
    vi.mocked(fetchAgentScopes).mockResolvedValue(AGENT_ROWS)
    vi.mocked(fetchAudits).mockResolvedValue(AUDITS)
    vi.mocked(saveScopeBinding).mockRejectedValue(
      new ScopeWriteError('该标识尚未纳入目录，请先在「数字员工设置」中纳管', 'conflict'),
    )

    renderWithProviders(<PermissionsPage />)
    await screen.findByText('运营')

    await userEvent.click(within(rowOf('运营')).getByRole('button', { name: '编辑范围' }))
    await screen.findByText('编辑知识范围：运营')
    await userEvent.click(screen.getByRole('button', { name: '保存范围' }))

    expect(
      await screen.findByText('未能保存：该标识尚未纳入目录，请先在「数字员工设置」中纳管'),
    ).toBeInTheDocument()
    expect(screen.getAllByText(/没有写入任何数据/).length).toBeGreaterThanOrEqual(1)
    expect(screen.queryByText(/已保存/)).not.toBeInTheDocument()
    expect(screen.getByText('编辑知识范围：运营')).toBeInTheDocument()
  })

  it('⑥ 422（参数非法）：回落本地固定文案，仍不关闭抽屉', async () => {
    vi.mocked(fetchRoleScopes).mockResolvedValue(ROLE_ROWS)
    vi.mocked(fetchAgentScopes).mockResolvedValue(AGENT_ROWS)
    vi.mocked(fetchAudits).mockResolvedValue(AUDITS)
    vi.mocked(saveScopeBinding).mockRejectedValue(
      new ScopeWriteError('请求参数不合法，已拒绝。', 'invalid'),
    )

    renderWithProviders(<PermissionsPage />)
    await screen.findByText('运营')

    await userEvent.click(within(rowOf('运营')).getByRole('button', { name: '编辑范围' }))
    await screen.findByText('编辑知识范围：运营')
    await userEvent.click(screen.getByRole('button', { name: '保存范围' }))

    expect(await screen.findByText(/请求参数不合法，已拒绝。/)).toBeInTheDocument()
    expect(screen.queryByText(/extra_forbidden/)).not.toBeInTheDocument()
    expect(screen.getByText('编辑知识范围：运营')).toBeInTheDocument()
  })

  it('⑦ 已接真实数据：标识与样例题注互斥（不出现"示例数据"字样）', async () => {
    setServiceMode('http')
    vi.mocked(fetchRoleScopes).mockResolvedValue({ sample: false, rows: ROLE_ROWS.rows })
    vi.mocked(fetchAgentScopes).mockResolvedValue({ sample: false, rows: [] })
    vi.mocked(fetchAudits).mockResolvedValue({ sample: false, items: [] })

    renderWithProviders(<PermissionsPage />)

    expect(await screen.findByText('已接入真实数据')).toBeInTheDocument()
    expect(screen.queryByText(SAMPLE_DATA_BADGE)).not.toBeInTheDocument()
    // 真实数据下空态依然解释"为什么空"
    expect(await screen.findByText(AGENT_EMPTY_NOTE)).toBeInTheDocument()
  })

  it('⑧ 从**设置弹窗**进入「权限配置」即渲染本页（收敛后仍可到达 —— B3 验收 A8）', async () => {
    // ⚠️ 2026-09-23 改：B3 §7 侧栏收敛后该入口不在侧栏，改走设置弹窗（新的真实路径）。
    renderWithProviders(<AppShell />)

    await userEvent.click(screen.getByRole('button', { name: /设\s*置/ }))
    await userEvent.click(await screen.findByLabelText('打开权限配置'))

    expect(screen.getByRole('heading', { level: 1, name: '权限配置' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: '权限配置' })).toBeInTheDocument()
    expect(await screen.findByText('角色知识范围')).toBeInTheDocument()
    expect(screen.getByText('数字员工知识范围')).toBeInTheDocument()
    expect(screen.getByText('最近变更')).toBeInTheDocument()
  })
})