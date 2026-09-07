# 内容工作台 SQLite 持久化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为内容工作台增加本地 SQLite 持久化，使任务、草稿、确认状态和审计在后端重启后可恢复，同时保持现有 API 行为不变。

**Architecture:** 保留现有内存 `ContentStore` 作为测试实现，新增同契约的 `SQLiteContentStore`。`ContentService` 继续负责业务校验和状态转换，但在每次变更后通过仓储的原子保存接口写回；应用启动通过配置选择 SQLite 或显式内存实现。

**Tech Stack:** Python 3.11、FastAPI、Pydantic Settings、标准库 `sqlite3`、pytest、Playwright 浏览器脚本。

---

## 文件结构与职责

- Modify: `app/settings.py`，增加内容仓储后端和 SQLite 路径配置，并校验后端选项。
- Modify: `app/bootstrap.py`，新增 `build_content_store`，集中选择内存或 SQLite 实现。
- Modify: `app/main.py`，用装配函数替换硬编码的 `ContentStore()`。
- Modify: `app/content/store.py`，补充可持久化保存所需的统一 `save` 契约和内存实现。
- Create: `app/content/sqlite_store.py`，实现 SQLite schema、序列化、读写事务和权限过滤。
- Modify: `app/content/service.py`，在编辑、确认、撤销确认和导出审计后调用原子保存。
- Modify: `tests/conftest.py`，在测试收集前将 API 应用显式切换到内存后端，避免测试依赖开发数据库文件。
- Create: `tests/test_content_sqlite_store.py`，覆盖 SQLite CRUD、重启恢复、幂等和版本冲突。
- Modify: `tests/test_content_service.py`，验证服务变更会写回仓储。
- Modify: `tests/test_persistence_contract.py`，验证配置和装配规则。
- Modify: `.gitignore`，忽略 `data/` 和 SQLite 文件。
- Modify: `docs/api-contract.md`，补充开发环境内容仓储配置说明（API 路径本身不变）。

### Task 1: 先建立配置和装配的失败测试

**Files:**
- Test: `tests/test_persistence_contract.py`
- Test: `tests/conftest.py`
- Modify: `app/settings.py`
- Modify: `app/bootstrap.py`

- [ ] **Step 1: 写配置默认值、环境变量别名和后端选择的失败测试**

```python
def test_content_store_settings_default_to_sqlite_and_accept_path_override(monkeypatch):
    from app.settings import Settings

    monkeypatch.setenv("CONTENT_STORE_PATH", "tmp/custom-content.sqlite3")
    settings = Settings()
    assert settings.content_store_backend == "sqlite"
    assert settings.content_store_path == "tmp/custom-content.sqlite3"


def test_build_content_store_selects_explicit_memory_or_sqlite(tmp_path):
    from app.bootstrap import build_content_store
    from app.content.sqlite_store import SQLiteContentStore
    from app.content.store import ContentStore
    from app.settings import Settings

    assert isinstance(build_content_store(Settings(content_store_backend="memory")), ContentStore)
    store = build_content_store(Settings(content_store_backend="sqlite", content_store_path=str(tmp_path / "content.db")))
    assert isinstance(store, SQLiteContentStore)
    store.close()
```

`tests/conftest.py` 在任何 `app.main` 导入前设置 `WORKBENCH_CONTENT_STORE_BACKEND=memory`，使既有 API 测试保持隔离；SQLite 测试通过显式 `Settings` 使用临时路径。

- [ ] **Step 2: 运行测试确认它因配置字段和装配函数缺失而失败**

Run: `python -m pytest tests/test_persistence_contract.py -k "content_store_settings or build_content_store" -q`

Expected: FAIL，提示 `Settings` 没有 `content_store_backend` 或 `build_content_store` 未定义。

- [ ] **Step 3: 实现最小配置和装配代码**

在 `app/settings.py` 增加：

