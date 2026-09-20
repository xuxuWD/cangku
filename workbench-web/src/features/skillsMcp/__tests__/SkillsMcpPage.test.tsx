/**
 * 「Skill & MCP」页用例（第 8 轮）。
 *
 * 覆盖口径（见 `docs/contracts/skills-mcp-api.md` §3 / §4）：
 *  - **两视图 + 整页无权限**：`skill.manage`（ceo / super_admin）⇒ 管理视图；
 *    `skill.submit`（employee / department_lead）⇒ 员工视图（提交表单 + 只读列表）；
 *    都没有（`customer_admin`）⇒ 整页无权限态 + 原因，**不请求任何数据**；
 *  - **四态齐备**（加载 / 空 / 错误可重试 / 无权限），空态**解释为什么空**；
 *  - 状态机驱动按钮：非法前置状态**禁用 + 给原因**（`title`），不静默隐藏；`rejected` 为终态；
 *  - **不能审自己的包**：按"提交人 = 当前登录账号"预置禁用 + 原因（服务端仍会再判 `403`）；
 *  - 写失败**就地呈现、不关闭抽屉、不假装成功**；成功只用**服务端回读值**提示；
 *  - MCP 如实呈现「尚未接入」，**不伪造服务器 / 工具清单**。
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders, signInAs, signOutForTest } from '../../../test/renderWithProviders'
import { MEMBER_REVIEW_ONLY_NOTE, PERMISSION_REASON, SkillsMcpPage } from '../SkillsMcpPage'
import { READ_ONLY_REASON, NOT_REVIEWED_TEXT, disabledReasonFor } from '../components/SkillListPanel'
import {
  MCP_NOT_CONNECTED_TITLE,
  MY_SKILLS_EMPTY_NOTE,
  SKILLS_EMPTY_NOTE,
  SkillError,
  enableSkill,
  fetchAgentCandidates,
  fetchBindings,
  fetchSkillContent,
  fetchSkills,
  submitSkill,
} from '../services/skillsService'
import { BINDING_GOVERNANCE_ONLY_NOTE, BIND_DISABLED_REASON } from '../components/BindingPanel'
import type { SkillBindingPage, SkillPage, SkillSummary } from '../types'

vi.mock('../services/skillsService', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/skillsService')>()
  return {
    ...actual,
    fetchSkills: vi.fn(actual.fetchSkills),
    fetchSkillContent: vi.fn(actual.fetchSkillContent),
    submitSkill: vi.fn(actual.submitSkill),
    reviewSkill: vi.fn(actual.reviewSkill),
    enableSkill: vi.fn(actual.enableSkill),
    disableSkill: vi.fn(actual.disableSkill),
    fetchBindings: vi.fn(actual.fetchBindings),
    fetchAgentCandidates: vi.fn(actual.fetchAgentCandidates),
  }
})

function skill(over: Partial<SkillSummary> = {}): SkillSummary {
  return {
    skill_key: 'summarize',
    version: '1.0.0',
    name: '摘要助手',
    description: '生成结构化摘要',
    license: 'Apache-2.0',
    allowed_tools: ['fs.read'],
    status: 'submitted',
    source_key: 'manual',
    owner_id: 'acct-other',
    reviewed_by: null,
    created_at: '2026-09-20T02:00:00Z',
    updated_at: '2026-09-20T02:00:00Z',
    ...over,
  }
}

function page(items: SkillSummary[]): SkillPage {
  return { sample: false, items, total: items.length, limit: 200, offset: 0 }
}

const EMPTY_BINDING_PAGE: SkillBindingPage = { sample: false, items: [], total: 0, limit: 200, offset: 0 }

/** 表格行（按行内文本定位；列表是异步取数，必须等文本出现）。 */
async function rowOf(text: string): Promise<HTMLElement> {
  const cell = await screen.findByText(text)
  const row = cell.closest('tr')
  if (!row) throw new Error(`未找到包含「${text}」的表格行`)
  return row as HTMLElement
}

/**
 * 两个汉字按钮的可见文案会被 AntD 自动插入空格（「提 交」）⇒ 一律用宽松正则匹配。
 * 四个汉字的按钮不插空格，可直接精确匹配。
 */
