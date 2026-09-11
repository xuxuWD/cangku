# `/api/v1` 接口契约（第一阶段）

## 身份

开发环境暂时使用 `X-Tenant-Id`、`X-User-Id`、`X-User-Role` 请求头验证流程。正式环境必须替换为统一登录、短期会话和设备绑定，客户端提供的角色不能作为安全依据。

角色标识：`employee`、`department_lead`、`ceo`、`super_admin`、`customer_admin`。CEO 与超级管理员的权限分开审计。

## 健康检查

`GET /api/v1/health`

返回服务状态和服务名，不包含密钥、数据库连接串或内部堆栈。

## 账号注册与登录

账号由工作台自建：员工提交注册申请，超级管理员审批并指定角色与归属租户，审批通过后才能登录。首个管理员凭部署注入的 `WORKBENCH_BOOTSTRAP_TOKEN` 自助申请，角色固定为超级管理员，租户由申请自行声明；普通申请的 `tenant_id` 与 `role` 一律忽略。

登录标识为手机号，在部署内全局唯一。口令只保存 scrypt 哈希，任何响应、事件和日志都不包含口令或口令哈希。

口令策略（注册、本人改密与管理员重置三条链路统一实施，且**不可通过环境变量关闭**）：

- 长度 10 到 128 个字符，不能包含控制字符。
- 不能是纯数字，不能是重复的单一字符。
- 不能命中内置的常见弱口令集合。比对时把输入转小写后精确查表，因此大小写变体会被拦截。
- **已知限制**：该集合是固定字符串集合，不做变形归一——对已收录口令追加字符、或更冷门的 leetspeak 变形不会被拦截；也不校验口令是否包含本人手机号或姓名。

上述任一不满足时，接口返回 `422`。

`POST /api/v1/auth/registrations`

提交注册申请。请求体包含 `phone`、`password`、`position`、`full_name`，可选 `email`、`tenant_id`、`bootstrap_token`。首个管理员申请缺少正确初始化口令时返回 `403`；手机号已存在返回 `409`；口令不满足策略返回 `422`；成功返回 `201` 与账号视图，视图中的手机号已脱敏。

`GET /api/v1/auth/registrations?status=pending`

仅超级管理员可调用，按状态查询申请列表，默认 `pending`。其他角色返回 `403`，非法状态返回 `400`。

`POST /api/v1/auth/registrations/{account_id}/approval`

仅超级管理员可调用。请求体为 `{ "role": "...", "tenant_id": "..." }`，只允许审批 `pending` 状态；重复审批返回 `409`，账号不存在返回 `404`。

`POST /api/v1/auth/registrations/{account_id}/rejection`

仅超级管理员可调用。请求体为 `{ "reason": "..." }`，只允许驳回 `pending` 状态。

`POST /api/v1/auth/sessions`

用 `phone`、`password` 与可选 `totp_code` 换取会话令牌。手机号不存在、口令错误或账号未通过审批一律返回 `401`，文案为「手机号或密码不正确」，不区分原因。账号绑定动态口令后必须同时提交 `totp_code`：未提交返回 `401`「需要动态验证码」，验证码错误返回 `401`「动态验证码不正确」（两种情况都会计入登录失败限流）。账号被锁定（同一手机号在 5 分钟窗口内失败达阈值）时返回 `429`，文案为「登录尝试过于频繁，请稍后再试」。由于计数按手机号统一执行，已存在与不存在的手机号达到阈值后表现一致，不泄露账号是否存在。成功返回 `access_token`、`token_type`、`expires_in`、`tenant_id`、`user_id`、`role` 和 `scope`。会话密钥未配置时返回 `503`。

会话按 `scope` 分两种：

- `full`：完整会话，可访问全部有权限的接口。
- `totp_enrollment`：**受限会话**。当 `WORKBENCH_REQUIRE_ADMIN_TOTP` 为真且 `super_admin` / `ceo` 尚未绑定动态口令时签发；有效期取 `min(WORKBENCH_SESSION_TTL_SECONDS, WORKBENCH_TOTP_ENROLLMENT_TTL_SECONDS)`（默认不超过 300 秒）。受限会话只允许访问 `POST /api/v1/auth/me/totp`、`POST /api/v1/auth/me/totp/confirmation`、`POST /api/v1/auth/logout` 与 `GET /api/v1/health`；访问其他受保护接口一律返回 `403`「账号需要先完成动态口令绑定」。

`POST /api/v1/auth/logout`

登出当前会话：把该令牌的唯一号（`jti`）记入**服务端撤销名单**，同一令牌**立即失效**，不再依赖有效期兜底。成功返回 `204`，无响应体。仅对令牌会话有效——使用开发期头部身份（`X-*` 头）时没有令牌可撤销，返回 `401`；已撤销或已过期的令牌再次调用同样返回 `401`。撤销存储不可用时返回 `503`（fail-closed，绝不放行）。撤销条目只保留到该令牌自身的过期时间，到期自动失效。

`PUT /api/v1/auth/me/password`

已登录用户修改本人密码。请求体为 `{ "old_password": "...", "new_password": "..." }`；原密码错误返回 `401`，新口令不满足策略返回 `422`。

`POST /api/v1/auth/accounts/{account_id}/password`

仅超级管理员可调用，用于忘记密码后的重置。请求体为 `{ "new_password": "..." }`；账号不存在返回 `404`，其他角色返回 `403`。

`POST /api/v1/auth/me/totp`

已登录用户开始绑定本人动态口令。服务端生成新的 base32 种子并返回 `secret`、`otpauth_uri`、`digest`（`SHA1`）、`digits`（`"6"`）、`period`（`"30"`）；此时尚未启用。重复调用会作废旧种子并重置确认状态。种子的 `otpauth_uri` 中账号标识为脱敏手机号，不含明文手机号。

`POST /api/v1/auth/me/totp/confirmation`

已登录用户用验证器当前 6 位码确认启用。请求体为 `{ "totp_code": "..." }`；尚未开始绑定返回 `409`「请先开始绑定动态口令」，验证码错误返回 `401`「动态验证码不正确」。

`POST /api/v1/auth/accounts/{account_id}/totp-reset`

仅超级管理员可调用，用于用户更换设备或丢失验证器后的找回：清除目标账号的动态口令绑定，之后该账号可仅凭口令登录（管理员会在下次登录时被要求重新绑定）。账号不存在返回 `404`，其他角色返回 `403`。

动态口令为自建实现（RFC 4226 / RFC 6238，仅使用标准库）：6 位码、30 秒步长、校验窗口 ±1 步，并拒绝同一窗口内的重放。绑定、确认与重置分别写入审计动作 `account.totp.enrolled`、`account.totp.confirmed`、`account.totp.reset`；强制绑定提示写入 `account.totp.enrollment_required`。审计明细与结构化日志均不含种子或验证码。动态口令种子在**持久化层静态加密**存储（AES-256-GCM；子密钥由 `WORKBENCH_BACKUP_ENCRYPTION_KEY` 经 HKDF-SHA256 派生，密文带 `v1:` 前缀，历史明文行只读兼容；内存仓储不落盘故不加密）——**轮换备份加密密钥会使既有种子不可解**，须先由超级管理员重置动态口令再完成轮换。