```python
from pydantic import AliasChoices, Field

content_store_backend: str = "sqlite"
content_store_path: str = Field(
    default="data/content-workbench.sqlite3",
    validation_alias=AliasChoices("CONTENT_STORE_PATH", "WORKBENCH_CONTENT_STORE_PATH"),
)
```

在 `validate_runtime_settings` 中仅允许 `sqlite` 和 `memory`，并禁止非开发环境使用 `memory`。

在 `app/bootstrap.py` 增加：

```python
def build_content_store(settings: Settings):
    validate_runtime_settings(settings)
    if settings.content_store_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存内容仓储")
        from .content.store import ContentStore
        return ContentStore()
    if settings.content_store_backend == "sqlite":
        from .content.sqlite_store import SQLiteContentStore
        path = Path(settings.content_store_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        return SQLiteContentStore(path)
    raise ValueError("不支持的内容仓储类型")
```

- [ ] **Step 4: 运行配置测试确认通过，并提交**

Run: `python -m pytest tests/test_persistence_contract.py -k "content_store_settings or build_content_store" -q`

Expected: 配置字段测试通过；选择 SQLite 的装配测试暂时因仓储模块尚未实现而失败，Task 2 完成后将整组置绿。本步骤只提交配置字段和装配接口骨架：

```bash
git add app/settings.py app/bootstrap.py tests/test_persistence_contract.py tests/conftest.py
git commit -m "feat: 增加内容仓储配置装配"
```

### Task 2: 实现 SQLite 仓储的创建、读取和重启恢复

**Files:**
- Test: `tests/test_content_sqlite_store.py`
- Create: `app/content/sqlite_store.py`
- Modify: `app/content/store.py`

- [ ] **Step 1: 写 SQLite 仓储的失败测试**

```python
def test_sqlite_store_round_trips_record_after_new_instance(tmp_path):
    first = SQLiteContentStore(tmp_path / "nested" / "content.sqlite3")
    record = make_record("task-1", "tenant-a", "user-a", "key-1")
    first.add(record)
    first.close()

    second = SQLiteContentStore(tmp_path / "nested" / "content.sqlite3")
    restored = second.get("tenant-a", "user-a", "task-1")
    assert restored.brief.topic == record.brief.topic
    assert restored.draft.body_markdown == record.draft.body_markdown
    assert restored.audits[0].action == "content.created"
    second.close()


def test_sqlite_store_scopes_idempotency_and_reads_by_tenant_user(tmp_path):
    store = SQLiteContentStore(tmp_path / "content.sqlite3")
    store.add(make_record("task-1", "tenant-a", "user-a", "same-key"))
    assert store.find_by_idempotency("tenant-a", "user-a", "same-key").task_id == "task-1"
    assert store.find_by_idempotency("tenant-b", "user-a", "same-key") is None
    with pytest.raises(KeyError):
        store.get("tenant-a", "other-user", "task-1")
    assert store.get("tenant-a", "admin", "task-1", elevated=True).task_id == "task-1"
    store.close()
```

