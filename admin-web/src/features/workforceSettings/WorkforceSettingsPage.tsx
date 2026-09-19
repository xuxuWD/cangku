import { Fragment, useCallback, useEffect, useState } from 'react'
import type { AppView } from '../../app/AppShell'
import { Toast } from '../../components/Toast'
import { EmptyState } from '../../components/ui/EmptyState'
import { createAgent, createRole, listAgents, listCandidates, listModelCandidates, readAgentConfig, readToolCatalog, listRoles, updateAgent, updateAgentConfig, updateRole } from './api'
import { asDirectoryError, initialDirectoryState } from './state'
import { formatLocalTime } from '../../utils/time'
import {
  AUTONOMY_LEVELS,
  AUTONOMY_LEVEL_HINTS,
  AUTONOMY_LEVEL_LABELS,
  CONFIG_FORBIDDEN_MESSAGE,
  EMPTY_MODEL_KEY_LABEL,
  FULL_AUTO_NOTICE,
  MAX_APPROVAL_TIMEOUT_MINUTES,
  MAX_SHORT_TERM_TURNS,
  MAX_SYSTEM_PROMPT_LENGTH,
  MIN_APPROVAL_TIMEOUT_MINUTES,
  MODEL_EMPTY_LABEL,
  MODEL_NOT_REGISTERED_REASON,
  RISK_THRESHOLD_LABELS,
  TOOL_NOT_IN_GATE_REASON,
  TOOL_UNKNOWN_REASON,
  directoryStatusLabel,
  type AgentConfig,
  type AgentConfigUpdate,
  type DirectoryErrorShape,
  type DirectoryState,
  type ToolCatalog,
  type ToolCatalogItem,
} from './types'

type EditTarget = { kind: 'role' | 'agent'; key: string; name: string; description: string; role_key: string }

const EMPTY_ROLE_FORM = { role_key: '', name: '', description: '' }
const EMPTY_AGENT_FORM = { agent_key: '', name: '', role_key: '', description: '' }

// 表单里数字一律先按字符串保存（用户可清空/输入中），提交前再统一换算与校验。
interface AgentConfigForm {
  system_prompt: string
  model_key: string
  temperature: string
  tool_allowlist: string[]
  short_term_enabled: boolean
  short_term_turns: string
  autonomy_level: string
  risk_threshold: string
  approval_timeout_minutes: string
  daily_budget_yuan: string
}

/** 工具多选的一个可选项：目录项带风险档；闸门集合里的目录外键标 `planner`；两者皆非标 `unknown`。 */
interface ToolOption {
  key: string
  selectable: boolean
  reason: string | null
  source: 'catalog' | 'planner' | 'unknown'
  item: ToolCatalogItem | null
}

function buildToolOptions(catalog: ToolCatalog | null, selected: string[]): ToolOption[] {
  if (!catalog) {
    // 候选不可用 ⇒ 回落自由文本（不摆假选项）：仅按当前值原样呈现，保存以服务端为准。
    return selected.map((key) => ({ key, selectable: true, reason: null, source: 'unknown' as const, item: null }))
  }
  const gate = new Set(catalog.allowlist)
  const options: ToolOption[] = catalog.items.map((item) => ({
    key: item.tool_key,
    selectable: gate.has(item.tool_key),
    reason: gate.has(item.tool_key) ? null : TOOL_NOT_IN_GATE_REASON,
    source: 'catalog' as const,
    item,
  }))
  const known = new Set(options.map((option) => option.key))
  for (const key of catalog.allowlist) {
    if (!known.has(key)) {
      options.push({ key, selectable: true, reason: null, source: 'planner' as const, item: null })
    }
  }
  // 当前值里既不在目录、也不在闸门集合内的键：灰显并给原因（保存会被后端 422 拒绝）。
  for (const key of selected) {
    if (!options.some((option) => option.key === key)) {
      options.push({ key, selectable: false, reason: TOOL_UNKNOWN_REASON, source: 'unknown' as const, item: null })
    }
  }
  return options
}

function toolOptionLabel(option: ToolOption): string {
  if (option.item) {
    const approval = option.item.requires_approval ? ' · 需审批' : ''
    return `${option.key}（风险 ${option.item.risk_level}${approval}${option.item.has_side_effect ? ' · 有副作用' : ''}）`
  }
  if (option.source === 'planner') return `${option.key}（规划器白名单）`
  return option.key
}

