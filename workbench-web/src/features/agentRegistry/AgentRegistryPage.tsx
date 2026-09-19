/**
 * 数字员工注册中心（第 5 轮，AD-01 管理后台视角）。
 *
 * - **仅管理角色可见**：员工访问时由 `PermissionGuard` 渲染无权限态（原因 + 申请入口），
 *   **既不请求数据、也不渲染空表格**；
 * - 统一视图用 `DataTable`（与员工侧"卡片"刻意不同形）：含创建者与使用统计；
 * - 筛选条件**原样透传**给适配层（一次提交带上全部参数），页面不做任何前端过滤；
 * - 状态保真：运行 / 成功率口径缺失时如实显示"未验证 / 样本不足 / 未配置"，**绝不显示 0% 或"成功"**。
 */
import { useMemo, useState } from 'react'
import { Alert, Button, Space } from 'antd'
import type { TableColumnsType } from 'antd'
import { DataTable, DangerConfirm, PageContainer, PermissionGuard } from '../../components'
import type { ContentStateKind } from '../../components'
import { usePanelData } from '../../utils/panelData'
import { SAMPLE_DATA_BADGE } from '../../utils/serviceKit'
import { tokens } from '../../theme/tokens'
import { AUTONOMY_LABEL } from '../myAgents/components/CapabilityPack'
import type { AgentStatus } from '../myAgents/types'
import { AgentDetailDrawer } from './components/AgentDetailDrawer'
import { RegistryFilters } from './components/RegistryFilters'
import { RegistryStats } from './components/RegistryStats'
import { LastRunCell, StatusCell, UsageCell } from './components/cells'
import { fetchRegistryAgents, fetchRegistryStats, roleTemplateOptions, setAgentStatus } from './services/agentRegistryService'
import type { RegistryFilters as RegistryFiltersValue, RegistryListPayload, RegistryRow, RegistryStatsPayload } from './types'
import { NO_FILTERS, REGISTRY_PAGE_SIZE } from './types'

/** 取数完成前用的空占位（此时界面处于 loading，不会渲染这些内容）。 */
const EMPTY_LIST: RegistryListPayload = { sample: true, items: [], total: 0, limit: REGISTRY_PAGE_SIZE, offset: 0 }
const EMPTY_STATS: RegistryStatsPayload = {
  sample: true,
  total: 0,
  active: 0,
  disabled: 0,
  draft: 0,
  ran_last_7d: null,
}

/** 非就绪态的文案：加载态用统一加载文案；无权限 / 失败 / 空必须分开说清楚。 */
const LIST_STATE_DESCRIPTION: Record<ContentStateKind, string | undefined> = {
  loading: undefined,
  empty: '没有符合条件的数字员工。',
  error: '数字员工列表加载失败，请稍后重试。',
  forbidden: '无权限查看数字员工列表，请联系管理员。',
}

/** 管理侧表格列（列名与契约文档逐字段对应）。 */
const COLUMNS: TableColumnsType<RegistryRow> = [
  { title: '员工标识', dataIndex: 'agent_key', key: 'agent_key', width: 176 },
  { title: '名称', dataIndex: 'name', key: 'name' },
  {
    title: '所属岗位',
    key: 'role_key',
    width: 152,
    render: (_, row) => `${row.template.name}（${row.role_key}）`,
  },
  { title: '创建者', dataIndex: 'created_by', key: 'created_by', width: 144 },
  { title: '状态', key: 'status', width: 96, render: (_, row) => <StatusCell row={row} /> },
  {
    title: '能力标签',
    key: 'capability',
    width: 224,
    render: (_, row) =>
      `Skill ${row.template.skills.length} · 知识范围 ${row.template.knowledge_scopes.length} · 自治档 ${AUTONOMY_LABEL[row.template.autonomy_level]}`,
  },
  { title: '使用统计', key: 'usage', width: 232, render: (_, row) => <UsageCell usage={row.usage} /> },
  { title: '最近使用', key: 'last_run_at', width: 184, render: (_, row) => <LastRunCell row={row} /> },
]

