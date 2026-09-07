# 公众号内容工作台 Alpha Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 FastAPI 控制平面和 Mock Runtime 之上，交付一个可供内部员工试用的微信公众号图文内容工作台，支持素材提交、确定性草稿生成、编辑、自确认和 Markdown 导出。

**Architecture:** 新增 `app/content/` 作为内容领域编排层，负责素材、草稿、版本、确认和导出；现有 `Task`、`RuntimeService` 和 `MockRuntime` 继续作为任务与运行事实源。开发期使用进程内内容仓储，所有 HTTP 操作从当前身份和任务快照派生权限；前端新增 `contentWorkbench` feature，通过内容 API 恢复任务状态，不直接组合底层任务和运行时接口。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic、pytest、React、TypeScript、Vite、Vitest、Testing Library。

---

## 文件与边界映射

- `app/content/models.py`：内容状态、来源、素材、草稿和审计数据结构，以及输入规范化。
- `app/content/store.py`：开发期租户隔离的进程内内容仓储和草稿 revision 检查。
- `app/content/service.py`：内容任务创建、Mock 运行启动、草稿编辑、确认、撤销和导出编排。
- `app/content/export.py`：只接受已确认草稿并生成脱敏 Markdown 字节流。
- `app/main.py`：新增内容请求/响应模型和 `/api/v1/content-tasks` 路由，复用现有 `current_user`、`store` 和 `runtime_service`。
- `docs/api-contract.md`：记录内容工作台 API、状态语义和安全边界。
- `tests/test_content_service.py`：领域服务、幂等、版本和安全单元测试。
- `tests/test_content_api.py`：FastAPI 集成测试和租户/用户权限测试。
- `admin-web/src/features/contentWorkbench/types.ts`：内容 API 类型和页面状态类型。
- `admin-web/src/features/contentWorkbench/api.ts`：内容工作台 API 客户端和 Markdown 下载处理。
- `admin-web/src/features/contentWorkbench/state.ts`：初始状态、输入规范化和本地幂等键。
- `admin-web/src/features/contentWorkbench/ContentWorkbenchPage.tsx`：左右分栏页面、状态条、输入、草稿编辑和确认下载。
- `admin-web/src/features/contentWorkbench/ContentWorkbenchPage.test.tsx`：页面交互和错误状态测试。
- `admin-web/src/app/App.tsx`、`AppShell.tsx`：将内容工作台设为员工入口，并保留现有知识权限页面可访问的导航占位。
- `admin-web/src/styles/global.css`、`tokens.css`：只增加内容工作台所需的布局/状态样式，不重构既有知识权限视觉系统。

---

### Task 1: 建立内容领域模型与输入规范化

**Files:**
- Create: `app/content/__init__.py`
- Create: `app/content/models.py`
- Test: `tests/test_content_service.py`

- [ ] **Step 1: 写失败测试，固定输入和状态契约**

```python
from datetime import UTC, datetime

import pytest

from app.content.models import ContentBriefInput, ContentStatus, SourceInput, normalize_brief


def test_normalize_brief_requires_topic_and_one_material():
    with pytest.raises(ValueError, match="主题不能为空"):
        normalize_brief(ContentBriefInput(topic="", sources=[], knowledge_references=[]))
    with pytest.raises(ValueError, match="至少提供一种素材"):
        normalize_brief(ContentBriefInput(topic="本周选题", sources=[], knowledge_references=[]))


def test_normalize_brief_rejects_non_http_url_and_sorts_sources():
    with pytest.raises(ValueError, match="来源链接必须使用 http 或 https"):
        normalize_brief(ContentBriefInput(
            topic="选题", sources=[SourceInput(url="javascript:alert(1)", excerpt="摘录")], knowledge_references=[]
        ))
    normalized = normalize_brief(ContentBriefInput(
        topic="  选题  ",
        sources=[SourceInput(url="https://b.example", excerpt="B"), SourceInput(url="https://a.example", excerpt="A")],
        knowledge_references=["kb-2", "kb-1", "kb-1"],
    ))
    assert normalized.topic == "选题"
    assert [item.url for item in normalized.sources] == ["https://a.example", "https://b.example"]
    assert normalized.knowledge_references == ("kb-1", "kb-2")


def test_status_values_are_stable():
    assert [item.value for item in ContentStatus] == ["generating", "reviewing", "confirmed", "failed"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_content_service.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.content'`.

