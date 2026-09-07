# 内容工作台模型供应商适配层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持内容工作台现有 API 和业务流程稳定的前提下，增加 Mock/OpenAI-compatible 可切换的结构化内容生成器，并让失败任务可审计、可重新生成。

**Architecture:** 新增窄接口 `ContentGenerator`，由 `MockContentGenerator` 和 `OpenAICompatibleContentGenerator` 实现。`ContentService` 只依赖该接口，配置装配决定实现；模型调用失败转换为 `failed` 草稿和脱敏审计，不自动降级。新增重新生成路由复用同一任务和素材，创建新的 run/draft。

**Tech Stack:** Python 3.11、FastAPI、Pydantic Settings、httpx、标准库 JSON/时间/重试、pytest、前端现有 Vite/Vitest。

---

## 文件结构与职责

- Modify: `app/settings.py`，增加内容生成后端、模型地址、模型名、密钥、超时和重试配置。
- Create: `app/content/generator.py`，定义输入/输出类型、生成器协议、错误类型和 Mock 实现。
- Create: `app/content/openai_compatible.py`，实现 OpenAI-compatible `/v1/chat/completions` 请求、重试和严格解析。
- Modify: `app/content/service.py`，注入生成器；创建/重新生成时调用生成器；处理失败状态和生成审计。
- Modify: `app/content/models.py`，补充生成失败元数据需要的字段约束或错误摘要类型。
- Modify: `app/bootstrap.py`，新增 `build_content_generator`。
- Modify: `app/main.py`，装配生成器并新增重新生成接口及失败错误映射。
- Modify: `.env.example`（如存在），记录供应商无关配置。
- Create: `tests/test_content_generator.py`，生成器契约和 Mock 测试。
- Create: `tests/test_content_openai_compatible.py`，HTTP 请求、解析、重试和脱敏测试。
- Modify: `tests/test_content_service.py`，覆盖真实生成器注入、失败状态和重新生成。
- Modify: `tests/test_content_api.py`，覆盖重新生成和失败 API 行为。
- Modify: `tests/test_persistence_contract.py`，覆盖生成配置和装配。
- Modify: `docs/api-contract.md`，补充生成后端配置和重新生成接口。

### Task 1: 写生成器领域契约和配置的失败测试

**Files:**
- Test: `tests/test_content_generator.py`
- Test: `tests/test_persistence_contract.py`
- Modify: `app/settings.py`
- Create: `app/content/generator.py`

- [ ] **Step 1: 写生成器输入/输出、Mock 和配置的失败测试**

```python
def test_mock_generator_returns_structured_draft_from_normalized_brief():
    generator = MockContentGenerator()
    result = generator.generate(ContentGenerationInput(
        topic="团队协作", sources=(NormalizedSource("", "素材摘录"),),
        knowledge_references=(), template_version="mock-content-v1",
    ))
    assert result.title.startswith("团队协作")
    assert result.body_markdown
    assert result.image_suggestions
    assert result.provider == "mock"


def test_content_generation_settings_default_to_mock_and_accept_openai_config(monkeypatch):
    from app.settings import Settings

    monkeypatch.setenv("CONTENT_GENERATION_BACKEND", "openai_compatible")
    monkeypatch.setenv("CONTENT_MODEL_BASE_URL", "https://model.internal/v1")
    monkeypatch.setenv("CONTENT_MODEL_NAME", "company-text")
    monkeypatch.setenv("CONTENT_MODEL_API_KEY", "secret-value")
    settings = Settings()
    assert settings.content_generation_backend == "openai_compatible"
    assert settings.content_model_base_url == "https://model.internal/v1"
    assert settings.content_model_name == "company-text"
    assert settings.content_model_api_key == "secret-value"
    assert Settings(_env_file=None).content_generation_backend == "mock"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_content_generator.py tests/test_persistence_contract.py -k "generator or content_generation" -q`

Expected: FAIL，提示生成器模块或 Settings 配置字段不存在。

- [ ] **Step 3: 实现最小领域类型、Mock 和配置字段**

