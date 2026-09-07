import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ContentWorkbenchPage } from './ContentWorkbenchPage'

describe('ContentWorkbenchPage', () => {
  beforeEach(() => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/content-tasks') && options?.method === 'POST') return { ok: true, json: async () => ({ task_id: 'task-content-1', run_id: 'run-1', status: 'reviewing', revision: 1, topic: '本周选题', sources: [{ url: '', excerpt: '参考摘录' }], knowledge_references: [], draft: { draft_id: 'draft-1', title: '标题', summary: '摘要', body_markdown: '正文', image_suggestions: [], citations: [], template_version: 'mock-content-v1' } }) } as Response
      if (path.endsWith('/draft')) return { ok: true, json: async () => ({ task_id: 'task-content-1', run_id: 'run-1', status: 'reviewing', revision: 2, topic: '本周选题', sources: [], knowledge_references: [], draft: { draft_id: 'draft-1', title: '新标题', summary: '摘要', body_markdown: '正文', image_suggestions: [], citations: [], template_version: 'mock-content-v1' } }) } as Response
      if (path.endsWith('/confirmation')) return { ok: true, json: async () => ({ task_id: 'task-content-1', run_id: 'run-1', status: 'confirmed', revision: 2, topic: '本周选题', sources: [], knowledge_references: [], draft: { draft_id: 'draft-1', title: '新标题', summary: '摘要', body_markdown: '正文', image_suggestions: [], citations: [], template_version: 'mock-content-v1' } }) } as Response
      if (path.endsWith('/export.md')) return { ok: true, blob: async () => new Blob(['# 新标题'], { type: 'text/markdown' }) } as Response
      return { ok: false, status: 404 } as Response
    }))
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn() })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('submits material, shows reviewing draft, edits, confirms, and downloads markdown', async () => {
    const user = userEvent.setup(); render(<ContentWorkbenchPage />)
    await user.type(screen.getByLabelText('内容主题'), '本周选题')
    await user.type(screen.getByLabelText('正文摘录'), '参考摘录')
    await user.click(screen.getByRole('button', { name: '开始生成' }))
    expect(await screen.findByText('待自检')).toBeInTheDocument()
    await user.clear(screen.getByLabelText('公众号标题')); await user.type(screen.getByLabelText('公众号标题'), '新标题')
    await user.click(screen.getByRole('button', { name: '保存修改' })); await waitFor(() => expect(screen.getByDisplayValue('新标题')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: '确认并下载' })); expect(await screen.findByText('已确认')).toBeInTheDocument()
  })
})
