# 组件库（第 2 轮）· `src/components/`

**口径（先读这条）**：《项目核心规范》**禁止自定义按钮 / 表格样式**。所以这里不是"再造一套 UI"，
而是**基于 AntD 的业务组合组件** —— 不重写 `Button` / `Table`，不做样式覆盖（不写 `!important`、不写 `.ant-*` 选择器），
颜色 / 圆角 / 间距只通过 `ConfigProvider`（`src/theme/tokens.ts`）统一。

## 组件清单与 Props 概要

| 组件 | 关键 Props |
| --- | --- |
| `PageContainer` | `title` `description` `extra` `state` `stateDescription` `onRetry` `children` |
| `DataTable<T>` | `columns`(AntD 泛型列) `rows` `rowKey` `state` `presence` `pagination{page,pageSize,total,onChange}` `onRetry` `loadingRows` |
| `StatCard` | `label` `value` `unit` `trend{direction,text}` `presence` `state` `onRetry` |
| `StatusTag` | `tone`（success/warning/danger/neutral/info）`presence` `state` `children` |
| `EmptyState` | `description` `actionText` `onAction` `action` `state` `onRetry` |
| `SkeletonList` | `rows` `state`(默认 loading) `stateDescription` `onRetry` |
| `FormDrawer` | `open` `title` `form` `onSubmit` `onClose` `dirty` `state` `width` |
| `PermissionGuard` | `capability` `children` `reason` `requestText` `onRequestAccess` |
| `DangerConfirm` | `open` `title` `description` `confirmWord` / `acknowledgeText` `onConfirm` `onCancel` `state` |
| `ContentState` | `state` `description` `onRetry` `action` `boxed` —— 四态底座，其余组件都在它之上拼装 |

## 八态矩阵

| 组件 | loading | empty | error | forbidden | hover / focus / active / disabled |
| --- | --- | --- | --- | --- | --- |
| `PageContainer` | `state` | `state` | `state`+重试 | `state` | 由 AntD 提供（`extra` 里的按钮） |
| `DataTable` | 骨架行（**不出现"暂无数据"**） | `state='empty'` 或 `presence` | `state`+重试 | `state` | 由 AntD 提供（Table / 分页） |
| `StatCard` | `state` | `state` | `state`+重试 | `state` | 由 AntD 提供 |
| `StatusTag` | `state` | `state` | `state` | `state` | 由 AntD 提供 |
| `EmptyState` | `state` | 默认态 | `state`+重试 | `state` | 由 AntD 提供（主操作按钮） |
| `SkeletonList` | 默认态（骨架行） | `state='empty'` | `state`+重试 | `state` | 由 AntD 提供 |
| `FormDrawer` | `state` | `state`（无可提交内容） | `state`+重试 | `state`（无提交按钮） | 由 AntD 提供（提交中 disabled 防重复提交） |
| `PermissionGuard` | —（权限判定是同步的） | — | — | `state='forbidden'`+原因+申请入口 | 由 AntD 提供 |
| `DangerConfirm` | `state` | `state` | `state`+重试 | `state`（确认按钮不可点） | 由 AntD 提供（`Button danger`） |

**状态保真（硬要求）**：`StatCard` / `DataTable` / `StatusTag` 支持"未配置 / 样本不足 / 未验证"三种非数值态
（`DataPresence`，见 `dataPresence.ts`），**不显示为 `0`，也不贴"成功"标签**；无数据显示"暂无"。

## 使用示例

```tsx
import { Button } from 'antd'
import { DataTable, PageContainer, StatCard } from '../components' // 包内用相对路径引用

<PageContainer title="运行概览" extra={<Button type="primary">新建</Button>} state={state}>
  <StatCard label="本周完成" value={12} unit="条" trend={{ direction: 'up', text: '较上周 +3' }} />
  <StatCard label="满意度" presence="insufficient_sample" />
  <DataTable<Row> columns={columns} rows={rows} rowKey={(r) => r.id} state={state} />
</PageContainer>
```

样品页：`vite dev` 下侧栏「组件样品」（`src/features/playground/ComponentsPlaygroundPage.tsx`），可统一切换四态。

## 纪律

- 颜色 / 圆角 / 间距只能取 `src/theme/tokens.ts` 令牌，由 `no-raw-colors.test.ts` 守卫。
- 不给 AntD 组件写样式覆盖；`StatusTag` 只接受受控枚举 `StatusTone`，不能传颜色值。
- 无权限一律**显式呈现**（原因 + 申请入口），禁止静默隐藏；前端判定只是呈现，真正校验在服务端。