会话令牌使用 HMAC-SHA256 签名，载荷包含租户、用户、角色、会话范围、签发时间、过期时间和唯一号；过期或签名错误一律返回 `401`。有效期由 `WORKBENCH_SESSION_TTL_SECONDS` 控制，默认 900 秒，范围 60–3600；受限会话有效期另受 `WORKBENCH_TOTP_ENROLLMENT_TTL_SECONDS` 约束，默认 300 秒，范围 60–900。旧令牌缺少会话范围时按 `full` 处理。**登出立即生效**：令牌的 `jti` 记入服务端撤销名单（迁移 `018`），此后同一令牌一律 `401`；缺少 `jti` 的令牌按无效处理。

### 关键操作审计

账号与计划模块的关键操作会写入通用安全审计表 `workbench_audit_log`，并同时输出单行 JSON 结构化日志（logger 名 `company_workbench.audit`，写入标准输出，级别取 `WORKBENCH_LOG_LEVEL`）。

覆盖动作：`account.registration.requested`、`account.registration.approved`、`account.registration.rejected`、`account.login.succeeded`、`account.login.failed`、`account.login.locked`、`account.password.changed`、`account.password.reset`、`account.totp.enrolled`、`account.totp.confirmed`、`account.totp.reset`、`account.totp.enrollment_required`、`account.sso.login.succeeded`、`account.sso.login.rejected`、`account.sso.identity.bound`、`account.sso.mfa_required`、`plan.proposed`、`plan.approved`、`plan.rejected`、`plan.run_started`、`orchestration.proposed`、`orchestration.approved`、`orchestration.rejected`。

审计记录包含动作、操作者、租户、目标、脱敏手机号与结构化明细（明细字段由服务端白名单限定）；**不包含**口令、口令哈希、令牌、Cookie、密钥或模型原始响应。本轮不提供读取审计的接口。

## 统一登录（SSO / OIDC）

在自建账号之上提供可选的 OIDC 单点登录。**默认关闭**（`WORKBENCH_SSO_ENABLED=false`）；启用时缺少任一必填项（issuer、授权/令牌/公钥端点、client id/secret、回调地址）一律按 fail-closed 在启动时报错。SSO 只做「登录」，账号仍由审批制产生。

`GET /api/v1/auth/sso/authorize`

无需认证。生成一次性 `state`、`nonce` 与 PKCE，返回 `{ "authorization_url": "...", "state": "..." }`，客户端据此跳转 IdP。未启用 SSO 返回 `503`「SSO 未启用」。

`POST /api/v1/auth/sso/callback`

无需认证。请求体为 `{ "code": "...", "state": "..." }`。服务端一次性消费 `state`（过期或重复使用一律拒绝），用授权码 + PKCE 换取令牌并校验 ID Token，按 **已验证邮箱**（`email_verified=true`）匹配账号。根据是否仍需要应用内 TOTP 返回两种结果：

- **需要 TOTP**：`200`，返回受限令牌 `scope=sso_pending`、`requires_totp=true`、`expires_in=WORKBENCH_SSO_STATE_TTL_SECONDS`，并附 `tenant_id`、`user_id`、`role`。
- **不需要 TOTP**：`200`，返回与 `POST /api/v1/auth/sessions` 同构的完整会话（`scope=full`、`expires_in=WORKBENCH_SESSION_TTL_SECONDS`）。

错误映射：未启用返回 `503`；`state` 失效、账号不存在/未审批、身份不匹配、ID Token 校验失败一律返回 `401`，detail 为固定安全文案，**不回吐 IdP 原始响应**。

`POST /api/v1/auth/sso/verification`

需要认证，且**只接受 `scope=sso_pending` 的受限令牌**（其他 scope 返回 `403`）。请求体为 `{ "totp_code": "..." }`；校验通过后返回完整会话（同 `create_session` 结构）。验证码错误/缺失沿用密码登录的同款状态码与文案（`401`）。

受限令牌 `sso_pending` 的权限边界：仅允许访问 `POST /api/v1/auth/sso/verification` 与 `GET /api/v1/health`，访问其他受保护接口一律返回 `403`「请先完成动态验证码校验」。

安全约定：

- **不自动建号**：邮箱在部署内必须已存在且已审批；否则返回 `401`，绝不隐式创建账号。邮箱只用于匹配，**不写入审计明细与日志**，拒绝审计只记录固定原因码与 `provider`。
- **防账号接管**：首次登录把 IdP 的 `sub` 绑定到账号（`account.sso.identity.bound`）；此后 `sub` 与已绑定值不一致一律拒绝。
- **算法白名单**：ID Token 只接受 `HS256`（用 `client_secret` 验签）与 `RS256`（用 jwks 公钥验签），显式拒绝 `alg=none` 与未知算法，防止算法混淆。
- **MFA 关系**：`WORKBENCH_SSO_TRUST_IDP_MFA` 默认 `false`，即 IdP 承担 MFA 与否都仍要求应用内 TOTP；只有部署方显式声明「IdP 已承担 MFA」时才跳过。应用内 TOTP 的校验与重放防护与密码登录完全一致。
- 审计动作：`account.sso.login.succeeded`、`account.sso.login.rejected`、`account.sso.identity.bound`、`account.sso.mfa_required`（明细只含 `provider` / 固定 `reason`）。

## 私有部署商业化 G0

商业化接口面向内部版和客户私有部署版，当前不包含在线支付、自动开通或 SaaS 计费。租户始终从认证上下文的 `X-Tenant-Id`（正式环境为统一登录会话）派生；客户端传入的 `tenant_id` 查询参数不会改变数据范围。

`GET /api/v1/commercial/usage`

返回本租户的**累计用量**与**累计费用**：`{"tenant_id", "units", "cost_cents"}`。数据来自追加式用量账本 `workbench_usage_ledger`（幂等键去重、冲正写入负值记录），因此 `cost_cents` 为**整数分**、冲正后累计可能为负；**没有按时间 / 模型 / 任务的维度**。

- **权限**：`super_admin`，或**本租户已登记的 `customer_admin`**；其他角色 `403`「只有客户管理员或超级管理员可以管理租户商业化设置」。
- **`404` 语义**：先查租户再取用量，因此**本租户未在商业化模块登记时返回 `404`「租户不存在」**——这是未初始化环境的常见态，不是故障；已登记但无计量事件的租户返回 `200` 且两个字段为 `0`。
- 管理台「用量与费用」页（`?view=billing`）复用本接口，只读展示；模型清单尚未实现（模型由配置注入，无实体表与接口），属下一期立项。设计见 `docs/superpowers/specs/2026-09-12-usage-billing-page-design.md`。

