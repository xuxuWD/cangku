/**
 * 我的数字员工（第 4 轮；第 6 轮接线批 2 接线）。
 *
 * - 卡片式列表（**非表格**，PRD 明确要求卡片），按归属分区：我创建的 / 共享给我的 / **归属无法判定**；
 * - 从岗位模板创建（DE-01）：**本批未接入**（后端无员工侧创建接口）⇒ 入口保留但**禁用 + 给原因**；
 * - 卡片操作：发起任务（DE-03 跳转占位）、查看详情（只读）、配置（可改名称与工作范围）、停用（走 `DangerConfirm`）；
 * - 数据：`http` 模式来自真实后端接口（`services/myAgentsService.ts` 是唯一接线点）。
 */
import { useState } from 'react'
import { Alert, Button, Space } from 'antd'
import { ContentState, DangerConfirm, EmptyState, PageContainer } from '../../components'
import type { ContentStateKind } from '../../components'
import { hasCapability, useSession } from '../../app/session'
import { SAMPLE_DATA_BADGE } from '../../utils/serviceKit'
import type { SamplePayload } from '../../utils/serviceKit'
import { usePanelData } from '../../utils/panelData'
import { tokens } from '../../theme/tokens'
import { AgentDetailDrawer } from './components/AgentDetailDrawer'
import { AgentGrid } from './components/AgentGrid'
import { CreateAgentDrawer } from './components/CreateAgentDrawer'
import {
  CREATE_AGENT_NOTE,
  ROLE_TEMPLATE_NOTE,
  createAgent,
  disableAgent,
  fetchMyAgents,
  fetchRoleTemplates,
  isConnected,
  updateAgent,
} from './services/myAgentsService'
import type { AgentItem, CreateAgentInput, RoleTemplate, UpdateAgentInput } from './types'

/** 取数完成前用的空占位（此时界面处于 loading，不会渲染这些内容）。 */
const EMPTY_AGENTS: SamplePayload<AgentItem> = { sample: true, items: [] }
const EMPTY_TEMPLATES: SamplePayload<RoleTemplate> = { sample: true, items: [] }

/**
 * 非就绪态的文案：加载态用统一加载文案；无权限与失败必须分开说清楚。
 *
 * ⚠️ 2026-09-25 更正（真机走查发现）—— 原注释与两条 `forbidden` 文案的前提**均已失效**：
 *  - 原文「该目录接口**仅超级管理员**」⇒ OP-01（e5626aa）已改成**四档业务角色**白名单
 *    （`employee` / `department_lead` / `ceo` / `super_admin`）。
 *    今日 403 的真实原因是「**当前角色不在该白名单内**」（如 `customer_admin`、未登录），
 *    不是"只对超管开放" —— 写成后者会让用户以为"要提权"，而实际是"这个角色面不含目录"。
 *  - 原文「请确认该员工**是否已共享给你**」⇒ OP-01 后**未共享的员工根本不出现在列表里**
 *    （服务端在仓储层按 owner∪shares 过滤，**不是 403**）。403 与"没被共享"**是两件事**，
 *    把它写进 403 文案会引导用户去找一个不存在的"共享开关"。
 */
function listStateDescription(connected: boolean): Record<ContentStateKind, string | undefined> {
  return {
    loading: undefined,
    empty: undefined,
    error: '数字员工列表加载失败，请稍后重试。',
    forbidden: connected
      ? '无权限查看数字员工列表：当前角色不在可访问目录的范围内（员工、部门负责人、企业负责人、超级管理员可访问；客户管理员不可）。'
      : '无权限查看数字员工列表，请联系管理员确认你的角色。',
  }
}

