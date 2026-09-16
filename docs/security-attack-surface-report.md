# 攻击面八类检查报告（本机实测）

> 本报告依据「安全工程师/攻击者」视角，对本仓库既有 FastAPI 服务执行八类攻击面实测。每一条结论都来自本机实际执行的脚本与真实输出，未验证项已明确标注。

## 1. 范围与方法

- **被测对象**：`app/main.py` 暴露的 `/api/v1` HTTP 接口、账号注册/登录/审批/改密/TOTP、登录限流、计划生成与审批、任务跨租户隔离、审计写入。
- **方法**：静态代码审查（对照 `docs/api-contract.md` 与实现）+ 真实请求测试（`fastapi.testclient.TestClient` 直接向 `app.main.app` 发起 HTTP 调用，必要时注入构造好的 `AccountService`/`PlannerService`）。
- **执行环境**：本机（Windows，Python 3.14.5，`py` 启动器）；进程内 `TestClient`；存储为内存仓储（`WORKBENCH_STORAGE_BACKEND=memory`、`WORKBENCH_CONTENT_STORE_BACKEND=memory`）；`WORKBENCH_ENV=development`；`WORKBENCH_AUTH_SECRET`、`WORKBENCH_BOOTSTRAP_TOKEN` 为测试值；`WORKBENCH_PLANNER_TOOLS` 配置 `content.publish(kind=publish)` 与 `knowledge.search(kind=read)`。
- **基线**：实测前 `py -m pytest -o addopts=""` 全量 **516 passed**。

> **明确声明：本报告未在真实 staging、真实 PostgreSQL、真实 Redis/Celery、真实外部 Runtime（RAGFlow/AgentScope）或真实外部平台上执行。** 所有结论仅代表本机内存仓储 + 进程内 TestClient 的行为。

---

## 2. 八类攻击面逐条

### 第 1 类 水平越权（跨租户）

| 攻击方法 | 实际执行方式 | 真实结果 | 结论 | 已修复 |
|---|---|---|---|---|
| 租户 A 读取租户 B 的任务 | 租户 B 建任务后，以 `X-Tenant-Id: t-a` 身份 `GET /api/v1/tasks/{id}` | `404` | 数据归属校验生效，不泄露存在性 | 是（既有实现） |
| 租户 A 审批租户 B 的任务 | 租户 B 建高风险任务（`pending_approval`），以租户 A 的 `ceo` 身份 `POST .../approve` | `404` | 审批同样按租户隔离 | 是（既有实现） |
| 同租户非发起人读取 | 同租户普通 `employee` 读他人任务 | `404` | 归属过滤覆盖同租户非发起人 | 是（既有实现） |
| 对照：租户 B 发起人本人读取 | `GET /api/v1/tasks/{id}` | `200` | 合法访问正常 | — |

真实输出摘要：
```
create_task_in_tenant_B_status => 201
tenantA_read_tenantB_task_status(期望404) => 404
tenantA_ceo_approve_tenantB_task_status(期望404) => 404
same_tenant_non_owner_read_status(期望404) => 404
tenantB_owner_read_own_task_status => 200
```

### 第 2 类 垂直越权（普通用户调管理员接口）

以 `employee` 身份逐个调用管理员/特权接口：

| 接口 | 真实状态码 | 期望 |
|---|---|---|
| `POST /api/v1/tasks/{id}/approve` | `403` | 403 |
| `GET /api/v1/auth/registrations` | `403` | 403 |
| `POST /api/v1/auth/accounts/{id}/password` | `403` | 403 |
| `POST /api/v1/auth/accounts/{id}/totp-reset` | `403` | 403 |
| `GET /api/v1/dead-letters` | `403` | 403 |
| `POST /api/v1/dead-letters/{id}/replay` | `403` | 403 |
| `GET /api/v1/runtimes/health` | `403` | 403 |
| `GET /api/v1/knowledge-access/roles/{role_key}` | `403` | 403 |

结论：全部返回 `403`，权限中间件在业务处理前拦截。已修复：是（既有实现）。

