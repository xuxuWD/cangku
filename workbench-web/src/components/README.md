# 组件库 · `src/components/`

**口径（先读这条）**：《项目核心规范》**禁止自定义按钮 / 表格样式**。所以这里不是"再造一套 UI"，而是
**基于 AntD 的业务组合组件** —— 不重写 `Button` / `Table`，不写样式覆盖（`!important` / `.ant-*` 选择器），
颜色 / 圆角 / 间距只通过 `ConfigProvider`（`src/theme/tokens.ts`）统一。（第 2 轮建立；第 4 轮给 `FormDrawer` 加只读态，本文件同步补齐。）

## 组件清单与 Props 概要

`?` = 可选（括号内为默认值）。全部 props 类型与实现同源，**改实现必须同轮改本文件**。

| 组件 | 关键 Props |
| --- | --- |
| `ContentState` | `state`（必填）`description?` `onRetry?`(仅 error 态渲染重试) `action?`(空态主按钮 / 无权限申请入口) `boxed?`(true) |
| `PageContainer` | `title?` `description?` `extra?` `state?`(ready) `stateDescription?` `onRetry?` `children?` |
| `DataTable<T>` | `columns`(AntD 泛型列) `rows` `rowKey` `state?`(ready) `presence?`(ready) `stateDescription?` `onRetry?` `pagination?{page,pageSize,total,onChange}` `loadingRows?`(3) `emptyAction?` |
| `StatCard` | `label` `value?` `unit?` `trend?{direction,text}` `presence?`(ready) `state?`(ready) `stateDescription?` `onRetry?` |
| `StatusTag` | `tone?`(neutral) `children?` `presence?`(ready) `state?`(ready) |
| `EmptyState` | `description?` `actionText?` `onAction?` `action?`(优先于 actionText) `state?`(empty) `onRetry?` `boxed?`(true) |
| `SkeletonList` | `rows?`(3) `state?`(loading) `stateDescription?` `onRetry?` `boxed?`(true) |
| `FormDrawer` | `open` `title` `form` `children` `onSubmit` `onClose` `dirty?`(false) `submitText?`(提交) `cancelText?`(取消) `readOnly?`(false) `state?`(ready) `stateDescription?` `onRetry?` `width?`(480) |
| `PermissionGuard` | `capability`(受控枚举) `children` `reason?` `requestText?`(申请权限) `onRequestAccess?` |
| `DangerConfirm` | `open` `title` `description` `confirmWord?` / `acknowledgeText?`(前者优先) `confirmText?`(确认执行) `cancelText?`(取消) `onConfirm` `onCancel` `state?`(ready) `stateDescription?` `onRetry?` |

辅助模块：`dataPresence.ts` 导出 `DataPresence` 与 `DATA_PRESENCE_LABEL`、`DATA_PRESENCE_DESCRIPTION`、`presenceLabel()`、`presenceDescription()`；
`ContentState.tsx` 另导出 `ContentStateKind` 与四态统一文案 `CONTENT_STATE_TEXT`。以上连同各 Props 类型都由 `index.ts` 再导出。

## 关键行为（逐个核对过实现）