- [ ] **Step 3: 实现最小领域类型和规范化**

实现 `SourceInput`、`ContentBriefInput`、`NormalizedBrief`、`ContentStatus`、`ContentDraft` 和 `ContentAudit`。`normalize_brief` 必须 trim 主题/摘录、限制主题 200 字、每条摘录 20,000 字、最多 20 条来源、只接受空 URL 或 `http/https` URL，并按 URL+摘录排序、知识库 ID 去重排序。使用 UTC aware `datetime`，输入中任何文字都只作为数据，不执行其中的命令。

- [ ] **Step 4: 运行领域测试**

Run: `python -m pytest tests/test_content_service.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add app/content/__init__.py app/content/models.py tests/test_content_service.py
git commit -m "feat: 定义内容工作台领域模型"
```

### Task 2: 实现租户隔离的内容仓储和确定性 Mock 生成

**Files:**
- Create: `app/content/store.py`
- Create: `app/content/service.py`
- Modify: `app/runtime/mock.py`
- Test: `tests/test_content_service.py`

- [ ] **Step 1: 写失败测试，覆盖创建、确定性输出和隔离**

```python
def test_content_service_creates_deterministic_draft_without_side_effects():
    service = make_content_service()
    first = service.create(actor=employee("tenant-a", "u1"), payload=brief("选题"), idempotency_key="k1")
    second = service.create(actor=employee("tenant-a", "u1"), payload=brief("选题"), idempotency_key="k1")
    assert first.task_id == second.task_id
    assert first.draft.body_markdown == second.draft.body_markdown
    assert first.draft.template_version == "mock-content-v1"
    assert service.runtime_side_effects(first.run_id) == []


def test_same_idempotency_key_with_different_input_conflicts_and_other_user_is_hidden():
    service = make_content_service()
    created = service.create(actor=employee("tenant-a", "u1"), payload=brief("选题"), idempotency_key="k1")
    with pytest.raises(IdempotencyConflict):
        service.create(actor=employee("tenant-a", "u1"), payload=brief("另一个选题"), idempotency_key="k1")
    with pytest.raises(ContentNotFound):
        service.get(actor=employee("tenant-a", "u2"), task_id=created.task_id)
    with pytest.raises(ContentNotFound):
        service.get(actor=employee("tenant-b", "u1"), task_id=created.task_id)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_content_service.py::test_content_service_creates_deterministic_draft_without_side_effects -q`

Expected: FAIL because `ContentService` and the content store do not exist.

- [ ] **Step 3: 实现仓储和服务**

`ContentStore` 按 `(tenant_id, created_by, idempotency_key)` 建立索引，并保存 `ContentBrief`、运行 ID、当前草稿 revision、审计列表和请求指纹。`ContentService.create` 必须先规范化并校验知识范围，再调用现有 `task_store.create` 创建低风险 `content-writer` 任务，调用 `RuntimeService.start` 启动仅含 `read`/`search` 的 Mock 计划，最后用 SHA-256 指纹生成确定性标题、摘要、正文、配图建议和引用。不得访问 URL、文件系统、知识库全文或外部网络。

为避免现有 Mock Runtime 事件不足，给 `MockRuntime` 增加可选的 `result_factory`/结果元数据保存能力，内容服务通过显式方法写入脱敏草稿结果，不把业务字段硬编码到通用 Runtime 事件中。

- [ ] **Step 4: 增加失败、重试和运行状态映射测试**

