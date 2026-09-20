/**
 * 「Skill & MCP」适配层 —— 本模块**唯一**的接线点（页面与组件都不认识 URL）。
 *
 * 第 8 轮实测（2026-09-20 真机 `127.0.0.1:18112` + 真库，超管 `13600000001` / 员工 `13600000002`）：
 *  - 读：`GET /api/v1/skills`（`status` 可选、`limit` 1–200、`offset`；**分页**）、
 *        `GET /api/v1/skills/{skill_key}/versions/{version}/content`（详情正文）；
 *  - 写：`POST /api/v1/skills`（**幂等**：同 `skill_key@version` 返回既有记录；
 *        请求体 `extra="forbid"`）、
 *        `POST …/{version}/review?approved=<bool>`（**`approved` 走 query 且必填**）、
 *        `POST …/{version}/enable`、`POST …/{version}/disable`（均幂等）；
 *  - **实测门禁**：`employee` 复核 / 启用 / 停用一律 `403`；`ceo` 与 `super_admin` 可复核 / 启停
 *        （2026-09-20 对齐矩阵 §3 后；此前 `ceo` 也被拒，属实现窄于矩阵的缺口，本轮已修）；
 *        提交对四个业务角色开放，`customer_admin` 一律 `403`；
 *  - **详情正文**：本人或管理员可见，他人未审包按 `404`（不暴露存在性）。
 *
 * **MCP 侧后端零实现**（`app/` 内无任何 MCP 端点）⇒ 本适配层**不提供任何 MCP 请求**，
 * 页面如实呈现「尚未接入」，**不伪造服务器 / 工具清单**（契约 §3 末行 / §4）。
 *
 * 纪律（改这个文件前先读）：
 *  ① 样例数据只在**开发模式**存在（`import.meta.env.DEV`）⇒ 生产构建里整块被摇掉；
 *  ② `http` 分支**必须抛错或返回真实数据**，不得静默返回空数组冒充"真的没有内容"；
 *  ③ 写失败必须分类（`forbidden` / `conflict` / `invalid` / `not_found` / `failed`）并保留
 *     请求层已 sanitize 的文案，界面据此**就地呈现**且**不假装成功**；成功只用**服务端回读值**提示；
 *  ④ 前端**不代算** `content_sha256`、**不代判** `allowed_tools` 合法性、**不代判**语义版本 ——
 *     这三条是服务端校验（契约 §1 实测文案），界面只做易用性提示；
 *  ⑤ 未来接线只改这一个文件。
 */
import { ApiError, request } from '../../../api/client'
import { SAMPLE_DATA_BADGE, ServiceError, resolveServiceMode } from '../../../utils/serviceKit'
import type {
  SkillContent,
  SkillContentOutcome,
  SkillPage,
  SkillSummary,
  SkillWriteOutcome,
  SubmitSkillInput,
} from '../types'
import { DEFAULT_SOURCE_KEY, parseSkillStatus } from '../types'

export type ServiceMode = 'mock' | 'http'

/** 适配层唯一模式开关（与其它模块同一份解析规则：显式变量 > 开发期 `mock` > 生产 `http`）。 */
export let mode: ServiceMode = resolveServiceMode()

/** 切换模式（开发 / 测试用）。 */
export function setServiceMode(next: ServiceMode): void {
  mode = next
}

/** 当前是否为样例模式（用函数取，避免页面读到模块级绑定的快照值）。 */
export function isConnected(): boolean {
  return mode === 'http'
}

/** 列表单页上限（后端 `limit` 上限 200）。 */
export const SKILLS_LIMIT = 200

const SKILLS_PATH = '/api/v1/skills'

/** 写成功的如实说明（后端已确认写入；回读值取自服务端响应）。 */
export const WRITE_OK_NOTE = '操作已受理。'

/**
 * 样例模式下的写说明（**只在开发期存在**，生产构建里为空串）。
 * 措辞避免开发术语，只说"没有写入任何数据"。
 */
