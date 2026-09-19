/**
 * 「数字员工注册中心」适配层（第 5 轮；第 6 轮接线批 2 回写）—— 本模块**唯一**的接线点。
 *
 * 第 6 轮实测后的接线结论：
 *  - **已接线（http 走真接口）**：
 *    ① 列表 `GET /api/v1/workforce/agents`（仅 `super_admin`，与本页权限口径正好一致）；
 *    ② 启停 `PATCH /api/v1/workforce/agents/{agent_key}`（请求体 `{status}`；停用不删除）。
 *  - **本批仍未接入（http 如实抛 `not_connected`，绝不静默忽略或返回空数据）**：
 *    ① 指标聚合接口 —— 后端**没有**（`GET /api/v1/workforce/agents/stats` 实测 `405`）⇒ 只能**从真实列表派生**；
 *    ② `draft`（草稿）—— 库列 `CHECK (status IN ('active','disabled'))`，**后端无此枚举** ⇒ `draft = null`；
 *    ③ 运行口径（`usage.run_count` / `success_rate` / `last_run_at` / `ran_last_7d`）—— 目录视图不含运行数据，
 *       且无按员工的运行聚合接口（`/api/v1/metrics/summary` 是租户级，**不按员工拆分**）⇒ 一律非就绪，**不显示 0 / 0% / "成功"**；
 *    ④ 按创建者 / 名称的筛选 —— 后端列表只支持 `status` / `role_key`（实测：未知查询参数被忽略）⇒ 透传会得到"未筛选"的假结果，
 *       故 **http 下如实抛 not_connected**（页面同时禁用这两个输入并给出原因）；
 *    ⑤ 管理侧只读详情 —— 后端无该口径（页面用列表已加载的行）。
 *
 * 纪律（与员工侧一致）：
 *  ① 样例数据只在**开发模式**存在（`import.meta.env.DEV`），生产构建里整块被摇掉；
 *  ② `http` 分支**必须抛错或返回真数据**，不得静默返回空数据；
 *  ③ 支持的筛选条件**原样透传**给服务端，页面不自行过滤；
 *  ④ 未来接线只改这一个文件。
 *
 * 复用（不复制第二份）：岗位模板是**项目级词汇**（真源 `docs/contracts/role-templates.md`），
 * 落在 `features/myAgents/services/myAgentsService.ts`，本轮直接复用；
 * 写操作的"未写入后端"口径同样复用 `MOCK_WRITE_NOTE`。
 */
import { request } from '../../../api/client'
import {
  SAMPLE_DATA_BADGE,
  ServiceError,
  notConnected,
  resolveServiceMode,
  serviceErrorFromApi,
} from '../../../utils/serviceKit'
import type { AgentStatus, AgentWriteResult, RoleKey, RoleTemplate } from '../../myAgents/types'
import {
  DISABLE_OK_NOTE,
  MOCK_WRITE_NOTE,
  ROLE_TEMPLATES,
  agentStatusOf,
  fetchWorkforceAgentViews,
  resolveRoleTemplate,
  templateOf,
} from '../../myAgents/services/myAgentsService'
import type { WorkforceAgentListView, WorkforceAgentView } from '../../myAgents/services/myAgentsService'
import type {
  RegistryAgentStatus,
  RegistryListPayload,
  RegistryQuery,
  RegistryRow,
  RegistryStatsPayload,
} from '../types'

export type ServiceMode = 'mock' | 'http'

/** 适配层唯一模式开关：本轮默认 `mock`；接线轮改为 `http` 或注入 `VITE_WORKBENCH_API_MODE=http`。 */
export let mode: ServiceMode = resolveServiceMode()

/** 切换模式（开发 / 测试用）。 */
export function setServiceMode(next: ServiceMode): void {
  mode = next
}

