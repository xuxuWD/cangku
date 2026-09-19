/**
 * 我的数字员工（第 4 轮）：DE-01 / DE-02 / DE-03 的员工侧部分。
 *
 * - 卡片式列表（**非表格**，PRD 明确要求卡片），按归属分区：我创建的 / 共享给我的；
 * - 从岗位模板创建（DE-01）：选模板 → 继承能力预览 → 填名称与工作范围 → 提交（mock，未写入后端）；
 * - 卡片操作：发起任务（DE-03 跳转占位）、查看详情（只读）、配置（可改名称与工作范围）、停用（走 `DangerConfirm`）；
 * - 数据：**未接后端**，全部来自 `services/myAgentsService.ts`（样例数据），页面顶部给出统一标识。
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
  createAgent,
  disableAgent,
  fetchMyAgents,
  fetchRoleTemplates,
  updateAgent,
} from './services/myAgentsService'
import type { AgentItem, CreateAgentInput, RoleTemplate, UpdateAgentInput } from './types'

/** 取数完成前用的空占位（此时界面处于 loading，不会渲染这些内容）。 */
const EMPTY_AGENTS: SamplePayload<AgentItem> = { sample: true, items: [] }
const EMPTY_TEMPLATES: SamplePayload<RoleTemplate> = { sample: true, items: [] }

/** 列表非就绪态的文案：加载态用统一加载文案；无权限与失败必须分开说清楚。 */
const LIST_STATE_DESCRIPTION: Record<ContentStateKind, string | undefined> = {
  loading: undefined,
  empty: undefined,
  error: '数字员工列表加载失败，请稍后重试。',
  forbidden: '无权限查看数字员工列表，请确认该员工是否已共享给你，或联系管理员。',
}

export function MyAgentsPage() {
  const role = useSession((state) => state.role)
  const agents = usePanelData(fetchMyAgents, EMPTY_AGENTS)
  const templates = usePanelData(fetchRoleTemplates, EMPTY_TEMPLATES)

  const [createOpen, setCreateOpen] = useState(false)
  const [detail, setDetail] = useState<{ agent: AgentItem; mode: 'view' | 'edit' } | null>(null)
  const [disabling, setDisabling] = useState<AgentItem | null>(null)
  const [actionNote, setActionNote] = useState<string | null>(null)

  // 管理他人员工需要 `agent.manage` 能力（本地桩判定；真实判定在服务端）。
  const manageShared = hasCapability(role, 'agent.manage')

  /** 写操作的统一收口：成功/失败都给一句可读的说明，绝不静默。 */
  const runWrite = async (action: () => Promise<{ note: string }>, okText: string) => {
    try {
      const result = await action()
      setActionNote(`${okText}；${result.note}`)
    } catch {
      setActionNote('操作未完成：后端接口尚未接线或未通过校验，本次没有写入任何数据。')
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

  const listBody =
    agents.state !== 'ready' ? (
      <ContentState
        state={agents.state}
        description={LIST_STATE_DESCRIPTION[agents.state]}
        onRetry={agents.reload}
        boxed={false}
      />
    ) : items.length === 0 ? (
      <EmptyState
        boxed={false}
        description="还没有数字员工。可以从岗位模板创建一个。"
        actionText="立即创建"
        onAction={() => setCreateOpen(true)}
      />
    ) : (
      <AgentGrid
        mine={mine}
        shared={shared}
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
        <Button type="primary" onClick={() => setCreateOpen(true)}>
          从岗位模板创建
        </Button>
      }
    >
      <Space direction="vertical" size={tokens.spacing.md} style={{ width: '100%' }}>
        {/* 诚实性标识：样例数据必须一眼可辨，不允许假装成真实数据 */}
        <Alert
          type="warning"
          showIcon
          message={SAMPLE_DATA_BADGE}
          description="本页数字员工与岗位模板均为样例数据；能力包数据来源为 docs/contracts/role-templates.md，接口口径见 docs/contracts/my-agents-api.md。"
        />
        {actionNote && <Alert type="info" showIcon message={actionNote} />}
        {listBody}
      </Space>

      <CreateAgentDrawer
        open={createOpen}
        templates={templates.data.items}
        state={templates.state}
        stateDescription="岗位模板加载失败，请稍后重试。"
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