`ContentGenerationInput` 使用不可变字段：`topic`、`sources`、`knowledge_references`、`template_version`；`GeneratedContentDraft` 包含 `title`、`summary`、`body_markdown`、`image_suggestions`、`provider`、`model_name`、`template_version`。

`MockContentGenerator.generate` 复用现有确定性模板逻辑，但只返回生成字段，不创建 `ContentDraft` 或审计。

配置增加：

```python
content_generation_backend: str = Field(default="mock", validation_alias=AliasChoices("CONTENT_GENERATION_BACKEND", "WORKBENCH_CONTENT_GENERATION_BACKEND"))
content_model_base_url: str = Field(default="", validation_alias=AliasChoices("CONTENT_MODEL_BASE_URL", "WORKBENCH_CONTENT_MODEL_BASE_URL"))
content_model_name: str = Field(default="", validation_alias=AliasChoices("CONTENT_MODEL_NAME", "WORKBENCH_CONTENT_MODEL_NAME"))
content_model_api_key: str = Field(default="", validation_alias=AliasChoices("CONTENT_MODEL_API_KEY", "WORKBENCH_CONTENT_MODEL_API_KEY"))
content_model_timeout_seconds: float = Field(default=30.0, ge=1, le=120, validation_alias=AliasChoices("CONTENT_MODEL_TIMEOUT_SECONDS", "WORKBENCH_CONTENT_MODEL_TIMEOUT_SECONDS"))
content_model_max_retries: int = Field(default=2, ge=0, le=5, validation_alias=AliasChoices("CONTENT_MODEL_MAX_RETRIES", "WORKBENCH_CONTENT_MODEL_MAX_RETRIES"))
```

- [ ] **Step 4: 运行生成器和配置测试确认通过，并提交**

Run: `python -m pytest tests/test_content_generator.py tests/test_persistence_contract.py -k "generator or content_generation" -q`

Expected: PASS。

```bash
git add app/settings.py app/content/generator.py tests/test_content_generator.py tests/test_persistence_contract.py
git commit -m "feat: 增加内容生成器契约和 Mock 实现"
```

### Task 2: 实现 OpenAI-compatible HTTP 适配器

**Files:**
- Test: `tests/test_content_openai_compatible.py`
- Create: `app/content/openai_compatible.py`

- [ ] **Step 1: 写 HTTP 请求、成功解析和失败重试的失败测试**

```python
def test_openai_compatible_generator_posts_structured_request_without_leaking_context():
    transport = FakeHttpTransport([fake_success_response()])
    generator = OpenAICompatibleContentGenerator(
        base_url="https://model.internal/v1", model_name="company-text", api_key="secret", timeout_seconds=3,
        max_retries=0, client=transport,
    )
    result = generator.generate(sample_input())
    request = transport.requests[0]
    assert request["url"] == "https://model.internal/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer secret"
    assert request["json"]["model"] == "company-text"
    assert "tenant_id" not in json.dumps(request["json"])
    assert result.title == "模型标题"


def test_openai_compatible_generator_retries_timeout_and_does_not_retry_4xx():
    retry_transport = FakeHttpTransport([TimeoutError(), TimeoutError(), fake_success_response()])
    generator = make_generator(retry_transport, max_retries=2)
    assert generator.generate(sample_input()).title == "模型标题"
    assert len(retry_transport.requests) == 3

    bad_request_transport = FakeHttpTransport([HttpResponseError(401)])
    with pytest.raises(ContentGenerationError, match="模型请求失败"):
        make_generator(bad_request_transport, max_retries=2).generate(sample_input())
    assert len(bad_request_transport.requests) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_content_openai_compatible.py -q`

Expected: FAIL，提示适配器模块不存在。

- [ ] **Step 3: 实现 HTTP 适配器和严格响应校验**

实现要求：