测试 Runtime 失败时状态为 `failed` 且保留输入；重新生成复用同一任务、创建新 run、旧 draft 仍可审计；生成成功状态为 `reviewing`。运行事件读取异常不能伪造 `reviewing`。

- [ ] **Step 5: 运行服务测试**

Run: `python -m pytest tests/test_content_service.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add app/content/store.py app/content/service.py app/runtime/mock.py tests/test_content_service.py
git commit -m "feat: 增加确定性的内容 Mock 生成"
```

### Task 3: 实现草稿编辑、revision、确认和 Markdown 导出

**Files:**
- Create: `app/content/export.py`
- Modify: `app/content/service.py`
- Test: `tests/test_content_service.py`

- [ ] **Step 1: 写失败测试，固定编辑和导出门禁**

```python
def test_draft_edit_uses_optimistic_revision_and_only_confirmed_draft_exports():
    service = make_content_service()
    item = service.create(actor=employee("tenant-a", "u1"), payload=brief("选题"), idempotency_key="k1")
    with pytest.raises(ExportNotAllowed):
        service.export_markdown(employee("tenant-a", "u1"), item.task_id)
    updated = service.update_draft(employee("tenant-a", "u1"), item.task_id, revision=1, title="新标题", summary="摘要", body_markdown="正文", image_suggestions=["配图"])
    with pytest.raises(RevisionConflict):
        service.update_draft(employee("tenant-a", "u1"), item.task_id, revision=1, title="旧版本", summary="摘要", body_markdown="正文", image_suggestions=[])
    service.confirm(employee("tenant-a", "u1"), item.task_id, revision=updated.revision)
    markdown = service.export_markdown(employee("tenant-a", "u1"), item.task_id)
    assert "# 新标题" in markdown.decode("utf-8")
    assert "tenant-a" not in markdown.decode("utf-8")
    assert "token" not in markdown.decode("utf-8").lower()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_content_service.py::test_draft_edit_uses_optimistic_revision_and_only_confirmed_draft_exports -q`

Expected: FAIL because export and confirmation methods do not exist.

- [ ] **Step 3: 实现 revision、确认状态和导出器**

`update_draft` 只允许 `reviewing` 状态，revision 不匹配抛 `RevisionConflict`，成功后递增 revision 并记录 `draft.updated`。`confirm` 必须要求当前 revision，写入 `confirmed_by/confirmed_at` 和 `draft.confirmed`；撤销只允许已确认草稿，递增 revision，恢复 `reviewing` 并写入 `draft.confirmation_revoked`。`MarkdownExporter` 只接收已确认草稿，按规格固定顺序输出 UTF-8 内容，清理控制字符和危险文件名字段，不输出租户、角色、内部事件或凭据。

- [ ] **Step 4: 增加敏感数据和审计测试**

用包含 `password`、`cookie`、`api_key`、`token`、验证码文字的来源摘录验证导出和公开 API 结果不包含原始敏感键值；确认、撤销和导出审计可查询。

- [ ] **Step 5: 运行测试并提交**

Run: `python -m pytest tests/test_content_service.py -q`

```powershell
git add app/content/export.py app/content/service.py tests/test_content_service.py
git commit -m "feat: 支持内容草稿确认和 Markdown 导出"
```

### Task 4: 接入 FastAPI 内容工作台 API

**Files:**
- Modify: `app/main.py`
- Modify: `docs/api-contract.md`
- Create: `tests/test_content_api.py`

- [ ] **Step 1: 写失败 API 测试**

