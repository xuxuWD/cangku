/**
 * B3 原型 · 悬浮助手（规格 §6 + 验收 A7）
 *
 * 规格 §6 要求「挂在 `body`、**路由切换不卸载**」⇒ 本组件由 `PrototypeApp` 在**路由切换之外**
 * 渲染一次，**不参与**主区域的互斥显示，所以路由怎么切它都在（A7 的可测证据：
 * `data-testid="floating-assistant"` 的 DOM 节点在切换前后是同一个）。
 *
 * 规则层全在 `assistantRules.ts`（纯函数、不用 LLM —— 规格 §11 N3）。
 */
import { useState } from 'react'
import { Badge, Button, Card, Drawer, Input, Space, Tag, Typography } from 'antd'
import { tokens } from '../theme/tokens'
import { buildAttentionItems, attentionBadgeText, buildSuggestedActions, routeIntent, INTENT_LABEL } from './assistantRules'
import { SAMPLE_ATTENTION, usePrototypeStore } from './store'
import { navigate, routeFor } from './router'

export function FloatingAssistant() {
  const open = usePrototypeStore((state) => state.assistantOpen)
  const setOpen = usePrototypeStore((state) => state.setAssistantOpen)
  const draft = usePrototypeStore((state) => state.assistantDraft)
  const setDraft = usePrototypeStore((state) => state.setAssistantDraft)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const items = buildAttentionItems(SAMPLE_ATTENTION)
  const match = routeIntent(draft)

  return (
    <>
      {/* 悬浮球：常驻右下角。**不随路由卸载** */}
      <div
        data-testid="floating-assistant"
        style={{ position: 'fixed', right: tokens.spacing.lg, bottom: tokens.spacing.lg, zIndex: 1000 }}
      >
        <Badge count={items.length} size="small">
          <Button type="primary" shape="circle" size="large" onClick={() => setOpen(true)} aria-label="打开悬浮助手">
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
        // 说明：抽屉是本原型的呈现选择，**关键在它挂在哪** —— 它不在路由分支里，故切换不卸载
        destroyOnHidden={false}
      >
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Typography.Text type="secondary">
            {attentionBadgeText(items.length)}（排序：待审批 &gt; 待输入 &gt; 受阻 &gt; 失败 &gt; 完成）
          </Typography.Text>

          {items.map((item) => {
            const actions = buildSuggestedActions(item.kind)
            const expanded = expandedId === item.id
            return (
              <Card key={item.id} size="small" title={item.kind}>
                <Space direction="vertical" size="small" style={{ width: '100%' }}>
                  <Typography.Text>{item.title}</Typography.Text>
                  <Space wrap>
                    <Button
                      size="small"
                      onClick={() => {
                        setExpandedId(expanded ? null : item.id)
                        // 点待办 ⇒ 打开该对象（右栏）—— 走 URL，可分享
                        navigate(routeFor('workitems', item.objectId, 'brief'))
                        setOpen(false)
                      }}
                    >
                      打开工作项
                    </Button>
                    {actions.length > 0 && (
                      <Button size="small" type="link" onClick={() => setExpandedId(expanded ? null : item.id)}>
                        {expanded ? '收起建议' : '查看建议'}
                      </Button>
                    )}
                  </Space>
                  {expanded && (
                    <Space direction="vertical" size={2}>
                      {/* 建议是**纯规则**产出的（规格 §6），界面上如实标注，不假装是"AI 想出来的" */}
                      {actions.map((action) => (
                        <Typography.Text key={action} type="secondary">
                          · {action}
                        </Typography.Text>
                      ))}
                      <Typography.Text type="secondary">（以上为规则生成，未调用任何模型）</Typography.Text>
                    </Space>
                  )}
                </Space>
              </Card>
            )
          })}

          <div>
            <Typography.Text type="secondary">
              意图路由是**中文正则**（规格 §11 N3：规则层不用 LLM）。试试输入「派给内容岗写篇稿」或「待我批的」。
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
