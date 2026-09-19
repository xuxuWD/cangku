/**
 * 「数字员工注册中心」适配层（第 5 轮）—— 本模块**唯一**的接线点。
 *
 * 现状：**未接后端**。`mode = 'mock'` 时返回带样例硬标记（`sample: true`）的样例数据。
 * 纪律（与员工侧一致）：
 *  ① 样例数据必须带 `sample: true`，界面必须显示「示例数据（未接后端）」；
 *  ② `http` 分支**必须抛错**，不得静默返回空数据；
 *  ③ **筛选参数原样透传**给"服务端"（这里是 mock 分支扮演服务端），页面不得在前端过滤；
 *  ④ 未来接线只改这一个文件。
 *
 * 复用（不复制第二份）：岗位模板是**项目级词汇**（真源 `docs/contracts/role-templates.md`），
 * 第 4 轮已落在 `features/myAgents/services/myAgentsService.ts`，本轮直接复用；
 * 写操作的"未写入后端"口径同样复用 `MOCK_WRITE_NOTE`。
 */
import type { AgentStatus, AgentWriteResult, RoleKey, RoleTemplate } from '../../myAgents/types'
import { MOCK_WRITE_NOTE, ROLE_TEMPLATES, templateOf } from '../../myAgents/services/myAgentsService'
import { SAMPLE_DATA_BADGE, ServiceError, notConnected } from '../../../utils/serviceKit'
import type {
  RegistryAgentStatus,
  RegistryListPayload,
  RegistryQuery,
  RegistryRow,
  RegistryStatsPayload,
} from '../types'

export type ServiceMode = 'mock' | 'http'

/** 适配层唯一模式开关：本轮默认 `mock`；接线轮改为 `http` 或注入 `VITE_WORKBENCH_API_MODE=http`。 */
export let mode: ServiceMode = import.meta.env.VITE_WORKBENCH_API_MODE === 'http' ? 'http' : 'mock'

/** 切换模式（开发 / 测试用）。 */
export function setServiceMode(next: ServiceMode): void {
  mode = next
}

/** 写操作的统一说明（复用员工侧同一句话，避免两处措辞漂移）。 */
export { MOCK_WRITE_NOTE }

/** 取模板，缺失即抛（样例数据构造用；模板缺失属编码错误，不静默降级）。 */
function requireTemplate(role_key: RoleKey): RoleTemplate {
  const template = templateOf(role_key)
  if (!template) throw new ServiceError(`岗位模板缺失：${role_key}`, 'failed')
  return template
}

/**
 * 样例数字员工（虚构内容；无手机号 / 真实用户 ID / 租户 ID）。
 * 刻意覆盖三种**非就绪**统计态与三种状态（含"草稿"），供状态保真与受控枚举用例断言。
 */
const MOCK_ROWS: RegistryRow[] = [
  {
    agent_key: 'sample-ops-content',
    name: '内容运营助手',
    description: '负责选题、草稿与发布前准备。',
    role_key: 'ops',
    status: 'active',
    created_by: '示例创建者 01',
    created_at: '2026-09-10T09:00:00+08:00',
    updated_at: '2026-09-19T09:00:00+08:00',
    last_run_at: '2026-09-19T09:20:00+08:00',
    template: requireTemplate('ops'),
    usage: { run_count: 12, success_rate: 0.9167 },
  },
  {
    agent_key: 'sample-rd-spec',
    name: '研发需求助理',
    description: '负责需求拆解与变更记录草稿。',
    role_key: 'rd',
    status: 'active',
    created_by: '示例创建者 01',
    created_at: '2026-09-12T14:00:00+08:00',
    updated_at: '2026-09-18T16:30:00+08:00',
    last_run_at: '2026-09-18T16:30:00+08:00',
    template: requireTemplate('rd'),
    usage: { run_count: 30, success_rate: 0.9 },
  },
  {
    agent_key: 'sample-sales-lead',
    name: '客户线索助手',
    description: '整理客户线索并生成跟进建议。',
    role_key: 'sales',
    status: 'active',
    created_by: '示例创建者 02',
    created_at: '2026-09-08T09:30:00+08:00',
    updated_at: '2026-09-17T15:00:00+08:00',
    last_run_at: '2026-09-17T15:00:00+08:00',
    template: requireTemplate('sales'),
    usage: { run_count: 7, success_rate: 0.8571 },
  },
  {
    agent_key: 'sample-finance-check',
    name: '财务对账助手',
    description: '负责对账口径核对说明（已停用）。',
    role_key: 'finance',
    status: 'disabled',
    created_by: '示例创建者 02',
    created_at: '2026-09-05T10:00:00+08:00',
    updated_at: '2026-09-15T11:00:00+08:00',
    last_run_at: '2026-09-15T10:40:00+08:00',
    template: requireTemplate('finance'),
    usage: { run_count: 5, success_rate: 0.8 },
  },
  {
    agent_key: 'sample-hr-jd',
    name: '招聘文书助手',
    description: '起草岗位说明与面试记录摘要。',
    role_key: 'hr',
    status: 'active',
    created_by: '示例创建者 03',
    created_at: '2026-09-14T10:20:00+08:00',
    updated_at: '2026-09-16T09:10:00+08:00',
    // 状态保真样本①：从未运行、也拿不到统计 ⇒ 必须显示"未验证"，不得显示 0 / 0%
    last_run_at: null,
    template: requireTemplate('hr'),
    usage: { run_count: null, success_rate: null },
  },
  {
    agent_key: 'sample-admin-minutes',
    name: '会议纪要助手',
    description: '整理会议纪要与待办要点。',
    role_key: 'admin',
    status: 'active',
    created_by: '示例创建者 03',
    created_at: '2026-09-16T11:00:00+08:00',
    updated_at: '2026-09-16T11:00:00+08:00',
    // 状态保真样本②：0 次运行 ⇒ 成功率无从计算，显示"样本不足"，不得显示 0%
    last_run_at: null,
    template: requireTemplate('admin'),
    usage: { run_count: 0, success_rate: null },
  },
  {
    agent_key: 'sample-ops-draft',
    name: '运营选题助手（草稿）',
    description: '尚未发布：正在配置知识库范围。',
    role_key: 'ops',
    status: 'draft',
    created_by: '示例创建者 01',
    created_at: '2026-09-19T08:00:00+08:00',
    updated_at: '2026-09-19T08:30:00+08:00',
    last_run_at: '2026-09-19T08:30:00+08:00',
    template: requireTemplate('ops'),
    // 状态保真样本③：有运行但成功率未配置 ⇒ 显示"未配置"，不得显示 0%
    usage: { run_count: 4, success_rate: null },
  },
  {
    agent_key: 'sample-rd-review',
    name: '代码检视助手',
    description: '只读检视集与变更说明（已停用）。',
    role_key: 'rd',
    status: 'disabled',
    created_by: '示例创建者 01',
    created_at: '2026-09-03T09:00:00+08:00',
    updated_at: '2026-09-12T09:00:00+08:00',
    last_run_at: '2026-09-12T08:50:00+08:00',
    template: requireTemplate('rd'),
    usage: { run_count: 18, success_rate: 0.9444 },
  },
  {
    agent_key: 'sample-sales-quote',
    name: '报价单助手',
    description: '按报价规则生成报价草稿。',
    role_key: 'sales',
    status: 'active',
    created_by: '示例创建者 02',
    created_at: '2026-09-13T13:00:00+08:00',
    updated_at: '2026-09-18T10:00:00+08:00',
    last_run_at: '2026-09-18T10:00:00+08:00',
    template: requireTemplate('sales'),
    usage: { run_count: 9, success_rate: 0.8889 },
  },
]

