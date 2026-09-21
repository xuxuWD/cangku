/**
 * 「编辑知识范围」抽屉用例（第 6 轮建，第 15 轮按"候选有真源"改口径）。
 *
 * 覆盖口径（见 `docs/contracts/permissions-api.md` §4 第 15 轮修订 + `permissions-fake-entry-plan.md` §9.3）：
 *  - 候选 = **知识库清单**（`name` 缺失时分落显示标识），**手输必须保留**（否则新租户死锁）；
 *  - 手输 / 已绑定但不在清单里的标识 ⇒ **黄色提醒**（提示，**不阻断保存**）；
 *  - 清单**没取到** ⇒ 如实说"没取到"（**绝不**说"没有知识库"），且**不再对手输值做判断**（不能误报）；
 *  - 前端校验**只有**：非空、去重、≤100 项（服务端仍是唯一权威）；
 *  - 写失败**就地呈现**（服务端原文 + "没有写入任何数据"），抽屉不关闭。
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ScopeDrawer } from '../components/ScopeDrawer'
import {
  CANDIDATE_ERROR_NOTE,
  CANDIDATE_LOADING_NOTE,
  CANDIDATE_NOTE,
  CANDIDATE_UNKNOWN_NOTE,
} from '../services/permissionsService'
import type { CandidateView, ScopeRow } from '../types'

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

/** 清单取到时的候选视图（`kb-b` 无名称 ⇒ 回落显示标识）。 */
function candidatesOf(over: Partial<CandidateView> = {}): CandidateView {
  return {
    state: 'ready',
    items: [
      { knowledge_base_id: 'kb-a', name: '知识库 A', origin: 'upstream' },
      { knowledge_base_id: 'kb-b', name: null, origin: 'upstream' },
      { knowledge_base_id: 'kb-c', name: '知识库 C', origin: 'upstream' },
    ],
    note: null,
    upstreamAvailable: true,
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
      candidates={candidatesOf()}
      error={null}
      onClose={onClose}
      onSubmit={onSubmit}
      {...over}
    />,
  )
  return { onSubmit, onClose }
}

describe('ScopeDrawer（编辑知识范围）', () => {
  it('回填当前绑定；候选显示清单名称（无名称回落显示标识）；写明候选来源', async () => {
    renderDrawer()

    expect(await screen.findByText('编辑知识范围：运营')).toBeInTheDocument()
    // 当前绑定回填成标签（不是空白表单）：有名称显示名称、无名称显示标识
    expect(screen.getByText('知识库 A')).toBeInTheDocument()
    expect(screen.getByText('kb-b')).toBeInTheDocument()
    expect(screen.getByText(CANDIDATE_NOTE)).toBeInTheDocument()
    expect(CANDIDATE_NOTE).toMatch(/候选来自知识库清单/)
    expect(CANDIDATE_NOTE).toMatch(/无法校验/)

    // 已绑定值都在清单里 ⇒ **不出现**"未出现在知识库清单中"的提醒（不误报）
    expect(screen.queryByText(/未出现在知识库清单中/)).not.toBeInTheDocument()
  })

  it('手动录入新标识：提交值包含手输；且给出黄色提醒但**不阻断**保存', async () => {
    const { onSubmit } = renderDrawer()

    const input = await screen.findByLabelText('知识库标识')
    // 手输的标识在**失焦**时并入表单（antd `mode="tags"` 的设计：`rc-select` 在 blur 时把输入并入值）。
    // 注意：`user-event` 不写 `event.which`，而 `rc-select` 的按键处理依赖 `which`，
    // 因此这里不能用 `{enter}` 模拟"回车成标签"（在用例里回车恒为无效键）；失焦才是可复现的真实路径。
    await userEvent.type(input, 'kb-new')
    await userEvent.tab()

    // 不在清单里 ⇒ 黄色提醒（提示，不是错误）
    expect(await screen.findByText(/未出现在知识库清单中：kb-new/)).toBeInTheDocument()
    expect(screen.getByText(CANDIDATE_UNKNOWN_NOTE)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '保存范围' }))
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledTimes(1)
    })
    expect(onSubmit.mock.calls[0][0]).toEqual(['kb-a', 'kb-b', 'kb-new'])
  })

  it('清单没取到（降级）：如实提示原因，且**不**对手输值给"不在清单"提醒（无从判断）', async () => {
    renderDrawer({
      candidates: candidatesOf({
        items: [{ knowledge_base_id: 'kb-a', name: null, origin: 'binding_only' }],
        upstreamAvailable: false,
        note: '未能获取知识库清单（请求超时），以下为本租户已绑定过的标识；可直接输入标识。',
      }),
    })

    expect(await screen.findByText(/未能获取知识库清单（请求超时）/)).toBeInTheDocument()
    // kb-b 不在候选里，但清单没取到 ⇒ 不能断言它"不存在"（不能误报）
    expect(screen.queryByText(/未出现在知识库清单中/)).not.toBeInTheDocument()
    expect(screen.queryByText(CANDIDATE_NOTE)).not.toBeInTheDocument()
  })

  it('清单请求失败：说"没取到"，**不说"没有知识库"**', async () => {
    renderDrawer({ candidates: candidatesOf({ state: 'error', items: [], upstreamAvailable: false }) })

    expect(await screen.findByText(CANDIDATE_ERROR_NOTE)).toBeInTheDocument()
    expect(screen.queryByText(/没有知识库/)).not.toBeInTheDocument()
    // 手输仍然可用（不因取不到而挡人）
    expect(screen.getByLabelText('知识库标识')).toBeInTheDocument()
  })

  it('清单加载中：给出加载说明', async () => {
    renderDrawer({ candidates: candidatesOf({ state: 'loading', items: [], upstreamAvailable: false }) })

    expect(await screen.findByText(CANDIDATE_LOADING_NOTE)).toBeInTheDocument()
  })

  it('提交前去重 + 去空白（同一个标识不会写两次）', async () => {
    const { onSubmit } = renderDrawer()

    const input = await screen.findByLabelText('知识库标识')
    await userEvent.type(input, '  kb-a  ')
    await userEvent.tab()
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