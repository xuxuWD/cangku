/**
 * 我的工作台（首页）。
 *
 * 布局：两栏 —— 左 2/3（待办 + 最近使用）、右 1/3（日程 + 快捷入口）；栅格 gap 16 / 24，卡片间距 16。
 *
 * 第 6 轮（接线批 1）变化：
 *  - 数据层改用 **React Query**（`useQuery` / `useMutation`）：失败不自动重试，四态由界面显式呈现；
 *  - 待办 = 未读站内通知 + 待审批（真接口），「标记已读」调 `POST /api/v1/inbox/{id}/read` 并刷新列表；
 *  - 「最近使用」「日程」**仍未接入**：前者如实显示"未接入"说明（不是"加载失败"），后者后端无实体；
 *  - 四块各自独立取数：一块失败不影响其它块；401 由请求层统一清会话并回到登录页。
 */
import { useState } from 'react'
import { Alert, Col, Row, Space } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PageContainer } from '../../components'
import type { ContentStateKind } from '../../components'
import { ApiError } from '../../api/client'
import { tokens } from '../../theme/tokens'
import { QuickActions } from './components/QuickActions'
import { RecentPanel } from './components/RecentPanel'
import { SchedulePanel } from './components/SchedulePanel'
import { TodoPanel, todoRowKey } from './components/TodoPanel'
import {
  RECENT_NOTE,
  SAMPLE_DATA_BADGE,
  SCHEDULE_ABSENT,
  fetchQuickActions,
  fetchRecent,
  fetchSchedule,
  fetchTodos,
  isNotConnected,
  markTodoRead,
  panelStateOfError,
} from './services/myWorkbenchService'
import type { QuickActionItem, RecentItem, SamplePayload, TodoItem } from './types'

type PanelViewState = ContentStateKind | 'ready'

/** 取数完成前的空占位（此时面板处于 loading，不会渲染这些内容）。 */
const EMPTY_TODOS: SamplePayload<TodoItem> = { sample: false, items: [] }
const EMPTY_RECENT: SamplePayload<RecentItem> = { sample: false, items: [] }
const EMPTY_ACTIONS: QuickActionItem[] = []

/** 取数结果 → 面板四态：`forbidden` 与其它失败分开；加载态不给失败文案。 */
function panelState(query: { isPending: boolean; isError: boolean; error: unknown }): PanelViewState {
  if (query.isPending) return 'loading'
  if (query.isError) return panelStateOfError(query.error)
  return 'ready'
}

/** 失败文案：请求层已给"安全短文案"，这里只做兜底。 */
function failureMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

export function MyWorkbenchPage() {
  const queryClient = useQueryClient()
  const [notice, setNotice] = useState<string | null>(null)
  const [markingKey, setMarkingKey] = useState<string | null>(null)

  const todos = useQuery({ queryKey: ['my-workbench', 'todos'], queryFn: () => fetchTodos() })
  const recent = useQuery({ queryKey: ['my-workbench', 'recent'], queryFn: () => fetchRecent() })
  const schedule = useQuery({ queryKey: ['my-workbench', 'schedule'], queryFn: () => fetchSchedule() })
  const actions = useQuery({ queryKey: ['my-workbench', 'quick-actions'], queryFn: () => fetchQuickActions() })

  const markRead = useMutation({
    mutationFn: (item: TodoItem) => markTodoRead(item.inbox_id ?? ''),
    onSuccess: () => {
      setNotice('已标记为已读。')
      // 已读后列表口径变化（`unread_only=true`）⇒ 重新取数，不本地"猜"结果
      void queryClient.invalidateQueries({ queryKey: ['my-workbench', 'todos'] })
    },
    onError: (error: unknown) => setNotice(failureMessage(error, '标记已读失败，请稍后重试。')),
    onSettled: () => setMarkingKey(null),
  })

  // 「最近使用」：后端没有运行列表接口 ⇒ 如实显示"未接入"（不是"加载失败"，也不编数据）
  const recentNotConnected = recent.isError && isNotConnected(recent.error)
  const recentState: PanelViewState = recentNotConnected ? 'empty' : panelState(recent)
  const todosSample = todos.data?.sample === true
  const recentSample = recent.data?.sample === true

  return (
    <PageContainer title="我的工作台" description="待办、最近使用、日程与快捷入口。">
      {/* 诚实性标识：只在真的有样例数据时出现（接线后为真实数据，不再出现） */}
      {(todosSample || recentSample) && (
        <Alert
          type="warning"
          showIcon
          message={SAMPLE_DATA_BADGE}
          description="本页仍有样例数据；接口口径见 docs/contracts/my-workbench-api.md。"
          style={{ marginBottom: tokens.spacing.md }}
        />
      )}
      {notice && (
        <Alert type="info" showIcon message={notice} style={{ marginBottom: tokens.spacing.md }} />
      )}

      <Row gutter={[tokens.spacing.md, tokens.spacing.lg]}>
        <Col xs={24} lg={16}>
          <Space direction="vertical" size={tokens.spacing.md} style={{ width: '100%' }}>
            <TodoPanel
              items={todos.data?.items ?? EMPTY_TODOS.items}
              sample={todosSample}
              state={panelState(todos)}
              stateDescription={
                todos.isError ? failureMessage(todos.error, '待办列表加载失败，请稍后重试。') : undefined
              }
              onRetry={() => void todos.refetch()}
              onOpen={() => setNotice('跳转目标页尚未接入：本批只接数据，不接路由。')}
              onMarkRead={(item) => {
                setNotice(null)
                setMarkingKey(todoRowKey(item))
                markRead.mutate(item)
              }}
              markingKey={markingKey}
            />
            <RecentPanel
              items={recent.data?.items ?? EMPTY_RECENT.items}
              sample={recentSample}
              state={recentState}
              stateDescription={
                recentState === 'empty' || recentState === 'loading'
                  ? RECENT_NOTE
                  : failureMessage(recent.error, '最近使用加载失败，请稍后重试。')
              }
              onRetry={() => void recent.refetch()}
            />
          </Space>
        </Col>

        <Col xs={24} lg={8}>
          <Space direction="vertical" size={tokens.spacing.md} style={{ width: '100%' }}>
            <SchedulePanel
              availability={schedule.data ?? SCHEDULE_ABSENT}
              state={panelState(schedule)}
              stateDescription={failureMessage(schedule.error, '日程块状态异常，请稍后重试。')}
              onRetry={() => void schedule.refetch()}
            />
            <QuickActions
              actions={actions.data ?? EMPTY_ACTIONS}
              state={panelState(actions)}
              stateDescription={failureMessage(actions.error, '快捷入口加载失败，请稍后重试。')}
              onRetry={() => void actions.refetch()}
            />
          </Space>
        </Col>
      </Row>
    </PageContainer>
  )
}