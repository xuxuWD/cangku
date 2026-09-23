/**
 * 应用壳：**B3 三栏形态**（侧栏 ≤10 / 主区域 / 右栏）+ 全局悬浮助手（2026-09-23 改）。
 *
 * ```
 * ┌──────────┬──────────────────────────────┬────────────────────┐
 * │ 侧栏      │  主区域（当前页）              │  右栏「当前对象」    │
 * │ ≤10 入口  │  标题 + 页面                   │  可展开全屏          │
 * └──────────┴──────────────────────────────┴────────────────────┘
 *               ＋ 悬浮助手（全局常驻，路由切换不卸载）
 * ```
 *
 * **本次改动（对照 B3 规格）**：
 *  - **§2 三栏**：两栏 → 三栏。原「顶栏 + 内容区」保留，右侧新增右栏；
 *  - **§7 侧栏收敛**：管理类三项（数字员工管理 / 权限配置 / 用量与费用）**收进设置弹窗**
 *    ⇒ 侧栏对**所有角色**都是 **8 项**（目标 ≤10）。**页面一行未改、功能一条未删**（可逆收敛）；
 *  - **§8 路由**：`useState<NavKey>` 切页 → **URL 路由**（自建，见 `shellRouter.ts`）。
 *    现在任意页可地址栏直达、可刷新、可分享、可前进后退；
 *  - **§6 悬浮助手**：新增，渲染在**路由分支之外** ⇒ 切换不卸载（验收 A7）。
 *
 * ⚠️ **本轮明确没做：§4「对话常驻」**。原因：`workbench-web` 里**没有对话页**
 * （对话在 `admin-web`，966 行 + 15 端点 + 整个 `stage/` 包）。中间列现在装的是**当前页**，
 * 等对话页按 D-050⑤ 合并过来之后，才能把「对话常驻 + 其他页互斥显示」落成 §4 的机制。
 * **不假装做了。**
 *
 * 保留的既有行为：登录门（未认证渲染 `LoginPage`）、退出登录失败要在登录页如实告知、
 * 主题只在 `ConfigProvider` 下发一次、`import.meta.env.DEV` 之下才有开发期样品页。
 */
import { Suspense, createElement, lazy, useRef, useState } from 'react'
import type { ComponentType } from 'react'
import { Button, ConfigProvider, Layout, Menu, Space, Typography } from 'antd'
import { ContentState } from '../components'
import { LoginPage } from '../features/auth/LoginPage'
import { logout } from '../features/auth/services/authService'
import { AgentRegistryPage } from '../features/agentRegistry/AgentRegistryPage'
import { AuditLogPage } from '../features/auditLog/AuditLogPage'
import { KnowledgePage } from '../features/knowledge/KnowledgePage'
import { MyAgentsPage } from '../features/myAgents/MyAgentsPage'
import { UsageBillingPage } from '../features/billing/UsageBillingPage'
import { CollaborationDynamicsPage } from '../features/collaborationDynamics/CollaborationDynamicsPage'
import { ConversationPage } from '../features/conversation/ConversationPage'
import { InboxPage } from '../features/inbox/InboxPage'
import { MyWorkbenchPage } from '../features/myWorkbench/MyWorkbenchPage'
import { PermissionsPage } from '../features/permissions/PermissionsPage'
import { SkillsMcpPage } from '../features/skillsMcp/SkillsMcpPage'
import { TeamPage } from '../features/team/TeamPage'
import { antdTheme, tokens } from '../theme/tokens'
import { FloatingAssistant } from './FloatingAssistant'
import { RightPanel } from './RightPanel'
import { SettingsModal } from './SettingsModal'
import { adminSettingsKeysForRole, navItemsForRole, navTitle } from './navigation'
import type { NavKey } from './navigation'
import { navigateShell, shellRoute, useShellRoute } from './shellRouter'
import { useShellStore } from './shellStore'
import { ROLE_LABEL, useSession } from './session'