`GET /api/v1/commercial/tenant`

客户管理员或超级管理员查看当前租户摘要，包括租户状态、负责人和创建时间。

`GET /api/v1/commercial/usage`

客户管理员或超级管理员查看当前租户服务端汇总的用量和成本（分）。用量记录由服务端追加，客户端不能提交额度结果、成本或套餐判断。

`POST /api/v1/commercial/exports`

客户管理员或超级管理员申请租户数据导出，接口只创建异步作业并返回 `202`。导出内容经过脱敏，不包含密码、Cookie、验证码、令牌、原始 API 密钥或客户原文。

`POST /api/v1/commercial/deletion-requests`

客户管理员或超级管理员申请删除当前租户，接口返回带冷静期的异步生命周期作业。冷静期结束前必须完成最终导出，删除执行不在请求线程完成。

`GET /api/v1/commercial/lifecycle/{job_id}`

只允许查看当前租户的生命周期作业；跨租户或不存在的作业统一返回 `404`。普通员工不能查看或发起商业化管理操作。

## 任务

## 公众号内容工作台 Alpha

内容工作台面向内部内容运营员工，使用现有任务和 Runtime 作为事实源，首期只生成微信公众号图文草稿，默认不抓取网页（仅在服务端配置抓取白名单后可用受限抓取接口）、不调用真实模型、不自动发布。

`POST /api/v1/content-tasks`

请求体包含 `topic`、`sources`、`knowledge_references` 和 `idempotency_key`。来源中的正文摘录由员工粘贴，链接只保存为引用元数据，服务端不会访问链接。服务端固定创建低风险 `content-writer` 任务并启动 Mock Runtime；相同租户、用户和幂等键重放返回原任务，输入不同返回 `409`。

`GET /api/v1/content-tasks`

按 `status`（可选，只允许 `reviewing`、`failed`、`confirmed`，其他值返回 `400`「不支持的内容任务状态」）、`page`（默认 1）、`page_size`（默认 20，上限 100，越界返回 `400`）分页列出内容任务摘要。可见性与单条查询一致：普通员工只能看到自己创建的任务，CEO 与超级管理员可看本租户全部。返回 `items`（任务号、主题、状态、创建人、创建/更新时间、运行号）、`page`、`page_size`、`total` 与 `has_next`。

`GET /api/v1/content-tasks/{task_id}`

返回素材、当前运行号、草稿、revision、状态和内容审计。状态为 `generating`、`reviewing`、`confirmed` 或 `failed`。普通员工只能访问自己创建的内容任务；跨租户或无权资源统一返回 `404`。

`POST /api/v1/content-tasks/{task_id}/regenerations`

使用新的幂等键重新生成当前任务草稿，不创建第二个业务任务；旧运行、草稿和生成审计保留。生成后端由 `CONTENT_GENERATION_BACKEND` 选择，默认 `mock`；真实模型使用 `CONTENT_MODEL_BASE_URL`、`CONTENT_MODEL_NAME`、`CONTENT_MODEL_API_KEY`、`CONTENT_MODEL_TIMEOUT_SECONDS` 和 `CONTENT_MODEL_MAX_RETRIES`。真实模型失败时任务进入 `failed`，不会静默降级为 Mock。

`PUT /api/v1/content-tasks/{task_id}/draft`

员工在 `reviewing` 状态下编辑标题、摘要、正文和配图建议。请求必须携带当前 `revision`，版本不匹配返回 `409`，服务端不会静默覆盖其他修改。

`POST /api/v1/content-tasks/{task_id}/confirmation`

员工确认当前 revision，写入确认操作者和时间。该确认是内容交付确认，不是管理审批，也不代表已发布。

`DELETE /api/v1/content-tasks/{task_id}/confirmation`

撤销已确认状态并增加 revision，撤销动作可审计。

`GET /api/v1/content-tasks/{task_id}/export.md`

仅允许导出已确认草稿，未确认返回 `409`。响应为 UTF-8 Markdown，包含标题、摘要、正文、配图建议、来源和公开任务号；不包含租户 ID、角色、Token、Cookie、API Key、Runtime 内部会话或原始事件载荷。

`POST /api/v1/content-sources/scrape`

需登录。请求体固定为 `{"url": "<http/https 地址>"}`，长度上限 2048，不接受未知字段（否则 `422`）。抓取功能默认关闭：仅当配置了抓取白名单（`CONTENT_SCRAPE_ALLOWED_DOMAINS`，逗号分隔）时可用，未配置返回 `503`（白名单为空即关闭，不是放行）。服务端只访问白名单域名及其子域，并遵守 `robots.txt`、按域限速（`CONTENT_SCRAPE_MIN_INTERVAL_SECONDS`）、限制响应体积（`CONTENT_SCRAPE_MAX_BYTES`）：非 `http`/`https`、地址含用户信息、域名不在白名单、robots 不允许或不可用（fail-closed）一律返回 `403`（`ScrapeDenied`）；非 `2xx`（不自动跨域跳转）、内容类型不受支持、正文为空、超时/网络失败一律返回 `502`（`ScrapeFailed`）。成功返回 `{"url","title","text","truncated","content_type","fetched_at"}`。**无论成功或被拒都写入审计 `content.source.scraped`，detail 仅含 `domain` 与 `status`（`fetched`/`denied`/`failed`）**；只读、不执行 JS、不写入任何数据，也不提供外部发布能力。

Mock Runtime 使用规范化素材和固定模板生成可重复结果，输入摘录中的指令性文字不会改变权限、策略或任务状态。

## 内容发布（公众号）

`POST /api/v1/content-tasks/{task_id}/publications`

需登录且仅限可见范围（非 CEO/超级管理员仅本人创建的内容）。**只有已确认的草稿可以发布**，未确认返回 `409`。发布功能默认关闭：仅当同时配置 `CONTENT_PUBLISH_ENDPOINT`、`CONTENT_PUBLISH_ACCOUNT_ID`、`CONTENT_PUBLISH_ACCESS_TOKEN` 时可用，否则返回 `503`。

**幂等与绝不自动重发**：幂等键由服务端推导为 `"{task_id}:{revision}"`，并由数据库对 `(tenant_id, idempotency_key)` 施加唯一约束。同一幂等键的重复请求**返回既有发布记录且不再次调用外部平台**，串行与并发下都不会重复发布。平台调用失败时先落库为 `manual_takeover` 再返回 `502`，交由人工接管；**重发必须由人工决定，服务端不会自动重试**。

成功或幂等复用返回 `201`：`{"publication_id","task_id","revision","target","status","receipt_id","error","created_at","verified_at"}`。

`GET /api/v1/content-tasks/{task_id}/publications`

返回 `{"items": [...]}`，按创建时间倒序，仅限本租户与可见范围。

`POST /api/v1/content-publications/{publication_id}/verification`

