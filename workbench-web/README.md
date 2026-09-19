# workbench-web（前端第 1 轮：应用壳）

公司数字员工工作台的前端独立包。**第 1 轮只搭壳**：不接后端、不接业务数据、不实现具体功能。

## 怎么跑

```bash
cd workbench-web
npm install          # 独立安装依赖（不影响 admin-web / companion-pwa / desktop）
npm run dev          # 本地开发（Vite）
npm run typecheck    # 类型检查（tsc --noEmit）
npm test             # 单元测试（vitest run）
npm run build        # 类型检查 + 生产构建
```

技术栈：React + TypeScript + Vite + Ant Design 5 + @ant-design/pro-components + zustand +
@tanstack/react-query；测试用 vitest + @testing-library/react + jsdom。

## 本轮覆盖什么

- 应用壳：AntD `Layout`（左导航 240 / 顶栏 56 / 内容区 padding 24、最大宽度 1440 居中），侧栏 `Menu`，顶栏产品名 + 角色切换器。
- 导航：员工 4 项（我的工作台 / 我的数字员工 / 知识库 / 团队协作），管理员额外 4 项（数字员工管理 / 权限配置 / Skill & MCP / 审计日志），共 8 项，按角色自适应。
- 会话/角色：`src/app/session.tsx` 是 **本地桩（zustand，内存态）**，右上角可切换角色以演示自适应。
- `ContentState`：loading / empty / error / forbidden 四态占位组件，供后续页面复用。
- 8 个占位页：只渲染 empty 态并写明"尚未接入（第 N 轮实现）"，不假装有数据。
- 纪律守卫：`src/theme/no-raw-colors.test.ts` 扫描 `src/**/*.{ts,tsx}`，除令牌文件外出现十六进制颜色或圆角数值字面量即失败。

## 还没接入（如实说明）

未接真实登录/会话与权限校验；未调用任何后端接口；未做路由（当前页用 `useState`，不可通过地址栏直达）；
未做响应式断点与移动端形态；未做暗色模式；未做 i18n；`@tanstack/react-query` 只挂了 Provider，没有任何请求。

## 设计令牌

唯一来源：`src/theme/tokens.ts`（导出令牌常量 + AntD `ConfigProvider` 的 `theme` 对象），
组件里不允许写颜色/圆角字面量。主色 `#1677FF` 与白底对比度约 3.68:1，**不满足 WCAG AA 正文 4.5:1**，
因此它只作组件底色（按钮背景、选中态底色等），正文、链接、可点击文字统一用加深后的 `#0958D9`（约 5.17:1）。

轮次编号（第 3～6 轮）是占位排期，用于说明"该模块尚未接入"，最终以阶段文档为准。