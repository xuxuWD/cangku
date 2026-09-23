/**
 * B3 原型 · 三栏壳（规格 §2 目标形态）
 *
 * ```
 * ┌──────────┬──────────────────────────────┬────────────────────┐
 * │ 侧栏      │  主区域                       │  右栏               │
 * │ ≤10 入口  │  对话（常驻，切走不卸载）      │  当前业务对象        │
 * │          │  ★ 唯一的「创建入口」          │  可展开全屏          │
 * └──────────┴──────────────────────────────┴────────────────────┘
 *               ＋ 悬浮助手（全局常驻，路由切换不卸载）
 * ```
 *
 * **本文件是"对话常驻"的接线处**，规格 §4 的四条要求在这里合起来才成立：
 *  - 要求 ①（不卸载）：`<ConversationSurface>` 在这个组件里**无条件渲染一次**，
 *    可见性只通过 `display` 切 —— **它不在任何条件分支里**；
 *  - 要求 ②（同步）：`chatVisible` 在 **render 期**由路由算出，epoch 用 React 官方的
 *    「render 期调整 state」写法同步推进，**不用 useEffect**（effect 是异步的，正是规格警告的坑）；
 *  - 要求 ③（epoch）：见下；
 *  - 要求 ④（同一状态树）：会话数据只在 `store.ts`，侧栏与对话都从那里读。
 *
 * ⚠️ 本原型**不接后端、不改 `admin-web`**；页面内容多为"未合并"的如实说明。
 */
import { useState } from 'react'
import { Badge, Button, ConfigProvider, Layout, Menu, Space, Typography } from 'antd'
import { antdTheme, tokens } from '../theme/tokens'
import { MORE_NAV, PRIMARY_NAV, SIDEBAR_ENTRY_COUNT, findNav } from './nav'
import type { PrototypeView } from './nav'
import { navigate, useRoute } from './router'
import { ConversationSurface } from './ConversationSurface'
import { FloatingAssistant } from './FloatingAssistant'
import { RightPanel } from './RightPanel'
import { SettingsModal } from './SettingsModal'
import { AgentsSurface, KnowledgeSurface, SimpleSurface, TodoSurface, WorkItemsSurface } from './Surfaces'
import { SAMPLE_ATTENTION, usePrototypeStore } from './store'

function SurfaceView({ view }: { view: PrototypeView }) {
  switch (view) {
    case 'todo':
      return <TodoSurface />
    case 'workitems':
      return <WorkItemsSurface />
    case 'agents':
      return <AgentsSurface />
    case 'knowledge':
      return <KnowledgeSurface />
    default:
      return <SimpleSurface view={view} />
  }
}

