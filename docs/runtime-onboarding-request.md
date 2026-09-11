# 项 8 外部运行时（RAGFlow / AgentScope）接入资料与索取表（草案）

> **本文件性质**：接入资料汇编 + 索取表，**不是已确认的外部契约**，也**不得据以编写实现代码**。
> **编制日期**：2026-09-11
> **对应门禁**：`docs/delivery-gates.md` 项「RAGFlow/AgentScope 密钥注入、跨租户实测、并发压测、沙箱验证和真实外部服务验收」（项 8）；验收判据见 `docs/external-dependency-acceptance-plan.md` 项 8；执行卡见 `docs/external-dependency-execution-plan.md` 项 8。
> **来源标注**：来自本仓库代码/文档的结论标注文件路径；未能核实的标注**待核实**。凡本仓库代码里不存在的接口、字段名、请求头或配置名，一律不写入本文件；代码里没有对应实现的，明确写成「缺口」。

---

## 0. 前提更正与结论

### 更正：项 8 的外部依赖是「外部运行时 / 外部知识服务」，不是第三方发布平台

门禁项 8 的原文是「**RAGFlow/AgentScope** 密钥注入、跨租户实测、并发压测、沙箱验证和真实外部服务验收」（`docs/delivery-gates.md`；`docs/external-dependency-acceptance-plan.md` §输入清单）。它讲的是**外部运行时与外部知识服务（RAGFlow、AgentScope）**；第三方发布平台（微信公众号）属**项 7 / 项 9**，见 `docs/platform-account-onboarding.md`。

### 与项 6 / 项 7 的关键差异

项 6（GEO）与项 7（公众号）需要**先拿到外部契约**才能动手（见 `docs/geo-contract-request.md` §0、`docs/platform-account-onboarding.md` §4）。**项 8 不同**：其对接契约的**很大一部分由本仓库自己定义**——`app/runtime/` 下已有契约层（`contracts.py`）、注册表（`registry.py`）与适配器（`adapters/`）。

### 结论

工作台侧已经用代码定义好「对方需要满足什么」（详见 §1）。**真正缺的是外部输入**，而不是契约文本：

1. 真实外部服务实例的 **HTTPS 地址**（RAGFlow / AgentScope 各一）；
2. **凭据及其注入途径**（注入能力**已实现**：`<KEY>_AUTH_TOKEN` + 可选 `<KEY>_AUTH_HEADER`/`<KEY>_AUTH_SCHEME`；仍**需外部方提供真实凭据与其注入方式**，见 §1.8）；
3. **契约固定版本号**（拒绝 `latest`/`main`/`head` 一类浮动值）；
4. **网络白名单**（工作台出口可达范围 / 域名）；
5. **两个分属不同租户的隔离测试账号**，以及**外部侧由谁创建隔离知识库 / 命名空间**。

> 满足以上输入后，方可按 §3 用本仓库已有探针做跨租户实测与并发压测，并按现有预检脚本核验元数据（`scripts/runtime_staging_preflight.py`）。

---

## 1. 工作台侧已有的对接契约（读代码得出，精确）

### 1.1 适配器协议（`app/runtime/contracts.py`）

`AgentRuntimeAdapter`（`contracts.py` L119-129）要求外部运行时实现以下方法：

| 方法 | 签名 |
|---|---|
| `start_run` | `(context: RuntimeContext, plan: AgentPlan) -> str` |
| `stream_events` | `(run_id: str, cursor: str \| None = None) -> list[RuntimeEvent]` |
| `pause_run` / `resume_run` | `(run_id, ...)` |
| `cancel_run` | `(run_id: str, reason: str) -> None` |
| `request_approval` | `(run_id: str, action: dict) -> str` |
| `get_checkpoint` | `(run_id: str) -> dict \| None` |
| `replay_run` | `(run_id: str, from_step: str \| None = None) -> str` |
| `get_usage` | `(run_id: str) -> dict` |
| `health` | `() -> dict` |

`RuntimeContext`（`contracts.py` L35-54）字段：`tenant_id`、`user_id`、`role_key`、`mode`、`project_id`、`task_id`、`device_id`、`knowledge_scope`、`file_scope`、`budget_cents`、`risk_level`、`policy_version`、`expires_at`；`is_valid_at(now)` 要求带时区且 `now < expires_at`。

`AgentPlan` / `PlanStep`（`contracts.py` L57-76）字段：`step_id`、`kind`、`tool`、`requires_approval`；`kind` 取值白名单 `ALLOWED_PLAN_KINDS = {read, write, external_send, publish, delete, permission}`（L9-11）。