回执核对：向平台查询该回执的当前状态并更新记录（写入 `verified_at`）。无回执或平台返回异常返回 `502`，未配置渠道返回 `503`。

审计动作：`content.publication.requested`、`content.publication.succeeded`、`content.publication.manual_takeover`、`content.publication.verified`。明细仅含 `target`、`receipt_id`、`status` 等非敏感字段，**不含正文、账号密钥或访问令牌**。

`POST /api/v1/tasks`

创建任务。必填信息为标题、数字员工标识、风险等级、预算和幂等键，可选项目标识。高风险任务创建后状态为 `pending_approval`，其他任务状态为 `queued`。首次创建返回 `201`，相同租户、用户和幂等键重放返回同一任务并返回 `200`。

`GET /api/v1/tasks/{task_id}`

只允许读取当前租户的任务。不存在或属于其他租户时统一返回 `404`，不泄露任务是否存在。

`POST /api/v1/tasks/{task_id}/approve`

仅 CEO 或超级管理员可调用。只允许审批 `pending_approval` 状态；重复审批返回冲突，不重复写入审计。

## 死信处理

`GET /api/v1/dead-letters`

仅 CEO 或超级管理员可查看当前租户的死信事件，返回失败原因、尝试次数和重放审计状态。

`POST /api/v1/dead-letters/{event_id}/replay`

仅 CEO 或超级管理员可发起重放。重放会将原事件重新投递到事件总线，重复重放返回 `already_replayed`，不会绕过消费端幂等校验。开发环境使用内存登记；生产环境必须接入 `003_dead_letters.sql` 对应的持久化仓储并完成 staging 验收。

## 协同动态

`GET /api/v1/collaboration-dynamics?limit=50`

返回当前用户有权限查看的近期任务事件摘要，供桌面端、网页端和未来动画表现层使用。接口只读，不接受动作指令；任务标题、数字员工、状态和发生时间均来自服务端真实任务记录。普通员工只能看到自己有权限读取的任务，CEO 和超级管理员可按当前租户权限查看汇总。

响应为数组，每项字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `event_id` | string | 任务事件 ID |
| `aggregate_id` | string | 任务号 |
| `action` | string | 事件动作 |
| `title` | string | 任务标题 |
| `employee_key` | string | 数字员工标识 |
| `status` | string | 任务状态，当前为 `queued` / `pending_approval` / `cancelled` |
| `tenant_id` | string | 所属租户 |
| `project_id` | string \| null | 所属项目，可为空 |
| `created_by` | string | 责任人 |
| `occurred_at` | string | 发生时间（ISO 8601） |

`status` 仅取当前任务状态机已有的三态；「执行中 / 等待发布 / 已完成 / 需要人工处理」等状态在任务状态机落地前不会返回。

## 企业知识检索

工作台通过 WeKnora 适配器调用官方 `POST /api/v1/knowledge-search`。适配器固定绑定租户、受限 API Key 和知识库白名单，只返回检索片段及来源引用，不把 WeKnora 内部表结构暴露给客户端。知识库写入、Skill 安装、Shell、沙箱和提示词变更不属于该只读接口范围。

适配器同时支持只读文档详情查询（对应 WeKnora `GET /api/v1/knowledge/:id`），用于获取文档标题、所属知识库、解析状态、启用状态和更新时间。工作台只保存文档 ID、知识库 ID、版本/更新时间和引用关系，不复制 WeKnora 原文；返回的租户或知识库范围不匹配时立即拒绝。

岗位和数字员工的知识库范围由超级管理员在工作台策略中心绑定。检索入口按当前租户、岗位和数字员工自动解析允许的知识库 ID；未配置范围返回空结果，不接受客户端自行扩大范围。

范围绑定的持久化记录包含租户、绑定类型、岗位/数字员工标识、知识库 ID、授权人和授权时间；同一租户内重复绑定不会产生重复记录，替换范围在单一事务中完成。

范围替换会在同一事务写入审计记录（旧范围、新范围、操作者、时间），用于权限变更追溯；客户端不能修改或删除审计记录。

`PUT /api/v1/knowledge-access/roles/{role_key}` / `GET /api/v1/knowledge-access/roles/{role_key}`

超级管理员设置或查看岗位的知识库范围。请求体为 `{ "knowledge_base_ids": ["kb-1", "kb-2"] }`，空数组表示清空范围。

- **写路径闸门（阶段 2）**：`PUT` 要求该岗位**已在「数字员工设置」目录中且状态为 `active`**，否则 `409`「该标识尚未纳入目录，请先在「数字员工设置」中纳管」；已停用、格式非法（非 `^[a-z0-9][a-z0-9._-]{0,63}$`）或不属于本租户的标识同样按「未纳管」处理（`409`），不泄露存在性。
- **判定顺序**：先鉴权（非 `super_admin` 一律 `403`），再判目录（`409`）。越权请求无论标识是否纳管都返回 `403`，不因闸门而改变。
- **标识归一（口径 D5）**：路径中的标识与目录同口径处理——去首尾空白并转小写后校验；**写入与查找都按归一键进行**，响应里的 `binding_key` 回显归一键。因此 `PUT .../roles/Content-Operator` 与 `PUT .../roles/content-operator` 是同一对象；同时**格式被收紧**（必须与目录标识同格式），非法格式的绑定不再被接受。
- **读路径不变**：`GET` 与检索解析**不设闸门**，历史自由文本绑定仍按归一键可读（`GET` 对非法/空标识返回空范围，不报错）。

`PUT /api/v1/knowledge-access/agents/{agent_key}` / `GET /api/v1/knowledge-access/agents/{agent_key}`

超级管理员设置或查看数字员工的知识库范围。接口按租户隔离并自动去重排序；其他角色返回 403。闸门与归一口径同岗位接口（`409` 文案相同）。

`GET /api/v1/knowledge-access/audits?limit=100`

超级管理员查看当前租户的知识范围变更记录，包含岗位/数字员工标识、修改前后知识库列表、操作者和时间。审计记录只读，其他角色返回 403。

任务视图至少包含：任务号、租户、项目、发起人、数字员工、标题、风险等级、预算、幂等键、状态和审计数量。真实运行阶段还需增加步骤、产物、证据、回滚和失败原因。

## 统一事件

后续任务、模型、审批、通知和移动端均使用统一事件封装：事件号、租户、聚合类型、聚合号、版本、顺序号、去重键、发生时间、动作和脱敏载荷。消费端必须幂等，支持断线重放。

任务创建和审批成功后会发布 `task.created` 与 `task.approved` 事件。相同幂等键的重放请求不会再次发布事件。开发环境使用内存总线验证顺序和重放；生产环境使用 PostgreSQL Outbox + Redis Streams + Celery，事件先在任务事务内写入 Outbox，再异步投递。

