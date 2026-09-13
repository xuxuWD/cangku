import { decideRunApproval, getRunMetrics, getTask, listRunApprovals, listRunEvents } from './api'

type FetchMock = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

const metrics = { run_id: 'run-1', task_id: 'task-1', proposal_id: null, runtime_key: 'mock', status: 'running', step_count: 3, completed_step_count: 1, tool_calls: 2, successful_tools: 1, knowledge_hits: 0, latency_ms: 1200, started_at: '2026-09-11T02:00:00Z', finished_at: null, finish_reason: null }

function ok(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response
}

describe('runDetail api', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('fetches metrics from the run metrics endpoint', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok(metrics))
    vi.stubGlobal('fetch', fetchMock)

    await expect(getRunMetrics('run-1')).resolves.toMatchObject({ run_id: 'run-1' })
    expect(String(fetchMock.mock.calls[0][0])).toContain('/runs/run-1/metrics')
  })

  it('encodes the run id when fetching events', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok([]))
    vi.stubGlobal('fetch', fetchMock)

    await expect(listRunEvents('run/1')).resolves.toEqual([])
    expect(String(fetchMock.mock.calls[0][0])).toContain('/runs/run%2F1/events')
  })

  it('fetches the task detail', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ id: 'task-1', created_by: 'admin' }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(getTask('task-1')).resolves.toMatchObject({ id: 'task-1' })
    expect(String(fetchMock.mock.calls[0][0])).toContain('/tasks/task-1')
  })

  it('fetches the approval list', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ items: [{ approval_id: 'a-1', step_id: 's-1', tool: 'search', status: 'pending' }] }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(listRunApprovals('run-1')).resolves.toMatchObject({ items: [{ approval_id: 'a-1' }] })
    expect(String(fetchMock.mock.calls[0][0])).toContain('/runs/run-1/approvals')
  })

  it('posts an approval decision with the boolean body', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ run_id: 'run-1', approval_id: 'a-1', status: 'approved', run_status: 'running' }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(decideRunApproval('run-1', 'a/1', true)).resolves.toMatchObject({ approval_id: 'a-1', status: 'approved' })

    expect(String(fetchMock.mock.calls[0][0])).toContain('/runs/run-1/approvals/a%2F1/approval')
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(init.body).toBe(JSON.stringify({ approved: true }))
  })

  it('tolerates the optional execution field on a decision response', async () => {
    // §4.1.6-7：决议端点新增可选 `execution`；客户端解析未知字段不得报错，既有字段不变。
    const fetchMock = vi.fn<FetchMock>(async () =>
      ok({
        run_id: 'run-1',
        approval_id: 'a-1',
        status: 'approved',
        run_status: 'completed',
        execution: { outcome: 'executed', code: 201, message_id: 'msg-1' },
      })
    )
    vi.stubGlobal('fetch', fetchMock)

    const decision = await decideRunApproval('run-1', 'a-1', true)

    expect(decision).toMatchObject({ run_id: 'run-1', approval_id: 'a-1', status: 'approved', run_status: 'completed' })
    expect(decision.execution?.outcome).toBe('executed')
  })

  it('parses a decision response without execution (backend=mock)', async () => {
    const fetchMock = vi.fn<FetchMock>(async () =>
      ok({ run_id: 'run-1', approval_id: 'a-1', status: 'approved', run_status: 'running' })
    )
    vi.stubGlobal('fetch', fetchMock)

    const decision = await decideRunApproval('run-1', 'a-1', true)

    expect(decision.execution).toBeUndefined()
  })

  it('maps 401 to a Chinese permission error', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 401, json: async () => ({}) }) as Response))

    await expect(getRunMetrics('run-1')).rejects.toMatchObject({ status: 401, retryable: false, message: '当前账号没有查看该运行的权限。' })
  })

  it('prefers the backend detail for 403', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 403, json: async () => ({ detail: '发起人不能审批自己发起的运行' }) }) as Response))

    await expect(decideRunApproval('run-1', 'a-1', true)).rejects.toMatchObject({ status: 403, message: '发起人不能审批自己发起的运行' })
  })

  it('falls back to a Chinese message when 403 has no detail', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 403, json: async () => ({}) }) as Response))

    await expect(decideRunApproval('run-1', 'a-1', false)).rejects.toMatchObject({ status: 403, message: '当前账号没有执行该操作的权限。' })
  })

  it('maps 404 to a non-disclosing message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 404, json: async () => ({}) }) as Response))

    await expect(listRunApprovals('run-1')).rejects.toMatchObject({ status: 404, message: '运行不存在，或你没有权限查看。' })
  })

  it('maps 409 to an already-decided message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 409, json: async () => ({}) }) as Response))

    await expect(decideRunApproval('run-1', 'a-1', true)).rejects.toMatchObject({ status: 409, message: '该审批已决议，正在刷新最新状态。' })
  })

  it('maps a network failure to a retryable message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => { throw new Error('boom') }))

    await expect(getRunMetrics('run-1')).rejects.toMatchObject({ status: 0, retryable: true, message: '运行服务暂时不可用，请检查网络后重新尝试。' })
  })

  it('maps a 500 response to a retryable message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 503, json: async () => ({}) }) as Response))

    await expect(listRunEvents('run-1')).rejects.toMatchObject({ status: 503, retryable: true, message: '运行服务暂时不可用，请检查网络后重新尝试。' })
  })
})
