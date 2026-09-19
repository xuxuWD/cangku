/**
 * 「我的数字员工」适配层 —— 本模块**唯一**的接线点。
 *
 * 现状：**未接后端**。`mode = 'mock'` 时返回显式标注（`sample: true`）的样例数据。
 * 纪律（三条，改这个文件前先读）：
 *  ① mock 分支的数据一律带 `sample: true`，界面必须显示「示例数据（未接后端）」；
 *  ② `http` 分支**必须抛错**，不得静默返回空数组 —— 静默空会伪装成"真的没有数据"；
 *  ③ 未来接线只改这一个文件（页面与组件都不认识 URL）。
 *
 * 岗位模板数据来源：`docs/contracts/role-templates.md`（唯一权威）。本文件里的 6 个模板
 * **逐字照抄**该文档 §2；模板的 `budget_cents` 在 §2 表格中**没有给出**，属样例值（已标注），
 * 接线轮以模板实体为准。后端模板实体待 S2 之后落地（见 `docs/contracts/my-agents-api.md` §2）。
 */
import type {
  AgentItem,
  AgentWriteResult,
  CreateAgentInput,
  RoleKey,
  RoleTemplate,
  UpdateAgentInput,
} from '../types'
import { SAMPLE_DATA_BADGE, ServiceError, notConnected, type SamplePayload } from '../../../utils/serviceKit'

export type ServiceMode = 'mock' | 'http'

/**
 * 适配层唯一模式开关：本轮默认 `mock`。
 * 接线轮改为 `'http'`，或用构建期变量 `VITE_WORKBENCH_API_MODE=http` 注入。
 */
export let mode: ServiceMode = import.meta.env.VITE_WORKBENCH_API_MODE === 'http' ? 'http' : 'mock'

/** 切换模式（开发 / 测试用；生产接线轮由上面的默认值或环境变量决定）。 */
export function setServiceMode(next: ServiceMode): void {
  mode = next
}

/** 写操作的统一说明：本轮**没有**写入后端，界面必须如实告诉用户。 */
export const MOCK_WRITE_NOTE = `本轮为${SAMPLE_DATA_BADGE}，操作未写入后端。`

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

/** 按岗位键取模板（找不到返回 undefined，调用方不得编造模板）。 */
export function templateOf(role_key: RoleKey): RoleTemplate | undefined {
  return ROLE_TEMPLATES.find((template) => template.role_key === role_key)
}

/** 取模板，缺失即抛（样例数据构造用；模板缺失属编码错误，不静默降级）。 */
function requireTemplate(role_key: RoleKey): RoleTemplate {
  const template = templateOf(role_key)
  if (!template) throw new ServiceError(`岗位模板缺失：${role_key}`, 'failed')
  return template
}

/** 样例数字员工（虚构内容；无 PII、无真实用户 ID / 租户 ID）。 */
const MOCK_AGENTS: AgentItem[] = [
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

/** 我创建/共享给我的数字员工列表（`GET /api/v1/workforce/agents` 的员工侧口径，见契约 §1）。 */
export async function fetchMyAgents(): Promise<SamplePayload<AgentItem>> {
  if (mode === 'http') notConnected('我的数字员工列表')
  return { sample: true, items: MOCK_AGENTS }
}

/** 岗位模板列表（来源 `role-templates.md`；后端模板实体待 S2 之后落地，见契约 §2）。 */
export async function fetchRoleTemplates(): Promise<SamplePayload<RoleTemplate>> {
  if (mode === 'http') notConnected('岗位模板列表')
  return { sample: true, items: ROLE_TEMPLATES }
}

/** 详情（员工侧只读视图；契约 §4）。 */
export async function fetchAgentDetail(agent_key: string): Promise<AgentItem> {
  if (mode === 'http') notConnected('数字员工详情')
  const found = MOCK_AGENTS.find((agent) => agent.agent_key === agent_key)
  if (!found) throw new ServiceError(`未找到数字员工：${agent_key}`, 'failed')
  return found
}

/**
 * 创建（从岗位模板创建，DE-01）。
 * 能力包**由模板继承**（服务端读模板 → 生成绑定），客户端只提交 `name` / `role_key` / `description`。
 */
export async function createAgent(input: CreateAgentInput): Promise<AgentWriteResult> {
  if (mode === 'http') notConnected('创建数字员工')
  const template = templateOf(input.role_key)
  if (!template) throw new ServiceError(`岗位模板不存在：${input.role_key}`, 'failed')
  return { agent_key: `sample-created-${input.role_key}`, written: false, note: MOCK_WRITE_NOTE }
}

/** 更新（名称 / 工作范围；`agent_key` 不可改，与后端口径一致）。 */
export async function updateAgent(input: UpdateAgentInput): Promise<AgentWriteResult> {
  if (mode === 'http') notConnected('修改数字员工')
  return { agent_key: input.agent_key, written: false, note: MOCK_WRITE_NOTE }
}

/** 停用（停用不删除，沿用后端口径；界面必须走危险操作二次确认）。 */
export async function disableAgent(agent_key: string): Promise<AgentWriteResult> {
  if (mode === 'http') notConnected('停用数字员工')
  return { agent_key, written: false, note: MOCK_WRITE_NOTE }
}