export function MyAgentsPage() {
  const role = useSession((state) => state.role)
  const agents = usePanelData(fetchMyAgents, EMPTY_AGENTS)
  const templates = usePanelData(fetchRoleTemplates, EMPTY_TEMPLATES)

  const [createOpen, setCreateOpen] = useState(false)
  const [detail, setDetail] = useState<{ agent: AgentItem; mode: 'view' | 'edit' } | null>(null)
  const [disabling, setDisabling] = useState<AgentItem | null>(null)
  const [actionNote, setActionNote] = useState<string | null>(null)

  /** 是否已接后端（`http`）：决定"未接入"文案与"创建"入口的可用性。 */
  const connected = isConnected()
  const listDescriptions = listStateDescription(connected)

  // 管理他人员工需要 `agent.manage` 能力（本地桩判定；真实判定在服务端）。
  const manageShared = hasCapability(role, 'agent.manage')

  /** 写操作的统一收口：成功/失败都给一句可读的说明，绝不静默。 */
  const runWrite = async (action: () => Promise<{ note: string }>, okText: string) => {
    try {
      const result = await action()
      setActionNote(`${okText}；${result.note}`)
    } catch (error) {
      // 失败必须如实说清楚：优先用请求层已 sanitize 的文案，不把失败伪装成"已完成"
      const detail = error instanceof Error ? error.message : ''
      setActionNote(`操作未完成：${detail || '后端接口未通过校验'}本次没有写入任何数据。`)
    }
  }

  const handleCreate = async (input: CreateAgentInput) => {
    await runWrite(() => createAgent(input), `已提交创建「${input.name}」（岗位：${input.role_key}）`)
    setCreateOpen(false)
  }

  const handleUpdate = async (input: UpdateAgentInput) => {
    await runWrite(() => updateAgent(input), `已提交修改「${input.name}」`)
    setDetail(null)
  }

  const handleDisable = async () => {
    const target = disabling
    if (!target) return
    setDisabling(null)
    await runWrite(() => disableAgent(target.agent_key), `已提交停用「${target.name}」`)
  }

  const items = agents.data.items
  const mine = items.filter((agent) => agent.ownership === 'mine')
  const shared = items.filter((agent) => agent.ownership === 'shared')
  // 归属无法判定的行单独成区（**不能**混进"我创建的"，那是在编造归属）
  const unknown = items.filter((agent) => agent.ownership === 'unknown')

  const listBody =
    agents.state !== 'ready' ? (
      <ContentState
        state={agents.state}
        description={listDescriptions[agents.state]}
        onRetry={agents.reload}
        boxed={false}
      />
    ) : items.length === 0 ? (
      <EmptyState
        boxed={false}
        description={
          connected
            ? '后端目录里还没有数字员工。创建本批未接入（需由管理员在目录中纳管）。'
            : '还没有数字员工。可以从岗位模板创建一个。'
        }
        actionText={connected ? undefined : '立即创建'}
        onAction={() => setCreateOpen(true)}
      />
    ) : (
      <AgentGrid
        mine={mine}
        shared={shared}
        unknown={unknown}
        manageShared={manageShared}
        onStartTask={(agent) =>
          setActionNote(`发起任务「${agent.name}」：DE-03 属后续轮次，本轮为跳转占位（未接路由）。`)
        }
        onOpenDetail={(agent) => setDetail({ agent, mode: 'view' })}
        onConfigure={(agent) => setDetail({ agent, mode: 'edit' })}
        onRequestDisable={setDisabling}
      />
    )

  return (
    <PageContainer
      title="我的数字员工"
      description="卡片式查看我创建与被共享的数字员工，并可从岗位模板创建新员工。"
      extra={
        // 未接入的能力一律"禁用 + 给原因"，不静默隐藏入口
        <Button
          type="primary"
          disabled={connected}
          title={connected ? CREATE_AGENT_NOTE : undefined}
          onClick={() => setCreateOpen(true)}
        >
          从岗位模板创建
        </Button>
      }
    >
      <Space direction="vertical" size={tokens.spacing.md} style={{ width: '100%' }}>
        {/* 诚实性标识：样例数据 / 已接后端都必须一眼可辨，不允许含糊 */}
        {connected ? (
          <Alert
            type="info"
            showIcon
            message="已接入后端数字员工目录接口"
            // ⚠️ 2026-09-25（真机走查后更正）：原描述写「后端为管理目录口径，仅超级管理员可见」
            // 与「后端不下发当前用户标识，因此归属按无法判定呈现」—— **两条均已失效**，
            // 且与同页实际显示「我创建的」**自相矛盾**。OP-01（e5626aa）已放开读档并按 owner∪shares 过滤、
            // 视图也下发了 `owner_user_id`。单测抓不到这处（不断言本字符串），只有真机走查能发现。
            // ⚠️ AntD `Alert` 的 `description` **不渲染 Markdown** —— 别在这里写 `**粗体**` 或反引号，
            // 否则用户看到的是字面星号/反引号。下面刻意用中文引号与全角括号做强调。
            description={`列表与「配置」「停用」走真实后端接口。目录读档已对四档业务角色放开，服务端在仓储层按「归属自己 ∪ 被共享」过滤后返回（客户管理员与未登录仍 403）。归属按后端下发的 owner_user_id 逐行判定；缺本人标识或后端未下发时按「无法判定」呈现（fail-closed，绝不臆测成「我创建的」）。未接入：岗位模板列表、员工侧详情；后端不下发运行记录与使用统计，故运行一律按「未验证」呈现。${CREATE_AGENT_NOTE}`}
          />
        ) : (
          <Alert
            type="warning"
            showIcon
            message={SAMPLE_DATA_BADGE}
            description="本页数字员工与岗位模板均为样例数据；能力包数据来源为 docs/contracts/role-templates.md，接口口径见 docs/contracts/my-agents-api.md。"
          />
        )}
        {actionNote && <Alert type="info" showIcon message={actionNote} />}
        {listBody}
      </Space>

      <CreateAgentDrawer
        open={createOpen}
        templates={templates.data.items}
        state={templates.state}
        stateDescription={connected ? ROLE_TEMPLATE_NOTE : '岗位模板加载失败，请稍后重试。'}
        onRetry={templates.reload}
        onClose={() => setCreateOpen(false)}
        onSubmit={handleCreate}
      />

      <AgentDetailDrawer
        open={detail !== null}
        agent={detail?.agent ?? null}
        mode={detail?.mode ?? 'view'}
        onClose={() => setDetail(null)}
        onSubmit={handleUpdate}
      />

      <DangerConfirm
        open={disabling !== null}
        title={`停用「${disabling?.name ?? ''}」？`}
        description="停用后该员工不能再承接新任务；历史任务与运行记录不受影响（停用不删除）。"
        confirmWord="停用"
        onConfirm={handleDisable}
        onCancel={() => setDisabling(null)}
      />
    </PageContainer>
  )
}