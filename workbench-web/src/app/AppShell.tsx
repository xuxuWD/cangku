/**
 * 应用壳（第 1 轮）：AntD Layout = 左侧导航 240 / 顶栏 56 / 内容区。
 *
 * 当前页状态用 React `useState`（**没有**用 URL hash）：
 * 第 1 轮没有深链分享与浏览器前进后退的需求，且 jsdom 下 hashchange 的触发时机不可靠，
 * 容易把测试写成假绿；等引入正式路由时再统一升级为地址栏可寻址。
 *
 * 主题只在这里通过 ConfigProvider 下发一次，页面里不允许出现颜色 / 圆角字面量。
 */
import { Suspense, createElement, lazy, useState } from 'react'
import type { ComponentType } from 'react'
import { ConfigProvider, Layout, Menu, Segmented, Space, Typography } from 'antd'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ContentState } from '../components'
import { AgentAdminPage } from '../features/agentAdmin/AgentAdminPage'
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
import { ROLE_OPTIONS, useSession } from './session'
import type { Role } from './session'

/**
 * 开发期辅助页（组件样品）：**只在开发分支里动态加载**，不静态引用。
 *
 * 为什么写成一个三元表达式而不是 `if`：`import.meta.env.DEV` 在**生产构建**时被替换为字面量 `false`，
 * 于是这个分支整体成为死代码被摇掉 —— 样品页代码与它的 chunk 都不会进入 `dist/`
 * （验收方式：`npm run build` 后对 `dist/` grep「组件样品」应为 0 命中）。
 * 导航入口同样只在开发模式出现，见 `navigation.ts` 的 `IS_DEV_MODE`。
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
  'agent-admin': AgentAdminPage,
  permissions: PermissionsPage,
  'skills-mcp': SkillsMcpPage,
  'audit-log': AuditLogPage,
  // 开发期辅助页（只在 vite dev 出现在导航里，见 navigation.ts 的 devOnly + 上面的动态加载）。
  'components-playground': DevPlaygroundPage,
}

export function AppShell() {
  const role = useSession((state) => state.role)
  const setRole = useSession((state) => state.setRole)
  // 请求层第 1 轮不接后端，只把 Provider 挂上，后续轮次直接在这里配置默认行为。
  const [queryClient] = useState(() => new QueryClient())

  const visibleItems = navItemsForRole(role)
  const [activeKey, setActiveKey] = useState<NavKey>(visibleItems[0].key)
  // 角色切换后当前页可能不再可见，此时回落到第一个可见项（不是渲染空白）。
  const current = visibleItems.find((item) => item.key === activeKey) ?? visibleItems[0]
  const Page = PAGES[current.key]

  return (
    <ConfigProvider theme={antdTheme}>
      <QueryClientProvider client={queryClient}>
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
                <Typography.Text type="secondary">角色（演示）</Typography.Text>
                <Segmented
                  size="small"
                  options={ROLE_OPTIONS}
                  value={role}
                  onChange={(value) => setRole(value as Role)}
                />
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
      </QueryClientProvider>
    </ConfigProvider>
  )
}