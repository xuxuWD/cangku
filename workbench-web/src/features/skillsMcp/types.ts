/**
 * 「Skill & MCP」模块类型（第 8 轮）。
 *
 * 命名口径：**逐字沿用后端 `SkillView` 的键**（`app/main.py` 的 `SkillView`）——
 * `skill_key / version / name / description / license / allowed_tools / status / source_key /
 * owner_id / reviewed_by / created_at / updated_at`（**不含正文**，正文由详情接口按需拉取）。
 * 与本模块契约 `docs/contracts/skills-mcp-api.md` **逐字一致**（改一处必须同时改另一处）。
 *
 * 唯一权威在别处：权限口径 = `permission-matrix.md` §3「技能」两行；
 * 后端契约真源 = `docs/api-contract.md`「技能（P4 技能层）」节（本模块只引用、不改写）。
 *
 * ⚠️ 三条**服务端校验**前端**不复算**（契约 §1 实测文案）：
 *  ① `version` 必须是 `major.minor.patch` 语义版本；
 *  ② `content_sha256` 必须与正文指纹一致（前端**不代算**指纹，避免与后端算法不一致造成假通过）；
 *  ③ `allowed_tools` 必须是执行工具目录内的键（界面**不提供自造键**，只做提示）。
 * 前端只做"非空 / 长度"这类易用性校验，其余一律以服务端拒绝为准并**如实呈现服务端原文**。
 */

/**
 * 技能包状态（受控枚举）。取值来自后端状态机（真机实测：
 * `submitted / approved / rejected / enabled / disabled`）。
 * `unknown` 用于后端将来新增取值时**不误标**成已知状态。
 */
export type SkillStatus = 'submitted' | 'approved' | 'rejected' | 'enabled' | 'disabled' | 'unknown'

/** 已知状态的中文标签（`unknown` 不在此表，界面另写"未定义状态"）。 */
export const SKILL_STATUS_LABEL: Record<Exclude<SkillStatus, 'unknown'>, string> = {
  submitted: '已提交',
  approved: '已审核',
  rejected: '已退回',
  enabled: '已启用',
  disabled: '已停用',
}

/** 全站统一的"状态未知"文案（避免各处另写一套）。 */
export const UNKNOWN_STATUS_TEXT = '未定义状态'

/** 许可白名单（与后端一致：`LICENSE_ALLOWLIST`），界面只提供这三项**供选择**，不放开自填。 */
export const LICENSE_OPTIONS = ['Apache-2.0', 'MIT', 'BSD-3'] as const

/** 工具目录键的**示例**（仅用于表单提示；合法集合以服务端工具目录为准，界面不代判）。 */
export const TOOL_KEY_HINT = '仅可勾选执行目录内的键；服务端会逐键校验，目录外的键会被拒绝。'

/**
 * 可选工具键（下拉**只给这些**，界面**不提供自造键** —— 契约 §1 第三条实测校验）。
 *
 * 取值来源：后端 `app/tool_execution/catalog.py` 的 `default_tool_specs()`（13 个键）。
 * ⚠️ 这是**提示集合**而非判定依据：服务端仍会逐键校验与取交集；
 * 后端新增工具键时需前端同步本表（该同步缺口在契约 §6「未验证」登记）。
 */
export const TOOL_KEY_OPTIONS: readonly string[] = [
  'fs.list',
  'fs.read',
  'fs.stat',
  'cmd.run',
  'fs.write',
  'fs.overwrite',
  'fs.delete',
  'artifact.export',
  'crm.account.search',
  'crm.account.get',
  'crm.opportunity.list',
  'crm.progress.summary',
  'crm.activity.log',
]

/** 来源（`source_key`）由**部署配置**注入白名单（`WORKBENCH_SKILL_SOURCE_ALLOWLIST`）；
 *  界面默认给出 `manual`（本机实测通过的取值），未知取值**原样显示**（不编造含义）。 */
export const SOURCE_KEY_LABEL: Record<string, string> = { manual: '手工申报' }
export const DEFAULT_SOURCE_KEY = 'manual'

/** 技能包视图（后端 `SkillView`，**不含正文**）。 */
export interface SkillSummary {
  skill_key: string
  version: string
  name: string
  description: string
  license: string
  allowed_tools: string[]
  status: SkillStatus
  source_key: string
  /** 提交人标识（不透明账号标识，非手机号）。 */
  owner_id: string
  /** 审核人标识；`null` = 尚未审核。 */
  reviewed_by: string | null
  created_at: string | null
  updated_at: string | null
}

/** 技能列表信封（后端 `SkillListResponse`，**必须是分页结果**）。 */
export interface SkillPage {
  /** `true` = 开发期样例（界面必须显示「示例数据（未接后端）」）；`false` = 服务端真实数据。 */
  sample: boolean
  items: SkillSummary[]
  total: number
  limit: number
  offset: number
}

