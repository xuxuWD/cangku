import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RunDetailPage } from './RunDetailPage'

const metrics = { run_id: 'run-1', task_id: 'task-1', proposal_id: null, runtime_key: 'mock', status: 'running', step_count: 3, completed_step_count: 1, tool_calls: 2, successful_tools: 1, knowledge_hits: 0, latency_ms: 1200, started_at: '2026-09-11T02:00:00Z', finished_at: null, finish_reason: null }

function makeTask(createdBy: string) {
  return { id: 'task-1', tenant_id: 'demo-tenant', project_id: null, created_by: createdBy, employee_key: 'content-operator', title: '整理本周选题', risk_level: 'low', budget: 100, idempotency_key: 'k-1', status: 'running', audit_count: 1 }
}

const events = [
  { cursor: 'run-1:1', run_id: 'run-1', sequence: 1, event_type: 'plan.created', payload: { status: 'pending_review' } },
  { cursor: 'run-1:2', run_id: 'run-1', sequence: 2, event_type: 'tool.call', payload: { step_id: 's-1', tool: 'search' } },
]

const approvals = [{ approval_id: 'a-1', step_id: 's-1', tool: 'search', status: 'pending' }]

const artifacts = [
  { artifact_id: 'art-1', virtual_path: '/workspace/report.md', change_kind: 'created', bytes: 2048, sha256: 'a'.repeat(64), created_at: '2026-09-11T02:01:00Z', expires_at: null },
]

const acceptance = {
  run_id: 'run-1',
  verdict: 'unmet',
  checks: { steps_complete: false, no_pending_approvals: true, finish_reason_ok: false },
  steps: { completed: 1, total: 3 },
  pending_approvals: 0,
  finish_reason: null,
  status: 'running',
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

interface Overrides {
  metrics?: () => Response
  task?: () => Response
  events?: () => Response
  approvals?: () => Response
  decision?: () => Response
  action?: (url: string) => Response
  acceptance?: () => Response
  acceptanceDecisions?: () => Response
  acceptanceSign?: (url: string, init?: RequestInit) => Response
  acceptancePromote?: (url: string, init?: RequestInit) => Response
}

function createFetch(createdBy = 'someone-else', overrides: Overrides = {}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/inbox?')) return jsonResponse({ items: [], unread_count: 0 })
    if (init?.method === 'POST' && url.includes('/approval')) return overrides.decision ? overrides.decision() : jsonResponse({ run_id: 'run-1', approval_id: 'a-1', status: 'approved', run_status: 'running' })
    if (init?.method === 'POST' && /\/pause|\/resume|\/cancel$/.test(url)) return overrides.action ? overrides.action(url) : jsonResponse({ run_id: 'run-1', status: 'paused' })
    if (init?.method === 'POST' && url.includes('/acceptance/tasks')) {
      return overrides.acceptancePromote ? overrides.acceptancePromote(url, init) : jsonResponse({ run_id: 'run-1', task_id: 'task-promoted', created: true, promotion: { task_id: 'task-promoted', title: '整理本周选题', promoted_by: 'someone-else', promoted_at: '2026-09-19T02:10:00Z' }, task: makeTask(createdBy) }, 201)
    }
    if (init?.method === 'POST' && url.includes('/acceptance/decisions')) {
      return overrides.acceptanceSign ? overrides.acceptanceSign(url, init) : jsonResponse({ run_id: 'run-1', decision_id: 'dec-1', decision: 'confirmed', reason: '', decided_by: 'someone-else', decided_at: '2026-09-18T02:10:00Z', structural_verdict: 'met', created: true })
    }
    if (url.includes('/runs/run-1/acceptance/decisions')) return overrides.acceptanceDecisions ? overrides.acceptanceDecisions() : jsonResponse({ run_id: 'run-1', items: [], latest: null, promotion: null })
    if (url.includes('/runs/run-1/acceptance')) return overrides.acceptance ? overrides.acceptance() : jsonResponse(acceptance)
    if (url.includes('/runs/run-1/metrics')) return overrides.metrics ? overrides.metrics() : jsonResponse(metrics)
    if (url.includes('/runs/run-1/events')) return overrides.events ? overrides.events() : jsonResponse(events)
    if (url.includes('/runs/run-1/approvals')) return overrides.approvals ? overrides.approvals() : jsonResponse({ items: approvals })
    if (url.includes('/runs/run-1/artifacts')) return jsonResponse({ run_id: 'run-1', items: artifacts, total: artifacts.length })
    if (url.includes('/tasks/task-1')) return overrides.task ? overrides.task() : jsonResponse(makeTask(createdBy))
    if (url.includes('/tasks/task-promoted')) return jsonResponse({ ...makeTask(createdBy), id: 'task-promoted', title: '整理本周选题' })
    return jsonResponse({})
  })
}

