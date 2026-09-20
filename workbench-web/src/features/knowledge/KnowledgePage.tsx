/**
 * 知识库（第 7 轮建立 · **2026-09-19 按矩阵 §3 分视图**）。
 *
 * 一页四块：① 治理指标 ② 文档列表（含登记） ③ 可检索文档（含到期扫描） ④ 知识检索。
 * 四态：加载 / 空 / 错误（可重试）/ 无权限。
 *
 * **视图按能力分流**（P0 修复：实现回到 `permission-matrix.md` §3「知识」四行）：
 *  - `knowledge.manage`（ceo / super_admin）⇒ **治理台**：四块齐备，含发布 / 归档 / 复核与治理读；
 *  - `knowledge.register` / `knowledge.search`（employee / department_lead）⇒ **员工视图**：
 *    可登记、可按**本人角色**检索；治理三块明确「无权限」且**不请求任何数据**（不伪造空态）；
 *  - 都没有（`customer_admin`）⇒ 整页无权限态 + 原因。
 *
 * 纪律：
 *  - 本页**只做呈现**：隐藏 / 禁用 / 无权限态都只是体验，真正的判定在服务端（每个请求都会再判一次）；
 *  - 动作按契约 §2 的**合法前置状态**启用（`archived` 为终态）；不合法一律**禁用 + 给原因**，不静默隐藏；
 *  - 写成功后才重新取数，且提示只用**服务端回读值**（不本地猜结果）；
 *  - 写失败就地呈现、抽屉不关闭、**不假装成功**；
 *  - 检索的 `empty_whitelist` / `no_binding` / `no_hits` / 「服务未接入」**四种情形分开呈现**。
 */
import { useState } from 'react'
import { Alert, Button, Space, Typography } from 'antd'
import { hasCapability, useSession } from '../../app/session'
import type { Role } from '../../app/session'
import { ContentState, DangerConfirm, PageContainer } from '../../components'
import type { ContentStateKind } from '../../components'
import { usePanelData } from '../../utils/panelData'
import { SAMPLE_DATA_BADGE } from '../../utils/serviceKit'
import { tokens } from '../../theme/tokens'
import { DocumentPanel } from './components/DocumentPanel'
import { EligiblePanel } from './components/EligiblePanel'
import { MetricsPanel } from './components/MetricsPanel'
import { RegisterDrawer } from './components/RegisterDrawer'
import type { RegisterDrawerError } from './components/RegisterDrawer'
import { SearchPanel } from './components/SearchPanel'
import {
  CONNECTED_DESCRIPTION,
  CONNECTED_NOTICE,
  DOCUMENTS_EMPTY_NOTE,
  ELIGIBLE_EMPTY_NOTE,
  KnowledgeError,
  MOCK_SCAN_NOTE,
  SAMPLE_DESCRIPTION,
  WRITE_FAILURE_HINT,
  archiveDocument,
  fetchDocuments,
  fetchEligible,
  fetchMetrics,
  isConnected,
  publishDocument,
  registerDocument,
  reviewDocument,
  runReviewScan,
  truncationNote,
} from './services/knowledgeService'
import { DOC_ACTION_DONE_LABEL, KNOWLEDGE_STATUS_LABEL, UNKNOWN_STATUS_TEXT, reviewApprovedValue } from './types'
import type { DocAction, DocumentPage, DocumentStatus, EligiblePage, KnowledgeDoc, MetricsPage, RegisterInput } from './types'

const EMPTY_DOCS: DocumentPage = { sample: true, items: [], total: 0, limit: 0, offset: 0 }
const EMPTY_METRICS: MetricsPage = {
  sample: true,
  metrics: { published: 0, needs_review: 0, archived: 0, total: 0, freshness_ratio: 0 },
}
const EMPTY_ELIGIBLE: EligiblePage = { sample: true, items: [], total: 0 }