### 1.2 HTTP 端点路径构造（`app/runtime/adapters/common.py` 的 `HttpRuntimeTransport`，L59-101）

| 用途 | 方法与路径 |
|---|---|
| 创建运行 | `POST {endpoint}/runs` |
| 读取事件 | `GET {endpoint}/runs/{remote_run_id}/events` |
| 知识检索 | `POST {endpoint}/knowledge-search` |
| 生命周期/审批/重放/用量 | `POST {endpoint}/runs/{remote_run_id}/{action}`，`action ∈ {pause, resume, cancel, approvals, replay, usage}` |
| 健康检查 | `GET {endpoint}/health` |

- 基址处理：`endpoint.rstrip("/")`（L65-67）。
- 失败即失败：非 2xx、响应非 JSON、响应非 object → 抛 `TransportError`，**禁止把失败伪装成成功**（L69-78）。

### 1.3 请求载荷

- **创建运行**（`common.py` L116-117）：`{"context": {…13 个 RuntimeContext 字段…}, "plan": [{"step_id","kind","tool","requires_approval"}]}`。
- **AgentScope 额外字段**：`payload["runtime_key"] = "agentscope"`（`adapters/agentscope.py` L13-16）。
- **RAGFlow 知识检索**（`adapters/ragflow.py` L68-73）：`{"tenant_id", "knowledge_base_ids", "query", "limit"}`；`query` 长度须 1–2000，`limit` 须 1–50（L61-64）。

### 1.4 响应字段要求

| 调用 | 必需字段 | 来源 |
|---|---|---|
| 创建运行 | `run_id` 或 `id`（非空字符串），否则抛「Runtime 返回中缺少运行号」 | `common.py` L82-85 |
| 读取事件 | `{"events": [...]}` 或 `{"items": [...]}`，每项为 object | `common.py` L87-92 |
| 知识检索 | `{"items": [...]}`，每项须含非空字符串 `document_id`、`knowledge_base_id`、`title`、`snippet`；`score` 可空，否则须为有限数值 | `ragflow.py` L74-115 |
| 审批 | `approval_id`（可缺，缺则本地生成） | `common.py` L152-155 |
| 健康检查 | 可选 `version` / `capabilities` / `sandbox` / `reason` / `status` | `common.py` L169-186；`registry.py` L53-74 |

### 1.5 事件类型映射与未知事件处理

- 映射表（`common.py` L130）：`plan.created`、`step.started`、`tool.call`、`tool.result`、`approval.requested`、`checkpoint.saved`、`run.paused`、`run.completed`、`run.failed`。
- **未知事件**：不猜测类型，统一映射为 `run.failed`，并把载荷替换为 `{"reason": "外部运行时返回未知事件", "remote_type": <安全类型>}`（`common.py` L131-136）；`_safe_remote_type` 正则 `^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$`，不匹配即记为 `"unknown"`（L12-19）。

### 1.6 版本校验规则（含拒绝哪些浮动值）

`app/runtime/registry.py` 的 `_validate_version`（L95-103）：值经 `strip` 后，若**非字符串、为空、或（大小写不敏感）等于 `latest`/`main`/`head`** → 抛 `RuntimeConfigError("{key} Runtime 需要固定版本")`。同一规则在预检脚本中独立复刻：

- `scripts/runtime_staging_preflight.py` `_fixed_version`（L44-45）；
- `scripts/commercial_g0_preflight.py`（L116-127，对 `WORKBENCH_RUNTIME_VERSIONS` 逐项判固定）。

### 1.7 注册表构造与「未配置时 fail-closed」

`build_runtime_registry`（`registry.py` L106-149）：

- **默认只注册 `mock`**（L113-115）；未知 key → `RuntimeConfigError("未知 Runtime: {key}")`（L128-129）。
- 配置项 `enabled` 非 `true` → **跳过、不注册**（L125）。
- `endpoint` 必须非空且以 `http://` 或 `https://` 开头（L77-82）。
- `capabilities` 必须是**非空字符串列表**（L131-137）。
- `timeout_seconds` 必须有限且 > 0（L85-92）。
- 已注册项：`mock`、`deerflow`、`codex_worker`、`hermes`、`ragflow`、`agentscope`（L117-123）。

