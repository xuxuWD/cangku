/**
 * 「权限配置」适配层 —— 本模块**唯一**的接线点（页面与组件都不认识 URL）。
 *
 * 第 6 轮实测（2026-09-19 真机 `127.0.0.1:18112` + 真库 `workbench_test`，只读源码未改后端一行）：
 *  - 读：`GET /api/v1/workforce/roles`、`GET /api/v1/workforce/agents`（目录，仅 `super_admin`）
 *    + 逐行 `GET /api/v1/knowledge-access/{roles|agents}/{key}`（读**不要求**该标识已纳管）；
 *  - 写：`PUT` 同一路径，请求体 `{"knowledge_base_ids":[...]}`（后端 `extra="forbid"`、`max_length=100`），
 *    成功返回**服务端回读值**；两道闸门顺序 = **先权限（`403`）后目录（`409`）**；
 *  - 变更记录：`GET /api/v1/knowledge-access/audits?limit=` 返回**数组**（只读）。
 *
 * 纪律（改这个文件前先读）：
 *  ① 样例数据只在**开发模式**存在（`import.meta.env.DEV`）⇒ 生产构建里整块被摇掉；
 *  ② `http` 分支**必须抛错或返回真实数据**，不得静默返回空数组（静默空会伪装成"真的没有内容"）；
 *  ③ 写失败必须分类（`forbidden` / `conflict` / `invalid` / `failed`）并保留请求层已 sanitize 的文案，
 *     界面据此**就地呈现**且**不假装成功**；
 *  ④ 未来接线只改这一个文件。
 *
 * 已知口径（契约 §4 已登记）：后端**没有知识库枚举接口** ⇒ 候选只能取"现有绑定的并集"，新标识需手动录入。
 * 已知性能口径：目录无批量绑定接口 ⇒ 每行一次 `GET`（随目录行数线性增长，已在契约 §6 登记）。
 */
import { ApiError, request } from '../../../api/client'
import type { RequestOptions } from '../../../api/client'
import {
  SAMPLE_DATA_BADGE,
  ServiceError,
  resolveServiceMode,
  serviceErrorFromApi,
} from '../../../utils/serviceKit'
import type {
  AuditPage,
  BindingType,
  DirectoryStatus,
  KnowledgeAuditEntry,
  KnowledgeBaseCandidateList,
  KnowledgeBinding,
  ScopePage,
  ScopeRow,
  ScopeWriteInput,
  ScopeWriteResult,
} from '../types'
import { BINDING_TYPE_LABEL, normalizeIds } from '../types'

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

/** 目录单页上限（后端 `limit` 上限 200）。超出时不自动翻页，也不展示残缺数据。 */
const DIRECTORY_PAGE_LIMIT = 200

/** 「最近变更」的取数条数（契约 §3：只读，取最近 20 条）。 */
export const AUDIT_LIMIT = 20

/** 写成功的如实说明（后端已确认写入；回读值取自服务端响应）。 */
export const WRITE_OK_NOTE = '已保存：知识范围已更新。'

/**
 * 样例模式下的写说明（**只在开发期存在**，生产构建里为空串）。
 * 措辞避免开发术语（"后端 / 接口 / 本轮"），只说"没有写入任何数据"。
 */
export const MOCK_WRITE_NOTE: string = import.meta.env.DEV
  ? `当前为${SAMPLE_DATA_BADGE}，本次操作没有写入任何数据。`
  : ''

/**
 * 候选来源的固定说明（**清单取到时**，第 15 轮起）。
 *
 * 口径变更（2026-09-21）：此前候选只能取"现有绑定并集"、且后端无枚举接口（旧文案"平台暂无可选清单"）；
 * 本轮接上 `GET /api/v1/knowledge/bases`（上游知识库清单）⇒ 候选有真源，但**平台仍不校验手输值**，
 * 这句话必须留着（诚实告知，不承诺平台能拦住配错）。
 */
export const CANDIDATE_NOTE =
  '候选来自知识库清单；也可直接输入标识 —— 平台无法校验标识是否存在，请与知识库的实际标识保持一致。'

