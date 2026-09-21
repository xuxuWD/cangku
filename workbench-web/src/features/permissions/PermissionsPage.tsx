/**
 * 权限配置（第 6 轮）—— 把占位页换成**可用的知识范围授权面**。
 *
 * 三块：① 角色知识范围 ② 数字员工知识范围 ③ 最近变更（只读）。
 * 四态：加载 / 空 / 错误（可重试）/ 无权限；**无权限时整页只呈现无权限态，不渲染任何编辑控件**。
 *
 * 纪律：
 *  - 本页**只做呈现**：隐藏 / 禁用 / 无权限态都只是体验，真正的判定在服务端（每个请求都会再判一次）；
 *  - 角色 / 数字员工的**创建与启停**不在这里（属「数字员工设置」），本页只**消费**目录状态；
 *    未纳管的标识写入会被服务端 `409` 拒绝，界面据此提示"请先在「数字员工设置」中纳管"；
 *  - 写成功后才重新取数（不本地猜结果）；写失败就地呈现、抽屉不关闭、不假装成功。
 */
import { useMemo, useState } from 'react'
import { Alert, Space } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { PageContainer, PermissionGuard } from '../../components'
import type { ContentStateKind } from '../../components'
import { SAMPLE_DATA_BADGE, panelStateOfError } from '../../utils/serviceKit'
import { tokens } from '../../theme/tokens'
import { AuditPanel } from './components/AuditPanel'
import { ScopeDrawer } from './components/ScopeDrawer'
import type { ScopeDrawerError } from './components/ScopeDrawer'
import { ScopePanel } from './components/ScopePanel'
import {
  AGENT_EMPTY_NOTE,
  AUDIT_EMPTY_NOTE,
  AUDIT_LIMIT,
  CONNECTED_DESCRIPTION,
  CONNECTED_NOTICE,
  ROLE_EMPTY_NOTE,
  SAMPLE_DESCRIPTION,
  ScopeWriteError,
  WRITE_FAILURE_HINT,
  fetchAgentScopes,
  fetchAudits,
  fetchRoleScopes,
  isConnected,
  listKnowledgeBases,
  saveScopeBinding,
} from './services/permissionsService'
import type { CandidateView, ScopeRow } from './types'

type PanelViewState = ContentStateKind | 'ready'

/** 取数结果 → 四态：`forbidden`（无权限）与其它失败分开。 */
function panelState(query: { isPending: boolean; isError: boolean; error: unknown }): PanelViewState {
  if (query.isPending) return 'loading'
  if (query.isError) return panelStateOfError(query.error)
  return 'ready'
}

/** 各块的非就绪文案（唯一来源在此，组件不另写一套）。 */
const STATE_TEXT = {
  role: {
    empty: ROLE_EMPTY_NOTE,
    error: '岗位知识范围加载失败，请稍后重试。',
    forbidden: '无权限查看知识范围：只有超级管理员可以调整知识库范围。',
  },
  agent: {
    empty: AGENT_EMPTY_NOTE,
    error: '数字员工知识范围加载失败，请稍后重试。',
    forbidden: '无权限查看知识范围：只有超级管理员可以调整知识库范围。',
  },
  audit: {
    empty: AUDIT_EMPTY_NOTE,
    error: '变更记录加载失败，请稍后重试。',
    forbidden: '无权限查看变更记录：只有超级管理员可以查看。',
  },
} as const

/** 就绪态的说明不需要文案（返回 undefined）。 */
function stateText(kind: keyof typeof STATE_TEXT, state: PanelViewState): string | undefined {
  if (state === 'ready' || state === 'loading') return undefined
  return STATE_TEXT[kind][state]
}

/**
 * 块级说明文案：**空态必须解释"为什么空"**（来自 `STATE_TEXT[kind].empty`）。
 * `isEmpty` 表示"就绪但一行都没有" —— 那种情况由组件降级为空态，文案同样必须给出原因。
 */
function panelDescription(
  kind: keyof typeof STATE_TEXT,
  state: PanelViewState,
  isEmpty: boolean,
): string | undefined {
  if (state === 'loading') return undefined
  if (state === 'empty') return STATE_TEXT[kind].empty
  const text = stateText(kind, state)
  if (text) return text
  return isEmpty ? STATE_TEXT[kind].empty : undefined
}

