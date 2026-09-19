import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Form, Input } from 'antd'
import { FormDrawer } from './FormDrawer'
import type { ContentStateKind } from './ContentState'

const FOUR_STATES = [
  ['loading', '正在加载，请稍候…'],
  ['empty', '暂无内容。'],
  ['error', '加载失败，请稍后再试。'],
  ['forbidden', '你没有查看该内容的权限。'],
] as const

/** 抽屉必须有宿主组件提供 Form 实例，因此测试里包一层宿主。 */
function Harness({
  state = 'ready',
  dirty = false,
  onSubmit = () => {},
  onClose = () => {},
}: {
  state?: ContentStateKind | 'ready'
  dirty?: boolean
  onSubmit?: () => void | Promise<void>
  onClose?: () => void
}) {
  const [form] = Form.useForm()
  return (
    <FormDrawer
      open
      title="抽屉表单样品"
      form={form}
      state={state}
      dirty={dirty}
      onSubmit={onSubmit}
      onClose={onClose}
    >
      <Form.Item name="name" label="名称" rules={[{ required: true, message: '请填写名称' }]}>
        <Input />
      </Form.Item>
    </FormDrawer>
  )
}

describe('FormDrawer', () => {
  it('四态：正文改为统一四态呈现，且不给提交按钮', async () => {
    for (const [state, text] of FOUR_STATES) {
      const { unmount } = render(<Harness state={state} />)
      expect(await screen.findByText(text)).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /提\s*交/ })).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: /关\s*闭/ })).toBeInTheDocument()
      unmount()
    }
  })

  it('校验失败：留在抽屉里并显式提示，不调用提交回调', async () => {
    let submitted = 0
    render(<Harness onSubmit={() => { submitted += 1 }} />)

    await userEvent.click(await screen.findByRole('button', { name: /提\s*交/ }))

    expect(await screen.findByText('请先修正表单中的错误，再提交。')).toBeInTheDocument()
    expect(submitted).toBe(0)
    expect(screen.getByRole('button', { name: /提\s*交/ })).toBeInTheDocument()
  })

  it('填写合法：调用提交回调', async () => {
    let submitted = 0
    render(<Harness onSubmit={() => { submitted += 1 }} />)

    await userEvent.type(await screen.findByLabelText('名称'), '示例名称')
    await userEvent.click(screen.getByRole('button', { name: /提\s*交/ }))

    expect(submitted).toBe(1)
  })

  it('提交中：两个按钮都 disabled，防重复提交', async () => {
    let release: (() => void) | undefined
    const onSubmit = () =>
      new Promise<void>((resolve) => {
        release = resolve
      })

    render(<Harness onSubmit={onSubmit} />)
    await userEvent.type(await screen.findByLabelText('名称'), '示例名称')
    await userEvent.click(screen.getByRole('button', { name: /提\s*交/ }))

    expect(screen.getByRole('button', { name: /提\s*交/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /取\s*消/ })).toBeDisabled()

    await act(async () => {
      release?.()
    })
  })

  it('有未保存改动：关闭前先二次确认，确认后才真正关闭', async () => {
    let closed = 0
    render(<Harness dirty onClose={() => { closed += 1 }} />)

    await userEvent.click(await screen.findByRole('button', { name: /取\s*消/ }))
    expect(await screen.findByText('放弃未保存的改动？')).toBeInTheDocument()
    expect(closed).toBe(0)

    await userEvent.click(screen.getByRole('button', { name: '放弃并关闭' }))
    expect(closed).toBe(1)
  })

  it('没有未保存改动：取消直接关闭，不弹二次确认', async () => {
    let closed = 0
    render(<Harness onClose={() => { closed += 1 }} />)

    await userEvent.click(await screen.findByRole('button', { name: /取\s*消/ }))
    expect(closed).toBe(1)
    expect(screen.queryByText('放弃未保存的改动？')).not.toBeInTheDocument()
  })
})