### 第 3 类 身份伪造

| 攻击方法 | 真实结果 | 结论 |
|---|---|---|
| 不带任何凭证访问受保护接口 | `401` | 认证强制 |
| 伪造签名的 Bearer 令牌（`Bearer aGVsbG8.forgedsignature`） | `401` | HMAC 验签拒绝 |
| 已过期令牌（`ttl_seconds=-10`） | `401` | 过期校验生效 |
| 生产模式下有效令牌（对照） | `200` | 证明令牌被正常接受，非全盘拒绝 |
| 生产模式篡改 payload（`role=employee`→`super_admin`）但保留原签名 | `401` | 篡改后签名不匹配，被拒绝 |

真实输出摘要：
```
no_credentials_status(期望401) => 401
forged_signature_status(期望401) => 401
expired_token_status(期望401) => 401
production_valid_token_status(应为404，证明令牌被接受) => 200
production_tampered_role_keep_signature_status(期望401) => 401
```

结论：`current_user` 在生产模式只信任 Bearer 令牌，篡改角色字段无法提权。已修复：是（既有实现）。

### 第 4 类 字段提权

| 攻击方法 | 真实结果 | 结论 |
|---|---|---|
| 注册请求体塞入 `"role":"super_admin"`、`"status":"approved"` | `422` | 模型 `extra="forbid"` 拒绝多余字段 |
| 审批请求体塞入额外字段 `"is_admin":true` | `422` | 同上 |
| 非首管理员注册传 `tenant_id:"t-hacker"` | 响应 `tenant_id=None`、`status=pending` | 客户端传的租户被忽略，审批前不带租户 |
| 计划生成：模型输出对发布类工具 `content.publish` 自报 `kind="read"` | 响应步骤 `kind=publish`、`requires_approval=True` | 服务端按白名单推导，模型自报 `kind` 无效 |
| 直接调用 `normalize_steps`（同一伪造输入） | 返回 `kind=publish` | 归一化层忽略生成器 kind |
| `WORKBENCH_PLANNER_TOOLS` 为空时生成计划 | `422`，detail「未配置任何可用工具」 | 空白名单不产出计划 |
| 弱口令：`1234567890` / `aaaaaaaaaa` / `password123` | 均 `422`（纯数字 / 重复单一字符 / 常见弱口令） | 口令策略生效 |

真实输出摘要：
```
registration_extra_role_status(期望422) => 422
approval_extra_field_status(期望422) => 422
employee_response_tenant_id(应被忽略=None) => None
planner_server_derived_kind(期望publish，模型自报read) => publish
planner_server_derived_requires_approval(期望True) => True
normalize_steps_direct_kind => publish
planner_empty_tools_status(期望422) => 422  detail=未配置任何可用工具
weak_password_1234567890_status => 422  detail=口令不能是纯数字
weak_password_aaaaaaaaaa_status => 422  detail=口令不能是重复的单一字符
weak_password_password123_status => 422  detail=口令过于常见，请更换
```

结论：核心安全性质「计划步骤的 `kind`/审批要求由服务端白名单推导、生成器同类字段被忽略」经 API 与归一化层双重实测成立。已修复：是（既有实现）。

### 第 5 类 注入

| 注入点 | 载荷 | 真实结果 |
|---|---|---|
| 手机号 | `' OR 1=1 --`（SQLi） | `422`（格式校验拒绝） |
| 手机号 | `1<script>alert1`（XSS） | `422` |
| 任务标题 | `'; DROP TABLE users;--` | `201`，响应原样回显 `"'; DROP TABLE users;--"` |
| 任务标题 | `<script>alert(1)</script>` | `201`，原样回显 |
| 任务标题 | `; rm -rf / \| cat /etc/passwd` | `201`，原样回显，无命令执行 |
| 计划目标 | `'; DROP TABLE users;-- <script>alert(1)</script>` | `201`，`goal` 与输入逐字相等 |
| 计划驳回原因 | `'; DROP TABLE users;--` | `200`，`rejection_reason` 与输入逐字相等 |
| 账号驳回原因 | `<script>alert(1)</script>` | `200` |

