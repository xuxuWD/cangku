import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AgentDetailDrawer } from '../components/AgentDetailDrawer'
import { ROLE_TEMPLATES } from '../../myAgents/services/myAgentsService'
import type { RegistryRow } from '../types'

const ROW: RegistryRow = {
  agent_key: 'sample-hr-jd',
  name: '招聘文书助手',
  description: '起草岗位说明与面试记录摘要。',
  role_key: 'hr',
  status: 'active',
  created_by: '示例创建者 03',
  created_at: '2026-09-14T10:20:00+08:00',
  updated_at: '2026-09-16T09:10:00+08:00',
  last_run_at: null,
  template: ROLE_TEMPLATES[1],
  usage: { run_count: null, success_rate: null },
}

describe('AgentDetailDrawer（管理侧只读详情）', () => {
  it('只读态：展示基础 / 创建 / 使用信息与能力包，没有提交按钮', async () => {
    let closed = 0
    render(<AgentDetailDrawer open agent={ROW} onClose={() => { closed += 1 }} />)

    expect(await screen.findByText('数字员工详情（只读）')).toBeInTheDocument()
    expect(screen.getByText('sample-hr-jd')).toBeInTheDocument()
    expect(screen.getByText('招聘文书助手')).toBeInTheDocument()
    expect(screen.getByText('起草岗位说明与面试记录摘要。')).toBeInTheDocument()
    expect(screen.getByText('人事（hr）')).toBeInTheDocument()
    expect(screen.getByText('示例创建者 03')).toBeInTheDocument()
    expect(screen.getByText('已启用')).toBeInTheDocument()
    expect(screen.getByText('2026-09-14 10:20')).toBeInTheDocument()

    // 能力包 6 项（复用员工侧同一份渲染）
    for (const label of ['默认 Skill', '工具 / MCP 面', '知识库范围', '记忆策略', '自治档', '单任务预算上限']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }

    // 只读：没有"保存"，只有"关闭"
    expect(screen.queryByRole('button', { name: /保\s*存/ })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /关\s*闭/ }))
    expect(closed).toBe(1)
  })

  it('状态保真：无运行记录 / 无使用统计都如实呈现，不出现 0 与 0%', async () => {
    render(<AgentDetailDrawer open agent={ROW} onClose={() => {}} />)

    expect(await screen.findByText('暂无运行记录')).toBeInTheDocument()
    // "未验证"在"最近使用"与"使用统计"两处都会出现（都是同一受控枚举）
    expect(screen.getAllByText('未验证').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('暂无运行统计')).toBeInTheDocument()
    expect(screen.queryByText('0')).not.toBeInTheDocument()
    expect(screen.queryByText(/0(\.0)?%/)).not.toBeInTheDocument()
    expect(screen.queryByText(/成功/)).not.toBeInTheDocument()
  })

  it('就绪的使用统计才给数字；草稿状态显示受控枚举标签', async () => {
    render(
      <AgentDetailDrawer
        open
        agent={{ ...ROW, status: 'draft', last_run_at: '2026-09-16T09:10:00+08:00', usage: { run_count: 12, success_rate: 0.9167 } }}
        onClose={() => {}}
      />,
    )

    expect(await screen.findByText('草稿')).toBeInTheDocument()
    expect(screen.getByText('2026-09-16 09:10')).toBeInTheDocument()
    expect(screen.getByText('12 次 · 成功率 91.7%')).toBeInTheDocument()
  })
})