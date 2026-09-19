# workbench-web（公司数字员工工作台前端）

公司数字员工工作台的**前端独立包**（不依赖 `admin-web` / `companion-pwa` / `desktop` 的构建产物）。

**当前状态（2026-09-19）**：第 1~5 轮交付（应用壳 / 组件库 / 我的工作台 / 我的数字员工 / 数字员工注册中心），
第 6 轮「接线轮」**批 1 已接真实后端**（真实登录会话 + 「我的工作台」待办/标记已读）。
**逐模块接线进度以 `../docs/contracts/` 下的契约文档为准**（每个模块一份 `*-api.md`，含实测形状与"未接入"登记）。

## 怎么跑

```bash
cd workbench-web
npm install          # 独立安装依赖
npm run dev          # 本地开发（Vite）
npm run typecheck    # 类型检查（tsc --noEmit）
npm test             # 单元测试（vitest run）
npm run build        # 类型检查 + 生产构建
```

### 环境变量（可选；写进 `.env.local`，**不进仓库**）

| 变量 | 作用 | 不设时的行为 |
| --- | --- | --- |
| `VITE_API_BASE_URL` | 后端地址（如 `http://127.0.0.1:8000`） | 空 = **同源**：开发期由 dev proxy 转发，生产期由反代处理 |
| `VITE_WORKBENCH_API_MODE` | `mock` \| `http`：适配层模式 | 开发默认 `mock`，**生产默认 `http`** |
| `VITE_DEV_PROXY_TARGET` | `npm run dev` 时 `/api` 的代理目标 | `http://127.0.0.1:8000` |

> 纪律：代码里**不写死**任何内网地址 / 端口 / 密钥；换环境只改配置。前端产物里**不得**出现样例数据字样。

## 已交付范围

- 应用壳：AntD `Layout`（左导航 240 / 顶栏 56 / 内容区 padding 24、最大宽度 1440 居中），侧栏 `Menu` 按角色自适应。
- 导航：员工 4 项（我的工作台 / 我的数字员工 / 知识库 / 团队协作），管理员额外 4 项（数字员工管理 / 权限配置 / Skill & MCP / 审计日志），共 8 项。
- 会话/角色（第 6 轮接线批 1）：走**服务端登录响应**（`POST /api/v1/auth/sessions`，`src/features/auth/`）；
  令牌只存 `sessionStorage`（键 `workbench.token`），仅进 `Authorization: Bearer` 头；顶栏显示**角色名** + 退出登录。
  **没有**角色切换器 —— 角色只能由服务端下发（旧的内存桩已删除）。
- HTTP：统一请求层 `src/api/client.ts` 是**全前端唯一**的 HTTP 出口（401 统一清会话；错误按状态分类；
  服务端 `detail` 只取"短且干净"的字符串，堆栈 / SQL / 内部路径一律丢弃）。
- 组件库：`src/components/`（9 个，含 loading / empty / error / forbidden 四态与 hover / focus / active / disabled）。
- 「我的工作台」：已接真接口 —— 待办 = 未读站内通知（`GET /api/v1/inbox?unread_only=true`）+ 待审批（`GET /api/v1/approvals/pending`）
  合并，支持「标记已读」（`POST /api/v1/inbox/{id}/read`）；「最近使用」「日程」**如实标未接入**（不返回空数组假装没有内容）。
- 纪律守卫：`src/theme/no-raw-colors.test.ts` 扫描颜色 / 圆角字面量（令牌文件除外，出现即失败）。

## 还没接入（如实说明）

- **未做路由**：当前页用 `useState`，不能用地址栏直达 / 分享（引入正式路由时统一升级）。
- 未做响应式断点与移动端形态；未做暗色模式；未做 i18n。
- 除「我的工作台」外的模块仍在接线中，进度见 `../docs/contracts/` 的对应契约（**未接入的一律抛 `not_connected` 并给说明，不返回空数据**）。
- 后端**没有**的接口（任务列表、日程实体、部分聚合统计）已逐条登记，未编造字段。

## 设计令牌

唯一来源：`src/theme/tokens.ts`（导出令牌常量 + AntD `ConfigProvider` 的 `theme` 对象），
组件里不允许写颜色/圆角字面量。主色 `#1677FF` 与白底对比度约 3.68:1，**不满足 WCAG AA 正文 4.5:1**，
因此它只作组件底色（按钮背景、选中态底色等），正文、链接、可点击文字统一用加深后的 `#0958D9`（约 5.17:1）。

轮次编号（第 3～6 轮）是占位排期，用于说明"该模块尚未接入"，最终以阶段文档为准。