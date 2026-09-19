import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AgentRegistryPage } from '../AgentRegistryPage'
import { AppShell } from '../../../app/AppShell'
import { renderWithProviders, signInAs } from '../../../test/renderWithProviders'
import { ServiceError } from '../../../utils/serviceKit'
import { ROLE_TEMPLATES } from '../../myAgents/services/myAgentsService'
import {
  fetchRegistryAgents,
  fetchRegistryStats,
  setAgentStatus,
  setServiceMode,
} from '../services/agentRegistryService'
import { REGISTRY_PAGE_SIZE } from '../types'

/** 真实实现：每个用例按需恢复，避免测试之间互相污染。 */
const REAL = await vi.importActual<typeof import('../services/agentRegistryService')>('../services/agentRegistryService')

vi.mock('../services/agentRegistryService', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/agentRegistryService')>()
  return {
    ...actual,
    fetchRegistryAgents: vi.fn(actual.fetchRegistryAgents),
    fetchRegistryStats: vi.fn(actual.fetchRegistryStats),
    setAgentStatus: vi.fn(actual.setAgentStatus),
  }
})

/** 管理角色（本页仅管理角色可见）。 */
function asAdmin(): void {
  signInAs('super_admin')
}

/** 定位某一行（按名称）。 */
function rowOf(name: string): HTMLElement {
  return screen.getByText(name).closest('tr') as HTMLElement
}

/** 选下拉：先点开，再选项。 */
async function pick(label: string, option: string): Promise<void> {
  await userEvent.click(screen.getByLabelText(label))
  await userEvent.click(await screen.findByTitle(option))
}

