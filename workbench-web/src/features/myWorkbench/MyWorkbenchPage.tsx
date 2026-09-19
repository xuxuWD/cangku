/**
 * 我的工作台（首页，第 3 轮）。
 *
 * 布局：两栏 —— 左 2/3（待办 + 最近使用）、右 1/3（日程 + 快捷入口）；栅格 gap 16 / 24，卡片间距 16。
 * 数据：**未接后端**，全部来自 `services/myWorkbenchService.ts`（样例数据），页面顶部给出统一标识。
 * 四块各自独立取数：一块失败不影响其它块；`forbidden` 与其它失败分别映射为界面的 forbidden / error 态。
 */
import { useEffect, useState } from 'react'
import { Alert, Col, Row, Space } from 'antd'
import { PageContainer } from '../../components'
import type { ContentStateKind } from '../../components'
import { tokens } from '../../theme/tokens'
import { QuickActions } from './components/QuickActions'
import { RecentPanel } from './components/RecentPanel'
import { SchedulePanel } from './components/SchedulePanel'
import { TodoPanel } from './components/TodoPanel'
import {
  SAMPLE_DATA_BADGE,
  SCHEDULE_ABSENT,
  fetchQuickActions,
  fetchRecent,
  fetchSchedule,
  fetchTodos,
  panelStateOfError,
} from './services/myWorkbenchService'
import type { QuickActionItem, RecentItem, SamplePayload, TodoItem } from './types'

type PanelViewState = ContentStateKind | 'ready'

/** 空样例信封：取数完成前用的占位（此时界面处于 loading，不会渲染这些内容）。 */
const EMPTY_TODOS: SamplePayload<TodoItem> = { sample: true, items: [] }
const EMPTY_RECENT: SamplePayload<RecentItem> = { sample: true, items: [] }

/**
 * 单块取数：把「加载中 / 就绪 / 失败」收敛成一份状态。
 * 用 `active` 标记丢弃过期结果，避免卸载后回写 state。
 */
function usePanelData<T>(loader: () => Promise<T>, fallback: T) {
  const [state, setState] = useState<PanelViewState>('loading')
  const [data, setData] = useState<T>(fallback)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let active = true
    setState('loading')
    loader()
      .then((next) => {
        if (!active) return
        setData(next)
        setState('ready')
      })
      .catch((error: unknown) => {
        if (!active) return
        setState(panelStateOfError(error))
      })
    return () => {
      active = false
    }
  }, [loader, attempt])

  return { state, data, reload: () => setAttempt((value) => value + 1) }
}

export function MyWorkbenchPage() {
  const todos = usePanelData(fetchTodos, EMPTY_TODOS)
  const recent = usePanelData(fetchRecent, EMPTY_RECENT)
  const schedule = usePanelData(fetchSchedule, SCHEDULE_ABSENT)
  const actions = usePanelData<QuickActionItem[]>(fetchQuickActions, [])

  return (
    <PageContainer title="我的工作台" description="待办、最近使用、日程与快捷入口。">
      {/* 诚实性标识：本页样例数据必须一眼可辨，不允许假装成真实数据。 */}
      <Alert
        type="warning"
        showIcon
        message={SAMPLE_DATA_BADGE}
        description="本页「待办」与「最近使用」为样例数据；「日程」后端无实体、「快捷入口」为前端静态定义。接口口径见 docs/contracts/my-workbench-api.md。"
        style={{ marginBottom: tokens.spacing.md }}
      />

      <Row gutter={[tokens.spacing.md, tokens.spacing.lg]}>
        <Col xs={24} lg={16}>
          <Space direction="vertical" size={tokens.spacing.md} style={{ width: '100%' }}>
            <TodoPanel
              items={todos.data.items}
              sample={todos.data.sample}
              state={todos.state}
              stateDescription="待办列表加载失败，请稍后重试。"
              onRetry={todos.reload}
            />
            <RecentPanel
              items={recent.data.items}
              sample={recent.data.sample}
              state={recent.state}
              stateDescription="最近使用加载失败，请稍后重试。"
              onRetry={recent.reload}
            />
          </Space>
        </Col>

        <Col xs={24} lg={8}>
          <Space direction="vertical" size={tokens.spacing.md} style={{ width: '100%' }}>
            <SchedulePanel
              availability={schedule.data}
              state={schedule.state}
              stateDescription="日程块状态异常，请稍后重试。"
              onRetry={schedule.reload}
            />
            <QuickActions
              actions={actions.data}
              state={actions.state}
              stateDescription="快捷入口加载失败，请稍后重试。"
              onRetry={actions.reload}
            />
          </Space>
        </Col>
      </Row>
    </PageContainer>
  )
}