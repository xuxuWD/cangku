/**
 * B3 原型 · 右栏（规格 §5：**收窄，不做通用舞台**）
 *
 * 规格 §5 逐字：
 * | 项 | 决定 |
 * | **放什么** | 当前对象的**简要信息** + **数字员工面板**（带该对象的上下文） |
 * | **不放什么** | ❌ 不做"可打开任意类型对象的通用舞台" |
 * | **逃生口** | 需要看全屏时**展开为整页**（此时左对话隐藏，返回即回） |
 *
 * **⚠️ 为什么收窄**（规格原文）：TabTin 的通用舞台（`context-space`）是 **92,805 行**，
 * 本文明确不追这个规模 —— 故本组件的"对象类型"是**受控枚举**，不是任意对象。
 *
 * **⚠️ 上下文注入是关键**（规格 §5）：员工在某对象上打开数字员工面板时，
 * **自动带上该对象的 id** —— 而不是在空白对话框里问"帮我看看这个"。
 * 这里把要注入的字段名**显式打在界面上**，方便真机走查时对照请求体（验收 A6）。
 *
 * ⚠️ **权限口径（规格 §13.2 R4）**：带 `current_*_id` 意味着对话要拿到该对象的读权限。
 * 本原型**不接后端**，故未实现权限判定；真实现须**复用既有权限判定**，
 * 无权时**静默降级为无上下文对话**（不是报错）。这一条**未实现**，如实登记。
 */
import { Alert, Button, Descriptions, Space, Tag, Typography } from 'antd'
import { tokens } from '../theme/tokens'
import { OBJECT_BRIEFS } from './store'

export interface RightPanelProps {
  /** 当前对象 id（来自 URL，规格 §5）。`null` = 空态。 */
  objectId: string | null
  /** 面板页签；『employee』= 数字员工面板。 */
  panel: 'brief' | 'employee' | null
  /** 是否已展开为整页（展开时左对话隐藏 —— 由父组件传入的 visible 控制）。 */
  expanded: boolean
  onSwitchPanel: (panel: 'brief' | 'employee') => void
  onToggleExpand: () => void
}

export function RightPanel({ objectId, panel, expanded, onSwitchPanel, onToggleExpand }: RightPanelProps) {
  const brief = objectId ? OBJECT_BRIEFS[objectId] : undefined
  const active: 'brief' | 'employee' = panel ?? 'brief'

  return (
    <aside
      data-testid="right-panel"
      style={{
        width: expanded ? '100%' : 360,
        flexShrink: 0,
        height: '100%',
        background: tokens.color.cardBg,
        borderRadius: tokens.radius.card,
        padding: tokens.spacing.md,
        display: 'flex',
        flexDirection: 'column',
        gap: tokens.spacing.md,
        overflowY: 'auto',
      }}
    >
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <Typography.Text strong>当前对象</Typography.Text>
        <Button size="small" onClick={onToggleExpand}>
          {expanded ? '收起右栏' : '展开全屏'}
        </Button>
      </Space>

      {/* 对象类型是**受控枚举**（`OBJECT_BRIEFS`），不是"任意对象舞台" —— 规格 §5 / §11 N1 */}
      {!brief ? (
        <Alert
          type="info"
          showIcon
          message="未选中对象"
          description="在「待我处理」或「工作项」里点一条，它就会出现在这里；也可以直接改地址栏的 ?object= 参数。"
        />
      ) : (
        <>
          <Space>
            <Button size="small" type={active === 'brief' ? 'primary' : 'default'} onClick={() => onSwitchPanel('brief')}>
              简要信息
            </Button>
            <Button
              size="small"
              type={active === 'employee' ? 'primary' : 'default'}
              onClick={() => onSwitchPanel('employee')}
            >
              数字员工
            </Button>
          </Space>

          {active === 'brief' ? (
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="名称">{brief.title}</Descriptions.Item>
              <Descriptions.Item label="类型">{brief.kind}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag>{brief.status}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="标识">{brief.id}</Descriptions.Item>
            </Descriptions>
          ) : (
            <Space direction="vertical" size="small" style={{ width: '100%' }}>
              <Alert
                type="success"
                showIcon
                message="已带上当前对象上下文"
                description={`唤起数字员工面板时会自动注入 ${brief.contextField} = ${brief.id}，不需要你在空白框里描述"是哪一个"。`}
              />
              <Typography.Text type="secondary">
                真实现须复用既有权限判定：无权读该对象时不注入该字段（静默降级为无上下文对话，不报错）。
                <b>本原型未实现权限判定。</b>
              </Typography.Text>
              <Tag>{`注入字段：${brief.contextField}`}</Tag>
            </Space>
          )}
        </>
      )}

      <Typography.Text type="secondary">
        右栏只放「当前对象的简要信息 + 数字员工面板」；<b>不做</b>可打开任意对象的通用舞台（规格 §5 / §11 N1）。
      </Typography.Text>
    </aside>
  )
}
