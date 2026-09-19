import { cancelRun, decideRunAcceptance, decideRunApproval, getRunMetrics, getTask, listRunAcceptanceDecisions, listRunApprovals, listRunEvents, newAcceptanceIdempotencyKey, pauseRun, resumeRun } from './api'

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

  // ---- S4 干预（暂停 / 恢复 / 取消） ----

  it('posts a pause with the required reason', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ run_id: 'run-1', status: 'paused' }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(pauseRun('run-1', '在工作台上手动暂停')).resolves.toEqual({ run_id: 'run-1', status: 'paused' })

    expect(String(fetchMock.mock.calls[0][0])).toContain('/runs/run-1/pause')
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ reason: '在工作台上手动暂停' })
  })

  it('posts a resume without a body and encodes the run id', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ run_id: 'run/1', status: 'running' }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(resumeRun('run/1')).resolves.toMatchObject({ status: 'running' })

    expect(String(fetchMock.mock.calls[0][0])).toContain('/runs/run%2F1/resume')
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(init.body).toBeUndefined()
  })

  it('posts a cancel with the required reason', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ run_id: 'run-1', status: 'cancelled' }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(cancelRun('run-1', '在工作台上手动取消')).resolves.toMatchObject({ status: 'cancelled' })

    expect(String(fetchMock.mock.calls[0][0])).toContain('/runs/run-1/cancel')
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({ reason: '在工作台上手动取消' })
  })

  it('does not disclose whether the run exists when an action is denied', async () => {
    // 越权与不存在都由服务端收敛为 404；前端文案不得暗示「运行存在但你没权限」。
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 404, json: async () => ({ detail: '运行不存在' }) }) as Response))

    await expect(cancelRun('run-1', '在工作台上手动取消')).rejects.toMatchObject({ status: 404, message: '运行不存在，或你没有权限操作。', retryable: false })
  })

  it('prefers the backend detail when the action is refused by state', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 409, json: async () => ({ detail: '运行已结束，无法决议' }) }) as Response))

    await expect(pauseRun('run-1', '在工作台上手动暂停')).rejects.toMatchObject({ status: 409, message: '运行已结束，无法决议', retryable: false })
  })

  it('falls back to a Chinese message when a 409 has no detail', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 409, json: async () => ({}) }) as Response))

    await expect(resumeRun('run-1')).rejects.toMatchObject({ status: 409, message: '该运行当前的状态不允许此操作，正在刷新最新状态。' })
  })

  it('maps a network failure on an action to a retryable message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => { throw new Error('offline') }))

    await expect(resumeRun('run-1')).rejects.toMatchObject({ status: 0, retryable: true })
  })

  // ---- S2 人工验收决议 ----

  it('lists the acceptance decisions from the newest first endpoint', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ run_id: 'run-1', items: [{ decision_id: 'd-1', decision: 'rejected', reason: '重做', decided_by: 'u-1', decided_at: '2026-09-18T02:00:00Z', structural_verdict: 'met' }], latest: { decision_id: 'd-1' } }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(listRunAcceptanceDecisions('run/1')).resolves.toMatchObject({ items: [{ decision_id: 'd-1' }] })
    expect(String(fetchMock.mock.calls[0][0])).toContain('/runs/run%2F1/acceptance/decisions')
    expect((fetchMock.mock.calls[0][1] as RequestInit | undefined)?.method).toBeUndefined()
  })

  it('posts an acceptance decision with the reason and idempotency key', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ run_id: 'run-1', decision_id: 'd-2', decision: 'rejected', reason: '结果不符', decided_by: 'u-1', decided_at: '2026-09-18T02:00:00Z', structural_verdict: 'met', created: true }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(decideRunAcceptance('run-1', { decision: 'rejected', reason: '结果不符', idempotencyKey: 'k-9' })).resolves.toMatchObject({ decision: 'rejected', created: true })

    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ decision: 'rejected', reason: '结果不符', idempotency_key: 'k-9' })
  })

  it('sends an empty reason when confirming completion', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ run_id: 'run-1', decision_id: 'd-3', decision: 'confirmed', reason: '', decided_by: 'u-1', decided_at: '2026-09-18T02:00:00Z', structural_verdict: 'met', created: true }))
    vi.stubGlobal('fetch', fetchMock)

    await decideRunAcceptance('run-1', { decision: 'confirmed', idempotencyKey: 'k-10' })

    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({ decision: 'confirmed', reason: '', idempotency_key: 'k-10' })
  })

  it('prefers the backend reason when a decision is refused as invalid input', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 422, json: async () => ({ detail: '打回重做必须写明原因' }) }) as Response))

    await expect(decideRunAcceptance('run-1', { decision: 'rejected', reason: ' ', idempotencyKey: 'k-11' })).rejects.toMatchObject({ status: 422, message: '打回重做必须写明原因', retryable: false })
  })

  it('maps a refusal by run state to the backend detail', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 409, json: async () => ({ detail: '运行尚未结束，暂不能验收' }) }) as Response))

    await expect(decideRunAcceptance('run-1', { decision: 'confirmed', idempotencyKey: 'k-12' })).rejects.toMatchObject({ status: 409, message: '运行尚未结束，暂不能验收' })
  })

  it('generates a fresh idempotency key per decision attempt', () => {
    const first = newAcceptanceIdempotencyKey()
    const second = newAcceptanceIdempotencyKey()
    expect(first).not.toBe(second)
    expect(first.startsWith('acceptance-')).toBe(true)
  })
})