`make_record` 使用现有 `ContentRecord`、`NormalizedBrief`、`ContentDraft` 和 `ContentAudit` 类型构造完整记录，确保测试的是实际序列化而不是简化字典。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_content_sqlite_store.py -q`

Expected: FAIL，提示 `SQLiteContentStore` 不存在。

- [ ] **Step 3: 实现 schema、序列化和只读/创建事务**

在 `app/content/sqlite_store.py` 中实现：

- `sqlite3.connect(str(path), check_same_thread=False, timeout=5)`，设置 `row_factory=sqlite3.Row`、外键和 busy timeout。
- 初始化 `content_store_meta`、`content_tasks`、`content_drafts`、`content_audits` 表及唯一/读取索引，schema 版本写入 `1`。
- 用 JSON 保存 `NormalizedBrief`、运行 ID、图片建议和引用；时间使用 ISO 8601，枚举保存 `.value`。
- `add` 在同一事务内写入任务、全部草稿、审计和幂等唯一索引。
- `find_by_idempotency` 与 `get` 通过行和子表重建 `ContentRecord`，沿用租户、用户和 elevated 过滤。
- `close` 关闭连接；重复 close 安全无副作用。

在 `app/content/store.py` 增加 `save(record, expected_revision=None)` 方法，内存实现直接保留当前对象并检查记录存在，作为 SQLite 实现的共同契约。

- [ ] **Step 4: 运行仓储测试确认通过并提交**

Run: `python -m pytest tests/test_content_sqlite_store.py tests/test_persistence_contract.py -q`

Expected: 所有 SQLite round-trip、租户隔离和装配测试 PASS。

```bash
git add app/content/store.py app/content/sqlite_store.py tests/test_content_sqlite_store.py app/settings.py app/bootstrap.py
git commit -m "feat: 增加内容工作台 SQLite 仓储"
```

### Task 3: 让服务变更原子写回并覆盖版本冲突

**Files:**
- Test: `tests/test_content_sqlite_store.py`
- Modify: `tests/test_content_service.py`
- Modify: `app/content/store.py`
- Modify: `app/content/sqlite_store.py`
- Modify: `app/content/service.py`

- [ ] **Step 1: 写持久化编辑、确认、撤销和审计的失败测试**

```python
def test_service_mutations_survive_store_reopen(tmp_path):
    store = SQLiteContentStore(tmp_path / "content.sqlite3")
    service = make_content_service(content_store=store)
    created = service.create(actor=employee("tenant-a", "user-a"), payload=brief("持久化"), idempotency_key="key-1")
    updated = service.update_draft(
        actor=employee("tenant-a", "user-a"), task_id=created.task_id, revision=1,
        title="已编辑", summary="摘要", body_markdown="正文", image_suggestions=["配图"],
    )
    service.confirm(actor=employee("tenant-a", "user-a"), task_id=created.task_id, revision=updated.revision)
    store.close()

    reopened = SQLiteContentStore(tmp_path / "content.sqlite3")
    restored = reopened.get("tenant-a", "user-a", created.task_id)
    assert restored.draft.status == ContentStatus.CONFIRMED
    assert restored.draft.title == "已编辑"
    assert [audit.action for audit in restored.audits] == [
        "content.created", "draft.updated", "draft.confirmed",
    ]
    reopened.close()
