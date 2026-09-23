/**
 * 右栏「当前对象」（B3 §5：**收窄，不做通用舞台**）
 *
 * 规格 §5 逐字：
 * | 项 | 决定 |
 * | **放什么** | 当前对象的**简要信息** + **数字员工面板**（带该对象的上下文） |
 * | **不放什么** | ❌ 不做"可打开任意类型对象的通用舞台" |
 * | **逃生口** | 需要看全屏时**展开为整页**（此时主区域隐藏，返回即回） |
 *
 * ⚠️ **为什么收窄**（规格原文）：TabTin 的通用舞台（`context-space`）是 **92,805 行** —— 本文明确不追。
 * 所以本组件的对象类型是**受控枚举**（`OBJECT_TYPE_LABEL`），不是任意对象。
 *
 * ⚠️ **单一可信来源**：`objectId` / `objectType` 的来源是 **URL**（`shellRouter`）；
 * 本组件只从 `shellStore` 取**详情**。深链直接打开时只有 id、没有详情 ⇒ **如实说明，不编造标题**。
 *
 * ⚠️ **未实现（如实登记）**：规格 §5 要求「自动带上对象 id 作为上下文」，
 * 且 §13.2 R4 要求**无权读该对象时不注入**（静默降级，不是报错）。
 * 本组件只**显示要注入的字段名**；真正的注入与权限判定要等数字员工面板（B2）合并进来。
 */
import { Alert, Button, Descriptions, Space, Tag, Typography } from 'antd'
import { tokens } from '../theme/tokens'
import { navigateShell } from './shellRouter'
import type { PanelTab, ShellRoute } from './shellRouter'
import { useShellStore } from './shellStore'

/** 受控的对象类型枚举（**不是**任意对象 —— 规格 §11 N1）。 */
const OBJECT_TYPE_LABEL: Record<string, { label: string; contextField: string }> = {
  task: { label: '任务', contextField: 'current_task_id' },
  run: { label: '运行', contextField: 'current_run_id' },
  publication: { label: '内容发布', contextField: 'current_publication_id' },
  conversation: { label: '会话', contextField: 'current_conversation_id' },
  approval: { label: '审批', contextField: 'current_approval_id' },
}

function typeMeta(type: string | null) {
  if (!type) return { label: '未知类型', contextField: 'current_object_id' }
  return OBJECT_TYPE_LABEL[type] ?? { label: type, contextField: 'current_object_id' }
}

export function RightPanel({ route }: { route: ShellRoute }) {
  const objects = useShellStore((state) => state.objects)
  const object = route.objectId ? objects[route.objectId] : undefined
  const meta = typeMeta(route.objectType ?? object?.type ?? null)
  const active: PanelTab = route.panel ?? 'brief'

  const go = (next: Partial<ShellRoute>, replace = false) => {
    navigateShell({ ...route, ...next }, { replace })
  }

  return (
    <aside
      data-testid="right-panel"
      aria-label="当前对象"
      style={{
        width: route.expand ? '100%' : 360,
        flexShrink: 0,
        height: '100%',
        overflowY: 'auto',
        background: tokens.color.cardBg,
        borderRadius: tokens.radius.card,
        boxShadow: tokens.shadow.card,
        padding: tokens.spacing.md,
      }}
    >
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <Typography.Text strong>当前对象</Typography.Text>
        {route.objectId && (
          <Button size="small" onClick={() => go({ expand: !route.expand })}>
            {route.expand ? '收起右栏' : '展开全屏'}
          </Button>
        )}
      </Space>

      {!route.objectId ? (
        <Alert
          style={{ marginTop: tokens.spacing.md }}
          type="info"
          showIcon
          message="未选中对象"
          description={
            <Space direction="vertical" size={2}>
              <span>在「通知」或悬浮助手里点一条，它指向的对象就会出现在这里。</span>
              <span>也可以直接改地址栏的 <code>?object=</code> 参数（右栏状态是可分享的）。</span>
            </Space>
          }
        />
      ) : (
        <Space direction="vertical" size="middle" style={{ width: '100%', marginTop: tokens.spacing.md }}>
          <Space>
            <Button size="small" type={active === 'brief' ? 'primary' : 'default'} onClick={() => go({ panel: 'brief' })}>
              简要信息
            </Button>
            <Button
              size="small"
              type={active === 'employee' ? 'primary' : 'default'}
              onClick={() => go({ panel: 'employee' })}
            >
              数字员工
            </Button>
          </Space>

          {!object ? (
            /* 深链直达：URL 里只有 id，壳里没有它的详情 —— **如实说明，不编造** */
            <Alert
              type="warning"
              showIcon
              message="只有对象标识，没有摘要"
              description={`这个链接只带了 ${route.objectType ?? '对象'} 标识 ${route.objectId}。摘要由页面在上报时提供，从对应页面进入才能看到完整信息。`}
            />
          ) : active === 'brief' ? (
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="名称">{object.title}</Descriptions.Item>
              <Descriptions.Item label="类型">{meta.label}</Descriptions.Item>
              {object.status && (
                <Descriptions.Item label="状态">
                  <Tag>{object.status}</Tag>
                </Descriptions.Item>
              )}
              <Descriptions.Item label="标识">{object.id}</Descriptions.Item>
              {object.detail && <Descriptions.Item label="说明">{object.detail}</Descriptions.Item>}
            </Descriptions>
          ) : (
            <Space direction="vertical" size="small" style={{ width: '100%' }}>
              <Alert
                type="success"
                showIcon
                message="将带上当前对象上下文"
                description={`数字员工面板会以 ${meta.contextField} = ${object.id} 唤起，不需要你在空白框里描述"是哪一个"。`}
              />
              <Tag>{`上下文注入字段：${meta.contextField}`}</Tag>
              <Alert
                type="warning"
                showIcon
                message="本面板尚未合并"
                description="数字员工面板属 B2（Agent + Assignment 两层表、SOUL 层、6 类岗位模板），B2 规格状态为「未评审」。此处先如实说明要注入什么，不做假的对话界面。"
              />
            </Space>
          )}
        </Space>
      )}

      <Typography.Paragraph type="secondary" style={{ marginTop: tokens.spacing.md, marginBottom: 0 }}>
        右栏只放「当前对象的简要信息 + 数字员工面板」，不做可打开任意对象的通用舞台（B3 §5 / §11 N1）。
      </Typography.Paragraph>
    </aside>
  )
}