const TWO_CHAR = (text: string) => new RegExp(`^${text[0]}\\s*${text[1]}$`)

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchSkills).mockResolvedValue(page([skill()]))
  vi.mocked(fetchBindings).mockResolvedValue(EMPTY_BINDING_PAGE)
  vi.mocked(fetchAgentCandidates).mockResolvedValue({ sample: false, items: [], total: 0 })
  vi.mocked(fetchSkillContent).mockResolvedValue({
    sample: false,
    content: { skill_key: 'summarize', version: '1.0.0', content_body: '# 正文', content_sha256: 'a'.repeat(64) },
    note: '',
  })
})

afterEach(() => {
  signOutForTest()
})

describe('管理视图（skill.manage：ceo / super_admin）', () => {
  it('列表呈现技能包、状态与审核人（未审核不编造审核人）', async () => {
    signInAs('super_admin')
    renderWithProviders(<SkillsMcpPage />)

    expect(await screen.findByText('summarize@1.0.0')).toBeInTheDocument()
    expect(screen.getByText('已提交')).toBeInTheDocument()
    expect(screen.getByText('手工申报')).toBeInTheDocument()
    expect(screen.getByText(NOT_REVIEWED_TEXT)).toBeInTheDocument()
  })

  it('ceo 也能进入管理视图（矩阵 §3：复核 / 启用 / 停用 = ceo + super_admin）', async () => {
    signInAs('ceo')
    renderWithProviders(<SkillsMcpPage />)

    expect(await screen.findByText('summarize@1.0.0')).toBeInTheDocument()
    expect(screen.queryByText(PERMISSION_REASON)).not.toBeInTheDocument()
  })

  it('绑定块：super_admin 会请求绑定数据；ceo 只看到"由超级管理员执行"且**不请求**绑定数据', async () => {
    signInAs('super_admin')
    const { unmount } = renderWithProviders(<SkillsMcpPage />)
    expect(await screen.findByText('数字员工绑定')).toBeInTheDocument()
    await waitFor(() => {
      expect(vi.mocked(fetchBindings)).toHaveBeenCalled()
    })

    unmount()
    vi.clearAllMocks()
    signInAs('ceo')
    renderWithProviders(<SkillsMcpPage />)
    expect(await screen.findByText(BIND_DISABLED_REASON)).toBeInTheDocument()
    expect(vi.mocked(fetchBindings)).not.toHaveBeenCalled()
  })

  it('合法前置状态：`submitted` 行可审核；`enable` 在该状态下禁用并给出原因', async () => {
    signInAs('super_admin')
    renderWithProviders(<SkillsMcpPage />)

    const row = await rowOf('summarize@1.0.0')
    const review = within(row).getByRole('button', { name: '审核通过' })
    const enable = within(row).getByRole('button', { name: TWO_CHAR('启用') })

    expect(review).toBeEnabled()
    expect(review).not.toHaveAttribute('title')
    expect(enable).toBeDisabled()
    expect(enable).toHaveAttribute('title', '该技能包尚未审核通过，不能启用。')
  })

  it('`rejected` 是终态：四个动作全部禁用并给出原因（不静默隐藏按钮）', async () => {
    vi.mocked(fetchSkills).mockResolvedValue(page([skill({ status: 'rejected' })]))
    signInAs('super_admin')
    renderWithProviders(<SkillsMcpPage />)

    const row = await rowOf('summarize@1.0.0')
    for (const name of ['审核通过', TWO_CHAR('退回'), TWO_CHAR('启用'), TWO_CHAR('停用')]) {
      const button = within(row).getByRole('button', { name })
      expect(button).toBeDisabled()
      expect(button).toHaveAttribute('title', expect.stringContaining('终态'))
    }
  })

  it('不能审自己的包：提交人 = 当前登录账号时，审核按钮预置禁用 + 给原因（服务端再判 403）', async () => {
    vi.mocked(fetchSkills).mockResolvedValue(page([skill({ owner_id: 'acct-self' })]))
    signInAs('super_admin', 'acct-self')
    renderWithProviders(<SkillsMcpPage />)

    const row = await rowOf('summarize@1.0.0')
    const review = within(row).getByRole('button', { name: '审核通过' })

    expect(review).toBeDisabled()
    expect(review).toHaveAttribute('title', '不能审核自己提交的技能包（请由其他管理角色审核）。')
    // 启停不受"自审"限制（服务端也允许本人启停自己的包）
    expect(within(row).getByRole('button', { name: TWO_CHAR('启用') })).toHaveAttribute(
      'title',
      '该技能包尚未审核通过，不能启用。',
    )
  })

  it('动作成功：提示只用服务端回读值，并重新取数', async () => {
    vi.mocked(fetchSkills).mockResolvedValue(page([skill({ status: 'approved', reviewed_by: 'acct-9' })]))
    vi.mocked(enableSkill).mockResolvedValue({
      skill: skill({ status: 'enabled', reviewed_by: 'acct-9' }),
      written: true,
      note: '操作已受理。',
    })
    signInAs('super_admin')
    renderWithProviders(<SkillsMcpPage />)

    const before = vi.mocked(fetchSkills).mock.calls.length
    await userEvent.click(within(await rowOf('summarize@1.0.0')).getByRole('button', { name: TWO_CHAR('启用') }))

    await waitFor(() => {
      expect(vi.mocked(enableSkill)).toHaveBeenCalledWith('summarize', '1.0.0')
    })
    expect(await screen.findByText(/已启用：「summarize@1.0.0」（当前状态：已启用）。/)).toBeInTheDocument()
    await waitFor(() => {
      expect(vi.mocked(fetchSkills).mock.calls.length).toBeGreaterThan(before)
    })
  })

  it('动作失败：就地呈现服务端原文 + 「没有写入任何数据」提示，不假装成功', async () => {
    vi.mocked(fetchSkills).mockResolvedValue(page([skill({ status: 'approved' })]))
    vi.mocked(enableSkill).mockRejectedValue(
      new SkillError('只有企业负责人或超级管理员可以审核或启用技能包', 'forbidden'),
    )
    signInAs('super_admin')
    renderWithProviders(<SkillsMcpPage />)

    await userEvent.click(within(await rowOf('summarize@1.0.0')).getByRole('button', { name: TWO_CHAR('启用') }))

    expect(
      await screen.findByText('未能完成操作：只有企业负责人或超级管理员可以审核或启用技能包'),
    ).toBeInTheDocument()
    expect(screen.getByText(/本次没有写入任何数据/)).toBeInTheDocument()
    expect(screen.queryByText(/已启用：/)).not.toBeInTheDocument()
  })

  it('详情抽屉：正文按需拉取（列表不带正文）', async () => {
    signInAs('super_admin')
    renderWithProviders(<SkillsMcpPage />)

    await userEvent.click(within(await rowOf('summarize@1.0.0')).getByRole('button', { name: TWO_CHAR('详情') }))

    expect(await screen.findByText('技能包详情：summarize@1.0.0')).toBeInTheDocument()
    await waitFor(() => {
      expect(vi.mocked(fetchSkillContent)).toHaveBeenCalledWith('summarize', '1.0.0')
    })
    expect(await screen.findByDisplayValue('# 正文')).toBeInTheDocument()
  })

  it('空列表：解释为什么空（不是"0 条"）；MCP 如实说明尚未接入', async () => {
    vi.mocked(fetchSkills).mockResolvedValue(page([]))
    signInAs('super_admin')
    renderWithProviders(<SkillsMcpPage />)

    expect(await screen.findByText(SKILLS_EMPTY_NOTE)).toBeInTheDocument()
    expect(screen.getByText(new RegExp(MCP_NOT_CONNECTED_TITLE))).toBeInTheDocument()
  })

  it('取数失败：错误态可重试（重试后重新请求）', async () => {
    // ⚠️ 绑定块也用 `fetchSkills` 取"已启用"候选 ⇒ 失败必须**限定在技能包列表区域**断言，
    // 否则同一 mock 被两个消费者共用，断言会落到另一个块上（本用例曾因此假红）。
    vi.mocked(fetchSkills).mockRejectedValue(new SkillError('服务暂时不可用，请稍后重试。', 'failed'))
    signInAs('super_admin')
    renderWithProviders(<SkillsMcpPage />)

    const listRegion = (await screen.findByText('技能包列表')).closest('div') as HTMLElement
    expect(await within(listRegion).findByText('技能包列表加载失败，请稍后重试。')).toBeInTheDocument()
    vi.mocked(fetchSkills).mockResolvedValue(page([skill()]))
    await userEvent.click(within(listRegion).getByRole('button', { name: TWO_CHAR('重试') }))

    expect(await screen.findByText('summarize@1.0.0')).toBeInTheDocument()
  })

  it('服务端 403：列表进入无权限态（与"加载失败"分开）', async () => {
    vi.mocked(fetchSkills).mockRejectedValue(new SkillError('无权限执行该操作。', 'forbidden'))
    signInAs('super_admin')
    renderWithProviders(<SkillsMcpPage />)

    expect(await screen.findByText('无权限查看技能包列表：技能入口不向客户管理员开放。')).toBeInTheDocument()
  })
})

