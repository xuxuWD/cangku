import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AppShell, type AppView } from '../../app/AppShell'
import { FilledIcon } from '../../components/FilledIcon'
import { NoticeBanner } from '../../components/NoticeBanner'
import { ObjectSelect } from '../../components/ObjectSelect'
import { SaveButton } from '../../components/SaveButton'
import { SegmentedControl } from '../../components/SegmentedControl'
import { Toast } from '../../components/Toast'
import { getKnowledgeAccess, getKnowledgeAudits, saveKnowledgeAccess } from './api'
import { AuditTimeline } from './AuditTimeline'
import { initialKnowledgeState, createIdempotencyKey } from './state'
import { KNOWLEDGE_BASES, type ApiErrorShape, type KnowledgeAudit, type KnowledgeState, type SubjectType } from './types'
import { KnowledgeScopeRow } from './KnowledgeScopeRow'
import { SoundPreference } from './SoundPreference'
import { playUiSound, type UiSound } from './sound'

const subjects = {
  role: [{ key: 'content-operator', label: '自媒体运营岗' }, { key: 'ceo', label: 'CEO 岗' }, { key: 'vibe-coding', label: 'Vibe Coding 岗' }],
  agent: [{ key: 'content-writer', label: '内容创作数字员工' }, { key: 'geo-analyst', label: 'GEO 分析数字员工' }],
}

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

  useEffect(() => { void load('role', 'content-operator') }, [load])
  useEffect(() => {
    if (!confirmClear) return
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setConfirmClear(false) }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [confirmClear])

  const currentSubject = options.find((item) => item.key === state.subjectKey) || options[0]
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

  if (state.loading) return <AppShell activeView="knowledge" onNavigate={onNavigate}><main className="main-content"><div className="loading-state" aria-live="polite"><span className="loading-dot" />正在读取知识权限...</div></main></AppShell>

  return <AppShell activeView="knowledge" onNavigate={onNavigate}>
    <main className="main-content">
      <div className="page-head"><div><div className="eyebrow">资料访问范围</div><h1 className="page-title">知识权限管理</h1><p className="page-desc">选择这个岗位和它的数字员工可以使用的资料。未授权的内容不会被读取。</p></div><div className="actions"><button className="button" type="button" disabled={!canEdit} onClick={clear}>清空选择</button><SaveButton saving={state.saving} disabled={!canSave || isUnauthorized || !state.bindingLoaded} onClick={() => void save()} /></div></div>
      <div className="controls"><SegmentedControl value={state.subjectType} onChange={(value) => void load(value, subjects[value][0].key)} /><ObjectSelect value={state.subjectKey} options={options} onChange={(key) => void load(state.subjectType, key)} /><span className="role-note">{state.subjectType === 'role' ? '内容中心 · 6 名员工' : `所属岗位：${currentSubject.label}`}</span></div>
      {statusNotice}
      <section className={`knowledge-panel ${isUnauthorized ? 'panel-locked' : ''}`} aria-busy={state.saving}>
        <div className="panel-header"><h2>可以使用的知识库</h2><span>{state.selectedIds.length ? `已选择 ${state.selectedIds.length} 个` : '暂未授权'}</span></div>
        {isUnauthorized ? <div className="empty-state locked-state"><strong>当前账号无法读取知识范围</strong><span>请联系超级管理员开通配置权限。</span></div> : !state.bindingLoaded ? <div className="empty-state"><strong>当前对象的权限暂时读不到</strong><span>检查网络后重新尝试，当前页面不会修改已有配置。</span><button className="text-action" type="button" onClick={retryLoad}>重新读取</button></div> : state.selectedIds.length === 0 && <div className="empty-state">当前对象还没有授权知识库，请按需要选择。</div>}
        {state.bindingLoaded && !isUnauthorized && KNOWLEDGE_BASES.map((item) => <KnowledgeScopeRow key={item.id} item={item} enabled={state.selectedIds.includes(item.id)} disabled={!canEdit} onToggle={() => toggle(item.id)} />)}
      </section>
      <NoticeBanner title="敏感资料提醒">GEO 项目资料仅在绑定项目内可见，不能跨项目查看；所有引用都会保留在操作记录中。</NoticeBanner>
      <div className="audit-latest"><div className="audit-label">最近一次调整</div><div className="audit-copy"><b>操作记录</b>　权限变更会记录岗位、范围和操作人</div><button className="text-action" type="button">查看记录</button></div>
    </main>
    <aside className="audit-panel"><AuditTimeline audits={state.audits as KnowledgeAudit[]} loading={state.auditsLoading} error={state.auditError} onRetry={() => void refreshAudits()} /><SoundPreference enabled={sound} onChange={setSound} /></aside>
    <Toast message={state.toast} actionLabel={clearSnapshot ? '撤销' : undefined} onAction={clearSnapshot ? undoClear : undefined} />
    {confirmClear && <div className="modal-backdrop" role="presentation" onMouseDown={() => setConfirmClear(false)}><section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="clear-dialog-title" onMouseDown={(event) => event.stopPropagation()}><div className="modal-icon"><FilledIcon name="warning" label="注意" /></div><h2 id="clear-dialog-title">确认清空已选范围？</h2><p>这会取消「{currentSubject.label}」当前选择的 {state.selectedIds.length} 个知识库。清空只会先保存在本地，点击“保存调整”后才会生效。</p><div className="modal-actions"><button className="button" type="button" onClick={() => setConfirmClear(false)}>保留当前选择</button><button className="button danger" type="button" onClick={confirmClearSelection}>清空并继续</button></div></section></div>}
  </AppShell>
}