function configToForm(config: AgentConfig): AgentConfigForm {
  const memory = config.memory_policy as { short_term_enabled?: unknown; short_term_turns?: unknown }
  return {
    system_prompt: config.system_prompt,
    model_key: config.model_key,
    // 温度固定显示两位小数（0.2 → 0.20），与后端 NUMERIC(3,2) 口径一致。
    temperature: config.temperature.toFixed(2),
    tool_allowlist: [...config.tool_allowlist],
    short_term_enabled: memory.short_term_enabled === true,
    short_term_turns: typeof memory.short_term_turns === 'number' ? String(memory.short_term_turns) : '0',
    autonomy_level: config.autonomy_level,
    risk_threshold: config.risk_threshold,
    approval_timeout_minutes: String(config.approval_timeout_minutes),
    daily_budget_yuan: (config.daily_budget_cents / 100).toFixed(2),
  }
}

// 金额按「元」输入、提交前换算为**整数分**（宪法：金额不用浮点）；换算不出数字时返回 null。
function buildConfigPayload(form: AgentConfigForm): AgentConfigUpdate | null {
  const temperature = Number(form.temperature)
  const turns = Number(form.short_term_turns)
  const timeout = Number(form.approval_timeout_minutes)
  const yuan = Number(form.daily_budget_yuan)
  if (![temperature, turns, timeout, yuan].every((value) => Number.isFinite(value))) return null
  return {
    system_prompt: form.system_prompt,
    model_key: form.model_key.trim(),
    temperature,
    tool_allowlist: [...form.tool_allowlist].sort(),
    memory_policy: { short_term_enabled: form.short_term_enabled, short_term_turns: turns },
    autonomy_level: form.autonomy_level,
    risk_threshold: form.risk_threshold,
    approval_timeout_minutes: timeout,
    daily_budget_cents: Math.round(yuan * 100),
  }
}