```python
def test_content_api_creates_reads_edits_confirms_and_exports():
    created = client.post("/api/v1/content-tasks", headers=h(), json={
        "topic": "本周选题", "sources": [{"url": "https://example.com/a", "excerpt": "参考摘录"}],
        "knowledge_references": [], "idempotency_key": "content-1",
    })
    assert created.status_code == 201
    task_id = created.json()["task_id"]
    assert client.get(f"/api/v1/content-tasks/{task_id}", headers=h()).json()["status"] == "reviewing"
    updated = client.put(f"/api/v1/content-tasks/{task_id}/draft", headers=h(), json={
        "revision": 1, "title": "新标题", "summary": "摘要", "body_markdown": "正文", "image_suggestions": ["配图"],
    })
    assert updated.status_code == 200
    assert client.post(f"/api/v1/content-tasks/{task_id}/confirmation", headers=h(), json={"revision": 2}).status_code == 200
    exported = client.get(f"/api/v1/content-tasks/{task_id}/export.md", headers=h())
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/markdown")
    assert "# 新标题" in exported.text


def test_content_api_hides_cross_user_and_rejects_unconfirmed_export():
    created = create_content_task(user="owner")
    task_id = created.json()["task_id"]
    assert client.get(f"/api/v1/content-tasks/{task_id}", headers=h(user="other")).status_code == 404
    assert client.get(f"/api/v1/content-tasks/{task_id}/export.md", headers=h(user="owner")).status_code == 409
```

- [ ] **Step 2: 运行测试确认路由不存在**

Run: `python -m pytest tests/test_content_api.py -q`

Expected: FAIL with `404` for `/api/v1/content-tasks`.

- [ ] **Step 3: 增加请求模型和应用级内容服务装配**

在 `app/main.py` 增加 `ContentCreate`、`ContentSource`、`ContentDraftUpdate`、`ContentConfirmation` 和响应模型。应用初始化一个 `ContentStore` 与 `ContentService`，服务接收现有 `store`、`runtime_service` 和 `knowledge_access_registry`。新增路由严格把 `ContentNotFound` 映射为 `404`，输入 `ValueError` 映射为 `422`，幂等/版本冲突映射为 `409`，导出使用 `Response(content=..., media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": ...})`。

- [ ] **Step 4: 更新 API 契约**

在 `docs/api-contract.md` 添加内容任务 API、状态、幂等键、revision、导出门禁和“不抓取/不自动发布”边界，明确内容 API 仍以任务、运行和审计作为事实源。

- [ ] **Step 5: 运行后端回归**

Run: `python -m pytest tests/test_content_api.py tests/test_content_service.py tests -q`

Expected: all tests PASS。

- [ ] **Step 6: 提交**

```powershell
git add app/main.py tests/test_content_api.py docs/api-contract.md
git commit -m "feat: 接入内容工作台 API"
```

### Task 5: 构建 React 内容工作台页面

**Files:**
- Create: `admin-web/src/features/contentWorkbench/types.ts`
- Create: `admin-web/src/features/contentWorkbench/api.ts`
- Create: `admin-web/src/features/contentWorkbench/state.ts`
- Create: `admin-web/src/features/contentWorkbench/ContentWorkbenchPage.tsx`
- Create: `admin-web/src/features/contentWorkbench/ContentWorkbenchPage.test.tsx`
- Modify: `admin-web/src/app/App.tsx`
- Modify: `admin-web/src/app/AppShell.tsx`
- Modify: `admin-web/src/styles/global.css`

- [ ] **Step 1: 写失败组件测试，固定用户主流程**

```tsx
it('submits material, shows reviewing draft, edits, confirms, and downloads markdown', async () => {
  const user = userEvent.setup()
  mockContentApi()
  render(<ContentWorkbenchPage />)
  await user.type(screen.getByLabelText('内容主题'), '本周选题')
  await user.type(screen.getByLabelText('正文摘录'), '参考摘录')
  await user.click(screen.getByRole('button', { name: '开始生成' }))
  expect(await screen.findByText('待自检')).toBeInTheDocument()
  await user.clear(screen.getByLabelText('公众号标题'))
  await user.type(screen.getByLabelText('公众号标题'), '新标题')
  await user.click(screen.getByRole('button', { name: '保存修改' }))
  await user.click(screen.getByRole('button', { name: '确认并下载' }))
  expect(await screen.findByText('已确认')).toBeInTheDocument()
})
```

- [ ] **Step 2: 运行测试确认页面不存在**