export function PrototypeApp() {
  const route = useRoute()
  const activeId = usePrototypeStore((state) => state.activeConversationId)
  const setActive = usePrototypeStore((state) => state.setActiveConversation)
  const settingsOpen = usePrototypeStore((state) => state.settingsOpen)
  const setSettingsOpen = usePrototypeStore((state) => state.setSettingsOpen)
  const [notice, setNotice] = useState<string | null>(null)

  /* ---- 要求 ②：可见性在 render 期**同步**算出，不经过任何异步回调 ---- */
  const chatVisible = route.view === 'chat' && !route.expand
  const pageVisible = route.view !== 'chat' && !route.expand

  /* ---- 要求 ③：epoch 用「render 期调整 state」推进（同步，且 StrictMode 安全） ----
   * 为什么不用 `useEffect(() => setEpoch(e => e+1), [chatVisible])`：
   * effect 在**提交之后**才跑，快速连切时两次可见性变化可能合并/错序 —— 正是规格 §4 抄下来的坑 ②。
   * 放在 render 期 → 与可见性**同一帧**确定，不存在"标志不同步"的窗口。 */
  const [epoch, setEpoch] = useState(0)
  const [lastChatVisible, setLastChatVisible] = useState(chatVisible)
  if (lastChatVisible !== chatVisible) {
    setLastChatVisible(chatVisible)
    setEpoch((value) => value + 1)
  }

  const attentionCount = SAMPLE_ATTENTION.filter((item) => item.kind !== '完成').length
  const activeNav = findNav(route.view)

  const openView = (view: PrototypeView) => {
    // 「新建对话」= 回到对话，并新开一个会话（对话是**唯一创建入口** —— 规格 §0）
    if (view === 'chat') {
      setActive(`conv-${Date.now()}`)
      setNotice('已新建一个会话（原型演示，未落后端）')
    }
    navigate({ view, objectId: route.objectId, panel: route.panel, expand: false })
  }

  return (
    <ConfigProvider theme={antdTheme}>
      <Layout style={{ minHeight: '100vh' }}>
        {/* ============ ① 侧栏（收敛后 ≤10） ============ */}
        <Layout.Sider theme="light" width={tokens.layout.siderWidth}>
          <div style={{ padding: tokens.spacing.md }}>
            <Typography.Text strong>公司数字员工工作台</Typography.Text>
            <div>
              <Typography.Text type="secondary">{`业务入口 ${SIDEBAR_ENTRY_COUNT} 项（目标 ≤10）`}</Typography.Text>
            </div>
          </div>

          <Menu
            mode="inline"
            selectedKeys={[route.view]}
            onClick={({ key }) => openView(key as PrototypeView)}
            items={[...PRIMARY_NAV, ...MORE_NAV].map((item) => ({
              key: item.view,
              icon: <item.icon />,
              label: item.view === 'todo' ? `待我处理 (${attentionCount})` : item.title,
            }))}
          />

          {/* 常驻最近会话列表（要求 ④：与对话**同一个状态树**） */}
          <div style={{ padding: tokens.spacing.md, borderTop: `1px solid ${tokens.color.border}` }}>
            <Typography.Text type="secondary">最近会话</Typography.Text>
            <Menu
              mode="inline"
              selectedKeys={[activeId]}
              onClick={({ key }) => {
                setActive(String(key))
                navigate({ view: 'chat', objectId: route.objectId, panel: route.panel, expand: false })
              }}
              items={usePrototypeStore
                .getState()
                .conversations.map((item) => ({ key: item.id, label: item.title }))}
            />
          </div>

          <div style={{ padding: tokens.spacing.md, display: 'flex', gap: tokens.spacing.sm }}>
            {/* 顶栏三项（不计入侧栏业务入口计数） */}
            <Button size="small" onClick={() => setSettingsOpen(true)}>设置</Button>
            <Badge count={attentionCount} size="small">
              <Button size="small" onClick={() => openView('todo')}>通知</Button>
            </Badge>
            <Button size="small">账号</Button>
          </div>
        </Layout.Sider>

        {/* ============ ② 主区域 + ③ 右栏 ============ */}
        <Layout>
          <Layout.Header
            style={{
              background: tokens.color.cardBg,
              height: tokens.layout.headerHeight,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: `0 ${tokens.spacing.lg}px`,
            }}
          >
            <Space>
              <Typography.Title level={4} style={{ margin: 0 }}>
                {activeNav?.title ?? '对话'}
              </Typography.Title>
              {/* 如实标注：形态是真的，数据是样例 */}
              <Typography.Text type="secondary">
                B3 形态原型 · URL {window.location.search || '（默认）'}
              </Typography.Text>
            </Space>
            {notice && (
              <Typography.Text type="secondary" onClick={() => setNotice(null)}>
                {notice}
              </Typography.Text>
            )}
          </Layout.Header>

          <Layout.Content style={{ padding: tokens.spacing.md, background: tokens.color.contentBg, overflow: 'hidden' }}>
            <div style={{ display: 'flex', gap: tokens.spacing.md, height: '100%', minWidth: 0 }}>
              {/*
                对话宿主：**无条件渲染**，只有 display 变（要求 ①）。
                注意它**不在**任何 `route.view === ...` 的条件分支里 —— 那会让它被卸载。
              */}
              <div style={{ flex: 1, minWidth: 0, display: chatVisible ? 'flex' : 'none' }}>
                <ConversationSurface visible={chatVisible} epoch={epoch} />
              </div>

              {!route.expand && (
                <div style={{ flex: 1, minWidth: 0, display: pageVisible ? 'flex' : 'none' }}>
                  <SurfaceView view={route.view} />
                </div>
              )}

              <RightPanel
                objectId={route.objectId}
                panel={route.panel}
                expanded={route.expand}
                onSwitchPanel={(panel) =>
                  navigate({ ...route, panel, expand: false })
                }
                onToggleExpand={() => navigate({ ...route, expand: !route.expand })}
              />
            </div>
          </Layout.Content>
        </Layout>

        {/* ============ ④ 悬浮助手（在路由分支之外 ⇒ 切换不卸载，验收 A7） ============ */}
        <FloatingAssistant />
        <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      </Layout>
    </ConfigProvider>
  )
}