export function WorkforceSettingsPage({ onNavigate }: { onNavigate?: (view: AppView) => void }) {
  const [state, setState] = useState<DirectoryState>(initialDirectoryState)
  const [roleForm, setRoleForm] = useState(EMPTY_ROLE_FORM)
  const [agentForm, setAgentForm] = useState(EMPTY_AGENT_FORM)
  const [editing, setEditing] = useState<EditTarget | null>(null)
  // 员工配置：展开哪个员工、读到的配置、编辑中的表单与错误。
  const [configTarget, setConfigTarget] = useState<string | null>(null)
  const [config, setConfig] = useState<AgentConfig | null>(null)
  const [configForm, setConfigForm] = useState<AgentConfigForm | null>(null)
  const [configLoading, setConfigLoading] = useState(false)
  const [configSaving, setConfigSaving] = useState(false)
  const [configError, setConfigError] = useState<DirectoryErrorShape | null>(null)
  // P2c-4：两个只读候选端点（仅超管）。读取失败 ⇒ `null`：**回落自由文本**，不摆假选项。
  const [modelKeys, setModelKeys] = useState<string[] | null>(null)
  const [toolCatalog, setToolCatalog] = useState<ToolCatalog | null>(null)
  const [candidateError, setCandidateError] = useState<DirectoryErrorShape | null>(null)

  const load = useCallback(async () => {
    setState((old) => ({ ...old, loading: true, error: null }))
    try {
      const [roles, agents, candidates] = await Promise.all([listRoles(), listAgents(), listCandidates()])
      setState((old) => ({ ...old, roles, agents, candidates, loading: false, error: null }))
    } catch (error) {
      setState((old) => ({ ...old, loading: false, error: asDirectoryError(error) }))
    }
  }, [])

  // 候选端点独立加载：目录列表挂了不应连带把选择器变成假选项（各自失败各自降级）。
  // 响应形态不完整（缺 items / allowlist）**一律按不可用处理**并回落自由文本，不猜测补默认值。
  const loadCandidates = useCallback(async () => {
    setCandidateError(null)
    try {
      const [models, catalog] = await Promise.all([listModelCandidates(), readToolCatalog()])
      if (!Array.isArray(models?.items) || !Array.isArray(catalog?.items) || !Array.isArray(catalog?.allowlist)) {
        setModelKeys(null)
        setToolCatalog(null)
        setCandidateError({ status: 0, message: '可选清单返回的内容不完整，已改为手动填写。', retryable: true })
        return
      }
      setModelKeys(models.items.filter((key): key is string => typeof key === 'string' && key.trim() !== ''))
      setToolCatalog(catalog)
    } catch (error) {
      setModelKeys(null)
      setToolCatalog(null)
      setCandidateError(asDirectoryError(error))
    }
  }, [])

  useEffect(() => { void load() }, [load])
  useEffect(() => { void loadCandidates() }, [loadCandidates])

  // 写操作统一走这里：成功→刷新列表并提示；失败→只把错误显示在表单区，不动已加载的列表。
  const submit = useCallback(async (operation: () => Promise<unknown>, success: string, reset?: () => void) => {
    setState((old) => ({ ...old, saving: true, formError: null }))
    try {
      await operation()
      reset?.()
      setEditing(null)
      setState((old) => ({ ...old, saving: false, toast: success }))
      await load()
    } catch (error) {
      setState((old) => ({ ...old, saving: false, formError: asDirectoryError(error) }))
    }
  }, [load])

  const switchTab = (tab: DirectoryState['tab']) => {
    setEditing(null)
    setConfigTarget(null)
    setConfigError(null)
    setState((old) => ({ ...old, tab, formError: null }))
  }
  const activeRoles = state.roles.items.filter((role) => role.status === 'active')

  // 读配置：仅超级管理员可读，403 时在配置区显示后端/固定中文文案。
  const openConfig = async (agentKey: string) => {
    setEditing(null)
    setConfigTarget(agentKey)
    setConfig(null)
    setConfigForm(null)
    setConfigError(null)
    setConfigLoading(true)
    try {
      const loaded = await readAgentConfig(agentKey)
      setConfig(loaded)
      setConfigForm(configToForm(loaded))
    } catch (error) {
      // 非超管读配置是 403：给配置区一句专用文案，而不是留空或复用目录权限文案。
      const shaped = asDirectoryError(error)
      setConfigError(shaped.status === 403 ? { ...shaped, message: CONFIG_FORBIDDEN_MESSAGE } : shaped)
    } finally {
      setConfigLoading(false)
    }
  }

  // 写配置：必须先等后端响应；422（含 D11 提示注入被拒）原样显示后端中文原因。
  const saveConfig = async () => {
    if (!configTarget || !configForm || configSaving) return
    const payload = buildConfigPayload(configForm)
    if (!payload) {
      setConfigError({ status: 0, message: '温度、保留轮数、审批超时与每日预算必须是数字。', retryable: false })
      return
    }
    setConfigSaving(true)
    setConfigError(null)
    try {
      const updated = await updateAgentConfig(configTarget, payload)
      setConfig(updated)
      setConfigForm(configToForm(updated))
      setState((old) => ({ ...old, toast: `数字员工 ${configTarget} 的配置已更新` }))
    } catch (error) {
      setConfigError(asDirectoryError(error))
    } finally {
      setConfigSaving(false)
    }
  }

  return <>
    <main className="main-content content-history t3 workforce-settings">
      <div className="t3__intro">
        <p className="page-desc">维护本公司的岗位与数字员工：标识创建后不可修改；停用只影响后续挂载与指派，不撤销已有的知识范围绑定，也不影响历史任务。仅超级管理员可读写。</p>
        <div className="t3__actions">
          <button className="btn btn--secondary" type="button" disabled={state.loading} onClick={() => void load()}>{state.loading ? '正在刷新' : '刷新'}</button>
        </div>
      </div>

      <div className="metrics">
        <div className="metric">
          <div className="metric__label">岗位</div>
          <div className="metric__value">{state.loading ? '—' : state.roles.total}</div>
          <div className="metric__hint">已纳入目录的岗位数</div>
        </div>
        <div className="metric">
          <div className="metric__label">数字员工</div>
          <div className="metric__value">{state.loading ? '—' : state.agents.total}</div>
          <div className="metric__hint">已纳入目录的数字员工数</div>
        </div>
        <div className="metric">
          <div className="metric__label">未纳管标识</div>
          <div className="metric__value">{state.loading ? '—' : state.candidates.roles.length + state.candidates.agents.length}</div>
          <div className="metric__hint">出现在知识绑定或历史任务里、尚未纳入目录</div>
        </div>
        <div className="metric">
          <div className="metric__label">启用中的岗位</div>
          <div className="metric__value">{state.loading ? '—' : activeRoles.length}</div>
          <div className="metric__hint">新建数字员工时只能挂到启用的岗位</div>
        </div>
      </div>

      <div className="toolbar">
        <div className="segmented" role="tablist" aria-label="目录类型">
          <button role="tab" type="button" aria-selected={state.tab === 'roles'} className={state.tab === 'roles' ? 'is-active' : ''} onClick={() => switchTab('roles')}>岗位</button>
          <button role="tab" type="button" aria-selected={state.tab === 'agents'} className={state.tab === 'agents' ? 'is-active' : ''} onClick={() => switchTab('agents')}>数字员工</button>
        </div>
        <span className="role-note">{state.tab === 'roles' ? `共 ${state.roles.total} 个岗位` : `共 ${state.agents.total} 个数字员工`}</span>
      </div>

      {state.error && <div className="notice notice-error" role="alert"><div><strong>名单加载失败</strong><p>{state.error.message}</p></div>{state.error.retryable && <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button>}</div>}
      {!state.error && state.formError && <div className="notice notice-error" role="alert"><div><strong>保存失败</strong><p>{state.formError.message}</p></div></div>}
      {state.loading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载岗位与数字员工…</div>}

      {!state.loading && !state.error && state.tab === 'roles' && <>
        <section className="card" aria-label="新建岗位">
          <div className="card__head"><h2>新建岗位</h2><span className="role-note">标识创建后不可修改</span></div>
          <div className="card__body">
            <div className="ws-form">
              <label className="ws-field">岗位标识<input value={roleForm.role_key} placeholder="content-operator" onChange={(event) => setRoleForm({ ...roleForm, role_key: event.target.value })} /></label>
              <label className="ws-field">中文名<input value={roleForm.name} placeholder="自媒体运营岗" onChange={(event) => setRoleForm({ ...roleForm, name: event.target.value })} /></label>
              <label className="ws-field ws-field--wide">描述<input value={roleForm.description} placeholder="可选" onChange={(event) => setRoleForm({ ...roleForm, description: event.target.value })} /></label>
              <div className="ws-submit"><button className="btn btn--primary" type="button" disabled={state.saving} onClick={() => void submit(() => createRole(roleForm), `岗位 ${roleForm.role_key} 已创建`, () => setRoleForm(EMPTY_ROLE_FORM))}>创建岗位</button></div>
            </div>
          </div>
        </section>

        <section className="card" aria-label="岗位列表">
          <div className="card__head"><h2>岗位</h2><span className="role-note">{state.roles.items.length} / {state.roles.total}</span></div>
          {state.roles.items.length === 0 && <EmptyState illustration="list" title="暂无岗位" text="先创建一个岗位，再把数字员工挂到它下面。" />}
          {state.roles.items.map((role) => editing?.kind === 'role' && editing.key === role.role_key
            ? <div className="ws-row" key={role.role_key}>
              <div className="ws-row-main">
                <label className="ws-field">中文名<input value={editing.name} onChange={(event) => setEditing({ ...editing, name: event.target.value })} /></label>
                <label className="ws-field ws-field--wide">描述<input value={editing.description} onChange={(event) => setEditing({ ...editing, description: event.target.value })} /></label>
                <div className="history-meta"><span className="ws-code">{role.role_key}</span><span>标识不可修改</span></div>
              </div>
              <div className="history-actions">
                <button className="btn btn--primary btn--sm" type="button" disabled={state.saving} onClick={() => void submit(() => updateRole(role.role_key, { name: editing.name, description: editing.description }), `岗位 ${role.role_key} 已更新`)}>保存</button>
                <button className="btn btn--secondary btn--sm" type="button" onClick={() => setEditing(null)}>取消</button>
              </div>
            </div>
            : <div className="ws-row" key={role.role_key}>
              <div className="ws-row-main">
                <strong>{role.name}</strong>
                <div className="history-meta">
                  <span className="ws-code">{role.role_key}</span>
                  <span className={`status-badge status-${role.status}`}>{directoryStatusLabel(role.status)}</span>
                  {role.description && <span>{role.description}</span>}
                </div>
              </div>
              <div className="history-actions">
                <button className="btn btn--secondary btn--sm" type="button" onClick={() => setEditing({ kind: 'role', key: role.role_key, name: role.name, description: role.description, role_key: role.role_key })}>修改</button>
                <button className="btn btn--secondary btn--sm" type="button" disabled={state.saving} onClick={() => void submit(() => updateRole(role.role_key, { status: role.status === 'active' ? 'disabled' : 'active' }), `岗位 ${role.role_key} 已${role.status === 'active' ? '停用' : '启用'}`)}>{role.status === 'active' ? '停用' : '启用'}</button>
              </div>
            </div>)}
        </section>

        {state.candidates.roles.length > 0 && <section className="card" aria-label="未纳管岗位标识">
          <div className="card__head"><h2>未纳管标识</h2><span className="role-note">{state.candidates.roles.length} 个</span></div>
          <div className="card__body">
            <p className="stage-hint">这些标识已出现在知识范围绑定里，但还没有纳入目录。纳管时补一个中文名即可（标识保持不变）。</p>
          </div>
          {state.candidates.roles.map((key) => <div className="ws-row" key={key}>
            <div className="ws-row-main"><strong className="ws-code">{key}</strong><div className="history-meta"><span>来源：知识范围绑定</span></div></div>
            <div className="history-actions"><button className="btn btn--secondary btn--sm" type="button" onClick={() => setRoleForm({ role_key: key, name: '', description: '' })}>纳管</button></div>
          </div>)}
        </section>}
      </>}

      {!state.loading && !state.error && state.tab === 'agents' && <>
        <section className="card" aria-label="新建数字员工">
          <div className="card__head"><h2>新建数字员工</h2><span className="role-note">必须归属一个启用中的岗位</span></div>
          <div className="card__body">
            <div className="ws-form">
              <label className="ws-field">员工标识<input value={agentForm.agent_key} placeholder="content-writer" onChange={(event) => setAgentForm({ ...agentForm, agent_key: event.target.value })} /></label>
              <label className="ws-field">中文名<input value={agentForm.name} placeholder="内容创作数字员工" onChange={(event) => setAgentForm({ ...agentForm, name: event.target.value })} /></label>
              <label className="ws-field">所属岗位<select value={agentForm.role_key} onChange={(event) => setAgentForm({ ...agentForm, role_key: event.target.value })}><option value="">请选择岗位</option>{activeRoles.map((role) => <option key={role.role_key} value={role.role_key}>{role.name}（{role.role_key}）</option>)}</select></label>
              <label className="ws-field ws-field--wide">描述<input value={agentForm.description} placeholder="可选" onChange={(event) => setAgentForm({ ...agentForm, description: event.target.value })} /></label>
              <div className="ws-submit"><button className="btn btn--primary" type="button" disabled={state.saving} onClick={() => void submit(() => createAgent(agentForm), `数字员工 ${agentForm.agent_key} 已创建`, () => setAgentForm(EMPTY_AGENT_FORM))}>创建数字员工</button></div>
            </div>
            {activeRoles.length === 0 && <p className="stage-hint">当前没有启用中的岗位：请先在「岗位」页签创建岗位，再回来挂载数字员工。</p>}
          </div>
        </section>

        <section className="card" aria-label="数字员工列表">
          <div className="card__head"><h2>数字员工</h2><span className="role-note">{state.agents.items.length} / {state.agents.total}</span></div>
          {state.agents.items.length === 0 && <EmptyState illustration="list" title="暂无数字员工" text="创建数字员工后需要指定它归属的岗位。" />}
          {state.agents.items.map((employee) => (
            <Fragment key={employee.agent_key}>
              {editing?.kind === 'agent' && editing.key === employee.agent_key
                ? <div className="ws-row">
                  <div className="ws-row-main">
                    <label className="ws-field">中文名<input value={editing.name} onChange={(event) => setEditing({ ...editing, name: event.target.value })} /></label>
                    <label className="ws-field">所属岗位<select value={editing.role_key} onChange={(event) => setEditing({ ...editing, role_key: event.target.value })}>{activeRoles.map((role) => <option key={role.role_key} value={role.role_key}>{role.name}（{role.role_key}）</option>)}</select></label>
                    <label className="ws-field ws-field--wide">描述<input value={editing.description} onChange={(event) => setEditing({ ...editing, description: event.target.value })} /></label>
                    <div className="history-meta"><span className="ws-code">{employee.agent_key}</span><span>标识不可修改</span></div>
                  </div>
                  <div className="history-actions">
                    <button className="btn btn--primary btn--sm" type="button" disabled={state.saving} onClick={() => void submit(() => updateAgent(employee.agent_key, { name: editing.name, description: editing.description, role_key: editing.role_key }), `数字员工 ${employee.agent_key} 已更新`)}>保存</button>
                    <button className="btn btn--secondary btn--sm" type="button" onClick={() => setEditing(null)}>取消</button>
                  </div>
                </div>
                : <div className="ws-row">
                  <div className="ws-row-main">
                    <strong>{employee.name}</strong>
                    <div className="history-meta">
                      <span className="ws-code">{employee.agent_key}</span>
                      <span className={`status-badge status-${employee.status}`}>{directoryStatusLabel(employee.status)}</span>
                      <span>所属岗位：{employee.role_key}</span>
                      {employee.description && <span>{employee.description}</span>}
                    </div>
                  </div>
                  <div className="history-actions">
                    <button className="btn btn--secondary btn--sm" type="button" onClick={() => void openConfig(employee.agent_key)}>配置</button>
                    <button className="btn btn--secondary btn--sm" type="button" onClick={() => setEditing({ kind: 'agent', key: employee.agent_key, name: employee.name, description: employee.description, role_key: employee.role_key })}>修改</button>
                    <button className="btn btn--secondary btn--sm" type="button" disabled={state.saving} onClick={() => void submit(() => updateAgent(employee.agent_key, { status: employee.status === 'active' ? 'disabled' : 'active' }), `数字员工 ${employee.agent_key} 已${employee.status === 'active' ? '停用' : '启用'}`)}>{employee.status === 'active' ? '停用' : '启用'}</button>
                  </div>
                </div>}

              {configTarget === employee.agent_key && (
                <AgentConfigEditor
                  name={employee.name}
                  agentKey={employee.agent_key}
                  config={config}
                  form={configForm}
                  loading={configLoading}
                  saving={configSaving}
                  error={configError}
                  modelKeys={modelKeys}
                  toolCatalog={toolCatalog}
                  candidateError={candidateError}
                  onReloadCandidates={() => void loadCandidates()}
                  onChange={setConfigForm}
                  onSave={() => void saveConfig()}
                  onClose={() => { setConfigTarget(null); setConfigError(null) }}
                />
              )}
            </Fragment>
          ))}
        </section>

        {state.candidates.agents.length > 0 && <section className="card" aria-label="未纳管员工标识">
          <div className="card__head"><h2>未纳管标识</h2><span className="role-note">{state.candidates.agents.length} 个</span></div>
          <div className="card__body">
            <p className="stage-hint">这些标识出现在知识范围绑定或历史任务里，但还没有纳入目录。纳管时补一个中文名并选择所属岗位。</p>
          </div>
          {state.candidates.agents.map((key) => <div className="ws-row" key={key}>
            <div className="ws-row-main"><strong className="ws-code">{key}</strong><div className="history-meta"><span>来源：知识范围绑定或历史任务</span></div></div>
            <div className="history-actions"><button className="btn btn--secondary btn--sm" type="button" onClick={() => setAgentForm({ agent_key: key, name: '', role_key: activeRoles[0]?.role_key ?? '', description: '' })}>纳管</button></div>
          </div>)}
        </section>}
      </>}

      <Toast message={state.toast} />
    </main>
  </>
}