Redis Streams 生产适配器使用消费组读取事件，处理成功后显式确认消息，并可接管超过空闲阈值的挂起消息。事件消费者以 `dedupe_key` 去重。Outbox 发布失败会递增持久化尝试次数，达到配置上限后登记到 `workbench_dead_letters`，继续由死信接口人工重放；失败事件不会被标记为已完成。真实 Redis/Celery Worker、告警渠道和 staging 联调仍需单独验收。

## 持久化启动

开发环境的内容工作台默认使用项目根目录 `data/content-workbench.sqlite3` 保存任务、草稿和审计，服务重启后可恢复。可用 `CONTENT_STORE_PATH` 或 `WORKBENCH_CONTENT_STORE_PATH` 覆盖 SQLite 文件路径；测试和临时场景可显式设置 `WORKBENCH_CONTENT_STORE_BACKEND=memory`。其他控制平面仓储仍遵循 `WORKBENCH_STORAGE_BACKEND` 配置。

`WORKBENCH_ENV` 为非开发值时，启动会强制要求 `WORKBENCH_STORAGE_BACKEND=postgres`、PostgreSQL 地址和不少于 32 位的认证密钥，并按 `migrations/` 文件名顺序执行未应用迁移。生产环境不会静默回退到内存仓储，内容工作台也不允许使用内存仓储。

## 错误

业务人员界面只展示中文原因和下一步建议。服务端日志保留内部诊断编号，但不返回堆栈、凭据、Cookie、验证码或原始 API 密钥。

## 计划生成与审核

员工用自然语言描述目标，服务端依据工具白名单生成一份可审核的 Agent 计划。计划的步骤、`kind` 与是否需要审批**一律由服务端按工具白名单推导**，生成器（含真实模型）提供的同类字段被忽略；未知工具会导致整份计划被拒绝。计划挂在既有任务上，审核通过后复用既有 Runtime 执行。

`POST /api/v1/tasks/{task_id}/plan-proposals`

在指定任务下提交目标并生成计划提案。请求体为 `{ "goal": "...", "idempotency_key": "..." }`。首次创建返回 `201` 与提案视图；相同租户、任务与幂等键重放返回既有提案。未配置任何可用工具返回 `422`；生成结果不合法（未知工具、步骤数超限、参数含敏感字段）返回 `422` 并给出固定文案，不回显模型输出；跨租户或无权任务返回 `404`。

`GET /api/v1/plan-proposals/{proposal_id}`

查看提案与服务端推导后的步骤。跨租户或无权统一返回 `404`。

`POST /api/v1/plan-proposals/{proposal_id}/approval`

仅 CEO 或超级管理员可调用，且**发起人不能审批自己提交的计划**；否则返回 `403`。只允许 `pending_review` 状态，重复审批返回 `409`，提案不存在返回 `404`。

`POST /api/v1/plan-proposals/{proposal_id}/rejection`

仅 CEO 或超级管理员可调用。请求体为 `{ "reason": "..." }`，只允许 `pending_review` 状态。

`POST /api/v1/plan-proposals/{proposal_id}/runs`

审核通过后启动运行。请求体为 `{ "runtime_key": "...", "mode": "..." }`。未通过审批返回 `409`；跨租户或无权返回 `404`；运行时不可用返回 `400`。执行时由服务端从任务快照重建租户、岗位、预算与策略版本，客户端不能覆盖。

提案视图包含提案号、任务号、目标、步骤（含服务端推导的 `kind` 与 `requires_approval`）、状态、生成器标识与时间；不包含模型密钥、原始模型响应或内部提示词。

工具白名单由 `WORKBENCH_PLANNER_TOOLS` 配置声明，**默认空**；为空时计划生成返回 `422`（未配置任何可用工具），不会产出空计划。

## 待我审批聚合

把四类待审批事项聚合成一个只读列表，供工作台首屏轮询展示「待我审批」。接口**不执行任何审批动作**，只做查询与计数。

`GET /api/v1/approvals/pending?limit=50`

- `limit` 为可选查询参数，默认 `50`，取值范围 `1`~`200`；越界返回 `422`。
- 需要登录；未认证返回 `401`。
- **按角色过滤**：任务审批（`task_approval`）、计划提案（`plan_proposal`）与运行内审批（`run_approval`）仅 `ceo`/`super_admin` 可见；账号注册（`account_registration`）仅 `super_admin` 可见。
- 非审批角色（如 `employee`、`department_lead`）**返回 `200` 与空列表、全 0 计数**，而非报错，便于客户端直接展示「暂无待办」。
- 计划提案与运行内审批中「发起人 == 当前用户」的条目会被剔除（与审批动作「发起人不能自审」保持一致）。
- 每类最多返回 `limit` 条，合并后按 `created_at` 降序；任务数据类没有时间字段，统一用最早时间兜底排在末尾。
- 不同租户之间数据隔离：只返回当前租户的任务、计划提案与运行审批；账号注册按既有注册列表口径（超级管理员可见的未分配租户申请）。
- **运行内审批只覆盖非终态运行**（`running`/`paused`）中仍为 `pending` 的项；已结束运行的待办不会出现（列出也点不了）。`postgres` 模式下运行时状态已持久化，待办跨重启与多进程可用；`memory` 模式（仅 development）仍随进程消失。

响应结构：

```json
{
  "items": [
    {
      "kind": "task_approval",
      "target_id": "task-xxx",
      "title": "整理选题",
      "requested_by": "u-1",
      "created_at": "2026-09-10T00:00:00+00:00",
      "detail": { "risk_level": "high", "employee_key": "content-operator" }
    }
  ],
  "counts": {
    "task_approval": 1,
    "plan_proposal": 0,
    "account_registration": 0,
    "run_approval": 0,
    "total": 1
  }
}
```

- `kind` 固定四取值：`task_approval`、`plan_proposal`、`account_registration`、`run_approval`。
- `detail` 只含既有接口已暴露的非敏感字段：任务为 `risk_level`、`employee_key`；计划提案为 `step_count`；账号注册为 `position`；运行内审批为 `run_id`、`approval_id`、`step_id`、`tool`（客户端据此调用 `POST /api/v1/runs/{run_id}/approvals/{approval_id}/approval`）。
- `counts` 五个键恒存在，无待办时为 `0`；`total` 为本次返回条目总数。账号注册的标题为脱敏手机号，不泄露超出既有注册列表接口的 PII；运行内审批的标题为任务标题（任务不可见时回落为「运行审批」）。

## 站内通知（收件箱）

把「与本人相关的结果」投递给**等待结果的人**，供工作台首屏与「通知」页展示。收件箱只做通知，**不承载任何业务正文**：标题是服务端固定文案，不含用户输入、手机号、客户原文或任务内容。接收人即触发动作的申请人（任务提交人、计划/编排提案发起人、内容发布记录创建人）。

三类接口均需登录（未认证 `401`），且**只返回/只影响调用者本人**的通知；跨用户、跨租户一律不可见。

`GET /api/v1/inbox?unread_only=false&limit=50`