export const MOCK_WRITE_NOTE: string = import.meta.env.DEV
  ? '当前为示例数据（未接后端），本次操作没有写入任何数据。'
  : ''

/** 已接入真实数据时的说明（与「示例数据」标识互斥，避免含糊）。 */
export const CONNECTED_NOTICE = '已接入真实数据'
export const CONNECTED_DESCRIPTION =
  '技能包列表与正文均来自服务端；提交、审核与启用 / 停用每次都会记录，且以服务端判定为准。'

/** 样例模式下的说明（**只在开发期存在** ⇒ 生产构建里为空串，"示例数据"字样不进产物）。 */
export const SAMPLE_DESCRIPTION: string = import.meta.env.DEV
  ? '本页技能包列表为示例数据，不会写入任何数据。'
  : ''

/**
 * 「技能包列表」空态：**解释为什么空**，而不是显示"0 条"。
 * 两种角色口径分开：管理视图（全租户）与员工视图（本人可见范围）。
 */
export const SKILLS_EMPTY_NOTE = '本租户还没有提交任何技能包；提交后需经企业负责人或超级管理员审核。'
export const MY_SKILLS_EMPTY_NOTE =
  '你还没有提交过技能包；提交后由企业负责人或超级管理员审核，审核通过并启用后才会生效。'

/** 列表被单页上限截断时的如实说明（不把残缺列表当全量）。 */
export function truncationNote(total: number, shown: number): string | undefined {
  return total > shown ? `共 ${total} 个技能包，本页只展示前 ${shown} 个。` : undefined
}

/** 详情正文在样例模式下的如实说明（**不伪造正文**）。 */
export const MOCK_CONTENT_NOTE: string = import.meta.env.DEV
  ? '示例数据（未接后端）：本条没有可展示的正文。'
  : '本条没有可展示的正文。'

/** 正文缺失（后端允许空正文落库的历史记录）时的如实文案。 */
export const EMPTY_CONTENT_NOTE = '该技能包没有登记正文。'

/**
 * MCP 侧如实说明（**后端零实现**，不伪造服务器 / 工具清单）。
 * 与契约 §3 / §4 逐字对齐。
 */
export const MCP_NOT_CONNECTED_TITLE = 'MCP 服务器注册中心尚未接入'
export const MCP_NOT_CONNECTED_NOTE =
  'MCP 服务器与工具的注册、连通性测试、开关在当前版本中还没有后端实现；本页不展示、也不伪造任何服务器或工具清单。'

/** 写失败分类：界面据此给出**不同的**可懂原因，而不是笼统的"操作失败"。 */
export type SkillFailure = 'forbidden' | 'conflict' | 'invalid' | 'not_found' | 'failed'

/**
 * 适配层错误（只带可读文案与分类，**不含**凭据 / 内部地址 / 堆栈）。
 *
 * 文案来源：请求层优先取服务端 `detail`（仅当它是"短且干净"的字符串），
 * 否则回落本地固定文案 —— 因此 `422`（`detail` 是数组）**不会**把校验 JSON 渲染到界面。
 */
export class SkillError extends ServiceError {
  readonly kind: SkillFailure

  constructor(message: string, kind: SkillFailure) {
    super(message, kind === 'forbidden' ? 'forbidden' : 'failed')
    this.name = 'SkillError'
    this.kind = kind
  }
}

/** 写失败的就地提示（**必须说明"没有写入任何数据"**，不允许含糊成"操作失败"）。 */
export const WRITE_FAILURE_HINT: Record<SkillFailure, string> = {
  forbidden: '本次没有写入任何数据；如需复核 / 启用 / 停用技能包，请使用企业负责人或超级管理员账号。',
  conflict: '本次没有写入任何数据；该操作与技能包当前状态冲突，请刷新后重试。',
  invalid: '本次没有写入任何数据；请检查填写内容（版本号、许可、工具键、正文与指纹）后重试。',
  not_found: '本次没有写入任何数据；该技能包不存在或当前不可见。',
  failed: '本次没有写入任何数据，请稍后重试。',
}

