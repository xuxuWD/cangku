/**
 * 「审计日志」模块类型（第 10 轮）。
 *
 * 命名口径：**逐字沿用后端 `AuditRecordView` 的键**（`app/main.py`）——
 * `record_id / action / actor_id / target_type / target_id / phone_masked / detail / occurred_at`。
 * 与本模块契约 `docs/contracts/audit-log-api.md` **逐字一致**（改一处必须同时改另一处）。
 *
 * 唯一权威在别处：权限口径 = `permission-matrix.md` §3「审计：查询」行（`employee` ⚠️仅本人相关）；
 * 后端契约真源 = `docs/api-contract.md`「审计查询」节。
 */

/** 审计记录（后端 `AuditRecordView`）。 */
export interface AuditRecord {
  record_id: string
  /** 动作码（受控枚举来自后端 `AuditAction`；界面**按码值原样呈现**，不编造中文名）。 */
  action: string
  /** 操作者标识（不透明账号标识，非手机号）。 */
  actor_id: string | null
  target_type: string | null
  target_id: string | null
  /** 掩码手机号（写入侧已脱敏；无则为 `null`）。 */
  phone_masked: string | null
  /** 明细（写入侧已按白名单核准 + 脱敏）。 */
  detail: Record<string, unknown>
  occurred_at: string
}

/** 审计列表信封（后端 `AuditListView`，**必须分页**）。 */
export interface AuditPage {
  /** `true` = 开发期样例（界面必须显示「示例数据（未接后端）」）；`false` = 服务端真实数据。 */
  sample: boolean
  items: AuditRecord[]
  total: number
  limit: number
  offset: number
}

/** 查询条件（字段与后端 query 参数逐字一致；空串/空数组 = 不传该条件）。 */
export interface AuditQuery {
  /** 动作码可多选 ⇒ 服务端按重复 query 解析。 */
  actions: string[]
  target_type?: string
  target_id?: string
  /** **仅"本租户全量"档可传**；`employee` 由服务端强制为本人（传他人 ⇒ 403）。 */
  actor_id?: string
  /** ISO 8601 **带时区**（一律 `toISOString()` 的 `Z` 形态；naive ⇒ 服务端 422）。 */
  since?: string
  until?: string
}

/** 分页参数（服务端语义，不在前端切片）。 */
export interface AuditPageParams {
  limit: number
  offset: number
}

/** 明细的展示条目（键值对；**值只做字符串化，绝不当 HTML 渲染**）。 */
export interface DetailEntry {
  key: string
  value: string
}

/**
 * `detail` → 稳定排序的键值对列表。
 *
 * - 键按字典序（同一记录多次渲染顺序一致，便于核对）；
 * - 值：字符串原样；其余（数字 / 布尔 / `null` / 对象 / 数组）走 `JSON.stringify`（**不美化、不解释**）；
 * - **不截断、不省略**：明细本就受写入侧白名单约束，界面不做二次创作。
 */
export function detailEntries(detail: Record<string, unknown> | null | undefined): DetailEntry[] {
  if (!detail) return []
  return Object.keys(detail)
    .sort()
    .map((key) => {
      const raw = detail[key]
      return {
        key,
        value: typeof raw === 'string' ? raw : (JSON.stringify(raw) ?? String(raw)),
      }
    })
}

/** 动作目录（后端 `AuditActionListView`；**单一来源 = 后端枚举**，前端不复制）。 */
export interface AuditActionCatalog {
  sample: boolean
  items: string[]
  total: number
}

/** 筛选条件是否为空（用于空态文案区分"没有记录"与"筛选没有命中"）。 */
export function isBlankQuery(query: AuditQuery): boolean {
  return (
    query.actions.length === 0 &&
    !query.target_type &&
    !query.target_id &&
    !query.actor_id &&
    !query.since &&
    !query.until
  )
}