Run: `npm test -- --run src/features/contentWorkbench/ContentWorkbenchPage.test.tsx`

Expected: FAIL because the feature files and export do not exist.

- [ ] **Step 3: 实现 API 客户端和页面状态**

`api.ts` 只调用 `/api/v1/content-tasks` 领域接口，统一处理 `401/404/409/5xx`，下载使用 Blob 和安全文件名。`state.ts` 生成稳定幂等键，保存当前任务号、revision 和状态恢复所需的最小信息，不把完整来源正文写入 localStorage。页面实现左右分栏：左侧主题/多条来源/知识资料输入，右侧状态条/Mock 标识/可编辑草稿/引用，确认前显示提示，失败保留素材并允许原任务重试。

- [ ] **Step 4: 接入现有 AppShell 和样式**

将 `App.tsx` 的员工默认入口改为 `ContentWorkbenchPage`；在 `AppShell` 增加“内容工作台”导航项，并保留知识权限管理入口的视觉一致性。不得添加自动发布按钮、抓取按钮或未实现的第三方 Runtime 入口。

- [ ] **Step 5: 完成前端交互测试**

覆盖输入校验、重复点击禁用、生成中、失败重试、编辑保存、revision 冲突、确认提示、已确认状态、下载调用、刷新恢复和权限错误。Mock `fetch` 响应必须包含真实 API 形状，不绕过页面状态机直接改 DOM。

- [ ] **Step 6: 运行前端测试和构建**

Run: `npm test -- --run`  
Run: `npm run build`

Expected: all tests PASS and Vite build succeeds。

- [ ] **Step 7: 提交**

```powershell
git add admin-web/src/features/contentWorkbench admin-web/src/app/App.tsx admin-web/src/app/AppShell.tsx admin-web/src/styles/global.css
git commit -m "feat: 增加公众号内容工作台页面"
```

### Task 6: 更新验收文档并执行 Alpha 回归

**Files:**
- Modify: `docs/delivery-gates.md`
- Modify: `README.md`
- Create: `tests/test_content_alpha.py`

- [ ] **Step 1: 写 10 次闭环验收测试**

`tests/test_content_alpha.py` 使用固定开发身份和脱敏素材循环 10 次：创建任务、读取 `reviewing` 草稿、编辑、确认、下载；同时对每次创建重复提交并断言任务号不变。测试不得连接真实外部 Runtime 或网络。

- [ ] **Step 2: 运行验收测试确认缺口**

Run: `python -m pytest tests/test_content_alpha.py -q`

Expected: FAIL until all API behavior is wired.

- [ ] **Step 3: 更新门禁与 README 状态**

在 `docs/delivery-gates.md` 增加：Mock 内容闭环、前端页面、10 次内部试跑已完成的独立检查项；明确真实模型、自动抓取、自动发布和客户验收仍未完成。README 只追加短状态段，不能将 Alpha 写成生产可用。

- [ ] **Step 4: 执行完整检查**

Run:

```powershell
python -m pytest -q
python -m compileall -q app tests extract_pdf.py
git diff --check
Set-Location admin-web
npm test -- --run
npm run build
```

Expected: all commands succeed。

- [ ] **Step 5: 提交文档和验收夹具**

```powershell
git add docs/delivery-gates.md README.md tests/test_content_alpha.py
git commit -m "test: 增加内容工作台 Alpha 验收"
```

## 执行顺序与完成定义

1. Task 1-3 完成后，内容领域服务可在内存中确定性生成、编辑、确认和导出。
2. Task 4 完成后，FastAPI 内容 API 可被开发身份调用，跨用户/租户和未确认导出门禁生效。
3. Task 5 完成后，员工可通过网页完成闭环，刷新可恢复状态。
4. Task 6 完成后，完整测试与 10 次内部 Mock 试跑通过，才可声明“内部 Alpha 可试用”。

真实模型、网页抓取、自动发布、桌面端、PWA、负责人审批和生产 staging 不属于本计划的完成条件。
