/**
 * 应用壳：AntD Layout = 左侧导航 240 / 顶栏 56 / 内容区。
 *
 * 第 6 轮（接线批 1）变化：
 *  - **登录门**：未认证（无令牌）时直接渲染登录页，壳内不再有"演示用角色切换器"；
 *  - 顶栏显示**角色名**（后端登录响应没有展示名，不编造姓名）+ 退出登录；
 *  - QueryClient 上移到 `main.tsx`（本组件不再自建请求层上下文）。
 *
 * 当前页状态用 React `useState`（**没有**用 URL hash）：本轮没有深链分享与前进后退需求，
 * 且 jsdom 下 hashchange 的触发时机不可靠，容易把测试写成假绿；引入正式路由时再统一升级。
 * 主题只在这里通过 ConfigProvider 下发一次，页面里不允许出现颜色 / 圆角字面量。
 */
import { Suspense, createElement, lazy, useState } from 'react'
import type { ComponentType } from 'react'
import { Button, ConfigProvider, Layout, Menu, Space, Typography } from 'antd'
import { ContentState } from '../components'
import { LoginPage } from '../features/auth/LoginPage'
import { logout } from '../features/auth/services/authService'
import { AgentRegistryPage } from '../features/agentRegistry/AgentRegistryPage'
import { AuditLogPage } from '../features/auditLog/AuditLogPage'
import { KnowledgePage } from '../features/knowledge/KnowledgePage'
import { MyAgentsPage } from '../features/myAgents/MyAgentsPage'
import { MyWorkbenchPage } from '../features/myWorkbench/MyWorkbenchPage'
import { PermissionsPage } from '../features/permissions/PermissionsPage'
import { SkillsMcpPage } from '../features/skillsMcp/SkillsMcpPage'
import { TeamPage } from '../features/team/TeamPage'
import { antdTheme, tokens } from '../theme/tokens'
import { navItemsForRole } from './navigation'
import type { NavKey } from './navigation'
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

/** 页面注册表：业务页 + 开发期样品页（后者在生产构建里恒为 `null`）。 */
const PAGES: Record<NavKey, ComponentType | null> = {
  'my-workbench': MyWorkbenchPage,
  'my-agents': MyAgentsPage,
  knowledge: KnowledgePage,
  team: TeamPage,
  // 「数字员工管理」（管理后台视角）由第 5 轮模块「数字员工注册中心」承载。
  'agent-admin': AgentRegistryPage,
  permissions: PermissionsPage,
  'skills-mcp': SkillsMcpPage,
  'audit-log': AuditLogPage,
  // 开发期辅助页（只在 vite dev 出现在导航里，见 navigation.ts 的 IS_DEV_MODE + 上面的动态加载）。
  'components-playground': DevPlaygroundPage,
}

export function AppShell() {
  const status = useSession((state) => state.status)
  const token = useSession((state) => state.token)
  const role = useSession((state) => state.role)
  const displayName = useSession((state) => state.displayName)
  const signOut = useSession((state) => state.signOut)
  const [logoutWarning, setLogoutWarning] = useState<string | null>(null)

  const [activeKey, setActiveKey] = useState<NavKey>('my-workbench')

  // 有令牌但角色未知（存储被部分清理 / 旧残留）⇒ 不能画出正确的导航，按未登录处理并清干净。
  if (status !== 'authenticated' || !token || !role) {
    if (status === 'authenticated') signOut()
    // 「退出登录时服务端撤销失败」的警告必须在这里（登录页）呈现：它产生的同一刻本组件就切到了
    // 登录页，若渲染在已登录分支里用户永远看不到（2026-09-19 真机走查发现的原缺陷）。
    return <LoginPage externalNotice={logoutWarning} />
  }

  const visibleItems = navItemsForRole(role)
  // 当前项不可见（如角色变化）时回落到第一个可见项，而不是渲染空白
  const current = visibleItems.find((item) => item.key === activeKey) ?? visibleItems[0]
  const Page = PAGES[current.key]

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
        <Layout.Sider aria-label="主导航" theme="light" width={tokens.layout.siderWidth}>
          <Menu
            mode="inline"
            style={{ borderInlineEnd: 'none', paddingTop: tokens.spacing.sm }}
            selectedKeys={[current.key]}
            items={visibleItems.map((item) => ({
              key: item.key,
              icon: createElement(item.icon, {}),
              label: item.title,
            }))}
            onClick={({ key }) => setActiveKey(key as NavKey)}
          />
        </Layout.Sider>

        <Layout>
          <Layout.Header
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              borderBottom: `1px solid ${tokens.color.border}`,
            }}
          >
            <Typography.Text strong style={{ fontSize: tokens.fontSize.md }}>
              公司数字员工工作台
            </Typography.Text>
            <Space size={tokens.spacing.sm}>
              <Typography.Text type="secondary">
                {displayName || ROLE_LABEL[role]}
              </Typography.Text>
              <Button size="small" onClick={handleLogout}>
                退出登录
              </Button>
            </Space>
          </Layout.Header>

          <Layout.Content style={{ padding: tokens.layout.contentPadding }}>
            <div style={{ maxWidth: tokens.layout.contentMaxWidth, margin: '0 auto' }}>
              <Typography.Title level={1}>{current.title}</Typography.Title>
              {Page ? (
                // 业务页是同步组件，Suspense 只服务于开发期那张懒加载的样品页。
                <Suspense fallback={<ContentState state="loading" boxed={false} />}>
                  <Page />
                </Suspense>
              ) : (
                // 只有"非开发模式 + 人为把当前页指向样品页"才可能到这里；导航入口本身在非 dev 下不出现。
                <ContentState
                  state="empty"
                  description="该入口仅在开发模式（vite dev）可用。"
                  boxed={false}
                />
              )}
            </div>
          </Layout.Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  )
}