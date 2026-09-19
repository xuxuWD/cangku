import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RegistryStats } from '../components/RegistryStats'
import { fetchRegistryAgents, fetchRegistryStats } from '../services/agentRegistryService'
import type { RegistryStatsSummary } from '../types'

/** 组件单测用的固定样本（明显区别于真实样例数字，避免"看起来像在断言样例"）。 */
const STATS: RegistryStatsSummary = { total: 5, active: 3, disabled: 1, draft: 1, ran_last_7d: null }
const FOUR_STATES = [
  ['loading', '正在加载，请稍候…'],
  ['empty', '暂无内容。'],
  ['error', '加载失败，请稍后再试。'],
  ['forbidden', '你没有查看该内容的权限。'],
] as const

describe('RegistryStats', () => {
  it('就绪：五张卡（全部含草稿 / 启用 / 停用 / 草稿 / 最近 7 天有运行）', () => {
    render(<RegistryStats stats={STATS} />)

    expect(screen.getByText('全部（含草稿）')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()
    expect(screen.getByText('已启用')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('已停用')).toBeInTheDocument()
    expect(screen.getByText('草稿')).toBeInTheDocument()
    expect(screen.getByText('最近 7 天有运行')).toBeInTheDocument()
  })

  it('算得清：全部（含草稿）= 已启用 + 已停用 + 草稿（期望值**从样例派生**，不硬编码数字）', async () => {
    // 逐行从样例派生期望值：样例增删行时用例自动跟随，不会出现"数字写死了所以假绿"
    const rows = (await fetchRegistryAgents({ page: 1, pageSize: 100 })).items
    const expected = {
      total: rows.length,
      active: rows.filter((row) => row.status === 'active').length,
      disabled: rows.filter((row) => row.status === 'disabled').length,
      draft: rows.filter((row) => row.status === 'draft').length,
    }

    const stats = await fetchRegistryStats()
    expect(stats).toMatchObject(expected)
    expect(stats.total).toBe(stats.active + stats.disabled + stats.draft)

    render(<RegistryStats stats={stats} />)
    const cardOf = (label: string) => screen.getByText(label).closest('.ant-pro-card') as HTMLElement
    expect(within(cardOf('全部（含草稿）')).getByText(String(expected.total))).toBeInTheDocument()
    expect(within(cardOf('已启用')).getByText(String(expected.active))).toBeInTheDocument()
    expect(within(cardOf('已停用')).getByText(String(expected.disabled))).toBeInTheDocument()
    expect(within(cardOf('草稿')).getByText(String(expected.draft))).toBeInTheDocument()
  })

  it('状态保真：运行口径无数据 ⇒ 显示"未验证"，**不显示 0 / 0% / 成功**', () => {
    render(<RegistryStats stats={STATS} />)

    expect(screen.getByText('未验证')).toBeInTheDocument()
    expect(screen.queryByText('0')).not.toBeInTheDocument()
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
    expect(screen.queryByText(/成功/)).not.toBeInTheDocument()
  })

  it('运行口径有数据时正常显示（保真分支不是"永远不可达"）', () => {
    // 取一个不与其它卡数字（5/3/1/1）碰撞的值
    render(<RegistryStats stats={{ ...STATS, ran_last_7d: 4 }} />)

    expect(screen.getByText('4')).toBeInTheDocument()
    expect(screen.queryByText('未验证')).not.toBeInTheDocument()
  })

  it('四态：loading / empty / error（可重试）/ forbidden', async () => {
    for (const [state, text] of FOUR_STATES) {
      const { unmount } = render(<RegistryStats stats={STATS} state={state} />)
      expect(screen.getByText(text)).toBeInTheDocument()
      expect(screen.queryByText('全部（含草稿）')).not.toBeInTheDocument()
      unmount()
    }

    let retried = 0
    render(<RegistryStats stats={STATS} state="error" stateDescription="指标统计加载失败，请稍后重试。" onRetry={() => { retried += 1 }} />)
    expect(screen.getByText('指标统计加载失败，请稍后重试。')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
    expect(retried).toBe(1)
  })

  it('加载态不使用失败文案（"还在转圈"不能看起来像"已出错"）', () => {
    render(<RegistryStats stats={STATS} state="loading" stateDescription="指标统计加载失败，请稍后重试。" />)

    expect(screen.getByText('正在加载，请稍候…')).toBeInTheDocument()
    expect(screen.queryByText('指标统计加载失败，请稍后重试。')).not.toBeInTheDocument()
  })
})