describe('AgentRegistryPage（数字员工注册中心）', () => {
  beforeEach(() => {
    asAdmin()
    vi.mocked(fetchRegistryAgents).mockImplementation(REAL.fetchRegistryAgents)
    vi.mocked(fetchRegistryStats).mockImplementation(REAL.fetchRegistryStats)
    vi.mocked(setAgentStatus).mockImplementation(REAL.setAgentStatus)
  })

  afterEach(() => {
    setServiceMode('mock')
  })

  it('① 四态：loading / empty / error / forbidden 各自可辨，且都不显示样例行', async () => {
    const cases = [
      { mock: () => vi.mocked(fetchRegistryAgents).mockImplementation(() => new Promise(() => {})), text: '正在加载，请稍候…' },
      {
        mock: () =>
          vi.mocked(fetchRegistryAgents).mockResolvedValue({
            sample: true,
            items: [],
            total: 0,
            limit: REGISTRY_PAGE_SIZE,
            offset: 0,
          }),
        text: '没有符合条件的数字员工。',
      },
      { mock: () => vi.mocked(fetchRegistryAgents).mockRejectedValue(new ServiceError('失败', 'failed')), text: '数字员工列表加载失败，请稍后重试。' },
      { mock: () => vi.mocked(fetchRegistryAgents).mockRejectedValue(new ServiceError('无权限', 'forbidden')), text: '无权限查看数字员工列表，请联系管理员。' },
    ]

    for (const item of cases) {
      item.mock()
      const { unmount } = render(<AgentRegistryPage />)
      // 用 waitFor + getByText：状态切换时节点可能被重建，先取到再断言会拿到"脱离文档"的旧节点
      await waitFor(() => {
        expect(screen.getByText(item.text)).toBeInTheDocument()
      })
      expect(screen.queryByText('内容运营助手')).not.toBeInTheDocument()
      unmount()
      vi.mocked(fetchRegistryAgents).mockImplementation(REAL.fetchRegistryAgents)
    }
  })

  it('① 无权限（员工角色）：渲染无权限态（原因 + 申请入口），**不渲染空表格、也不请求数据**', () => {
    signInAs('employee')
    render(<AgentRegistryPage />)

    expect(screen.getByText('无访问权限')).toBeInTheDocument()
    expect(screen.getByText(/没有「数字员工管理」权限/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '申请权限' })).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByText('全部（含草稿）')).not.toBeInTheDocument()
    expect(vi.mocked(fetchRegistryAgents)).not.toHaveBeenCalled()
  })

  it('② 列齐全：员工标识 / 名称 / 岗位 / 创建者 / 状态 / 能力标签 / 使用统计 / 最近使用 / 操作', async () => {
    render(<AgentRegistryPage />)

    expect(await screen.findByText('内容运营助手')).toBeInTheDocument()
    for (const header of ['员工标识', '名称', '所属岗位', '创建者', '状态', '能力标签', '使用统计', '最近使用', '操作']) {
      expect(screen.getByRole('columnheader', { name: header })).toBeInTheDocument()
    }

    const row = rowOf('内容运营助手')
    expect(within(row).getByText('sample-ops-content')).toBeInTheDocument()
    expect(within(row).getByText('运营（ops）')).toBeInTheDocument()
    expect(within(row).getByText('示例创建者 01')).toBeInTheDocument()
    expect(within(row).getByText('Skill 3 · 知识范围 2 · 自治档 平衡')).toBeInTheDocument()
    expect(within(row).getByText('12 次 · 成功率 91.7%')).toBeInTheDocument()

    // 受控枚举：启用 / 停用 / 草稿三种状态行都在（草稿是后端尚无的枚举值，已在契约标注）
    expect(screen.getAllByText('已启用').length).toBeGreaterThan(0)
    expect(screen.getAllByText('已停用').length).toBeGreaterThan(0)
    // 「草稿」既是状态标签也是指标卡标签，这里断言的是行内状态标签
    expect(within(rowOf('运营选题助手（草稿）')).getByText('草稿')).toBeInTheDocument()
  })

  it('③ 筛选：条件**原样透传**给服务层（断言调用参数，而不是断言前端过滤结果）', async () => {
    render(<AgentRegistryPage />)
    await screen.findByText('内容运营助手')
    vi.mocked(fetchRegistryAgents).mockClear()

    await pick('岗位', '运营（ops）')
    await pick('状态', '草稿')
    await userEvent.type(screen.getByLabelText('创建者'), '示例创建者 01')
    await userEvent.type(screen.getByLabelText('名称'), '助手')
    await userEvent.click(screen.getByRole('button', { name: /查\s*询/ }))

    expect(vi.mocked(fetchRegistryAgents)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(fetchRegistryAgents)).toHaveBeenCalledWith({
      role_key: 'ops',
      status: 'draft',
      created_by: '示例创建者 01',
      keyword: '助手',
      page: 1,
      pageSize: REGISTRY_PAGE_SIZE,
    })
  })

  it('③ 页面不自行过滤：服务端返回空页时就显示空态（即使本地样例里有数据）', async () => {
    render(<AgentRegistryPage />)
    await screen.findByText('内容运营助手')

    vi.mocked(fetchRegistryAgents).mockResolvedValue({
      sample: true,
      items: [],
      total: 0,
      limit: REGISTRY_PAGE_SIZE,
      offset: 0,
    })
    await pick('岗位', '财务（finance）')
    await userEvent.click(screen.getByRole('button', { name: /查\s*询/ }))

    expect(await screen.findByText('没有符合条件的数字员工。')).toBeInTheDocument()
    expect(screen.queryByText('内容运营助手')).not.toBeInTheDocument()
  })

  it('③ 重置：回到空筛选并重新取数（第 1 页）', async () => {
    render(<AgentRegistryPage />)
    await screen.findByText('内容运营助手')

    await pick('岗位', '运营（ops）')
    await userEvent.click(screen.getByRole('button', { name: /查\s*询/ }))
    vi.mocked(fetchRegistryAgents).mockClear()

    await userEvent.click(screen.getByRole('button', { name: /重\s*置/ }))
    expect(vi.mocked(fetchRegistryAgents)).toHaveBeenCalledWith({ page: 1, pageSize: REGISTRY_PAGE_SIZE })
  })

  it('④ 状态保真：无运行 / 无统计的行与指标卡都不出现 0%、0 或"成功"', async () => {
    render(<AgentRegistryPage />)
    await screen.findByText('招聘文书助手')

    // 指标卡：运行口径未接入 ⇒ 未验证
    expect(screen.getByText('最近 7 天有运行')).toBeInTheDocument()
    expect(screen.getAllByText('未验证').length).toBeGreaterThanOrEqual(2)

    const neverRun = rowOf('招聘文书助手')
    expect(within(neverRun).getByText('暂无运行记录')).toBeInTheDocument()
    expect(within(neverRun).getByText('暂无运行统计')).toBeInTheDocument()
    // "最近使用"与"使用统计"两处都按同一受控枚举显示"未验证"
    expect(within(neverRun).getAllByText('未验证').length).toBeGreaterThanOrEqual(1)

    const zeroRun = rowOf('会议纪要助手')
    expect(within(zeroRun).getByText('样本不足')).toBeInTheDocument()
    expect(within(zeroRun).getByText('暂无运行（成功率无从计算）')).toBeInTheDocument()

    const noRate = rowOf('运营选题助手（草稿）')
    expect(within(noRate).getByText('未配置')).toBeInTheDocument()
    expect(within(noRate).getByText('成功率未配置')).toBeInTheDocument()

    // 三种非就绪态行内**不得**出现任何百分比数字、"成功"结论或 0
    for (const row of [neverRun, zeroRun, noRate]) {
      expect(within(row).queryByText(/\d+(\.\d+)?%/)).not.toBeInTheDocument()
      expect(within(row).queryByText('成功')).not.toBeInTheDocument()
      expect(within(row).queryByText(/^0$/)).not.toBeInTheDocument()
    }
    // 全页不得出现"0%"（用整串匹配，避免误伤 90.0% 这类正常就绪值）
    expect(screen.queryAllByText(/^0(\.0)?%$/)).toHaveLength(0)
  })

  it('⑤ 停用走 DangerConfirm：未确认前零调用，确认后才触发，并如实告知未写入后端', async () => {
    render(<AgentRegistryPage />)
    await screen.findByText('内容运营助手')

    await userEvent.click(within(rowOf('内容运营助手')).getByRole('button', { name: /停\s*用/ }))
    expect(await screen.findByText('停用「内容运营助手」？')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认执行' })).toBeDisabled()
    expect(vi.mocked(setAgentStatus)).not.toHaveBeenCalled()

    // 输错确认词仍然不可点
    await userEvent.type(screen.getByLabelText('请输入「停用」以确认'), '停用吧')
    expect(screen.getByRole('button', { name: '确认执行' })).toBeDisabled()
    expect(vi.mocked(setAgentStatus)).not.toHaveBeenCalled()

    const input = screen.getByLabelText('请输入「停用」以确认')
    await userEvent.clear(input)
    await userEvent.type(input, '停用')
    await userEvent.click(screen.getByRole('button', { name: '确认执行' }))

    expect(vi.mocked(setAgentStatus)).toHaveBeenCalledWith({ agent_key: 'sample-ops-content', status: 'disabled' })
    expect(await screen.findByText(/已提交停用「内容运营助手」/)).toBeInTheDocument()
    expect(screen.getByText(/未写入后端/)).toBeInTheDocument()
  })

  it('⑤ 草稿行：启停按钮禁用且给出原因（不静默隐藏入口）', async () => {
    render(<AgentRegistryPage />)
    await screen.findByText('运营选题助手（草稿）')

    const draftRow = rowOf('运营选题助手（草稿）')
    const toggle = within(draftRow).getByRole('button', { name: /停\s*用/ })
    expect(toggle).toBeVisible()
    expect(toggle).toBeDisabled()
    expect(toggle).toHaveAttribute('title', '草稿尚未发布，无需启用或停用')
  })

  it('⑥ 详情：打开只读抽屉（含能力包与创建信息），没有提交按钮', async () => {
    render(<AgentRegistryPage />)
    await screen.findByText('内容运营助手')

    await userEvent.click(within(rowOf('内容运营助手')).getByRole('button', { name: /详\s*情/ }))
    expect(await screen.findByText('数字员工详情（只读）')).toBeInTheDocument()
    expect(screen.getByText('能力自动继承自岗位，不可放大')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /保\s*存/ })).not.toBeInTheDocument()
  })

  it('⑦ mode=http：已接后端口径 —— 不支持的筛选禁用给原因、草稿口径"未验证"、能力包不编造', async () => {
    setServiceMode('http')
    vi.mocked(fetchRegistryAgents).mockResolvedValue({
      sample: false,
      items: [
        {
          agent_key: 'content-ops',
          name: '内容运营助手',
          description: '负责选题与草稿。',
          role_key: 'ops',
          created_by: 'acct-0001',
          created_at: '2026-09-10T09:00:00+08:00',
          updated_at: '2026-09-19T09:00:00+08:00',
          last_run_at: null,
          template: null,
          status: 'active',
          usage: { run_count: null, success_rate: null },
        },
      ],
      total: 1,
      limit: REGISTRY_PAGE_SIZE,
      offset: 0,
    })
    vi.mocked(fetchRegistryStats).mockResolvedValue({
      sample: false,
      total: 1,
      active: 1,
      disabled: 0,
      draft: null,
      ran_last_7d: null,
    })

    render(<AgentRegistryPage />)

    expect(await screen.findByText('内容运营助手')).toBeInTheDocument()
    // 已接后端必须一眼可辨（与"示例数据"标识互斥）
    expect(screen.getByText('已接入后端数字员工目录接口')).toBeInTheDocument()
    expect(screen.queryByText('示例数据（未接后端）')).not.toBeInTheDocument()

    // 后端不支持的筛选：禁用 + 给原因（不静默忽略成"未筛选"的假结果）
    expect(screen.getByLabelText('创建者')).toBeDisabled()
    expect(screen.getByLabelText('名称')).toBeDisabled()

    // 草稿口径后端未定义 ⇒ 草稿卡"未验证"，总数卡不再写"含草稿"（也不写 0）
    expect(screen.getByText('全部')).toBeInTheDocument()
    expect(screen.queryByText('全部（含草稿）')).not.toBeInTheDocument()

    // 能力包 / 运行统计后端未提供 ⇒ 如实"未接入 / 未验证"，不编造岗位名与数字
    const row = rowOf('内容运营助手')
    expect(within(row).getByText('ops（模板未接入）')).toBeInTheDocument()
    expect(within(row).getByText('能力包未接入（后端未下发模板）')).toBeInTheDocument()
    expect(within(row).getByText('暂无运行记录')).toBeInTheDocument()
    expect(within(row).getByText('暂无运行统计')).toBeInTheDocument()
  })

  it('壳里选中「数字员工管理」即渲染本页（并给出 6 个岗位选项）', async () => {
    renderWithProviders(<AppShell />)

    await userEvent.click(screen.getByRole('menuitem', { name: /数字员工管理/ }))

    expect(screen.getByRole('heading', { level: 1, name: '数字员工管理' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: '数字员工管理' })).toBeInTheDocument()
    expect(await screen.findByText('内容运营助手')).toBeInTheDocument()

    await userEvent.click(screen.getByLabelText('岗位'))
    for (const template of ROLE_TEMPLATES) {
      expect(await screen.findByTitle(`${template.name}（${template.role_key}）`)).toBeInTheDocument()
    }
  })
})