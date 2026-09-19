/**
 * 「知识库」模块类型（第 7 轮）。
 *
 * 命名口径：**逐字沿用 `KnowledgeDocView` 的键**（`app/main.py:3306`）——
 * `document_id / title / owner_id / status / version / source_key / last_reviewed_at /
 * review_due_at / registered_by / created_at / updated_at`（**无正文**，正文在知识服务侧）。
 * 与本模块契约 `docs/contracts/knowledge-api.md` **逐字一致**（改一处必须同时改另一处）。
 *
 * 唯一权威在别处：权限口径 = `permission-matrix.md`；知识分级 = `knowledge-acl.md`；
 * 治理语义 = `docs/superpowers/specs/2026-09-15-knowledge-governance-design.md`。
 */

/**
 * 文档状态（受控枚举）。取值来自后端状态机（真机实测：`draft / published / needs_review / archived`）。
 * `unknown` 用于后端将来新增取值时**不误标**成已知状态。
 */
export type DocumentStatus = 'draft' | 'published' | 'needs_review' | 'archived' | 'unknown'

/** 已知状态的中文标签（`unknown` 不在此表，界面另写"未定义状态"）。 */
export const KNOWLEDGE_STATUS_LABEL: Record<Exclude<DocumentStatus, 'unknown'>, string> = {
  draft: '草稿',
  published: '已发布',
  needs_review: '待复核',
  archived: '已归档',
}

/** 全站统一的"状态未知"文案（避免各处另写一套）。 */
export const UNKNOWN_STATUS_TEXT = '未定义状态'

/** 来源（`source_key`）的中文标签；未知取值**原样显示**（不编造含义）。 */
export const SOURCE_KEY_LABEL: Record<string, string> = { manual: '手工登记' }

/** 文档视图（后端 `KnowledgeDocView`）。 */
export interface KnowledgeDoc {
  document_id: string
  title: string
  /** 负责人标识（不透明账号标识，非手机号）；空串 = 尚未指定（发布会被服务端拒）。 */
  owner_id: string
  status: DocumentStatus
  version: string
  source_key: string
  last_reviewed_at: string | null
  review_due_at: string | null
  registered_by: string
  created_at: string | null
  updated_at: string | null
}

/** 文档列表 / 可检索清单信封（后端 `KnowledgeDocListResponse`）。 */
export interface DocumentPage {
  /** `true` = 开发期样例（界面必须显示「示例数据（未接后端）」）；`false` = 服务端真实数据。 */
  sample: boolean
  items: KnowledgeDoc[]
  total: number
  limit: number
  offset: number
}

/** 可检索清单信封（后端同形，`limit` 为清单上限）。 */
export interface EligiblePage {
  sample: boolean
  items: KnowledgeDoc[]
  total: number
}

/**
 * 治理指标（后端 `KnowledgeMetricsResponse`）。
 * `freshness_ratio` = `published / total`，**分母含 draft 与 archived**（真机实测口径，界面必须如实说明）。
 */
export interface GovernanceMetrics {
  published: number
  needs_review: number
  archived: number
  total: number
  freshness_ratio: number
}

export interface MetricsPage {
  sample: boolean
  metrics: GovernanceMetrics
}

/** 检索引用（后端 `KnowledgeSearchCitationView`）。 */
export interface Citation {
  citation_id: string
  content: string
  source_title: string
  knowledge_id: string
  score: number | null
}

/**
 * 空结果归因（后端 `reason`，受控枚举）：
 * `no_binding` = 该岗位/员工未绑定任何知识库；`empty_whitelist` = 守卫拦截（fail-closed）；
 * `no_hits` = 白名单非空但无命中。**三者在界面上必须分开呈现**。
 */
export type SearchReason = 'no_binding' | 'empty_whitelist' | 'no_hits' | null

export interface SearchOutcome {
  items: Citation[]
  truncated: boolean
  reason: SearchReason
}

/** 检索入参：`role_key` 与 `agent_key` **恰一**（后端模型校验）。 */
export interface SearchInput {
  query: string
  role_key?: string
  agent_key?: string
  limit?: number
}

/** 登记入参（后端 `KnowledgeDocRegisterRequest`，`extra="forbid"`）。 */
export interface RegisterInput {
  document_id: string
  title: string
  owner_id?: string
  version?: string
  source_key?: string
}

/**
 * 写路径受理结果。
 * `written === true` 表示**服务端已确认写入**，`doc` 是**服务端回读值**（不本地猜）；
 * 样例模式（无服务端）下 `written === false` 且 `doc === null` —— **绝不伪造回读值**。
 */
export interface WriteOutcome {
  doc: KnowledgeDoc | null
  written: boolean
  note: string
}

/** 到期扫描结果（后端 `{"reviewed_due": n}`，幂等）。 */
export interface ReviewScanOutcome {
  sample: boolean
  reviewed_due: number
}

/** 后端 `status` → 受控枚举；**未知取值一律落 `unknown`**，绝不误标成已知状态。 */
export function parseDocumentStatus(raw: string): DocumentStatus {
  if (raw === 'draft' || raw === 'published' || raw === 'needs_review' || raw === 'archived') return raw
  return 'unknown'
}

/** 文档上的管理动作（受状态机约束）。 */
export type DocAction = 'publish' | 'archive' | 'review_approve' | 'review_reject'

export const DOC_ACTION_LABEL: Record<DocAction, string> = {
  publish: '发布',
  archive: '归档',
  review_approve: '复核通过',
  review_reject: '复核退回',
}

/** 动作完成后的提示用语（过去式，与按钮文案区分；提示只用**服务端回读值**）。 */
export const DOC_ACTION_DONE_LABEL: Record<DocAction, string> = {
  publish: '已发布',
  archive: '已归档',
  review_approve: '复核通过',
  review_reject: '复核退回',
}

/**
 * 动作 × 前置状态的**禁用原因**（`null` = 允许执行）。
 *
 * 口径来自契约 §2「实测状态机」：`publish` 仅 `draft`；`archive` 除 `archived`（终态）外均可；
 * `review` 仅 `needs_review`。**不合法一律禁用并给原因，不静默隐藏按钮**。
 */
export function actionDisabledReason(action: DocAction, status: DocumentStatus): string | null {
  if (status === 'unknown') {
    return '该文档的状态未在界面定义，暂不能执行任何管理操作。'
  }
  if (status === 'archived') {
    return '文档已归档（终态，不可恢复），不能再发布、归档或复核。'
  }

  if (action === 'publish') {
    if (status === 'draft') return null
    if (status === 'published') return '只有草稿状态的文档可以发布；该文档已发布。'
    return '该文档等待复核，请先完成复核（通过或退回）。'
  }

  if (action === 'archive') return null

  // 复核（通过 / 退回）：只有到期待复核的文档才需要复核
  if (status === 'needs_review') return null
  return '只有到期待复核的文档才需要复核。'
}

/** 复核动作对应的 `approved` 取值（后端 `review?approved=<bool>` 必填 query）。 */
export function reviewApprovedValue(action: Extract<DocAction, 'review_approve' | 'review_reject'>): boolean {
  return action === 'review_approve'
}