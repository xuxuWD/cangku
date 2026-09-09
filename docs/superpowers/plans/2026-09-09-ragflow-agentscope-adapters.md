# RAGFlow 与 AgentScope 适配器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 FastAPI 控制平面的 Runtime 边界内增加 RAGFlow 只读知识检索和 AgentScope 运行时适配器，并通过受控配置、契约测试和文档同步使其可在开发期安全接入。

**Architecture:** RAGFlowAdapter 与 AgentScopeAdapter 都复用 `ExternalAdapter` 和 `HttpRuntimeTransport`，第三方服务只承担协议转换后的检索或执行，不拥有租户、权限、审批、审计和最终任务状态。RAGFlow 仅暴露受 `RuntimeContext.knowledge_scope` 限制的 `search()`；AgentScope 复用现有运行生命周期、事件游标和命令边界，并把未知事件映射为 `run.failed`。

**Tech Stack:** Python 3.11+、dataclasses、现有 Runtime Protocol、`httpx`、pytest、FakeTransport/MockTransport。

---

### Task 1: 扩展运行时契约和传输层的知识检索边界

**Files:**
- Modify: `app/runtime/contracts.py`
- Modify: `app/runtime/adapters/common.py`
- Modify: `app/runtime/adapters/__init__.py`
- Test: `tests/test_runtime_contracts.py`
- Test: `tests/test_runtime_http_transport.py`

- [ ] **Step 1: Write the failing tests**

在 `tests/test_runtime_contracts.py` 增加：

```python
from app.runtime.contracts import KnowledgeCitation


def test_knowledge_citation_requires_the_public_reference_fields() -> None:
    citation = KnowledgeCitation(
        document_id="doc-1",
        knowledge_base_id="kb-1",
        title="设备维护手册",
        snippet="检查电源和散热。",
        score=0.92,
    )

    assert citation.document_id == "doc-1"
    assert citation.knowledge_base_id == "kb-1"
    assert citation.score == 0.92
```

在 `tests/test_runtime_http_transport.py` 增加：

```python
def test_http_transport_searches_knowledge_without_exposing_internal_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"items": [{"document_id": "doc-1"}]})

    transport = HttpRuntimeTransport(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    data = transport.knowledge_search(
        "https://ragflow.example/api",
        {"tenant_id": "tenant-1", "knowledge_base_ids": ["kb-1"], "query": "故障", "limit": 1},
    )

    assert data["items"][0]["document_id"] == "doc-1"
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/api/knowledge-search"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q tests/test_runtime_contracts.py::test_knowledge_citation_requires_the_public_reference_fields tests/test_runtime_http_transport.py::test_http_transport_searches_knowledge_without_exposing_internal_fields`

Expected: FAIL because `KnowledgeCitation` and `HttpRuntimeTransport.knowledge_search` do not exist.

- [ ] **Step 3: Write the minimal implementation**

在 `app/runtime/contracts.py` 的 `RuntimeContext` 前增加：

```python
@dataclass(frozen=True)
class KnowledgeCitation:
    document_id: str
    knowledge_base_id: str
    title: str
    snippet: str
    score: float | None = None
```

在 `HttpRuntimeTransport` 增加只读方法，复用 `_request` 并只返回字典：

```python
def knowledge_search(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    return self._request("POST", f"{self._base(endpoint)}/knowledge-search", json=payload)
```

在 `FakeTransport` 增加 `knowledge_search`，从可注入的 `knowledge_items` 返回 `{"items": ...}`，并把请求记录到 `requests`；在 `adapters/__init__.py` 导出新增契约所需的现有传输类型，不改变既有适配器导出。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q tests/test_runtime_contracts.py::test_knowledge_citation_requires_the_public_reference_fields tests/test_runtime_http_transport.py::test_http_transport_searches_knowledge_without_exposing_internal_fields`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/runtime/contracts.py app/runtime/adapters/common.py app/runtime/adapters/__init__.py tests/test_runtime_contracts.py tests/test_runtime_http_transport.py
git commit -m "feat: 增加知识引用与检索传输契约"
```