/** 当前是否已接后端（`http`）—— 页面据此决定"未接入"文案与筛选可用性（用函数取，避免读到快照值）。 */
export function isConnected(): boolean {
  return mode === 'http'
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
const MOCK_ROWS: RegistryRow[] = import.meta.env.DEV ? [
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
  : []

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

/** 后端视图 → 管理侧行（`usage` / `last_run_at` 后端不提供 ⇒ 非就绪，**绝不填 0 / 0%**）。 */
function rowOfView(view: WorkforceAgentView): RegistryRow {
  return {
    agent_key: view.agent_key,
    name: view.name,
    description: view.description,
    role_key: view.role_key,
    created_by: view.created_by,
    created_at: view.created_at ?? '',
    updated_at: view.updated_at ?? '',
    last_run_at: null,
    template: resolveRoleTemplate(view.role_key),
    status: agentStatusOf(view),
    usage: { run_count: null, success_rate: null },
  }
}

/** 后端**不支持**的筛选：透传会被后端静默忽略（返回"未筛选"结果）⇒ 如实抛"尚未接入"。 */
function rejectUnsupportedFilters(query: RegistryQuery): void {
  if (query.created_by) notConnected('按创建者筛选')
  if (query.keyword) notConnected('按名称筛选')
  if (query.status === 'draft') notConnected('按「草稿」状态筛选')
}

/**
 * 列表（含筛选与分页）：`GET /api/v1/workforce/agents`（既有，仅 super_admin；见契约 §1）。
 * 支持的筛选（`status` / `role_key`）与分页（`limit` / `offset`）**原样透传**，页面不做前端过滤。
 */
export async function fetchRegistryAgents(
  query: RegistryQuery,
  fetchImpl?: typeof fetch,
): Promise<RegistryListPayload> {
  if (mode === 'mock') return applyQuery(MOCK_ROWS, query)

  rejectUnsupportedFilters(query)
  try {
    const view = await request<WorkforceAgentListView>('/api/v1/workforce/agents', {
      query: {
        role_key: query.role_key,
        status: query.status,
        limit: query.pageSize,
        offset: (query.page - 1) * query.pageSize,
      },
      fetchImpl,
    })
    return {
      sample: false,
      items: view.items.map(rowOfView),
      total: view.total,
      limit: view.limit,
      offset: view.offset,
    }
  } catch (error) {
    serviceErrorFromApi(error)
  }
}

/**
 * 指标统计：**后端没有聚合接口** ⇒ 只能**从真实列表派生**（全员口径，不带筛选）。
 * `draft` / `ran_last_7d` 后端无口径 ⇒ `null`（界面按「未验证」呈现，**不显示 0**）。
 */
export async function fetchRegistryStats(fetchImpl?: typeof fetch): Promise<RegistryStatsPayload> {
  if (mode === 'mock') {
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

  const views = await fetchWorkforceAgentViews(fetchImpl)
  // 用 `agentStatusOf` 校验状态（未知取值抛错，避免把未知状态算漏还不报）
  const statuses = views.map(agentStatusOf)
  return {
    sample: false,
    total: views.length,
    active: statuses.filter((status) => status === 'active').length,
    disabled: statuses.filter((status) => status === 'disabled').length,
    // 后端 status 无 draft 枚举 ⇒ 未接入（不写 0）
    draft: null,
    // 目录视图不含运行数据、无按员工的运行聚合接口 ⇒ 未验证（不写 0）
    ran_last_7d: null,
  }
}

/** 管理侧只读详情：后端无该口径（页面用列表已加载的行）⇒ 如实抛"尚未接入"。 */
export async function fetchRegistryAgentDetail(agent_key: string): Promise<RegistryRow> {
  if (mode === 'mock') {
    const found = MOCK_ROWS.find((row) => row.agent_key === agent_key)
    if (!found) throw new ServiceError(`未找到数字员工：${agent_key}`, 'failed')
    return found
  }
  notConnected('数字员工详情（管理侧）')
}

/** 启用 / 停用：`PATCH /api/v1/workforce/agents/{agent_key}`（既有，仅 super_admin；见契约 §4）。 */
export async function setAgentStatus(
  input: { agent_key: string; status: AgentStatus },
  fetchImpl?: typeof fetch,
): Promise<AgentWriteResult> {
  if (mode === 'mock') return { agent_key: input.agent_key, written: false, note: MOCK_WRITE_NOTE }

  try {
    const view = await request<WorkforceAgentView>(
      `/api/v1/workforce/agents/${encodeURIComponent(input.agent_key)}`,
      { method: 'PATCH', body: { status: input.status }, fetchImpl },
    )
    return {
      agent_key: view.agent_key,
      written: true,
      note: input.status === 'disabled' ? DISABLE_OK_NOTE : '已写入后端：该数字员工已启用。',
    }
  } catch (error) {
    serviceErrorFromApi(error)
  }
}

/** 岗位模板（筛选栏的岗位选项）：复用项目级唯一一份模板表。 */
export function roleTemplateOptions(): RoleTemplate[] {
  return ROLE_TEMPLATES
}

/** 「示例数据」标识（页面统一展示；同一处文案来自共享 serviceKit）。 */
export const SAMPLE_NOTICE = SAMPLE_DATA_BADGE

/**
 * 后端**不支持**的筛选（创建者 / 名称 / 草稿）在 http 模式下禁用的原因。
 * 透传会被后端静默忽略（返回"未筛选"的结果），那比报错更危险 ⇒ 禁用 + 给原因，并在服务层抛 `not_connected`。
 */
export const UNSUPPORTED_FILTER_NOTE = '后端列表接口不支持该筛选（透传会被忽略、返回"未筛选"的假结果），本批如实禁用。'