**应用装配层面的现状（已于 2026-09-11 修复）**：`app/main.py` 曾以 `RuntimeService(store)` 构造，默认 `RuntimeRegistry()`（**只注册 mock**），`build_runtime_registry(...)` 仅被测试调用。现已由 `app/bootstrap.py` 的 `build_runtime_service(...)` 接入：从 Settings 读取**裸名**配置（`<KEY>_ENDPOINT` / `<KEY>_VERSION` / `<KEY>_CAPABILITIES` / `<KEY>_TIMEOUT_SECONDS` / `<KEY>_AUTH_*`）组装注册表并注入 `RuntimeService`。**未配置任何 `<KEY>_ENDPOINT` 时仍只注册 mock**（开发默认不回归）。
>
> 接线时另发现并修复一处潜在缺陷：注册表与 `RuntimeService` 曾各自持有 `RuntimeStateStore`，导致 mock 记录的运行在服务层查不到；现改为共享同一实例。
>
> 注意：`WORKBENCH_RUNTIME_VERSIONS` 是 staging 模板里的**元数据登记**键，注册表配置**不由它驱动**，而是由上述 `<KEY>_*` 裸名驱动。

**RAGFlow 只读语义**（`adapters/ragflow.py` L10-52）：所有执行类方法（`start_run`/`stream_events`/`pause_run`/`resume_run`/`cancel_run`/`request_approval`/`replay_run`/`get_usage`）一律抛 `RuntimeUnavailable("RAGFlow Runtime 不可用：仅支持知识检索")`；`health()` 固定返回 `status="unavailable"`。

**空范围 fail-closed**（`ragflow.py` L65-66）：`context.knowledge_scope` 为空时直接返回 `[]`，**不发起任何外部请求**。

**未配置不外呼**：未配置或未启用的外部 Runtime 不会被自动调用（`docs/api-contract.md` L399、L403）。

### 1.8 认证与令牌传递

- **认证头注入（已于 2026-09-11 实现）**：`HttpRuntimeTransport` 支持注入认证头，默认形如 `Authorization: Bearer <token>`，头名与前缀可配置（`<KEY>_AUTH_HEADER` / `<KEY>_AUTH_SCHEME`，后者允许显式置空以发送裸令牌）。凭据来自 `<KEY>_AUTH_TOKEN`（**由部署密钥系统注入**）。
- **fail-closed**：声明 `<KEY>_AUTH_INJECTED=true` 却未提供 `<KEY>_AUTH_TOKEN` 时，**应用启动期直接报 `RuntimeConfigError`**，不会静默降级为匿名调用。
- **密钥不外泄**：令牌字段以 `dataclasses.field(repr=False)` 处理，**不进 `repr`、不进异常消息、不进健康摘要**（有专门测试守护）；注入的头不得进入任务载荷、事件或审计。
- **短时授权令牌**：`app/runtime/tokens.py` 的 `ShortLivedGrant`（HMAC-SHA256 签名，绑定 `run_id`/`task_id`/`device_id`/`actions`/`expires_at`，`issue`/`verify`）是**契约与策略辅助件**，目前仍**仅被测试使用**（`tests/test_runtime_policy.py`），**尚未接入传输层**——这一条仍属缺口。
- **事件脱敏**：`RuntimeEvent.to_public_dict`（`contracts.py` L86-116）把键 `password`/`cookie`/`api_key`/`secret`/`token`/`authorization`/`access_token`/`refresh_token`/`session`/`验证码` 的值替换为 `[已隐藏]`。

---

## 2. 需要外部方提供或确认的事项（索取表）

| # | 事项 | 为什么必需（判据） | 依据 | 填写 |
|---|---|---|---|---|
| E1 | **RAGFlow HTTPS 地址** | 预检要求 `https://` 且非空；注册表要求 `http(s)://` | `scripts/runtime_staging_preflight.py` L48-49、L64；`registry.py` L77-82 | |
| E2 | **RAGFlow 契约固定版本号** | 拒绝 `latest`/`main`/`head` 浮动值 | `registry.py` L95-103；`runtime_staging_preflight.py` L44-45 | |
| E3 | **AgentScope HTTPS 地址** | 同 E1 | 同 E1 | |
| E4 | **AgentScope 契约固定版本号** | 同 E2 | 同 E2 | |
| E5 | **认证方式与凭据注入途径** | 工作台要求凭据**仅经部署密钥系统注入传输层**，不入载荷/事件/日志；代码层尚无注入实现（§1.8） | `docs/api-contract.md` L411；`README.md` L55 | |
| E6 | **两个隔离测试账号（须分属两个不同租户）** | 跨租户实测需两套令牌做双向交叉访问 | `scripts/cross_tenant_probe.py` 前置条件 L29-33；`.env.staging.example` L41-43（就绪标记键） | |
| E7 | **网络白名单**（工作台出口 IP / 可达域名） | 预检要求 `WORKBENCH_RUNTIME_NETWORK` 非空 | `runtime_staging_preflight.py` L70-71；`.env.staging.example` L39 | |
| E8 | **平台侧限流 / 额度** | 并发压测与长跑不得触限 | `scripts/staging_concurrency_probe.py` 前置条件 | |
| E9 | **由谁在外部侧创建隔离知识库 / 命名空间** | `knowledge_scope` 由工作台从 `RuntimeContext` 解析传入，外部侧须存在对应知识库；RAGFlow 只读、不提供写入/删除/索引 | `adapters/ragflow.py` L68-99；`docs/api-contract.md` L407 | |
| E10 | **沙箱能力声明**（`health.sandbox` 取值语义） | 健康摘要会透传 `sandbox` 字符串；沙箱验证需要外部侧可声明其隔离语义 | `registry.py` L61；`common.py` L182-183 | |

