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
 * 候选知识库标识 = **所有已加载绑定**（角色块 ∪ 数字员工块）与**变更记录**里出现过的标识，
 * 去重后排序；界面再允许**手动录入**新标识（后端无枚举接口，见契约 §4）。
 */
export function collectCandidates(
  rows: readonly ScopeRow[],
  audits: readonly KnowledgeAuditEntry[],
): string[] {
  const ids = new Set<string>()
  for (const row of rows) for (const id of row.knowledge_base_ids) ids.add(id)
  for (const audit of audits) {
    for (const id of audit.old_knowledge_base_ids) ids.add(id)
    for (const id of audit.new_knowledge_base_ids) ids.add(id)
  }
  return [...ids].sort()
}