/** 各块的非就绪文案（唯一来源在此，组件不另写一套）。 */
const DOCS_STATE_TEXT: Record<Exclude<ContentStateKind, 'loading'>, string> = {
  empty: DOCUMENTS_EMPTY_NOTE,
  error: '文档列表加载失败，请稍后重试。',
  forbidden: '无权限查看文档列表：只有企业负责人与超级管理员可以查看。',
}
const METRICS_STATE_TEXT: Record<Exclude<ContentStateKind, 'loading'>, string> = {
  empty: DOCUMENTS_EMPTY_NOTE,
  error: '治理指标加载失败，请稍后重试。',
  forbidden: '无权限查看治理指标：只有企业负责人与超级管理员可以查看。',
}
const ELIGIBLE_STATE_TEXT: Record<Exclude<ContentStateKind, 'loading'>, string> = {
  empty: ELIGIBLE_EMPTY_NOTE,
  error: '可检索清单加载失败，请稍后重试。',
  forbidden: '无权限查看可检索清单：只有企业负责人与超级管理员可以查看。',
}

/**
 * 无权限原因（`customer_admin` 等无任何知识能力的角色）。
 * 措辞逐条对应 `permission-matrix.md` §3「知识」四行，不夸大也不含糊。
 */
export const PERMISSION_REASON =
  '知识库不向客户管理员开放：登记与检索面向员工、部门负责人、企业负责人与超级管理员；发布、归档、复核与治理指标仅企业负责人与超级管理员可用。'

/** 员工视图里治理三块的说明（**不请求数据**、也不静默隐藏）。 */
export const GOVERNANCE_ONLY_BLOCK_NOTE =
  '该项属于知识治理面，仅企业负责人与超级管理员可用；你当前角色可以使用上方「登记文档」与下方「知识检索」。'

/** 状态标签文案（未知状态不误标）。 */
function statusLabel(status: DocumentStatus): string {
  return status === 'unknown' ? UNKNOWN_STATUS_TEXT : KNOWLEDGE_STATUS_LABEL[status]
}

function stateText(
  table: Record<Exclude<ContentStateKind, 'loading'>, string>,
  state: ContentStateKind | 'ready',
): string | undefined {
  if (state === 'ready' || state === 'loading') return undefined
  return table[state]
}

/** 写失败的分类提示（`not_configured` 不会出现在写路径上）。 */
function failureHint(error: unknown): string {
  if (error instanceof KnowledgeError && error.kind !== 'not_configured') {
    return WRITE_FAILURE_HINT[error.kind]
  }
  return WRITE_FAILURE_HINT.failed
}

function messageOf(error: unknown): string {
  return error instanceof Error && error.message.length > 0 ? error.message : WRITE_FAILURE_HINT.failed
}

/**
 * 「登记文档」块（治理台与员工视图**共用**；差异只在受理后要不要刷新治理读）。
 * 成功只用**服务端回读值**提示；失败就地呈现、抽屉不关闭、不假装成功。
 */
function RegisterBlock({ onRegistered }: { onRegistered?: () => void }) {
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<RegisterDrawerError | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const handleRegister = async (input: RegisterInput) => {
    setError(null)
    setNotice(null)
    try {
      const result = await registerDocument(input)
      setOpen(false)
      if (result.written && result.doc) {
        // 提示只用**服务端回读值**（标题与状态都取自响应）
        setNotice(`已登记：「${result.doc.title}」（当前状态：${statusLabel(result.doc.status)}）。`)
        onRegistered?.()
      } else {
        // 样例模式：没有写入任何数据，也就没有可刷新的服务端变化（如实说明，不假装已保存）
        setNotice(result.note)
      }
    } catch (caught) {
      // 失败就地呈现、抽屉留在原地（不关抽屉、不假装成功）
      setError({ message: messageOf(caught), hint: failureHint(caught) })
    }
  }

  return (
    <>
      {notice && <Alert type="info" showIcon message={notice} />}
      <div style={{ marginBottom: tokens.spacing.sm }}>
        <Button type="primary" onClick={() => setOpen(true)}>
          登记文档
        </Button>
      </div>
      <RegisterDrawer
        open={open}
        error={error}
        onClose={() => {
          setOpen(false)
          setError(null)
        }}
        onSubmit={handleRegister}
      />
    </>
  )
}

/** 治理面限定块：**只给说明，不发任何请求**（无权读的块不伪造空态，也不静默隐藏）。 */
function GovernanceOnlyBlock({ title }: { title: string }) {
  return (
    <div>
      <Typography.Title level={3}>{title}</Typography.Title>
      <ContentState state="forbidden" description={GOVERNANCE_ONLY_BLOCK_NOTE} boxed={false} />
    </div>
  )
}