describe('员工视图（skill.submit：employee / department_lead）', () => {
  it('员工可提交并可查看列表；四个管理动作全部禁用 + 给出"由谁执行"的原因', async () => {
    signInAs('employee')
    renderWithProviders(<SkillsMcpPage />)

    expect(await screen.findByRole('button', { name: '提交技能包' })).toBeInTheDocument()
    expect(await screen.findByText('summarize@1.0.0')).toBeInTheDocument()
    expect(screen.getByText(MEMBER_REVIEW_ONLY_NOTE)).toBeInTheDocument()

    const row = await rowOf('summarize@1.0.0')
    for (const name of ['审核通过', TWO_CHAR('退回'), TWO_CHAR('启用'), TWO_CHAR('停用')]) {
      const button = within(row).getByRole('button', { name })
      expect(button).toBeDisabled()
      expect(button).toHaveAttribute('title', READ_ONLY_REASON)
    }
  })

  it('员工空列表：按"本人可见范围"解释（不是我可见的有内容但不显示）', async () => {
    vi.mocked(fetchSkills).mockResolvedValue(page([]))
    signInAs('department_lead')
    renderWithProviders(<SkillsMcpPage />)

    expect(await screen.findByText(MY_SKILLS_EMPTY_NOTE)).toBeInTheDocument()
  })

  it('绑定块：员工视图只给治理面说明，且**不请求**绑定数据（不伪造空态）', async () => {
    signInAs('employee')
    renderWithProviders(<SkillsMcpPage />)

    expect(await screen.findByText(BINDING_GOVERNANCE_ONLY_NOTE)).toBeInTheDocument()
    expect(vi.mocked(fetchBindings)).not.toHaveBeenCalled()
  })

  it('提交成功：请求体逐键对齐（九个键），提示用服务端回读值，抽屉关闭', async () => {
    vi.mocked(fetchSkills).mockResolvedValue(page([]))
    vi.mocked(submitSkill).mockResolvedValue({
      skill: skill({ owner_id: 'acct-self' }),
      written: true,
      note: '操作已受理。',
    })
    signInAs('employee')
    renderWithProviders(<SkillsMcpPage />)

    await userEvent.click(await screen.findByRole('button', { name: '提交技能包' }))
    await userEvent.type(screen.getByLabelText('技能包标识'), 'summarize')
    await userEvent.type(screen.getByLabelText('版本号'), '1.0.0')
    await userEvent.type(screen.getByLabelText('名称'), '摘要助手')
    await userEvent.type(screen.getByLabelText('描述'), '生成结构化摘要')
    await userEvent.click(screen.getByLabelText('许可'))
    await userEvent.click(await screen.findByTitle('Apache-2.0'))
    await userEvent.click(screen.getByLabelText('可调用工具'))
    await userEvent.click(await screen.findByTitle('fs.read'))
    await userEvent.type(screen.getByLabelText('正文指纹（content_sha256）'), 'a'.repeat(64))
    await userEvent.type(screen.getByLabelText('正文'), '# 摘要助手')
    await userEvent.click(screen.getByRole('button', { name: TWO_CHAR('提交') }))

    await waitFor(() => {
      expect(vi.mocked(submitSkill)).toHaveBeenCalledTimes(1)
    })
    expect(vi.mocked(submitSkill).mock.calls[0][0]).toEqual({
      skill_key: 'summarize',
      version: '1.0.0',
      name: '摘要助手',
      description: '生成结构化摘要',
      license: 'Apache-2.0',
      allowed_tools: ['fs.read'],
      source_key: 'manual',
      content_sha256: 'a'.repeat(64),
      content_body: '# 摘要助手',
    })
    expect(await screen.findByText(/已提交：「summarize@1.0.0」（当前状态：已提交）。/)).toBeInTheDocument()
  })

  it('提交失败：抽屉不关闭、如实呈现服务端原文，且不假装成功', async () => {
    vi.mocked(fetchSkills).mockResolvedValue(page([]))
    vi.mocked(submitSkill).mockRejectedValue(new SkillError('content_sha256 与技能包正文指纹不一致', 'invalid'))
    signInAs('employee')
    renderWithProviders(<SkillsMcpPage />)

    await userEvent.click(await screen.findByRole('button', { name: '提交技能包' }))
    await userEvent.type(screen.getByLabelText('技能包标识'), 'summarize')
    await userEvent.type(screen.getByLabelText('版本号'), '1.0.0')
    await userEvent.type(screen.getByLabelText('名称'), '摘要助手')
    await userEvent.type(screen.getByLabelText('描述'), '生成结构化摘要')
    await userEvent.click(screen.getByLabelText('许可'))
    await userEvent.click(await screen.findByTitle('Apache-2.0'))
    await userEvent.click(screen.getByLabelText('可调用工具'))
    await userEvent.click(await screen.findByTitle('fs.read'))
    await userEvent.type(screen.getByLabelText('正文指纹（content_sha256）'), 'b'.repeat(64))
    await userEvent.type(screen.getByLabelText('正文'), '# 摘要助手')
    await userEvent.click(screen.getByRole('button', { name: TWO_CHAR('提交') }))

    expect(await screen.findByText(/content_sha256 与技能包正文指纹不一致/)).toBeInTheDocument()
    // 抽屉仍在（标题可见），且没有"已提交"的假成功提示
    expect(await screen.findByText('提交技能包', { selector: '.ant-drawer-title' })).toBeVisible()
    expect(screen.queryByText(/已提交：/)).not.toBeInTheDocument()
  })
})

