/**
 * 「权限配置」模块类型（第 6 轮）。
 *
 * 命名口径：**逐字沿用后端既有字段名** —— 知识访问绑定
 * `binding_type` / `binding_key` / `knowledge_base_ids`（`app/main.py:2964` 的 `_knowledge_access_view`）；
 * 变更记录 `old_knowledge_base_ids` / `new_knowledge_base_ids` / `actor_id` / `occurred_at`（`app/main.py:3666`）；
 * 目录条目 `role_key` / `agent_key` / `name` / `status`（`JobRoleView` / `DigitalEmployeeView`）。
 *
 * 与本模块契约 `docs/contracts/permissions-api.md` **逐字一致**（改一处必须同时改另一处）。
 * 唯一权威在别处：权限口径 = `permission-matrix.md`；知识分级 = `knowledge-acl.md`。
 */

/** 绑定主体类型（后端 `binding_type` 的受控枚举，库列有 CHECK 约束）。 */
export type BindingType = 'role' | 'agent'

/** 目录条目状态（后端库列 `CHECK (status IN ('active','disabled'))`）。 */
export type DirectoryStatus = 'active' | 'disabled'

export const BINDING_TYPE_LABEL: Record<BindingType, string> = { role: '岗位', agent: '数字员工' }

export const DIRECTORY_STATUS_LABEL: Record<DirectoryStatus, string> = {
  active: '已启用',
  disabled: '已停用',
}

/** 单次提交的知识库标识上限（后端 `KnowledgeAccessUpdate.knowledge_base_ids` 的 `max_length=100`）。 */
export const MAX_KNOWLEDGE_BASE_IDS = 100

/** 知识访问绑定（`GET` / `PUT /api/v1/knowledge-access/{roles|agents}/{key}` 的响应形状）。 */
export interface KnowledgeBinding {
  binding_type: BindingType
  binding_key: string
  knowledge_base_ids: string[]
}

/** 知识访问变更记录（`GET /api/v1/knowledge-access/audits` 的数组元素）。 */
export interface KnowledgeAuditEntry {
  binding_type: BindingType
  binding_key: string
  old_knowledge_base_ids: string[]
  new_knowledge_base_ids: string[]
  /** 操作者账号标识（后端 `actor_id`，不透明标识，非手机号）。 */
  actor_id: string
  /** ISO 8601。 */
  occurred_at: string
}

/** 范围行（「角色知识范围」与「数字员工知识范围」两块共用的视图模型）。 */
export interface ScopeRow {
  binding_type: BindingType
  binding_key: string
  name: string
  status: DirectoryStatus
  /** 当前绑定的知识库标识；**空数组 = 尚未绑定**（界面如实写"尚未绑定"，不写"0 条"）。 */
  knowledge_base_ids: string[]
}

/** 一块的取数信封（`sample` 为样例硬标记，与其它模块同口径）。 */
export interface ScopePage {
  /** `true` = 开发期样例（界面必须显示「示例数据（未接后端）」）；`false` = 服务端真实数据。 */
  sample: boolean
  rows: ScopeRow[]
}

/** 变更记录信封。 */
export interface AuditPage {
  sample: boolean
  items: KnowledgeAuditEntry[]
}

/** 写路径入参（标识由目录决定，不可改）。 */
export interface ScopeWriteInput {
  binding_type: BindingType
  binding_key: string
  knowledge_base_ids: string[]
}

/**
 * 写路径受理结果。
 * `written === true` 表示**服务端已确认写入**，`binding` 是**服务端回读值**（不本地猜）；
 * 样例模式（无服务端）下 `written === false` 且 `binding === null` —— **绝不伪造回读值**。
 */
export interface ScopeWriteResult {
  binding: KnowledgeBinding | null
  written: boolean
  note: string
}

/**
 * 候选知识库标识的来源（第 15 轮起由 `GET /api/v1/knowledge/bases` 提供）：
 * - `upstream`：出现在**知识库清单**里（真源）；
 * - `binding_only`：**只在本租户绑定里出现过、清单未返回** ⇒ 「标识配错 / 库已被删」的可见化，
 *   界面据此给黄色提醒（**不阻断保存** —— 平台无权替操作者判定）。
 */
export type KnowledgeBaseOrigin = 'upstream' | 'binding_only'

/** 候选知识库（`GET /api/v1/knowledge/bases` 的 `items` 元素）。`name` 可为 `null` ⇒ 界面回落显示标识。 */
export interface KnowledgeBaseCandidate {
  knowledge_base_id: string
  name: string | null
  origin: KnowledgeBaseOrigin
}

/**
 * 候选清单信封。`upstream_available === false` ⇒ **降级**（清单没取到），此时 `note` 必带原因，
 * 且 `items` 只是"本租户已绑定过的标识"——**界面不得读成「没有知识库」**。
 */
export interface KnowledgeBaseCandidateList {
  upstream_available: boolean
  source: 'upstream' | 'local_only'
  items: KnowledgeBaseCandidate[]
  note: string | null
}

/** 抽屉用的候选视图（含加载 / 取不到两态；取不到时如实说明，**不冒充空清单**）。 */
export interface CandidateView {
  state: 'loading' | 'ready' | 'error'
  items: KnowledgeBaseCandidate[]
  /** 服务端给的降级原因（`null` = 清单正常）。 */
  note: string | null
  /** 清单是否真的取到（决定"能不能对手输值给出提醒"）。 */
  upstreamAvailable: boolean
}

/**
 * 规范化标识列表：去首尾空白、丢弃空项、**去重**（保持首次出现顺序）。
 * 前端**只做这三件事**，合法性（该库是否存在）一律以服务端为准。
 */
export function normalizeIds(ids: readonly string[]): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const raw of ids) {
    const value = raw.trim()
    if (value.length === 0 || seen.has(value)) continue
    seen.add(value)
    result.push(value)
  }
  return result
}

/**
 * 提交前校验（返回错误文案；`null` = 通过）：
 * ① 每一项都不能为空；② 去重后不超过 100 项。
 * 说明：**留空是合法输入**（表示解除全部绑定），因此不校验"列表非空"。
 */
export function validateIds(ids: readonly string[]): string | null {
  if (ids.some((raw) => raw.trim().length === 0)) {
    return '知识库标识不能为空，请删除空项后再保存。'
  }
  if (normalizeIds(ids).length > MAX_KNOWLEDGE_BASE_IDS) {
    return `最多 100 个知识库标识（当前 ${normalizeIds(ids).length} 个），请先删减到 100 项以内。`
  }
  return null
}

/**
 * 当前填写的标识里，**不在知识库清单里**的那些（界面据此给黄色提醒，**不阻断保存**）。
 *
 * 只把 `origin === 'upstream'` 的项当作"清单里真有"：`binding_only` 是后端告诉我们
 * "绑定里有、清单却没返回"的项，本身就属于要提醒的范畴。
 * 清单没取到时（`upstream_available === false`）调用方**不应**调用本函数 —— 无从判断，不能误报。
 */
export function unknownCandidateIds(
  ids: readonly string[],
  items: readonly KnowledgeBaseCandidate[],
): string[] {
  const known = new Set(
    items.filter((item) => item.origin === 'upstream').map((item) => item.knowledge_base_id),
  )
  return normalizeIds(ids).filter((id) => !known.has(id))
}