/**
 * 开发期辅助页（组件样品）：**只在开发分支里动态加载**，不静态引用。
 *
 * `import.meta.env.DEV` 在生产构建时被替换为字面量 `false`，该分支整体成为死代码被摇掉 ——
 * 样品页代码与它的 chunk 都不会进入 `dist/`（验收：构建后 grep「组件样品」应为 0 命中）。
 */
const DevPlaygroundPage: ComponentType | null = import.meta.env.DEV
  ? lazy(() =>
      import('../features/playground/ComponentsPlaygroundPage').then((module) => ({
        default: module.ComponentsPlaygroundPage,
      })),
    )
  : null

/**
 * 页面注册表：业务页 + 开发期样品页（后者在生产构建里恒为 `null`）。
 *
 * 口径未变：**所有页面都是无 props 组件**（`<Page />`）—— 所以换路由**没有改动任何页面的契约**。
 * 页面若要把「当前对象」推到右栏，用 `shellStore.showObject()` **上报**，而不是接收回调。
 */
const PAGES: Record<NavKey, ComponentType | null> = {
  conversation: ConversationPage,
  'my-workbench': MyWorkbenchPage,
  inbox: InboxPage,
  'my-agents': MyAgentsPage,
  knowledge: KnowledgePage,
  dynamics: CollaborationDynamicsPage,
  team: TeamPage,
  // 「数字员工管理」（管理后台视角）由第 5 轮模块「数字员工注册中心」承载 —— 现在从**设置弹窗**进入。
  'agent-admin': AgentRegistryPage,
  permissions: PermissionsPage,
  'skills-mcp': SkillsMcpPage,
  'audit-log': AuditLogPage,
  billing: UsageBillingPage,
  'components-playground': DevPlaygroundPage,
}

/** 侧栏业务入口的默认页（任一角色都可见，见 `navItemsForRole` 的兜底口径）。 */
const DEFAULT_VIEW: NavKey = 'my-workbench'