/** 治理台（`knowledge.manage`：ceo / super_admin）。 */
function KnowledgeBoard() {
  /** 是否已接真实数据：决定顶部标识与文案（样例与真实**互斥**，不允许含糊）。 */
  const connected = isConnected()

  const docs = usePanelData(() => fetchDocuments(), EMPTY_DOCS)
  const metrics = usePanelData(() => fetchMetrics(), EMPTY_METRICS)
  const eligible = usePanelData(() => fetchEligible(), EMPTY_ELIGIBLE)

  const [notice, setNotice] = useState<string | null>(null)
  const [actionError, setActionError] = useState<{ message: string; hint: string } | null>(null)
  const [pending, setPending] = useState<{ document_id: string; action: DocAction } | null>(null)
  const [archiveTarget, setArchiveTarget] = useState<KnowledgeDoc | null>(null)
  const [scanPending, setScanPending] = useState(false)
  const [scanNote, setScanNote] = useState<string | null>(null)

  /** 写成功后才重新取数（不本地猜结果）。 */
  const refreshAll = () => {
    docs.reload()
    metrics.reload()
    eligible.reload()
  }

  const runAction = async (action: Exclude<DocAction, 'archive'>, doc: KnowledgeDoc) => {
    setNotice(null)
    setActionError(null)
    setPending({ document_id: doc.document_id, action })
    try {
      const result =
        action === 'publish'
          ? await publishDocument(doc.document_id)
          : await reviewDocument(doc.document_id, reviewApprovedValue(action))
      if (result.written && result.doc) {
        setNotice(
          `${DOC_ACTION_DONE_LABEL[action]}：「${result.doc.title}」（当前状态：${statusLabel(result.doc.status)}）。`,
        )
        refreshAll()
      } else {
        setNotice(result.note)
      }
    } catch (error) {
      setActionError({ message: `未能完成操作：${messageOf(error)}`, hint: failureHint(error) })
    } finally {
      setPending(null)
    }
  }

  const handleAction = (action: DocAction, doc: KnowledgeDoc) => {
    // 归档是终态（不可恢复）⇒ 先二次确认；其余动作直接提交
    if (action === 'archive') {
      setArchiveTarget(doc)
      return
    }
    void runAction(action, doc)
  }

  const handleArchiveConfirmed = async () => {
    const target = archiveTarget
    setArchiveTarget(null)
    if (!target) return
    setNotice(null)
    setActionError(null)
    setPending({ document_id: target.document_id, action: 'archive' })
    try {
      const result = await archiveDocument(target.document_id)
      if (result.written && result.doc) {
        setNotice(
          `${DOC_ACTION_DONE_LABEL.archive}：「${result.doc.title}」（当前状态：${statusLabel(result.doc.status)}）。`,
        )
        refreshAll()
      } else {
        setNotice(result.note)
      }
    } catch (error) {
      setActionError({ message: `未能完成操作：${messageOf(error)}`, hint: failureHint(error) })
    } finally {
      setPending(null)
    }
  }

  const handleScan = async () => {
    setScanNote(null)
    setScanPending(true)
    try {
      const result = await runReviewScan()
      if (result.sample) {
        // 样例模式：没有请求服务端，因此如实说明"没有改变任何文档"（不假装扫过）
        setScanNote(MOCK_SCAN_NOTE || '本次扫描没有改变任何文档。')
      } else {
        setScanNote(`扫描完成：${result.reviewed_due} 篇文档被置为「待复核」。`)
        refreshAll()
      }
    } catch (error) {
      setScanNote(`扫描未完成：${messageOf(error)}本次没有改变任何文档。`)
    } finally {
      setScanPending(false)
    }
  }

  // 就绪但一行没有 ⇒ 该块进入"空"态，并由本页给出「为什么空」的说明
  const docsState: ContentStateKind | 'ready' =
    docs.state === 'ready' && docs.data.items.length === 0 ? 'empty' : docs.state
  const metricsState: ContentStateKind | 'ready' = metrics.state
  const eligibleState: ContentStateKind | 'ready' =
    eligible.state === 'ready' && eligible.data.items.length === 0 ? 'empty' : eligible.state

  return (
    <Space direction="vertical" size={tokens.spacing.lg} style={{ width: '100%' }}>
      {connected ? (
        <Alert type="info" showIcon message={CONNECTED_NOTICE} description={CONNECTED_DESCRIPTION} />
      ) : (
        <Alert type="warning" showIcon message={SAMPLE_DATA_BADGE} description={SAMPLE_DESCRIPTION} />
      )}

      {notice && <Alert type="info" showIcon message={notice} />}
      {actionError && (
        <Alert type="error" showIcon message={actionError.message} description={actionError.hint} />
      )}

      <MetricsPanel
        metrics={metrics.data.metrics}
        state={metricsState}
        stateDescription={stateText(METRICS_STATE_TEXT, metricsState)}
        onRetry={metrics.reload}
      />

      <div>
        <RegisterBlock onRegistered={refreshAll} />
        <DocumentPanel
          docs={docs.data.items}
          state={docsState}
          stateDescription={stateText(DOCS_STATE_TEXT, docsState)}
          onRetry={docs.reload}
          onAction={handleAction}
          truncationNote={truncationNote(docs.data.total, docs.data.items.length)}
          pending={pending}
        />
      </div>

      <EligiblePanel
        items={eligible.data.items}
        state={eligibleState}
        stateDescription={stateText(ELIGIBLE_STATE_TEXT, eligibleState)}
        onRetry={eligible.reload}
        onScan={() => void handleScan()}
        scanPending={scanPending}
        scanNote={scanNote}
      />

      <SearchPanel />

      <DangerConfirm
        open={archiveTarget !== null}
        title={`归档「${archiveTarget?.title ?? ''}」？`}
        description="归档后该文档不再进入可检索范围，且归档是终态（不可恢复、不可再发布）。本条记录不会被删除。"
        confirmWord="归档"
        confirmText="确认归档"
        onConfirm={handleArchiveConfirmed}
        onCancel={() => setArchiveTarget(null)}
      />
    </Space>
  )
}