- `unread_only` 可选，默认 `false`；`limit` 可选，默认 `50`，取值 `1`~`200`，越界返回 `422`。
- 按创建时间降序返回；`unread_count` **始终是本人未读总数**，与 `unread_only`、`limit` 无关，便于客户端角标直接取值。
- 返回 `{"items": [...], "unread_count": 0}`，每项字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `inbox_id` | string | 通知 ID（服务端生成） |
| `kind` | string | 通知类型，见下表 |
| `title` | string | 服务端固定文案 |
| `target_type` | string \| null | 关联对象类型，可为空 |
| `target_id` | string \| null | 关联对象 ID（任务号、提案号等），可为空 |
| `created_at` | string | 创建时间（ISO 8601） |
| `read_at` | string \| null | 已读时间，未读为 `null` |

- `kind` 固定十取值：`task.approved`、`plan.approved`、`plan.rejected`、`orchestration.approved`、`orchestration.rejected`、`publication.manual_takeover`、`run.failed`、`run.cancelled`、`run.approval_rejected`、`account.registration.approved`。

`POST /api/v1/inbox/{inbox_id}/read`

标记单条通知已读，返回更新后的通知对象。**重复标记幂等**（首次写入的 `read_at` 不被覆盖）。他人或跨租户的通知统一返回 `404`「通知不存在」，不泄露存在性。

`POST /api/v1/inbox/read-all`

把本人全部未读通知标记为已读，返回 `{"updated": <实际更新条数>}`；无未读时返回 `{"updated": 0}`。

**触发点**：任务审批通过、计划提案通过/驳回、编排优化提案通过/驳回、内容发布失败转人工接管、运行失败、运行被取消、运行内审批被驳回、账号注册审核通过。运行类通知的接收人经 `task_id → task.created_by` 反查；任务不可见时跳过通知并写审计 `run.notify_skipped`。

**写入失败不阻断主流程**：通知写入异常时主业务照常返回，并写入审计 `inbox.write_failed`（明细仅含 `kind` 等非敏感字段）。

**保留期**：通知保留 `WORKBENCH_INBOX_RETENTION_DAYS` 天（默认 `90`），由写入时的惰性清理删除过期记录，无独立定时任务。

## 岗位与数字员工清单

把**已经出现过的**岗位 / 数字员工标识摊开给超级管理员看：各自绑定的知识库与关联任务数。接口**只读**，不提供增删改（编辑知识范围走「知识权限管理」）。

`GET /api/v1/workforce/roster`

- **权限**：仅 `super_admin`；其他角色 `403`「只有超级管理员可以查看岗位与数字员工清单」；未认证 `401`。
- **租户隔离**：只统计与列出当前租户的数据。
- **数据来源（三个事实源的并集）**：知识范围里的 `role` 绑定、`agent` 绑定、以及任务中出现过的 `employee_key`；同一标识只出现一次。
- 响应：`{"items": [{"key", "role_knowledge_base_ids", "agent_knowledge_base_ids", "task_count"}], "total": <条数>}`

| 字段 | 说明 |
| --- | --- |
| `key` | 岗位 / 数字员工标识 |
| `role_knowledge_base_ids` | 作为**岗位**绑定的知识库 id；未绑定时为空数组 |
| `agent_knowledge_base_ids` | 作为**数字员工**绑定的知识库 id；未绑定时为空数组 |
| `task_count` | 本租户内 `employee_key == key` 的任务数；无任务时为 `0` |

- 排序：`task_count` 倒序，其次 `key` 升序（结果稳定）。
- 不返回账号、手机号或任何 PII。
- **不是目录管理**：本接口只反映「已出现过的标识」，不提供新增/编辑/停用；真正的目录实体见下一节。系统角色（账号 `role`）不在此接口。`task_count` 为**精确匹配**，标识写法不同（大小写、空格）会被视作不同标识，不做归一化。

## 岗位与数字员工目录（「数字员工设置」）

把岗位与数字员工变成**可管理的目录实体**：岗位有标识、中文名、描述与启用状态；数字员工有标识、中文名、**所属岗位**、描述与启用状态。口径见 `docs/superpowers/specs/2026-09-12-agent-directory-design.md`。

**通用约定（适用于本节全部接口）**

- **权限**：仅 `super_admin` 可读写；`ceo`、`customer_admin`、`department_lead`、`employee` 一律 `403`「只有超级管理员可以管理岗位与数字员工目录」；未认证 `401`。权限在仓储层与接口层各强制一次。
- **租户隔离**：只读写当前租户；他租户的标识按「不存在」处理（`404`），不泄露存在性。
- **标识规则**：`^[a-z0-9][a-z0-9._-]{0,63}$`；提交前 `strip()` 并转小写（大小写不同视为同一标识）；**创建后不可修改**（任务、知识绑定、运行记录都引用了它）。
- **停用不删除**：`status` 只有 `active` / `disabled`；停用只影响「能否挂载新员工 / 后续指派」，不撤销既有知识绑定，也不影响历史任务与运行。
- **分页**：列表接口必须带 `limit`（1–200，默认 50）与 `offset`（≥0），响应含 `total`。
- **请求体未知字段**：一律 `422`（`extra="forbid"`），避免「传了标识但被静默忽略」。
- **审计**：每次变更写审计，动作为 `workforce.role.created` / `workforce.role.updated` / `workforce.role.disabled` / `workforce.agent.created` / `workforce.agent.updated` / `workforce.agent.disabled`，明细只含 `role_key`、`agent_key`、`status`、`changed_fields`（均为服务端声明值）。
- **响应不含 PII**：字段固定为 `role_key`、`agent_key`、`name`、`description`、`role_key`（所属岗位）、`status`、`created_by`、`created_at`、`updated_at`。

`GET /api/v1/workforce/roles`

- 查询参数：`status`（可选，`active` / `disabled`，其他值 `422`）、`limit`、`offset`。
- 响应：`{"items": [{role_key, name, description, status, created_by, created_at, updated_at}], "total", "limit", "offset"}`；按 `role_key` 升序。

`POST /api/v1/workforce/roles`

- 请求体：`{"role_key": "...", "name": "...", "description": "..."}`（`description` 可省略）。
- `201` 返回创建后的视图；标识重复 `409`「该岗位标识已存在」；标识非法或中文名为空/超长 `422`。

`PATCH /api/v1/workforce/roles/{role_key}`

- 请求体只允许 `name`、`description`、`status`；**传 `role_key` 直接 `422`**（标识不可改）。
- `200` 返回更新后的视图；岗位不存在或不属于本租户 `404`；`status` 非法 `422`。

`GET /api/v1/workforce/agents`

- 查询参数：`status`（可选）、`role_key`（可选，按所属岗位过滤）、`limit`、`offset`。
- 响应：`{"items": [{agent_key, name, description, role_key, status, created_by, created_at, updated_at}], "total", "limit", "offset"}`；按 `role_key`、`agent_key` 升序。