export function AppShell() {
  const status = useSession((state) => state.status)
  const token = useSession((state) => state.token)
  const role = useSession((state) => state.role)
  const displayName = useSession((state) => state.displayName)
  const signOut = useSession((state) => state.signOut)
  const [logoutWarning, setLogoutWarning] = useState<string | null>(null)
  const settingsOpen = useShellStore((state) => state.settingsOpen)
  const conversationSlotRef = useRef<HTMLDivElement | null>(null)
  /**
   * B3 §4 要求 ③ 的 epoch 计数器。
   *
   * ⚠️ **必须声明在登录门（下面的 `if (...) return <LoginPage/>`）之前**：
   * 2026-09-23 落 §4 时常把它放在门后，结果**登出时组件在门口提前 return，这两个 hook 就不再执行**
   * ⇒ React 报 `Rendered fewer hooks than expected`，**真登出会崩**。
   * Hooks 的调用顺序不能随分支变化 —— 这是同一类错误的第二次（`useShellRoute` 也在门之前）。
   */
  const [epoch, setEpoch] = useState(0)
  const [lastVisible, setLastVisible] = useState(false)
  const setSettingsOpen = useShellStore((state) => state.setSettingsOpen)

  // ⚠️ Hooks 必须无条件调用 ⇒ 路由 hook 放在登录门**之前**。
  // 未登录时用默认页当兜底（登录后 URL 会被规范化到该角色的可见页）。
  //
  // ⚠️ **兜底仍取 `DEFAULT_VIEW`（我的工作台），不取"侧栏第一项"**：
  // 2026-09-23 把「对话」加到侧栏第一位后，"第一项"变成了对话 —— 那会让**所有用户在打开工作台时
  // 直接落到对话页**，是一次没人要求过的行为变化。侧栏顺序（对话在首位，B3 §2 的排法）
  // 与**落地页**是两件事，这里保持落地页不变；要改落地页请显式裁决。
  const fallback: NavKey = role
    ? navItemsForRole(role).some((item) => item.key === DEFAULT_VIEW)
      ? DEFAULT_VIEW
      : (navItemsForRole(role)[0]?.key ?? DEFAULT_VIEW)
    : DEFAULT_VIEW
  const route = useShellRoute(fallback)

  // 有令牌但角色未知（存储被部分清理 / 旧残留）⇒ 不能画出正确的导航，按未登录处理并清干净。
  if (status !== 'authenticated' || !token || !role) {
    if (status === 'authenticated') signOut()
    // 「退出登录时服务端撤销失败」的警告必须在这里（登录页）呈现：它产生的同一刻本组件就切到了
    // 登录页，若渲染在已登录分支里用户永远看不到（2026-09-19 真机走查发现的原缺陷）。
    return <LoginPage externalNotice={logoutWarning} />
  }

  const visibleItems = navItemsForRole(role)
  const settingsKeys = adminSettingsKeysForRole(role)
  /**
   * 当前角色**能到达**的全部视图 = 侧栏可见项 ∪ 设置弹窗里对它可见的管理项。
   *
   * ⚠️ **不能只用 `visibleItems`**：管理类三项已被收敛进设置弹窗、不在侧栏里。
   * 只用侧栏项算，会让**连超管都进不去**「权限配置」—— 从设置弹窗点「打开」会被回落掉。
   * （2026-09-23 换壳时踩到，AppShell 用例当场照出来。）
   */
  const allowedKeys: readonly NavKey[] = [...visibleItems.map((item) => item.key), ...settingsKeys]
  // 当前项不可达（如角色变化 / 收到别人的分享链接）时回落到第一个侧栏可见项，而不是渲染空白。
  // ⚠️ 这里**不写回 URL**（那会把"无权"变成"看起来有权"）；URL 保留原样，界面如实回落到可见页。
  // 回落目标与"URL 为空时的落地页"**必须是同一个**（都用 `fallback`）——
  // 否则会出现"打开是 A 页、链接无权时却落到 B 页"这种两套口径。
  const currentKey: NavKey = allowedKeys.includes(route.view) ? route.view : fallback

  /* ---- B3 §4「对话常驻」：可见性在 render 期**同步**算出 ---- */
  // 要求 ②：可见性**同步**算出，不经过任何异步回调（effect 是异步的，正是 EvoFlow 注释里记下的坑）。
  const conversationVisible = currentKey === 'conversation' && !route.expand
  // 要求 ③：epoch 用 React 官方「render 期调整 state」写法推进 —— **同步**，且 StrictMode 安全。
  // ⚠️ 两个 `useState` 必须在上面的**登录门之前**调用（见 `epoch` 的声明处）。
  if (lastVisible !== conversationVisible) {
    setLastVisible(conversationVisible)
    setEpoch((value) => value + 1)
  }
  const currentTitle = navTitle(currentKey) ?? navTitle(fallback) ?? ''
  const Page = PAGES[currentKey]

  const handleLogout = async () => {
    setLogoutWarning(null)
    try {
      await logout()
    } catch {
      // 服务端撤销失败也必须清本地；但要**如实告知**：服务端那头可能仍然有效
      setLogoutWarning('已退出本地登录，但服务端会话撤销失败：该登录凭证可能仍然有效，请关闭浏览器标签页。')
    }
    signOut()
  }

  return (
    <ConfigProvider theme={antdTheme}>
      <Layout style={{ minHeight: '100vh' }}>
        {/* ============ 侧栏（B3 §2 / §7：收敛后 8 项，目标 ≤10） ============ */}
        <Layout.Sider aria-label="主导航" theme="light" width={tokens.layout.siderWidth}>
          <div style={{ padding: tokens.spacing.md }}>
            <Typography.Text strong>公司数字员工工作台</Typography.Text>
            <div>
              <Typography.Text type="secondary">{`业务入口 ${visibleItems.length} 项（目标 ≤10）`}</Typography.Text>
            </div>
          </div>

          <Menu
            mode="inline"
            style={{ borderInlineEnd: 'none' }}
            selectedKeys={[currentKey]}
            items={visibleItems.map((item) => ({
              key: item.key,
              icon: createElement(item.icon, {}),
              label: item.title,
            }))}
            onClick={({ key }) => navigateShell(shellRoute(key as NavKey))}
          />

          {/* 设置 / 通知 / 账号（B3 §2 第三行）。设置开弹窗，不是新页面。 */}
          <div style={{ padding: tokens.spacing.md, display: 'flex', gap: tokens.spacing.sm }}>
            <Button size="small" onClick={() => setSettingsOpen(true)}>
              设置
            </Button>
            <Button size="small" onClick={() => navigateShell(shellRoute('inbox'))}>
              通知
            </Button>
            <Typography.Text type="secondary" style={{ alignSelf: 'center' }}>
              {displayName || ROLE_LABEL[role]}
            </Typography.Text>
          </div>
        </Layout.Sider>

        <Layout>
          <Layout.Header
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              background: tokens.color.cardBg,
              borderBottom: `1px solid ${tokens.color.border}`,
            }}
          >
            <Space>
              <Typography.Title level={1} style={{ margin: 0, fontSize: tokens.fontSize.lg }}>
                {currentTitle}
              </Typography.Title>
              <Typography.Text type="secondary">{`链接：${window.location.search || '（默认）'}`}</Typography.Text>
            </Space>
            <Space size={tokens.spacing.sm}>
              <Button size="small" onClick={handleLogout}>
                退出登录
              </Button>
            </Space>
          </Layout.Header>

          <Layout.Content
            style={{
              padding: tokens.layout.contentPadding,
              background: tokens.color.contentBg,
              overflow: 'hidden',
            }}
          >
            <div style={{ display: 'flex', gap: tokens.spacing.md, height: '100%', minWidth: 0 }}>
              {/*
                对话常驻宿主（B3 §4 要求 ①）：**永远渲染**，切走只切 `hidden` 与 `display`，**不卸载**。
                - `className="view-slot"` 是给 `useSlotVisible` 用的标记：槽被 `hidden` 时，
                  流读端据此**主动断开**（「切走即断」，不做后台堆积长连接）。
                - `data-epoch` 留在 DOM 上，让"快切不出错"这件事**可被真机断言**。
                - ⚠️ 它**不在**任何条件分支里 —— 一旦放进 `currentKey === 'conversation' && ...`，
                  切走就会卸载，SSE 与滚动位置全丢。
              */}
              <div
                ref={conversationSlotRef}
                className="view-slot"
                data-testid="conversation-slot"
                data-epoch={epoch}
                data-visible={conversationVisible ? 'true' : 'false'}
                hidden={!conversationVisible}
                aria-hidden={conversationVisible ? undefined : true}
                style={{
                  flex: 1,
                  minWidth: 0,
                  overflowY: 'auto',
                  display: conversationVisible ? 'block' : 'none',
                }}
              >
                <ConversationPage />
              </div>

              {/* 其他页与对话**互斥显示**（B3 §2）；右栏展开为整页时两者都隐藏（§5 逃生口） */}
              {currentKey !== 'conversation' && (
                <div
                  data-testid="main-surface"
                  style={{
                    flex: 1,
                    minWidth: 0,
                    overflowY: 'auto',
                    display: route.expand ? 'none' : 'block',
                  }}
                >
                  {Page ? (
                    // 业务页是同步组件，Suspense 只服务于开发期那张懒加载的样品页。
                    <Suspense fallback={<ContentState state="loading" boxed={false} />}>
                      <Page />
                    </Suspense>
                  ) : (
                    // 只有"非开发模式 + 人为把 URL 指向样品页"才可能到这里。
                    <ContentState
                      state="empty"
                      description="该入口仅在开发模式（vite dev）可用。"
                      boxed={false}
                    />
                  )}
                </div>
              )}

              <RightPanel route={route} />
            </div>
          </Layout.Content>
        </Layout>

        {/* ============ 悬浮助手（在路由分支**之外** ⇒ 切换不卸载，验收 A7） ============ */}
        <FloatingAssistant route={route} />
        <SettingsModal
          open={settingsOpen}
          onClose={() => setSettingsOpen(false)}
          visibleKeys={adminSettingsKeysForRole(role)}
        />
      </Layout>
    </ConfigProvider>
  )
}
