/**
 * 「我的数字员工」适配层 —— 本模块**唯一**的接线点。
 *
 * 第 6 轮（接线批 2）实测后的接线结论：
 *  - **已接线（http 走真接口）**：
 *    ① 列表 `GET /api/v1/workforce/agents`（后端**管理目录**口径，仅 `super_admin`；其他角色 `403`）；
 *    ② 配置 `PATCH /api/v1/workforce/agents/{agent_key}`（请求体 `{name, description}`）；
 *    ③ 停用 `PATCH /api/v1/workforce/agents/{agent_key}`（请求体 `{status:"disabled"}`，停用不删除）。
 *  - **本批仍未接入（http 如实抛 `not_connected`，绝不返回空数组）**：
 *    ① 岗位模板列表 —— 后端无模板实体（`role-templates.md` §3）；
 *    ② 员工侧只读详情 —— 后端无员工侧详情接口（页面用列表已加载的行，不发额外请求）；
 *    ③ 创建（从岗位模板创建）—— 见下方 `CREATE_AGENT_NOTE` 与契约 §3。
 *
 * 后端实测（`app/main.py:1399` 的 `DigitalEmployeeView`，8 个键）：`agent_key / name / description /
 * role_key / status / created_by / created_at / updated_at`；**没有** `template` / `last_run_at` / `ownership`
 * 与任何使用统计 ⇒ 这三项在本批分别是：前端静态目录解析 / 恒 `null`（未验证）/ 恒 `unknown`（无法判定）。
 *
 * 纪律（三条，改这个文件前先读）：
 *  ① mock 样例只在**开发模式**存在（`import.meta.env.DEV`），生产构建里整块被摇掉；
 *  ② `http` 分支**必须抛错或返回真数据**，不得静默返回空数组 —— 静默空会伪装成"真的没有数据"；
 *  ③ 未来接线只改这一个文件（页面与组件都不认识 URL）。
 *
 * 岗位模板数据来源：`docs/contracts/role-templates.md`（唯一权威）。本文件里的 6 个模板
 * **逐字照抄**该文档 §2；模板的 `budget_cents` 在 §2 表格中**没有给出**，属样例值（已标注）。
 */
import {
  SAMPLE_DATA_BADGE,
  ServiceError,
  notConnected,
  resolveServiceMode,
  serviceErrorFromApi,
  type SamplePayload,
} from '../../../utils/serviceKit'
import { request } from '../../../api/client'
import { readStoredUserId } from '../../../app/session'
import type {
  AgentItem,
  AgentOwnership,
  AgentStatus,
  AgentWriteResult,
  CreateAgentInput,
  RoleKey,
  RoleTemplate,
  UpdateAgentInput,
} from '../types'

export type ServiceMode = 'mock' | 'http'

/**
 * 适配层唯一模式开关：本轮默认 `mock`。
 * 接线轮改为 `'http'`，或用构建期变量 `VITE_WORKBENCH_API_MODE=http` 注入。
 */
export let mode: ServiceMode = resolveServiceMode()

/** 切换模式（开发 / 测试用；生产接线轮由上面的默认值或环境变量决定）。 */
export function setServiceMode(next: ServiceMode): void {
  mode = next
}

/**
 * 当前是否已接后端（`http`）—— 页面据此决定"未接入"文案与"创建"入口是否禁用。
 * 用函数而不是直接读 `mode`：`mode` 是模块级可变绑定，页面组件跨越 mock 边界时读到的可能是快照值。
 */
export function isConnected(): boolean {
  return mode === 'http'
}

/**
 * 写操作说明（**只在开发期样例数据下使用**，因此只在 DEV 分支存在；生产构建里为空串）。
 * 真接口下写成功用 `WRITE_OK_NOTE`，**不**复用这句话。
 */
export const MOCK_WRITE_NOTE = import.meta.env.DEV ? `本轮为${SAMPLE_DATA_BADGE}，操作未写入后端。` : ''

/** 真接口写成功的如实说明（后端已确认写入）。 */
export const WRITE_OK_NOTE = '已写入后端：本次修改已提交成功。'

/** 停用的如实说明（沿用后端口径：停用不删除，不影响历史任务与运行）。 */
export const DISABLE_OK_NOTE = '已写入后端：该数字员工已停用（停用不删除，历史任务与运行记录不受影响）。'

