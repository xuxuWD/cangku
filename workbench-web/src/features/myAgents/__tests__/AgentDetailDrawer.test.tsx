import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AgentDetailDrawer } from '../components/AgentDetailDrawer'
import type { AgentItem, RoleTemplate } from '../types'

const TEMPLATE: RoleTemplate = {
  role_key: 'rd',
  name: '研发',
  mission: '帮研发做需求拆解、代码检视与文档',
  skills: ['rd.repo_inspect', 'rd.spec_draft', 'rd.changelog'],
  tools: ['只读检视集（ls/cat/head/tail/wc 等）', '沙箱执行'],
  knowledge_scopes: ['技术文档（内部）', '接口契约（机密）'],
  memory_policy: { scope: 'project', write_categories: ['方案要点'] },
  autonomy_level: 'approval_for_risky',
  budget_cents: 8000,
}

const AGENT: AgentItem = {
  agent_key: 'sample-rd-assistant',
  name: '研发需求助理',
  description: '负责需求拆解与变更记录草稿。',
  role_key: 'rd',
  status: 'active',
  created_by: '示例创建者（本人）',
  created_at: '2026-09-12T14:00:00+08:00',
  updated_at: '2026-09-18T16:30:00+08:00',
  last_run_at: null,
  ownership: 'mine',
  template: TEMPLATE,
}

describe('AgentDetailDrawer', () => {
  it('只读态：展示详情与能力包，没有提交按钮，关闭前不做未保存确认', async () => {
    let closed = 0
    render(<AgentDetailDrawer open agent={AGENT} mode="view" onClose={() => { closed += 1 }} />)

    expect(await screen.findByText('数字员工详情（只读）')).toBeInTheDocument()
    expect(screen.getByText('sample-rd-assistant')).toBeInTheDocument()
    expect(screen.getByText('所属岗位')).toBeInTheDocument()
    expect(screen.getByText('研发（rd）')).toBeInTheDocument()
    expect(screen.getByText('我创建的')).toBeInTheDocument()
    expect(screen.getByText('创建时间')).toBeInTheDocument()
    expect(screen.getByText('2026-09-12 14:00')).toBeInTheDocument()

    // 状态保真：无运行记录 ⇒ 未验证 + 暂无运行记录（不出现 0 / 成功）
    expect(screen.getByText('未验证')).toBeInTheDocument()
    expect(screen.getByText('暂无运行记录')).toBeInTheDocument()
    expect(screen.queryByText('0')).not.toBeInTheDocument()

    // 能力包 6 项
    for (const label of ['默认 Skill', '工具 / MCP 面', '知识库范围', '记忆策略', '自治档', '单任务预算上限']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(screen.getByText('¥80.00')).toBeInTheDocument()

    // 只读：没有提交按钮，字段禁用
    expect(screen.queryByRole('button', { name: /保\s*存/ })).not.toBeInTheDocument()
    expect(screen.getByLabelText('名称')).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: /关\s*闭/ }))
    expect(closed).toBe(1)
  })

  it('编辑态：可改名称与工作范围，提交回调收到 agent_key 与改后的值', async () => {
    const submitted: { agent_key: string; name: string; description: string }[] = []
    render(
      <AgentDetailDrawer
        open
        agent={AGENT}
        mode="edit"
        onClose={() => {}}
        onSubmit={(input) => {
          submitted.push(input)
        }}
      />,
    )

    const name = await screen.findByLabelText('名称')
    expect(name).toBeEnabled()
    await userEvent.clear(name)
    await userEvent.type(name, '研发助理（改名）')
    await userEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    expect(submitted).toHaveLength(1)
    expect(submitted[0]).toEqual({
      agent_key: 'sample-rd-assistant',
      name: '研发助理（改名）',
      description: '负责需求拆解与变更记录草稿。',
    })
  })
})