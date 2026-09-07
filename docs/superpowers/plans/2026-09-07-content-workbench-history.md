# 内容工作台历史草稿 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) to implement this plan task-by-task with review checkpoints.

**Goal:** 为内容工作台增加按权限过滤、状态筛选、分页的历史草稿页，并能从列表恢复到现有编辑器。

**Architecture:** 后端在内容存储层增加摘要列表查询，由 `ContentService` 负责状态校验、权限范围、排序和分页，API 只返回摘要；前端增加独立历史页和轻量 URL 状态（`?view=history`、`?task=<id>`），详情仍由现有工作台加载，避免复制编辑状态机。

**Tech Stack:** Python 3、FastAPI、dataclasses、SQLite、React、TypeScript、Vitest、Testing Library。

---

### Task 1: 后端列表摘要模型与存储查询

**Files:**
- Modify: `app/content/store.py`
- Modify: `app/content/sqlite_store.py`
- Test: `tests/test_content_sqlite_store.py`

- [ ] **Step 1: 写失败测试，定义摘要查询契约**

在 `tests/test_content_sqlite_store.py` 增加：

```python
def test_sqlite_store_lists_scoped_summaries_in_updated_order(tmp_path):
    store = SQLiteContentStore(tmp_path / "content.sqlite3")
    older = make_record("task-old", "tenant-a", "user-a", "key-old")
    newer = make_record("task-new", "tenant-a", "user-b", "key-new")
    newer.draft.updated_at = older.draft.updated_at.replace(second=older.draft.updated_at.second + 1)
    store.add(older)
    store.add(newer)

    summaries, total = store.list_summaries("tenant-a", user_id=None, status=None, offset=0, limit=20)

    assert total == 2
    assert [item.task_id for item in summaries] == ["task-new", "task-old"]
    assert summaries[0].topic == "持久化选题"
    assert not hasattr(summaries[0], "draft")
    store.close()
```

运行：`python -m pytest tests/test_content_sqlite_store.py::test_sqlite_store_lists_scoped_summaries_in_updated_order -q`。
预期：失败，`list_summaries` 尚未定义。

- [ ] **Step 2: 增加摘要类型和内存存储实现**

在 `app/content/store.py` 增加 `ContentTaskSummary`，字段为 `task_id`、`tenant_id`、`created_by`、`topic`、`status`、`run_id`、`created_at`、`updated_at`。在 `ContentStore` 增加：

```python
def list_summaries(self, tenant_id, *, user_id, status, offset, limit):
    records = [record for record in self._records.values()
               if record.tenant_id == tenant_id and (user_id is None or record.created_by == user_id)
               and (status is None or record.draft.status == status)]
    records.sort(key=lambda record: (record.draft.updated_at, record.task_id), reverse=True)
    total = len(records)
    page = records[offset:offset + limit]
    return [self._summary(record) for record in page], total
```

`_summary` 只读取 brief.topic、最新 draft 状态/run/revision 时间，不把正文放进返回类型。

- [ ] **Step 3: 为 SQLite 实现同一查询语义**

在 `app/content/sqlite_store.py` 用 `content_tasks` 与最新 `content_drafts` 的查询实现 `list_summaries`：按 `tenant_id` 过滤，`user_id` 非空时加 `created_by`，`status` 非空时过滤最新 draft，按 `content_tasks.updated_at DESC, task_id DESC` 排序，使用 `LIMIT ? OFFSET ?`，另取 `COUNT(*)` 返回总数。

- [ ] **Step 4: 运行存储测试**

运行：`python -m pytest tests/test_content_sqlite_store.py -q`。
预期：全部通过，并补充内存存储同语义测试。

- [ ] **Step 5: 提交存储层变更**

```powershell
git add app/content/store.py app/content/sqlite_store.py tests/test_content_sqlite_store.py
git commit -m "feat: 增加内容任务摘要查询"
```

### Task 2: 内容服务与 API 列表接口

**Files:**
- Modify: `app/content/service.py`
- Modify: `app/main.py`
- Test: `tests/test_content_api.py`
- Test: `tests/test_content_service.py`

- [ ] **Step 1: 写权限、筛选、分页和响应瘦身测试**

在 `tests/test_content_api.py` 增加测试：创建同租户两个用户和另一租户任务，然后断言：

```python
def test_content_api_lists_scoped_paginated_summaries():
    create_content_task(user="owner-a")
    create_content_task(user="owner-b")
    create_content_task(user="other-tenant", tenant="tenant-b")

    employee = client.get("/api/v1/content-tasks?page=1&page_size=1", headers=h(user="owner-a"))
    assert employee.status_code == 200
    assert employee.json()["total"] == 1
    assert employee.json()["items"][0]["created_by"] == "owner-a"
    assert "draft" not in employee.json()["items"][0]

    admin = client.get("/api/v1/content-tasks?page=1&page_size=20", headers=h(role="super_admin", user="admin"))
    assert admin.json()["total"] >= 2

    assert client.get("/api/v1/content-tasks?status=bad", headers=h()).status_code == 400
    assert client.get("/api/v1/content-tasks?page=0", headers=h()).status_code == 400
    assert client.get("/api/v1/content-tasks?page_size=101", headers=h()).status_code == 400
```

运行该测试，预期先因路由不存在而失败。

- [ ] **Step 2: 增加服务列表方法**

在 `ContentService` 增加 `list(actor, status, page, page_size)`：将 `super_admin`/`ceo` 映射为 `user_id=None`，其他角色使用 `actor.user_id`，调用存储 `list_summaries`，返回 `items`、`page`、`page_size`、`total`、`has_next`。