/**
 * 创建入口的固定说明（**本批未接入**，界面禁用按钮时给出该原因，不静默隐藏入口）。
 *
 * 实测口径（`app/main.py:1541`）：`POST /api/v1/workforce/agents` **存在**，但
 * ① 请求体要求**客户端自带** `agent_key`（与"标识由服务端生成"相反）；
 * ② 仅 `super_admin` 可调用（员工侧一律 `403`）；
 * ③ 后端无模板实体 ⇒ 没有"从岗位模板继承能力包"的服务端口径。
 * 因此员工侧「从岗位模板创建」本批**不接入**：不生成假标识、不假装创建成功。
 */
export const CREATE_AGENT_NOTE =
  // ⚠️ 2026-09-25 更正：原文写「后端没有员工侧创建接口」—— **已失效**。
  // OP-01（e5626aa）已开放员工侧创建（`POST /workforce/agents` 的 creator 档；
  // `owner_user_id` 由**服务端**置为调用者本人，不可伪造），后端**有**该接口了。
  // 但**前端这侧的创建入口仍未接线**（`createAgent` 仍如实抛 `not_connected`）—— 两件事要分开说。
  // ⚠️ 本串会**原样渲染到界面**（AntD tooltip / Alert）⇒ **不要写 Markdown 标记**（反引号、星号），
  // 否则用户看到字面符号。2026-09-25 真机走查实测踩过一次，已去掉反引号。
  '创建尚未接线：后端已于 2026-09-24 开放员工侧创建（接口 POST /workforce/agents，归属由服务端置为调用者本人），但本页的创建入口仍未接线，本批不会创建任何数据。'

/** 岗位模板列表未接入的说明（同一处文案，页面直接引用）。 */
export const ROLE_TEMPLATE_NOTE = '岗位模板尚未接入：后端无模板实体（接口未定义），本批不展示模板数据。'

/**
 * 归属无法判定的原因（界面必须可见，不允许把"无法判定"当成"我创建的"）。
 *
 * ⚠️ 2026-09-24（OP-01）更新：原文写「后端不下发当前用户标识，也没有『共享』实体」。
 * **两条前提均已失效** —— 登录响应自带 `user_id`（`app/session.tsx:63`），
 * 后端也已有 `workbench_employee_shares` 共享实体 + 视图下发 `owner_user_id`。
 * 现仅在**两侧信息缺一**时（未登录 / 后端未下发归属）才落到本态，属 fail-closed 兜底。
 */
export const OWNERSHIP_UNKNOWN_NOTE =
  '归属无法判定：本次响应未携带归属人，或当前会话没有本人标识；为避免误判，按"他人创建"同口径处理 —— 配置与停用需要「数字员工管理」能力。'

/**
 * 归属判定：**逐行按后端下发的 `owner_user_id` 与本人标识比对**（OP-01 起可判）。
 *
 * fail-closed：**缺本人标识或后端未下发归属 ⇒ `unknown`**，绝不臆测成 `mine`
 * （界面必须把"无法判定"与"我创建的"分开呈现）。
 */
function ownershipOf(view: WorkforceAgentView): AgentOwnership {
  const me = readStoredUserId()
  const owner = view.owner_user_id
  if (!me || !owner) return 'unknown'
  return owner === me ? 'mine' : 'shared'
}

/**
 * 岗位模板（能力包）—— 逐字对齐 `role-templates.md` §1 + §2。
 * `budget_cents` 为**样例值**（§2 表格未给该列），单位为整数分。
 */
