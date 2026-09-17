import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ArtifactPanel } from './ArtifactPanel'
import { useRunArtifacts } from './useRunArtifacts'

/** 宿主：把 hook 与面板串起来（与 `ConversationPage` 的用法一致）。 */
function Host({ runId }: { runId?: string }) {
  const artifacts = useRunArtifacts(runId)
  return <ArtifactPanel runId={runId} artifacts={artifacts} onOpenRunDetail={() => undefined} />
}

function json(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

function makeFetch(handler: (url: string, init?: RequestInit) => Response) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => handler(String(input), init))
}

const artifact = {
  artifact_id: 'art-1',
  virtual_path: '/workspace/report.md',
  change_kind: 'created',
  bytes: 128,
  sha256: 'sha256:abcdef0123456789',
  created_at: '2026-09-17T00:00:00Z',
  expires_at: '2026-10-17T00:00:00Z',
}

describe('ArtifactPanel（产物登记 · 只读元数据）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('无运行 ⇒ 不渲染面板（不摆假面板，也不发请求）', () => {
    const fetchMock = makeFetch(() => json({ run_id: 'x', items: [], total: 0 }))
    vi.stubGlobal('fetch', fetchMock)

    const { container } = render(<Host />)

    expect(container).toBeEmptyDOMElement()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('渲染登记条目（白名单字段），未过期条目照常展示', async () => {
    vi.stubGlobal('fetch', makeFetch((url) => {
      if (url.includes('/runs/run-1/artifacts')) return json({ run_id: 'run-1', items: [artifact], total: 1 })
      return json({}, 404)
    }))

    render(<Host runId="run-1" />)

    await waitFor(() => expect(screen.getByText('/workspace/report.md')).toBeInTheDocument())
    expect(screen.getByText('新建')).toBeInTheDocument()
    expect(screen.getByText('128 B')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '产物登记' })).toHaveTextContent('1 项')
  })

  it('空态：没有登记产物时如实告知（不是加载失败）', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ run_id: 'run-1', items: [], total: 0 })))

    render(<Host runId="run-1" />)

    await waitFor(() => expect(screen.getByText('本次运行没有登记产物')).toBeInTheDocument())
  })

  it('错误态：403 给不可重试文案（无重试按钮），5xx 给可重试按钮', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ detail: '当前岗位无权查看' }, 403)))
    const { unmount } = render(<Host runId="run-1" />)
    await waitFor(() => expect(screen.getByText('产物登记加载失败')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: '重新尝试' })).toBeNull()
    unmount()

    vi.stubGlobal('fetch', makeFetch(() => json({}, 502)))
    render(<Host runId="run-1" />)
    await waitFor(() => expect(screen.getByRole('button', { name: '重新尝试' })).toBeInTheDocument())
  })

  it('注入未知键 / 缺虚拟路径的条目一律不渲染（白名单投影）', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({
      run_id: 'run-1',
      items: [
        { ...artifact, artifact_id: 'art-2', secret: 'sk-live-abcdef', content: '文件正文不应出现' },
        { change_kind: 'created', bytes: 1 }, // 缺 virtual_path ⇒ 整条丢弃
      ],
      total: 2,
    })))

    render(<Host runId="run-1" />)

    await waitFor(() => expect(screen.getByText('/workspace/report.md')).toBeInTheDocument())
    expect(screen.queryByText(/sk-live-abcdef/)).toBeNull()
    expect(screen.queryByText(/文件正文不应出现/)).toBeNull()
    expect(screen.getByRole('region', { name: '产物登记' })).toHaveTextContent('1 项')
  })

  it('未知变更类型原样展示（不猜测、不空白）', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({
      run_id: 'run-1',
      items: [{ ...artifact, change_kind: 'renamed' }],
      total: 1,
    })))

    render(<Host runId="run-1" />)

    await waitFor(() => expect(screen.getByText('renamed')).toBeInTheDocument())
  })

  it('可重试错误：点「重新尝试」会重新请求', async () => {
    let calls = 0
    vi.stubGlobal('fetch', makeFetch(() => {
      calls += 1
      if (calls === 1) return json({}, 502)
      return json({ run_id: 'run-1', items: [artifact], total: 1 })
    }))

    render(<Host runId="run-1" />)
    const retry = await screen.findByRole('button', { name: '重新尝试' })
    await userEvent.click(retry)

    await waitFor(() => expect(screen.getByText('/workspace/report.md')).toBeInTheDocument())
    expect(calls).toBeGreaterThanOrEqual(2)
  })
})