真实输出摘要：
```
task_title_sql_stored_equal => True      task_title_sql_echoed_literal => "'; DROP TABLE users;--"
task_title_xss_stored_equal => True      task_title_xss_echoed_literal => '<script>alert(1)</script>'
task_title_cmd_stored_equal => True      task_title_cmd_echoed_literal => '; rm -rf / | cat /etc/passwd'
plan_goal_stored_equal => True
plan_rejection_reason_stored_equal => True
phone_sqli_status(期望422) => 422
phone_xss_status(期望422) => 422
```

结论：实测**无任何 500**；文本字段按字面存储并由 JSON 响应返回（本项目响应为 `application/json`，不渲染 HTML，故不存在服务端 HTML 执行）；手机号等强格式字段直接 `422` 拒绝；本项目不在请求路径上执行 shell，命令注入字符不改变语义、不触发执行。已修复：是（既有实现，无参数拼接式查询）。

### 第 6 类 绕过前端

| 场景 | 真实结果 | 结论 |
|---|---|---|
| 生产模式（`env=production`）：仅带 `X-User-Role: super_admin`、无 Bearer 令牌 | `401` | 服务端不信任客户端自填角色 |
| 开发模式：同样三个身份请求头、无 Bearer 令牌 | `200` | **开发态设计约定**：`docs/api-contract.md` 明确开发环境用 `X-Tenant-Id/X-User-Id/X-User-Role` 验流程，正式环境必须替换 |

真实输出摘要：
```
production_header_only_super_admin_status(期望401) => 401
development_header_only_super_admin_status(开发态设计约定) => 200
```

结论：生产模式不再接受请求头身份（`401`）；开发模式的请求头身份是**显式设计内的开发态约定**，不是绕过漏洞，但必须在生产环境彻底关闭（当前配置门禁已要求 `WORKBENCH_ENV≠development` 时强制 PostgreSQL + ≥32 位密钥）。已修复：是（既有实现 + 文档标注）。

### 第 7 类 信息泄露

穷举检查字符串：明文手机号、`password`、`password_hash`、`scrypt$`、`access_token`、`totp_secret`、bootstrap 令牌、`WORKBENCH_AUTH_SECRET` 的值。

| 采集对象 | 明文手机号 | 口令/哈希/密钥/种子/bootstrap | `access_token` |
|---|---|---|---|
| 注册响应 | 无（`phone=138****0001` 已脱敏） | 无 | 无 |
| 账号视图（申请列表） | 无 | 无 | 无 |
| 计划提案视图 | 无 | 无 | 无 |
| 登录响应 | 无 | 无 | 有（`access_token`，设计内，是登录接口的正常返回体） |
| 审计记录明细 | 无（仅 `phone_masked`） | 无 | — |