export const ROLE_TEMPLATES: RoleTemplate[] = [
  {
    role_key: 'sales',
    name: '销售',
    mission: '帮销售把客户线索变成可跟进的商机',
    skills: ['crm.lead_intake', 'crm.quote_draft', 'content.outreach_draft'],
    tools: ['CRM 读写（受限）', '文档生成', '无出网'],
    knowledge_scopes: ['产品资料（内部）', '报价规则（机密）'],
    memory_policy: { scope: 'project', write_categories: ['客户偏好摘要'] },
    autonomy_level: 'approval_for_risky',
    budget_cents: 5000,
  },
  {
    role_key: 'hr',
    name: '人事',
    mission: '帮 HR 处理招聘与员工事务的文书工作',
    skills: ['hr.jd_draft', 'hr.interview_summary', 'doc.extract'],
    tools: ['文档解析', '表格处理'],
    knowledge_scopes: ['人事制度（内部）', '员工手册（内部）'],
    memory_policy: { scope: 'role', write_categories: ['面试记录摘要'] },
    autonomy_level: 'approval_for_all',
    budget_cents: 3000,
  },
  {
    role_key: 'rd',
    name: '研发',
    mission: '帮研发做需求拆解、代码检视与文档',
    skills: ['rd.repo_inspect', 'rd.spec_draft', 'rd.changelog'],
    tools: ['只读检视集（ls/cat/head/tail/wc 等）', '沙箱执行'],
    knowledge_scopes: ['技术文档（内部）', '接口契约（机密）'],
    memory_policy: { scope: 'project', write_categories: ['方案要点'] },
    autonomy_level: 'approval_for_risky',
    budget_cents: 8000,
  },
  {
    role_key: 'finance',
    name: '财务',
    mission: '帮财务做对账口径核对与报表说明',
    skills: ['fin.reconcile_hint', 'fin.report_explain', 'doc.extract'],
    tools: ['表格处理（只读）'],
    knowledge_scopes: ['财务制度（机密）', '历史报表（绝密）'],
    memory_policy: { scope: 'role', write_categories: ['口径说明'] },
    autonomy_level: 'approval_for_all',
    budget_cents: 2000,
  },
  {
    role_key: 'ops',
    name: '运营',
    mission: '帮运营做内容生产与发布准备',
    skills: ['content.topic_plan', 'content.draft', 'content.review'],
    tools: ['内容工具', '图片处理（无自动发布）'],
    knowledge_scopes: ['运营手册（内部）', '品牌素材（内部）'],
    memory_policy: { scope: 'project', write_categories: ['选题偏好'] },
    autonomy_level: 'approval_for_risky',
    budget_cents: 4000,
  },
  {
    role_key: 'admin',
    name: '行政',
    mission: '帮行政处理会议与流程文书',
    skills: ['office.meeting_minutes', 'office.schedule_hint', 'doc.extract'],
    tools: ['文档解析', '日程（只读）'],
    knowledge_scopes: ['行政制度（内部）'],
    memory_policy: { scope: 'role', write_categories: ['会议纪要要点'] },
    autonomy_level: 'approval_for_risky',
    budget_cents: 1500,
  },
]

/** 按岗位键取模板（找不到返回 undefined，调用方不得编造模板）。参数是**自由字符串**（后端岗位键不受控）。 */
export function templateOf(role_key: string): RoleTemplate | undefined {
  return ROLE_TEMPLATES.find((template) => template.role_key === role_key)
}

/** 取模板，缺失即抛（样例数据构造用；模板缺失属编码错误，不静默降级）。 */
function requireTemplate(role_key: RoleKey): RoleTemplate {
  const template = templateOf(role_key)
  if (!template) throw new ServiceError(`岗位模板缺失：${role_key}`, 'failed')
  return template
}

/**
 * 开发期样例数字员工（虚构内容；无 PII、无真实用户 ID / 租户 ID）。
 * **只在 `import.meta.env.DEV` 分支里存在** ⇒ 生产构建里整块被摇掉（构建后 grep 应为 0 命中）。
 */
const MOCK_AGENTS: AgentItem[] = import.meta.env.DEV ? [
  {
    agent_key: 'sample-content-ops',
    name: '内容运营助手',
    description: '负责选题、草稿与发布前准备。',
    role_key: 'ops',
    status: 'active',
    created_by: '示例创建者（本人）',
    created_at: '2026-09-10T09:00:00+08:00',
    updated_at: '2026-09-19T09:00:00+08:00',
    last_run_at: '2026-09-19T09:20:00+08:00',
    ownership: 'mine',
    template: requireTemplate('ops'),
  },
  {
    agent_key: 'sample-rd-assistant',
    name: '研发需求助理',
    description: '负责需求拆解与变更记录草稿。',
    role_key: 'rd',
    status: 'active',
    created_by: '示例创建者（本人）',
    created_at: '2026-09-12T14:00:00+08:00',
    updated_at: '2026-09-18T16:30:00+08:00',
    // 状态保真：从未运行过 ⇒ 界面必须显示"暂无运行记录 / 未验证"，不能显示 0
    last_run_at: null,
    ownership: 'mine',
    template: requireTemplate('rd'),
  },
  {
    agent_key: 'sample-finance-check',
    name: '财务对账助手',
    description: '负责对账口径核对说明（已停用）。',
    role_key: 'finance',
    status: 'disabled',
    created_by: '示例创建者（本人）',
    created_at: '2026-09-05T10:00:00+08:00',
    updated_at: '2026-09-15T11:00:00+08:00',
    last_run_at: '2026-09-15T10:40:00+08:00',
    ownership: 'mine',
    template: requireTemplate('finance'),
  },
  {
    agent_key: 'sample-sales-shared',
    name: '客户线索助手',
    description: '由同事创建并共享给我，用于线索整理。',
    role_key: 'sales',
    status: 'active',
    created_by: '示例创建者（他人）',
    created_at: '2026-09-08T09:30:00+08:00',
    updated_at: '2026-09-17T15:00:00+08:00',
    last_run_at: null,
    ownership: 'shared',
    template: requireTemplate('sales'),
  },
]
  : []