**交接方式**：地址/版本/网络白名单等**元数据**登记在 `.env.staging`（模板见 `.env.staging.example` L29-43）；**凭据值只经部署密钥系统注入，不写入任何环境文件**（`.env.staging.example` L2-3、L22-24）。

---

## 3. 跨租户实测与并发压测要求

### 3.1 必须用两个租户交叉验证，不得只测单租户

跨租户隔离是水平越权防线（门禁项 8 判据「跨租户结果**整批拒绝**」）。**单租户自测无法证明隔离**，必须用两个分属不同租户的令牌做**双向交叉访问**。

### 3.2 `scripts/cross_tenant_probe.py`（跨租户隔离实测）

- 资源类型与路径（脚本 `RESOURCE_PATHS` L63-70）：`task`→`GET /api/v1/tasks/{id}`、`plan_proposal`→`/api/v1/plan-proposals/{id}`、`content_task`→`/api/v1/content-tasks/{id}`、`run_metrics`→`/api/v1/runs/{id}/metrics`、`orchestration_proposal`→`/api/v1/orchestration-proposals/{id}`、`commercial_lifecycle`→`/api/v1/commercial/lifecycle/{id}`。
- **双向判定**：`A→B` 与 `B→A` 必须返回 `403` 或 `404`，其余（含 `200`、`5xx`、传输异常）判 `fail`（`evaluate_isolation` L196-209）。
- **正向对照（关键）**：必须先**用所有者自己的令牌读到自己的资源**——`A→A` 与 `B→B` 都必须 `200`；任一不为 `200`，则该用例判 `fail（用例无效）`，因为「两端都 404」既可能是隔离成立，也可能是资源根本不存在（`evaluate_isolation_with_controls` L221-239，脚本 docstring L13-18）。
- 参数：`--base-url <staging> --token-a <A> --token-b <B> --resource KIND:A_ID:B_ID`（可重复）；退出码 `2` 参数错误 / `0` 全 pass / `1` 任一 fail（L49-50）。
- 护栏：非 HTTPS（未加 `--allow-insecure`）拒绝、指向 localhost/127.0.0.1/::1/0.0.0.0（未加 `--allow-local`）拒绝（`resolve_base_url` L121-134）；**报告只输出资源类型与响应码，绝不打印令牌或响应正文业务数据**（docstring L40-41）。
- **已知缺口（脚本 docstring L43-47 已登记）**：`knowledge-access` 的角色/数字员工绑定与审计接口按调用方 `tenant_id` 直接返回本租户数据，没有可指向他租户的资源标识，**无法构造跨租户对照，故未纳入探测**；无法提供他租户标识的资源应如实跳过，不得伪造 id。

### 3.3 `scripts/staging_concurrency_probe.py`（并发压测）

- 三场景（`SCENES` L49）：① `login_throttle`——同一探针手机号并发错误口令登录，期望出现 `429`；② `task_idempotency`——同一幂等键并发创建任务，期望只产生 1 条记录；③ `plan_approval`——同一计划提案并发审批，期望恰好 1 个 `200`、其余 `409`。
- 护栏：默认强制 HTTPS 与独立主机，`--concurrency` 限 1–64（L63-74、L447-449）；报告只输出主机、响应码分布与 P95，**绝不写入口令明文、令牌或完整 URL 查询串**（docstring L18-22）。
- **定位**：本脚本只产出**并发行为统计**，**不构成验收证据**，是否通过须人工按判据判定（docstring L21-22）。
- 前置：专用探针账号（会被锁定，勿用真实人员账号）；`plan_approval` 还需一个处于 `pending_review` 且**发起人 ≠ 令牌用户**的提案 id（docstring L11-17）。

