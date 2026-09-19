import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DangerConfirm } from './DangerConfirm'
import type { ContentStateKind } from './ContentState'

const FOUR_STATES = [
  ['loading', '正在加载，请稍候…'],
  ['empty', '暂无内容。'],
  ['error', '加载失败，请稍后再试。'],
  ['forbidden', '你没有查看该内容的权限。'],
] as const

describe('DangerConfirm', () => {
  it('未输入确认词：确认按钮 disabled（不能误删）', async () => {
    render(
      <DangerConfirm
        open
        title="删除该数字员工？"
        description="删除后不可恢复。"
        confirmWord="删除"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    )
    expect(await screen.findByText('删除该数字员工？')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认执行' })).toBeDisabled()
  })

  it('输入错误的确认词仍 disabled；输入正确才可点，并能触发回调', async () => {
    let confirmed = 0
    render(
      <DangerConfirm
        open
        title="删除该数字员工？"
        description="删除后不可恢复。"
        confirmWord="删除"
        onConfirm={() => { confirmed += 1 }}
        onCancel={() => {}}
      />,
    )

    const input = await screen.findByLabelText('请输入「删除」以确认')
    await userEvent.type(input, '删除吧')
    expect(screen.getByRole('button', { name: '确认执行' })).toBeDisabled()

    await userEvent.clear(input)
    await userEvent.type(input, '删除')
    const confirm = screen.getByRole('button', { name: '确认执行' })
    expect(confirm).toBeEnabled()
    await userEvent.click(confirm)
    expect(confirmed).toBe(1)
  })

  it('勾选声明模式：未勾选 disabled，勾选后可点', async () => {
    render(
      <DangerConfirm
        open
        title="导出全部数据？"
        description="导出内容包含客户信息。"
        acknowledgeText="我确认已了解导出风险"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    )

    expect(screen.getByRole('button', { name: '确认执行' })).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox'))
    expect(screen.getByRole('button', { name: '确认执行' })).toBeEnabled()
  })

  it('两种二次确认都没配置：安全默认不可执行，并给出说明', async () => {
    render(
      <DangerConfirm open title="变更权限？" description="将提升为管理员。" onConfirm={() => {}} onCancel={() => {}} />,
    )
    expect(await screen.findByText('未配置二次确认方式，出于安全考虑该操作不可执行。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认执行' })).toBeDisabled()
  })

  it('四态：正文改为统一四态呈现，且确认按钮一律 disabled', async () => {
    for (const [state, text] of FOUR_STATES) {
      const { unmount } = render(
        <DangerConfirm
          open
          title="删除该数字员工？"
          description="删除后不可恢复。"
          confirmWord="删除"
          state={state as ContentStateKind}
          onConfirm={() => {}}
          onCancel={() => {}}
        />,
      )
      expect(await screen.findByText(text)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: '确认执行' })).toBeDisabled()
      unmount()
    }
  })
})