### Task 2: 实现 RAGFlow 只读检索适配器

**Files:**
- Create: `app/runtime/adapters/ragflow.py`
- Modify: `app/runtime/adapters/__init__.py`
- Test: `tests/test_ragflow_adapter.py`

- [ ] **Step 1: Write the failing tests**

创建 `tests/test_ragflow_adapter.py`，使用带 `knowledge_search` 的 FakeTransport 和现有 `RuntimeContext` 工厂，覆盖成功、输入边界、空范围、字段缺失和越权整批拒绝：

```python
def test_search_sends_context_scope_and_maps_citations() -> None:
    transport = FakeTransport(
        knowledge_items=[{
            "document_id": "doc-1", "knowledge_base_id": "kb-1",
            "title": "手册", "snippet": "先断电。", "score": 0.8,
        }]
    )
    citations = RAGFlowAdapter(transport, "https://ragflow").search(
        context=make_context(knowledge_scope=("kb-1",)), query="设备故障", limit=5
    )
    assert citations[0].document_id == "doc-1"
    assert transport.requests[-1]["tenant_id"] == "t1"
    assert transport.requests[-1]["knowledge_base_ids"] == ["kb-1"]


@pytest.mark.parametrize("query", ["", "x" * 2001])
def test_search_rejects_invalid_query(query: str) -> None:
    with pytest.raises(ValueError):
        RAGFlowAdapter(FakeTransport(), "https://ragflow").search(
            context=make_context(), query=query
        )


def test_search_returns_empty_for_empty_knowledge_scope() -> None:
    transport = FakeTransport(knowledge_items=[{"document_id": "wrong"}])
    result = RAGFlowAdapter(transport, "https://ragflow").search(
        context=make_context(knowledge_scope=()), query="查询"
    )
    assert result == []
    assert transport.requests == []


def test_search_rejects_missing_reference_fields() -> None:
    transport = FakeTransport(knowledge_items=[{"document_id": "doc-1", "knowledge_base_id": "kb-1"}])
    with pytest.raises(TransportError, match="引用"):
        RAGFlowAdapter(transport, "https://ragflow").search(context=make_context(), query="查询")


def test_search_rejects_cross_tenant_or_out_of_scope_items_without_partial_results() -> None:
    transport = FakeTransport(knowledge_items=[{
        "tenant_id": "other", "document_id": "doc-1", "knowledge_base_id": "kb-1",
        "title": "手册", "snippet": "内容",
    }])
    with pytest.raises(TransportError, match="范围"):
        RAGFlowAdapter(transport, "https://ragflow").search(context=make_context(), query="查询")
```