- `PageContainer`：标题为 `Typography.Title level={2}`（页面唯一 h1 由应用壳给）；`state` 非 ready 时正文换成四态。
- `DataTable`：`loading`→骨架行；`error`/`forbidden`→四态；`state='empty'` 或 `presence` 非 ready→空态（presence 文案优先于 `stateDescription`）；否则渲染 AntD `Table`。分页：传 `pagination` 即服务端语义（`rows` 为当前页），不传则 10 条/页、单页时隐藏。
- `StatCard`：`state` 非 ready→四态；`presence` 非 ready→显示占位文案并**隐藏单位与趋势**；`value` 缺失→"暂无"。
- `StatusTag`：优先级 `state` > `presence` > `tone`；非 ready 时**忽略 `children`**，改用固定文案与对应语义色（色调枚举→AntD 预设色，不接受颜色值）。
- `EmptyState` / `SkeletonList`：`ContentState` 的薄封装；`SkeletonList` 默认态即"加载中"，加载中不出现任何"暂无"文案。
- `FormDrawer`：校验失败→留在原地 + Alert（字段级错误由 Form 展示）；提交中→两按钮 disabled；`dirty` 且非只读→关闭前 Modal 二次确认；**`readOnly`→表单整体 disabled、footer 只剩"关闭"、无提交按钮、忽略 `dirty`**；`state` 非 ready→正文四态且无提交按钮。
- `PermissionGuard`：判定同步（无 state 参数），有权限渲染 `children`，无权限渲染"原因 + 申请入口"且**不渲染 children**。
- `DangerConfirm`：`confirmWord` 需**去首尾空格后精确匹配**、`acknowledgeText` 需勾选；**两者都没配置 ⇒ 确认按钮永远不可点**（安全默认）；每次打开重置输入/勾选；`state` 非 ready ⇒ 确认按钮不可点。

## 八态矩阵

| 组件 | loading | empty | error | forbidden | hover / focus / active / disabled |
| --- | --- | --- | --- | --- | --- |
| `PageContainer` | `state` | `state` | `state`+重试 | `state` | 由 AntD 提供（`extra` 里的按钮） |
| `DataTable` | 骨架行（**不出现"暂无数据"**） | `state='empty'` 或 `presence` | `state`+重试 | `state` | 由 AntD 提供（Table / 分页） |
| `StatCard` | `state` | `state` | `state`+重试 | `state` | 由 AntD 提供 |
| `StatusTag` | `state` | `state` | `state` | `state` | 由 AntD 提供 |
| `EmptyState` | `state` | 默认态 | `state`+重试 | `state` | 由 AntD 提供（主操作按钮） |
| `SkeletonList` | 默认态（骨架行） | `state='empty'` | `state`+重试 | `state` | 由 AntD 提供 |
| `FormDrawer` | `state` | `state`（无可提交内容） | `state`+重试 | `state`（无提交按钮） | 由 AntD 提供（提交中 disabled 防重复提交；只读态见上） |
| `PermissionGuard` | 不支持（判定同步，无 loading 语义） | 不支持 | 不支持 | 默认行为：原因 + 申请入口 | 由 AntD 提供 |
| `DangerConfirm` | `state` | `state` | `state`+重试 | `state`（确认按钮不可点） | 由 AntD 提供（`Button danger`） |

**状态保真（硬要求）**：`StatCard` / `DataTable` / `StatusTag` 支持"未配置 / 样本不足 / 未验证"三种非数值态（`DataPresence`，见 `dataPresence.ts`）：
**不得显示为 `0`、不得贴"成功"类结论**；无数据显示"暂无"，非就绪态 `StatusTag` 一律用中性色。

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

样品页：`vite dev` 下侧栏「组件样品」（`src/features/playground/ComponentsPlaygroundPage.tsx`，可统一切换四态）。
该页**仅开发模式可达且为动态加载**（构建期常量决定入口 + `React.lazy`）；生产构建里入口与页面代码都不存在（`npm run build` 后 grep `dist/` 应 0 命中）。

## 纪律

- 颜色 / 圆角 / 间距只能取 `src/theme/tokens.ts` 令牌，由 `no-raw-colors.test.ts` 守卫。
- 不给 AntD 组件写样式覆盖；`StatusTag` 只接受受控枚举 `StatusTone`，不能传颜色值。
- 无权限一律**显式呈现**（原因 + 申请入口），禁止静默隐藏；前端判定只是呈现，真正校验在服务端。
- 本文件的"Props 概要 + 关键行为 + 八态矩阵"是**契约**：新增 / 修改组件 props 与行为时，同轮更新本文件（曾漏过 `readOnly`）。