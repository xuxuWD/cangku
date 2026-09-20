/**
 * 「数字员工绑定」块用例（第 9 轮）。
 *
 * 覆盖口径（见 `docs/contracts/skill-bindings-api.md` §2 / §3）：
 *  - 列表：`active` / `disabled` 状态如实呈现；**已解除的绑定不能重复解绑**（禁用 + 原因）；
 *  - 解绑走**二次确认**（输入确认词才能执行），成功提示只用**服务端回读值**并重新取数；
 *  - 绑定表单：技能候选**只含「已启用」技能**（界面自我收敛，服务端不拦）；员工支持**手动录入**；
 *  - 写失败**就地呈现服务端原文 + "没有写入任何数据"**，不假装成功；
 *  - 工具面预览：**四种归因分开**（就绪 / 无绑定 / 无已启用技能 / 交集为空）；
 *  - `canBind=false`（`ceo`）：**不请求任何数据**，控件禁用并给原因（不静默隐藏）。
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { BIND_DISABLED_REASON, BindingPanel } from '../components/BindingPanel'
import {
  AGENT_CANDIDATE_EMPTY_NOTE,
  BINDINGS_EMPTY_NOTE,
  SkillError,
  UNBIND_CONFIRM_TITLE,
  bindAgentSkill,
  fetchAgentCandidates,
  fetchAgentTools,
  fetchBindings,
  fetchSkills,
  unbindAgentSkill,
} from '../services/skillsService'
import { AGENT_TOOLS_REASON_TEXT } from '../types'
import type { AgentCandidatePage, SkillBinding, SkillBindingPage, SkillPage, SkillSummary } from '../types'

vi.mock('../services/skillsService', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/skillsService')>()
  return {
    ...actual,
    fetchBindings: vi.fn(actual.fetchBindings),
    fetchSkills: vi.fn(actual.fetchSkills),
    fetchAgentCandidates: vi.fn(actual.fetchAgentCandidates),
    fetchAgentTools: vi.fn(actual.fetchAgentTools),
    bindAgentSkill: vi.fn(actual.bindAgentSkill),
    unbindAgentSkill: vi.fn(actual.unbindAgentSkill),
  }
})

function binding(over: Partial<SkillBinding> = {}): SkillBinding {
  return {
    skill_key: 'summarize',
    agent_key: 'agent-1',
    status: 'active',
    created_by: 'acct-admin',
    created_at: '2026-09-20T06:00:00Z',
    ...over,
  }
}

function skill(over: Partial<SkillSummary> = {}): SkillSummary {
  return {
    skill_key: 'summarize',
    version: '1.0.0',
    name: '摘要助手',
    description: '生成结构化摘要',
    license: 'Apache-2.0',
    allowed_tools: ['fs.read'],
    status: 'enabled',
    source_key: 'manual',
    owner_id: 'acct-1',
    reviewed_by: null,
    created_at: null,
    updated_at: null,
    ...over,
  }
}

function bindingPage(items: SkillBinding[]): SkillBindingPage {
  return { sample: false, items, total: items.length, limit: 200, offset: 0 }
}

function skillPage(items: SkillSummary[]): SkillPage {
  return { sample: false, items, total: items.length, limit: 200, offset: 0 }
}

const CANDIDATES: AgentCandidatePage = {
  sample: false,
  items: [{ agent_key: 'agent-1', name: '内容运营助手' }],
  total: 1,
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchBindings).mockResolvedValue(bindingPage([binding()]))
  vi.mocked(fetchSkills).mockResolvedValue(
    skillPage([skill(), skill({ skill_key: 'draft-skill', version: '1.0.0', status: 'submitted' })]),
  )
  vi.mocked(fetchAgentCandidates).mockResolvedValue(CANDIDATES)
  vi.mocked(fetchAgentTools).mockResolvedValue({
    sample: false,
    tools: { agent_key: 'agent-1', tools: ['fs.read'] },
    note: '',
  })
})

describe('列表与动作可用性', () => {
  it('列表呈现绑定关系，状态如实标注（生效中 / 已解除）', async () => {
    vi.mocked(fetchBindings).mockResolvedValue(
      bindingPage([binding(), binding({ skill_key: 'legacy', agent_key: 'agent-2', status: 'disabled' })]),
    )
    renderWithProviders(<BindingPanel canBind />)

    expect(await screen.findByText('summarize')).toBeInTheDocument()
    expect(screen.getByText('生效中')).toBeInTheDocument()
    expect(screen.getByText('已解除')).toBeInTheDocument()
  })

  it('已解除的绑定：解绑按钮禁用并给出原因（不静默隐藏）', async () => {
    vi.mocked(fetchBindings).mockResolvedValue(bindingPage([binding({ status: 'disabled' })]))
    renderWithProviders(<BindingPanel canBind />)

    const row = (await screen.findByText('summarize')).closest('tr') as HTMLElement
    const button = within(row).getByRole('button', { name: /解\s*绑/ })

    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('title', '该绑定已解除，无需重复解绑。')
  })

  it('空列表：解释为什么空', async () => {
    vi.mocked(fetchBindings).mockResolvedValue(bindingPage([]))
    renderWithProviders(<BindingPanel canBind />)

    expect(await screen.findByText(BINDINGS_EMPTY_NOTE)).toBeInTheDocument()
  })

  it('读失败：错误态可重试', async () => {
    vi.mocked(fetchBindings).mockRejectedValueOnce(new SkillError('服务暂时不可用，请稍后重试。', 'failed'))
    renderWithProviders(<BindingPanel canBind />)

    expect(await screen.findByText('绑定关系加载失败，请稍后重试。')).toBeInTheDocument()
    vi.mocked(fetchBindings).mockResolvedValue(bindingPage([binding()]))
    await userEvent.click(screen.getByRole('button', { name: /重\s*试/ }))

    expect(await screen.findByText('summarize')).toBeInTheDocument()
  })

  it('403：绑定列表进入无权限态（非 super_admin 不得读）', async () => {
    vi.mocked(fetchBindings).mockRejectedValue(new SkillError('只有超级管理员可以绑定或解绑技能', 'forbidden'))
    renderWithProviders(<BindingPanel canBind />)

    expect(await screen.findByText('无权限查看绑定关系：该列表仅超级管理员可读。')).toBeInTheDocument()
  })
})

describe('解绑（二次确认）', () => {
  it('确认后调用服务端，提示用回读值并重新取数', async () => {
    vi.mocked(unbindAgentSkill).mockResolvedValue({
      result: { skill_key: 'summarize', agent_key: 'agent-1', status: 'disabled' },
      written: true,
      note: '操作已受理。',
    })
    renderWithProviders(<BindingPanel canBind />)

    const row = (await screen.findByText('summarize')).closest('tr') as HTMLElement
    const before = vi.mocked(fetchBindings).mock.calls.length
    await userEvent.click(within(row).getByRole('button', { name: /解\s*绑/ }))

    expect(await screen.findByText(UNBIND_CONFIRM_TITLE)).toBeInTheDocument()
    // 未输入确认词时确认按钮不可点（DangerConfirm 的安全默认）
    expect(screen.getByRole('button', { name: '确认解绑' })).toBeDisabled()
    await userEvent.type(screen.getByLabelText('请输入「解绑」以确认'), '解绑')
    await userEvent.click(screen.getByRole('button', { name: '确认解绑' }))

    await waitFor(() => {
      expect(vi.mocked(unbindAgentSkill)).toHaveBeenCalledWith('summarize', 'agent-1')
    })
    expect(await screen.findByText(/已解除：summarize → agent-1（状态：已解除）。/)).toBeInTheDocument()
    await waitFor(() => {
      expect(vi.mocked(fetchBindings).mock.calls.length).toBeGreaterThan(before)
    })
  })

  it('解绑失败：就地呈现服务端原文 + 「没有写入任何数据」', async () => {
    vi.mocked(unbindAgentSkill).mockRejectedValue(new SkillError('binding agent-1/summarize', 'not_found'))
    renderWithProviders(<BindingPanel canBind />)

    const row = (await screen.findByText('summarize')).closest('tr') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: /解\s*绑/ }))
    await userEvent.type(await screen.findByLabelText('请输入「解绑」以确认'), '解绑')
    await userEvent.click(screen.getByRole('button', { name: '确认解绑' }))

    expect(await screen.findByText(/未能完成解绑：binding agent-1\/summarize/)).toBeInTheDocument()
    expect(screen.getByText(/本次没有写入任何数据/)).toBeInTheDocument()
    expect(screen.queryByText(/已解除：/)).not.toBeInTheDocument()
  })
})

describe('绑定表单', () => {
  it('技能候选只含「已启用」技能；员工可手动录入；提交请求体逐键正确', async () => {
    vi.mocked(bindAgentSkill).mockResolvedValue({
      result: { skill_key: 'summarize', agent_key: 'agent-9', status: 'active' },
      written: true,
      note: '操作已受理。',
    })
    renderWithProviders(<BindingPanel canBind />)
    await screen.findByText('summarize')

    await userEvent.click(screen.getByLabelText('技能包'))
    // 已启用技能在候选里；未启用（submitted）的不在
    expect(await screen.findByTitle('summarize@1.0.0')).toBeInTheDocument()
    expect(screen.queryByTitle('draft-skill@1.0.0')).not.toBeInTheDocument()
    await userEvent.click(screen.getByTitle('summarize@1.0.0'))

    // 员工候选来自目录，且允许手动录入目录之外的标识
    await userEvent.type(screen.getByLabelText('数字员工标识'), 'agent-9{enter}')
    await userEvent.click(screen.getByRole('button', { name: /绑\s*定/ }))

    await waitFor(() => {
      expect(vi.mocked(bindAgentSkill)).toHaveBeenCalledWith('summarize', 'agent-9')
    })
    expect(await screen.findByText(/已绑定：summarize → agent-9（状态：生效中）。/)).toBeInTheDocument()
  })

  it('员工候选为空：给出如实说明（目录为空是正常状态），且不阻断手动录入', async () => {
    vi.mocked(fetchAgentCandidates).mockResolvedValue({ sample: false, items: [], total: 0 })
    renderWithProviders(<BindingPanel canBind />)
    await screen.findByText('summarize')

    await userEvent.click(screen.getByLabelText('数字员工标识'))

    expect(await screen.findByText(AGENT_CANDIDATE_EMPTY_NOTE)).toBeInTheDocument()
  })

  it('绑定失败：就地呈现服务端原文 + 「没有写入任何数据」，不假装成功', async () => {
    vi.mocked(bindAgentSkill).mockRejectedValue(new SkillError('只有超级管理员可以绑定或解绑技能', 'forbidden'))
    renderWithProviders(<BindingPanel canBind />)
    await screen.findByText('summarize')

    await userEvent.click(screen.getByLabelText('技能包'))
    await userEvent.click(await screen.findByTitle('summarize@1.0.0'))
    await userEvent.type(screen.getByLabelText('数字员工标识'), 'agent-9{enter}')
    await userEvent.click(screen.getByRole('button', { name: /绑\s*定/ }))

    expect(await screen.findByText(/未能完成绑定：只有超级管理员可以绑定或解绑技能/)).toBeInTheDocument()
    expect(screen.getByText(/本次没有写入任何数据/)).toBeInTheDocument()
    expect(screen.queryByText(/已绑定：/)).not.toBeInTheDocument()
  })
})

describe('工具面预览（四种归因分开）', () => {
  it('就绪：展示工具键标签', async () => {
    renderWithProviders(<BindingPanel canBind />)
    const row = (await screen.findByText('summarize')).closest('tr') as HTMLElement

    await userEvent.click(within(row).getByRole('button', { name: '查看工具面' }))

    expect(await screen.findByText('工具面预览：agent-1')).toBeInTheDocument()
    await waitFor(() => {
      expect(vi.mocked(fetchAgentTools)).toHaveBeenCalledWith('agent-1')
    })
    expect(await screen.findByText('fs.read')).toBeInTheDocument()
  })

  it('无绑定：说明"该员工还没有绑定任何技能"（已解除的绑定不算生效）', async () => {
    vi.mocked(fetchBindings).mockResolvedValue(bindingPage([binding({ status: 'disabled' })]))
    vi.mocked(fetchAgentTools).mockResolvedValue({ sample: false, tools: { agent_key: 'agent-1', tools: [] }, note: '' })
    renderWithProviders(<BindingPanel canBind />)

    const row = (await screen.findByText('summarize')).closest('tr') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: '查看工具面' }))

    expect(await screen.findByText(AGENT_TOOLS_REASON_TEXT.no_binding)).toBeInTheDocument()
  })

  it('无已启用技能：说明"已绑定但都未启用"', async () => {
    vi.mocked(fetchBindings).mockResolvedValue(bindingPage([binding({ skill_key: 'draft-skill' })]))
    vi.mocked(fetchSkills).mockResolvedValue(skillPage([skill({ skill_key: 'draft-skill', status: 'submitted' })]))
    vi.mocked(fetchAgentTools).mockResolvedValue({ sample: false, tools: { agent_key: 'agent-1', tools: [] }, note: '' })
    renderWithProviders(<BindingPanel canBind />)

    const row = (await screen.findByText('draft-skill')).closest('tr') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: '查看工具面' }))

    expect(await screen.findByText(AGENT_TOOLS_REASON_TEXT.none_enabled)).toBeInTheDocument()
  })

  it('交集为空：说明"与执行目录没有交集"', async () => {
    vi.mocked(fetchAgentTools).mockResolvedValue({ sample: false, tools: { agent_key: 'agent-1', tools: [] }, note: '' })
    renderWithProviders(<BindingPanel canBind />)

    const row = (await screen.findByText('summarize')).closest('tr') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: '查看工具面' }))

    expect(await screen.findByText(AGENT_TOOLS_REASON_TEXT.empty_intersection)).toBeInTheDocument()
  })
})

describe('ceo 视角（canBind=false）', () => {
  it('不请求绑定 / 技能 / 候选数据，控件禁用并给原因（不静默隐藏）', async () => {
    renderWithProviders(<BindingPanel canBind={false} />)

    expect(await screen.findByText(BIND_DISABLED_REASON)).toBeInTheDocument()
    expect(vi.mocked(fetchBindings)).not.toHaveBeenCalled()
    expect(vi.mocked(fetchSkills)).not.toHaveBeenCalled()
    expect(vi.mocked(fetchAgentCandidates)).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /绑\s*定/ })).toBeDisabled()
  })
})