`make_context` 返回 `tenant_id="t1"`、`knowledge_scope=("kb-1",)` 的有效 `RuntimeContext`；测试同时断言适配器没有 `write`、`delete` 或任意 URL 方法。

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q tests/test_ragflow_adapter.py`

Expected: FAIL because `RAGFlowAdapter` is not defined and FakeTransport 尚未接受知识结果参数。

- [ ] **Step 3: Write the minimal implementation**

在 `ragflow.py` 实现：

```python
class RAGFlowAdapter:
    def __init__(self, transport: Any, endpoint: str) -> None:
        self.transport = transport
        self.endpoint = endpoint

    def search(self, *, context: RuntimeContext, query: str, limit: int = 10) -> list[KnowledgeCitation]:
        if not isinstance(query, str) or not 1 <= len(query) <= 2000:
            raise ValueError("查询长度必须在 1 到 2000 个字符之间")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("检索条数必须在 1 到 50 之间")
        if not context.knowledge_scope:
            return []
        payload = {
            "tenant_id": context.tenant_id,
            "knowledge_base_ids": list(context.knowledge_scope),
            "query": query,
            "limit": limit,
        }
        data = self.transport.knowledge_search(self.endpoint, payload)
        items = data.get("items")
        if not isinstance(items, list):
            raise TransportError("RAGFlow 引用响应格式无效")
        citations: list[KnowledgeCitation] = []
        for item in items:
            if not isinstance(item, dict):
                raise TransportError("RAGFlow 引用响应格式无效")
            if item.get("tenant_id", context.tenant_id) != context.tenant_id:
                raise TransportError("RAGFlow 返回结果超出租户范围")
            document_id = item.get("document_id")
            knowledge_base_id = item.get("knowledge_base_id")
            title = item.get("title")
            snippet = item.get("snippet")
            if not all(isinstance(value, str) and value for value in (document_id, knowledge_base_id, title, snippet)):
                raise TransportError("RAGFlow 引用字段缺失")
            if knowledge_base_id not in context.knowledge_scope:
                raise TransportError("RAGFlow 返回结果超出知识库范围")
            score = item.get("score")
            if score is not None and not isinstance(score, (int, float)):
                raise TransportError("RAGFlow 引用分数格式无效")
            citations.append(KnowledgeCitation(document_id, knowledge_base_id, title, snippet, score))
        return citations
```

所有协议问题都抛出 `TransportError`；不实现写入、删除、索引或 URL 拼接以外的访问入口。导出 `RAGFlowAdapter`。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q tests/test_ragflow_adapter.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/runtime/adapters/ragflow.py app/runtime/adapters/__init__.py tests/test_ragflow_adapter.py
git commit -m "feat: 增加 RAGFlow 只读检索适配器"
```

### Task 3: 实现 AgentScope 运行时适配器并锁定审批边界

**Files:**
- Create: `app/runtime/adapters/agentscope.py`
- Modify: `app/runtime/adapters/__init__.py`
- Test: `tests/test_runtime_adapters.py`

- [ ] **Step 1: Write the failing tests**

增加以下行为测试：

```python
def test_agentscope_adds_fixed_runtime_key_and_preserves_approval_flags() -> None:
    transport = FakeTransport()
    adapter = AgentScopeAdapter(transport, "https://agentscope")
    run = adapter.start_run(
        context(), AgentPlan.from_steps([{"step_id": "s1", "kind": "write", "tool": "file.write"}])
    )
    payload = transport.requests[-1]
    assert run.startswith("run-")
    assert payload["runtime_key"] == "agentscope"
    assert payload["plan"][0]["requires_approval"] is True
    assert payload["context"]["tenant_id"] == "t1"


def test_agentscope_maps_known_events_and_unknown_events_to_failure() -> None:
    transport = FakeTransport(events=[
        {"type": "step.started", "payload": {"step_id": "s1"}},
        {"type": "checkpoint.saved", "payload": {"token": "hidden"}},
        {"type": "vendor.new_event", "payload": {"cookie": "hidden"}},
    ])
    adapter = AgentScopeAdapter(transport, "https://agentscope")
    run = adapter.start_run(context(), AgentPlan.from_steps([]))
    events = adapter.stream_events(run)
    assert [event.event_type.value for event in events] == ["step.started", "checkpoint.saved", "run.failed"]
    assert events[-1].to_public_dict()["payload"]["cookie"] == "[已隐藏]"


def test_agentscope_reuses_lifecycle_commands_without_automatic_retry() -> None:
    transport = FakeTransport()
    adapter = AgentScopeAdapter(transport, "https://agentscope")
    run = adapter.start_run(context(), AgentPlan.from_steps([]))
    adapter.pause_run(run, "人工检查")
    adapter.resume_run(run)
    adapter.cancel_run(run, "取消")
    approval_id = adapter.request_approval(run, {"step_id": "s1"})
    adapter.replay_run(run, "s1")
    assert approval_id.startswith("approval-")
    assert [request["action"] for request in transport.requests[1:]] == [
        "pause", "resume", "cancel", "approvals", "replay",
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q tests/test_runtime_adapters.py -k agentscope`

