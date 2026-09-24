import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MyAgentsPage } from '../MyAgentsPage'
import { AppShell } from '../../../app/AppShell'
import { renderWithProviders, signInAs } from '../../../test/renderWithProviders'
import { ServiceError } from '../../../utils/serviceKit'
import { createAgent, disableAgent, fetchMyAgents, fetchRoleTemplates, setServiceMode } from '../services/myAgentsService'

/** 取出各取数函数的**真实实现**，供每个用例按需恢复（避免测试之间互相污染）。 */
const REAL = await vi.importActual<typeof import('../services/myAgentsService')>('../services/myAgentsService')

vi.mock('../services/myAgentsService', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/myAgentsService')>()
  return {
    ...actual,
    fetchMyAgents: vi.fn(actual.fetchMyAgents),
    fetchRoleTemplates: vi.fn(actual.fetchRoleTemplates),
    createAgent: vi.fn(actual.createAgent),
    updateAgent: vi.fn(actual.updateAgent),
    disableAgent: vi.fn(actual.disableAgent),
  }
})

describe('MyAgentsPage', () => {
  beforeEach(() => {
    signInAs('employee')
    vi.mocked(fetchMyAgents).mockImplementation(REAL.fetchMyAgents)
    vi.mocked(fetchRoleTemplates).mockImplementation(REAL.fetchRoleTemplates)
    vi.mocked(createAgent).mockImplementation(REAL.createAgent)
    vi.mocked(disableAgent).mockImplementation(REAL.disableAgent)
  })

  afterEach(() => {
    setServiceMode('mock')
  })

  it('就绪：卡片式列表按归属分区，且有统一的"示例数据（未接后端）"标识', async () => {
    render(<MyAgentsPage />)

    expect(screen.getByRole('heading', { level: 2, name: '我的数字员工' })).toBeInTheDocument()
    expect(screen.getByText('示例数据（未接后端）')).toBeInTheDocument()

    expect(await screen.findByText('内容运营助手')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: /我创建的（3）/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: /共享给我的（1）/ })).toBeInTheDocument()
    expect(screen.getByText('客户线索助手')).toBeInTheDocument()
    // 卡片式而非表格
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('四态之一：loading（首屏同步渲染不显示空态文案）', () => {
    vi.mocked(fetchMyAgents).mockImplementation(() => new Promise(() => {}))

    render(<MyAgentsPage />)
    expect(screen.getByText('正在加载，请稍候…')).toBeInTheDocument()
    expect(screen.queryByText('还没有数字员工。可以从岗位模板创建一个。')).not.toBeInTheDocument()
  })

  it('四态之二：empty（空态主操作为"立即创建"，可打开创建抽屉）', async () => {
    vi.mocked(fetchMyAgents).mockResolvedValue({ sample: true, items: [] })

    render(<MyAgentsPage />)
    expect(await screen.findByText('还没有数字员工。可以从岗位模板创建一个。')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '立即创建' }))
    expect(await screen.findByText('从岗位模板创建数字员工')).toBeInTheDocument()
  })

  it('四态之三：error（可重试，不假装空）', async () => {
    vi.mocked(fetchMyAgents).mockRejectedValue(new ServiceError('取数失败', 'failed'))

    render(<MyAgentsPage />)
    expect(await screen.findByText('数字员工列表加载失败，请稍后重试。')).toBeInTheDocument()
    expect(screen.queryByText('还没有数字员工。可以从岗位模板创建一个。')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重\s*试/ })).toBeInTheDocument()
  })

  it('四态之四：forbidden（无权限时说明原因，不静默空列表）', async () => {
    vi.mocked(fetchMyAgents).mockRejectedValue(new ServiceError('无权限', 'forbidden'))

    render(<MyAgentsPage />)
    // 与 error 态文案明确区分：这是"无权限"，不是"加载失败"
    expect(await screen.findByText('无访问权限')).toBeInTheDocument()
    // 2026-09-25（真机走查后）文案更改：原句「请确认该员工是否已共享给你」的前提已失效 ——
    // OP-01 后**未共享的员工根本不出现在列表里**（服务端按 owner∪shares 过滤，不是 403），
    // 把"没被共享"写进 403 文案会引导用户去找一个不存在的"共享开关"。
    expect(screen.getByText('无权限查看数字员工列表，请联系管理员确认你的角色。')).toBeInTheDocument()
    expect(screen.queryByText('数字员工列表加载失败，请稍后重试。')).not.toBeInTheDocument()
    expect(screen.queryByText('还没有数字员工。可以从岗位模板创建一个。')).not.toBeInTheDocument()
  })

  it('mode=http：已接后端口径 —— 创建入口禁用并给原因，归属无法判定单独成区（不假装"我创建的"）', async () => {
    setServiceMode('http')
    vi.mocked(fetchMyAgents).mockResolvedValue({
      sample: false,
      items: [
        {
          agent_key: 'content-ops',
          name: '内容运营助手',
          description: '负责选题与草稿。',
          role_key: 'ops',
          status: 'active',
          created_by: 'acct-0001',
          created_at: '2026-09-10T09:00:00+08:00',
          updated_at: '2026-09-19T09:00:00+08:00',
          last_run_at: null,
          ownership: 'unknown',
          template: null,
        },
      ],
    })

    render(<MyAgentsPage />)

    expect(await screen.findByText('内容运营助手')).toBeInTheDocument()
    // 已接后端必须一眼可辨（与"示例数据"标识互斥）
    expect(screen.getByText('已接入后端数字员工目录接口')).toBeInTheDocument()
    expect(screen.queryByText('示例数据（未接后端）')).not.toBeInTheDocument()

    // 创建本批未接入 ⇒ 禁用 + 给原因（入口保留，不静默隐藏）
    const create = screen.getByRole('button', { name: '从岗位模板创建' })
    expect(create).toBeDisabled()
    // 2026-09-25（真机走查后）措辞由「创建尚未**接入**」改为「创建尚未**接线**」：
    // 「接线」是本项目既定术语，且要点在于区分「**后端已开放**员工侧创建（OP-01）」
    // 与「**前端入口**仍未接线」—— 原文案「后端没有员工侧创建接口」已与事实相反。
    expect(create).toHaveAttribute('title', expect.stringContaining('创建尚未接线'))

    // 归属无法判定：单独成区，**不混进"我创建的"**
    expect(screen.getByRole('heading', { level: 3, name: /归属无法判定（1）/ })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 3, name: /我创建的/ })).not.toBeInTheDocument()
    // 模板未接入：不编造岗位名 / 能力标签
    expect(screen.getByText(/ops（模板未接入（后端未下发岗位模板））/)).toBeInTheDocument()
    // 无运行记录 ⇒ 未验证（不是 0、不是成功）
    expect(screen.getByText('暂无运行记录')).toBeInTheDocument()
  })

  it('共享给我的员工：配置 / 停用禁用且有原因（员工角色）', async () => {
    render(<MyAgentsPage />)

    const sharedCard = (await screen.findByText('客户线索助手')).closest('.ant-pro-card') as HTMLElement
    expect(within(sharedCard).getByRole('button', { name: /配\s*置/ })).toBeDisabled()
    expect(within(sharedCard).getByRole('button', { name: /停\s*用/ })).toBeDisabled()
    expect(within(sharedCard).getByText(/只有创建者或具备「数字员工管理」能力的角色/)).toBeInTheDocument()
  })

  it('停用必须走 DangerConfirm：未输入确认词前不触发任何停用调用', async () => {
    render(<MyAgentsPage />)

    const mineCard = (await screen.findByText('内容运营助手')).closest('.ant-pro-card') as HTMLElement
    await userEvent.click(within(mineCard).getByRole('button', { name: /停\s*用/ }))

    expect(await screen.findByText('停用「内容运营助手」？')).toBeInTheDocument()
    const confirm = screen.getByRole('button', { name: '确认执行' })
    expect(confirm).toBeDisabled()
    expect(vi.mocked(disableAgent)).not.toHaveBeenCalled()

    // 输入错的确认词仍然不可点
    await userEvent.type(screen.getByLabelText('请输入「停用」以确认'), '停用吧')
    expect(screen.getByRole('button', { name: '确认执行' })).toBeDisabled()
    expect(vi.mocked(disableAgent)).not.toHaveBeenCalled()

    // 输入正确后才真正触发，并如实告知"没有写入后端"
    const input = screen.getByLabelText('请输入「停用」以确认')
    await userEvent.clear(input)
    await userEvent.type(input, '停用')
    await userEvent.click(screen.getByRole('button', { name: '确认执行' }))

    expect(vi.mocked(disableAgent)).toHaveBeenCalledWith('sample-content-ops')
    expect(await screen.findByText(/已提交停用「内容运营助手」/)).toBeInTheDocument()
    expect(screen.getByText(/未写入后端/)).toBeInTheDocument()
  })

  it('创建流程：选模板 → 预览 → 提交后回调收到名称与模板键', async () => {
    render(<MyAgentsPage />)

    await userEvent.click(screen.getByRole('button', { name: '从岗位模板创建' }))
    await screen.findByText('从岗位模板创建数字员工')

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByTitle('研发（rd）'))
    expect(await screen.findByText('能力自动继承自岗位，不可放大')).toBeInTheDocument()
    expect(screen.getByText('默认 Skill')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('名称'), '研发小助手')
    await userEvent.type(screen.getByLabelText('工作范围'), '负责需求拆解。')
    // 精确定位抽屉里的提交按钮（页头"从岗位模板创建"也含"创建"二字）
    await userEvent.click(screen.getByRole('button', { name: /^创\s*建$/ }))

    expect(vi.mocked(createAgent)).toHaveBeenCalledWith({
      name: '研发小助手',
      role_key: 'rd',
      description: '负责需求拆解。',
    })
    expect(await screen.findByText(/已提交创建「研发小助手」（岗位：rd）/)).toBeInTheDocument()
  })

  it('壳里选中"我的数字员工"能渲染本页', async () => {
    renderWithProviders(<AppShell />)

    await userEvent.click(screen.getByRole('menuitem', { name: /我的数字员工/ }))

    expect(screen.getByRole('heading', { level: 1, name: '我的数字员工' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: '我的数字员工' })).toBeInTheDocument()
    expect(await screen.findByText('内容运营助手')).toBeInTheDocument()
  })
})