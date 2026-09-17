import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConversationPage } from './ConversationPage'

const json = (body: unknown, status = 200): Response =>
  ({ ok: status < 400, status, json: async () => body }) as Response

function sseResponse(chunks: string[], headers: Record<string, string> = {}): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
  return { ok: true, status: 200, body, headers: new Headers(headers) } as unknown as Response
}

const sseFrame = (seq: number, kind: string, isTerminal = false) =>
  `id: ${seq}\nevent: ${kind}\ndata: ${JSON.stringify({ seq, kind, payload: { status: 'ok', tool_key: 'cmd.run' }, is_terminal: isTerminal })}\n\n`

const conversation = { conversation_id: 'conv-1', agent_key: 'agent-ops', title: '整理客户反馈', status: 'active', created_at: '2026-09-11T02:00:00Z', updated_at: '2026-09-11T02:00:00Z' }

const metrics = {
  run_id: 'run-9', task_id: 'task-1', proposal_id: null, runtime_key: 'dsh', status: 'completed',
  step_count: 1, completed_step_count: 1, tool_calls: 1, successful_tools: 1, knowledge_hits: 0,
  latency_ms: 1200, started_at: '2026-09-17T02:00:00Z', finished_at: '2026-09-17T02:00:01Z', finish_reason: 'run_completed',
}

const task = {
  id: 'task-1', tenant_id: 'demo-tenant', project_id: null, created_by: 'someone-else', employee_key: 'agent-ops',
  title: '工具调用', risk_level: 'low', budget: 0, idempotency_key: 'k-1', status: 'completed', audit_count: 1,
}

interface Call { url: string; method: string; body: string; headers: Record<string, string> }

function makeFetch(options: { approvals?: unknown[]; produceRun?: boolean; frames?: string[]; streamHeaders?: Record<string, string> } = {}) {
  const calls: Call[] = []
  const approvals = options.approvals ?? []
  const produceRun = options.produceRun !== false
  const frames = options.frames ?? [sseFrame(1, 'tool.call'), sseFrame(2, 'run.completed', true)]
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    calls.push({ url, method, body: typeof init?.body === 'string' ? init.body : '', headers: (init?.headers ?? {}) as Record<string, string> })

    if (url.includes('/inbox?')) return json({ items: [], unread_count: 0 })
    if (url.includes('/messages:stream')) {
      // `produceRun: false` 模拟「后端未装配真实执行」：回落桩路径，**没有运行**（无 X-Stream-Run-Id）
      return {
        ok: true,
        status: 201,
        headers: new Headers(produceRun ? { 'X-Stream-Run-Id': 'run-9' } : {}),
        json: async () =>
          produceRun
            ? { message_id: 'msg-2', conversation_id: 'conv-1', stub: false, run_id: 'run-9' }
            : { message_id: 'msg-2', conversation_id: 'conv-1', stub: true, run_id: null },
      } as unknown as Response
    }
    if (url.includes('/messages')) {
      return json({ message_id: 'msg-2', conversation_id: 'conv-1', stub: true, reply: { message_id: 'msg-3', conversation_id: 'conv-1', role: 'assistant', content: '（P1 桩回复）已收到你的消息。', stub: true, tool_name: null, tool_call_id: null, created_at: null } }, 201)
    }
    if (url.includes('/conversations/conv-1/stream')) return sseResponse(frames, options.streamHeaders)
    if (url.includes('/runs/run-9/metrics')) return json(metrics)
    if (url.includes('/runs/run-9/approvals/') && method === 'POST') return json({ run_id: 'run-9', approval_id: 'ap-1', status: 'approved', run_status: 'completed' })
    if (url.includes('/runs/run-9/approvals')) return json({ items: approvals })
    if (url.includes('/tasks/')) return json(task)
    if (url.includes('/conversations/')) {
      return json({
        ...conversation,
        messages: [{ message_id: 'msg-1', conversation_id: 'conv-1', role: 'user', content: '整理一下客户反馈', stub: false, tool_name: null, tool_call_id: null, created_at: null }],
        messages_total: 1, messages_limit: 50, messages_offset: 0,
      })
    }
    return json({ items: [conversation], total: 1, limit: 20, offset: 0 })
  })
  return { fetchMock, calls }
}