/**
 * 后端数字员工视图（`DigitalEmployeeView`，`app/main.py:1399`）—— **10 个键，逐个点名**。
 *
 * ⚠️ 2026-09-24（OP-01）：新增 `owner_user_id` / `visibility`。
 * 此前视图**不下发归属**，故前端只能把 `ownership` 恒判为 `unknown`（见 `OWNERSHIP_UNKNOWN_NOTE`）；
 * OP-01 的目录闸门拆分把「我创建的 ∪ 共享给我的」在后端**定义了**，归属自此可判。
 */
export interface WorkforceAgentView {
  agent_key: string
  name: string
  description: string
  role_key: string
  status: string
  created_by: string
  created_at: string | null
  updated_at: string | null
  /** 归属人账号标识（OP-01 新增）。缺省 / 空串 ⇒ 前端按"无法判定"处理，**不臆测**。 */
  owner_user_id?: string | null
  /** 可见性档位 `private` / `shared`（OP-01 新增；当前实现恒为 `private`，见评审材料 §十）。 */
  visibility?: string | null
}

/** 列表响应（`DigitalEmployeeListView`）：`items / total / limit / offset`。 */
export interface WorkforceAgentListView {
  items: WorkforceAgentView[]
  total: number
  limit: number
  offset: number
}

/** 单页上限：后端 `limit` 上限 200。超出时本批**不做自动翻页**（避免把残缺列表当全量）。 */
export const AGENT_PAGE_LIMIT = 200

/** 后端状态 → 受控枚举（库列有 `CHECK (status IN ('active','disabled'))`）。 */
const AGENT_STATUS: Record<string, AgentStatus> = { active: 'active', disabled: 'disabled' }

/** 后端状态 → 受控枚举；未知取值**抛错**（不误标成"已启用 / 已停用"）。 */
export function agentStatusOf(view: WorkforceAgentView): AgentStatus {
  const mapped = AGENT_STATUS[view.status]
  if (!mapped) {
    throw new ServiceError(
      `后端返回了界面未定义的员工状态，本批不展示该员工（${view.agent_key}）。`,
      'failed',
    )
  }
  return mapped
}

/** 岗位键 → 模板：只用项目级唯一目录；未知岗位键返回 `null`（不编造模板）。 */
export function resolveRoleTemplate(role_key: string): RoleTemplate | null {
  return templateOf(role_key) ?? null
}

/**
 * 全员目录列表（**未带筛选**，一次取满单页）—— 员工侧列表与注册中心指标共用同一处请求口径。
 * `total` 大于单页返回 ⇒ 抛 `failed`（不返回残缺列表、不把残缺派生当准数）。
 */
export async function fetchWorkforceAgentViews(fetchImpl?: typeof fetch): Promise<WorkforceAgentView[]> {
  try {
    const view = await request<WorkforceAgentListView>('/api/v1/workforce/agents', {
      query: { limit: AGENT_PAGE_LIMIT, offset: 0 },
      fetchImpl,
    })
    if (view.total > view.items.length) {
      throw new ServiceError(
        `后端共有 ${view.total} 个数字员工，超过单页上限 ${AGENT_PAGE_LIMIT}；本批不做自动翻页，不展示残缺数据。`,
        'failed',
      )
    }
    return view.items
  } catch (error) {
    serviceErrorFromApi(error)
  }
}

/** 后端视图 → 界面条目（绝不编造后端没有的字段）。 */
function agentOfView(view: WorkforceAgentView): AgentItem {
  return {
    agent_key: view.agent_key,
    name: view.name,
    description: view.description,
    role_key: view.role_key,
    status: agentStatusOf(view),
    created_by: view.created_by,
    // 视图模型声明可空（库列 `NOT NULL`）：拿到空值时如实留空串，**不编造时间**
    created_at: view.created_at ?? '',
    updated_at: view.updated_at ?? '',
    // 后端目录视图不下发运行时间 ⇒ 恒为 null（界面按"未验证"呈现，绝不给 0 / 成功）
    last_run_at: null,
    ownership: ownershipOf(view),
    template: resolveRoleTemplate(view.role_key),
  }
}

