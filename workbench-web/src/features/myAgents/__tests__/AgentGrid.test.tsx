import { act, render, screen, within } from '@testing-library/react'
import { AgentGrid } from '../components/AgentGrid'
import { useSession } from '../../../app/session'
import type { AgentItem, RoleTemplate } from '../types'

const TEMPLATE: RoleTemplate = {
  role_key: 'sales',
  name: '销售',
  mission: '帮销售把客户线索变成可跟进的商机',
  skills: ['crm.lead_intake'],
  tools: ['CRM 读写（受限）'],
  knowledge_scopes: ['产品资料（内部）'],
  memory_policy: { scope: 'project', write_categories: ['客户偏好摘要'] },
  autonomy_level: 'approval_for_risky',
  budget_cents: 5000,
}

function agent(overrides: Partial<AgentItem>): AgentItem {
  return {
    agent_key: 'sample-a',
    name: '示例员工',
    description: '示例说明',
    role_key: 'sales',
    status: 'active',
    created_by: '示例创建者',
    created_at: '2026-09-10T09:00:00+08:00',
    updated_at: '2026-09-19T09:00:00+08:00',
    last_run_at: null,
    ownership: 'mine',
    template: TEMPLATE,
    ...overrides,
  }
}

const MINE = agent({ agent_key: 'sample-mine', name: '我创建的员工' })
const SHARED = agent({ agent_key: 'sample-shared', name: '共享给我的员工', ownership: 'shared' })

describe('AgentGrid', () => {
  beforeEach(() => {
    useSession.setState({ role: 'employee' })
  })

  it('按归属分区渲染，并显示各自数量', () => {
    render(<AgentGrid mine={[MINE]} shared={[SHARED]} />)

    expect(screen.getByRole('heading', { level: 3, name: '我创建的（1）' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: '共享给我的（1）' })).toBeInTheDocument()
    expect(screen.getByText('我创建的员工')).toBeInTheDocument()
    expect(screen.getByText('共享给我的员工')).toBeInTheDocument()
  })

  it('员工角色：共享给我的员工 —— 配置 / 停用禁用且有原因，入口不隐藏', () => {
    render(<AgentGrid mine={[MINE]} shared={[SHARED]} />)

    // 我创建的卡片：可管理（同一屏里出现两个「配置」，故按卡片定位）
    const mineCard = screen.getByText('我创建的员工').closest('.ant-pro-card') as HTMLElement
    expect(within(mineCard).getByRole('button', { name: /配\s*置/ })).toBeEnabled()
    expect(within(mineCard).getByRole('button', { name: /停\s*用/ })).toBeEnabled()

    // 共享的卡片：禁用 + 原因
    const sharedCard = screen.getByText('共享给我的员工').closest('.ant-pro-card') as HTMLElement
    const sharedConfigure = within(sharedCard).getByRole('button', { name: /配\s*置/ })
    expect(sharedConfigure).toBeVisible()
    expect(sharedConfigure).toBeDisabled()
    expect(within(sharedCard).getByRole('button', { name: /停\s*用/ })).toBeDisabled()
    expect(within(sharedCard).getByText(/只有创建者或具备「数字员工管理」能力的角色/)).toBeInTheDocument()
    expect(within(sharedCard).getByText(/当前角色：员工/)).toBeInTheDocument()
  })

  it('具备管理能力的角色：共享给我的员工也可配置 / 停用，不再显示禁用原因', () => {
    act(() => {
      useSession.setState({ role: 'super_admin' })
    })
    render(<AgentGrid mine={[MINE]} shared={[SHARED]} manageShared />)

    const sharedCard = screen.getByText('共享给我的员工').closest('.ant-pro-card') as HTMLElement
    expect(within(sharedCard).getByRole('button', { name: /配\s*置/ })).toBeEnabled()
    expect(within(sharedCard).getByRole('button', { name: /停\s*用/ })).toBeEnabled()
    expect(within(sharedCard).queryByText(/只有创建者或具备/)).not.toBeInTheDocument()
  })

  it('没有共享员工时不渲染该分区', () => {
    render(<AgentGrid mine={[MINE]} shared={[]} />)
    expect(screen.queryByRole('heading', { level: 3, name: /共享给我的/ })).not.toBeInTheDocument()
  })
})