/** 取数失败 → 界面四态：`forbidden` 单独区分（无权限），其余按"加载失败"。 */
export function panelStateOfError(error: unknown): 'error' | 'forbidden' {
  if (error instanceof SkillError && error.kind === 'forbidden') return 'forbidden'
  if (error instanceof ServiceError && error.failure === 'forbidden') return 'forbidden'
  return 'error'
}

/** 读路径失败 → 模块错误（非请求层错误原样抛出，不吞异常）。 */
function readError(error: unknown): never {
  if (error instanceof ApiError) {
    if (error.failure === 'forbidden') throw new SkillError(error.message, 'forbidden')
    if (error.failure === 'not_found') throw new SkillError(error.message, 'not_found')
    throw new SkillError(error.message, 'failed')
  }
  throw error
}

/** 写路径失败 → 模块错误（分类见 `SkillFailure`）。 */
function writeError(error: unknown): never {
  if (error instanceof ApiError) {
    if (error.failure === 'forbidden') throw new SkillError(error.message, 'forbidden')
    if (error.failure === 'not_found') throw new SkillError(error.message, 'not_found')
    if (error.failure === 'conflict') throw new SkillError(error.message, 'conflict')
    if (error.status === 422) throw new SkillError(error.message, 'invalid')
    throw new SkillError(error.message, 'failed')
  }
  throw error
}

/** 形状不符统一文案（**绝不臆测**成"没有内容"）。 */
const SHAPE_ERROR = '服务端返回的内容形状不符合约定，本模块不展示该内容。'

/** 单条技能视图 → 模块类型；缺必需键即抛错（不静默跳过、不编造字段）。 */
function toSkill(raw: unknown): SkillSummary {
  const value = raw as Partial<SkillSummary> | null
  if (!value || typeof value.skill_key !== 'string' || typeof value.version !== 'string') {
    throw new SkillError(SHAPE_ERROR, 'failed')
  }
  return {
    skill_key: value.skill_key,
    version: value.version,
    name: typeof value.name === 'string' ? value.name : '',
    description: typeof value.description === 'string' ? value.description : '',
    license: typeof value.license === 'string' ? value.license : '',
    allowed_tools: Array.isArray(value.allowed_tools)
      ? value.allowed_tools.filter((item): item is string => typeof item === 'string')
      : [],
    status: parseSkillStatus(typeof value.status === 'string' ? value.status : ''),
    source_key: typeof value.source_key === 'string' ? value.source_key : '',
    owner_id: typeof value.owner_id === 'string' ? value.owner_id : '',
    reviewed_by: typeof value.reviewed_by === 'string' ? value.reviewed_by : null,
    created_at: value.created_at ?? null,
    updated_at: value.updated_at ?? null,
  }
}

/** 列表视图 → `SkillSummary[]`（`items` 不是数组即抛错）。 */
function toSkills(raw: unknown): SkillSummary[] {
  const items = (raw as { items?: unknown } | null)?.items
  if (!Array.isArray(items)) throw new SkillError(SHAPE_ERROR, 'failed')
  return items.map(toSkill)
}

/** 正文视图 → 受控结构（必需键缺失即抛错，不编造正文）。 */
function toContent(raw: unknown): SkillContent {
  const value = raw as Partial<SkillContent> | null
  if (
    !value ||
    typeof value.skill_key !== 'string' ||
    typeof value.version !== 'string' ||
    typeof value.content_body !== 'string'
  ) {
    throw new SkillError(SHAPE_ERROR, 'failed')
  }
  return {
    skill_key: value.skill_key,
    version: value.version,
    content_body: value.content_body,
    content_sha256: typeof value.content_sha256 === 'string' ? value.content_sha256 : '',
  }
}

