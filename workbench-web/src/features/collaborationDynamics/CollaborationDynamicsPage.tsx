/**
 * 协同动态 —— 由 `admin-web/src/features/collaborationDynamics/CollaborationDynamicsPage.tsx` 合并移植。
 *
 * **移植口径（如实登记）**：
 *  - 业务能力**等价保留**：动态列表 / 三项统计（本页动态 · 涉及任务 · 等待审批）/ 刷新 / 四态；
 *  - 呈现层换成 **AntD + 项目组件库**（`PageContainer` / `DataTable` / `StatCard` / `StatusTag`），
 *    符合 ADR-0003；传输层换成全前端唯一请求层；
 *  - **目标落点（2026-09-23 换壳后更新）**：完整页面（任务详情）**尚未合并**，
 *    但壳有了**右栏「当前对象」**（B3 §5）⇒ 每行给出「在右栏查看」，把该对象上报给壳
 *    （顺带把 `?object=` 写进 URL ⇒ 可分享）。**两档都要说清**，不给点了没反应的按钮。
 *
 * 纪律：
 *  - 三项统计**只统计本页已加载的数据**，并在提示里写明「按本页统计」，不假装是全量；
 *  - 数字只在取数成功后展示；加载中与失败时显示占位，**不留误导性的 0**；
 *  - 失败按四态呈现，**不得**把失败说成"没有动态"。
 */
import { useMemo } from 'react'
import { Alert, Button, Space, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { DataTable, PageContainer, StatCard, StatusTag } from '../../components'
import type { ContentStateKind } from '../../components'
import { showObject } from '../../app/shellStore'
import { formatDateTime } from '../../utils/format'
import { usePanelData } from '../../utils/panelData'
import {
  CONNECTED_DESCRIPTION,
  CONNECTED_NOTICE,
  DYNAMICS_EMPTY_NOTE,
  SAMPLE_DATA_BADGE,
  SAMPLE_DESCRIPTION,
  fetchDynamics,
  isConnected,
} from './services/dynamicsService'
import { dynamicStatusLabel, dynamicStatusTone } from './types'
import type { CollaborationDynamic } from './types'

const LIST_STATE_TEXT: Record<Exclude<ContentStateKind, 'loading'>, string> = {
  empty: DYNAMICS_EMPTY_NOTE,
  error: '协同动态加载失败，请稍后重试。',
  forbidden: '当前账号没有查看协同动态的权限。',
}

const NO_ITEMS: CollaborationDynamic[] = []

export function CollaborationDynamicsPage() {
  const connected = isConnected()
  const dynamics = usePanelData(() => fetchDynamics(), NO_ITEMS)
  const { state, data: items, reload } = dynamics

  // 三项统计只统计**本页已加载**的数据，提示文案里写明口径，不冒充全量。
  const taskCount = useMemo(() => new Set(items.map((item) => item.aggregate_id)).size, [items])
  const pendingCount = useMemo(() => items.filter((item) => item.status === 'pending_approval').length, [items])

  // 就绪但没内容 ⇒ 显式转成 empty，否则会落到 AntD 表格自带的"暂无数据"
  const listState: ContentStateKind | 'ready' = state !== 'ready' ? state : items.length === 0 ? 'empty' : 'ready'

  const columns: TableColumnsType<CollaborationDynamic> = [
    {
      title: '动态',
      dataIndex: 'title',
      key: 'title',
      render: (_value, item) => (
        <Space direction="vertical" size={2} style={{ width: '100%' }}>
          <Typography.Text strong>{item.title}</Typography.Text>
          {/* 完整页面尚未合并，但**右栏能看摘要** ⇒ 给出可达的那一档，并如实说明另一档 */}
          <Typography.Text type="secondary">
            {`可在右栏看到该任务的简要信息；「任务详情」完整页面尚未合并进本工作台。`}
          </Typography.Text>
          <Button
            size="small"
            onClick={() =>
              showObject(
                { id: item.aggregate_id, type: 'task', title: item.title, status: dynamicStatusLabel(item.status) },
                { view: 'dynamics', panel: 'brief' },
              )
            }
          >
            在右栏查看
          </Button>
        </Space>
      ),
    },
    {
      title: '数字员工',
      dataIndex: 'employee_key',
      key: 'employee_key',
      width: 160,
      render: (value: string) => <Typography.Text>{value}</Typography.Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (_value, item) => <StatusTag tone={dynamicStatusTone(item.status)}>{dynamicStatusLabel(item.status)}</StatusTag>,
    },
    {
      title: '时间',
      dataIndex: 'occurred_at',
      key: 'occurred_at',
      width: 170,
      render: (value: string) => <Typography.Text type="secondary">{formatDateTime(value)}</Typography.Text>,
    },
  ]

  return (
    <PageContainer
      title="协同动态"
      description="展示当前账号有权限查看的任务动态；统计口径均为「按本页统计」。"
      extra={
        <Button onClick={reload} disabled={state === 'loading'}>
          {state === 'loading' ? '正在刷新' : '刷新'}
        </Button>
      }
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {connected ? (
          <Alert type="success" showIcon message={CONNECTED_NOTICE} description={CONNECTED_DESCRIPTION} />
        ) : (
          SAMPLE_DATA_BADGE !== '' && (
            <Alert type="warning" showIcon message={SAMPLE_DATA_BADGE} description={SAMPLE_DESCRIPTION} />
          )
        )}

        <Space size="middle" wrap>
          <StatCard label="本页动态" value={items.length} state={state} onRetry={reload} />
          <StatCard label="涉及任务" value={taskCount} state={state} onRetry={reload} />
          <StatCard label="等待审批" value={pendingCount} state={state} onRetry={reload} />
        </Space>

        <DataTable<CollaborationDynamic>
          columns={columns}
          rows={items}
          rowKey={(row) => row.event_id}
          state={listState}
          stateDescription={state !== 'ready' ? LIST_STATE_TEXT[state as Exclude<ContentStateKind, 'loading'>] : DYNAMICS_EMPTY_NOTE}
          onRetry={reload}
        />
      </Space>
    </PageContainer>
  )
}