describe('整页无权限（customer_admin）', () => {
  it('无任何技能能力：整页无权限态 + 原因，且**不请求任何数据**', async () => {
    signInAs('customer_admin')
    renderWithProviders(<SkillsMcpPage />)

    expect(await screen.findByText(PERMISSION_REASON)).toBeInTheDocument()
    expect(vi.mocked(fetchSkills)).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: '提交技能包' })).not.toBeInTheDocument()
  })
})

describe('禁用原因判定（纯函数，锚点）', () => {
  it('员工只读：任何状态都返回"由谁执行"的原因', () => {
    for (const status of ['submitted', 'approved', 'enabled', 'disabled', 'rejected', 'unknown'] as const) {
      expect(
        disabledReasonFor('enable', skill({ status }), { readOnly: true, currentUserId: 'acct-self' }),
      ).toBe(READ_ONLY_REASON)
    }
  })

  it('管理视图：自审仅拦"审核"两个动作，不拦启用 / 停用', () => {
    const own = skill({ status: 'submitted', owner_id: 'acct-self' })
    expect(disabledReasonFor('review_approve', own, { readOnly: false, currentUserId: 'acct-self' })).toContain(
      '不能审核自己提交的技能包',
    )
    expect(disabledReasonFor('review_reject', own, { readOnly: false, currentUserId: 'acct-self' })).toContain(
      '不能审核自己提交的技能包',
    )
    expect(disabledReasonFor('enable', own, { readOnly: false, currentUserId: 'acct-self' })).toContain(
      '尚未审核通过',
    )
    // 当前账号未知（未取到 user_id）时不预置禁用 ⇒ 交由服务端判定
    expect(disabledReasonFor('review_approve', own, { readOnly: false, currentUserId: null })).toBeNull()
  })
})