/**
 * 悬浮助手（B3 §6 + 验收 A7）
 *
 * | 规格要求 | 怎么做的 |
 * | --- | --- |
 * | 挂在 `body`、**路由切换不卸载** | 本组件由 `AppShell` 在**路由分支之外**渲染一次，不参与主区域的互斥显示 |
 * | `buildAttentionItems()` 跨模块统一「待你处理」 | 复用**既有**的 `fetchTodos()` —— 它就是「未读站内通知 + 待审批」的跨模块聚合（规格 §6 原话：数据源已经有了） |
 * | `buildSuggestedActions()` / 意图路由**纯规则** | 全在 `assistantRules.ts`（纯函数），**零模型调用**（§11 N3） |
 *
 * ⚠️ **如实登记的两条限制**：
 *  ① `fetchTodos()` 把通知的 `kind` **归一化掉了**（只剩 `notification_result`），
 *     所以五类里**只有「待审批」与「完成」区分得出来**；`待输入 / 受阻 / 失败` 需要更细的来源。
 *     **不做硬凑** —— 界面上照实说明。
 *  ② 「待你处理」与既有 `inbox` 页**是同一份数据源**（B3 §13.1 **V4 待裁决**：同一数据源还是合并）
 *     ⇒ 这里按"同一数据源、两处呈现"实现，**不预判 V4**。
 */
import { useMemo } from 'react'
import { Badge, Button, Drawer, Input, List, Space, Tag, Typography } from 'antd'
import { tokens } from '../theme/tokens'
import { usePanelData } from '../utils/panelData'
import { fetchTodos } from '../features/myWorkbench/services/myWorkbenchService'
import type { TodoItem, TodoKind } from '../features/myWorkbench/types'
import {
  INTENT_LABEL,
  attentionBadgeText,
  buildAttentionItems,
  buildSuggestedActions,
  routeIntent,
} from './assistantRules'
import type { AttentionKind } from './assistantRules'
import type { ShellRoute } from './shellRouter'
import { showObject, useShellStore } from './shellStore'

/**
 * `TodoKind` → 本助手的受控枚举。
 *
 * **只映射数据支持得住的两类**：四类审批 ⇒ `待审批`；其余（`notification_result` / `other`）
 * ⇒ `完成`（通知类都是"结果已出"）。中间三类**当前来源区分不出来，故不产出**。
 */
export function attentionKindOf(kind: TodoKind): AttentionKind {
  switch (kind) {
    case 'task_approval':
    case 'plan_proposal':
    case 'run_approval':
    case 'account_registration':
      return '待审批'
    default:
      return '完成'
  }
}

interface AttentionRow {
  id: string
  kind: AttentionKind
  title: string
  targetId: string | null
  targetType: string | null
}

const NO_TODOS = { sample: false, items: [] as TodoItem[] }

export function FloatingAssistant({ route }: { route: ShellRoute }) {
  const open = useShellStore((state) => state.assistantOpen)
  const setOpen = useShellStore((state) => state.setAssistantOpen)
  const draft = useShellStore((state) => state.assistantDraft)
  const setDraft = useShellStore((state) => state.setAssistantDraft)

  const todos = usePanelData(() => fetchTodos(), NO_TODOS)

  const ordered = useMemo<AttentionRow[]>(() => {
    const rows = (todos.data?.items ?? []).map((item) => ({
      id: item.target_id,
      kind: attentionKindOf(item.kind),
      title: item.title,
      targetId: item.target_id ?? null,
      targetType: item.target_type,
    }))
    return buildAttentionItems(rows)
  }, [todos.data])

  const approvalCount = ordered.filter((row) => row.kind === '待审批').length
  const match = routeIntent(draft)

  return (
    <>
      {/* 悬浮球：常驻右下角。它由 AppShell 渲染在路由分支之外 ⇒ **切换路由不卸载**（验收 A7） */}
      <div
        data-testid="floating-assistant"
        style={{ position: 'fixed', right: tokens.spacing.lg, bottom: tokens.spacing.lg, zIndex: 1000 }}
      >
        <Badge count={ordered.length} size="small">
          <Button type="primary" shape="circle" size="large" aria-label="打开悬浮助手" onClick={() => setOpen(true)}>
            助
          </Button>
        </Badge>
      </div>

      <Drawer
        title="悬浮助手"
        placement="right"
        width={380}
        open={open}
        onClose={() => setOpen(false)}
        // 不销毁：关掉再打开不重新取数（与"路由切换不卸载"同一精神）
        destroyOnHidden={false}
      >
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Typography.Text type="secondary">{attentionBadgeText(ordered.length)}</Typography.Text>

          <Typography.Text type="secondary">
            数据源 = 既有「我的工作台」待办（未读站内通知 + 待审批：`GET /api/v1/inbox` 与
            `GET /api/v1/approvals/pending`）。排序口径：待审批 &gt; 待输入 &gt; 受阻 &gt; 失败 &gt; 完成；
            <b>当前来源只能区分出「待审批」与「完成」两类，其余不硬凑</b>。
          </Typography.Text>

          {approvalCount > 0 && <Tag color="warning">{`其中待你审批 ${approvalCount} 条`}</Tag>}

          <List
            size="small"
            locale={{ emptyText: '暂无待你处理' }}
            dataSource={ordered}
            renderItem={(row) => {
              const actions = buildSuggestedActions(row.kind)
              return (
                <List.Item>
                  <Space direction="vertical" size={2} style={{ width: '100%' }}>
                    <Space wrap>
                      <Tag>{row.kind}</Tag>
                      <Typography.Text>{row.title}</Typography.Text>
                    </Space>
                    {actions.length > 0 && (
                      <Typography.Text type="secondary">
                        {`建议（规则生成，未调用模型）：${actions.join('；')}`}
                      </Typography.Text>
                    )}
                    {row.targetId && (
                      <Button
                        size="small"
                        onClick={() => {
                          // ① 先把**已知的详情**上报给壳（否则右栏只有 id、什么都显示不出来）；
                          // ② **保持当前页不变**，只把对象推到右栏；写进 URL ⇒ 可分享 / 可刷新。
                          const type = row.targetType ?? 'task'
                          showObject(
                            { id: String(row.targetId), type, title: row.title, status: row.kind },
                            { view: route.view, panel: 'brief' },
                          )
                          setOpen(false)
                        }}
                      >
                        在右栏查看
                      </Button>
                    )}
                  </Space>
                </List.Item>
              )
            }}
          />

          <div>
            <Typography.Text type="secondary">
              意图路由是中文正则（§11 N3：规则层不用 LLM）。试试「派给内容岗写篇稿」或「待我批的」。
            </Typography.Text>
            <Input
              style={{ marginTop: tokens.spacing.sm }}
              value={draft}
              placeholder="派给内容岗写篇稿"
              onChange={(event) => setDraft(event.target.value)}
            />
            <Space style={{ marginTop: tokens.spacing.sm }} align="center">
              <Tag>{INTENT_LABEL[match.intent]}</Tag>
              {match.matched && <Typography.Text type="secondary">{`命中：/${match.matched}/`}</Typography.Text>}
            </Space>
          </div>
        </Space>
      </Drawer>
    </>
  )
}
