import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AppView } from '../../app/AppShell'
import { Icon } from '../../components/Icon'
import { NoticeBanner } from '../../components/NoticeBanner'
import { ObjectSelect } from '../../components/ObjectSelect'
import { SaveButton } from '../../components/SaveButton'
import { SegmentedControl } from '../../components/SegmentedControl'
import { Toast } from '../../components/Toast'
import { EmptyState } from '../../components/ui/EmptyState'
import { getDirectorySubjects, getKnowledgeAccess, getKnowledgeAudits, saveKnowledgeAccess, type DirectorySubjects } from './api'
import { AuditTimeline } from './AuditTimeline'
import { initialKnowledgeState, createIdempotencyKey } from './state'
import { KNOWLEDGE_BASES, type ApiErrorShape, type KnowledgeAudit, type KnowledgeState, type SubjectType } from './types'
import { KnowledgeScopeRow } from './KnowledgeScopeRow'
import { SoundPreference } from './SoundPreference'
import { playUiSound, type UiSound } from './sound'

function asApiError(error: unknown): ApiErrorShape {
  if (typeof error === 'object' && error !== null && 'message' in error) {
    const candidate = error as Partial<ApiErrorShape>
    return { status: candidate.status || 0, message: candidate.message || '请求暂时无法完成。', retryable: candidate.retryable !== false, unauthorized: candidate.unauthorized === true }
  }
  return { status: 0, message: '服务暂时不可用，请检查网络后重新尝试。', retryable: true, unauthorized: false }
}