/**
 * 服务端语义的筛选 + 分页（mock 分支扮演服务端）。
 * 页面**不得**自行过滤 —— 所有筛选条件都从这里进出，接线后换成真实查询参数即可。
 */
function applyQuery(rows: RegistryRow[], query: RegistryQuery): RegistryListPayload {
  const keyword = query.keyword?.trim().toLowerCase()
  const creator = query.created_by?.trim().toLowerCase()

  const filtered = rows.filter(
    (row) =>
      (!query.role_key || row.role_key === query.role_key) &&
      (!query.status || row.status === query.status) &&
      (!creator || row.created_by.toLowerCase().includes(creator)) &&
      (!keyword || row.name.toLowerCase().includes(keyword)),
  )

  const offset = (query.page - 1) * query.pageSize
  return {
    sample: true,
    items: filtered.slice(offset, offset + query.pageSize),
    total: filtered.length,
    limit: query.pageSize,
    offset,
  }
}

/** 列表（含筛选与分页）：`GET /api/v1/workforce/agents`（既有，仅 super_admin；见契约 §1）。 */
export async function fetchRegistryAgents(query: RegistryQuery): Promise<RegistryListPayload> {
  if (mode === 'http') notConnected('数字员工注册中心列表')
  return applyQuery(MOCK_ROWS, query)
}

/** 指标统计：**不受筛选影响**（全员大盘）。接口后端未定义，见契约 §3。 */
export async function fetchRegistryStats(): Promise<RegistryStatsPayload> {
  if (mode === 'http') notConnected('数字员工指标统计')
  const countBy = (status: RegistryAgentStatus) => MOCK_ROWS.filter((row) => row.status === status).length
  const active = countBy('active')
  const disabled = countBy('disabled')
  const draft = countBy('draft')
  return {
    sample: true,
    // 总数恒等于三态之和（界面据此展示"全部（含草稿）"，评审者不必自己相减）
    total: active + disabled + draft,
    active,
    disabled,
    draft,
    // 运行口径统计后端未接入 ⇒ 如实为 null，界面显示"未验证"（不得填 0）
    ran_last_7d: null,
  }
}

/** 详情（管理侧视图，含能力包与创建信息）。 */
export async function fetchRegistryAgentDetail(agent_key: string): Promise<RegistryRow> {
  if (mode === 'http') notConnected('数字员工详情（管理侧）')
  const found = MOCK_ROWS.find((row) => row.agent_key === agent_key)
  if (!found) throw new ServiceError(`未找到数字员工：${agent_key}`, 'failed')
  return found
}

/** 启用 / 停用：`PATCH /api/v1/workforce/agents/{agent_key}`（既有，仅 super_admin；见契约 §4）。 */
export async function setAgentStatus(input: {
  agent_key: string
  status: AgentStatus
}): Promise<AgentWriteResult> {
  if (mode === 'http') notConnected('数字员工启停')
  return { agent_key: input.agent_key, written: false, note: MOCK_WRITE_NOTE }
}

/** 岗位模板（筛选栏的岗位选项）：复用项目级唯一一份模板表。 */
export function roleTemplateOptions(): RoleTemplate[] {
  return ROLE_TEMPLATES
}

/** 「示例数据」标识（页面统一展示；同一处文案来自共享 serviceKit）。 */
export const SAMPLE_NOTICE = SAMPLE_DATA_BADGE