/** 表格区域（hooks 都在这里，权限门在外层，避免条件调用 hooks）。 */
function RegistryBoard() {
  const [filters, setFilters] = useState<RegistryFiltersValue>(NO_FILTERS)
  const [page, setPage] = useState(1)
  const [detail, setDetail] = useState<RegistryRow | null>(null)
  const [statusChange, setStatusChange] = useState<{ row: RegistryRow; next: AgentStatus } | null>(null)
  const [actionNote, setActionNote] = useState<string | null>(null)

  // 查询对象只随筛选 / 分页变化 ⇒ 变化即重新取数（`deps` 显式声明何时重取）。
  const query = useMemo(() => ({ ...filters, page, pageSize: REGISTRY_PAGE_SIZE }), [filters, page])
  const agents = usePanelData(() => fetchRegistryAgents(query), EMPTY_LIST, [query])
  const stats = usePanelData(fetchRegistryStats, EMPTY_STATS)

  const columns: TableColumnsType<RegistryRow> = [
    ...COLUMNS,
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: (_, row) => {
        const isDisabled = row.status === 'disabled'
        const isDraft = row.status === 'draft'
        return (
          <Space size={tokens.spacing.sm}>
            <Button size="small" onClick={() => setDetail(row)}>
              详情
            </Button>
            {/* 草稿尚未发布，启用 / 停用对它没有意义：禁用并说明，而不是藏起来 */}
            <Button
              size="small"
              danger={!isDisabled}
              disabled={isDraft}
              title={isDraft ? '草稿尚未发布，无需启用或停用' : undefined}
              onClick={() => setStatusChange({ row, next: isDisabled ? 'active' : 'disabled' })}
            >
              {isDisabled ? '启用' : '停用'}
            </Button>
          </Space>
        )
      },
    },
  ]

  /** 筛选：条件变化一律回到第 1 页，并把参数整体交给适配层（前端不过滤）。 */
  const handleFilterChange = (next: RegistryFiltersValue) => {
    setFilters(next)
    setPage(1)
  }

  const handleReset = () => {
    setFilters(NO_FILTERS)
    setPage(1)
  }

  const handleStatusConfirmed = async () => {
    const target = statusChange
    if (!target) return
    setStatusChange(null)
    const verb = target.next === 'disabled' ? '停用' : '启用'
    try {
      const result = await setAgentStatus({ agent_key: target.row.agent_key, status: target.next })
      setActionNote(`已提交${verb}「${target.row.name}」；${result.note}`)
    } catch {
      setActionNote(`${verb}未完成：后端接口尚未接线或未通过校验，本次没有写入任何数据。`)
    }
  }

  const tableState: ContentStateKind | 'ready' =
    agents.state === 'ready' && agents.data.items.length === 0 ? 'empty' : agents.state

  return (
    <Space direction="vertical" size={tokens.spacing.md} style={{ width: '100%' }}>
      {/* 诚实性标识：样例数据必须一眼可辨，不允许假装成真实数据 */}
      <Alert
        type="warning"
        showIcon
        message={SAMPLE_DATA_BADGE}
        description="本页列表与指标均为样例数据；「最近 7 天有运行」的运行口径未接入，界面按「未验证」如实呈现。接口口径见 docs/contracts/agent-registry-api.md。"
      />
      {actionNote && <Alert type="info" showIcon message={actionNote} />}

      <RegistryStats
        stats={stats.data}
        state={stats.state}
        stateDescription="指标统计加载失败，请稍后重试。"
        onRetry={stats.reload}
      />

      <RegistryFilters
        filters={filters}
        templates={roleTemplateOptions()}
        onChange={handleFilterChange}
        onReset={handleReset}
      />

      <DataTable<RegistryRow>
        columns={columns}
        rows={agents.data.items}
        rowKey={(row) => row.agent_key}
        state={tableState}
        stateDescription={LIST_STATE_DESCRIPTION[tableState === 'ready' ? 'empty' : tableState]}
        onRetry={agents.reload}
        pagination={{
          page,
          pageSize: REGISTRY_PAGE_SIZE,
          total: agents.data.total,
          onChange: (nextPage) => setPage(nextPage),
        }}
      />

      <AgentDetailDrawer open={detail !== null} agent={detail} onClose={() => setDetail(null)} />

      <DangerConfirm
        open={statusChange !== null}
        title={statusChange?.next === 'disabled' ? `停用「${statusChange.row.name}」？` : `启用「${statusChange?.row.name ?? ''}」？`}
        description={
          statusChange?.next === 'disabled'
            ? '停用后该员工不能再承接新任务；历史任务与运行记录不受影响（停用不删除）。'
            : '启用后该员工可以重新承接新任务；能力包与知识绑定沿用原岗位模板。'
        }
        confirmWord={statusChange?.next === 'disabled' ? '停用' : '启用'}
        onConfirm={handleStatusConfirmed}
        onCancel={() => setStatusChange(null)}
      />
    </Space>
  )
}

export function AgentRegistryPage() {
  return (
    <PageContainer
      title="数字员工管理"
      description="数字员工注册中心：全员统一视图（筛选 / 指标 / 启停 / 详情），仅管理角色可见。"
    >
      {/* 无权限时渲染"无权限态（原因 + 申请入口）"，不请求数据、也不渲染空表格 */}
      <PermissionGuard capability="agent.manage">
        <RegistryBoard />
      </PermissionGuard>
    </PageContainer>
  )
}