const invocation = JSON.stringify({ tool_key: 'cmd.run', params: { executable: 'echo', args: ['hi'] } })

describe('ConversationPage（P2c-1 实时流路径与舞台）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
  })

  it('结构化调用走 messages:stream（带幂等键），响应头里的 run 驱动舞台概览与审批', async () => {
    const { fetchMock, calls } = makeFetch({ approvals: [{ approval_id: 'ap-1', step_id: 's-1', tool: 'cmd.run', status: 'pending' }] })
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByText('整理一下客户反馈')

    fireEvent.change(screen.getByLabelText('消息内容'), { target: { value: invocation } })
    await userEvent.click(screen.getByRole('button', { name: '发送消息' }))

    const posted = await waitFor(() => {
      const found = calls.find((call) => call.url.includes('/messages:stream'))
      expect(found).toBeDefined()
      return found as Call
    })
    expect(posted.headers['Idempotency-Key']).toBeTruthy()
    expect(JSON.parse(posted.body)).toEqual({ content: invocation })

    // 舞台：运行概览（既有 runs 接口）+ 审批（既有 run 审批接口）——全部来自同一条 run
    expect(await screen.findByText('步骤完成度')).toBeInTheDocument()
    // 审批卡会在对话流内联与舞台各出现一次（两处同源）
    expect((await screen.findAllByRole('button', { name: '通过' })).length).toBeGreaterThan(0)
    // 过程时间线：终态帧已到达（帧同时出现在折叠条与舞台，两处同源）
    expect((await screen.findAllByText('运行完成')).length).toBeGreaterThan(0)
  })

  it('纯文本不带幂等键、不开流（桩路径）', async () => {
    const { fetchMock, calls } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByText('整理一下客户反馈')

    await userEvent.type(screen.getByLabelText('消息内容'), '再补一条')
    await userEvent.click(screen.getByRole('button', { name: '发送消息' }))

    const posted = await waitFor(() => {
      const found = calls.find((call) => call.method === 'POST' && call.url.includes('/messages'))
      expect(found).toBeDefined()
      return found as Call
    })
    expect(posted.url).not.toContain(':stream')
    expect(posted.headers['Idempotency-Key']).toBeUndefined()
    // 纯文本**不触发实时发送路径**（`messages:stream` 不出现；进入会话的回放读端是另一回事，P2c-2 起）
    expect(calls.some((call) => call.method === 'POST' && call.url.includes(':stream'))).toBe(false)
    // 桩路径照旧：发送后重取详情（不做乐观拼接），草稿清空
    expect(await screen.findByLabelText('消息内容')).toHaveValue('')
    expect(calls.some((call) => call.method === 'GET' && call.url.includes('/conversations/conv-1?'))).toBe(true)
  })

  it('审批决议走既有接口，且决议后重新拉取（不做本地乐观更新）', async () => {
    const { fetchMock, calls } = makeFetch({ approvals: [{ approval_id: 'ap-1', step_id: 's-1', tool: 'cmd.run', status: 'pending' }] })
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByText('整理一下客户反馈')
    fireEvent.change(screen.getByLabelText('消息内容'), { target: { value: invocation } })
    await userEvent.click(screen.getByRole('button', { name: '发送消息' }))

    const approve = (await screen.findAllByRole('button', { name: '通过' }))[0]
    const before = calls.filter((call) => call.method === 'GET' && call.url.includes('/runs/run-9/approvals')).length

    await userEvent.click(approve)

    await waitFor(() => expect(calls.some((call) => call.method === 'POST' && call.url.includes('/runs/run-9/approvals/ap-1/approval'))).toBe(true))
    await waitFor(() =>
      expect(calls.filter((call) => call.method === 'GET' && call.url.includes('/runs/run-9/approvals')).length).toBeGreaterThan(before),
    )
  })

  it('非审批角色只读展示，不渲染决议按钮（服务端仍是权威）', async () => {
    vi.stubEnv('VITE_USER_ROLE', 'employee')
    const { fetchMock } = makeFetch({ approvals: [{ approval_id: 'ap-1', step_id: 's-1', tool: 'cmd.run', status: 'pending' }] })
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByText('整理一下客户反馈')
    fireEvent.change(screen.getByLabelText('消息内容'), { target: { value: invocation } })
    await userEvent.click(screen.getByRole('button', { name: '发送消息' }))

    expect((await screen.findAllByText(/仅 CEO \/ 超级管理员可决议/)).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: '通过' })).toBeNull()
    expect(screen.queryByRole('button', { name: '驳回' })).toBeNull()
  })

  it('收尾检查（展示型）：终态后给出进度档但不改运行状态', async () => {
    const { fetchMock } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByText('整理一下客户反馈')
    fireEvent.change(screen.getByLabelText('消息内容'), { target: { value: invocation } })
    await userEvent.click(screen.getByRole('button', { name: '发送消息' }))

    expect(await screen.findByText('收尾检查')).toBeInTheDocument()
    expect(await screen.findByText('进度档')).toBeInTheDocument()
    expect(screen.getByText('只做展示，不改变运行状态（结构判定与一键重做在 P2c-4 提供）。')).toBeInTheDocument()
  })

  it('结构化调用未产生运行（后端未装配真实执行）⇒ 关流并如实告知，不留「执行中」假象', async () => {
    const { fetchMock } = makeFetch({ produceRun: false })
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByText('整理一下客户反馈')
    fireEvent.change(screen.getByLabelText('消息内容'), { target: { value: invocation } })
    await userEvent.click(screen.getByRole('button', { name: '发送消息' }))

    expect(await screen.findByText('本次没有过程流')).toBeInTheDocument()
    expect(screen.getByText(/未产生运行：后端未装配真实执行/)).toBeInTheDocument()
    // 关流后过程条不残留（不谎报「执行中」）
    await waitFor(() => expect(document.querySelector('.process-bar')).toBeNull())
    expect(screen.queryByText('执行中')).toBeNull()
    // 舞台回到「暂无运行」空态，而不是加载一个不存在的 run
    expect(screen.getByText('暂无运行')).toBeInTheDocument()
  })

  it('终端输出面板：只渲染有界摘录并显式告知截断（无输出则不摆面板）', async () => {
    const outputFrame = `id: 3\nevent: tool.result\ndata: ${JSON.stringify({
      seq: 3,
      kind: 'tool.result',
      payload: { tool_key: 'cmd.run', status: 'ok', output_excerpt: 'hello\nworld', output_truncated: true, output_bytes: 4096 },
      is_terminal: false,
    })}\n\n`
    const { fetchMock } = makeFetch({ frames: [outputFrame, sseFrame(4, 'run.completed', true)] })
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByText('整理一下客户反馈')
    fireEvent.change(screen.getByLabelText('消息内容'), { target: { value: invocation } })
    await userEvent.click(screen.getByRole('button', { name: '发送消息' }))

    expect(await screen.findByRole('region', { name: '终端输出' })).toBeInTheDocument()
    expect(screen.getByLabelText('执行输出摘录')).toHaveTextContent('hello')
    expect(screen.getByText(/输出超过回传上限，已截断（已读取 4096 字节/)).toBeInTheDocument()
  })

  it('无输出帧时不渲染终端 / 文件改动面板（不摆空面板）', async () => {
    const { fetchMock } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByText('整理一下客户反馈')
    fireEvent.change(screen.getByLabelText('消息内容'), { target: { value: invocation } })
    await userEvent.click(screen.getByRole('button', { name: '发送消息' }))

    await screen.findAllByText('运行完成')
    expect(screen.queryByRole('region', { name: '终端输出' })).toBeNull()
    expect(screen.queryByRole('region', { name: '文件改动' })).toBeNull()
  })

  it('历史会话：读端响应头解析 run ⇒ 运行概览与审批可用（此前只有过程时间线）', async () => {
    const { fetchMock, calls } = makeFetch({
      frames: [sseFrame(1, 'run.completed', true)],
      streamHeaders: { 'X-Stream-Run-Id': 'run-9' },
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByText('整理一下客户反馈')

    expect(await screen.findByText('步骤完成度')).toBeInTheDocument()
    expect(calls.some((call) => call.url.includes('/runs/run-9/metrics'))).toBe(true)
    expect(calls.some((call) => call.url.includes('/runs/run-9/approvals'))).toBe(true)
  })
})