/** 清单**没取到**（服务端降级）时的如实说明：说"没取到"，**绝不**说"没有知识库"。 */
export const CANDIDATE_UNAVAILABLE_NOTE =
  '未能获取知识库清单，以下为已绑定过的标识；可直接输入标识。'

/** 清单请求**失败**（网络 / 权限 / 服务错误）时的说明：同样只说"没取到"，可继续手输。 */
export const CANDIDATE_ERROR_NOTE = '未能获取知识库清单；可直接输入标识。'

/** 清单加载中。 */
export const CANDIDATE_LOADING_NOTE = '正在获取知识库清单…'

/** 手输 / 已绑定但不在清单里的标识 ⇒ 黄色提醒文案（**不阻断保存**）。 */
export const CANDIDATE_UNKNOWN_NOTE =
  '该标识未出现在知识库清单中，请再确认拼写；保存后若知识库里不存在该标识，检索将无结果。'

/** 「角色知识范围」空态：解释**为什么空**，而不是显示"0 条绑定"。 */
export const ROLE_EMPTY_NOTE =
  '目录里还没有岗位；请先在「数字员工设置」中纳管岗位，再回到本页配置知识范围。'

/** 「数字员工知识范围」空态（同上口径）。 */
export const AGENT_EMPTY_NOTE =
  '目录里还没有数字员工；请先在「数字员工设置」中纳管数字员工，再回到本页配置知识范围。'

/** 「最近变更」空态：**真实语义**（确实没有变更过），不是加载失败。 */
export const AUDIT_EMPTY_NOTE = '暂无变更记录。'

/** 已接入真实数据时的说明（与「示例数据」标识互斥，避免含糊）。 */
export const CONNECTED_NOTICE = '已接入真实数据'
export const CONNECTED_DESCRIPTION =
  '岗位、数字员工与知识范围均来自服务端；候选标识来自知识库清单，也可直接输入标识。'

/** 样例模式下的说明。 */
export const SAMPLE_DESCRIPTION = '本页岗位、数字员工与变更记录均为示例数据，不会写入任何数据。'

/** 写失败分类：界面据此给出**不同的**可懂原因，而不是笼统的"操作失败"。 */
export type ScopeWriteFailure = 'forbidden' | 'conflict' | 'invalid' | 'failed'

/**
 * 写失败（带分类与已 sanitize 的文案）。
 *
 * 文案来源：请求层优先取服务端 `detail`（仅当它是"短且干净"的字符串），
 * 否则回落本地固定文案 —— 因此 `422`（`detail` 是数组）**不会**把校验 JSON 渲染到界面。
 */
export class ScopeWriteError extends ServiceError {
  readonly kind: ScopeWriteFailure

  constructor(message: string, kind: ScopeWriteFailure) {
    super(message, kind === 'forbidden' ? 'forbidden' : 'failed')
    this.name = 'ScopeWriteError'
    this.kind = kind
  }
}

/** 写失败的就地提示（**必须说明"没有写入任何数据"**，不允许含糊成"操作失败"）。 */
export const WRITE_FAILURE_HINT: Record<ScopeWriteFailure, string> = {
  forbidden: '本次没有写入任何数据；如需调整知识范围，请使用超级管理员账号。',
  conflict: '本次没有写入任何数据；该标识尚未纳入目录，请先在「数字员工设置」中纳管后重试。',
  invalid: '本次没有写入任何数据；请检查填写内容后重试。',
  failed: '本次没有写入任何数据，请稍后重试。',
}

/**
 * 写路径方法：`PUT`（知识访问绑定的契约方法）。
 *
 * 收口记录（2026-09-19）：本模块交付时请求层的 `RequestOptions.method` **缺 `PUT`**，只能做类型收窄；
 * 收口时已把 `PUT` 补进 `src/api/client.ts` 的受控枚举（并加请求层用例锁定方法透传）⇒ 收窄已移除。
 */
const PUT: RequestOptions['method'] = 'PUT'

/** 目录列表路径。 */
function directoryPath(kind: BindingType): string {
  return kind === 'role' ? '/api/v1/workforce/roles' : '/api/v1/workforce/agents'
}

