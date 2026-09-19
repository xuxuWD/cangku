/**
 * 「编辑知识范围」抽屉用例（第 6 轮）。
 *
 * 覆盖口径（见 `docs/contracts/permissions-api.md` §4）：
 *  - 候选 = 现有绑定的并集，**新库标识需手动录入**（界面必须写明这一点）；
 *  - 前端校验**只有**：非空、去重、≤100 项（服务端仍是唯一权威）；
 *  - 写失败**就地呈现**（服务端原文 + "没有写入任何数据"），抽屉不关闭。
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ScopeDrawer } from '../components/ScopeDrawer'
import { CANDIDATE_NOTE } from '../services/permissionsService'
import type { ScopeRow } from '../types'

function targetOf(over: Partial<ScopeRow> = {}): ScopeRow {
  return {
    binding_type: 'role',
    binding_key: 'ops',
    name: '运营',
    status: 'active',
    knowledge_base_ids: ['kb-a', 'kb-b'],
    ...over,
  }
}

function renderDrawer(over: Partial<Parameters<typeof ScopeDrawer>[0]> = {}) {
  const onSubmit = vi.fn()
  const onClose = vi.fn()
  render(
    <ScopeDrawer
      open
      target={targetOf()}
      candidates={['kb-a', 'kb-b', 'kb-c']}
      error={null}
      onClose={onClose}
      onSubmit={onSubmit}
      {...over}
    />,
  )
  return { onSubmit, onClose }
}

describe('ScopeDrawer（编辑知识范围）', () => {
  it('回填当前绑定；候选来自传入的现有绑定；界面写明"新库标识需手动录入"', async () => {
    renderDrawer()

    expect(await screen.findByText('编辑知识范围：运营')).toBeInTheDocument()
    // 当前绑定回填成标签（不是空白表单）
    expect(screen.getByText('kb-a')).toBeInTheDocument()
    expect(screen.getByText('kb-b')).toBeInTheDocument()
    expect(screen.getByText(CANDIDATE_NOTE)).toBeInTheDocument()
    expect(CANDIDATE_NOTE).toMatch(/候选来自现有绑定/)
    expect(CANDIDATE_NOTE).toMatch(/手动录入/)

    // 候选清单确实来自传入的并集（下拉里能选到未绑定的 kb-c）
    await userEvent.click(screen.getByLabelText('知识库标识'))
    expect(await screen.findByTitle('kb-c')).toBeInTheDocument()
  })

  it('手动录入新标识：提交值包含手工输入的标识', async () => {
    const { onSubmit } = renderDrawer()

    const input = await screen.findByLabelText('知识库标识')
    await userEvent.type(input, 'kb-new{enter}')
    await userEvent.click(screen.getByRole('button', { name: '保存范围' }))

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledTimes(1)
    })
    expect(onSubmit.mock.calls[0][0]).toEqual(['kb-a', 'kb-b', 'kb-new'])
  })

  it('提交前去重 + 去空白（同一个标识不会写两次）', async () => {
    const { onSubmit } = renderDrawer()

    const input = await screen.findByLabelText('知识库标识')
    await userEvent.type(input, '  kb-a  {enter}')
    await userEvent.click(screen.getByRole('button', { name: '保存范围' }))

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledTimes(1)
    })
    expect(onSubmit.mock.calls[0][0]).toEqual(['kb-a', 'kb-b'])
  })

  it('超过 100 项：被前端拦下（服务端 max_length=100），不发出提交', async () => {
    const many = Array.from({ length: 101 }, (_, index) => `kb-${index}`)
    const { onSubmit } = renderDrawer({ target: targetOf({ knowledge_base_ids: many }) })

    await userEvent.click(await screen.findByRole('button', { name: '保存范围' }))

    expect(await screen.findByText(/最多 100 个知识库标识/)).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('写失败（409 未纳管）：就地呈现服务端原文 + "没有写入任何数据"，抽屉不关闭', async () => {
    renderDrawer({
      error: {
        message: '该标识尚未纳入目录，请先在「数字员工设置」中纳管',
        hint: '本次没有写入任何数据；该标识尚未纳入目录，请先在「数字员工设置」中纳管后重试。',
      },
    })

    expect(
      await screen.findByText('未能保存：该标识尚未纳入目录，请先在「数字员工设置」中纳管'),
    ).toBeInTheDocument()
    expect(screen.getAllByText(/没有写入任何数据/).length).toBeGreaterThanOrEqual(1)
    // 仍在编辑态：提交按钮还在，抽屉没被关掉
    expect(screen.getByRole('button', { name: '保存范围' })).toBeInTheDocument()
  })
})