/**
 * 员工视图（`knowledge.register` / `knowledge.search`：employee / department_lead）。
 *
 * 与治理台的三点差异：① 不做治理读（那三块由后端 403，故界面**直接说明原因、不发请求**）；
 * ② 检索**自限于本人角色**（`fixedRoleKey`）；③ 登记成功后无需刷新治理读。
 */
function KnowledgeMemberView({ role }: { role: Role }) {
  const connected = isConnected()

  return (
    <Space direction="vertical" size={tokens.spacing.lg} style={{ width: '100%' }}>
      {connected ? (
        <Alert type="info" showIcon message={CONNECTED_NOTICE} description={CONNECTED_DESCRIPTION} />
      ) : (
        <Alert type="warning" showIcon message={SAMPLE_DATA_BADGE} description={SAMPLE_DESCRIPTION} />
      )}

      <div>
        <RegisterBlock />
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          登记后以「草稿」存在；发布由企业负责人或超级管理员完成，发布后才进入可检索范围。
        </Typography.Paragraph>
      </div>

      <SearchPanel fixedRoleKey={role} />

      <GovernanceOnlyBlock title="治理指标" />
      <GovernanceOnlyBlock title="文档列表" />
      <GovernanceOnlyBlock title="可检索文档" />
    </Space>
  )
}

export function KnowledgePage() {
  const role = useSession((state) => state.role)
  const canManage = hasCapability(role, 'knowledge.manage')
  const canRegister = hasCapability(role, 'knowledge.register')
  const canSearch = hasCapability(role, 'knowledge.search')

  const description = canManage
    ? '登记知识文档并管理其发布、复核与归档；可检索范围由已发布文档决定，检索范围按岗位或数字员工解析。'
    : '登记知识文档并按本人角色检索；发布、归档、复核与治理指标由企业负责人或超级管理员负责。'

  return (
    <PageContainer title="知识库" description={description}>
      {canManage ? (
        <KnowledgeBoard />
      ) : canRegister || canSearch ? (
        role ? (
          <KnowledgeMemberView role={role} />
        ) : null
      ) : (
        /* 无任何知识能力（如 customer_admin）：整页无权限态 + 原因，不请求数据、不渲染编辑控件 */
        <ContentState state="forbidden" description={PERMISSION_REASON} />
      )}
    </PageContainer>
  )
}