```

另加一个测试：读取 revision `1` 的记录后，先由第二个仓储实例保存 revision `2`，第一个实例使用旧 revision 调用 `save` 时抛出 `ContentStoreConflict`，且服务转换为现有 `RevisionConflict`。

- [ ] **Step 2: 运行测试确认它在当前服务中失败**

Run: `python -m pytest tests/test_content_sqlite_store.py -k "mutations_survive or conflict" -q`

Expected: FAIL，编辑后的标题或确认状态在重开仓储后仍不是新值，或 `make_content_service` 不接受注入仓储。

- [ ] **Step 3: 实现最小原子保存和服务写回**

将 `ContentService.make_content_service` 测试辅助函数改为接受可选 `content_store`；生产服务逻辑按以下顺序保存：

1. 读取当前记录并记录 `expected_revision`。
2. 按现有校验修改内存对象。
3. 调用 `content_store.save(record, expected_revision=expected_revision)`。
4. 将存储层版本冲突转换为原有中文 `RevisionConflict`。

SQLite `save` 在一个写事务中：

- 先按任务范围和权限验证当前数据库 revision。
- 使用 `WHERE task_id = ? AND revision = ?` 更新/替换当前草稿集合。
- 同事务替换审计行和任务的运行 ID/brief JSON。
- 受影响行数不为预期时回滚并抛出 `ContentStoreConflict`。

内存 `save` 保留对象语义；`export_markdown` 追加 `draft.exported` 审计后也必须调用 `save`，确认、撤销确认同理。

- [ ] **Step 4: 运行服务和仓储测试确认通过并提交**

Run: `python -m pytest tests/test_content_service.py tests/test_content_sqlite_store.py -q`

Expected: 服务原有行为、SQLite 重启恢复和 revision 冲突全部 PASS。

```bash
git add app/content/service.py app/content/store.py app/content/sqlite_store.py tests/test_content_service.py tests/test_content_sqlite_store.py
git commit -m "feat: 持久化内容草稿状态和审计"
```

### Task 4: 接入应用、隔离测试数据库并补充文档

**Files:**
- Modify: `app/main.py`
- Modify: `tests/conftest.py`
- Modify: `.gitignore`
- Modify: `docs/api-contract.md`
- Modify: `tests/test_persistence_contract.py`

- [ ] **Step 1: 写应用装配和文件忽略的失败测试**

```python
def test_development_app_uses_configured_content_store_path(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTENT_STORE_PATH", str(tmp_path / "configured.sqlite3"))
    settings = Settings()
    store = build_content_store(settings)
    assert store.path == Path(tmp_path / "configured.sqlite3")
    store.close()
```

同时检查 `.gitignore` 包含 `data/` 和 `*.sqlite3`，并在 `docs/api-contract.md` 记录 `CONTENT_STORE_PATH` 的开发配置说明。

- [ ] **Step 2: 运行测试确认应用仍硬编码内存仓储**

Run: `python -m pytest tests/test_persistence_contract.py -k "configured_content_store_path" -q`

Expected: FAIL，应用装配未调用 `build_content_store` 或 SQLite 路径属性未暴露。

- [ ] **Step 3: 接入应用并完成测试隔离**

在 `app/main.py` 导入并调用 `build_content_store(settings)`，替换 `ContentStore()`；保留已确认的 CORS 配置。

在 `tests/conftest.py` 顶部设置：

```python
import os

os.environ.setdefault("WORKBENCH_CONTENT_STORE_BACKEND", "memory")
```

在 `.gitignore` 增加：

```gitignore
data/
*.sqlite3
```

文档说明：开发默认 SQLite，测试/临时场景可设置 `WORKBENCH_CONTENT_STORE_BACKEND=memory`，路径可用 `CONTENT_STORE_PATH` 覆盖。

- [ ] **Step 4: 运行后端完整回归并提交**

Run: `python -m pytest -q`

Expected: 全部现有测试和新增测试 PASS。

```bash
git add app/main.py tests/conftest.py .gitignore docs/api-contract.md tests/test_persistence_contract.py
git commit -m "feat: 内容工作台默认启用 SQLite 持久化"
```

### Task 5: 运行构建、重启恢复和浏览器验收

**Files:**
- Modify: `tmp/content_alpha_browser_test.py` only if needed for restart assertion; do not commit `tmp/`.

- [ ] **Step 1: 执行静态和前端回归**

Run:

```powershell
python -m compileall -q app tests extract_pdf.py
git diff --check
Push-Location admin-web
npm test -- --run
npm run build
Pop-Location
```

Expected: Python 编译、前端测试和构建均以退出码 `0` 完成。

- [ ] **Step 2: 启动使用 SQLite 默认路径的后端和现有前端**

Run:

```powershell
python -m uvicorn app.main:app --port 8010
$env:VITE_API_BASE_URL='http://127.0.0.1:8010/api/v1'
npm run dev -- --host 127.0.0.1 --port 5174
```

Expected: 前端 `http://127.0.0.1:5174`，后端 `http://127.0.0.1:8010` 可访问，数据库文件出现在 `data/content-workbench.sqlite3`。

- [ ] **Step 3: 执行浏览器闭环并验证重启恢复**

Run: `python -u tmp/content_alpha_browser_test.py`

Expected: 生成、编辑、确认、Markdown 下载通过；停止并重新启动后端后，用同一任务 ID 的 GET 仍返回 `confirmed` 和编辑后的标题。

- [ ] **Step 4: 完成收尾检查**

Run:

```powershell
git status --short --branch
git log -5 --oneline
```

Expected：只有预期提交和已有未跟踪 `.superpowers/`，不包含 `data/`、`tmp/`、`node_modules/` 或数据库文件。

完成后报告：SQLite 配置路径、重启恢复证据、后端/前端测试结果和最终提交列表。