export function KnowledgeAccessPage({ onNavigate }: { onNavigate?: (view: AppView) => void } = {}) {
  const [state, setState] = useState<KnowledgeState>(initialKnowledgeState)
  const [sound, setSound] = useState(true)
  const [confirmClear, setConfirmClear] = useState(false)
  const [clearSnapshot, setClearSnapshot] = useState<string[] | null>(null)
  // 候选岗位/数字员工来自目录（「数字员工设置」）；为空时本页无事可做，给出明确指引。
  const [subjects, setSubjects] = useState<DirectorySubjects>({ role: [], agent: [] })
  const [subjectsLoading, setSubjectsLoading] = useState(true)
  // 目录读取失败或为空后，允许重新读取一次（真实动作，不做本地猜测）。
  const [directoryNonce, setDirectoryNonce] = useState(0)
  const subjectsInitialised = useRef(false)
  const loadSequence = useRef(0)
  const options = subjects[state.subjectType]

  const update = useCallback((patch: Partial<KnowledgeState>) => setState((old) => ({ ...old, ...patch })), [])
  const playIfEnabled = useCallback((kind: UiSound) => { if (sound) playUiSound(kind) }, [sound])

  const refreshAudits = useCallback(async () => {
    update({ auditsLoading: true, auditError: null })
    try {
      const audits = await getKnowledgeAudits()
      update({ audits, auditsLoading: false })
    } catch (error) {
      update({ auditsLoading: false, auditError: asApiError(error) })
    }
  }, [update])

  const load = useCallback(async (type: SubjectType, key: string) => {
    const requestId = ++loadSequence.current
    update({ loading: true, error: null, saveError: null, auditError: null, subjectType: type, subjectKey: key, selectedIds: [], initialIds: [], bindingLoaded: false, audits: [], auditsLoading: true, toast: null })
    const [bindingResult, auditsResult] = await Promise.allSettled([getKnowledgeAccess(type, key), getKnowledgeAudits()])
    if (requestId !== loadSequence.current) return

    if (bindingResult.status === 'fulfilled') update({ loading: false, bindingLoaded: true, selectedIds: bindingResult.value.knowledge_base_ids, initialIds: bindingResult.value.knowledge_base_ids })
    else update({ loading: false, error: asApiError(bindingResult.reason) })
    if (auditsResult.status === 'fulfilled') update({ audits: auditsResult.value, auditsLoading: false })
    else update({ auditsLoading: false, auditError: asApiError(auditsResult.reason) })
  }, [update])

  // 目录先到：候选对象是真实存在的岗位/数字员工，不再用写死清单。
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const loaded = await getDirectorySubjects()
        if (!cancelled) setSubjects(loaded)
      } catch {
        if (!cancelled) setSubjects({ role: [], agent: [] })
      } finally {
        if (!cancelled) setSubjectsLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [directoryNonce])

  const reloadDirectory = useCallback(() => {
    // 重新读取目录后要重新挑一次默认对象（否则对象列表回来了却没人去读绑定）。
    subjectsInitialised.current = false
    setSubjectsLoading(true)
    setDirectoryNonce((value) => value + 1)
  }, [])

  // 目录就绪后只挑一次默认对象：沿用当前类型里的第一个，没有就退到另一类。
  useEffect(() => {
    if (subjectsLoading || subjectsInitialised.current) return
    subjectsInitialised.current = true
    const target = subjects[state.subjectType][0] ?? subjects[state.subjectType === 'role' ? 'agent' : 'role'][0]
    if (!target) {
      // 目录为空或读取失败：仍按当前标识读一次绑定，把真实错误显示出来，而不是一直转圈。
      if (state.subjectKey) void load(state.subjectType, state.subjectKey)
      else update({ loading: false })
      return
    }
    const type: SubjectType = subjects.role.some((item) => item.key === target.key) ? 'role' : 'agent'
    void load(type, target.key)
  }, [subjectsLoading, subjects, state.subjectType, state.subjectKey, load, update])
  useEffect(() => {
    if (!confirmClear) return
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setConfirmClear(false) }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [confirmClear])

  const currentSubject = options.find((item) => item.key === state.subjectKey) || options[0]
  // 目录里没有该类对象时不能切换过去（ObjectSelect 会没有可选项）。
  const switchSubjectType = (value: SubjectType) => { const first = subjects[value][0]; if (first) void load(value, first.key) }
  const isUnauthorized = state.error?.unauthorized === true
  const canEdit = state.bindingLoaded && !isUnauthorized && !state.saving
  const canSave = state.selectedIds.join(',') !== state.initialIds.join(',')

  const toggle = (id: string) => {
    if (!canEdit) return
    update({ selectedIds: state.selectedIds.includes(id) ? state.selectedIds.filter((item) => item !== id) : [...state.selectedIds, id], saveError: null })
  }

  const clear = () => {
    if (isUnauthorized || !state.bindingLoaded) return
    if (state.selectedIds.length) setConfirmClear(true)
    else { update({ toast: '当前没有已授权的范围' }); playIfEnabled('warning') }
  }

  const confirmClearSelection = () => {
    setClearSnapshot([...state.selectedIds])
    setConfirmClear(false)
    update({ selectedIds: [], saveError: null, toast: '已清空选择，可撤销' })
    playIfEnabled('warning')
  }

  const undoClear = () => {
    if (!clearSnapshot) return
    update({ selectedIds: [...clearSnapshot], toast: '已恢复清空前的选择' })
    setClearSnapshot(null)
    playIfEnabled('success')
  }

  const save = async () => {
    if (!canSave || !canEdit) return
    const ids = [...state.selectedIds]
    const type = state.subjectType
    const key = state.subjectKey
    update({ saving: true, saveError: null })
    try {
      await saveKnowledgeAccess(type, key, ids, createIdempotencyKey(type, key, ids))
      update({ saving: false, initialIds: ids, toast: '已保存权限调整' })
      setClearSnapshot(null)
      playIfEnabled('success')
      await refreshAudits()
    } catch (error) {
      update({ saving: false, saveError: asApiError(error), toast: '保存失败，已保留本地调整' })
      playIfEnabled('error')
    }
  }

  const retryLoad = () => { void load(state.subjectType, state.subjectKey) }
  const statusNotice = useMemo(() => {
    if (state.saveError) return <NoticeBanner tone="error" title="保存失败">{state.saveError.message} <button className="text-action" type="button" onClick={() => void save()}>重新保存</button></NoticeBanner>
    if (!state.error) return null
    return <NoticeBanner tone="error" title={state.error.unauthorized ? '暂时无法配置知识权限' : '知识权限读取失败'}>{state.error.message} {state.error.retryable && <button className="text-action" type="button" onClick={retryLoad}>重新尝试</button>}</NoticeBanner>
  }, [retryLoad, save, state.error, state.saveError])

  const pageDesc = '设置这个岗位和它的数字员工可以使用哪些资料。未授权的内容不会被读取，所有调整都会记录岗位、范围与操作人。'

  if (state.loading || subjectsLoading) return <><main className="main-content t3 knowledge"><div className="loading-state" role="status" aria-live="polite"><span className="loading-dot" />正在读取知识权限...</div></main></>

  if (subjects.role.length === 0 && subjects.agent.length === 0) return <>
    <main className="main-content t3 knowledge">
      <div className="t3__intro"><p className="page-desc">{pageDesc}</p></div>
      {/* 空目录分支也保留统计条（数字为 0 是真实状态，不是错误） */}
      <div className="metrics">
        <div className="metric">
          <div className="metric__label">已开启</div>
          <div className="metric__value">0</div>
          <div className="metric__hint">还没有可配置的对象</div>
        </div>
        <div className="metric">
          <div className="metric__label">共</div>
          <div className="metric__value">{KNOWLEDGE_BASES.length}</div>
          <div className="metric__hint">系统内置的知识范围（有了对象才能逐个配置）</div>
        </div>
      </div>
      {statusNotice}
      <section className="card">
        <EmptyState illustration="list" title="还没有可配置的知识范围" text="请先在「数字员工设置」中创建岗位与数字员工，再回来配置知识范围。">
          {onNavigate && <button className="btn btn--primary btn--sm" type="button" onClick={() => onNavigate('workforceSettings')}>去数字员工设置</button>}
          <button className="btn btn--secondary btn--sm" type="button" onClick={reloadDirectory}>刷新</button>
        </EmptyState>
      </section>
    </main>
  </>

  return <>
    <main className="main-content t3 knowledge">
      <div className="t3__intro">
        <p className="page-desc">{pageDesc}</p>
        <div className="t3__actions">
          <button className="btn btn--secondary btn--sm" type="button" disabled={!canEdit} onClick={clear}>清空选择</button>
          <SaveButton saving={state.saving} disabled={!canSave || isUnauthorized || !state.bindingLoaded} onClick={() => void save()} />
        </div>
      </div>

      <div className="metrics">
        <div className="metric">
          <div className="metric__label">已开启</div>
          <div className="metric__value">{state.selectedIds.length}</div>
          <div className="metric__hint">当前对象已授权的知识范围</div>
        </div>
        <div className="metric">
          <div className="metric__label">共</div>
          <div className="metric__value">{KNOWLEDGE_BASES.length}</div>
          <div className="metric__hint">可配置的知识范围总数</div>
        </div>
      </div>

      <div className="toolbar"><SegmentedControl value={state.subjectType} onChange={switchSubjectType} /><ObjectSelect value={state.subjectKey} options={options} onChange={(key) => void load(state.subjectType, key)} /><span className="role-note">{state.subjectType === 'role' ? `共 ${subjects.role.length} 个启用中的岗位` : currentSubject ? `所属岗位：${currentSubject.role_key ?? '未设置'}` : '暂无启用中的数字员工'}</span></div>
      {statusNotice}
      <section className="card" aria-busy={state.saving}>
        <div className="card__head"><h2>可以使用的知识库</h2><span className="page-meta">{state.selectedIds.length ? `已选择 ${state.selectedIds.length} 个` : '暂未授权'}</span></div>
        {isUnauthorized && <div className="card__body"><div className="notice" role="status"><div><strong>当前账号无法读取知识范围</strong><p>请联系超级管理员开通配置权限。</p></div></div></div>}
        {!isUnauthorized && !state.bindingLoaded && <div className="card__body"><div className="notice notice-error" role="alert"><div><strong>当前对象的权限暂时读不到</strong><p>检查网络后重新尝试，当前页面不会修改已有配置。</p></div><button className="text-action" type="button" onClick={retryLoad}>重新读取</button></div></div>}
        {!isUnauthorized && state.bindingLoaded && state.selectedIds.length === 0 && <div className="card__body"><p className="page-desc">当前对象还没有授权知识库，请按需要选择。</p></div>}
        {state.bindingLoaded && !isUnauthorized && KNOWLEDGE_BASES.map((item) => <KnowledgeScopeRow key={item.id} item={item} enabled={state.selectedIds.includes(item.id)} disabled={!canEdit} onToggle={() => toggle(item.id)} />)}
      </section>
      <NoticeBanner title="敏感资料提醒">GEO 项目资料仅在绑定项目内可见，不能跨项目查看；所有引用都会保留在操作记录中。</NoticeBanner>
      <div className="audit-latest"><div className="audit-label">最近一次调整</div><div className="audit-copy"><b>操作记录</b>　权限变更会记录岗位、范围和操作人</div><button className="text-action" type="button">查看记录</button></div>
    </main>
    <aside className="audit-panel"><AuditTimeline audits={state.audits as KnowledgeAudit[]} loading={state.auditsLoading} error={state.auditError} onRetry={() => void refreshAudits()} /><SoundPreference enabled={sound} onChange={setSound} /></aside>
    <Toast message={state.toast} actionLabel={clearSnapshot ? '撤销' : undefined} onAction={clearSnapshot ? undoClear : undefined} />
    {confirmClear && <div className="modal-backdrop" role="presentation" onMouseDown={() => setConfirmClear(false)}><section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="clear-dialog-title" onMouseDown={(event) => event.stopPropagation()}><div className="modal-icon"><Icon name="warning" label="注意" /></div><h2 id="clear-dialog-title">确认清空已选范围？</h2><p>这会取消「{currentSubject.label}」当前选择的 {state.selectedIds.length} 个知识库。清空只会先保存在本地，点击“保存调整”后才会生效。</p><div className="modal-actions"><button className="button" type="button" onClick={() => setConfirmClear(false)}>保留当前选择</button><button className="button danger" type="button" onClick={confirmClearSelection}>清空并继续</button></div></section></div>}
  </>
}