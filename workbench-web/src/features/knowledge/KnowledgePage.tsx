/**
 * 知识库（第 7 轮）—— 把占位页换成**可用的知识治理台 + 检索入口**。
 *
 * 一页四块：① 治理指标 ② 文档列表（含登记） ③ 可检索文档（含到期扫描） ④ 知识检索。
 * 四态：加载 / 空 / 错误（可重试）/ 无权限；**无权限时整页只呈现无权限态，不请求数据、不渲染任何编辑控件**。
 *
 * 纪律：
 *  - 本页**只做呈现**：隐藏 / 禁用 / 无权限态都只是体验，真正的判定在服务端（每个请求都会再判一次）；
 *  - 动作按契约 §2 的**合法前置状态**启用（`archived` 为终态）；不合法一律**禁用 + 给原因**，不静默隐藏；
 *  - 写成功后才重新取数，且提示只用**服务端回读值**（不本地猜结果）；
 *  - 写失败就地呈现、抽屉不关闭、**不假装成功**；
 *  - 检索的 `empty_whitelist` / `no_binding` / `no_hits` / 「服务未接入」**四种情形分开呈现**。
 */
import { useState } from 'react'
import { Alert, Button, Space } from 'antd'
import { DangerConfirm, PageContainer, PermissionGuard } from '../../components'
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
  forbidden: '无权限查看文档列表：只有超级管理员可以管理知识库。',
}
const METRICS_STATE_TEXT: Record<Exclude<ContentStateKind, 'loading'>, string> = {
  empty: DOCUMENTS_EMPTY_NOTE,
  error: '治理指标加载失败，请稍后重试。',
  forbidden: '无权限查看治理指标：只有超级管理员可以查看。',
}
const ELIGIBLE_STATE_TEXT: Record<Exclude<ContentStateKind, 'loading'>, string> = {
  empty: ELIGIBLE_EMPTY_NOTE,
  error: '可检索清单加载失败，请稍后重试。',
  forbidden: '无权限查看可检索清单：只有超级管理员可以查看。',
}

/** 无权限原因（与契约 §5 引用同族文案）。 */
export const PERMISSION_REASON =
  '无权限管理知识库：只有超级管理员可以登记、发布、归档、复核与检索知识文档。'

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

/** 表格区域（hooks 都在这里；权限门在外层，避免条件调用 hooks）。 */
function KnowledgeBoard() {
  /** 是否已接真实数据：决定顶部标识与文案（样例与真实**互斥**，不允许含糊）。 */
  const connected = isConnected()

  const docs = usePanelData(() => fetchDocuments(), EMPTY_DOCS)
  const metrics = usePanelData(() => fetchMetrics(), EMPTY_METRICS)
  const eligible = usePanelData(() => fetchEligible(), EMPTY_ELIGIBLE)

  const [registerOpen, setRegisterOpen] = useState(false)
  const [registerError, setRegisterError] = useState<RegisterDrawerError | null>(null)
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

  const handleRegister = async (input: RegisterInput) => {
    setRegisterError(null)
    setNotice(null)
    setActionError(null)
    try {
      const result = await registerDocument(input)
      setRegisterOpen(false)
      if (result.written && result.doc) {
        // 提示只用**服务端回读值**（标题与状态都取自响应）
        setNotice(`已登记：「${result.doc.title}」（当前状态：${statusLabel(result.doc.status)}）。`)
        refreshAll()
      } else {
        // 样例模式：没有写入任何数据，也就没有可刷新的服务端变化（如实说明，不假装已保存）
        setNotice(result.note)
      }
    } catch (error) {
      // 失败就地呈现、抽屉留在原地（不关抽屉、不假装成功）
      setRegisterError({ message: messageOf(error), hint: failureHint(error) })
    }
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
        <div style={{ marginBottom: tokens.spacing.sm }}>
          <Button type="primary" onClick={() => setRegisterOpen(true)}>
            登记文档
          </Button>
        </div>
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

      <RegisterDrawer
        open={registerOpen}
        error={registerError}
        onClose={() => {
          setRegisterOpen(false)
          setRegisterError(null)
        }}
        onSubmit={handleRegister}
      />

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

export function KnowledgePage() {
  return (
    <PageContainer
      title="知识库"
      description="登记知识文档并管理其发布、复核与归档；可检索范围由已发布文档决定，检索范围按岗位或数字员工解析。"
    >
      {/* 无权限时渲染"无权限态（原因 + 申请入口）"，不请求数据、也不渲染任何编辑控件 */}
      <PermissionGuard capability="knowledge.manage" reason={PERMISSION_REASON}>
        <KnowledgeBoard />
      </PermissionGuard>
    </PageContainer>
  )
}