# 管理台知识权限路由接入设计

## 目标

将现有 `KnowledgeAccessPage` 接入管理台主路由，使侧边栏“知识权限管理”入口可用，并保持内容工作台和历史草稿现有导航行为不变。

## 方案

继续使用 `window.location.search`、`history.pushState` 和 `popstate` 实现轻量路由，不引入 React Router 或其他依赖。

路由状态包含三个视图：

- `?view=knowledge`：知识权限管理
- `?view=history`：历史草稿
- 无 `view` 参数，或带 `?task=<id>`：内容工作台

解析函数负责把非法或未知的 `view` 值归一化到内容工作台，避免出现空白页面。导航函数统一通过 `pushState` 更新 URL，再派发 `popstate` 让 `App` 刷新状态。

## 组件与数据流

- `App` 根据当前 URL 选择 `KnowledgeAccessPage`、`ContentHistoryPage` 或 `ContentWorkbenchPage`。
- `AppShell` 的导航项增加 `knowledge` 视图标识，并将其点击事件交给 `onNavigate`。
- `KnowledgeAccessPage` 继续使用现有 API、加载、错误和保存逻辑，不复制或迁移业务代码。
- 知识权限页切换到其他视图时只改变 URL，不共享或覆盖内容工作台的任务状态。

## 交互与错误处理

- 当前页面对应的导航项必须有 active 样式。
- 浏览器后退/前进通过 `popstate` 恢复正确视图。
- 直接访问 `?view=knowledge` 应直接打开知识权限页。
- 未知查询参数或未知 `view` 不报错，回退到内容工作台。
- 既有知识权限 API 错误展示逻辑保持不变。

## 测试

新增或更新 `admin-web/src/app/App.test.tsx`，覆盖：

- `?view=knowledge` 渲染知识权限页面。
- 点击“知识权限管理”后 URL 更新并切换页面。
- 点击“历史草稿”和“内容工作台”仍可正常切换。
- `popstate` 能恢复对应页面。
- 未知 view 回退到内容工作台。

实现前先运行新增测试确认其因路由尚未接入而失败；实现后运行全部前端测试和构建。

## 非目标

- 不引入路由库。
- 不修改知识权限 API、权限策略或后端代码。
- 不改动内容工作台、历史草稿的数据模型和业务状态机。