/** 技能列表（`status` 可选、**分页**）。 */
export async function fetchSkills(
  params: { status?: string; limit?: number; offset?: number } = {},
  fetchImpl?: typeof fetch,
): Promise<SkillPage> {
  if (mode === 'mock') {
    const items = MOCK_SKILLS
    return { sample: true, items, total: items.length, limit: SKILLS_LIMIT, offset: 0 }
  }

  try {
    const raw = await request<unknown>(SKILLS_PATH, {
      query: {
        ...(params.status ? { status: params.status } : {}),
        limit: params.limit ?? SKILLS_LIMIT,
        offset: params.offset ?? 0,
      },
      fetchImpl,
    })
    const view = raw as { total?: unknown; limit?: unknown; offset?: unknown }
    const items = toSkills(raw)
    return {
      sample: false,
      items,
      total: typeof view.total === 'number' ? view.total : items.length,
      limit: typeof view.limit === 'number' ? view.limit : SKILLS_LIMIT,
      offset: typeof view.offset === 'number' ? view.offset : 0,
    }
  } catch (error) {
    readError(error)
  }
}

/** 提交技能包（申报，不生效；后端幂等）。成功返回**服务端回读值**。 */
export async function submitSkill(input: SubmitSkillInput, fetchImpl?: typeof fetch): Promise<SkillWriteOutcome> {
  if (mode === 'mock') {
    // 样例模式没有服务端 ⇒ 不伪造回读值，且明确"没有写入任何数据"
    return { skill: null, written: false, note: MOCK_WRITE_NOTE }
  }

  try {
    const raw = await request<unknown>(SKILLS_PATH, {
      method: 'POST',
      // 后端 `extra="forbid"`：请求体只放后端允许的九个键
      body: {
        skill_key: input.skill_key,
        version: input.version,
        name: input.name,
        description: input.description,
        license: input.license,
        allowed_tools: input.allowed_tools,
        source_key: input.source_key || DEFAULT_SOURCE_KEY,
        content_sha256: input.content_sha256,
        content_body: input.content_body,
      },
      fetchImpl,
    })
    return { skill: toSkill(raw), written: true, note: WRITE_OK_NOTE }
  } catch (error) {
    writeError(error)
  }
}

/** 单个版本的动作 / 详情路径（`content` 是详情读路径，其余三个是写动作）。 */
function versionPath(
  skill_key: string,
  version: string,
  action: 'review' | 'enable' | 'disable' | 'content',
): string {
  return `${SKILLS_PATH}/${encodeURIComponent(skill_key)}/versions/${encodeURIComponent(version)}/${action}`
}

/** 审核（`approved=true` → 已审核；`false` → 已退回）。提交人自审由服务端拒绝（`403`）。 */
export async function reviewSkill(
  skill_key: string,
  version: string,
  approved: boolean,
  fetchImpl?: typeof fetch,
): Promise<SkillWriteOutcome> {
  return writeVersionAction(versionPath(skill_key, version, 'review'), { query: { approved } }, fetchImpl)
}

/** 启用（`approved` / `disabled` → `enabled`；已启用幂等）。 */
export async function enableSkill(
  skill_key: string,
  version: string,
  fetchImpl?: typeof fetch,
): Promise<SkillWriteOutcome> {
  return writeVersionAction(versionPath(skill_key, version, 'enable'), {}, fetchImpl)
}

/** 停用（`enabled` → `disabled`；已停用幂等）。 */
export async function disableSkill(
  skill_key: string,
  version: string,
  fetchImpl?: typeof fetch,
): Promise<SkillWriteOutcome> {
  return writeVersionAction(versionPath(skill_key, version, 'disable'), {}, fetchImpl)
}

/** 三个版本级动作共用的写路径（样例模式只在开发期落到"没有写入任何数据"）。 */
async function writeVersionAction(
  path: string,
  extra: { query?: Record<string, string | number | boolean> },
  fetchImpl?: typeof fetch,
): Promise<SkillWriteOutcome> {
  if (mode === 'mock') return { skill: null, written: false, note: MOCK_WRITE_NOTE }

  try {
    const raw = await request<unknown>(path, { method: 'POST', query: extra.query, fetchImpl })
    return { skill: toSkill(raw), written: true, note: WRITE_OK_NOTE }
  } catch (error) {
    writeError(error)
  }
}