- 审计明细白名单：本次共写入 10 条审计记录，顶层明细键全部落在 `ALLOWED_DETAIL_KEYS` 内，越界键集合为空。
- 错误响应：`404` 返回 `{"detail":"任务不存在"}`；`422` 为 Pydantic 校验结构（`type/loc/msg/input`）；两者均不含 `Traceback`、`site-packages`、`C:\`、`SELECT ` 等内部信息。

真实输出摘要：
```
registration_view_plaintext_phone_present => False
account_view_plaintext_phone_present => False
plan_proposal_view_plaintext_phone_present => False
login_view_plaintext_phone_present => False
login_view_contains_access_token(设计内) => True
registration_phone_masked => 138****0001
audit_record_count => 10
audit_detail_keys_outside_whitelist(期望空) => []
audit_contains_plaintext_phone => False
audit_contains_password_hash => False
error_404_body => {"detail":"任务不存在"}
error_body_leaks_internal => False
error_422_leaks_internal => False
```

结论：除登录接口按设计返回会话令牌外，未发现敏感信息泄露；审计只写脱敏手机号与白名单明细；错误响应不泄露堆栈/路径/SQL。已修复：是（既有实现）。

### 第 8 类 资源滥用

| 场景 | 真实结果 |
|---|---|
| 不存在手机号连续 5 次错误口令 | `[401, 401, 401, 401, 401]`，第 6 次 `429` |
| 存在手机号连续 5 次错误口令 | `[401, 401, 401, 401, 401]`，第 6 次 `429` |
| 存在 vs 不存在的失败文案 | 完全一致：`手机号或密码不正确` |
| 已绑定 TOTP 账号连续 5 次错误动态码 | 失败计数推进 `1→2→3→4→5`，第 6 次 `429` |
| 单次 scrypt 计算耗时（本机） | 约 `53.3 ms` |

真实输出摘要：
```
nonexistent_wrong_password_5x_statuses => [401, 401, 401, 401, 401]
nonexistent_6th_status(期望429) => 429
nonexistent_429_detail => 登录尝试过于频繁，请稍后再试
existing_wrong_password_5x_statuses => [401, 401, 401, 401, 401]
existing_6th_status(期望429) => 429
existing_and_nonexistent_1st_detail_equal => True
totp_wrong_code_5x_(status,count) => [(401, 1), (401, 2), (401, 3), (401, 4), (401, 5)]
totp_6th_status(期望429) => 429
single_scrypt_ms => 53.3
```

结论：登录失败按手机号计数，达到阈值（默认 5）后锁定并返回 `429`；错误动态口令计入同一限流计数；存在与不存在的手机号在文案与锁定行为上一致，不泄露账号是否存在。

**残留风险（如实记录）**：注册与登录均为匿名入口，每次调用执行一次 scrypt（本机约 53 ms）。攻击者可轮换手机号，每个号仍可消耗 5 次 scrypt。生产环境必须在网关层补充限流/防刷。

---

## 3. 发现的问题清单

**未发现新的可利用问题。** 本轮八类攻击面实测未发现可被利用的新漏洞；上述八类的期望防御（`404`/`403`/`401`/`422`/`429`）均按设计生效，注入载荷未产生 `500` 或语义改变，信息泄露检查未命中敏感串。

以下为**已知限制**（非本轮新引入的缺陷，如实列出）。

## 4. 已知限制

1. ~~**TOTP 密钥明文存储**~~ **已修复（2026-09-11）**：改为在账号持久化适配器（`PostgresAccountRepository`）实施静态加密——AES-256-GCM，子密钥由 `WORKBENCH_BACKUP_ENCRYPTION_KEY` 经 HKDF-SHA256（info=`workbench-totp-secret-v1`，RFC 5869）派生，密文格式 `v1:base64(nonce||ct||tag)`，见 `app/accounts/secrets.py`。**剩余边界**：① 开发用内存仓储不落盘，不做加密；② 历史明文行仍可读（只读兼容，新写入一律加密）；③ 拿到 `v1:` 密文却无密钥时仓储直接 fail-closed；④ 轮换备份加密密钥会使既有 TOTP 密文不可解，需由 `super_admin` 重置动态口令后重新绑定。
2. **登录限流按手机号计数**：挡不住攻击者轮换手机号，每个号仍可消耗 5 次 scrypt（本机约 53 ms/次）。生产仍需网关层限流。
3. **弱口令列表为固定字符串集合**：不做变形归一——对已收录口令追加字符、或更冷门的 leetspeak 变形不被拦截；也不校验口令是否包含本人手机号或姓名（已与 `docs/api-contract.md` 一致）。
4. ~~**会话令牌无服务端撤销**~~ **已修复（2026-09-11）**：新增 `POST /api/v1/auth/logout` 与按 `jti` 的服务端撤销名单（内存 + PostgreSQL 表 `workbench_session_revocations`，迁移 `018`），鉴权依赖在每次请求时校验撤销状态，登出后同一令牌**立即失效**；撤销条目只保留到令牌自身过期时间。**剩余边界**：① 撤销查询失败时按 fail-closed 返回 `503`（不放行）；② 缺少 `jti` 的令牌按无效处理；③ 开发期头部身份（`X-*` 头）没有令牌，不适用撤销。
5. ~~**审计明细白名单只校验顶层键名**~~ **已修复（2026-09-11）**：`build_record` 在顶层白名单之外，对**每个明细值**调用 `redaction.has_sensitive_key` 做递归敏感键检查，命中即抛 `AuditDetailNotAllowed`。顶层键仍以白名单为准（因此 `runtime_key` 这类含 `key` 词元的合法键不会被启发式误伤）；**嵌套结构里出现 `*_key` 等敏感词元一律拒绝**（fail-closed）。当前所有明细值都是标量，因此该加固不改变既有行为。
6. **TOTP 同一窗口重放防护**：TOTP 确认后，同一 30 秒窗口内的同一个码无法再次用于登录（被重放防护拒绝）——这是正确行为，但客户端需等待新窗口。
7. **未在真实环境验证的部分**：PostgreSQL 仓储、Celery/Outbox、外部 Runtime 均未在真实环境验证。
8. **开发态请求头身份**：`X-Tenant-Id/X-User-Id/X-User-Role` 在 `development` 下是设计内约定；必须以生产门禁（`WORKBENCH_ENV≠development`）确保其不被启用。

## 5. 未覆盖范围与原因

| 未覆盖项 | 原因 | 需要真实环境 |
|---|---|---|
| PostgreSQL 仓储的租户隔离、唯一约束、原子审批 | 本机内存仓储，未连真实 PostgreSQL | 真实 staging + PostgreSQL |
| 登录限流的并发正确性与跨进程一致性 | 内存实现，单进程 | 真实 PostgreSQL 的 upsert + 并发压测 |
| Redis Streams / Celery / Outbox / 死信通知 | 未启动真实 Redis/Celery | 真实 staging |
| RAGFlow / AgentScope / WeKnora 适配器的密钥注入与跨租户实测 | 使用 FakeTransport / 未接真实外部服务 | 真实外部平台账号与密钥注入 |
| 真实模型生成的内容安全与提示词注入 | 使用 Mock 后端 | 真实模型 + 内容安全评估 |
| 传输层安全（TLS/HSTS）、网关限流、WAF | 进程内 TestClient 无网络层 | 真实部署网络 |
| 桌面端/浏览器端 XSS 渲染 | 项目仅返回 JSON，无前端渲染层 | 前端应用集成测试 |
| TOTP 与主流验证器 App 的兼容性 | 未用真实验证器扫描 | 真实设备验收 |

> **复测指针（2026-09-16）**：上表各项的真实环境复测**尚未执行**；其中与本表第 1 行（真实 PostgreSQL 租户隔离面）、第 2 行（限流并发面）直接相关的「八类攻击面」重放方法已成文（1.12）：**决策层** = [`docs/superpowers/specs/2026-09-16-attack-surface-retest-design.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-16-attack-surface-retest-design.md)（范围 / 判据 / 分期 / A1–A5 裁决）；**执行层** = [`docs/attack-surface-retest-runbook.md`](file:///d:/徐徐AI学习/公司工作台/docs/attack-surface-retest-runbook.md)（八类逐项请求清单）。其余行不在 1.12 复测范围（规格 §5）。**执行待基础设施输入 I1–I14 与单独写授权；本报告全部结论不变。**

## 6. 结论

本报告基于**本机 `TestClient` + 内存仓储**的真实执行：八类攻击面（水平越权、垂直越权、身份伪造、字段提权、注入、绕过前端、信息泄露、资源滥用）**均按设计返回预期防御结果，未发现新的可利用问题**；同时如实记录了 8 项已知限制与 8 项需真实环境验证的范围。

**本报告不代表生产验收。** 真实 staging、真实 PostgreSQL、真实 Redis/Celery、真实外部 Runtime 与真实外部平台上的验收仍未完成；本报告不构成任何「已上线 / 已发布 / 已收录」的结论。