Expected: FAIL because `AgentScopeAdapter` is not defined and the new runtime key is not added.

- [ ] **Step 3: Write the minimal implementation**

在 `agentscope.py` 继承 `ExternalAdapter`，只覆盖 `_payload`：

```python
class AgentScopeAdapter(ExternalAdapter):
    def __init__(self, transport: Any, endpoint: str) -> None:
        super().__init__(transport, endpoint, "agentscope")

    def _payload(self, context: RuntimeContext, plan: AgentPlan) -> dict[str, Any]:
        payload = super()._payload(context, plan)
        payload["runtime_key"] = "agentscope"
        return payload
```

在 `ExternalAdapter.stream_events` 的映射表补充 `tool.call`、`checkpoint.saved`、`run.paused`；未知类型仍生成 `RuntimeEventType.RUN_FAILED`，并保留脱敏前的 `remote_type` 作为普通字符串。不得从外部响应覆盖 `RuntimeContext`，不得自动重试命令。导出 `AgentScopeAdapter`。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q tests/test_runtime_adapters.py -k agentscope tests/test_runtime_adapters.py -k 'not agentscope'`

Expected: PASS，既有 DeerFlow、Codex Worker、Hermes 测试不回归。

- [ ] **Step 5: Commit**

```bash
git add app/runtime/adapters/agentscope.py app/runtime/adapters/common.py app/runtime/adapters/__init__.py tests/test_runtime_adapters.py
git commit -m "feat: 增加 AgentScope 运行时适配器"
```

### Task 4: 接入受控 Runtime 注册表和固定版本配置

**Files:**
- Modify: `app/runtime/registry.py`
- Test: `tests/test_runtime_registry_config.py`

- [ ] **Step 1: Write the failing tests**

增加配置测试：

```python
@pytest.mark.parametrize("key", ["ragflow", "agentscope"])
def test_enabled_new_runtime_is_explicitly_registered(key: str) -> None:
    registry = build_runtime_registry(
        {key: {
            "enabled": True, "endpoint": f"https://{key}.example",
            "capabilities": ["read"], "version": "v1.0.0",
        }},
        transport_factory=lambda _key, _config: FakeTransport(),
    )
    assert key in registry.keys()


@pytest.mark.parametrize("version", [None, "", "latest", "main", "head"])
def test_enabled_external_runtime_requires_fixed_version(version: str | None) -> None:
    with pytest.raises(RuntimeConfigError, match="版本"):
        build_runtime_registry({
            "agentscope": {
                "enabled": True, "endpoint": "https://agentscope.example",
                "capabilities": ["run"], "version": version,
            }
        })