/** 员工配置编辑区：提示词 / 模型 / 温度 / 工具白名单 / 记忆策略 / 治理字段。 */
function AgentConfigEditor({
  name,
  agentKey,
  config,
  form,
  loading,
  saving,
  error,
  modelKeys,
  toolCatalog,
  candidateError,
  onReloadCandidates,
  onChange,
  onSave,
  onClose,
}: {
  name: string
  agentKey: string
  config: AgentConfig | null
  form: AgentConfigForm | null
  loading: boolean
  saving: boolean
  error: DirectoryErrorShape | null
  /** P2c-4：模型候选键（`null` = 候选不可用 ⇒ 回落自由文本）。 */
  modelKeys: string[] | null
  /** P2c-4：工具目录 + 保存闸门（`null` = 候选不可用 ⇒ 回落自由文本）。 */
  toolCatalog: ToolCatalog | null
  candidateError: DirectoryErrorShape | null
  onReloadCandidates: () => void
  onChange: (form: AgentConfigForm) => void
  onSave: () => void
  onClose: () => void
}) {
  const toolOptions = form ? buildToolOptions(toolCatalog, form.tool_allowlist) : []
  const blockedTools = toolOptions.filter((option) => !option.selectable && form?.tool_allowlist.includes(option.key))
  return (
    <div className="ws-row ws-row--config">
      <div className="ws-row-main">
        <strong>{name} · 配置</strong>
        <div className="history-meta">
          <span className="ws-code">{agentKey}</span>
          <span>仅超级管理员可读写</span>
          {config?.updated_at && <span>更新于 {formatLocalTime(config.updated_at)}</span>}
        </div>

        {loading && <div className="loading-state" role="status"><span className="loading-dot" />正在读取配置…</div>}

        {error && <div className="notice notice-error" role="alert"><div><strong>{config ? '配置未保存' : '配置读取失败'}</strong><p>{error.message}</p></div></div>}

        {!loading && !form && !error && <div className="empty-state"><strong>暂无配置</strong><span>服务端没有返回该员工的配置。</span></div>}

        {form && (
          <div className="ws-form">
            <label className="ws-field ws-field--wide">
              系统提示词
              <textarea
                aria-label="系统提示词"
                value={form.system_prompt}
                rows={6}
                maxLength={MAX_SYSTEM_PROMPT_LENGTH}
                onChange={(event) => onChange({ ...form, system_prompt: event.target.value })}
              />
              <small className="ws-field-hint">最多 {MAX_SYSTEM_PROMPT_LENGTH} 字；写着「忽略审批」「绕过审批」这类指令的提示词会被拒绝。</small>
              <small className="ws-counter">{form.system_prompt.length} / {MAX_SYSTEM_PROMPT_LENGTH}</small>
            </label>

            <label className="ws-field">
              模型键
              {modelKeys ? (
                <>
                  <select aria-label="模型键" value={form.model_key} onChange={(event) => onChange({ ...form, model_key: event.target.value })}>
                    <option value="">{modelKeys.length === 0 ? MODEL_EMPTY_LABEL : `（默认模型）`}</option>
                    {modelKeys.map((key) => <option value={key} key={key}>{key}</option>)}
                    {form.model_key.trim() !== '' && !modelKeys.includes(form.model_key) && (
                      <option value={form.model_key} disabled>
                        {form.model_key}（不可用：{MODEL_NOT_REGISTERED_REASON}）
                      </option>
                    )}
                  </select>
                  <small className="ws-field-hint">
                    {modelKeys.length === 0
                      ? '本部署没有登记可选的模型键（模型由部署配置决定）：只能用默认模型；留空即默认。'
                      : `可选 ${modelKeys.length} 个，来自本部署已登记的模型键；不在其中的键保存时会被拒绝。`}
                  </small>
                </>
              ) : (
                <>
                  <input aria-label="模型键" value={form.model_key} placeholder="须为本部署已登记的模型键" onChange={(event) => onChange({ ...form, model_key: event.target.value })} />
                  <small className="ws-field-hint">
                    暂时读不到可选的模型清单（{candidateError?.message ?? '读取失败'}）⇒ 已改为手动填写；
                    {form.model_key.trim() === '' ? `当前为「${EMPTY_MODEL_KEY_LABEL}」。` : '不在已登记清单里的键保存时会被拒绝。'}
                  </small>
                </>
              )}
            </label>

            <label className="ws-field">
              温度
              <input aria-label="温度" type="number" min={0} max={2} step={0.05} value={form.temperature} onChange={(event) => onChange({ ...form, temperature: event.target.value })} />
              <small className="ws-field-hint">取值范围 0.00–2.00，步进 0.05。</small>
            </label>

            <fieldset className="ws-field ws-field--wide ws-fieldset">
              <legend>工具白名单</legend>
              {toolCatalog ? (
                <>
                  <div className="ws-tool-list" role="group" aria-label="工具白名单多选">
                    {toolOptions.map((option) => {
                      const checked = form.tool_allowlist.includes(option.key)
                      return (
                        <label className={`ws-check ws-tool-option ${option.selectable ? '' : 'is-disabled'}`} key={option.key}>
                          <input
                            type="checkbox"
                            aria-label={`工具 ${option.key}`}
                            checked={checked}
                            disabled={!option.selectable}
                            onChange={(event) => onChange({
                              ...form,
                              tool_allowlist: event.target.checked
                                ? [...form.tool_allowlist, option.key].sort()
                                : form.tool_allowlist.filter((item) => item !== option.key),
                            })}
                          />
                          <span>{toolOptionLabel(option)}</span>
                          {!option.selectable && <small className="ws-field-hint">{option.reason}</small>}
                        </label>
                      )
                    })}
                  </div>
                  <small className="ws-field-hint">
                    勾选项来自「执行工具清单」；能保存哪些以「规划器工具白名单」为准——
                    不在其中的工具已灰显并给出原因，保存时仍会被校验拒绝。
                  </small>
                  {blockedTools.length > 0 && (
                    <div className="notice" role="status">
                      <div>
                        <strong>当前配置含不可用工具（{blockedTools.length} 项）</strong>
                        <p>这些工具当前不可勾选，直接保存会被拒绝。</p>
                      </div>
                      <button
                        className="text-action"
                        type="button"
                        onClick={() => onChange({
                          ...form,
                          tool_allowlist: form.tool_allowlist.filter(
                            (item) => !blockedTools.some((option) => option.key === item),
                          ),
                        })}
                      >
                        移除不可用工具
                      </button>
                    </div>
                  )}
                </>
              ) : (
                <>
                  <input
                    aria-label="工具白名单"
                    value={form.tool_allowlist.join(', ')}
                    placeholder="逗号分隔；留空表示不使用任何工具"
                    onChange={(event) => onChange({
                      ...form,
                      tool_allowlist: event.target.value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean),
                    })}
                  />
                  <small className="ws-field-hint">
                    暂时读不到工具清单（{candidateError?.message ?? '读取失败'}）⇒ 已改为手动填写；不在白名单里的工具保存时会被拒绝。
                  </small>
                </>
              )}
            </fieldset>

            <label className="ws-field">
              短期记忆
              <span className="ws-check">
                <input aria-label="启用短期记忆" type="checkbox" checked={form.short_term_enabled} onChange={(event) => onChange({ ...form, short_term_enabled: event.target.checked })} />
                启用
              </span>
            </label>

            <label className="ws-field">
              短期记忆保留轮数
              <input aria-label="短期记忆保留轮数" type="number" min={0} max={MAX_SHORT_TERM_TURNS} step={1} value={form.short_term_turns} disabled={!form.short_term_enabled} onChange={(event) => onChange({ ...form, short_term_turns: event.target.value })} />
              <small className="ws-field-hint">0–{MAX_SHORT_TERM_TURNS} 轮。</small>
            </label>

            <label className="ws-field">
              自治等级
              <select aria-label="自治等级" value={form.autonomy_level} onChange={(event) => onChange({ ...form, autonomy_level: event.target.value })}>
                {AUTONOMY_LEVELS.map((level) => (
                  <option value={level} key={level}>{AUTONOMY_LEVEL_LABELS[level]}（{level}）</option>
                ))}
              </select>
            </label>

            {form.autonomy_level === 'full_auto' && (
              <div className="notice" role="status">
                <div><strong>免批是特权，不是默认</strong><p>{FULL_AUTO_NOTICE}</p></div>
              </div>
            )}

            <label className="ws-field">
              风险阈值
              <select aria-label="风险阈值" value={form.risk_threshold} onChange={(event) => onChange({ ...form, risk_threshold: event.target.value })}>
                {Object.entries(RISK_THRESHOLD_LABELS).map(([value, label]) => <option value={value} key={value}>{label}（{value}）</option>)}
              </select>
            </label>

            <label className="ws-field">
              审批超时（分钟）
              <input aria-label="审批超时（分钟）" type="number" min={MIN_APPROVAL_TIMEOUT_MINUTES} max={MAX_APPROVAL_TIMEOUT_MINUTES} step={1} value={form.approval_timeout_minutes} onChange={(event) => onChange({ ...form, approval_timeout_minutes: event.target.value })} />
              <small className="ws-field-hint">{MIN_APPROVAL_TIMEOUT_MINUTES}–{MAX_APPROVAL_TIMEOUT_MINUTES} 分钟。</small>
            </label>

            <label className="ws-field">
              每日预算（元）
              <input aria-label="每日预算（元）" type="number" min={0} step={0.01} value={form.daily_budget_yuan} onChange={(event) => onChange({ ...form, daily_budget_yuan: event.target.value })} />
              <small className="ws-field-hint">按元填写，保存时换算为整数分（金额一律以分为单位记录，避免小数误差）。</small>
            </label>

            <div className="ws-field ws-field--wide">
              <span>自治等级说明</span>
              <ul className="ws-hints">
                {AUTONOMY_LEVELS.map((level) => (
                  <li key={level}><strong>{AUTONOMY_LEVEL_LABELS[level]}</strong>（{level}）：{AUTONOMY_LEVEL_HINTS[level]}</li>
                ))}
              </ul>
              <small className="ws-field-hint">自治等级只决定「是否需要人批」，不决定「是否绕开权限判定」：免批的员工也不能做操作者本人无权做的事。</small>
            </div>
          </div>
        )}
      </div>

      <div className="history-actions">
        <button className="btn btn--primary" type="button" disabled={saving || !form} onClick={onSave}>保存配置</button>
        <button className="btn btn--secondary" type="button" onClick={onClose}>收起</button>
      </div>
    </div>
  )
}