/**
 * 详情正文（按需拉取，列表不返回正文）。
 * 他人未审包按 `404`（不暴露存在性）⇒ 分类 `not_found`，界面如实说明。
 */
export async function fetchSkillContent(
  skill_key: string,
  version: string,
  fetchImpl?: typeof fetch,
): Promise<SkillContentOutcome> {
  if (mode === 'mock') return { sample: true, content: null, note: MOCK_CONTENT_NOTE }

  try {
    const raw = await request<unknown>(versionPath(skill_key, version, 'content'), { fetchImpl })
    return { sample: false, content: toContent(raw), note: '' }
  } catch (error) {
    readError(error)
  }
}

/**
 * 开发期样例数据（虚构内容，无 PII：不含手机号 / 用户 ID / 租户 ID / 密钥）。
 * **只在 `import.meta.env.DEV` 分支里存在** ⇒ 生产构建里整块被摇掉（构建后 grep 应为 0 命中）。
 * 刻意覆盖五种状态（含终态与幂等态），用于断言动作可用性与"不合法一律禁用 + 给原因"。
 */
const MOCK_SKILLS: SkillSummary[] = import.meta.env.DEV
  ? [
      {
        skill_key: 'sample-summarize',
        version: '1.0.0',
        name: '摘要助手',
        description: '生成结构化摘要',
        license: 'Apache-2.0',
        allowed_tools: ['fs.read'],
        status: 'submitted',
        source_key: 'manual',
        owner_id: '示例提交人 01',
        reviewed_by: null,
        created_at: '2026-09-20T02:00:00Z',
        updated_at: '2026-09-20T02:00:00Z',
      },
      {
        skill_key: 'sample-translate',
        version: '2.1.0',
        name: '翻译助手',
        description: '中英互译',
        license: 'MIT',
        allowed_tools: ['fs.read', 'fs.stat'],
        status: 'approved',
        source_key: 'manual',
        owner_id: '示例提交人 02',
        reviewed_by: '示例审核人 01',
        created_at: '2026-09-19T02:00:00Z',
        updated_at: '2026-09-19T03:00:00Z',
      },
      {
        skill_key: 'sample-report',
        version: '1.2.0',
        name: '周报助手',
        description: '汇总本周进展',
        license: 'BSD-3',
        allowed_tools: ['fs.read', 'cmd.run'],
        status: 'enabled',
        source_key: 'manual',
        owner_id: '示例提交人 02',
        reviewed_by: '示例审核人 01',
        created_at: '2026-09-18T02:00:00Z',
        updated_at: '2026-09-18T05:00:00Z',
      },
      {
        skill_key: 'sample-legacy',
        version: '1.0.0',
        name: '旧版助手',
        description: '已停用的历史版本',
        license: 'MIT',
        allowed_tools: ['fs.list'],
        status: 'disabled',
        source_key: 'manual',
        owner_id: '示例提交人 01',
        reviewed_by: '示例审核人 01',
        created_at: '2026-09-01T02:00:00Z',
        updated_at: '2026-09-10T02:00:00Z',
      },
      {
        skill_key: 'sample-rejected',
        version: '1.0.0',
        name: '被退回的助手',
        description: '描述含不合规内容，已退回',
        license: 'MIT',
        allowed_tools: ['fs.read'],
        status: 'rejected',
        source_key: 'manual',
        owner_id: '示例提交人 03',
        reviewed_by: '示例审核人 01',
        created_at: '2026-08-30T02:00:00Z',
        updated_at: '2026-08-31T02:00:00Z',
      },
    ]
  : []

/** 样例模式下的"示例数据"标识（供页面直接引用，避免各处另写）。 */
export { SAMPLE_DATA_BADGE }