def test_new_external_runtimes_remain_disabled_by_default() -> None:
    assert build_runtime_registry({}).keys() == ("mock",)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q tests/test_runtime_registry_config.py`

Expected: FAIL because constructors and `version` validation are absent.

- [ ] **Step 3: Write the minimal implementation**

在 `RuntimeEndpointConfig` 增加 `version: str`；在 constructors 中注册 `"ragflow": RAGFlowAdapter` 与 `"agentscope": AgentScopeAdapter`。增加：

```python
def _validate_version(key: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or value.lower() in {"latest", "main", "head"}:
        raise RuntimeConfigError(f"{key} Runtime 需要固定版本")
    return value
```

仅在 `enabled` 为真时校验 endpoint、capabilities、timeout 和 version；保持默认只注册 `mock`。将 `version` 保存于 `RuntimeEndpointConfig`，但不把认证头、Cookie 或 API Key 放入配置对象、载荷或日志。更新既有测试中的启用外部 Runtime 配置以提供固定版本。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q tests/test_runtime_registry_config.py`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add app/runtime/registry.py tests/test_runtime_registry_config.py
git commit -m "feat: 注册 RAGFlow 与 AgentScope 并校验版本"
```

### Task 5: 同步 API、架构和交付门禁文档

**Files:**
- Modify: `docs/api-contract.md`
- Modify: `docs/architecture.md`
- Modify: `docs/delivery-gates.md`

- [ ] **Step 1: Add the contract text**

在 `docs/api-contract.md` 的“Agent Runtime 运行”下增加 RAGFlow/AgentScope 约定：`POST {endpoint}/knowledge-search` 只读、知识库范围来自服务端上下文；AgentScope 的 `/runs`、`/events`、暂停/恢复/取消/审批/重放/usage 和 `/health` 均为外部协议，外部服务不能覆盖工作台上下文。明确未知事件变为 `run.failed`，认证由部署环境注入，开发期 FakeTransport 不等于 staging 验收。

在 `docs/architecture.md` 补充两条组件边界：RAGFlow 仅提供带引用的租户内检索，AgentScope 仅提供受控执行；两者不能直连工作台数据库或决定最终状态。

在 `docs/delivery-gates.md` 增加已完成项“开发期 RAGFlow/AgentScope 适配器契约与受控注册表”，并保留未完成项“真实 staging 与真实平台账号验收”；不得勾选密钥注入、跨租户实测、并发压测、沙箱验证和真实外部服务验收。

- [ ] **Step 2: Verify documentation wording and links**

Run: `rg -n "RAGFlow|AgentScope|staging|真实" docs/api-contract.md docs/architecture.md docs/delivery-gates.md`

Expected: 三份文档均包含开发期边界和未完成的真实验收声明，且没有“已上线”“已发布”等不实表述。

- [ ] **Step 3: Commit**

```bash
git add docs/api-contract.md docs/architecture.md docs/delivery-gates.md
git commit -m "docs: 同步 RAGFlow 与 AgentScope 接入边界"
```

### Task 6: 全量回归与交付检查

**Files:**
- Modify: none
- Test: all existing tests and new adapter tests

- [ ] **Step 1: Run the focused adapter suite**

Run: `python -m pytest -q tests/test_ragflow_adapter.py tests/test_runtime_adapters.py tests/test_runtime_registry_config.py tests/test_runtime_http_transport.py`

Expected: PASS。

- [ ] **Step 2: Run the complete verification commands**

Run: `python -m pytest -q`

Expected: 全部测试通过。

Run: `python -m compileall -q app tests scripts/commercial_g0_preflight.py`

Expected: 命令成功且无输出。

Run: `git diff --check`

Expected: 无空白错误。

- [ ] **Step 3: Inspect the final diff and status**

Run: `git status --short --branch` and `git diff HEAD~5..HEAD --stat`。

确认仅包含适配器、契约测试、注册表和三份文档变更；不包含 `.env`、密钥、Cookie、临时媒体或真实第三方凭据。

- [ ] **Step 4: Commit the verification record if documentation changed**

若验证过程中只产生测试缓存，不提交缓存；若需要补充交付说明，使用：

```bash
git add docs/delivery-gates.md
git commit -m "docs: 标记开发期适配器交付门禁"
```

## Self-Review Checklist

- 规格中的 RAGFlow 只读、租户/知识库范围校验、字段错误和输入边界由 Task 1-2 覆盖。
- 规格中的 AgentScope 启动载荷、审批标记、事件映射、生命周期命令和无自动降级由 Task 3 覆盖。
- 规格中的显式启用、固定版本、默认 Mock 和认证不入配置由 Task 4 覆盖。
- API 契约、架构边界和 staging 未完成状态由 Task 5 覆盖。
- 所有任务都先写失败测试，再实现，再运行聚焦测试并提交；Task 6 负责全量 pytest、编译和 diff 校验。
- 计划中没有要求安装第三方 SDK、调用真实外部服务或宣称 staging 已完成。