`POST /api/v1/workforce/agents`

- 请求体：`{"agent_key": "...", "name": "...", "role_key": "...", "description": "..."}`（`description` 可省略）。
- `201`；数字员工标识重复 `409`；**所属岗位不存在、不属于本租户或已停用 `409`**。

`PATCH /api/v1/workforce/agents/{agent_key}`

- 请求体允许 `name`、`description`、`role_key`（**换岗**，会重新校验岗位可用）、`status`；**传 `agent_key` 直接 `422`**（身份不可改）。
- `200`；员工不存在或不属于本租户 `404`；目标岗位不可用 `409`。

`GET /api/v1/workforce/candidates`

- **未纳管**标识：知识范围绑定与任务记录里出现过、但目录里还没有的标识，供管理员一键纳管。
- 响应：`{"roles": [...], "agents": [...]}`；岗位候选来自知识范围的 `role` 绑定，员工候选来自 `agent` 绑定与任务中 `employee_key` 的并集。
- 该结果是**实时求差集**，不落库，因此不存在「已纳管却仍显示未纳管」的第二份真相。

**已知限制（如实登记）**

- **命名不对齐**：目录用 `agent_key`，任务字段是 `employee_key`（同值不同名）；因此一个曾作为 `employee_key` 使用过的标识，即使已作为「岗位」纳管，仍会出现在员工候选里。
- **写路径已收敛（阶段 2，2026-09-12 已完成）**：`PUT /api/v1/knowledge-access/{roles|agents}/...` 现在要求标识已在目录且启用（`409`），并已按口径 D5 归一绑定键。**读/检索解析不变**，历史自由文本绑定仍可用。
- 不含模型 / Runtime / 技能 / 预算绑定，也不含组织与部门（均属后续独立立项）。

## 审计查询

把已落库的审计记录（写入侧的明细白名单与递归敏感键校验见「错误」章节与审计模块）变成可查证据。接口**只读**，不接受任何写动作。

`GET /api/v1/audits`

- **权限**：仅 `ceo` / `super_admin`；其他角色 `403`「只有 CEO 或超级管理员可以查看审计日志」；未认证 `401`。
- **租户隔离**：只返回 `tenant_id` 等于调用者租户的记录；`tenant_id` 为空的全局记录（如启动引导）**不返回**。
- 查询参数：

| 参数 | 说明 |
| --- | --- |
| `action` | 可重复（`?action=a&action=b`），取值必须是已登记的审计动作；未知动作码返回 `422` |
| `target_type` / `target_id` / `actor_id` | 精确匹配，可选 |
| `since` / `until` | ISO 8601 时间，**必须带时区**（无时区返回 `422`）；`until` 为闭区间上界。客户端应使用 `Z` 形式——URL 里的 `+00:00` 会被解码成空格而解析失败 |
| `limit` | 默认 `50`，范围 `1`~`200`，越界 `422` |
| `offset` | 默认 `0`，`>= 0`，越界 `422` |

- 响应：`{"items": [...], "total": <命中总数>, "limit": <本次 limit>, "offset": <本次 offset>}`；`items` 按时间**倒序**（新 → 旧），每项字段 `record_id`、`action`、`actor_id`、`target_type`、`target_id`、`phone_masked`、`detail`、`occurred_at`（**不含 `tenant_id`**，恒等于调用者租户）。
- `detail` 直接返回落库内容：写入侧已按白名单 + 递归敏感键校验处理，此处不二次加工。
- **已知限制**：`offset` 分页在翻页期间有新写入时可能跳过/重复个别记录（用时间范围或动作筛选可规避）；`total` 为额外 `COUNT` 查询；不支持导出与 `detail` 模糊搜索。

## 运行指标（子项目②）

每次运行都会写入运行记录（迁移 `013`，结束原因见迁移 `020`），用于聚合指标与生成编排优化提案的样本来源。「运行」包括通过 `POST /api/v1/tasks/{task_id}/runs` 直接启动的运行、计划审批通过后启动的运行，以及内容生成内部启动的运行；记录的**写入者是运行时服务**，暂停/恢复/取消后都会回写同一条记录（保留原始启动时间）。

`GET /api/v1/runs/{run_id}/metrics`

返回单次运行的结构化指标：`run_id`、`task_id`、`proposal_id`、`runtime_key`、`status`、`step_count`、`completed_step_count`、`tool_calls`、`successful_tools`、`knowledge_hits`、`latency_ms`、`started_at`、`finished_at`、`finish_reason`。运行记录不存在，或该运行所属任务对调用者不可见时，统一返回 `404`「运行记录不存在」（跨租户不泄露存在性）。

- `finish_reason` 是**受控枚举**（`run_completed` / `cancelled_by_user` / `step_failed` / `approval_rejected`），仅终态非空；非终态（`running` / `paused`）恒为 `null`，且此时 `finished_at` 也为 `null`。`failed` 细分为「步骤本身失败」与「审批被人工驳回」两种。
- `finish_reason` **不承载自由文本**：失败与取消的具体原因（哪一步、什么原因）需查 `GET /api/v1/runs/{run_id}/events`。
- **已知限制**：`knowledge_hits` 依赖运行时上报，Mock 运行时下恒为 0。

`GET /api/v1/metrics/summary`

按本租户聚合运行指标，可选 `runtime_key` 过滤。仅 CEO 或超级管理员可访问，其他角色返回 `403`「只有 CEO 或超级管理员可以查看运行指标」。

## 基于指标的编排优化提案

工作台读取运行指标（子项目②），在样本充足时自动生成一条「将默认运行时切换到表现更好运行时」的**待人工审核提案**。提案只做建议与留痕，**不会自动修改任何配置**：审批通过只改变提案状态，采纳与执行必须由人按运行手册完成。全部接口仅 CEO 或超级管理员可访问，其他角色返回 `403`「只有 CEO 或超级管理员可以管理编排优化提案」。

生成规则固定且确定性：只保留样本数不少于 `WORKBENCH_ORCHESTRATION_MIN_SAMPLES` 的运行时；合格运行时少于 2 个、当前默认运行时已最优、当前默认运行时样本不足、或最优运行时完成率提升未达到 `WORKBENCH_ORCHESTRATION_IMPROVEMENT_THRESHOLD` 时，均**不生成提案**，由 `reason` 说明原因。合格集合内按完成率、工具成功率、样本数降序、运行时键升序取优，相同输入始终得到相同结论。相同的待审建议会复用既有提案（幂等）；被驳回后可重新生成。

`POST /api/v1/orchestration-proposals`

请求体为 `{ "kind": "runtime_default" }`（可省略，当前仅支持 `runtime_default`，其他值返回 `422`）。接口**始终返回 `200`**，响应为 `{ "proposal": <提案视图>|null, "reason": "..." }`；无提案时 `proposal` 为 `null`，`reason` 为人类可读原因。

