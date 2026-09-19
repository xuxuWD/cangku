import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AgentCard } from '../components/AgentCard'
import type { AgentItem, RoleTemplate } from '../types'

const TEMPLATE: RoleTemplate = {
  role_key: 'ops',
  name: '运营',
  mission: '帮运营做内容生产与发布准备',
  skills: ['content.topic_plan', 'content.draft', 'content.review'],
  tools: ['内容工具', '图片处理（无自动发布）'],
  knowledge_scopes: ['运营手册（内部）', '品牌素材（内部）'],
  memory_policy: { scope: 'project', write_categories: ['选题偏好'] },
  autonomy_level: 'approval_for_risky',
  budget_cents: 4000,
}

const AGENT: AgentItem = {
  agent_key: 'sample-content-ops',
  name: '内容运营助手',
  description: '负责选题、草稿与发布前准备。',
  role_key: 'ops',
  status: 'active',
  created_by: '示例创建者（本人）',
  created_at: '2026-09-10T09:00:00+08:00',
  updated_at: '2026-09-19T09:00:00+08:00',
  last_run_at: '2026-09-19T09:20:00+08:00',
  ownership: 'mine',
  template: TEMPLATE,
}

describe('AgentCard', () => {
  it('卡片字段齐全：头像首字母 / 名称 / 岗位 / 能力标签 / 状态 / 最近使用', () => {
    render(<AgentCard agent={AGENT} manageable />)

    expect(screen.getByText('内')).toBeInTheDocument() // Avatar 首字母，不引用图片文件
    expect(screen.getByText('内容运营助手')).toBeInTheDocument()
    expect(screen.getByText('所属岗位：运营（ops）')).toBeInTheDocument()
    expect(screen.getByText('Skill 3 个')).toBeInTheDocument()
    expect(screen.getByText('知识范围 2 个')).toBeInTheDocument()
    expect(screen.getByText('自治档：平衡')).toBeInTheDocument()
    expect(screen.getByText('已启用')).toBeInTheDocument()
    expect(screen.getByText('我创建的')).toBeInTheDocument()
    expect(screen.getByText('最近使用：2026-09-19 09:20')).toBeInTheDocument()
  })

  it('状态保真：无运行记录显示"暂无运行记录 / 未验证"，不显示 0、不显示成功态', () => {
    render(<AgentCard agent={{ ...AGENT, last_run_at: null }} manageable />)

    expect(screen.getByText('暂无运行记录')).toBeInTheDocument()
    expect(screen.getByText('未验证')).toBeInTheDocument()
    expect(screen.queryByText('最近使用：2026-09-19 09:20')).not.toBeInTheDocument()
    expect(screen.queryByText('0')).not.toBeInTheDocument()
    expect(screen.queryByText(/成功/)).not.toBeInTheDocument()
  })

  it('不可管理：配置 / 停用**仍然可见**但禁用，并给出原因（不静默隐藏）', () => {
    render(<AgentCard agent={{ ...AGENT, ownership: 'shared' }} manageable={false} manageDeniedReason="只有创建者可以配置。" />)

    const configure = screen.getByRole('button', { name: /配\s*置/ })
    const disable = screen.getByRole('button', { name: /停\s*用/ })
    expect(configure).toBeVisible()
    expect(disable).toBeVisible()
    expect(configure).toBeDisabled()
    expect(disable).toBeDisabled()
    expect(screen.getByText('只有创建者可以配置。')).toBeInTheDocument()

    // 只读与使用类操作不受影响
    expect(screen.getByRole('button', { name: '查看详情' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '发起任务' })).toBeEnabled()
  })

  it('可管理：配置 / 停用可点，并分别回调', async () => {
    const calls: string[] = []
    render(
      <AgentCard
        agent={AGENT}
        manageable
        onStartTask={() => calls.push('start')}
        onOpenDetail={() => calls.push('detail')}
        onConfigure={() => calls.push('configure')}
        onRequestDisable={() => calls.push('disable')}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: '发起任务' }))
    await userEvent.click(screen.getByRole('button', { name: '查看详情' }))
    await userEvent.click(screen.getByRole('button', { name: /配\s*置/ }))
    await userEvent.click(screen.getByRole('button', { name: /停\s*用/ }))

    expect(calls).toEqual(['start', 'detail', 'configure', 'disable'])
  })
})