/**
 * 数字员工列表：`GET /api/v1/workforce/agents`。
 *
 * ⚠️ 2026-09-24（OP-01）**口径已变更** —— 原文写「后端管理目录口径，仅 `super_admin`；
 * 员工侧『我创建的 ∪ 共享给我的』在后端**未定义**，非 super_admin 会 `403`」。**该前提已失效**：
 * 目录读档已对**四档业务角色**放开（`employee` / `department_lead` / `ceo` / `super_admin`），
 * 服务端在**仓储层**按 `owner ∪ shares` 过滤后返回 ⇒ **普通员工拿到的是 200 + 已过滤列表**，
 * 不再是 `403`。归属由响应里的 `owner_user_id` 判定（见 `ownershipOf`）。
 *
 * **仍会 `403` 的**：`customer_admin`（权限矩阵数字员工四行全 ❌），以及未登录（`401`）。
 */
export async function fetchMyAgents(fetchImpl?: typeof fetch): Promise<SamplePayload<AgentItem>> {
  if (mode === 'mock') return { sample: true, items: MOCK_AGENTS }
  return { sample: false, items: (await fetchWorkforceAgentViews(fetchImpl)).map(agentOfView) }
}

/** 岗位模板列表：后端无模板实体 ⇒ **如实抛"尚未接入"**，不返回空数组。 */
export async function fetchRoleTemplates(): Promise<SamplePayload<RoleTemplate>> {
  if (mode === 'mock') return { sample: true, items: ROLE_TEMPLATES }
  notConnected('岗位模板列表')
}

/** 员工侧只读详情：后端无对应接口（页面用列表已加载的行）⇒ 如实抛"尚未接入"。 */
export async function fetchAgentDetail(agent_key: string): Promise<AgentItem> {
  if (mode === 'mock') {
    const found = MOCK_AGENTS.find((agent) => agent.agent_key === agent_key)
    if (!found) throw new ServiceError(`未找到数字员工：${agent_key}`, 'failed')
    return found
  }
  notConnected('数字员工详情（员工侧）')
}

/**
 * 创建（从岗位模板创建，DE-01）：**本批未接入**。
 * 后端 `POST /api/v1/workforce/agents` 存在，但要求客户端自带 `agent_key` 且仅 `super_admin` 可用，
 * 且无模板实体 ⇒ 不生成假标识、不假装创建成功（原因见 `CREATE_AGENT_NOTE`）。
 */
export async function createAgent(input: CreateAgentInput): Promise<AgentWriteResult> {
  if (mode === 'mock') {
    const template = templateOf(input.role_key)
    if (!template) throw new ServiceError(`岗位模板不存在：${input.role_key}`, 'failed')
    return { agent_key: `sample-created-${input.role_key}`, written: false, note: MOCK_WRITE_NOTE }
  }
  notConnected('创建数字员工')
}

/** 更新（名称 / 工作范围）：`PATCH /api/v1/workforce/agents/{agent_key}`，`agent_key` 不可改。 */
export async function updateAgent(
  input: UpdateAgentInput,
  fetchImpl?: typeof fetch,
): Promise<AgentWriteResult> {
  if (mode === 'mock') return { agent_key: input.agent_key, written: false, note: MOCK_WRITE_NOTE }

  try {
    // 只发 `name` / `description`（后端 `extra="forbid"`；传 `agent_key` 直接 422）
    const view = await request<WorkforceAgentView>(
      `/api/v1/workforce/agents/${encodeURIComponent(input.agent_key)}`,
      { method: 'PATCH', body: { name: input.name, description: input.description }, fetchImpl },
    )
    return { agent_key: view.agent_key, written: true, note: WRITE_OK_NOTE }
  } catch (error) {
    serviceErrorFromApi(error)
  }
}

/** 停用（停用不删除，沿用后端口径；界面必须走危险操作二次确认）。 */
export async function disableAgent(agent_key: string, fetchImpl?: typeof fetch): Promise<AgentWriteResult> {
  if (mode === 'mock') return { agent_key, written: false, note: MOCK_WRITE_NOTE }

  try {
    const view = await request<WorkforceAgentView>(
      `/api/v1/workforce/agents/${encodeURIComponent(agent_key)}`,
      { method: 'PATCH', body: { status: 'disabled' }, fetchImpl },
    )
    return { agent_key: view.agent_key, written: true, note: DISABLE_OK_NOTE }
  } catch (error) {
    serviceErrorFromApi(error)
  }
}