/** 终态 + 已确认完成的运行（沉淀入口的两个前置条件）。 */
function confirmedRun(promotion: unknown = null) {
  return {
    metrics: () => jsonResponse({ ...metrics, status: 'completed', completed_step_count: 3, finished_at: '2026-09-18T02:09:00Z', finish_reason: 'run_completed' }),
    acceptanceDecisions: () => jsonResponse({
      run_id: 'run-1',
      items: [{ decision_id: 'dec-1', decision: 'confirmed', reason: '', decided_by: 'someone-else', decided_at: '2026-09-18T02:10:00Z', structural_verdict: 'met' }],
      latest: { decision_id: 'dec-1', decision: 'confirmed', reason: '', decided_by: 'someone-else', decided_at: '2026-09-18T02:10:00Z', structural_verdict: 'met' },
      promotion,
    }),
  }
}

/** 上面那份「已确认完成」的覆写集合（终态 + 决议历史一起给，缺一样就不是沉淀场景）。 */
function confirmedOverrides(promotion: unknown = null): Overrides {
  return confirmedRun(promotion)
}

describe('RunDetailPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('loads and displays metrics, approvals and events', async () => {
    vi.stubGlobal('fetch', createFetch())

    render(<RunDetailPage runId="run-1" />)

    expect(await screen.findByText('整理本周选题')).toBeInTheDocument()
    expect(screen.getByText('1/3')).toBeInTheDocument()
    expect(screen.getByText('1200 ms')).toBeInTheDocument()
    expect(screen.getByText('运行中', { selector: 'span.status-badge' })).toBeInTheDocument()
    // 审批项改用共用 ApprovalCard（步骤 / 工具 / 审批号 + 状态徽标）。
    const approvalsList = document.querySelector('.approvals-stack[role="list"]') as HTMLElement
    expect(approvalsList).not.toBeNull()
    expect(within(approvalsList).getByText('search')).toBeInTheDocument()
    expect(within(approvalsList).getByText('s-1')).toBeInTheDocument()
    expect(within(approvalsList).getByText('a-1')).toBeInTheDocument()
    expect(within(approvalsList).getByText('待审批')).toBeInTheDocument()
    expect(screen.getByText('#1 计划已创建')).toBeInTheDocument()
    expect(screen.getByText('#2 工具调用')).toBeInTheDocument()
  })

  it('hides the decision buttons and explains when the viewer is the initiator', async () => {
    vi.stubGlobal('fetch', createFetch('admin'))

    render(<RunDetailPage runId="run-1" />)

    expect(await screen.findByText(/仅 CEO \/ 超级管理员可决议，且发起人不得自审/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '同意并继续' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '拒绝' })).not.toBeInTheDocument()
  })

  it('keeps the buttons for non-initiators and reloads after a decision', async () => {
    const fetchMock = createFetch('someone-else')
    vi.stubGlobal('fetch', fetchMock)

    render(<RunDetailPage runId="run-1" />)

    await screen.findByRole('button', { name: '同意并继续' })
    const approvalsCalls = () => fetchMock.mock.calls.filter((call) => String(call[0]).includes('/runs/run-1/approvals') && !(call[1] as RequestInit | undefined)?.method).length
    expect(approvalsCalls()).toBe(1)

    await userEvent.click(screen.getByRole('button', { name: '同意并继续' }))

    expect(await screen.findByText('已通过', { selector: '.toast span' })).toBeInTheDocument()
    await waitFor(() => expect(approvalsCalls()).toBeGreaterThanOrEqual(2))
  })

  it('shows the backend detail when a decision is denied', async () => {
    vi.stubGlobal('fetch', createFetch('someone-else', { decision: () => jsonResponse({ detail: '发起人不能审批自己发起的运行' }, 403) }))

    render(<RunDetailPage runId="run-1" />)

    await screen.findByRole('button', { name: '同意并继续' })
    await userEvent.click(screen.getByRole('button', { name: '同意并继续' }))

    expect(await screen.findByText('发起人不能审批自己发起的运行', { selector: '.toast span' })).toBeInTheDocument()
  })

  it('keeps metrics and approvals when the events region fails', async () => {
    vi.stubGlobal('fetch', createFetch('someone-else', { events: () => jsonResponse({}, 500) }))

    render(<RunDetailPage runId="run-1" />)

    expect(await screen.findByText('整理本周选题')).toBeInTheDocument()
    expect(screen.getByText('1/3')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: '审批' })).getByText('s-1')).toBeInTheDocument()
    expect(await screen.findByText('事件加载失败')).toBeInTheDocument()
  })

  it('shows the empty states for approvals and events', async () => {
    vi.stubGlobal('fetch', createFetch('someone-else', { approvals: () => jsonResponse({ items: [] }), events: () => jsonResponse([]) }))

    render(<RunDetailPage runId="run-1" />)

    expect(await screen.findByText(/该运行没有审批项/)).toBeInTheDocument()
    expect(screen.getByText(/暂无事件/)).toBeInTheDocument()
  })

  // ---- S4 干预 ----

  it('refreshes to the authoritative state after pausing', async () => {
    let paused = false
    const fetchMock = createFetch('someone-else', {
      metrics: () => jsonResponse({ ...metrics, status: paused ? 'paused' : 'running' }),
      action: () => { paused = true; return jsonResponse({ run_id: 'run-1', status: 'paused' }) },
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<RunDetailPage runId="run-1" />)

    await userEvent.click(await screen.findByRole('button', { name: '暂停运行' }))

    // 不做本地乐观更新：状态来自重取的指标（running → paused），按钮随之切成「恢复运行」。
    expect(await screen.findByRole('button', { name: '恢复运行' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '暂停运行' })).not.toBeInTheDocument()
    expect(screen.getByText('已暂停该运行', { selector: '.toast span' })).toBeInTheDocument()
    const metricsCalls = fetchMock.mock.calls.filter((call) => String(call[0]).includes('/runs/run-1/metrics') && !(call[1] as RequestInit | undefined)?.method).length
    expect(metricsCalls).toBeGreaterThanOrEqual(2)
  })

  it('asks for confirmation before cancelling and sends nothing when declined', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const fetchMock = createFetch('someone-else')
    vi.stubGlobal('fetch', fetchMock)

    render(<RunDetailPage runId="run-1" />)

    await userEvent.click(await screen.findByRole('button', { name: '取消运行' }))

    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls.some((call) => /\/cancel$/.test(String(call[0])))).toBe(false)
    // 未确认 ⇒ 状态不变，运行仍可继续干预。
    expect(screen.getByRole('button', { name: '暂停运行' })).toBeInTheDocument()
    confirmSpy.mockRestore()
  })

  it('cancels after confirmation and drops the intervention buttons from the terminal run', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    let cancelled = false
    const fetchMock = createFetch('someone-else', {
      metrics: () => jsonResponse({ ...metrics, status: cancelled ? 'cancelled' : 'running', finished_at: cancelled ? '2026-09-11T02:05:00Z' : null, finish_reason: cancelled ? 'cancelled_by_user' : null }),
      action: () => { cancelled = true; return jsonResponse({ run_id: 'run-1', status: 'cancelled' }) },
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<RunDetailPage runId="run-1" />)

    await userEvent.click(await screen.findByRole('button', { name: '取消运行' }))

    expect(await screen.findByText('已取消该运行', { selector: '.toast span' })).toBeInTheDocument()
    expect(screen.getByText('已取消', { selector: 'span.status-badge' })).toBeInTheDocument()
    // 终态运行没有可干预项：不留假按钮。
    expect(screen.queryByRole('button', { name: '暂停运行' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '取消运行' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '恢复运行' })).not.toBeInTheDocument()
    confirmSpy.mockRestore()
  })

  it('shows the server reason inline when an intervention is refused', async () => {
    vi.stubGlobal('fetch', createFetch('someone-else', { action: () => jsonResponse({ detail: '运行已结束，无法暂停' }, 409) }))

    render(<RunDetailPage runId="run-1" />)

    await userEvent.click(await screen.findByRole('button', { name: '暂停运行' }))

    const notice = await screen.findByRole('alert')
    expect(within(notice).getByText('操作未生效')).toBeInTheDocument()
    expect(within(notice).getByText('运行已结束，无法暂停')).toBeInTheDocument()
  })

  it('does not offer intervention buttons for a finished run', async () => {
    vi.stubGlobal('fetch', createFetch('someone-else', { metrics: () => jsonResponse({ ...metrics, status: 'completed', completed_step_count: 3, finished_at: '2026-09-11T02:05:00Z', finish_reason: 'run_completed' }) }))

    render(<RunDetailPage runId="run-1" />)

    expect(await screen.findByText('已完成', { selector: 'span.status-badge' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '暂停运行' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '取消运行' })).not.toBeInTheDocument()
  })

  // ---- S2 交付（读侧） ----

  it('lists the delivery artifacts and the acceptance checks', async () => {
    vi.stubGlobal('fetch', createFetch('someone-else'))

    render(<RunDetailPage runId="run-1" />)

    const delivery = await screen.findByRole('region', { name: '交付' })
    expect(within(delivery).getByText('/workspace/report.md')).toBeInTheDocument()
    expect(within(delivery).getByText('新建')).toBeInTheDocument()
    expect(within(delivery).getByText('2048 B')).toBeInTheDocument()
    expect(within(delivery).getByText('未达标', { selector: 'span.status-badge' })).toBeInTheDocument()
    expect(within(delivery).getByText('步骤全部完成（未满足）')).toBeInTheDocument()
    expect(within(delivery).getByText('没有未决审批（已满足）')).toBeInTheDocument()
    expect(within(delivery).getByText('正常结束（未满足）')).toBeInTheDocument()
  })

  // S2 收尾（2026-09-19）：沉淀入口已交付——未确认时不给入口（如实说明缺哪一步）；
  // 「设为自动化」仍未交付，界面不摆假按钮（见下方沉淀相关用例）。
  it('states honestly which step is missing before the delivery sink appears', async () => {
    vi.stubGlobal('fetch', createFetch('someone-else'))

    render(<RunDetailPage runId="run-1" />)

    const delivery = await screen.findByRole('region', { name: '交付' })
    expect(within(delivery).getByText(/沉淀入口（存成任务）在「确认完成」之后出现/)).toBeInTheDocument()
    // 还没到那一步就不摆按钮（不假装可点）。
    expect(within(delivery).queryByRole('button', { name: /存成任务|设为自动化/ })).not.toBeInTheDocument()
  })

  it('points to the conversation for a redo instead of faking one on this page', async () => {
    vi.stubGlobal('fetch', createFetch('someone-else'))

    render(<RunDetailPage runId="run-1" />)

    const delivery = await screen.findByRole('region', { name: '交付' })
    expect(within(delivery).getByText(/请回到发起这次运行的对话页使用「一键重做」/)).toBeInTheDocument()
    expect(within(delivery).queryByRole('button', { name: '一键重做' })).not.toBeInTheDocument()
  })

  // ---- S2 人工验收（写侧） ----

  it('offers the acceptance actions on a finished run and records a confirmation', async () => {
    let signed = 0
    const fetchMock = createFetch('someone-else', {
      metrics: () => jsonResponse({ ...metrics, status: 'completed', completed_step_count: 3, finished_at: '2026-09-18T02:05:00Z', finish_reason: 'run_completed' }),
      acceptanceDecisions: () => jsonResponse({
        run_id: 'run-1',
        items: signed === 0 ? [] : [{ decision_id: 'dec-1', decision: 'confirmed', reason: '', decided_by: 'someone-else', decided_at: '2026-09-18T02:10:00Z', structural_verdict: 'met' }],
        latest: null,
      }),
      acceptanceSign: () => { signed += 1; return jsonResponse({ run_id: 'run-1', decision_id: 'dec-1', decision: 'confirmed', reason: '', decided_by: 'someone-else', decided_at: '2026-09-18T02:10:00Z', structural_verdict: 'met', created: true }) },
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<RunDetailPage runId="run-1" />)

    const confirmButton = await screen.findByRole('button', { name: '确认完成' })
    await userEvent.click(confirmButton)

    const posted = await waitFor(() => {
      const found = fetchMock.mock.calls.find((call) => (call[1] as RequestInit | undefined)?.method === 'POST' && String(call[0]).includes('/acceptance/decisions'))
      expect(found).toBeDefined()
      return found as [string, RequestInit]
    })
    const body = JSON.parse(String(posted[1].body))
    expect(body.decision).toBe('confirmed')
    expect(body.reason).toBe('')
    expect(body.idempotency_key).toBeTruthy()
    expect(await screen.findByText('已确认完成', { selector: '.toast span' })).toBeInTheDocument()
    // 服务端权威：重取决议历史后展示最新结论（不做本地拼接）。
    expect(await screen.findByText('已确认完成', { selector: 'span.status-badge' })).toBeInTheDocument()
  })

  it('requires a reason before sending a rejection and shows the recorded decision', async () => {
    let signed = 0
    const fetchMock = createFetch('someone-else', {
      metrics: () => jsonResponse({ ...metrics, status: 'completed', completed_step_count: 3, finished_at: '2026-09-18T02:05:00Z', finish_reason: 'run_completed' }),
      acceptanceDecisions: () => jsonResponse({
        run_id: 'run-1',
        items: signed === 0 ? [] : [{ decision_id: 'dec-2', decision: 'rejected', reason: '结果与要求不符', decided_by: 'someone-else', decided_at: '2026-09-18T02:12:00Z', structural_verdict: 'met' }],
        latest: null,
      }),
      acceptanceSign: () => { signed += 1; return jsonResponse({ run_id: 'run-1', decision_id: 'dec-2', decision: 'rejected', reason: '结果与要求不符', decided_by: 'someone-else', decided_at: '2026-09-18T02:12:00Z', structural_verdict: 'met', created: true }) },
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<RunDetailPage runId="run-1" />)

    await userEvent.click(await screen.findByRole('button', { name: '打回重做' }))
    const submit = screen.getByRole('button', { name: '确认打回' })
    expect(submit).toBeDisabled()

    await userEvent.type(screen.getByLabelText('打回原因'), '结果与要求不符')
    expect(submit).toBeEnabled()
    await userEvent.click(submit)

    const posted = await waitFor(() => {
      const found = fetchMock.mock.calls.find((call) => (call[1] as RequestInit | undefined)?.method === 'POST' && String(call[0]).includes('/acceptance/decisions'))
      expect(found).toBeDefined()
      return found as [string, RequestInit]
    })
    expect(JSON.parse(String(posted[1].body))).toMatchObject({ decision: 'rejected', reason: '结果与要求不符' })
    expect(await screen.findByText('已打回重做', { selector: '.toast span' })).toBeInTheDocument()
    expect(await screen.findByText(/原因：结果与要求不符/)).toBeInTheDocument()
  })

  it('shows the server reason when a rejection is refused', async () => {
    vi.stubGlobal('fetch', createFetch('someone-else', {
      metrics: () => jsonResponse({ ...metrics, status: 'completed', completed_step_count: 3, finished_at: '2026-09-18T02:05:00Z', finish_reason: 'run_completed' }),
      acceptanceSign: () => jsonResponse({ detail: '打回重做必须写明原因' }, 422),
    }))

    render(<RunDetailPage runId="run-1" />)

    await userEvent.click(await screen.findByRole('button', { name: '打回重做' }))
    await userEvent.type(screen.getByLabelText('打回原因'), 'x')
    await userEvent.click(screen.getByRole('button', { name: '确认打回' }))

    const notice = await screen.findByRole('alert')
    expect(within(notice).getByText('验收未记录')).toBeInTheDocument()
    expect(within(notice).getByText('打回重做必须写明原因')).toBeInTheDocument()
  })

  it('does not offer acceptance while the run is still going', async () => {
    vi.stubGlobal('fetch', createFetch('someone-else'))

    render(<RunDetailPage runId="run-1" />)

    const delivery = await screen.findByRole('region', { name: '交付' })
    expect(within(delivery).getByText(/运行尚未结束，暂不能验收/)).toBeInTheDocument()
    expect(within(delivery).queryByRole('button', { name: '确认完成' })).not.toBeInTheDocument()
    expect(within(delivery).queryByRole('button', { name: '打回重做' })).not.toBeInTheDocument()
  })

  it('explains the permission rules instead of showing dead buttons to non-owners', async () => {
    vi.stubEnv('VITE_USER_ROLE', 'employee')
    vi.stubEnv('VITE_USER_ID', 'admin')
    vi.stubGlobal('fetch', createFetch('someone-else', {
      metrics: () => jsonResponse({ ...metrics, status: 'completed', completed_step_count: 3, finished_at: '2026-09-18T02:05:00Z', finish_reason: 'run_completed' }),
    }))

    render(<RunDetailPage runId="run-1" />)

    const delivery = await screen.findByRole('region', { name: '交付' })
    expect(await within(delivery).findByText(/仅任务发起人、CEO 或超级管理员可以验收/)).toBeInTheDocument()
    expect(within(delivery).queryByRole('button', { name: '确认完成' })).not.toBeInTheDocument()
  })

  it('keeps the delivery block honest when the acceptance check cannot be read', async () => {
    vi.stubGlobal('fetch', createFetch('someone-else', { acceptance: () => jsonResponse({}, 500) }))

    render(<RunDetailPage runId="run-1" />)

    const delivery = await screen.findByRole('region', { name: '交付' })
    expect(within(delivery).getByText('验收判定读取失败')).toBeInTheDocument()
    // 读不到就如实说读不到（可重试），不给「达标 / 未达标」的假结论。
    expect(within(delivery).getByRole('button', { name: '重新尝试' })).toBeInTheDocument()
    expect(within(delivery).queryByText('达标')).not.toBeInTheDocument()
    expect(within(delivery).queryByText('未达标')).not.toBeInTheDocument()
  })

  // ---- S2 沉淀入口（存成任务） ----

  it('offers the promotion only after a confirmed acceptance, then records it', async () => {
    const { metrics: doneMetrics, acceptanceDecisions } = confirmedRun()
    let promotions = 0
    const fetchMock = createFetch('someone-else', {
      metrics: doneMetrics,
      // 第一次读：未沉淀；沉淀之后再读：已沉淀（服务端权威回流，不做本地拼接）。
      acceptanceDecisions: () => (promotions === 0
        ? acceptanceDecisions()
        : jsonResponse({
            run_id: 'run-1',
            // 真实服务端始终返回完整历史：确认那条仍在 items 里（面板以 items 为准）。
            items: [{ decision_id: 'dec-1', decision: 'confirmed', reason: '', decided_by: 'someone-else', decided_at: '2026-09-18T02:10:00Z', structural_verdict: 'met' }],
            latest: { decision_id: 'dec-1', decision: 'confirmed', reason: '', decided_by: 'someone-else', decided_at: '2026-09-18T02:10:00Z', structural_verdict: 'met' },
            promotion: { task_id: 'task-promoted', title: '整理本周选题', promoted_by: 'someone-else', promoted_at: '2026-09-19T02:10:00Z' },
          })),
      acceptancePromote: () => { promotions += 1; return jsonResponse({ run_id: 'run-1', task_id: 'task-promoted', created: true, promotion: { task_id: 'task-promoted', title: '整理本周选题', promoted_by: 'someone-else', promoted_at: '2026-09-19T02:10:00Z' }, task: makeTask('someone-else') }, 201) },
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<RunDetailPage runId="run-1" />)

    const delivery = await screen.findByRole('region', { name: '交付' })
    // 标题默认填来源承载任务标题（服务端数据），用户可改。
    const title = await within(delivery).findByLabelText('任务标题')
    expect((title as HTMLInputElement).value).toBe('整理本周选题')

    await userEvent.click(within(delivery).getByRole('button', { name: '存成任务' }))

    const posted = await waitFor(() => {
      const found = fetchMock.mock.calls.find((call) => (call[1] as RequestInit | undefined)?.method === 'POST' && String(call[0]).includes('/acceptance/tasks'))
      expect(found).toBeDefined()
      return found as [RequestInfo | URL, RequestInit]
    })
    expect(JSON.parse(String(posted[1].body))).toEqual({ title: '整理本周选题' })
    // 服务端权威回流：出现「已存成任务」与任务编号（不再显示标题输入框）；
    // 不给「打开任务」——平任务没有页面（任务中心未立项），点了只会落空。
    expect(await within(delivery).findByText('已存成任务')).toBeInTheDocument()
    expect(within(delivery).getByText(/task-promoted/)).toBeInTheDocument()
    expect(within(delivery).getByText(/任务的列表与详情页属后续范围（任务中心）/)).toBeInTheDocument()
    expect(within(delivery).queryByRole('button', { name: '打开任务' })).not.toBeInTheDocument()
    expect(within(delivery).queryByRole('button', { name: '存成任务' })).not.toBeInTheDocument()
  })

  it('does not offer the promotion before a confirmation and says which step is missing', async () => {
    vi.stubGlobal('fetch', createFetch('someone-else'))

    render(<RunDetailPage runId="run-1" />)

    const delivery = await screen.findByRole('region', { name: '交付' })
    expect(await within(delivery).findByText(/沉淀入口（存成任务）在「确认完成」之后出现/)).toBeInTheDocument()
    expect(within(delivery).queryByRole('button', { name: '存成任务' })).not.toBeInTheDocument()
    expect(within(delivery).queryByLabelText('任务标题')).not.toBeInTheDocument()
  })

  it('states where the promoted task can (and cannot) be found instead of a dead link', async () => {
    vi.stubGlobal('fetch', createFetch('someone-else', confirmedOverrides({ task_id: 'task-promoted', title: '上个月的那次整理', promoted_by: 'someone-else', promoted_at: '2026-09-19T02:10:00Z' })))

    render(<RunDetailPage runId="run-1" />)

    const delivery = await screen.findByRole('region', { name: '交付' })
    expect(await within(delivery).findByText('已存成任务')).toBeInTheDocument()
    expect(within(delivery).getByText(/上个月的那次整理/)).toBeInTheDocument()
    expect(within(delivery).queryByRole('button', { name: '存成任务' })).not.toBeInTheDocument()
    expect(within(delivery).queryByRole('button', { name: '打开任务' })).not.toBeInTheDocument()
  })

  it('keeps the promotion honest when the server refuses it', async () => {
    const { metrics: doneMetrics, acceptanceDecisions } = confirmedRun()
    vi.stubGlobal('fetch', createFetch('someone-else', {
      metrics: doneMetrics,
      acceptanceDecisions,
      acceptancePromote: () => jsonResponse({ detail: '先确认完成，再沉淀成任务' }, 409),
    }))

    render(<RunDetailPage runId="run-1" />)

    const delivery = await screen.findByRole('region', { name: '交付' })
    await userEvent.click(await within(delivery).findByRole('button', { name: '存成任务' }))

    // 服务端结论原样展示，不谎报成功、不留「已存成任务」假状态。
    expect(await within(delivery).findByText('沉淀未完成')).toBeInTheDocument()
    expect(within(delivery).queryByText('已存成任务')).not.toBeInTheDocument()
  })

  it('states that setting up automation is not delivered yet instead of faking a button', async () => {
    vi.stubGlobal('fetch', createFetch('someone-else', confirmedOverrides()))

    render(<RunDetailPage runId="run-1" />)

    const delivery = await screen.findByRole('region', { name: '交付' })
    expect(await within(delivery).findByText(/「设为自动化」属定时调度（尚未交付）/)).toBeInTheDocument()
    expect(within(delivery).queryByRole('button', { name: /自动化/ })).not.toBeInTheDocument()
  })
})