/** 表格区域（hooks 都在这里；权限门在外层，避免条件调用 hooks）。 */
function PermissionsBoard() {
  const queryClient = useQueryClient()
  const [target, setTarget] = useState<ScopeRow | null>(null)
  const [writeError, setWriteError] = useState<ScopeDrawerError | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  /** 是否已接真实数据：决定顶部标识与文案（样例与真实**互斥**，不允许含糊）。 */
  const connected = isConnected()

  const roles = useQuery({ queryKey: ['permissions', 'role-scopes'], queryFn: () => fetchRoleScopes() })
  const agents = useQuery({ queryKey: ['permissions', 'agent-scopes'], queryFn: () => fetchAgentScopes() })
  const audits = useQuery({
    queryKey: ['permissions', 'audits'],
    queryFn: () => fetchAudits(AUDIT_LIMIT),
  })

  // 候选真源（第 15 轮）：只读的知识库清单。**打开抽屉时才请求**（契约：不做缓存，一次即可）；
  // 清单没取到时后端会降级并给 `note`，界面据此如实提示（**绝不**读成"没有知识库"）。
  const bases = useQuery({
    queryKey: ['permissions', 'knowledge-bases'],
    queryFn: () => listKnowledgeBases(),
    enabled: target !== null,
  })

  const candidates: CandidateView = useMemo(() => {
    if (target === null) return { state: 'ready', items: [], note: null, upstreamAvailable: false }
    if (bases.isPending) return { state: 'loading', items: [], note: null, upstreamAvailable: false }
    if (bases.isError || !bases.data) {
      return { state: 'error', items: [], note: null, upstreamAvailable: false }
    }
    return {
      state: 'ready',
      items: bases.data.items,
      note: bases.data.note,
      upstreamAvailable: bases.data.upstream_available,
    }
  }, [target, bases.isPending, bases.isError, bases.data])

  const roleState = panelState(roles)
  const agentState = panelState(agents)
  const auditState = panelState(audits)
  const roleRows = roles.data?.rows ?? []
  const agentRows = agents.data?.rows ?? []
  const auditItems = audits.data?.items ?? []

  const openEditor = (row: ScopeRow) => {
    setWriteError(null)
    setNotice(null)
    setTarget(row)
  }

  const handleSubmit = async (ids: string[]) => {
    const row = target
    if (!row) return
    setWriteError(null)
    setNotice(null)
    try {
      const result = await saveScopeBinding({
        binding_type: row.binding_type,
        binding_key: row.binding_key,
        knowledge_base_ids: ids,
      })
      // 只有确认受理后才关闭抽屉；失败路径见 catch（抽屉留在原地）
      setTarget(null)
      if (result.written) {
        // 数量取自**服务端回读值**；拿不到回读值就**不说数量**（不本地猜结果）
        const count = result.binding?.knowledge_base_ids.length
        setNotice(
          count === undefined
            ? result.note
            : `${result.note}「${row.name}」当前可见 ${count} 个知识库。`,
        )
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: ['permissions', row.binding_type === 'role' ? 'role-scopes' : 'agent-scopes'],
          }),
          queryClient.invalidateQueries({ queryKey: ['permissions', 'audits'] }),
        ])
      } else {
        // 样例模式：没有写入任何数据，也就没有可刷新的服务端变化（如实说明，不假装已保存）
        setNotice(result.note)
      }
    } catch (error) {
      const message =
        error instanceof Error && error.message.length > 0 ? error.message : WRITE_FAILURE_HINT.failed
      setWriteError({
        message,
        hint: error instanceof ScopeWriteError ? WRITE_FAILURE_HINT[error.kind] : WRITE_FAILURE_HINT.failed,
      })
    }
  }

  return (
    <Space direction="vertical" size={tokens.spacing.lg} style={{ width: '100%' }}>
      {connected ? (
        <Alert type="info" showIcon message={CONNECTED_NOTICE} description={CONNECTED_DESCRIPTION} />
      ) : (
        <Alert type="warning" showIcon message={SAMPLE_DATA_BADGE} description={SAMPLE_DESCRIPTION} />
      )}
      {notice && <Alert type="info" showIcon message={notice} />}

      <ScopePanel
        title="角色知识范围"
        description="岗位能检索到的知识库范围；标识需先在「数字员工设置」中纳管才能调整。"
        keyColumnTitle="岗位标识"
        rows={roleRows}
        state={roleState}
        stateDescription={panelDescription('role', roleState, roleRows.length === 0)}
        onRetry={() => void roles.refetch()}
        onEdit={openEditor}
      />

      <ScopePanel
        title="数字员工知识范围"
        description="数字员工能检索到的知识库范围；范围不会超过使用者的权限。"
        keyColumnTitle="员工标识"
        rows={agentRows}
        state={agentState}
        stateDescription={panelDescription('agent', agentState, agentRows.length === 0)}
        onRetry={() => void agents.refetch()}
        onEdit={openEditor}
      />

      <AuditPanel
        items={auditItems}
        state={auditState}
        stateDescription={panelDescription('audit', auditState, auditItems.length === 0)}
        onRetry={() => void audits.refetch()}
      />

      <ScopeDrawer
        open={target !== null}
        target={target}
        candidates={candidates}
        error={writeError}
        onClose={() => {
          setTarget(null)
          setWriteError(null)
        }}
        onSubmit={handleSubmit}
      />
    </Space>
  )
}

export function PermissionsPage() {
  return (
    <PageContainer
      title="权限配置"
      description="为岗位与数字员工配置可见的知识库范围；每次变更都会留下记录，仅超级管理员可调整。"
    >
      {/* 无权限时渲染"无权限态（原因 + 申请入口）"，不请求数据、也不渲染任何编辑控件 */}
      <PermissionGuard capability="permission.manage">
        <PermissionsBoard />
      </PermissionGuard>
    </PageContainer>
  )
}