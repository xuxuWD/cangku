/**
 * B3 原型 · 对话常驻宿主（规格 §4 的实现要求，四条逐条落地）
 *
 * 规格 §4 抄自 EvoFlow 的两个坑（原文）：
 * > ①「离开路由时已经 display:none；再卸列表会在标志不同步时留下永久空白」
 * > ②「必须同步：动态 `import().then` 在快速切路由时会乱序，导致 `chatSurfaceVisible` 卡在 false」
 *
 * | 规格要求 | 本文件怎么做的 |
 * | --- | --- |
 * | **① 切走只 `display:none`、不卸载**（保 SSE 与滚动位置） | 宿主由 `PrototypeApp` **无条件渲染**，这里只切 `display`；`data-testid="conversation-host"` 的 DOM 节点在路由切换前后是**同一个** |
 * | **② 可见性切换必须同步** | `visible` 由父组件**在 render 期**从路由算出并直接落到 `style`，**没有任何异步回调参与** |
 * | **③ epoch 计数器串行化 hide/show** | `epochRef` 每次可见性变化 +1；任何**延后执行**的副作用在动手前必须核对 `epoch === epochRef.current`，过期即放弃 |
 * | **④ 与侧栏同一状态树** | 消息与最近会话全部从 `store.ts` 读，本组件**不持有一份自己的 useState** |
 *
 * ⚠️ **一句如实说明**：本原型的对话**不是懒加载**的（没有 `import().then`），
 * 所以「② 同步」天然成立、epoch 目前**没有在真实竞态上起作用**。它被保留是因为
 * 规格 §4 把它列为实现要求、且验收 A4 要测「快速连续切路由 20 次不错乱」——
 * 我把它做成**可测的守卫**（`epoch` 在 DOM 上留痕，见 `data-epoch`），
 * **而不是假装它在挡一个不存在的竞态**。真正需要它的是将来把对话改成懒加载时。
 */
import { useEffect, useLayoutEffect, useRef } from 'react'
import { Button, Space, Tag, Typography } from 'antd'
import { tokens } from '../theme/tokens'
import { usePrototypeStore } from './store'
import type { ChatMessage } from './store'

const STEP_MARK: Record<NonNullable<ChatMessage['step']>['state'], string> = {
  done: '✓',
  running: '⟳',
  failed: '✕',
}

const STEP_COLOR: Record<NonNullable<ChatMessage['step']>['state'], string> = {
  done: 'success',
  running: 'processing',
  failed: 'error',
}

export interface ConversationSurfaceProps {
  /** **同步**算出的可见性：`false` 时只隐藏、不卸载。 */
  visible: boolean
  /** 可见性变化时递增，用于任何延后副作用的过期检查。 */
  epoch: number
}

export function ConversationSurface({ visible, epoch }: ConversationSurfaceProps) {
  const messages = usePrototypeStore((state) => state.messages)
  const conversations = usePrototypeStore((state) => state.conversations)
  const activeId = usePrototypeStore((state) => state.activeConversationId)
  const setActive = usePrototypeStore((state) => state.setActiveConversation)
  const running = usePrototypeStore((state) => state.backgroundRunning)
  const ticks = usePrototypeStore((state) => state.backgroundTicks)
  const toggleBackground = usePrototypeStore((state) => state.toggleBackground)
  const bump = usePrototypeStore((state) => state.bumpBackground)

  const epochRef = useRef(epoch)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  // ③ epoch：可见性变化即在**同一帧内**把 epoch 同步到 ref（不排队、不延后）
  useLayoutEffect(() => {
    epochRef.current = epoch
  }, [epoch])

  // 「后台产出」模拟器：真实 setInterval —— 宿主被隐藏时它**照样在跑**，
  // 这正是"切走不卸载"的可观测证据（验收 A3 的替身；真 SSE 接线后换成流订阅）。
  useEffect(() => {
    if (!running) return
    const captured = epochRef.current
    const timer = window.setInterval(() => {
      // ③ 延后执行的副作用动手前核对 epoch：过期就放弃（防将来的懒加载乱序）
      if (captured !== epochRef.current) return
      bump()
    }, 1000)
    return () => window.clearInterval(timer)
  }, [running, bump])

  // 新消息进来时滚到底 —— 只在**可见**时滚，隐藏时保位置（验收 A2 的"滚动位置不丢"）
  useEffect(() => {
    if (!visible) return
    const node = scrollRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [messages.length, visible])

  const active = conversations.find((item) => item.id === activeId)

  return (
    <section
      data-testid="conversation-host"
      data-epoch={epoch}
      data-visible={visible ? 'true' : 'false'}
      aria-hidden={visible ? undefined : true}
      style={{
        display: visible ? 'flex' : 'none',
        flexDirection: 'column',
        height: '100%',
        background: tokens.color.cardBg,
        borderRadius: tokens.radius.card,
      }}
    >
      <header
        style={{
          padding: `${tokens.spacing.md}px`,
          borderBottom: `1px solid ${tokens.color.border}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: tokens.spacing.md,
        }}
      >
        <Space direction="vertical" size={0}>
          <Typography.Text strong>对话 · {active?.title ?? '未选择会话'}</Typography.Text>
          {/* 这条计数是给"切走不卸载"做证据的：切到别的页它仍在涨 */}
          <Typography.Text type="secondary">
            宿主已渲染 {ticks} 拍后台产出（切到别的页面它不会停 —— 这就是「不卸载」）
          </Typography.Text>
        </Space>
        <Button size="small" onClick={toggleBackground}>
          {running ? '停止后台产出' : '开始后台产出（演示）'}
        </Button>
      </header>

      <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: tokens.spacing.md }}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          {messages.map((message) => (
            <article key={message.id}>
              <Typography.Text type={message.role === 'user' ? 'success' : 'secondary'}>
                {message.role === 'user' ? '你' : message.role === 'employee' ? '数字员工' : '系统'} · {message.at}
              </Typography.Text>
              {message.step && (
                <div>
                  {/* 规格 §9 手法 2：语义化步骤条，不是裸日志 */}
                  <Tag color={STEP_COLOR[message.step.state]}>{STEP_MARK[message.step.state]}</Tag>
                  <Typography.Text>{message.step.label}</Typography.Text>
                </div>
              )}
              <div>
                <Typography.Text>{message.text}</Typography.Text>
              </div>
            </article>
          ))}
        </Space>
      </div>

      <footer style={{ padding: tokens.spacing.md, borderTop: `1px solid ${tokens.color.border}` }}>
        <Typography.Text type="secondary">
          这是唯一创建入口：说清要什么，数字员工去做；其他页面只负责看进度与结果。
        </Typography.Text>
        <div style={{ marginTop: tokens.spacing.sm }}>
          <Space wrap>
            {conversations.map((item) => (
              <Button
                key={item.id}
                size="small"
                type={item.id === activeId ? 'primary' : 'default'}
                onClick={() => setActive(item.id)}
              >
                {item.title}
              </Button>
            ))}
          </Space>
        </div>
      </footer>
    </section>
  )
}