- [ ] **Step 3: 增加 FastAPI 查询模型和路由**

在 `app/main.py` 增加状态查询映射和：

```python
@app.get("/api/v1/content-tasks")
def list_content_tasks(
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    context: UserContext = Depends(current_user),
):
    if status_filter is not None and status_filter not in {item.value for item in ContentStatus}:
        raise HTTPException(status_code=400, detail="不支持的内容任务状态")
    return content_service.list(actor=context, status=ContentStatus(status_filter) if status_filter else None,
                                page=page, page_size=page_size)
```

列表项序列化为摘要字段，时间使用 ISO 8601；不调用 `_content_view`。

- [ ] **Step 4: 运行 API 回归**

运行：`python -m pytest tests/test_content_api.py tests/test_content_service.py -q`。
预期：列表权限、筛选、分页和旧内容流程全部通过。

- [ ] **Step 5: 提交 API 变更**

```powershell
git add app/content/service.py app/main.py tests/test_content_api.py tests/test_content_service.py
git commit -m "feat: 增加内容任务历史列表接口"
```

### Task 3: 前端 API、路由状态与历史页面

**Files:**
- Modify: `admin-web/src/features/contentWorkbench/api.ts`
- Modify: `admin-web/src/features/contentWorkbench/types.ts`
- Modify: `admin-web/src/app/App.tsx`
- Modify: `admin-web/src/app/AppShell.tsx`
- Create: `admin-web/src/features/contentHistory/ContentHistoryPage.tsx`
- Create: `admin-web/src/features/contentHistory/ContentHistoryPage.test.tsx`
- Modify: `admin-web/src/styles/global.css`

- [ ] **Step 1: 写失败的前端列表测试**

新增测试 mock `GET /content-tasks?page=1&page_size=20` 返回两个摘要，断言页面显示“历史草稿”、主题、状态、分页总数和“继续处理”；再切换“失败”筛选，断言请求 URL 含 `status=failed`。

运行：`npm test -- --run src/features/contentHistory/ContentHistoryPage.test.tsx`。
预期：失败，因为页面和 `listContentTasks` 尚不存在。

- [ ] **Step 2: 增加前端摘要类型和 API 方法**

在 `types.ts` 增加 `ContentTaskSummary` 与 `ContentTaskList`；在 `api.ts` 增加：

```ts
export function listContentTasks(status: ContentStatus | '', page = 1, pageSize = 20) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (status) params.set('status', status)
  return request<ContentTaskList>(`/content-tasks?${params.toString()}`)
}
```

- [ ] **Step 3: 实现历史页面状态机**

`ContentHistoryPage` 使用 `useEffect` 根据 `status`/`page` 请求列表，提供 `loading`、`error`、`empty` 和成功状态；筛选切换时将页码重置为 1；分页按钮按 `page` 和 `has_next` 禁用。每行按钮调用 `onOpenTask(taskId)`，失败行同时提供 `onOpenTask` 的“重新生成”语义入口。

- [ ] **Step 4: 接入轻量 URL 导航和 AppShell**

`App.tsx` 根据 `window.location.search` 在历史页与工作台间切换：导航到历史页使用 `?view=history`，打开任务使用 `?task=<id>`；监听 `popstate`，按钮通过 `history.pushState` 后派发 `popstate`。`ContentWorkbenchPage` 接收可选 `taskId`，优先从该 ID 加载详情并写入 sessionStorage。AppShell 增加“历史草稿”导航项，并通过 props 标记当前项。

- [ ] **Step 5: 增加页面样式和交互测试**

在 `global.css` 增加历史列表、状态徽标、分页和响应式规则，沿用现有变量、圆角和按钮风格。测试继续处理会写入 `?task=...` 并加载详情；失败任务行显示“重新生成”。

- [ ] **Step 6: 运行前端测试与构建**

运行：`npm test -- --run` 与 `npm run build`。
预期：新增历史页面测试和现有 8 个测试全部通过，TypeScript/Vite 构建成功。

- [ ] **Step 7: 提交前端历史页**

```powershell
git add admin-web/src/features/contentWorkbench/api.ts admin-web/src/features/contentWorkbench/types.ts admin-web/src/app/App.tsx admin-web/src/app/AppShell.tsx admin-web/src/features/contentHistory admin-web/src/styles/global.css
git commit -m "feat: 增加内容历史草稿页面"
```

### Task 4: 端到端验证与收尾

**Files:**
- Test: `tmp/verify_content_history.py` (临时文件，不提交)
- Modify: none unless verification exposes a defect

- [ ] **Step 1: 启动现有后端和前端**

后端保持 `http://127.0.0.1:8000`，前端使用 `npm run dev -- --host 127.0.0.1 --port 5173`；不设置任何模型 API Key。

- [ ] **Step 2: 用 Playwright 验证历史恢复闭环**

验证：历史页加载、状态筛选请求、失败任务显示“重新生成”、点击“继续处理”后工作台加载同一 task_id、reviewing 可编辑、failed 字段锁定。

- [ ] **Step 3: 执行完整验证**

运行：

```powershell
python -m pytest -q
python -m compileall -q app tests extract_pdf.py
git diff --check
cd admin-web
npm test -- --run
npm run build
```

预期：所有命令退出码为 0。

- [ ] **Step 4: 检查工作区并提交验证结果**

确认 `git status --short --branch` 只包含预期改动；`.superpowers/` 与临时 Playwright 脚本不纳入提交。若所有验证通过，使用 `git log -1 --oneline` 记录最终提交。