/** 知识访问绑定路径（读 / 写同一条）。 */
function bindingPath(kind: BindingType, key: string): string {
  const segment = kind === 'role' ? 'roles' : 'agents'
  return `/api/v1/knowledge-access/${segment}/${encodeURIComponent(key)}`
}

/** 变更记录路径。 */
const AUDIT_PATH = '/api/v1/knowledge-access/audits'

/** 知识库候选清单路径（第 15 轮新增，只读）。 */
const KNOWLEDGE_BASES_PATH = '/api/v1/knowledge/bases'

/** 目录条目视图（后端 `JobRoleView` / `DigitalEmployeeView` 的公共键）。 */
interface DirectoryItemView {
  role_key?: string
  agent_key?: string
  name: string
  status: string
}

interface DirectoryListView {
  items: DirectoryItemView[]
  total: number
  limit: number
  offset: number
}

/** 取目录条目的标识键（缺失即抛：不编造标识、不静默跳过）。 */
function directoryKeyOf(kind: BindingType, item: DirectoryItemView): string {
  const key = kind === 'role' ? item.role_key : item.agent_key
  if (typeof key !== 'string' || key.length === 0) {
    throw new ServiceError('服务端返回的目录条目缺少标识，本模块不展示该条目。', 'failed')
  }
  return key
}

/** 目录状态 → 受控枚举；**未知取值抛错**（不误标成"已启用 / 已停用"）。 */
function statusOf(raw: string, key: string): DirectoryStatus {
  if (raw === 'active' || raw === 'disabled') return raw
  throw new ServiceError(`服务端返回了界面未定义的目录状态，本模块不展示该条目（${key}）。`, 'failed')
}

/** 写失败 → 带分类的模块错误（非请求层错误原样抛出，不吞异常）。 */
function toWriteError(error: unknown): never {
  if (error instanceof ApiError) {
    if (error.failure === 'forbidden') throw new ScopeWriteError(error.message, 'forbidden')
    if (error.failure === 'conflict') throw new ScopeWriteError(error.message, 'conflict')
    if (error.status === 422) throw new ScopeWriteError(error.message, 'invalid')
    throw new ScopeWriteError(error.message, 'failed')
  }
  throw error
}

/**
 * 一块范围：先取目录（分页一次取满），再**逐行**取该行的绑定。
 *
 * 行数与请求数 1:N（后端无批量绑定接口）；目录总数超过单页上限 ⇒ 抛错（不把残缺列表当全量）。
 * 任一请求失败即整块失败（宁可整块报错，也不静默漏掉一部分绑定 —— 少一半绑定比"加载失败"更危险）。
 */
async function fetchScopes(kind: BindingType, fetchImpl?: typeof fetch): Promise<ScopePage> {
  try {
    const list = await request<DirectoryListView>(directoryPath(kind), {
      query: { limit: DIRECTORY_PAGE_LIMIT, offset: 0 },
      fetchImpl,
    })
    if (list.total > list.items.length) {
      throw new ServiceError(
        `目录共有 ${list.total} 个${BINDING_TYPE_LABEL[kind]}，超过单页上限 ${DIRECTORY_PAGE_LIMIT}；本模块不做自动翻页，不展示残缺数据。`,
        'failed',
      )
    }

    const rows: ScopeRow[] = await Promise.all(
      list.items.map(async (item) => {
        const binding_key = directoryKeyOf(kind, item)
        const binding = await request<KnowledgeBinding>(bindingPath(kind, binding_key), { fetchImpl })
        if (!Array.isArray(binding.knowledge_base_ids)) {
          // 形状不符 ⇒ 抛错；**绝不默认成"未绑定"**（那会把"没拿到"显示成"确实没有"）
          throw new ServiceError(`服务端未返回「${binding_key}」的知识范围，本模块不臆测。`, 'failed')
        }
        return {
          binding_type: kind,
          binding_key,
          name: item.name,
          status: statusOf(item.status, binding_key),
          knowledge_base_ids: normalizeIds(binding.knowledge_base_ids),
        }
      }),
    )

    return { sample: false, rows }
  } catch (error) {
    serviceErrorFromApi(error)
  }
}

