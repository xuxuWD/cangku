import { useCallback, useEffect, useState } from 'react'
import { AppShell, type AppView } from '../../app/AppShell'
import { Toast } from '../../components/Toast'
import { createAgent, createRole, listAgents, listCandidates, listRoles, updateAgent, updateRole } from './api'
import { asDirectoryError, initialDirectoryState } from './state'
import { directoryStatusLabel, type DirectoryState } from './types'

type EditTarget = { kind: 'role' | 'agent'; key: string; name: string; description: string; role_key: string }

const EMPTY_ROLE_FORM = { role_key: '', name: '', description: '' }
const EMPTY_AGENT_FORM = { agent_key: '', name: '', role_key: '', description: '' }

export function WorkforceSettingsPage({ onNavigate }: { onNavigate?: (view: AppView) => void }) {
  const [state, setState] = useState<DirectoryState>(initialDirectoryState)
  const [roleForm, setRoleForm] = useState(EMPTY_ROLE_FORM)
  const [agentForm, setAgentForm] = useState(EMPTY_AGENT_FORM)
  const [editing, setEditing] = useState<EditTarget | null>(null)

  const load = useCallback(async () => {
    setState((old) => ({ ...old, loading: true, error: null }))
    try {
      const [roles, agents, candidates] = await Promise.all([listRoles(), listAgents(), listCandidates()])
      setState((old) => ({ ...old, roles, agents, candidates, loading: false, error: null }))
    } catch (error) {
      setState((old) => ({ ...old, loading: false, error: asDirectoryError(error) }))
    }
  }, [])

  useEffect(() => { void load() }, [load])

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

  const switchTab = (tab: DirectoryState['tab']) => { setEditing(null); setState((old) => ({ ...old, tab, formError: null })) }
  const activeRoles = state.roles.items.filter((role) => role.status === 'active')

  return <AppShell activeView="workforceSettings" onNavigate={onNavigate}>
    <main className="main-content content-history workforce-settings">
      <div className="page-head">
        <div>
          <h1 className="page-title">数字员工设置</h1>
          <p className="page-desc">维护本租户的岗位与数字员工。标识创建后不可修改；停用只影响后续挂载与指派，不撤销既有知识绑定、也不影响历史任务。仅超级管理员可读写。</p>
        </div>
        <div className="actions"><button className="button" type="button" onClick={() => void load()}>刷新</button></div>
      </div>

      <div className="toolbar">
        <div className="segment" role="tablist" aria-label="目录类型">
          <button role="tab" type="button" aria-selected={state.tab === 'roles'} className={state.tab === 'roles' ? 'active' : ''} onClick={() => switchTab('roles')}>岗位</button>
          <button role="tab" type="button" aria-selected={state.tab === 'agents'} className={state.tab === 'agents' ? 'active' : ''} onClick={() => switchTab('agents')}>数字员工</button>
        </div>
        <span className="role-note">{state.tab === 'roles' ? `共 ${state.roles.total} 个岗位` : `共 ${state.agents.total} 个数字员工`}</span>
      </div>

      {state.error && <div className="notice notice-error" role="alert"><div><strong>目录加载失败</strong><p>{state.error.message}</p></div>{state.error.retryable && <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button>}</div>}
      {!state.error && state.formError && <div className="notice notice-error" role="alert"><div><strong>保存失败</strong><p>{state.formError.message}</p></div></div>}
      {state.loading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载岗位与数字员工…</div>}

      {!state.loading && !state.error && state.tab === 'roles' && <>
        <section className="history-panel workforce-settings__panel" aria-label="新建岗位">
          <div className="panel-header"><h2>新建岗位</h2><span>标识创建后不可修改</span></div>
          <div className="ws-form">
            <label className="ws-field">岗位标识<input value={roleForm.role_key} placeholder="content-operator" onChange={(event) => setRoleForm({ ...roleForm, role_key: event.target.value })} /></label>
            <label className="ws-field">中文名<input value={roleForm.name} placeholder="自媒体运营岗" onChange={(event) => setRoleForm({ ...roleForm, name: event.target.value })} /></label>
            <label className="ws-field ws-field--wide">描述<input value={roleForm.description} placeholder="可选" onChange={(event) => setRoleForm({ ...roleForm, description: event.target.value })} /></label>
            <div className="ws-submit"><button className="button primary" type="button" disabled={state.saving} onClick={() => void submit(() => createRole(roleForm), `岗位 ${roleForm.role_key} 已创建`, () => setRoleForm(EMPTY_ROLE_FORM))}>创建岗位</button></div>
          </div>
        </section>

        <section className="history-panel workforce-settings__panel" aria-label="岗位列表">
          <div className="panel-header"><h2>岗位</h2><span>{state.roles.items.length} / {state.roles.total}</span></div>
          {state.roles.items.length === 0 && <div className="empty-state"><strong>暂无岗位</strong><span>先创建一个岗位，再把数字员工挂载到它下面。</span></div>}
          {state.roles.items.map((role) => editing?.kind === 'role' && editing.key === role.role_key
            ? <div className="ws-row" key={role.role_key}>
              <div className="ws-row-main">
                <label className="ws-field">中文名<input value={editing.name} onChange={(event) => setEditing({ ...editing, name: event.target.value })} /></label>
                <label className="ws-field ws-field--wide">描述<input value={editing.description} onChange={(event) => setEditing({ ...editing, description: event.target.value })} /></label>
                <div className="history-meta"><span className="ws-code">{role.role_key}</span><span>标识不可修改</span></div>
              </div>
              <div className="history-actions">
                <button className="button primary" type="button" disabled={state.saving} onClick={() => void submit(() => updateRole(role.role_key, { name: editing.name, description: editing.description }), `岗位 ${role.role_key} 已更新`)}>保存</button>
                <button className="button" type="button" onClick={() => setEditing(null)}>取消</button>
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
                <button className="button" type="button" onClick={() => setEditing({ kind: 'role', key: role.role_key, name: role.name, description: role.description, role_key: role.role_key })}>修改</button>
                <button className="button" type="button" disabled={state.saving} onClick={() => void submit(() => updateRole(role.role_key, { status: role.status === 'active' ? 'disabled' : 'active' }), `岗位 ${role.role_key} 已${role.status === 'active' ? '停用' : '启用'}`)}>{role.status === 'active' ? '停用' : '启用'}</button>
              </div>
            </div>)}
        </section>

        {state.candidates.roles.length > 0 && <section className="history-panel workforce-settings__panel" aria-label="未纳管岗位标识">
          <div className="panel-header"><h2>未纳管标识</h2><span>{state.candidates.roles.length} 个</span></div>
          <p className="ws-hint">这些标识已出现在知识范围绑定里，但还没有纳入目录。纳管时补一个中文名即可（标识保持不变）。</p>
          {state.candidates.roles.map((key) => <div className="ws-row" key={key}>
            <div className="ws-row-main"><strong className="ws-code">{key}</strong><div className="history-meta"><span>来源：知识范围绑定</span></div></div>
            <div className="history-actions"><button className="button" type="button" onClick={() => setRoleForm({ role_key: key, name: '', description: '' })}>纳管</button></div>
          </div>)}
        </section>}
      </>}

      {!state.loading && !state.error && state.tab === 'agents' && <>
        <section className="history-panel workforce-settings__panel" aria-label="新建数字员工">
          <div className="panel-header"><h2>新建数字员工</h2><span>必须归属一个启用的岗位</span></div>
          <div className="ws-form">
            <label className="ws-field">员工标识<input value={agentForm.agent_key} placeholder="content-writer" onChange={(event) => setAgentForm({ ...agentForm, agent_key: event.target.value })} /></label>
            <label className="ws-field">中文名<input value={agentForm.name} placeholder="内容创作数字员工" onChange={(event) => setAgentForm({ ...agentForm, name: event.target.value })} /></label>
            <label className="ws-field">所属岗位<select value={agentForm.role_key} onChange={(event) => setAgentForm({ ...agentForm, role_key: event.target.value })}><option value="">请选择岗位</option>{activeRoles.map((role) => <option key={role.role_key} value={role.role_key}>{role.name}（{role.role_key}）</option>)}</select></label>
            <label className="ws-field ws-field--wide">描述<input value={agentForm.description} placeholder="可选" onChange={(event) => setAgentForm({ ...agentForm, description: event.target.value })} /></label>
            <div className="ws-submit"><button className="button primary" type="button" disabled={state.saving} onClick={() => void submit(() => createAgent(agentForm), `数字员工 ${agentForm.agent_key} 已创建`, () => setAgentForm(EMPTY_AGENT_FORM))}>创建数字员工</button></div>
          </div>
          {activeRoles.length === 0 && <p className="ws-hint">当前没有启用中的岗位：请先在「岗位」页签创建岗位，再回来挂载数字员工。</p>}
        </section>

        <section className="history-panel workforce-settings__panel" aria-label="数字员工列表">
          <div className="panel-header"><h2>数字员工</h2><span>{state.agents.items.length} / {state.agents.total}</span></div>
          {state.agents.items.length === 0 && <div className="empty-state"><strong>暂无数字员工</strong><span>创建数字员工后需要指定它归属的岗位。</span></div>}
          {state.agents.items.map((employee) => editing?.kind === 'agent' && editing.key === employee.agent_key
            ? <div className="ws-row" key={employee.agent_key}>
              <div className="ws-row-main">
                <label className="ws-field">中文名<input value={editing.name} onChange={(event) => setEditing({ ...editing, name: event.target.value })} /></label>
                <label className="ws-field">所属岗位<select value={editing.role_key} onChange={(event) => setEditing({ ...editing, role_key: event.target.value })}>{activeRoles.map((role) => <option key={role.role_key} value={role.role_key}>{role.name}（{role.role_key}）</option>)}</select></label>
                <label className="ws-field ws-field--wide">描述<input value={editing.description} onChange={(event) => setEditing({ ...editing, description: event.target.value })} /></label>
                <div className="history-meta"><span className="ws-code">{employee.agent_key}</span><span>标识不可修改</span></div>
              </div>
              <div className="history-actions">
                <button className="button primary" type="button" disabled={state.saving} onClick={() => void submit(() => updateAgent(employee.agent_key, { name: editing.name, description: editing.description, role_key: editing.role_key }), `数字员工 ${employee.agent_key} 已更新`)}>保存</button>
                <button className="button" type="button" onClick={() => setEditing(null)}>取消</button>
              </div>
            </div>
            : <div className="ws-row" key={employee.agent_key}>
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
                <button className="button" type="button" onClick={() => setEditing({ kind: 'agent', key: employee.agent_key, name: employee.name, description: employee.description, role_key: employee.role_key })}>修改</button>
                <button className="button" type="button" disabled={state.saving} onClick={() => void submit(() => updateAgent(employee.agent_key, { status: employee.status === 'active' ? 'disabled' : 'active' }), `数字员工 ${employee.agent_key} 已${employee.status === 'active' ? '停用' : '启用'}`)}>{employee.status === 'active' ? '停用' : '启用'}</button>
              </div>
            </div>)}
        </section>

        {state.candidates.agents.length > 0 && <section className="history-panel workforce-settings__panel" aria-label="未纳管员工标识">
          <div className="panel-header"><h2>未纳管标识</h2><span>{state.candidates.agents.length} 个</span></div>
          <p className="ws-hint">这些标识出现在知识范围绑定或历史任务里，但还没有纳入目录。纳管时补一个中文名并选择所属岗位。</p>
          {state.candidates.agents.map((key) => <div className="ws-row" key={key}>
            <div className="ws-row-main"><strong className="ws-code">{key}</strong><div className="history-meta"><span>来源：知识范围绑定或历史任务</span></div></div>
            <div className="history-actions"><button className="button" type="button" onClick={() => setAgentForm({ agent_key: key, name: '', role_key: activeRoles[0]?.role_key ?? '', description: '' })}>纳管</button></div>
          </div>)}
        </section>}
      </>}

      <Toast message={state.toast} />
    </main>
  </AppShell>
}