`GET /api/v1/orchestration-proposals?limit=50`

列出当前租户的优化提案，返回 `{ "items": [<提案视图>...] }`。

`GET /api/v1/orchestration-proposals/{proposal_id}`

查看提案详情；跨租户或不存在统一返回 `404`「优化提案不存在」。

`POST /api/v1/orchestration-proposals/{proposal_id}/approval`

仅 CEO 或超级管理员可调用，且**发起人不能审批自己提交的优化提案**；否则返回 `403`。只允许 `pending_review` 状态，重复审批返回 `409`，提案不存在返回 `404`。审批通过不触发任何运行时配置变更。

`POST /api/v1/orchestration-proposals/{proposal_id}/rejection`

仅 CEO 或超级管理员可调用。请求体为 `{ "reason": "..." }`，去空后为空返回 `422`，只允许 `pending_review` 状态，映射同审批。

提案视图包含提案号、类型、当前值、建议值、理由、指标快照、状态与时间；指标快照只保留运行时公开评估字段（运行时键、样本数、完成率、工具成功率、知识命中率、P95 延迟），不含内部结构。

生成、审批与驳回分别写入审计动作 `orchestration.proposed`、`orchestration.approved`、`orchestration.rejected`，明细字段由服务端白名单限定。

## Agent Runtime 运行

运行时只是任务执行器，不是权限或任务最终状态事实源。所有动作仍由工作台策略中心检查，计划阶段不执行写入、发布、删除、权限或生产工作流动作。

**运行时状态持久化**（迁移 `021`）：运行上下文、步骤计划、事件、审批项、用量与检查点都会落库（`postgres` 模式写入 `workbench_runtime_states`；`memory` 模式仅限 development），因此**暂停 / 恢复 / 取消 / 决议 / 事件与指标查询在服务重启与多进程部署下仍然可用**；事件 payload 在**写入前**就按同一套敏感键规则脱敏（凭据类键不落库）。

- **已知限制**：事件与状态同存一行、写入为整行 upsert（长运行有写放大，超出当前量级应拆事件表）；同一次运行的并发修改以**最后写入获胜**；重启不会补回此前只在内存里的历史运行；敏感键规则是「键名精确匹配（忽略大小写）」，`cookies` 这类变体不匹配。

- POST /api/v1/tasks/{task_id}/runs：在指定任务下创建运行。请求可指定 runtime_key、mode 和步骤计划；服务端从任务快照重建租户、用户、岗位、项目、预算、知识/文件范围和策略版本，客户端不能覆盖这些字段。创建成功即写入运行记录（响应中的 `status` 反映启动后的真实状态）。
- GET /api/v1/runs/{run_id}/events?cursor=...：返回脱敏事件摘要，支持断点读取；内部 Harness session、凭据和原始敏感载荷不返回。
- POST /api/v1/runs/{run_id}/pause、POST /api/v1/runs/{run_id}/resume、POST /api/v1/runs/{run_id}/cancel：任务创建人、CEO 或超级管理员可操作；跨租户运行统一返回 404。三个动作都会**回写运行记录**（取消后 `status=cancelled`、`finish_reason=cancelled_by_user`、`finished_at` 非空；暂停与恢复为非终态，`finish_reason` 与 `finished_at` 均为 `null`）。取消成功后会向任务创建人发出一条 `run.cancelled` 站内通知。
- POST /api/v1/runs/{run_id}/approvals：登记高风险动作审批请求，返回审批号和 pending 状态，不代表已执行。
- GET /api/v1/runs/{run_id}/approvals：列出该运行的审批项（含已决议），返回 `{"items":[{"approval_id","step_id","tool","status"}]}`；`status ∈ pending/approved/rejected`，`step_id`/`tool` 仅在审批项对应计划步骤时非空。跨租户或运行不存在返回 `404`。
- POST /api/v1/runs/{run_id}/approvals/{approval_id}/approval：决议一个审批项，请求体 `{"approved": true|false}`（不接受未知字段，否则 `422`）。**通过**则执行被批准的步骤，待该运行的审批项全部决议后运行置 `completed`；**驳回**则运行立即置 `failed` 并停止执行剩余步骤。成功返回 `{"run_id","approval_id","status","run_status"}`。
  - 权限：**仅 `ceo`/`super_admin`**，且**发起人不能审批自己发起的运行**（否则 `403`，与计划提案同一口径）。
  - 状态码：未认证 `401`；跨租户/运行不存在 `404`「运行不存在」；`approval_id` 不属于该运行 `404`「审批不存在」；已决议过 `409`「审批已决议」；**运行已进入终态** `409`「运行已结束，无法决议」（终态即终态，不允许用剩余审批把已结束的运行复活）。
  - 决议写入审计 `run.approval_decided`（明细仅 `status`，**不含任何自由文本**）；驳回后向任务创建人发出 `run.approval_rejected` 站内通知。
  - **已知限制**：不收集驳回原因（不收自由文本）；同一次运行的并发决议以最后写入获胜。

开发环境默认注册 mock Runtime。DeerFlow、Codex Worker、Hermes 只能作为独立外部适配器接入，不能直连工作台数据库、Redis、GEO 或生产账号；Hermes 的成长结果只能进入待审核提案。

GET /api/v1/runtimes/health

仅 CEO 和超级管理员可查看 Runtime 健康摘要。返回运行时状态、版本、能力和沙箱状态；未配置或未启用的外部 Runtime 不会被自动调用，响应不包含认证头、内部会话或原始异常。

### RAGFlow 与 AgentScope 外部协议

RAGFlow 适配器只提供租户内的只读知识检索。请求为 `POST {endpoint}/knowledge-search`，知识库范围必须由服务端从当前 `RuntimeContext` 解析并传入；客户端不能扩大、替换或自行指定知识库范围。响应只允许返回经过范围校验的检索片段和引用，不提供知识库写入、删除或索引操作。

AgentScope 适配器只承接受控执行，以下均为外部服务协议：`POST /runs` 创建运行，`GET /runs/{id}/events` 读取事件，`POST /runs/{id}/pause`、`resume`、`cancel`、`approvals`、`replay` 和 `usage` 执行生命周期、审批、重放及用量命令，另有 `GET /health` 健康检查。外部服务不能覆盖工作台从任务快照重建的租户、用户、岗位、项目、预算、知识/文件范围、策略版本、审批结果或最终任务状态。

外部事件只能映射到统一事件类型；未知事件统一映射为 `run.failed`，并仅保留脱敏后的失败原因和安全的外部类型。RAGFlow 与 AgentScope 的认证头、API Key 和 Cookie 应由部署环境注入传输层，不能进入任务载荷、事件或日志；认证注入在开发期尚未实现或验证。开发期使用 `FakeTransport` 只验证适配器契约，不等于真实 RAGFlow/AgentScope staging 验收；真实外部服务、密钥注入、跨租户实测、并发压测和沙箱验证仍需单独完成。