- 接受可注入客户端；生产默认使用 `httpx.Client`，测试不访问外网。
- `base_url.rstrip("/")` 后若结尾是 `/v1`，拼接 `/chat/completions`；否则拼接 `/v1/chat/completions`。
- 发送 `Authorization`、`Content-Type`、`Accept`；请求只包含系统提示和脱敏素材字段。
- 读取 `choices[0].message.content`，必须解析为 JSON 对象。
- 检查 `title`、`summary`、`body_markdown` 为非空字符串，`image_suggestions` 为最多 20 条字符串。
- 连接错误、超时和 5xx 最多重试 `max_retries` 次，退避使用 `min(0.25 * 2**attempt, 2.0)`；测试注入 `sleep=lambda _: None`。
- 4xx、认证失败、JSON/字段错误直接抛出 `ContentGenerationError`，错误文本不包含 API Key、Authorization 或原始响应全文。

- [ ] **Step 4: 运行适配器测试确认通过并提交**

Run: `python -m pytest tests/test_content_openai_compatible.py -q`

Expected: PASS。

```bash
git add app/content/openai_compatible.py tests/test_content_openai_compatible.py
git commit -m "feat: 增加 OpenAI-compatible 内容模型适配器"
```

### Task 3: 接入内容服务、失败状态和重新生成

**Files:**
- Test: `tests/test_content_service.py`
- Modify: `app/content/service.py`
- Modify: `app/content/models.py`

- [ ] **Step 1: 写服务失败状态、成功元数据和重新生成的失败测试**

```python
def test_generation_failure_is_audited_and_not_exportable():
    service = make_content_service(content_generator=FailingGenerator("模型不可用"))
    created = service.create(actor=employee("tenant-a", "u1"), payload=brief("失败用例"), idempotency_key="k1")
    assert created.draft.status == ContentStatus.FAILED
    assert created.audits[-1].action == "content.generation.failed"
    with pytest.raises(ExportNotAllowed):
        service.export_markdown(actor=employee("tenant-a", "u1"), task_id=created.task_id)


def test_regenerate_reuses_task_and_creates_new_run_and_draft():
    generator = SequenceGenerator(["first", "second"])
    service = make_content_service(content_generator=generator)
    created = service.create(actor=employee("tenant-a", "u1"), payload=brief("重试"), idempotency_key="k1")
    regenerated = service.regenerate(actor=employee("tenant-a", "u1"), task_id=created.task_id, idempotency_key="regen-1")
    assert regenerated.task_id == created.task_id
    assert regenerated.run_id != created.run_id
    assert regenerated.draft.title == "second"
```

- [ ] **Step 2: 运行测试确认当前服务失败**

Run: `python -m pytest tests/test_content_service.py -k "generation_failure or regenerate" -q`

Expected: FAIL，当前服务没有可注入生成器或 `regenerate` 方法。

- [ ] **Step 3: 实现服务接入和失败/成功持久化**

将 `ContentService` 构造器增加可选 `content_generator`，默认使用 `MockContentGenerator`，以保留现有单元测试调用方式。

创建和重新生成流程：

1. 创建或复用任务、素材和 Runtime run。
2. 写入 `content.generation.started`。
3. 调用生成器，将结果转换为 `ContentDraft`；引用始终使用 brief 来源，状态为 `reviewing`。
4. 捕获 `ContentGenerationError`，创建状态为 `failed` 的草稿，正文为空，审计写入固定动作 `content.generation.failed` 和脱敏原因摘要。
5. 成功写入 `content.generation.completed`，只记录 provider/model/耗时等元数据，不写原始响应。
6. 使用现有 `content_store.add/save` 持久化整个记录。

`regenerate` 校验任务权限，使用新的幂等键避免重复 run；不创建第二个业务任务，将新 run ID 追加到 `run_ids`，旧草稿和审计保留。失败也复用同一任务，当前草稿状态为 `failed`。

- [ ] **Step 4: 运行服务测试确认通过并提交**

Run: `python -m pytest tests/test_content_service.py -q`

Expected: 原有内容服务测试和新增失败/重新生成测试全部 PASS。

```bash
git add app/content/models.py app/content/service.py tests/test_content_service.py
git commit -m "feat: 接入内容生成器并支持失败重试"
```

### Task 4: 配置装配、API 路由和文档

**Files:**
- Test: `tests/test_persistence_contract.py`
- Test: `tests/test_content_api.py`
- Modify: `app/bootstrap.py`
- Modify: `app/main.py`
- Modify: `docs/api-contract.md`

- [ ] **Step 1: 写装配和重新生成 API 的失败测试**