---

## 4. 安全红线

1. **凭据仅经部署密钥系统注入**：`.env.staging.example` 明示「部署注入的密钥……由部署密钥系统注入」「本文件只登记部署元数据，脚本不会读取或打印密钥值」（L2-3、L22-24、L32-43）；`README.md`「所有密钥只从环境注入」并要求缺失即启动失败（L55）。
2. **证据不得含 `Authorization` / API Key / Cookie / 客户原文**：门禁项 8 通过判据原文如此（`docs/external-dependency-acceptance-plan.md` L233）；`cross_tenant_probe.py` 报告只含状态码（docstring L41）。
3. **外部运行时不得直连工作台数据库、Redis、GEO 或生产账号**：原文见 `docs/api-contract.md` L399（「DeerFlow、Codex Worker、Hermes 只能作为独立外部适配器接入，不能直连工作台数据库、Redis、GEO 或生产账号」）与 `README.md`「与 GEO 的边界」（L92-94：禁止跨库写入、复制 GEO 内部表）。
4. **认证头 / API Key / Cookie 不得进入任务载荷、事件或日志**：`docs/api-contract.md` L411；事件层已按 §1.8 的敏感键列表脱敏（`contracts.py` L86-116）。
5. **绝不自动重放外部副作用**：外部服务失败时应保留事件摘要、回退 Mock，重放由人工决定（`docs/external-dependency-execution-plan.md` 项 8 风险条）。

---

## 5. 沙箱验证要求

代码里与「沙箱」相关的真实能力，**只有以下两处**，其余为缺口：

1. **健康摘要透传 `sandbox` 字段**：注册表允许 `sandbox` 为字符串进入健康摘要（`registry.py` L61），`ExternalAdapter.health` 透传外部返回的 `sandbox`（`common.py` L182-183）；Mock 运行时报告 `sandbox="deterministic"`（`mock.py` L85）。
2. **特权沙箱属高风险能力**：`privileged_sandbox` 被列入 `HIGH_RISK_CAPABILITIES`，须 `ceo`/`super_admin` 且经管理员审核，并走专用灰度流程，**不能直接启用**（`app/capabilities.py` L22-31、L46-56）。

**缺口（如实登记）**：除上述健康摘要透传与能力治理外，本仓库**没有**外部运行时沙箱的创建、隔离执行或验证实现；本地冒烟 `app/runtime/staging.py` 覆盖 Mock 与适配器边界（上下文范围、凭据脱敏、Hermes 复核闸门），**不校验任何沙箱隔离语义**（`staging.py` `run_smoke_check` L87-106）。因此「沙箱验证」的具体判据需与外部侧按此处仅有的字段语义另行确认（见 §6 U4）。

---

## 6. 待确认与不可判定事项（本文件不猜测）

| # | 事项 | 状态 |
|---|---|---|
| U1 | RAGFlow / AgentScope 真实实例与 HTTPS 地址（E1/E3） | **待外部提供** |
| U2 | 固定版本号（E2/E4）、认证方式与凭据注入途径（E5） | **待外部确认**；注入机制**已实现**（`<KEY>_AUTH_TOKEN`，见 §1.8），缺的是外部凭据本身 |
| U3 | 两个分属不同租户的隔离测试账号（E6）、隔离知识库/命名空间归属（E9） | **待外部提供** |
| U4 | 沙箱能力的具体语义与验证判据（E10） | **待外部确认**；本仓库除健康摘要有 `sandbox` 字段外无沙箱验证实现（§5） |
| U5 | 网络白名单具体条目（E7）、限流/额度（E8） | **待外部确认** |
| U6 | ~~配置驱动注册表接入应用装配的时机~~ | **已完成**（2026-09-11，见 §1.7） |

---

## 7. 声明

1. 本文件是**接入资料汇编与索取表**，来源均已标注；未核实处一律标注**待核实**或**待外部提供/确认**，不做推测填充。
2. **不得**据本文件编写实现代码或契约测试；接入应以**真实代码为准**（§1），并在拿到 §2 外部输入后另行评审。
3. 本文件**不改变任何门禁状态**：项 8 仍为**未实现 / 未验收**（`docs/delivery-readiness-checklist.md` E 节仍标 `❌/❌/⬜`）。