/** 技能包正文（后端 `SkillContentResponse`，详情专用）。 */
export interface SkillContent {
  skill_key: string
  version: string
  content_body: string
  content_sha256: string
}

/** 提交入参（后端 `SkillSubmitRequest`，`extra="forbid"`：只放下面这九个键）。 */
export interface SubmitSkillInput {
  skill_key: string
  version: string
  name: string
  description: string
  license: string
  allowed_tools: string[]
  source_key: string
  content_sha256: string
  content_body: string
}

/**
 * 写路径受理结果。
 * `written === true` 表示**服务端已确认写入**，`skill` 是**服务端回读值**（不本地猜）；
 * 样例模式（无服务端）下 `written === false` 且 `skill === null` —— **绝不伪造回读值**。
 */
export interface SkillWriteOutcome {
  skill: SkillSummary | null
  written: boolean
  note: string
}

/** 详情正文读取结果（`sample` 区分样例与真实；样例模式**不伪造正文**）。 */
export interface SkillContentOutcome {
  sample: boolean
  content: SkillContent | null
  note: string
}

/** 技能包上的管理动作（受状态机约束）。 */
export type SkillAction = 'review_approve' | 'review_reject' | 'enable' | 'disable'

export const SKILL_ACTION_LABEL: Record<SkillAction, string> = {
  review_approve: '审核通过',
  review_reject: '退回',
  enable: '启用',
  disable: '停用',
}

/** 动作完成后的提示用语（过去式，与按钮文案区分；提示只用**服务端回读值**）。 */
export const SKILL_ACTION_DONE_LABEL: Record<SkillAction, string> = {
  review_approve: '已审核通过',
  review_reject: '已退回',
  enable: '已启用',
  disable: '已停用',
}

/** 后端 `status` → 受控枚举；**未知取值一律落 `unknown`**，绝不误标成已知状态。 */
export function parseSkillStatus(raw: string): SkillStatus {
  if (raw === 'submitted' || raw === 'approved' || raw === 'rejected' || raw === 'enabled' || raw === 'disabled') {
    return raw
  }
  return 'unknown'
}

/**
 * 动作 × 前置状态的**禁用原因**（`null` = 允许执行）。
 *
 * 口径来自契约 §2「真机实测状态机」：
 *  - `review`（通过 / 退回）仅 `submitted`；
 *  - `enable` 仅 `approved` / `disabled`（`enabled` 幂等，服务端原样返回 ⇒ 界面允许点击并注明幂等）；
 *  - `disable` 仅 `enabled`（`disabled` 幂等）；
 *  - `rejected` 是**终态**（三动作全部不可执行）。
 * **不合法一律禁用并给原因，不静默隐藏按钮**。
 */
export function actionDisabledReason(action: SkillAction, status: SkillStatus): string | null {
  if (status === 'unknown') {
    return '该技能包的状态未在界面定义，暂不能执行任何管理动作。'
  }
  if (status === 'rejected') {
    return '该技能包已被退回（终态）：需要修改后以新版本重新提交，不能再审核或启用。'
  }

  if (action === 'review_approve' || action === 'review_reject') {
    if (status === 'submitted') return null
    if (status === 'approved') return '该技能包已经审核通过，无需重复审核。'
    if (status === 'enabled') return '该技能包已启用；如需调整请先停用，再提交新版本。'
    return '该技能包已停用，不能再审核；如需启用请直接点击「启用」。'
  }

  if (action === 'enable') {
    if (status === 'approved' || status === 'disabled') return null
    if (status === 'enabled') return null // 幂等：服务端原样返回
    return '该技能包尚未审核通过，不能启用。'
  }

  // disable：仅 enabled 可停用（disabled 为幂等）
  if (status === 'enabled' || status === 'disabled') return null
  return '只有已启用的技能包可以停用。'
}

/** 审核动作对应的 `approved` 取值（后端 `review?approved=<bool>` 必填 query）。 */
export function reviewApprovedValue(action: Extract<SkillAction, 'review_approve' | 'review_reject'>): boolean {
  return action === 'review_approve'
}

/** 易用性校验：语义版本形如 `major.minor.patch`（**最终判定在服务端**，这里只为少一次往返）。 */
export function looksLikeSemver(value: string): boolean {
  return /^\d+\.\d+\.\d+$/.test(value.trim())
}

/** 易用性校验：指纹为 64 位十六进制的**形状检查**（前端**不代算**指纹，只查长度与字符）。 */
export function looksLikeSha256(value: string): boolean {
  return /^[0-9a-fA-F]{64}$/.test(value.trim())
}