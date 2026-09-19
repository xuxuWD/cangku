/**
 * 应用壳（第 1 轮）：AntD Layout = 左侧导航 240 / 顶栏 56 / 内容区。
 *
 * 当前页状态用 React `useState`（**没有**用 URL hash）：
 * 第 1 轮没有深链分享与浏览器前进后退的需求，且 jsdom 下 hashchange 的触发时机不可靠，
 * 容易把测试写成假绿；等引入正式路由时再统一升级为地址栏可寻址。
 *
 * 主题只在这里通过 ConfigProvider 下发一次，页面里不允许出现颜色 / 圆角字面量。
 */
import { createElement, useState } from 'react'
import type { ComponentType } from 'react'
import { ConfigProvider, Layout, Menu, Segmented, Space, Typography } from 'antd'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AgentAdminPage } from '../features/agentAdmin/AgentAdminPage'
import { AuditLogPage } from '../features/auditLog/AuditLogPage'
import { KnowledgePage } from '../features/knowledge/KnowledgePage'
import { MyAgentsPage } from '../features/myAgents/MyAgentsPage'
import { MyWorkbenchPage } from '../features/myWorkbench/MyWorkbenchPage'
import { PermissionsPage } from '../features/permissions/PermissionsPage'
import { ComponentsPlaygroundPage } from '../features/playground/ComponentsPlaygroundPage'
import { SkillsMcpPage } from '../features/skillsMcp/SkillsMcpPage'
import { TeamPage } from '../features/team/TeamPage'
import { antdTheme, tokens } from '../theme/tokens'
import { navItemsForRole } from './navigation'
import type { NavKey } from './navigation'
import { ROLE_OPTIONS, useSession } from './session'
import type { Role } from './session'

/** 8 个导航项各对应一个占位页；用 Record 约束"有导航项就必须有页面"。 */
const PAGES: Record<NavKey, ComponentType> = {
  'my-workbench': MyWorkbenchPage,
  'my-agents': MyAgentsPage,
  knowledge: KnowledgePage,
  team: TeamPage,
  'agent-admin': AgentAdminPage,
  permissions: PermissionsPage,
  'skills-mcp': SkillsMcpPage,
  'audit-log': AuditLogPage,
  // 开发期辅助页（只在 vite dev 出现在导航里，见 navigation.ts 的 devOnly）。
  'components-playground': ComponentsPlaygroundPage,
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
                <Page />
              </div>
            </Layout.Content>
          </Layout>
        </Layout>
      </QueryClientProvider>
    </ConfigProvider>
  )
}