/** 角色知识范围（「角色知识范围」块）。 */
export async function fetchRoleScopes(fetchImpl?: typeof fetch): Promise<ScopePage> {
  if (mode === 'mock') return { sample: true, rows: MOCK_ROLE_ROWS }
  return fetchScopes('role', fetchImpl)
}

/** 数字员工知识范围（「数字员工知识范围」块）。 */
export async function fetchAgentScopes(fetchImpl?: typeof fetch): Promise<ScopePage> {
  if (mode === 'mock') return { sample: true, rows: MOCK_AGENT_ROWS }
  return fetchScopes('agent', fetchImpl)
}

/** 最近变更（只读）：`GET /api/v1/knowledge-access/audits?limit=`，返回**数组**。 */
export async function fetchAudits(
  limit: number = AUDIT_LIMIT,
  fetchImpl?: typeof fetch,
): Promise<AuditPage> {
  if (mode === 'mock') return { sample: true, items: MOCK_AUDITS }

  try {
    const items = await request<KnowledgeAuditEntry[]>(AUDIT_PATH, { query: { limit }, fetchImpl })
    if (!Array.isArray(items)) {
      throw new ServiceError('变更记录返回的形状不符合约定，本模块不展示臆测内容。', 'failed')
    }
    return { sample: false, items }
  } catch (error) {
    serviceErrorFromApi(error)
  }
}

/**
 * 知识库候选清单：`GET /api/v1/knowledge/bases`（**只读**，第 15 轮）。
 *
 * 契约要点（`docs/api-contract.md`「企业知识检索」节）：
 *  - `upstream_available === false` ⇒ **降级**（清单没取到），此时 `note` **必带**原因、
 *    `items` 只是"本租户已绑定过的标识"——界面据此如实提示，**绝不**读成「没有知识库」；
 *  - 形状不符 / 降级却不带 `note` ⇒ **抛错**（不展示臆测内容，也不静默返回空清单）。
 *
 * ⚠️ 该端点上游侧**未实调**（无可用上游实例）⇒ 本机真机走的一定是降级分支，
 * 这是**如实**的结果，不是缺陷；实调补验方式见 `docs/contracts/permissions-fake-entry-plan.md` §11。
 */
export async function listKnowledgeBases(fetchImpl?: typeof fetch): Promise<KnowledgeBaseCandidateList> {
  if (mode === 'mock') return MOCK_KNOWLEDGE_BASES

  try {
    const list = await request<KnowledgeBaseCandidateList>(KNOWLEDGE_BASES_PATH, { fetchImpl })
    const shaped =
      typeof list?.upstream_available === 'boolean' &&
      (list.source === 'upstream' || list.source === 'local_only') &&
      Array.isArray(list.items) &&
      list.items.every(
        (item) => typeof item?.knowledge_base_id === 'string' && item.knowledge_base_id.length > 0,
      )
    if (!shaped) {
      throw new ServiceError('知识库清单返回的形状不符合约定，本模块不展示臆测内容。', 'failed')
    }
    if (!list.upstream_available && typeof list.note !== 'string') {
      // 降级却不说明原因 ⇒ 会被界面读成"没有知识库"（正是本轮要消掉的谎报）⇒ 直接判为失败
      throw new ServiceError('知识库清单未能取到，且服务端没有说明原因，本模块不臆测。', 'failed')
    }
    return list
  } catch (error) {
    serviceErrorFromApi(error)
  }
}

/**
 * 保存某行（角色 / 数字员工）的知识范围：`PUT /api/v1/knowledge-access/{roles|agents}/{key}`。
 *
 * - 请求体**只有** `knowledge_base_ids`（后端 `extra="forbid"`，多字段直接 `422`）；
 * - 成功 ⇒ 返回**服务端回读值**（`binding`），调用方据此提示并**重新取数**（不本地猜结果）；
 * - 失败 ⇒ 抛 `ScopeWriteError`（带分类），调用方**就地呈现**且**不关闭抽屉**。
 */