```python
def test_build_content_generator_selects_mock_or_openai():
    from app.bootstrap import build_content_generator
    from app.content.generator import MockContentGenerator
    from app.content.openai_compatible import OpenAICompatibleContentGenerator
    from app.settings import Settings

    assert isinstance(build_content_generator(Settings()), MockContentGenerator)
    settings = Settings(
        content_generation_backend="openai_compatible", content_model_base_url="http://localhost:9999/v1",
        content_model_name="local", content_model_api_key="test-key",
    )
    assert isinstance(build_content_generator(settings), OpenAICompatibleContentGenerator)
```

API test：创建任务后调用 `POST /api/v1/content-tasks/{task_id}/regenerations`，携带新的 `idempotency_key`，断言返回相同 `task_id`、新 `run_id` 和 `reviewing` 状态；失败生成返回 `failed` 且导出返回 `409`。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_persistence_contract.py tests/test_content_api.py -k "content_generator or regeneration" -q`

Expected: FAIL，提示装配函数和路由不存在。

- [ ] **Step 3: 实现装配、API 错误映射和文档**

在 `app/bootstrap.py` 新增 `build_content_generator(settings)`：

- `mock` 返回 `MockContentGenerator()`。
- `openai_compatible` 校验 base URL、model、API key 非空后构造 `OpenAICompatibleContentGenerator`。
- 未知后端或缺失配置抛出明确中文 `ValueError`；不打印密钥。

在 `app/main.py`：

- `content_service` 注入 `build_content_generator(settings)`。
- 新增 `POST /api/v1/content-tasks/{task_id}/regenerations`，请求体只含 `idempotency_key`。
- 将 `ContentGenerationError` 映射为返回任务视图而不是伪造 500；任务状态由服务写为 `failed`。
- 重复重新生成幂等键返回原任务/原 run，输入不一致返回 `409`。

在 `docs/api-contract.md` 说明生成后端环境变量、失败状态、无静默 Mock 降级和重新生成路径。

- [ ] **Step 4: 运行后端回归并提交**

Run: `python -m pytest -q`

Expected: 全部后端测试 PASS。

```bash
git add app/bootstrap.py app/main.py tests/test_persistence_contract.py tests/test_content_api.py docs/api-contract.md
git commit -m "feat: 装配可切换内容模型并开放重新生成"
```

### Task 5: 本地假服务、构建和端到端验收

**Files:**
- Create: `tmp/openai_compatible_fake_server.py`（只用于本地验收，不提交）
- Modify: `tmp/content_alpha_browser_test.py` only if needed; do not commit `tmp/`.

- [ ] **Step 1: 增加本地假服务和适配器闭环测试**

假服务只返回固定合法 JSON，不记录或输出 Authorization；支持通过环境变量返回 500/无效 JSON，验证失败路径。

Run: `python -m pytest tests/test_content_openai_compatible.py tests/test_content_service.py tests/test_content_api.py -q`

Expected: PASS。

- [ ] **Step 2: 执行静态、前端和构建回归**

Run:

```powershell
python -m compileall -q app tests extract_pdf.py
git diff --check
Push-Location admin-web
npm test -- --run
npm run build
Pop-Location
```

Expected: 全部命令退出码 `0`。

- [ ] **Step 3: 使用 Mock 默认配置执行浏览器闭环**

启动后端和前端，运行 `python -u tmp/content_alpha_browser_test.py`，确认现有 Alpha 仍生成、编辑、确认、下载成功。

- [ ] **Step 4: 使用本地 OpenAI-compatible 假服务执行浏览器闭环**

以 `CONTENT_GENERATION_BACKEND=openai_compatible`、本地假服务地址、测试模型名和临时密钥启动后端，执行同一浏览器脚本，确认页面能看到模型生成标题，且服务日志、审计接口和导出文件不包含密钥或 Authorization。

- [ ] **Step 5: 完成收尾检查**

Run:

```powershell
git status --short --branch
git log -6 --oneline
```

Expected：只有预期提交和已有未跟踪 `.superpowers/`，不包含临时服务、数据库、模型密钥或 `node_modules/`。
