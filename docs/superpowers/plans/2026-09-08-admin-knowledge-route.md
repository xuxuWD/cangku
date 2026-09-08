# 管理台知识权限路由接入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task with review checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有知识权限管理页面接入管理台轻量 URL 路由，使侧边栏入口、直接访问和浏览器前进后退都可用。

**Architecture:** 继续使用 `App.tsx` 当前的 `URLSearchParams`、`history.pushState` 和 `popstate` 机制，扩展为 `workbench`、`history`、`knowledge` 三种视图。`KnowledgeAccessPage` 保持现有数据加载和编辑逻辑，只由主路由选择渲染；`AppShell` 通过统一的 `onNavigate` 回调切换视图。

**Tech Stack:** React、TypeScript、Vite、Vitest、Testing Library、浏览器 History API。

---

### Task 1: 为主路由补充失败测试

**Files:**
- Modify: `admin-web/src/app/App.test.tsx`

- [ ] **Step 1: 扩展测试桩并增加 URL 清理**

在测试的 `beforeEach` 中将 `window.history.replaceState({}, '', '/')` 放在 `render(<App />)` 前，保证每个用例从根路径开始；保留现有 `fetch` mock，使知识页面的 binding 和 audits 请求都能返回成功数据。

- [ ] **Step 2: 添加知识视图直接访问测试**

增加测试：将 URL 设置为 `/?view=knowledge` 后渲染 `App`，等待标题 `知识权限管理` 和页面正文 `可以使用的知识库` 出现。当前实现会渲染内容工作台，因此该测试应失败。

- [ ] **Step 3: 添加侧边栏导航测试**

增加测试：从根路径渲染 `App`，点击 `知识权限管理`，断言 `window.location.search === '?view=knowledge'`，并等待标题 `知识权限管理` 出现。当前导航项没有 `view` 标识，因此该测试应失败。

- [ ] **Step 4: 添加未知 view 回退测试**

增加测试：将 URL 设置为 `/?view=unknown` 后渲染 `App`，断言显示 `内容工作台`。该测试用于固定 fail-safe 行为。

- [ ] **Step 5: 运行新增测试确认红灯**

运行：

```powershell
cd admin-web
npm test -- --run src/app/App.test.tsx
```

预期：新增知识路由和导航用例失败，失败原因是路由与导航尚未实现；现有内容工作台用例继续通过。

### Task 2: 扩展 URL 路由状态

**Files:**
- Modify: `admin-web/src/app/App.tsx`

- [ ] **Step 1: 扩展路由类型和解析函数**

将路由视图类型扩展为 `'workbench' | 'history' | 'knowledge'`。解析函数只把 `view=history` 解析为历史页、把 `view=knowledge` 解析为知识权限页，其余值统一返回工作台；继续保留 `task` 查询参数。

```tsx
type AppView = 'workbench' | 'history' | 'knowledge'

function routeFromLocation() {
  const params = new URLSearchParams(window.location.search)
  const view = params.get('view')
  return {
    view: view === 'history' || view === 'knowledge' ? view : 'workbench',
    taskId: params.get('task') || undefined,
  } as { view: AppView; taskId?: string }
}
```

- [ ] **Step 2: 统一导航函数签名**

让 `navigate` 接受 `AppView`，生成规则为：`history` 使用 `?view=history`，`knowledge` 使用 `?view=knowledge`，工作台在存在任务时使用 `?task=<id>`，否则回到当前 pathname。更新 URL 后继续派发 `PopStateEvent`。

- [ ] **Step 3: 增加知识页面分支**

在历史页面分支前增加：

```tsx
if (route.view === 'knowledge') return <KnowledgeAccessPage />
```

知识页面暂不需要导航回调，因为其 `AppShell` 会在下一任务中接收统一的视图回调；实现时应将 `onNavigate` 传入页面并由页面继续传给 `AppShell`。

- [ ] **Step 4: 运行 App 测试确认仍为红灯或暴露接口缺口**

运行同 Task 1 的命令，确认直接访问测试开始通过，并记录剩余失败集中在 `AppShell` 导航和页面回调接口。

### Task 3: 接入 AppShell 与知识页面导航

**Files:**
- Modify: `admin-web/src/app/AppShell.tsx`
- Modify: `admin-web/src/features/knowledgeAccess/KnowledgeAccessPage.tsx`

- [ ] **Step 1: 为 AppShell 增加 knowledge 导航项**

将 navigation 项改为包含 `view: 'knowledge'`，并把 `view` 类型扩展为 `'workbench' | 'history' | 'knowledge'`。保持现有图标、文案和 active class 逻辑。

- [ ] **Step 2: 为 KnowledgeAccessPage 增加可选 onNavigate**

将组件签名改为接收 `{ onNavigate?: (view: 'workbench' | 'history' | 'knowledge') => void } = {}`，并在两个 `AppShell` 返回点传入 `activeView="knowledge"` 和 `onNavigate={onNavigate}`。不改动其知识权限状态机。

- [ ] **Step 3: 更新 App 的页面回调类型**

将 `navigate` 回调传给 `KnowledgeAccessPage`，并把内容工作台、历史页面已有回调类型同步扩展到包含 `knowledge`，确保 TypeScript 类型检查通过。

- [ ] **Step 4: 运行 App 测试确认绿灯**

运行：

```powershell
cd admin-web
npm test -- --run src/app/App.test.tsx
```

预期：App 路由测试全部通过，知识页的异步加载由既有 fetch mock 完成。

### Task 4: 回归验证与提交

**Files:**
- Modify: `admin-web/src/app/App.test.tsx`
- Modify: `admin-web/src/app/App.tsx`
- Modify: `admin-web/src/app/AppShell.tsx`
- Modify: `admin-web/src/features/knowledgeAccess/KnowledgeAccessPage.tsx`

- [ ] **Step 1: 运行全部前端测试**

运行：

```powershell
cd admin-web
npm test -- --run
```

预期：所有测试通过，且无未处理异常。

- [ ] **Step 2: 运行生产构建**

运行：

```powershell
npm run build
```

预期：TypeScript 检查和 Vite 构建均退出码为 0。

- [ ] **Step 3: 检查差异**

运行：

```powershell
cd ..
git diff --check
git status --short --branch
```

确认只包含本功能涉及的四个前端文件，以及此前已存在的 `.superpowers/` 未跟踪目录。

- [ ] **Step 4: 提交实现**

```powershell
git add admin-web/src/app/App.test.tsx admin-web/src/app/App.tsx admin-web/src/app/AppShell.tsx admin-web/src/features/knowledgeAccess/KnowledgeAccessPage.tsx
git commit -m "feat: 接入管理台知识权限路由"
```

## 自检结果

- 设计中的三个视图、直接访问、侧边栏导航、未知 view 回退和异步知识页加载均有对应任务。
- 未引入新依赖，未修改后端 API 或知识权限业务逻辑。
- 所有生产代码步骤均安排在对应失败测试之后。
- 未使用占位符或未定义的接口名称。