export async function saveScopeBinding(
  input: ScopeWriteInput,
  fetchImpl?: typeof fetch,
): Promise<ScopeWriteResult> {
  if (mode === 'mock') {
    // 样例模式没有服务端 ⇒ 不伪造回读值，且明确"没有写入任何数据"
    return { binding: null, written: false, note: MOCK_WRITE_NOTE }
  }

  try {
    const binding = await request<KnowledgeBinding>(bindingPath(input.binding_type, input.binding_key), {
      method: PUT,
      body: { knowledge_base_ids: input.knowledge_base_ids },
      fetchImpl,
    })
    return { binding, written: true, note: WRITE_OK_NOTE }
  } catch (error) {
    toWriteError(error)
  }
}

/**
 * 开发期样例数据（虚构内容，无 PII：不含手机号 / 用户 ID / 租户 ID / 密钥）。
 * **只在 `import.meta.env.DEV` 分支里存在** ⇒ 生产构建里整块被摇掉（构建后 grep 应为 0 命中）。
 * 刻意包含一行**未绑定**（`knowledge_base_ids: []`），用于断言"尚未绑定"不被渲染成"0 条"。
 */
const MOCK_ROLE_ROWS: ScopeRow[] = import.meta.env.DEV
  ? [
      { binding_type: 'role', binding_key: 'ops', name: '运营', status: 'active', knowledge_base_ids: ['kb-ops-handbook', 'kb-brand-assets'] },
      { binding_type: 'role', binding_key: 'rd', name: '研发', status: 'active', knowledge_base_ids: ['kb-tech-docs'] },
      { binding_type: 'role', binding_key: 'sales', name: '销售', status: 'active', knowledge_base_ids: [] },
      { binding_type: 'role', binding_key: 'finance', name: '财务', status: 'disabled', knowledge_base_ids: ['kb-finance-policy'] },
    ]
  : []

const MOCK_AGENT_ROWS: ScopeRow[] = import.meta.env.DEV
  ? [
      { binding_type: 'agent', binding_key: 'sample-content-ops', name: '内容运营助手', status: 'active', knowledge_base_ids: ['kb-ops-handbook'] },
      { binding_type: 'agent', binding_key: 'sample-rd-spec', name: '研发需求助理', status: 'active', knowledge_base_ids: ['kb-tech-docs', 'kb-api-contract'] },
    ]
  : []

const MOCK_AUDITS: KnowledgeAuditEntry[] = import.meta.env.DEV
  ? [
      {
        binding_type: 'role',
        binding_key: 'ops',
        old_knowledge_base_ids: [],
        new_knowledge_base_ids: ['kb-ops-handbook', 'kb-brand-assets'],
        actor_id: '示例操作者 01',
        occurred_at: '2026-09-19T10:25:43Z',
      },
      {
        binding_type: 'agent',
        binding_key: 'sample-rd-spec',
        old_knowledge_base_ids: ['kb-tech-docs'],
        new_knowledge_base_ids: ['kb-tech-docs', 'kb-api-contract'],
        actor_id: '示例操作者 01',
        occurred_at: '2026-09-18T16:30:00Z',
      },
    ]
  : []

/**
 * 开发期样例知识库清单（虚构内容，无 PII）。**只在 `import.meta.env.DEV` 分支里存在** ⇒
 * 生产构建里整块被摇掉（构建后 grep 应为 0 命中）。
 * 刻意含一条 `binding_only`（绑定里有、清单没返回），用于断言"配错 / 库已删"会被提醒出来。
 */
const MOCK_KNOWLEDGE_BASES: KnowledgeBaseCandidateList = import.meta.env.DEV
  ? {
      upstream_available: true,
      source: 'upstream',
      items: [
        { knowledge_base_id: 'kb-ops-handbook', name: '运营手册', origin: 'upstream' },
        { knowledge_base_id: 'kb-brand-assets', name: '品牌素材', origin: 'upstream' },
        { knowledge_base_id: 'kb-tech-docs', name: '研发文档', origin: 'upstream' },
        { knowledge_base_id: 'kb-finance-policy', name: '财务制度', origin: 'upstream' },
        { knowledge_base_id: 'kb-api-contract', name: null, origin: 'upstream' },
        { knowledge_base_id: 'kb-legacy-sample', name: null, origin: 'binding_only' },
      ],
      note: null,
    }
  : { upstream_available: false, source: 'local_only', items: [], note: '' }