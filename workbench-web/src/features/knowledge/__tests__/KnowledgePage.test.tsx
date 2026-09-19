/**
 * 「知识库」页用例（第 7 轮）。
 *
 * 覆盖口径（见 `docs/contracts/knowledge-api.md` §3 / §4 与 `knowledge-module-plan.md` §4）：
 *  - 四块齐备（治理指标 / 文档列表 / 可检索文档 / 知识检索）+ 检索入口；
 *  - 四态齐备（加载 / 空 / 错误可重试 / 无权限），**无权限时不请求数据、不渲染编辑控件**；
 *  - 状态机驱动按钮：非法前置状态**禁用 + 给原因**（`title`），不静默隐藏；`archived` 为终态；
 *  - 写失败**就地呈现、不关闭抽屉、不假装成功**；成功只用**服务端回读值**提示；
 *  - 检索：`empty_whitelist` 与「没查到」**分开呈现**；未配置（`503`）⇒「服务未接入」。
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppShell } from '../../../app/AppShell'
import { ServiceError } from '../../../utils/serviceKit'
import { renderWithProviders, signInAs, signOutForTest } from '../../../test/renderWithProviders'
import { KnowledgePage } from '../KnowledgePage'
import {
  DOCUMENTS_EMPTY_NOTE,
  ELIGIBLE_EMPTY_NOTE,
  KnowledgeError,
  SEARCH_EMPTY_WHITELIST_NOTE,
  SEARCH_NOT_CONFIGURED_NOTE,
  SEARCH_NO_HITS_NOTE,
  fetchDocuments,
  fetchEligible,
  fetchMetrics,
  registerDocument,
  publishDocument,
  archiveDocument,
  reviewDocument,
  searchKnowledge,
  setServiceMode,
} from '../services/knowledgeService'
import type { DocumentPage, EligiblePage, KnowledgeDoc, MetricsPage } from '../types'

const REAL = await vi.importActual<typeof import('../services/knowledgeService')>(
  '../services/knowledgeService',
)

vi.mock('../services/knowledgeService', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/knowledgeService')>()
  return {
    ...actual,
    fetchDocuments: vi.fn(actual.fetchDocuments),
    fetchMetrics: vi.fn(actual.fetchMetrics),
    fetchEligible: vi.fn(actual.fetchEligible),
    registerDocument: vi.fn(actual.registerDocument),
    publishDocument: vi.fn(actual.publishDocument),
    archiveDocument: vi.fn(actual.archiveDocument),
    reviewDocument: vi.fn(actual.reviewDocument),
    runReviewScan: vi.fn(actual.runReviewScan),
    searchKnowledge: vi.fn(actual.searchKnowledge),
  }
})

function doc(over: Partial<KnowledgeDoc> = {}): KnowledgeDoc {
  return {
    document_id: 'doc-draft',
    title: '员工手册',
    owner_id: 'acct-0001',
    status: 'draft',
    version: '1',
    source_key: 'manual',
    last_reviewed_at: null,
    review_due_at: null,
    registered_by: 'acct-0001',
    created_at: '2026-09-19T10:00:00Z',
    updated_at: '2026-09-19T10:00:00Z',
    ...over,
  }
}

const DOCS: DocumentPage = {
  sample: true,
  total: 4,
  limit: 50,
  offset: 0,
  items: [
    doc({ document_id: 'doc-draft', title: '员工手册', status: 'draft' }),
    doc({
      document_id: 'doc-published',
      title: '运营手册',
      status: 'published',
      review_due_at: '2026-10-19T14:21:29Z',
    }),
    doc({ document_id: 'doc-review', title: '合规检查表', status: 'needs_review' }),
    doc({ document_id: 'doc-archived', title: '旧版制度', status: 'archived' }),
  ],
}

const METRICS: MetricsPage = {
  sample: true,
  metrics: { published: 1, needs_review: 1, archived: 1, total: 4, freshness_ratio: 0.25 },
}

const ELIGIBLE: EligiblePage = {
  sample: true,
  total: 1,
  items: [doc({ document_id: 'doc-published', title: '合规指南', status: 'published', review_due_at: '2026-10-19T14:21:29Z' })],
}

function rowOf(title: string): HTMLElement {
  return screen.getByText(title).closest('tr') as HTMLElement
}

function asAdmin(): void {
  signInAs('super_admin')
}

function readyReads(): void {
  vi.mocked(fetchDocuments).mockResolvedValue(DOCS)
  vi.mocked(fetchMetrics).mockResolvedValue(METRICS)
  vi.mocked(fetchEligible).mockResolvedValue(ELIGIBLE)
}

describe('KnowledgePage（知识库）', () => {
  beforeEach(() => {
    asAdmin()
    vi.mocked(fetchDocuments).mockImplementation(REAL.fetchDocuments)
    vi.mocked(fetchMetrics).mockImplementation(REAL.fetchMetrics)
    vi.mocked(fetchEligible).mockImplementation(REAL.fetchEligible)
    vi.mocked(registerDocument).mockImplementation(REAL.registerDocument)
    vi.mocked(publishDocument).mockImplementation(REAL.publishDocument)
    vi.mocked(archiveDocument).mockImplementation(REAL.archiveDocument)
    vi.mocked(reviewDocument).mockImplementation(REAL.reviewDocument)
  })

  afterEach(() => {
    setServiceMode('mock')
    signOutForTest()
  })

  it('① 四块齐备：治理指标 / 文档列表 / 可检索文档 / 知识检索', async () => {
    readyReads()

    renderWithProviders(<KnowledgePage />)

    expect(await screen.findByRole('heading', { level: 3, name: '治理指标' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: '文档列表' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: '可检索文档' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: '知识检索' })).toBeInTheDocument()

    // 指标：四数 + 新鲜度比率（分母为全部已登记文档，如实呈现）
    expect(screen.getByText('已登记总数')).toBeInTheDocument()
    expect(screen.getByText('新鲜度比率')).toBeInTheDocument()
    expect(screen.getByText('25.0%')).toBeInTheDocument()
    expect(screen.getByText(/分母为全部已登记文档/)).toBeInTheDocument()

    // 文档列表：四行状态标签各自如实
    expect(await screen.findByText('员工手册')).toBeInTheDocument()
    expect(within(rowOf('员工手册')).getByText('草稿')).toBeInTheDocument()
    expect(within(rowOf('运营手册')).getByText('已发布')).toBeInTheDocument()
    expect(within(rowOf('合规检查表')).getByText('待复核')).toBeInTheDocument()
    expect(within(rowOf('旧版制度')).getByText('已归档')).toBeInTheDocument()
    // 复核到期：有值照实显示，无值写"未设置"（不编造）
    expect(within(rowOf('运营手册')).getByText('2026-10-19 14:21')).toBeInTheDocument()
    expect(within(rowOf('员工手册')).getByText('未设置')).toBeInTheDocument()

    // 可检索文档：只列已发布
    expect(screen.getByText('当前可被检索的文档（已发布且未过复核期）')).toBeInTheDocument()
  })

  it('② 状态机驱动按钮：非法前置状态禁用 + 给原因（不静默隐藏）', async () => {
    readyReads()

    renderWithProviders(<KnowledgePage />)
    await screen.findByText('员工手册')

    // 草稿：可发布、可归档；复核不可用（并给出原因）
    expect(within(rowOf('员工手册')).getByRole('button', { name: /发\s*布/ })).toBeEnabled()
    expect(within(rowOf('员工手册')).getByRole('button', { name: /归\s*档/ })).toBeEnabled()
    expect(within(rowOf('员工手册')).getByRole('button', { name: '复核通过' })).toBeDisabled()
    expect(within(rowOf('员工手册')).getByRole('button', { name: '复核通过' })).toHaveAttribute(
      'title',
      expect.stringContaining('复核'),
    )

    // 已发布：不能发布（给原因）、可归档、复核不可用
    expect(within(rowOf('运营手册')).getByRole('button', { name: /发\s*布/ })).toBeDisabled()
    expect(within(rowOf('运营手册')).getByRole('button', { name: /发\s*布/ })).toHaveAttribute(
      'title',
      expect.stringContaining('草稿'),
    )
    expect(within(rowOf('运营手册')).getByRole('button', { name: /归\s*档/ })).toBeEnabled()

    // 待复核：可复核（通过 / 退回）、不可发布
    expect(within(rowOf('合规检查表')).getByRole('button', { name: '复核通过' })).toBeEnabled()
    expect(within(rowOf('合规检查表')).getByRole('button', { name: '复核退回' })).toBeEnabled()
    expect(within(rowOf('合规检查表')).getByRole('button', { name: /发\s*布/ })).toBeDisabled()

    // 已归档（终态）：三个动作全部禁用，且原因说明终态
    expect(within(rowOf('旧版制度')).getByRole('button', { name: /归\s*档/ })).toBeDisabled()
    expect(within(rowOf('旧版制度')).getByRole('button', { name: /归\s*档/ })).toHaveAttribute(
      'title',
      expect.stringContaining('终态'),
    )
    expect(within(rowOf('旧版制度')).getByRole('button', { name: /发\s*布/ })).toBeDisabled()
  })

  it('② 加载态：骨架屏，且不出现空态 / 失败文案', () => {
    vi.mocked(fetchDocuments).mockImplementation(() => new Promise(() => {}))
    vi.mocked(fetchMetrics).mockImplementation(() => new Promise(() => {}))
    vi.mocked(fetchEligible).mockImplementation(() => new Promise(() => {}))

    renderWithProviders(<KnowledgePage />)

    expect(document.querySelectorAll('.ant-skeleton').length).toBeGreaterThan(0)
    expect(screen.queryByText(DOCUMENTS_EMPTY_NOTE)).not.toBeInTheDocument()
    expect(screen.queryByText(ELIGIBLE_EMPTY_NOTE)).not.toBeInTheDocument()
  })

  it('③ 空 / 错误（可重试）/ 无权限各自可辨，且空态解释"为什么空"', async () => {
    // 空：文案说明"登记并发布后才可被检索"，不写"0 条"
    vi.mocked(fetchDocuments).mockResolvedValue({ sample: true, items: [], total: 0, limit: 50, offset: 0 })
    vi.mocked(fetchMetrics).mockResolvedValue({
      sample: true,
      metrics: { published: 0, needs_review: 0, archived: 0, total: 0, freshness_ratio: 0 },
    })
    vi.mocked(fetchEligible).mockResolvedValue({ sample: true, items: [], total: 0 })

    const { unmount } = renderWithProviders(<KnowledgePage />)

    expect(await screen.findByText(DOCUMENTS_EMPTY_NOTE)).toBeInTheDocument()
    expect(screen.getByText(ELIGIBLE_EMPTY_NOTE)).toBeInTheDocument()
    expect(screen.queryByText(/0 条/)).not.toBeInTheDocument()
    unmount()

    // 错误：可重试；点重试重新取数（只让第一次取数失败）
    readyReads()
    vi.mocked(fetchDocuments).mockRejectedValueOnce(new ServiceError('加载失败', 'failed'))

    renderWithProviders(<KnowledgePage />)

    expect(await screen.findByText('文档列表加载失败，请稍后重试。')).toBeInTheDocument()
    const before = vi.mocked(fetchDocuments).mock.calls.length
    await userEvent.click(screen.getAllByRole('button', { name: /重\s*试/ })[0])
    expect(await screen.findByText('员工手册')).toBeInTheDocument()
    expect(vi.mocked(fetchDocuments).mock.calls.length).toBeGreaterThan(before)
  })

  it('④ 无权限（员工）：整页无权限态，不请求数据、不渲染任何编辑控件', () => {
    signInAs('employee')

    renderWithProviders(<KnowledgePage />)

    expect(screen.getByText('无访问权限')).toBeInTheDocument()
    expect(screen.getByText(/只有超级管理员/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '登记文档' })).not.toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 3, name: '文档列表' })).not.toBeInTheDocument()
    expect(vi.mocked(fetchDocuments)).not.toHaveBeenCalled()
    expect(vi.mocked(fetchMetrics)).not.toHaveBeenCalled()
    expect(vi.mocked(fetchEligible)).not.toHaveBeenCalled()
  })

  it('⑤ 登记成功：参数逐字正确 → 用服务端回读值提示 → 关闭抽屉 → 重新取数', async () => {
    readyReads()
    vi.mocked(registerDocument).mockResolvedValue({
      doc: doc({ document_id: 'doc-new', title: '新制度', status: 'draft' }),
      written: true,
      note: '已登记知识文档。',
    })

    renderWithProviders(<KnowledgePage />)
    await screen.findByText('员工手册')

    await userEvent.click(screen.getByRole('button', { name: '登记文档' }))
    expect(await screen.findByText('登记知识文档')).toBeInTheDocument()

    const before = vi.mocked(fetchDocuments).mock.calls.length
    await userEvent.type(screen.getByLabelText('文档标识'), 'doc-new')
    await userEvent.type(screen.getByLabelText('标题'), '新制度')
    await userEvent.click(screen.getByRole('button', { name: '提交登记' }))

    await waitFor(() => {
      expect(vi.mocked(registerDocument)).toHaveBeenCalledWith({
        document_id: 'doc-new',
        title: '新制度',
        owner_id: '',
        version: '1',
        source_key: 'manual',
      })
    })
    // 提示只用服务端回读值（状态取自响应，不本地猜）
    expect(await screen.findByText(/已登记：「新制度」（当前状态：草稿）/)).toBeInTheDocument()
    // 受理后才关闭抽屉（表单内容仍挂载，故按"可见性"断言而不是按文案消失）
    await waitFor(() => {
      expect(document.querySelector('.ant-drawer-open')).toBeNull()
    })
    await waitFor(() => {
      expect(vi.mocked(fetchDocuments).mock.calls.length).toBeGreaterThan(before)
    })
  })

  it('⑥ 登记失败（422）：就地呈现，抽屉不关闭，也不显示"已登记"', async () => {
    readyReads()
    vi.mocked(registerDocument).mockRejectedValue(
      new KnowledgeError('请求参数不合法，已拒绝。', 'invalid'),
    )

    renderWithProviders(<KnowledgePage />)
    await screen.findByText('员工手册')

    await userEvent.click(screen.getByRole('button', { name: '登记文档' }))
    await screen.findByText('登记知识文档')
    await userEvent.type(screen.getByLabelText('文档标识'), 'doc-new')
    await userEvent.click(screen.getByRole('button', { name: '提交登记' }))

    expect(await screen.findByText(/未能登记：请求参数不合法，已拒绝。/)).toBeInTheDocument()
    expect(screen.getAllByText(/没有写入任何数据/).length).toBeGreaterThanOrEqual(1)
    expect(screen.queryByText(/已登记：/)).not.toBeInTheDocument()
    expect(screen.getByText('登记知识文档')).toBeInTheDocument()
  })

  it('⑦ 发布 / 归档 / 复核：成功后按服务端回读状态提示，并重新取数', async () => {
    readyReads()
    vi.mocked(publishDocument).mockResolvedValue({
      doc: doc({ document_id: 'doc-draft', title: '员工手册', status: 'published' }),
      written: true,
      note: '已发布知识文档。',
    })
    vi.mocked(reviewDocument).mockResolvedValue({
      doc: doc({ document_id: 'doc-review', title: '合规检查表', status: 'archived' }),
      written: true,
      note: '已记录复核结果。',
    })

    renderWithProviders(<KnowledgePage />)
    await screen.findByText('员工手册')

    const before = vi.mocked(fetchDocuments).mock.calls.length
    await userEvent.click(within(rowOf('员工手册')).getByRole('button', { name: /发\s*布/ }))
    expect(await screen.findByText(/已发布：「员工手册」（当前状态：已发布）/)).toBeInTheDocument()
    await waitFor(() => {
      expect(vi.mocked(fetchDocuments).mock.calls.length).toBeGreaterThan(before)
    })

    await userEvent.click(within(rowOf('合规检查表')).getByRole('button', { name: '复核退回' }))
    expect(await screen.findByText(/复核退回：「合规检查表」（当前状态：已归档）/)).toBeInTheDocument()
    await waitFor(() => {
      expect(vi.mocked(reviewDocument)).toHaveBeenCalledWith('doc-review', false)
    })
  })

  it('⑦ 发布 409（状态冲突）：保留服务端原文就地呈现，不假装成功', async () => {
    readyReads()
    vi.mocked(publishDocument).mockRejectedValue(
      new KnowledgeError('当前状态不能发布（仅 draft 可发布）', 'conflict'),
    )

    renderWithProviders(<KnowledgePage />)
    await screen.findByText('员工手册')

    await userEvent.click(within(rowOf('员工手册')).getByRole('button', { name: /发\s*布/ }))

    expect(
      await screen.findByText(/未能完成操作：当前状态不能发布（仅 draft 可发布）/),
    ).toBeInTheDocument()
    expect(screen.getAllByText(/没有写入任何数据/).length).toBeGreaterThanOrEqual(1)
    expect(screen.queryByText(/已发布：/)).not.toBeInTheDocument()
  })

  it('⑧ 检索：empty_whitelist 与「没查到」分开呈现，后者不给"先发布"指引', async () => {
    readyReads()
    vi.mocked(searchKnowledge).mockResolvedValue({ items: [], truncated: false, reason: 'empty_whitelist' })

    renderWithProviders(<KnowledgePage />)
    await screen.findByText('员工手册')

    await userEvent.type(screen.getByLabelText('身份标识'), 'evidence-ops')
    await userEvent.type(screen.getByLabelText('检索关键词'), '合规')
    await userEvent.click(screen.getByRole('button', { name: /检\s*索/ }))

    expect(await screen.findByText(SEARCH_EMPTY_WHITELIST_NOTE)).toBeInTheDocument()
    expect(screen.queryByText(SEARCH_NO_HITS_NOTE)).not.toBeInTheDocument()

    // 换成"白名单非空但无命中"：文案必须不同，且不再提示"先登记并发布"
    vi.mocked(searchKnowledge).mockResolvedValue({ items: [], truncated: false, reason: 'no_hits' })
    await userEvent.click(screen.getByRole('button', { name: /检\s*索/ }))

    expect(await screen.findByText(SEARCH_NO_HITS_NOTE)).toBeInTheDocument()
    expect(screen.queryByText(SEARCH_EMPTY_WHITELIST_NOTE)).not.toBeInTheDocument()
    // 两种空结果文案必须不同：无命中时**不给**"先登记并发布"的指引
    expect(SEARCH_NO_HITS_NOTE).not.toMatch(/请先/)
    expect(SEARCH_NO_HITS_NOTE).not.toBe(SEARCH_EMPTY_WHITELIST_NOTE)
  })

  it('⑨ 检索未配置（503）：呈现"服务未接入"，不是空结果', async () => {
    readyReads()
    vi.mocked(searchKnowledge).mockRejectedValue(
      new KnowledgeError('知识检索服务未启用', 'not_configured'),
    )

    renderWithProviders(<KnowledgePage />)
    await screen.findByText('员工手册')

    await userEvent.type(screen.getByLabelText('身份标识'), 'evidence-ops')
    await userEvent.type(screen.getByLabelText('检索关键词'), '合规')
    await userEvent.click(screen.getByRole('button', { name: /检\s*索/ }))

    expect(await screen.findByText(SEARCH_NOT_CONFIGURED_NOTE)).toBeInTheDocument()
    expect(screen.queryByText(SEARCH_EMPTY_WHITELIST_NOTE)).not.toBeInTheDocument()
    expect(screen.queryByText(/没有匹配/)).not.toBeInTheDocument()
  })

  it('⑩ 壳里选中「知识库」即渲染真实页（占位页已被替换）', async () => {
    readyReads()

    renderWithProviders(<AppShell />)

    await userEvent.click(screen.getByRole('menuitem', { name: /知识库/ }))

    expect(screen.getByRole('heading', { level: 1, name: '知识库' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 2, name: '知识库' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 3, name: '文档列表' })).toBeInTheDocument()
    expect(screen.queryByText('「知识库」尚未接入（第 4 轮实现）。')).not.toBeInTheDocument()
  })
})