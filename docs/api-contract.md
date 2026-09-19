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

客户管理员或超级管理员申请租户数据导出，接口只创建异步作业并返回 `202`。导出内容经过脱敏，不包含密码、Cookie、验证码、令牌、原始 API 密钥或客户原文。导出由 worker 周期任务异步生成（不在请求线程完成），导出包过期时间为 **7 天**（`expires_at = created_at + 7 天`，2026-09-14 裁决）。

`GET /api/v1/commercial/exports`

列出本租户**已生成**的导出包元数据（`package_id` / `job_id` / `created_at` / `expires_at`），按生成时间倒序（同一时刻按包号倒序，顺序确定），`limit` 1–200（默认 50）+ `offset` ≥ 0 分页（非法值 `422`）；响应 `{"items", "total", "limit", "offset"}`。**列表不返回载荷 `payload`**（载荷按 `package_id` 单独取回，避免列表携带大体积数据）；列表**如实包含已过期但尚未被 worker 清理的包**——客户端按 `expires_at` 自行标注「已过期」，取回这类包仍返回 `404`「导出包已过期」（清理后与「从未存在」不可区分）。权限与租户口径同取回端点：仅 `customer_admin` / `super_admin` 可列出，租户由服务端从登录上下文解析，**永不列出他租户的导出包**（查询以 `tenant_id` 限定）。设计原因：取回端点需要 `package_id`，而作业视图与申请响应都不携带它；没有本列表时客户端**无法发现包号**，取回能力实际不可用（2026-09-19 补链）。

`GET /api/v1/commercial/exports/{package_id}`

取回本租户已生成的导出包：返回 `package_id`、`tenant_id`、`job_id`、`created_at`、`expires_at` 与脱敏载荷 `payload`。租户由服务端从登录上下文解析（客户端不能指定租户），仅 `customer_admin` / `super_admin` 可取回，普通员工 `403`。**跨租户的导出包与不存在的导出包统一返回 `404`「导出包不存在」**（不泄露他租户资源是否存在）；`expires_at <= 当前时刻` 的过期包返回 `404`「导出包已过期」。**过期包由 worker 周期任务 `export-packages-purge` 按 `expires_at` 物理清理**（`DELETE FROM workbench_export_packages WHERE expires_at <= now`，beat 间隔 `WORKBENCH_EXPORT_PACKAGE_PURGE_INTERVAL_SECONDS`，默认 3600 秒），清理后与「从未存在」不可区分。

`POST /api/v1/commercial/deletion-requests`

客户管理员或超级管理员申请删除当前租户，接口返回带冷静期（默认 7 天）的异步生命周期作业。删除前必须完成**最终导出**：**删除申请之后首次完成的导出即「最终导出」**（据此置 `final_exported` 并与该删除作业关联）。删除前还必须**记录确认人**（见下条确认端点）；两项前置缺一，删除执行一律拒绝（`确认人` 未记录时拒绝执行，**不静默跳过**）。冷静期结束、已完成最终导出且已记录确认人后，由 worker 周期任务执行删除并推进租户到 `deleted`，**删除执行不在请求线程完成**；删除执行写入审计 `commercial.deletion.executed`，明细含 `confirmed_by` 与 `cleared_categories`（本次**实际**清到哪些面，未注入的面不列）。

**删除清场口径（B-3 + B1，2026-09-19）**：租户删除是**物理清场**（软删语义只留给正常业务）。当前清场面为**会话层、记忆层、技能层、知识治理层**四处，逐面调用各层 `delete_all_for_tenant`，并在审计 `cleared_categories` 里如实记录真正清到的面；**未注入的面不参与清场、也不出现在该列表**（不假装清过）。**「整层」= 该层在迁移里的全部租户级表**，不是只清主表：记忆层 = 事实 / 规则 / 身份类画像三张（`029`），技能层 = 技能包 / 数字员工绑定两张（`030`），知识治理层 = 知识文档一张（`032`）——2026-09-19 修复前两处只清主表，导致 `cleared_categories` 面名齐全却仍有整租户行残留（规则 / 画像 / 绑定），现已按整层清场并落守护用例。**会话层（B1）= 六张表**：`execution_idempotency` → `conversation_stream_frames` / `conversation_stream_state` → `conversation_members` → `conversation_messages` → `conversations`（该顺序由**真库外键**决定：幂等行同时引用会话行与消息行、流帧/流态/消息均引用会话行，且这些外键**无级联**；成员表虽有级联仍显式删以保证逐表可数。见 `app/conversation/purge.py`）。**清场未覆盖的租户级表**（任务与运行、CRM、账号、收件箱、授权绑定等）按批次继续扩围（`docs/superpowers/specs/2026-09-19-tenant-purge-expansion-design.md` 的 B2→B5），对象存储文件 / 向量索引 / 缓存另立专项。worker 到期执行时若管理员尚未显式确认，则**按申请自动确认**（确认人 = 请求人，写同一审计动作 `commercial.deletion.confirmed`），避免冷静期长达数十天导致删除静默卡死。

`POST /api/v1/commercial/deletion-requests/{job_id}/confirm`

记录当前租户删除申请的**确认人**（真源 `commercial-g0-design.md:114`「删除前必须生成最终导出包**并记录确认人**」）。这是一次**显式确认动作**，与「申请删除」分开，消除「确认人 = 发起人」的默认假设。成功返回该生命周期作业视图（含 `confirmed_by` / `confirmed_at`）。

- **前置**：作业须处于冷静期内（`cooling_down`）**且已完成最终导出**（`final_exported`）；确认**不改作业状态**，执行仍由冷静期闸门与 worker 排程决定。
- **权限**：仅 `customer_admin` / `super_admin`；普通员工 `403`。
- **`409` 语义**：尚未完成最终导出返回 `409`「删除前必须完成最终导出，再记录确认人」；作业不在冷静期内（已取消 / 已完成）返回 `409`「没有处于冷静期内、可确认的删除申请」。
- **`404` 语义**：跨租户与不存在的作业统一返回 `404`「生命周期任务不存在」。
- **fail-closed**：确认必须写入审计（`commercial.deletion.confirmed`，明细只含 `kind` / `status` 两个受控值，确认人由 `actor_id` 承载）；**未配置审计通道时拒绝确认**（`403`），绝不留下不可追的确认人。

`POST /api/v1/commercial/deletion-requests/cancel`

客户管理员或超级管理员撤销当前租户处于冷静期内的删除申请：租户经状态机从 `deleting` 回到 `active`（`deleting → active` 允许边，不直接改状态字段），作业状态置为 `cancelled`，撤销后 worker 不再执行该删除。没有可撤销的申请时返回 `409`「没有可撤销的删除申请」；非管理员返回 `403`；租户不存在返回 `404`。管理台暂未接入该入口（当前为后端 + 契约能力）。

`GET /api/v1/commercial/lifecycle/{job_id}`

只允许查看当前租户的生命周期作业；跨租户或不存在的作业统一返回 `404`。普通员工不能查看或发起商业化管理操作。

**导出包内容口径（B-2，2026-09-19）**

导出载荷顶层为 `{"tenant_id", "resources", "unimplemented_categories", "unavailable_categories", "truncated_categories", "redaction"}`：

- `resources`：真源 15 类（`users` / `roles` / `agents` / `tasks` / `runs` / `steps` / `artifacts` / `knowledge_documents` / `knowledge_versions` / `knowledge_references` / `memories` / `growth_proposals` / `approvals` / `usage` / `audits`）。**接了读取通道的类别填真实行，未接的一律空数组**并在 `unimplemented_categories` 里列出（**不臆造字段、不假装有数据**）。
- **已接线的类别与字段口径**（B-2 首批·读取器见 `app/commercial/export_readers.py`；**各类行内一律不含租户列**——顶层 `tenant_id` 已给）：`roles`（`role_key` / `name` / `description` / `status` / `created_by` / `created_at` / `updated_at`）、`agents`（数字员工**目录**字段 = `agent_key` / `role_key` / `name` / `description` / `status` / `created_by` / `created_at` / `updated_at`；**不含**系统提示词 / 模型键 / 工具白名单 / 记忆策略 / 自治档 / 预算）、`knowledge_documents`（`KnowledgeDocView` 同字段，不含正文）、`audits`（`AuditRecordView` 同字段，手机号列本身已是掩码列）、`runs`（`RunMetricsView` 同字段，**不含**执行授权位）、`memories`（**三类记忆，行内以 `kind` 判别**；2026-09-19 起覆盖整层——此前只出事实类）。
- **B-2b 追加三类（2026-09-19）**：`tasks`（`task_id` / `project_id` / `created_by` / `employee_key` / `title` / `risk_level` / **`budget_cents`（整数分；组 10.5 起不再导元-浮点）** / `status`；**不含** `idempotency_key` 与 `request_fingerprint`）、`users`（`account_id` / `phone_masked` / `position` / `full_name` / `email` / `role` / `status` / `requested_at` / `reviewed_at` / `reviewed_by`；**手机号只出掩码**，**不含**口令哈希 / TOTP 种子 / SSO 主体 / 驳回理由；**未审批（无租户）的申请账号不属于任何租户** ⇒ 不入包）、`usage`（账本明细 `id` / `units` / `cost_cents` / `reversal_of` / `occurred_at` / **`reason`（2026-09-19 起）**；冲正为负值记录、`reversal_of` 指向原条目，累计口径与 `GET /api/v1/commercial/usage` 一致；**不含**内部幂等键。`reason` 为服务端写入的标记列（保留策略结转行为 `retention_carryover`，见「保留策略执行口径」；冲正行为调用方给的原因；普通明细为 `null`）——补它是为了让结转行在包内**可识别**，否则与普通明细不可区分）。各类排序确定：`tasks` / `users` 为 `id` / `requested_at, account_id`，`usage` 为 `occurred_at, id`。
- **B-2c 追加两类（2026-09-19）**：`artifacts`（`run_id` / `artifact_id` / `virtual_path` / `change_kind` / `bytes` / `sha256` / `created_at` / `expires_at`；在运行级视图之上**补 `run_id`**（租户级快照必须能看出产物属于哪次运行）；**过期口径与运行产物端点一致**（`expires_at` 已过的登记不入包、不计入总数）、排序 `created_at, artifact_id`）、`steps`（**每个计划步骤一行**：`run_id` / `step_id` / `kind` / `tool` / `requires_approval` / `completed`；`completed` 由运行状态的 `completed_steps` 判定；**不含**步骤正文与执行输出——那些属运行事件明细）。**边界登记**：`steps` 上游 `list_for_tenant` 无分页（适配器一次取全量后切片与计数）；内存存储模式下运行时状态是**进程内状态**（重启 / 多进程看到的不完整），**PG 模式读的是持久化状态行**（`workbench_runtime_states`）。
- **`memories` 整层口径（2026-09-19）**：真源 §6.1 的导出项「记忆」= 记忆层的**三类记忆**（`migrations/029_memory_layer.sql` 自述「三类记忆（身份 / 规则 / 事实）」）⇒ 该类别**三类都出**、行内以 `kind` 判别：`kind="fact"`（事实类，字段 = `memory_id` / `scope` / `status` / `content` / `created_at`，**与 2026-09-16 起既有字段逐字一致**）、`kind="rule"`（规则类，既有事实字段 + `rule_key` / `version`）、`kind="profile"`（身份类画像 KV：`owner_kind` / `owner_id` / `profile_key` / `value` / `updated_at`）。**排序确定**：按 `fact` → `rule` → `profile` 分组，组内为 `created_at, memory_id` / `owner_kind, owner_id, profile_key`。**只出 `active` 条目**（`superseded` 的历史版本不入包 —— 与既有事实类口径一致；「导出历史版本」属口径变更，需另议）。**边界登记**：三张表均以 `list_*_for_tenant` 全量读取（无分页）⇒ 适配器一次取全量后切片与计数（同 `knowledge_documents` 手法）。
- **剩余 4 类（`knowledge_versions` / `knowledge_references` / `growth_proposals` / `approvals`）不接线**：系统内**没有对应实体或没有按租户读取通道**（版本只是文档上的单值列、引用关系只存在于内容任务 brief、成长提案无租户字段且仅内存实现、审批只有「待审批聚合」无历史表）⇒ 一律空数组 + 留在 `unimplemented_categories`，**不造数据、不假装有**（真源要求的三类如实标注之一）。
- `truncated_categories`：每类**行数上限**为 `5000`（`EXPORT_CATEGORY_MAX_ROWS`），超出的类别给出 `{"exported": 行数, "total": 该类总数}` —— **不静默截断**；总数取自存储计数（SQL `COUNT(*)`），**不拿返回条数冒充总数**。
- `unavailable_categories`：**读取通道已接但本次读取失败**的类别（读取器抛错）。这类类别**不写入 `resources`**（与「读了但是空」区分开），其余类别照常导出；失败原因只进服务端日志，不进载荷。
- **脱敏**：凭据类列按类别**硬排除**（口令哈希、TOTP 种子、SSO 主体、系统提示词、任务幂等键与请求指纹、运行执行授权位等），且全部行统一过既有脱敏器（敏感键名 + 值内凭据形态，产物 `[已隐藏]`）。
- ⚠️ **部署口径**：导出作业由 **worker 周期任务**执行 ⇒ 生产环境**API 与 worker 两个进程都必须注入同一套读取器**（`build_export_readers`）；只注入一侧时，未注入的那一侧生成的包会是「所有类别皆空」的假包。

**保留策略执行口径（B-4 选项 C，2026-09-19：从声明式变为服务侧可执行）**

保留策略由 worker 周期任务 `app.worker.purge_expired_tenant_data`（beat 条目 `retention-purge`，间隔 `WORKBENCH_RETENTION_PURGE_INTERVAL_SECONDS`，默认 3600 秒、范围 30–604800）**逐租户**执行，把过期数据按策略清理。策略取 `workbench_retention_policies`（真源 §6.3 默认：`tasks` 180 / `events` 365 / `usage` 365 / `audit` 730 天）；**未自定义策略的租户按默认策略清理**（默认保留期是平台声明，不是可选项），`deleted` 租户的残留数据同样按龄清理。每面每轮**有界**（默认 5000 行/面，剩余留待下一轮）；**不提供**「立即全量清理」入口（只按龄、按轮次）。

五面语义（逐面如实，不含夸大）：

- **`tasks`（默认 180 天，按 `created_at`）**：物理删除过期任务行。**仅当该任务的运行（若有）全部已过期时才删**（谓词 `NOT EXISTS(SELECT 1 FROM workbench_run_records r WHERE r.tenant_id = t.tenant_id AND r.task_id = t.id AND r.started_at >= cutoff)`）；不满足则本轮跳过、下一轮运行过期后自然可删 —— `workbench_run_records.task_id` **无外键**，直接删任务会留下悬挂运行。同轮按龄（`created_at`）删除提案域 `workbench_plan_proposals` 与 `workbench_orchestration_proposals`，避免随任务删除产生孤儿（`workbench_plan_versions` 是**商业化套餐版本目录**，不属运行期数据，**不清理**）。⚠️ **任务域事件流不保留**：`workbench_audit_events`（`ON DELETE CASCADE`）随任务一起物理消失 —— 已裁决接受；需要长期追溯的应在导出包中留存。
- **`runs`（默认 180 天，按 `started_at`）**：**先子后父**显式删除（同一事务，顺序固定）：`run_artifacts` → `run_acceptance_decisions` → `run_promotions` → `tool_actions` → `execution_idempotency` → `runtime_states` → `run_records`。⚠️ **运行域证据不保留、不可恢复**：工具执行证据（`027`）、运行验收决议（`040`）、运行→任务沉淀链接（`042`）、产物登记（`037`）随运行一起被销毁。**不删** `workbench_runtime_events`（属 `events` 面）与流帧 / 流状态（属实时流保留期 `WORKBENCH_STREAM_RETENTION_DAYS`，由 `conversation-stream-purge` 负责）。
- **`usage`（默认 365 天，按 `occurred_at`）**：**结转**而非直接删明细。每轮先把过期明细**插入一行净额结转行**（`units` / `cost_cents` = 过期明细的求和；`reason='retention_carryover'`；`actor_id='system:worker'`；`idempotency_key='retention-carryover:<cutoff ISO>'`；`occurred_at=cutoff`），再删除**被求和的那些行**（按行 id 精确删除，不是按时间谓词重删）⇒ `SUM(新表) = SUM(旧表)` **逐分不变**（与是否含冲正对无关：冲正与原件同在过期集合或同在保留集合）。因此 `GET /api/v1/commercial/usage` 的**累计口径与总额不变**；**窗口口径以结转后明细为准**（按时间窗自行汇总的报表在窗内会因结转而位移）。结转行自身也受龄：下一轮到期即并入下一笔结转（净额前滚），不会双算。**有可识别标识**：导出包 `usage` 类别含 `reason` 列（见上条），结转行与普通明细可区分。
- **`events`（默认 365 天）**：**不新建执行器** —— 运行事件已由全局 `runtime-events-purge` 按 `WORKBENCH_RUNTIME_EVENTS_RETENTION_DAYS`（默认 **30 天**）清理 ⇒ 实际保留期 = **更短者**（30 天）。
- **`audit`（默认 730 天）**：**不删**（730 只作留存上限声明，与「审计不可删除」判据一致；执行器不触碰任何审计表）。

可观测：**仅当本轮确有清理或结转**时写审计 `commercial.retention.purged`（空转轮次不落审计 —— 审计面不可删除，不能被心跳噪声占满），明细只含受控值：`runs_deleted` / `tasks_deleted` / `proposals_deleted` / `usage_carried_units` / `usage_carried_cents` / `cutoff`，**不含自由文本**。worker 未接线时任务返回零值（与既有周期任务同口径，不伪造清理结果）。

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

创建任务。必填信息为标题、数字员工标识、风险等级、预算和幂等键，可选项目标识。

- `risk_level` 取值 `low | medium | high | critical`（迁移 `025` 起扩为四档），非法值或大小写不符一律 `422`。
- **`critical` 只能由 `ceo` / `super_admin` 发起**：其他角色（含 `department_lead` 与 `employee`）返回 `403`。该档创建后**一律**进入 `pending_approval`（最高风险档任何自治等级都不得免批）。
- `high` 及以上仍受既有的员工预算闸门约束（`employee` + 不低于 `high` + 预算 > 1000 → `403`），判定用「**不低于**」而不是「等于」，避免更高档绕过闸门。
- **金额口径（组 10.5，迁移 `044_task_budget_cents`，2026-09-19）**：请求与视图**权威字段是整数分 `budget_cents`**（宪法「金额不用浮点」）。`budget`（单位**元**、浮点）保留为**兼容字段**：只给 `budget` 时服务端按 `Decimal(str(x)) × 100` **四舍五入到分**（`0.29` 元 ⇒ `29` 分，不是 28）；**两个字段同时显式提交 ⇒ `422`**（不静默取其一）；都不给 ⇒ `0` 分。响应同时带两字段：`budget_cents`（权威）与 `budget`（= `budget_cents / 100`，供老客户端）。**幂等指纹**：用 `budget` 的请求指纹与 10.5 之前**逐字相同**（老客户端重放仍返回原任务 `200`）；用 `budget_cents` 的请求以 `budget_cents` 入指纹。阈值口径不变（`1000` 元 = `100000` 分）。
- 其余任务的状态由**该数字员工的治理配置**决定（段一规格 §2.2）：`autonomy_level=approval_for_all` 一律待审批；`approval_for_risky` 按该员工的 `risk_threshold` 判定；`full_auto` 除 `critical` 外直接入队。**标识不存在或员工已停用**时回落到 `high` 及以上的既有口径。
- 首次创建返回 `201`，相同租户、用户和幂等键重放返回同一任务并返回 `200`。

`GET /api/v1/tasks/{task_id}`

只允许读取当前租户的任务。不存在或属于其他租户时统一返回 `404`，不泄露任务是否存在。

`POST /api/v1/tasks/{task_id}/approve`

仅 CEO 或超级管理员可调用；**发起人不能审批自己创建的任务**（`403`）。只允许审批 `pending_approval` 状态；重复审批返回冲突，不重复写入审计。

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

> **生产检索入口（2026-09-16 接线）**：对外唯一的检索路径是 `POST /api/v1/knowledge/search`（见「知识治理」节），它**必须先过检索谓词守卫**——未经治理白名单 / 未发布 / 已过复核期的文档不进结果。适配器与守卫此前只有测试装配点，该路由把它们接进运行路径；`WORKBENCH_WEKNORA_BASE_URL` / `WORKBENCH_WEKNORA_API_KEY` 未配置时该路由 `503`（不返回空结果）。

适配器同时支持只读文档详情查询（对应 WeKnora `GET /api/v1/knowledge/:id`），用于获取文档标题、所属知识库、解析状态、启用状态和更新时间；以及**只读文档列表**（对应 `GET /api/v1/knowledge-bases/{id}/knowledge`，分页 `page`/`page_size`/`parse_status`），供存量导入脚本取上游既有文档（规格 §4 N1）。工作台只保存文档 ID、知识库 ID、版本/更新时间和引用关系，不复制 WeKnora 原文；返回的租户或知识库范围不匹配时立即拒绝。

> **租户标识口径**：适配器构造参数 `tenant_id` 必须是 **WeKnora 侧的空间标识**，且调用方 `UserContext.tenant_id` 必须与之同源（适配器靠二者相等强制隔离）。工作台内部租户号与 WeKnora 空间号之间**没有映射表**——混用会被判为「租户范围不匹配」。

岗位和数字员工的知识库范围由超级管理员在工作台策略中心绑定。检索入口按当前租户、岗位和数字员工自动解析允许的知识库 ID；未配置范围返回空结果，不接受客户端自行扩大范围。

范围绑定的持久化记录包含租户、绑定类型、岗位/数字员工标识、知识库 ID、授权人和授权时间；同一租户内重复绑定不会产生重复记录，替换范围在单一事务中完成。

范围替换会在同一事务写入审计记录（旧范围、新范围、操作者、时间），用于权限变更追溯；客户端不能修改或删除审计记录。

`PUT /api/v1/knowledge-access/roles/{role_key}` / `GET /api/v1/knowledge-access/roles/{role_key}`

超级管理员设置或查看岗位的知识库范围。请求体为 `{ "knowledge_base_ids": ["kb-1", "kb-2"] }`，空数组表示清空范围。

- **写路径闸门（阶段 2）**：`PUT` 要求该岗位**已在「数字员工设置」目录中且状态为 `active`**，否则 `409`「该标识尚未纳入目录，请先在「数字员工设置」中纳管」；已停用、格式非法（非 `^[a-z0-9][a-z0-9._-]{0,63}$`）或不属于本租户的标识同样按「未纳管」处理（`409`），不泄露存在性。**数字员工接口额外要求其所属岗位也是 `active`**（岗位停用连带约束其员工；岗位记录缺失同样按不可用处理）。
- **判定顺序**：先鉴权（非 `super_admin` 一律 `403`），再判目录（`409`）。越权请求无论标识是否纳管都返回 `403`，不因闸门而改变。
- **标识归一（口径 D5）**：路径中的标识与目录同口径处理——去首尾空白并转小写后校验；**写入与查找都按归一键进行**，响应里的 `binding_key` 回显归一键。因此 `PUT .../roles/Content-Operator` 与 `PUT .../roles/content-operator` 是同一对象；同时**格式被收紧**（必须与目录标识同格式），非法格式的绑定不再被接受。
- **读路径不变**：`GET` 与检索解析**不设闸门**，历史自由文本绑定仍按归一键可读（`GET` 对非法/空标识返回空范围，不报错）。

`PUT /api/v1/knowledge-access/agents/{agent_key}` / `GET /api/v1/knowledge-access/agents/{agent_key}`

超级管理员设置或查看数字员工的知识库范围。接口按租户隔离并自动去重排序；其他角色返回 403。闸门与归一口径同岗位接口（`409` 文案相同）。

`GET /api/v1/knowledge-access/audits?limit=100`

超级管理员查看当前租户的知识范围变更记录，包含岗位/数字员工标识、修改前后知识库列表、操作者和时间。审计记录只读，其他角色返回 403。

## 知识治理（知识生命周期 + 检索谓词守卫）

口径：`docs/superpowers/specs/2026-09-15-knowledge-governance-design.md`。治理表 `workbench_knowledge_documents`（迁移 032）是**文档级元数据守卫**：登记 Who 拥有 / 同步到什么状态 / 何时复核；**不复制正文、不重建索引**（WeKnora 仍是检索唯一事实源，D1）。

状态机：`draft → published → needs_review → published/archived`（`published → under_review → needs_review → published/archived` 为可选中间态）；`archived` 终态。**归档为「any → archived」：`draft` 可直接归档**（登记后即判废，无需先发布，2026-09-15 口径裁定）。归档 = `status='archived'` 物理保留（软删口径延续，不物理删除）。

发布闸门：`owner_id` 必填（调用方传入或回退既有行，两者皆空 `422`）；仅 `draft` 可发布，其他状态 `409`（状态机校验）。

权限：登记 / 发布 / 归档 / 复核 / 到期扫描 / 列表 / 指标 / 白名单全部**仅 `super_admin`**；其他角色一律 `403`。跨租户或不存在的文档一律 `404`（不泄露存在性）。

检索谓词守卫（§2.3，**N2 已落定并含实测校正**）：治理总开关 `WORKBENCH_KNOWLEDGE_GOVERNANCE_ENABLED`（默认 false）**关闭时**检索行为与今天完全一致（不过滤，也不下传白名单）；**开启时**检索入口在请求 WeKnora 前取本租户 `status='published'` 且未过 `review_due_at` 的文档白名单，**白名单为空 → fail-closed 直接返回空结果、不请求 WeKnora**；非空时把白名单作为 **`knowledge_ids` 下传**（方案②，前向兼容）+ **返回后按白名单收敛**（①）。过期 / 归档文档从检索**下线**，「只归档没删除也没用，必须从谓词下线」。

> ️ **上游实测差异（2026-09-15，WeKnora v0.8.0 + postgres 驱动，真实实例）**：上游 `POST /api/v1/knowledge-search` 虽有 `knowledge_ids` 参数，但**只要请求带了 `knowledge_base_id(s)` 就被静默忽略**（服务端 SQL 无该谓词；不存在的文档 id 也照常返回整库，fail-open）。⇒ 适配器**仍按知识库范围 + 文档白名单双下传**（前向兼容），但**当前真实生效的防线是返回后收敛**，绝不可因「已下传」而删除收敛。**不得**为规避此差异改成「只给 `knowledge_ids`」请求形态（会丢掉上游侧知识库边界）。上游修复后须复测并更新本节。

审计动作码（§2.7，只记文档标识/标题/状态/负责人/版本/来源，**不落正文**）：`knowledge.doc.registered` / `knowledge.doc.published` / `knowledge.doc.archived` / `knowledge.doc.reviewed` / `knowledge.doc.review_due`；检索入口被守卫拦截时记 `knowledge.search.blocked`（明细仅 `role_key` / `agent_key` / `reason`，**绝不记查询正文**；审计通道故障不阻断检索，只在日志留痕）。

- `POST /api/v1/knowledge/documents`：登记知识文档（`draft`；仅 `super_admin`）。请求体 `{"document_id": string, "title"?, string, "owner_id"?, string, "version"? = "1", "source_key"? = "manual"}`，未知字段 `422`。**幂等**：同 `(tenant, document_id)` 重复登记返回既有记录（`201`）。成功 `201`，返回文档视图（不含正文）。
- `GET /api/v1/knowledge/documents?status=&limit=&offset=`：文档列表（仅 `super_admin`），必须分页（`limit` 1–200 默认 50，`offset` ≥0）。`status` 可选 `draft|published|under_review|needs_review|archived`（非法 `422`）。返回 `{"items": [...], "total", "limit", "offset"}`。
- `POST /api/v1/knowledge/documents/{document_id}/publish?owner_id=`：发布（发布闸门：owner 必填；仅 `draft` → `published`）。无 owner `422`，状态冲突 `409`。**发布即置 `review_due_at` = 发布时刻 + 复核宽限**（默认 30 天，`WORKBENCH_KNOWLEDGE_REVIEW_GRACE_DAYS`）——首轮复核周期自发布起算。返回更新后的文档视图。
- `POST /api/v1/knowledge/documents/{document_id}/archive`：归档（`draft` / `published` / `under_review` / `needs_review` → `archived`，§2.2「any → archived」**允许 draft 直接判废**；仅 `archived` 终态出发 `409`）。返回更新后的文档视图。
- `POST /api/v1/knowledge/documents/{document_id}/review?approved=true|false`：人工复核（`under_review` / `needs_review` → 通过 `published`（刷新 `last_reviewed_at` + `review_due_at` 顺延宽限）或判废 `archived`；状态非法 `409`）。返回更新后的文档视图。
- `POST /api/v1/knowledge/review-scan`：手动触发到期扫描（published 且已过 `review_due_at` → `needs_review`；幂等，重复触发不重复计数）。返回 `{"reviewed_due": int}`。**自动调度**：worker beat 任务 `knowledge-review-scan`（`app.worker.scan_knowledge_review_due`）按 `WORKBENCH_KNOWLEDGE_REVIEW_SCAN_INTERVAL_SECONDS`（默认 3600s）周期执行同一扫描（跨租户候选、写回逐条带租户、审计 actor `system:worker`）；扫描不在 HTTP 请求线程执行。
- `GET /api/v1/knowledge/metrics`：Freshness Index（仅 `super_admin`）。返回 `{"published", "needs_review", "archived", "total", "freshness_ratio"}`，其中 `freshness_ratio = published/total`（`total=0` 时取 1.0）。
- `GET /api/v1/knowledge/governance/eligible?limit=`：检索谓词守卫白名单出口（仅 `super_admin`）。只返回 `status='published'` 且未过 `review_due_at` 的文档，供检索组合件在请求 WeKnora 前取白名单（空集 = fail-closed）。
- `POST /api/v1/knowledge/search`：**知识检索（治理层唯一生产入口，2026-09-16 接线，规格 §2.3）**。仅 `super_admin`。请求体 `{"query": string(1–500), "role_key"?: string, "agent_key"?: string, "limit"?: 1–50}`——`role_key` 与 `agent_key` **恰好给一个**（都传/都不传 `422`），**未知字段一律 `422`**（客户端不得自带租户或知识库 id）。范围由服务端 `KnowledgeAccessRegistry.resolve` 按租户解析，检索前先取白名单（`status='published'` 且未过 `review_due_at`）：**白名单空 ⇒ 不请求 WeKnora**。响应 `{"items": [{citation_id, content, source_title, knowledge_id, score}], "total", "limit", "truncated", "reason"}`，其中 `reason` 为空结果归因：`no_binding`（该岗位/员工未绑定任何知识库）/ `empty_whitelist`（被守卫拦截，fail-closed）/ `no_hits`（白名单非空但无命中）；非空结果为 `null`。`limit` **只在服务端截断**（`total` 仍是收敛后总数，超出时 `truncated=true`；不下传上游 `top_k`）。状态码：未登录 `401`；非 `super_admin` `403`；参数非法 `422`；**未配置 WeKnora 或治理开关关闭 `503`**（不提供「无守卫的检索入口」，不返回空结果以免被读成「没查到」）；上游超时 `504`、其余上游失败（连接失败/非 2xx/`success:false`）`502`（对外只给固定文案，**不回显上游地址与密钥**）。拦截路径落审计 `knowledge.search.blocked`（明细仅 `role_key`/`agent_key`/`reason`，**不记查询正文**）；正常检索不落审计。

**存量文档导入（非 API，运维脚本）**：`scripts/knowledge_import_register.py`——**两种数据源**：

- `--source file`（缺省）：读清单文件（JSON `{"documents":[{"document_id","title"?,"version"?}]}` / CSV 含 `document_id` 表头）。
- `--source weknora`（2026-09-16 收口 N1 缺口）：经 `WeKnoraKnowledgeAdapter.list_documents` 调上游 `GET /api/v1/knowledge-bases/{id}/knowledge`（查询参数 `page` / `page_size` / `parse_status`；响应 `{"data":[...], "page", "page_size", "total", "success"}`）**逐页拉到 `total`**；凭据取 `--weknora-base-url` / `--weknora-api-key` 或环境变量 `WORKBENCH_WEKNORA_BASE_URL` / `WORKBENCH_WEKNORA_API_KEY`（**从不回显**，只打印上游主机名）；`--tenant-id` 必须是**上游空间标识**（适配器以「租户号相等」强制隔离，工作台内部租户号与 WeKnora 空间号之间无映射表）；翻页超 `--max-pages`（默认 50）**显式失败**，绝不只导入一部分；条目缺 id 计入拒绝。

两者都：逐条登记为 `draft`（`source_key='migration'`、owner 留空待人工补）、**默认 dry-run**（`--apply` 才写库）、逐行拒绝不静默丢弃（有拒绝时退出码 1）、幂等（已登记跳过）、审计 actor 取 `--actor-id`。

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
- 任务审批、计划提案与运行内审批中「发起人 == 当前用户」的条目会被剔除（与审批动作「发起人不能自审」保持一致）。
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
| `target_conversation_id` | string \| null | **S1 第三款**：该结果所属会话 ID（服务端反查），可为空 |
| `target_approval_id` | string \| null | **S1 第三款**：被驳回的那条审批 ID（仅 `run.approval_rejected`），可为空 |
| `created_at` | string | 创建时间（ISO 8601） |
| `read_at` | string \| null | 已读时间，未读为 `null` |

- `target_conversation_id` / `target_approval_id` 是**可空的上文标识**（迁移 `041_inbox_target_context`，纯增列）：运行类通知由服务端沿 `run_id → 幂等行 → conversation_id` 反查补齐；反查不到（非对话触发的运行、存量行）一律为 `null`。客户端据此可直达「该会话的该条卡」，缺省时回落 `target_type`/`target_id` 的既有落点——**服务端只给权威值，不猜测会话或审批**。

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

返回单次运行的结构化指标：`run_id`、`task_id`、`proposal_id`、`runtime_key`、`status`、`step_count`、`completed_step_count`、`tool_calls`、`successful_tools`、`knowledge_hits`、`latency_ms`、`started_at`、`finished_at`、`finish_reason`。运行记录不存在，或该运行所属任务对调用者不可见时，统一返回 `404`「运行记录不存在」（跨租户不泄露存在性）。**2026-09-17（P2c-6）**：**会话成员可见**（经「运行 → 会话（幂等行反查）→ 成员判定」放行；控制类端点不适用，见「会话协作」节）。

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

**运行时状态持久化**（迁移 `021` + `034`）：运行上下文、步骤计划、审批项、用量、检查点与**事件计数**落 `workbench_runtime_states`，**运行事件独立落 append-only 表 `workbench_runtime_events`**（迁移 `034`：主键 `(run_id, sequence)`，一次写入只追加一行，不再重写历史事件）（`postgres` 模式；`memory` 模式仅限 development），因此**暂停 / 恢复 / 取消 / 决议 / 事件与指标查询在服务重启与多进程部署下仍然可用**；事件 payload 在**写入前**就按同一套敏感键规则脱敏（凭据类键不落库）。

- **事件保留期（运行事件有界）**：事件默认保留 **30 天**（`WORKBENCH_RUNTIME_EVENTS_RETENTION_DAYS`，范围 1–3650），由 worker 周期任务 `runtime-events-purge`（beat 间隔 `WORKBENCH_RUNTIME_EVENTS_PURGE_INTERVAL_SECONDS`，默认 3600 秒）按事件写入时刻清理 ⇒ **超出保留期的事件不再可查**（`GET /api/v1/runs/{run_id}/events` 只返回保留期内的事件；清理不回退序号，已删序号不会被复用）。**只清理运行事件**：审计数据不可删除。
- **已知限制**：事件行与状态行是同一事务内的两次写入（跨进程读只保证各自完整）；同一次运行的并发修改以**最后写入获胜**（同一 run 内并发写同一序号会因主键冲突直接失败，不会写出重复序号）；重启不会补回此前只在内存里的历史运行；敏感键规则是「键名精确匹配（忽略大小写）」，`cookies` 这类变体不匹配；**迁移 `034` 回填的存量事件没有原始时间戳**，其 `occurred_at` 用状态行创建时间近似填充（仅影响这些老事件的保留期计龄）；存量老运行的知识命中计数为 `0`（不回溯统计），新运行的计数从改造后开始累积。

- POST /api/v1/tasks/{task_id}/runs：在指定任务下创建运行。请求可指定 runtime_key、mode 和步骤计划；服务端从任务快照重建租户、用户、岗位、项目、预算、知识/文件范围和策略版本，客户端不能覆盖这些字段。创建成功即写入运行记录（响应中的 `status` 反映启动后的真实状态）。
- GET /api/v1/runs/{run_id}/events?cursor=...：返回脱敏事件摘要（数据来自 append-only 表 `workbench_runtime_events`），支持断点读取——`cursor` 语义不变，返回**序号严格大于该游标**的事件；超出保留期的事件已不再可查；内部 Harness session、凭据和原始敏感载荷不返回。**2026-09-17（P2c-6）**：**会话成员可读**；**非发起人且非成员**沿用既有 `403`「当前员工无权操作此运行」（该端点未纳入「不泄露存在性」的 `404` 口径，如实登记、本批不改）。
- POST /api/v1/runs/{run_id}/pause、POST /api/v1/runs/{run_id}/resume、POST /api/v1/runs/{run_id}/cancel：任务创建人、CEO 或超级管理员可操作；跨租户运行统一返回 404。三个动作都会**回写运行记录**（取消后 `status=cancelled`、`finish_reason=cancelled_by_user`、`finished_at` 非空；暂停与恢复为非终态，`finish_reason` 与 `finished_at` 均为 `null`）。取消成功后会向任务创建人发出一条 `run.cancelled` 站内通知。
- POST /api/v1/runs/{run_id}/approvals：登记高风险动作审批请求，返回审批号和 pending 状态，不代表已执行。
- GET /api/v1/runs/{run_id}/approvals：列出该运行的审批项（含已决议），返回 `{"items":[{"approval_id","step_id","tool","status"}]}`；`status ∈ pending/approved/rejected`，`step_id`/`tool` 仅在审批项对应计划步骤时非空。跨租户或运行不存在返回 `404`。**2026-09-17（P2c-6）**：**会话成员可读该列表**；**决议端点（下面 `POST .../approval`）不放松**（仍仅 `ceo` / `super_admin` 且不得自审）。
- POST /api/v1/runs/{run_id}/approvals/{approval_id}/approval：决议一个审批项，请求体 `{"approved": true|false}`（不接受未知字段，否则 `422`）。**通过**则执行被批准的步骤，待该运行的审批项全部决议后运行置 `completed`；**驳回**则运行立即置 `failed` 并停止执行剩余步骤。成功返回 `{"run_id","approval_id","status","run_status"}`，并**新增可选字段** `execution: {outcome, code?, message_id?}`（`outcome ∈ executed / pending_approval / rejected / failed`；由规格 §4.1.6-7 定义；**不改既有字段**，客户端须对未知字段容错）。
  - 权限：**仅 `ceo`/`super_admin`**，且**发起人不能审批自己发起的运行**（否则 `403`，与计划提案同一口径）。
  - **执行授权位**（迁移 `026`）：**通过**时按服务端认证态登记「谁在何时批准了哪个计划摘要」（`execution_authorized_at/by` + `authorized_plan_digest`），**驳回**时撤销既有授权。授权来源由服务端判定（HTTP 入口固定为 `user`，白名单 `user/system/api/ui/automation`，**`agent` 被显式拒绝**）；请求体塞 `authorized_by` 会 `422`。
  - 状态码：未认证 `401`；跨租户/运行不存在 `404`「运行不存在」；`approval_id` 不属于该运行 `404`「审批不存在」；已决议过 `409`「审批已决议」；**运行已进入终态** `409`「运行已结束，无法决议」（终态即终态，不允许用剩余审批把已结束的运行复活）；**授权位落不下或与当前计划摘要不一致** `409`（`resume` 推进执行时同样校验：已登记授权的运行，计划在批准后变更即拒绝推进）。
  - 决议写入审计 `run.approval_decided`（明细仅 `status` 与 `authorized_by_source`，**不含任何自由文本**）；驳回后向任务创建人发出 `run.approval_rejected` 站内通知。
  - **已知限制**：不收集驳回原因（不收自由文本）；**同一次运行的并发决议为「首写获胜」——重复决议返回 `409`【第四轮修订：原「最后写入获胜」与上一行 `409` 的表述自相矛盾，已按实码 `ApprovalAlreadyDecided` 统一】**；**未授权的运行（计划里没有需要审批的步骤）不在此闸门范围内**——段一没有真实工具，该闸门**拦不到真实副作用**，其硬拦截在 P2a 段二接入真实工具后生效。

开发环境默认注册 mock Runtime。DeerFlow、Codex Worker、Hermes 只能作为独立外部适配器接入，不能直连工作台数据库、Redis、GEO 或生产账号；Hermes 的成长结果只能进入待审核提案。

GET /api/v1/runtimes/health

仅 CEO 和超级管理员可查看 Runtime 健康摘要。返回运行时状态、版本、能力和沙箱状态；未配置或未启用的外部 Runtime 不会被自动调用，响应不包含认证头、内部会话或原始异常。

### RAGFlow 与 AgentScope 外部协议

RAGFlow 适配器只提供租户内的只读知识检索。请求为 `POST {endpoint}/knowledge-search`，知识库范围必须由服务端从当前 `RuntimeContext` 解析并传入；客户端不能扩大、替换或自行指定知识库范围。响应只允许返回经过范围校验的检索片段和引用，不提供知识库写入、删除或索引操作。

AgentScope 适配器只承接受控执行，以下均为外部服务协议：`POST /runs` 创建运行，`GET /runs/{id}/events` 读取事件，`POST /runs/{id}/pause`、`resume`、`cancel`、`approvals`、`replay` 和 `usage` 执行生命周期、审批、重放及用量命令，另有 `GET /health` 健康检查。外部服务不能覆盖工作台从任务快照重建的租户、用户、岗位、项目、预算、知识/文件范围、策略版本、审批结果或最终任务状态。

外部事件只能映射到统一事件类型；未知事件统一映射为 `run.failed`，并仅保留脱敏后的失败原因和安全的外部类型。RAGFlow 与 AgentScope 的认证头、API Key 和 Cookie 应由部署环境注入传输层，不能进入任务载荷、事件或日志；认证注入在开发期尚未实现或验证。开发期使用 `FakeTransport` 只验证适配器契约，不等于真实 RAGFlow/AgentScope staging 验收；真实外部服务、密钥注入、跨租户实测、并发压测和沙箱验证仍需单独完成。

## 对话式 AI 员工平台（P1）

口径：`docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md`。租户语义 100% 落在本项目的 `workbench_conversations`（迁移 `023_conversational_agent`）；会话消息表 **append-only**（不提供编辑接口；**2026-09-17 修订（P2c-4）**：本人可发起**受控物理删除**——见「P2c 对话模式 · 导出与物理删除 · 候选端点 · 结构判定（P2c-4）」；**2026-09-17 修订（P2c-6）**：会话分享与多端协同**已交付**——见「会话协作：分享与多端协同（P2c-6）」，消息 `sender_id` 只增、读路径为「本人 ∪ 成员」）。

**P1 的对话语义**：Harness 使用 `MockRuntime`，**不做任何真实工具调用、不接真实模型**。助手回复是**确定性桩**，并在响应体显式标注 `stub: true`，绝不伪装成真实模型输出。会话与消息的数据模型、权限、审计、分页都是真实的。第一期**不开通文件读写与命令执行**（那是 P2 的能力，D8），配置里的 `tool_allowlist` 只存不用。

**权限与隔离**（与 §8 一致）：
- 可用对话入口的岗位：`employee` / `department_lead` / `ceo` / `super_admin`；`customer_admin` 返回 `403`。
- 普通岗位只能读写**自己发起**的会话；`ceo` / `super_admin` 可读本租户内他人会话。**2026-09-17（P2c-6）**：读路径扩为「**本人 ∪ 成员**」（成员见「会话协作」节）；发言扩为「本人 ∪ `write` 成员」；管理动作（归档 / 改模式 / 删除 / 增删成员）**仍仅本人**。
- **跨租户**访问、以及**修改他人会话**（发消息 / 归档）一律返回 `404`（而非 `403`，避免探测存在性）。**例外（P2c-6）**：可读的 `read` 成员发言 ⇒ `403`（存在性已对成员可见，不再以 404 隐藏）。
- 全部接口：未认证 `401`；越权 `403`；只返回本租户数据；响应不含账号 PII（会话视图不含 `operator_id` 与 `dsh_session_id`）。
- **权限收敛**：对话入口与表单入口对同一动作共用同一套 `ensure_can_create` / `ensure_can_approve` 判定，对话路径不复制判定逻辑。**自治等级只决定「是否需要人批」，不决定「是否绕开权限判定」**：`full_auto` 的员工仍不能做其操作者无权做的事。

**分页口径**：会话列表与会话详情内的消息都使用 `limit`（1–200，默认 50）+ `offset`（≥0，默认 0），并返回命中总数。

- `POST /api/v1/conversations`：新建会话。请求体 `{"agent_key"?: string, "title"?: string}`（未知字段 `422`）。`agent_key` 缺省为默认员工；`agent_key` 只做标识归一，**不校验其在目录中是否启用**——历史会话在数字员工停用后仍必须可解析。成功 `201`，返回会话视图（**2026-09-17 只增 `mode` 字段（P2c-4）**，新建一律 `craft`）。
- `GET /api/v1/conversations`：会话列表，**必须分页**。可选 `status=active|archived`（非法值 `422`）。返回 `{"items":[...],"total","limit","offset"}`。**2026-09-17（P2c-4）**：条目**只增** `mode`；`deleted_at` 非空的会话**一律不出现**（列表 / 详情 / 流 / 发消息 / 改模式对其统一 `404`，与「不存在」不可区分）。**2026-09-17（P2c-6）**：列表范围 = 「**本人 ∪ 成员**」（非 `ceo` / `super_admin` 时；被点名分享的会话同样入列，见「会话协作」节）。
- `GET /api/v1/conversations/{conversation_id}`：会话详情（含消息）。消息同样以 `limit`/`offset` 分页，返回 `messages`、`messages_total`、`messages_limit`、`messages_offset`。跨租户或不属于当前操作者的会话返回 `404`。**2026-09-17（P2c-6）**：读路径 = 「**本人 ∪ 成员**」（`ceo` / `super_admin` 既有只读口径不变）；消息条目**只增** `sender_id`（见「会话协作」节）。
- `POST /api/v1/conversations/{conversation_id}/messages`：发送一条用户消息，落库用户消息与**确定性桩回复**。请求体 `{"content": string}`（空/纯空白 `422`，超长 `422`，未知字段 `422`）。成功 `201`，返回 `{"message_id","conversation_id","stub": true, "reply": {...}}`，其中 `reply.stub=true`。向**已归档**会话发消息返回 `409`。审计动作 `conversation.message.sent`（只记标识与角色，**不记消息正文**）。**2026-09-17（P2c-6）**：发言写权限 = 「**本人 ∪ `write` 成员**」；`read` 成员 ⇒ `403`（**不落库 / 不执行 / 不写幂等行**），非成员且非本人仍 `404`（见「会话协作」节）。
  - **用户消息 `content` 的落库语义（§8 U23，2026-09-14 裁决）＝ 脱敏摘要，非原文**：对话入口**不再把用户原始调用 JSON（或自由文本）逐字落** `workbench_conversation_messages.content`，改落**脱敏摘要** —— 调用 JSON 落 `tool_key` + 参数**键名清单** + 摘要指纹，自由文本落长度 + 指纹；**所有参数值一律不落**（含 `body` 类与 `control` 类，`path` / `target` 亦不保留）。因此 `GET /api/v1/conversations/{conversation_id}` 的 `messages[].content` 为摘要（前端按字符串展示即可），**不含正文原文 / 参数值 / 宿主路径 / 凭据**（与用例 33② 天然一致）。**不改变**响应结构与 `stub` 语义、**不改变**幂等重放（重放按助手消息 `message_id` 反查）与 `messages_total`。哨兵查询：`SELECT COUNT(*) FROM workbench_conversation_messages WHERE content LIKE '%' || <正文原文> || '%';` ⇒ 0。
  - **用户消息 `tool_name` 的落库语义（§8 U23「展示弥补」，2026-09-14）**：为让 UI 仍能看出「用户调用了哪个工具」，**调用 JSON 路径**的两个写入点（`201 executed` / `202 pending_approval`）把解析出的 `tool_key` 落到**用户消息行**的 `tool_name` 列（该列已存在、此前未用）；`content` **仍为脱敏摘要**——`tool_name` 的回填**不得**把任何参数值塞回 `content`。**桩路径**（无 `Idempotency-Key`、不触发真实执行）保持 `tool_name = null`。因此 `GET /api/v1/conversations/{conversation_id}` 的 `messages[]` 中：**用户消息**的 `tool_name` 为本次调用的工具键（桩路径与**存量消息**为 `null`），**助手消息**的 `tool_name` 恒为 `null`。前端在用户气泡展示该字段，字段为空时不渲染（存量消息自然降级为不显示）。
- `POST /api/v1/conversations/{conversation_id}/archive`：归档会话（不删除）。成功返回更新后的会话视图（`status=archived`）；改他人会话返回 `404`。审计动作 `conversation.archived`。
- `GET /api/v1/workforce/agents/{agent_key}/config`：读数字员工配置。**仅 `super_admin`**（其他角色 `403`）；跨租户或不存在返回 `404`。返回提示词、模型键、温度、工具白名单、记忆策略与治理字段（`autonomy_level` / `risk_threshold` / `approval_timeout_minutes` / `daily_budget_cents`）。
- `PATCH /api/v1/workforce/agents/{agent_key}/config`：改配置，**仅 `super_admin`**。请求体各字段可选、未知字段 `422`。校验失败一律 `422`：非法 `model_key`（不在模型网关注册候选内）、越界 `temperature`（须 0.00–2.00）、`tool_allowlist` 含白名单外工具、`system_prompt` 超 8000 字符、`autonomy_level` / `risk_threshold` 非法枚举、`approval_timeout_minutes` 不在 5–10080、`daily_budget_cents` 为负、`memory_policy` 含未知字段。
  - **D11 提示词防护**：`system_prompt` 在**写入阶段**扫描试图改变权限判定的指令（如「忽略/绕过/跳过 审批/权限/限制」、`ignore previous instructions`、`skip approval`），命中返回 `422` 并给出明确中文原因；扫描已考虑大小写、全角/半角与常见分隔符绕过。被拒绝的尝试写入审计 `workforce.agent.config.rejected`（记录被拒字段名与原因，**不记录提示词正文**）。
  - 成功写入审计 `workforce.agent.config.updated`（明细为 `agent_key` 与变更字段名，不含字段正文）；读取写入 `workforce.agent.config.read`。

## 工具执行（P2a 段二）

> **状态（2026-09-14 更正）：本节所述能力已落地**（段二-2 / 段二-3 / 段二-4 + 执行回调端点，实现注见各条；原「契约先行 · 草案 · **未实现**」表述已失效）。**契约口径不变**：与实现冲突时仍以规格评审结论为准并**回改本节**。口径源：`docs/superpowers/specs/2026-09-12-dsh-integration-design.md` §3。
> 落地子段：段二-2（工具目录 + 九步闸门，离线可验收）→ 段二-3（容器执行器 + dsh 适配器 + **`agent_key` 校验收紧**）→ 段二-4（对话入口路由）。
> 本节**先于代码**存在；若实现与本节冲突，以规格评审结论为准并**回改本节**，不得只改代码。

### 与既有契约的变更点（五处）

1. **`POST /api/v1/conversations/{conversation_id}/messages`**：P2a-2 起可触发**真实工具执行**，响应 `stub` 由 `true` 变为 `false`；请求体与分页口径不变。执行是**同步、非流式**的（流属 P2b），期间无过程反馈，因此**必须有单次执行硬上限**（超时 → `504`，见闸门 ⑧）。**状态码分支**：已执行 → `201` + `stub=false`；命中需审批 → `202` + pending；闸门拒绝 → 见闸门表 **①②** 的 `422`（**输入语义错误**：未知工具 / 参数不符）与 **③④⑦** 的 `403`/`409`（**安全拒绝 / 状态冲突**）。**注（J9 定死，2026-09-13）**：① 在**首次执行路径**取 `422`，在**审批后重跑路径**取 `409`（状态漂移冲突，见规格 §4.1.6-5）——**两者刻意不同，实现不得自行统一为一个码**。**请求头 `Idempotency-Key` 可选**：带键 ⇒ 真实执行 + 幂等；**不带键 ⇒ 不触发真实执行**（沿用既有 `stub=true`，不创建承载任务与运行，见变更点 5）。
    **结构化调用口径（实现决策，待评审确认）**：带键触发执行时，消息 `content` 必须是一段**结构化工具调用** JSON `{"tool_key": string, "params": object}`；非结构化 `content` 一律 `422`（不静默执行）。P2a **不做模型规划**，真源未定义「自由文本 → 工具」的映射，故本段不定义该映射；后续接真实模型时由 `tool_invocation_resolver` 替换。
    **`202` 响应体（2026-09-13 定死，不得再留"待定"）**：`{"conversation_id": string, "message_id": string, "stub": false, "status": "pending_approval", "run_id": string, "approval_id": string}`——`message_id` 供幂等重放时重建首次响应，`run_id`/`approval_id` 供前端跳转审批；**不得返回**工具参数原文、宿主路径、凭据。`201` 响应体在既有字段之上**新增可选** `run_id`（无运行时为 `null`），既有字段不变。
2. **`agent_key` 校验收紧的落点在执行入口**：真实执行发生在 `POST /api/v1/conversations/{conversation_id}/messages`，因此**该校验必须在执行入口生效**（存在且启用，复用 `ensure_agent_binding_available`），否则 `422`；`POST /api/v1/conversations` 的既有语义不变。**历史会话在数字员工停用后仍必须可读**（沿用 P1 语义，读取不做启用校验）。
   - **实现注（段二-4，2026-09-14）**：既有 `ensure_agent_binding_available` 底层走 `store.agent_is_active → _ensure_admin`，**只允许 `super_admin`**——普通员工（`employee` / `department_lead`）调用会 `403`，无法作为执行入口校验。故执行入口改用**语义等价且无角色限制**的既有只读入口 `read_agent_governance`（不存在 / 已停用一律返回 `None` → `422`，同时取回治理两字段）。**差异**：`read_agent_governance` 只判「员工 active」，`agent_is_active` 另含「所属岗位 active」；岗位停用连带的收紧**未**在执行入口覆盖（登记为已知差异，待评审决定是否下沉到非管理读路径）。
3. **`GET /api/v1/audits`**：**必须新增** `AuditAction` 的 **`tool.executed`** 与 **`tool.blocked`**（不是「建议」——未扩动作码时 `?action=tool.executed` 会直接 `422`）；明细走 `ALLOWED_DETAIL_KEYS` 白名单，**不含自由文本**，`reason` 为**受控枚举码**（键与取值见下）。**同步要求**：`admin-web/src/features/auditLog/types.ts` 的 `AUDIT_ACTION_LABELS` 必须与后端动作码**全集相等**（`tests/test_frontend_audit_labels.py` 为守护测试，漏同步即红）。
4. **对话消息端点新增副作用**：触发真实执行时会**自动创建一个「承载任务 + 运行」**（`workbench_run_records.task_id` 保持 `NOT NULL` 不变），审批与授权位复用既有 `/api/v1/runs/{run_id}/approvals/*`；**授权项与待批动作由新增迁移 `027` 承载**（2026-09-12 裁决 R1；**DDL、字段规范、主从/事务、回退口径见规格 §4.1**，其中 `027` 为唯一授权权威、`026` 降级为运行级快照）。**不新增 `origin` 之类来源字段**：系统无任务列表接口（仅 `POST /api/v1/tasks`、`GET /api/v1/tasks/{task_id}`、`POST /api/v1/tasks/{task_id}/approve`），承载任务无对外列表面，该要求与迁移口径互斥，已于 2026-09-12 裁决撤销。
5. **新增请求头 `Idempotency-Key`（执行幂等键）**：同一 `Idempotency-Key` 重放**必须返回既有结果**（不新增消息、不新增承载任务、不新增运行、不二次执行）。作用域按 `(tenant_id, 操作者, 会话, 键值)` 唯一，冲突一律返回首次结果并记审计。**原方案（用服务端生成的 `message_id`）不可行**：该值每次 `append` 都新建，重放拿不到相同值。**必填性与缺省语义（2026-09-13 裁决 R6，定死）**：该请求头**可选**；**带键** ⇒ 真实执行且幂等；**不带键** ⇒ **不触发真实执行**（`stub=true`，不创建承载任务与运行、不产生任何真实副作用）。实现**不得**把「无键」理解为「幂等关闭后照常真实执行」（与宪法 4.2「关键写接口必须幂等」相悖，第三轮评审 R3-4 已否）。幂等落点 = 迁移 `027` 的 `workbench_execution_idempotency`（规格 §4.1.3）。

### 执行回调接收端点（内部控制面 · P2a 段二 · 2026-09-14）

> **⚠️ 非用户面**：本端点是**内网服务对服务**调用面（**不挂用户认证依赖**），只由执行回调边车调用，
> 不对前端 / 外部开放。口径源：规格 §3.5 P1 第 3 条 ②④ / §8 U21 裁决「候选②：边车纯转发 + 判定回工作台」。

- 路由：**`POST /api/v1/internal/exec-callback`**（唯一一条；边车对外只暴露 `POST /internal/exec-callback`，
  收到后**原样转发**到本端点）。
- **鉴权**：请求头 **`X-Exec-Callback-Key`**（`WORKBENCH_EXEC_CALLBACK_SHARED_SECRET`，两侧同值）。
  `constant-time` 比对；**缺失 / 不匹配 / 未配置 → `403`**（fail-closed，不泄露存在性）。
- **限流**：`100` rps（进程内令牌桶）；**超限 → `429`**（多副本部署为「每副本 100 rps」，非全局口径）。
- **②④ 判定（判定在工作台权威状态处）**：以 `Authorization: Bearer <短期令牌>` 反查工作台自持绑定，
  `expected` 从工作台权威状态（`ActiveExecutionRegistry` 的「会话当前代次」）重建——**绝不取自请求体**；
  与令牌绑定做 `constant-time` 比对。**不匹配 / 跨租户 / 旧代次 / 未知令牌 → `403`**（固定文案，不泄露存在性）
  + 记审计（**复用 `tool.blocked`，不新增动作码**）。请求体中的任何绑定声明（`binding` / `claimed_binding`）**被忽略**。
- **成功**：`200 {"status":"accepted"}`；**不返回**任何令牌 / 绑定 / 参数原文。
- **边车不做判定**：边车是**无状态纯转发**（不持有自持绑定与登记表）；它把工作台返回的状态码**原样透传**。

### 九步闸门 → HTTP 语义

执行入口唯一，闸门顺序固定（`②③④` 先于 `⑤⑦`）。任一步失败即**不执行**，并写审计 `tool.blocked`。

| 步 | 失败条件 | 状态码 | 中文原因 | 备注 |
| --- | --- | --- | --- | --- |
| ① 白名单 | 工具不在当前组装面内（**首次执行路径**） | `422` | 「未知工具」 | 组装时过滤 **且** 执行入口再校验一次；**审批后重跑路径下同一现象取 `409`**（状态漂移冲突）——规格 §4.1.6-5，**J9 定死** |
| ② 结构化参数 | schema 不符 / 含未知字段 | `422` | 「参数不符合要求」 | 未知字段一律拒绝（白名单） |
| ③ 路径校验 | realpath 后落在允许目录外（含 `..`、符号链接） | `403` | 「路径不在允许范围内」 | |
| ④ 危险命令闸门 | ④-0 可执行文件非来自受信任且不可写的根（含工作卷内同名脚本/ELF）· ④-1 可执行名不在白名单 · ④-2 命中 §3.2.1 的 A/B/C 任一层 | `403` | 「该命令被禁止执行」 | 三个子判定**顺序固定**；④-0 与 ④-1 为 **fail-closed**；**命中即拒，不允许审批放行** |
| ⑤ 风险定档 | 定档为需审批 —— **判定口径 = `spec.requires_approval` OR `needs_approval(自治等级, 风险档, 阈值)`**（复合、取更严；**2026-09-13 用户裁决**，与规格 §3.2 ⑤ 行一致；原只写 `needs_approval`，会让「有副作用但风险档未达阈值」的调用绕过审批）**且**尚无授权 | `202` | pending | 先落库审批请求**再**返回；未落库不得进入等待 |
| ⑥ 审批落库 | 落库失败 | `503` | 「审批请求暂时无法登记，请稍后重试」 | 不进入等待（避免 UI orphan）；**待批动作落迁移 `027`** |
| ⑦ 授权位校验 | 未授权 / **计划摘要或参数摘要不一致** / **存在无对应授权项的待批动作** | `409` | 「授权已失效，请重新审批」 | 授权项由**新增迁移 `027`** 承载（**逐项**校验：待批动作 + 规范化参数摘要 + 批准人/时间 + 计划摘要）；**授权来源白名单校验发生在审批写入阶段**，不在本步 |
| ⑧ 容器执行 | 超时 / 容器异常 / 非 2xx | `504`（超时）或 `502` | 「执行超时，已终止」/「执行失败」 | **超时语义 = 拒绝并终止容器**（fail-closed） |
| ⑨ 结果落库 | — | — | — | 只落**摘要**（见下） |

> **审批通过后的推进（2026-09-12 修订补；2026-09-13 R5-1 补"参数取回口径"）**：审批决议端点通过后，**在同一请求内**从迁移 `027` 的**待批动作**取回**冻结的动作与参数**，并**从 ① 重跑全套闸门**（含 ②③④）再进入 ⑧。**参数取回口径（定死，不得只改一处）**：**控制参数**取该行 `args_json`（**该列只含控制参数，正文类参数以占位常量 `"«body»"` 替代**）；**正文类参数从该行 `body_ciphertext` 解密还原**（规格 §3.4「唯一受控例外」五条约束：AEAD 密文、**密钥不落库**、**TTL 与审批同寿**、**审批落定即清**、**不导出**、**审计不落**），并**按完整参数（含正文）重算 `args_digest` 与本行比对**，不一致 → `409`。**本节「落库口径」的「永不落正文」现为「默认 + 一处受控例外」**（唯一例外即上述密文列，详见规格 §3.4）。**不存在**任何跳过 ②③④ 的「已校验」续跑路径；**不得**以「重新发消息」作为推进方式（那会产生新运行与新授权位，⑦ 将永不可达）。

权限沿用既有口径：对话入口可用岗位为 `employee` / `department_lead` / `ceo` / `super_admin`（`customer_admin` → `403`）；需要审批的动作**仅 `ceo`/`super_admin`** 可决议，且**发起人不能审批自己发起的执行**。跨租户与改他人会话一律 `404`（不泄露存在性）。

### 审计与落库口径

- **审计**：`tool.executed`（已执行）与 `tool.blocked`（被拒，含被黑名单/路径/参数拒）。**明细键为最小集**：新增 `tool_key`、`risk_level`，复用既有 `run_id`、`runtime_key`、`status`、`reason`；**不落** `args_digest`、虚拟路径、`sha256`、字节数。新增键须**同步扩 `ALLOWED_DETAIL_KEYS` 并配测试**（未声明键会直接抛错）；**同时必须扩 `AuditAction`**（否则 `?action=tool.executed` 会 `422`）。
- **`reason` 为受控枚举码**（`path_denied` / `blacklisted` / `param_invalid` / `not_authorized` / `not_in_catalog` / `timeout` / `runtime_error` / `approval_denied` / `approval_expired`——**共 9 值，与规格 §4.1.1 的 `reason_code` 同一集合**；第四轮修订 R4-3 已统一），**不得写入自由文本**——否则命令串、路径、异常 message 会随它落进审计。**该约束仅作用于本节的 `tool.executed` / `tool.blocked`**，**不得**在全局白名单层做 `reason` 键级枚举（既有非工具动作会把 `str(exc)` 写进 `reason`，全局收窄会误伤）。
- **落库**（**文件级**，与上条「审计明细」是两回事）：文件元数据 `摘要 + args_digest + sha256 + 字节数` 的**唯一落点 = 显式导出时的对象存储元数据**；**未导出的中间文件只落摘要**；**永不落文件正文**。当轮上下文可含原文（送模型），**持久化只落摘要**。
  **修订（2026-09-17 · P2c-2）**：执行输出与文件变更的**有界摘录**经**帧通道**回传（见「实时流与过程事件（P2b）」章节的「内容级回传」：
  默认 16 KiB、二进制只留 `bytes`+`sha256`、过 `redact_payload`、**不进审计、不进消息表**、随帧 7 天）；**本条对审计 / 消息表 / 对象存储的既有口径不变**。
- **对象存储**：仅当该文件属工作台受控范围且租户隔离/权限受控时才落；否则**连对象存储也不落**。
- **不建「工具调用记录表」**（X5 不变）：工具调用进既有 append-only 审计。**注意区分**：**新增迁移 `027`** 承载的是**授权项与待批动作**（执行闸门所需），**不是**工具调用记录表。

### 响应与不返回

- 响应可含助手回复文本，**不得**含：宿主真实路径（对外用**虚拟化路径**）、凭据/认证头/Cookie、容器内原始 stdout 全文、其它租户数据、内部堆栈。
- 产物须**显式导出**并过内容安全检查后才可下载；执行环境内**不持有任何长寿命密钥**。

### 已知限制

- **非流式**：⑧ 步执行期间无过程反馈，用户可能面对「等一会儿才出结果」。**2026-09-17 更新（P2b）**：过程反馈经**独立通道**提供——`POST .../messages:stream` + `GET .../stream`（SSE，见「实时流与过程事件（P2b）」章节）；**本端点的同步语义与全部分支保持不变**（流是伴随通道，不是本端点的行为变更）。
- **终止只能由容器层实现**：dsh 无 `cancel`、无 `session-close`、无版本协商；超时与终止一律由容器层承担。
- **黑名单是兜底**：看不到脚本内部；本段按 §3.2.1 的 Q1 锁定值**禁止脚本执行**、只读集仅 `ls/cat/head/tail/wc/stat/file`、禁止管道与 `xargs`。放宽属规格变更。
- **执行闸门此前拦不到真实副作用**（段一无真实工具）；本段接入后该闸门才真正生效。
- **待核实（不得当作已成立）**：dsh 进程位置与模型凭据来源尚未确认，因此本契约**不承诺**「执行环境内不持有任何模型密钥」，只承诺「**不持有任何长寿命密钥**」；该项由段二-1 实测回填。

### 本节开口的决议（Y1–Y3 已定，2026-09-12）

| # | 开口 | 决议 |
| --- | --- | --- |
| Y1 | 是否需要**工具目录只读端点** | ~~**不加**。沿用既有 `model_key` / `tool_allowlist` 惯例：前端自由文本输入 + 提示，后端对非法键返回 `422`；不为假想需求预留端点~~ **2026-09-17 推翻（P2c-4，用户裁决）**：新增两个**只读**候选端点（`GET /api/v1/workforce/model-candidates`、`GET /api/v1/tools/catalog`，仅 `super_admin`、无凭据）；前端改为候选下拉 / 目录多选，**后端校验不变（非法键仍 `422`）**——见「P2c 对话模式 · 导出与物理删除 · 候选端点 · 结构判定（P2c-4）」 |
| Y2 | 工具执行的**运行/审批归属** | **自动创建「承载任务 + Run」**并复用既有 `/api/v1/runs/{run_id}/approvals/*`；**授权项与待批动作由新增迁移 `027` 承载**（2026-09-12 裁决 R1；`026` 降级为运行级快照，见规格 §4.1.5）；**不新增 `origin` 字段**（2026-09-12 裁决撤销）；**幂等键 = 请求头 `Idempotency-Key`**（2026-09-12 裁决 R2，原「`message_id` 派生」已废弃）；**仅当带该键时才触发真实执行**（2026-09-13 裁决 R6） |
| Y3 | `tool.executed` / `tool.blocked` 的**明细键名单** | **最小集**：新增 `tool_key`、`risk_level`，复用 `run_id` / `runtime_key` / `status` / `reason`；不落 `args_digest`、虚拟路径、`sha256`、字节数 |

> 上述三项与本节其余内容**已于 2026-09-14 落地**（原「尚未实现」表述已失效）；实现时若与本表冲突，同样以规格评审结论为准并回改本节。

## 记忆与画像（P3 记忆层）

> 口径：`docs/superpowers/specs/2026-09-15-memory-layer-p3-design.md`（迁移 `029_memory_layer`）。
> **维度固定 1024**（Qwen3-Embedding-0.6B，自托管本地 HTTP 服务，Apache-2.0；**数据不出内网**，生产/staging 必须配置 `WORKBENCH_EMBEDDING_BASE_URL`，缺失即拒绝启动）。
> **状态 2026-09-15：已落地**（契约与实现一致；若有冲突以规格评审结论为准并回改本节）。

**分类口径**：三类记忆互不合并——
- **身份类（画像）**：KV，**不进向量检索、每轮常驻会话上下文**；同键覆盖（UPSERT）。
- **规则类**：整段文本准则；**强制人工在环**；更新走 supersede 链（`status='superseded'` + `superseded_by`），版本号递增。
- **事实类**：短句 + 向量；**向量检索**（pgvector HNSW，cosine）；作废走 supersede 软删链，**不物理删除**。
- 一切按**租户隔离**（写进约束）；跨租户与改他人记忆一律 `404`（不泄露存在性）。

**权限与隔离**（与 P1 对话层同口径）：
- 写：本人「自己的记忆」（`owner_kind=user, owner_id=自己`）；规则类写仅 `super_admin`（视为治理操作）。
- 读：本人自己的；`ceo` / `super_admin` 可读本租户内他人记忆。
- `scope`（user/role/project/organization）**由服务端解析校验**；检索时客户端传入的 scope **一律忽略并重算**（本期固定解析为 user 档 = 本人语义）。
- 未认证 `401`；越权 `403`；embedding 服务不可达写路径 `502`（fail-closed，**不静默降级为「无向量」入库**）。

**审计**：`memory.fact.created` / `memory.fact.superseded` / `memory.rule.created` / `memory.profile.updated`。明细键为最小集（`memory_id` / `scope` / `owner_kind` / `rule_key` / `version`，已入白名单），**不落记忆正文**。

- `POST /api/v1/memory/facts`：写事实类记忆。请求体 `{"content": string, "scope": string, "owner_kind": "user"|"agent", "owner_id"?: string, "idempotency_key": string}`（未知字段 `422`；非法 scope/owner_kind `422`；空/超长 content `422`）。成功 `201`，返回记忆视图（`memory_id`/`content`/`scope`/`owner_kind`/`status`/`created_at`，**不含 embedding 向量**）。**幂等**：同 `(tenant, owner_kind, owner_id, idempotency_key)` 重放返回既有记录，不重复落库、不重复审计。embedding 失败 → `502`。
- `GET /api/v1/memory/facts`：事实类列表，**必须分页**（`limit` 1–200 默认 50，`offset`）。可选 `owner_kind`/`owner_id` 过滤；默认 user 档本人。
- `POST /api/v1/memory/facts/{memory_id}/supersede`：作废事实类（软删链不物理删）。他人/跨租户 → `404`。
- `POST /api/v1/memory/search?query=...&limit=...`：语义检索事实类（query 必填，1–8000 字符）。**scope 由服务端解析**，客户端传值忽略。返回命中列表（按相似度降序）。
- `POST /api/v1/memory/rules`：写规则类记忆。请求体 `{"rule_key", "content", "scope", "owner_kind", "owner_id"}`；同一 `(owner, rule_key)` 已有 active → 自动 supersede 旧版并 `version+1`（版本快照可回滚）。
- `PUT /api/v1/memory/profile`：覆写身份类画像键 `{"key", "value", "owner_kind", "owner_id"}`；同键覆盖。返回当前画像。
- `GET /api/v1/memory/profile?owner_kind=&owner_id=`：读取画像（KV 字典）。

## 技能（P4 技能层）

> 口径：`docs/superpowers/specs/2026-09-15-skill-layer-p4-design.md`（迁移 `030_skills`）。
> **状态 2026-09-15：已实现**（契约与实现一致；若有冲突以规格评审结论为准并回改本节）。
> 技能层 = 「包的声明→校验→注册→审核→绑定→启用」，**不是新执行引擎**——执行永远走既有九步闸门 + `ToolSpecCatalog`；技能只提供「包声明 + 白名单 + 审计」。

**核心语义**：
- **来源白名单**（部署注入 `WORKBENCH_SKILL_SOURCE_ALLOWLIST`，逗号分隔）：空 = 技能层关闭（可登记、不可启用，fail-closed）；`source_key` 不在白名单 → `403`。
- **许可白名单**：`license` ∈ {Apache-2.0, MIT, BSD-3}，否则 `422`。
- **allowed-tools 逐键校验 + 交集**：登记时逐键必须 ∈ 既有 `ToolSpecCatalog`；启用后技能展开的 `allowed-tools` 与目录**取交集**（fail-closed）。
- **人工在环**：提交 → `super_admin` 审核（提交人不能审自己的提交）→ 启用；**不允许用户自传技能包直接生效**。
- **状态机**：`submitted → approved → enabled → disabled`（enabled⇄disabled；approved⇄submitted；rejected 终态）；同 key 多版本并存，只 `enabled` 版本参与工具面展开。
- **零默认技能**：未启用任何技能时，工具面 = 既有默认集，行为与今天一致。
- 全部接口：未认证 `401`；越权 `403`；跨租户/不存在 `404`；只返回本租户数据；响应不含包正文与内容指纹原文。

**审计**：`skill.submitted` / `skill.approved` / `skill.rejected` / `skill.enabled` / `skill.disabled`；明细键最小集（`skill_key` / `agent_key` / `source_key` / `license`，已入白名单），**不落包正文与 description**。

- `POST /api/v1/skills`：提交技能包（申报）。请求体 `{"skill_key", "version", "name", "description", "license", "allowed_tools": [...], "source_key", "content_sha256", "content_body"?}`（未知字段 `422`）。成功 `201`，返回技能视图。**幂等**：同 `(tenant, skill_key, version)` 重复提交返回既有记录。`source_key` 不在白名单 `403`；`license`/`allowed_tools`/`description`/`content_body`（D11 类扫描 + 体积上限）不合法 `422`。**M5 裁决（2026-09-15）**：`content_body` 为技能包正文（库内落库，`031_skills_content`），体积上限 `WORKBENCH_SKILL_CONTENT_MAX_BYTES`（默认 64 KiB）；给出 `content_body` 时其指纹必须等于 `content_sha256`，不一致 `422`。
- `GET /api/v1/skills/{skill_key}/versions/{version}/content`：返回技能包正文（`{"skill_key","version","content_body","content_sha256"}`）。仅本人/管理员可见；他人未审包按 `404`。列表接口**不返回** `content_body`（避免大响应）。
- `POST /api/v1/skills/{skill_key}/versions/{version}/memories`：**M3 打通（2026-09-15）**——把技能使用经验沉淀为**事实类记忆**。请求体 `{"content": string, 1–2000 字符}`；记忆正文加技能引用前缀 `[skill:{skill_key}@{version}] {content}`（可检索），归属操作者自己（`owner_kind=user`），**幂等**（同 `(skill_key, version, content)` 重复提交返回既有记录）。技能对操作者不可见（他人未审包）→ `404`；空内容 → `422`；记忆层未接线 → `503`（fail-closed）。审计复用 `memory.fact.created`。
- `GET /api/v1/skills?status=&limit=&offset=`：技能列表（管理员全看；普通员工只看自己提交的），必须分页。
- `POST /api/v1/skills/{skill_key}/versions/{version}/review?approved=true|false`：审核（仅 `super_admin`；提交人自审 `403`）。
- `POST /api/v1/skills/{skill_key}/versions/{version}/enable`：启用（approved/disabled→enabled；已启用幂等）。
- `POST /api/v1/skills/{skill_key}/versions/{version}/disable`：停用（enabled→disabled；已停用幂等）。
- `POST /api/v1/skills/bindings`：绑定技能到数字员工 `{"skill_key", "agent_key"}`（管理动作）。
- `DELETE /api/v1/skills/bindings?skill_key=&agent_key=`：解绑（active→disabled）。
- `GET /api/v1/skills/agents/{agent_key}/tools`：返回该数字员工已启用技能的 `allowed-tools` 与执行目录的**交集**（服务端解析，fail-closed）。

## 自进化·评测集（P6a）

> 口径：`docs/superpowers/specs/2026-09-16-self-evolution-p6-design.md`（迁移 `033_evolution_eval`，A2 裁决：**P6a 先行**）。
> **状态 2026-09-16：已实现（P6a）**；候选生成 / 准入闸门 / 指针灰度 / 回滚属 **P6b**（D13 判据达标后开工），**本节不承诺**任何 P6b 能力。
> 评测集 = 用例库（`draft → published → archived`，软删 + supersede 软链）+ **离线评测运行器**（CLI `scripts/evolution_eval.py`）+ 采集器（只读拦截轨迹 → 草稿用例）。
> 与 P4 的关系：**同一注册表、同一审计、同一人工闸门口径**；P6a **不改**工具面展开路径（指针化属 P6b）。

**核心语义**：
- **总开关** `WORKBENCH_EVOLUTION_ENABLED`（默认 `false`，fail-closed）：关闭时**不装配任何评测组件** ⇒ 本节全部端点 `503`，CLI 拒绝执行（退出码 1）。
- **权限**：本节全部端点（含只读）**仅 `super_admin`**；越权 `403`；跨租户/不存在 `404`（不泄露存在性）。
- **快照纪律**：`input_snapshot` 必须为对象、UTF-8 体积 ≤ 16 KiB，**任何层级含敏感键（api_key/token/password 等）一律 `422`**——快照不得成为第二份密钥副本。
- **发布闸门（fail-closed）**：发布要求期望（`expectation`）**可执行**——`{"probe": <已注册受评对象>, "expect": "pass"|"blocked"}`（键集恰好两项；probe 必须已注册且能消费该快照形状），否则 `422`。**未标注期望的用例不得发布、不得进入评测**（不默认为通过）。
- **变更走 supersede**：草稿可原地补全期望；**已发布用例的变更用新条目替代**（旧条目 `archived` + `superseded_by` 链到新条目，不物理删除、不原地覆盖）。
- **评测运行只落判定与计数**：`suite_digest` = 当次所用已发布用例集指纹（事后可验证「考了什么」）；逐例明细仅含判定与计数（`status`/`expect`/`repeats`/`failed_repeats`），**不含用例正文**；费用为整数分，单次运行预计费用超过 `WORKBENCH_EVOLUTION_EVAL_MAX_COST_CENTS`（默认 500）即 fail-closed 中止并留痕（`aborted` 运行 + 审计）。
- **运行方式**：v1 为**离线运行**（CLI，不在请求链路内自动触发）；内置受评对象 `runtime-safety-probe`（复用既有运行时安全判定，确定性、零费用）。**运行触发端点不在本期**。

**审计**：`evolution.case.changed`（用例变更）/ `evolution.eval.completed`（运行完成，含 `aborted`）；明细键最小集（`case_id` / `eval_run_id` / `case_count` / `pass_count` / `suite_digest`，已入白名单），**不落用例内容与期望正文**。

- `POST /api/v1/evolution/cases`：登记评测用例（缺省草稿）。请求体 `{"suite_key", "source": "run_trace"|"manual"|"regression"（默认 manual）, "input_snapshot": {...}, "expectation"?: {...}}`（未知字段 `422`；非法 suite_key / 来源 / 快照 / 期望 `422`）。成功 `201`，返回用例视图（含 `input_snapshot`/`expectation`/`input_digest`；`suite_key` 归一为小写）。
- `GET /api/v1/evolution/cases?suite_key=&status=&source=&limit=&offset=`：用例列表，**必须分页**（`limit` 1–200 默认 50）。
- `GET /api/v1/evolution/cases/{case_id}`：用例详情。
- `POST /api/v1/evolution/cases/{case_id}/expectation`：补全草稿用例的期望 `{"expectation": {...}}`。**仅草稿**；已发布/已归档 → `409`。
- `POST /api/v1/evolution/cases/{case_id}/publish`：发布用例（发布闸门见上）；重复发布幂等；已归档 → `409`。
- `POST /api/v1/evolution/cases/{case_id}/archive`：归档用例（软删）；重复归档幂等。
- `POST /api/v1/evolution/cases/{case_id}/supersede`：替代用例，请求体 `{"input_snapshot"?, "expectation"?}`（**至少一项**，否则 `422`）；成功返回**新条目**（草稿，继承套件与来源），旧条目 `archived` 且链到新条目。
- `GET /api/v1/evolution/eval-runs?suite_key=&limit=&offset=`：评测运行列表（离线运行器产出；只读）。
- `GET /api/v1/evolution/eval-runs/{eval_run_id}`：运行详情，含 `results`（逐例 `{case_id, passed, detail}`；明细不含正文）。

## CRM（P5a：客户主数据 + 商务主线 + 智能化打底）

> 口径：`docs/superpowers/specs/2026-09-17-crm-p5a-design.md`（已评审 2026-09-17；迁移 `035_crm_core`，12 表）。
> **状态 2026-09-17：已实现（P5a）**；**发票 / 电子签章 / 工单门户 / 营销自动化 / 触达渠道为二期**（规格 §1.5），本节**不承诺**任何二期能力。
> **权限**：读 / 写 = 本人负责对象（`owner_id`）；`department_lead` / `ceo` / `super_admin` 可全量；`customer_admin` 不进本模块（`403`）。跨租户与「他人负责对象」（非特权岗位）一律 `404`（不泄露存在性）。
> **字段级密级**：联系人 / 线索的 `phone`、`email` 在**列表与详情响应中一律为掩码**（`138****1234` / `a***@example.com`）；明文**只**经 `POST .../reveal` 专用端点返回（响应 `Cache-Control: no-store`），并落审计 `crm.sensitive.revealed`（**明细不落字段值**）；敏感字段**不进** LLM 输入、**不经**数字员工工具输出。
> **状态机（单向推进，非法迁移一律 `409`）**：商机 `qualification → proposal → negotiation → won|lost`（终态不可回迁）；报价 `draft → confirmed → converted|voided`（**confirmed 冻结**：禁改行 / 禁改金额）；合同 `draft → pending_sign → signed → voided|expired`；联动（转合同）均**人工触发**。
> **金额**：一律整数分（`amount_cents`，禁用浮点）；报价行金额 / 税额由**服务端**重算（`Decimal` + `ROUND_HALF_UP`；税率万分比整数 `tax_rate_bp`，13% = 1300）。
> **签署与回款（本段口径）**：合同 `signed` = **线下签署结果的人工登记**（`register-signature`），**系统不承诺法律效力**；回款为人工登记（`register-payment`，原子增量，超合同金额 `409`）。**本段不写任何 provider 代码**。
> **智能化**：`followup-plan` 为**人工触发**；输出固定 Schema（`actions[].{action_type,target_ref,reason,evidence_refs,confidence}` + `summary`），服务端逐条校验**证据引用真实性**（存在 + 同租户 + 归属链），无效引用丢弃并记 `dropped_refs`；全部无效或网关未接 ⇒ `insufficient_evidence=true` 且 `summary` 为**服务端固定文案**「依据不足，无法给出建议」；网关失败 ⇒ `502`（**不降级、不落库**）；**建议永不直接执行**。`progress/summary` **分母为零一律 `null`**（含 `no_target` 标注）。
> **审计**：`crm.*` 最小集 17 个动作码（`crm.account.created` / `contact.created` / `lead.converted` / `opportunity.created` / `opportunity.stage_changed` / `activity.logged` / `quote.created|confirmed|converted|voided` / `contract.created|signed|voided|payment_registered` / `insight.generated` / `sensitive.revealed` / `health.recomputed`）；明细只含标识与受控枚举（**不落正文 / PII / 敏感字段值**）。
> **周期任务**（worker，未接线返回零值）：`crm-health-recompute`（逐租户重算；审计为每租户一行汇总）、`crm-activity-reminder`（**同日幂等**）、`crm-renewal-window`（窗口内提醒；到期未续 ⇒ `expired` 翻转）。
> **错误语义**：未认证 `401`；角色不许可（`customer_admin` / `scope=all` 非管理角色 / 目标写入非管理角色）`403`；跨租户 / 他人对象 / 不存在 `404`；状态冲突（非法迁移 / 冻结改单 / 重复转化 / 回款超限）`409`；未知字段（`extra=forbid`）与非法取值 `422`；模型网关失败 `502`。

- `GET /api/v1/crm/accounts?owner_id=&status=&limit=&offset=`：客户列表（**必须分页**，`limit` 1–200 默认 50；employee 仅本人负责，显式请求他人 `owner_id` ⇒ `404`）。
- `POST /api/v1/crm/accounts`：建客户，请求体 `{"name", "industry"?, "owner_id"?, "custom_fields"?}`（未知字段 `422`；`owner_id` 缺省 = 操作者本人；自定义字段按 `field-defs` 白名单校验）。成功 `201`。
- `GET /api/v1/crm/accounts/{account_id}`：客户详情（含健康度 `health_score` / `health_band` / `health_computed_at`；**未计算 = `null`**）。
- `PATCH /api/v1/crm/accounts/{account_id}`：受控更新 `{"name"?, "industry"?, "status"?, "custom_fields"?}`。
- `POST /api/v1/crm/accounts/{account_id}/followup-plan`：生成跟进计划（见上「智能化」口径）；成功返回洞察记录（`content` / `evidence_refs` / `dropped_refs` / `model_key`）。
- `GET /api/v1/crm/accounts/{account_id}/insights?limit=&offset=`：历史生成记录（append-only；分页）。
- `GET /api/v1/crm/accounts/{account_id}/contacts?limit=&offset=`：联系人列表（**掩码**）。
- `POST /api/v1/crm/accounts/{account_id}/contacts`：建联系人 `{"name", "title"?, "phone"?, "email"?, "is_primary"?, "birthday"?, "custom_fields"?}`。成功 `201`。
- `GET /api/v1/crm/contacts/{contact_id}`：联系人详情（**掩码**）。
- `PATCH /api/v1/crm/contacts/{contact_id}`：受控更新（同上字段）。
- `POST /api/v1/crm/contacts/{contact_id}/reveal`：**敏感字段揭示**，请求体 `{"field": "phone"|"email"}`（其余字段 `422`）；成功返回单字段明文 + `Cache-Control: no-store`；落审计（明细 `{contact_id, field_name}`，**不含值**）。
- `GET /api/v1/crm/leads?owner_id=&status=&limit=&offset=`：线索列表（**掩码**）。
- `POST /api/v1/crm/leads`：建线索 `{"name", "company"?, "phone"?, "email"?, "source"?, "custom_fields"?}`。成功 `201`。
- `POST /api/v1/crm/leads/{lead_id}/convert`：线索转化（**单事务**），请求体 `{"create_opportunity"?, "opportunity_name"?, "account_name"?}`；成功 `201` 返回 `{account, contact, opportunity|null}`；**重复转化 `409`**。
- `POST /api/v1/crm/leads/{lead_id}/reveal`：线索敏感字段揭示（同联系人口径）。
- `GET /api/v1/crm/opportunities?owner_id=&account_id=&stage=&limit=&offset=`：商机列表（分页；`stage` 取值见状态机）。
- `POST /api/v1/crm/opportunities`：建商机 `{"account_id", "name", "amount_cents"?, "expected_close"?, "custom_fields"?}`（`amount_cents` 整数分且 ≥ 0）。成功 `201`。
- `GET /api/v1/crm/opportunities/{opportunity_id}`：商机详情 + **阶段事件时间线**（`stage_events`，append-only）。
- `POST /api/v1/crm/opportunities/{opportunity_id}/stage`：阶段迁移 `{"to_stage"}`（白名单；非法 / 并发先写 ⇒ `409`；每次迁移 append 阶段事件，终态置 `closed_at`）。
- `GET /api/v1/crm/activities?account_id=&contact_id=&opportunity_id=&limit=&offset=`：跟进活动列表（时间线倒序）。
- `POST /api/v1/crm/activities`：登记活动 `{"kind", "subject"?, "content"?, "account_id"?, "contact_id"?, "opportunity_id"?, "status"?, "due_at"?}`（`task` 类默认 `planned` 且必须带 `due_at`；`kind` 五类受控）。成功 `201`。
- `GET /api/v1/crm/quotes?account_id=&status=&limit=&offset=`：报价列表。
- `POST /api/v1/crm/quotes`：建报价 `{"account_id", "lines": [{"description", "qty", "unit_price_cents", "tax_rate_bp"?}], "opportunity_id"?, "valid_until"?}`（行数 1–200；金额服务端重算）。成功 `201`，返回 `{quote, lines}`。
- `GET /api/v1/crm/quotes/{quote_id}`：报价详情，返回 `{quote, lines}`。
- `PUT /api/v1/crm/quotes/{quote_id}/lines`：行**全量替换** `{"lines": [...]}`（仅 `draft`；confirmed 冻结 ⇒ `409`；服务端重算金额）。
- `POST /api/v1/crm/quotes/{quote_id}/confirm`：确认报价（要求 ≥ 1 行且金额 > 0，否则 `422`；仅 `draft`）。
- `POST /api/v1/crm/quotes/{quote_id}/void`：作废报价（`draft` / `confirmed` 可作废）。
- `POST /api/v1/crm/quotes/{quote_id}/convert-to-contract`：报价转合同（**单事务**；仅 `confirmed`；金额取报价合计；quote 置 `converted`）。成功 `201`。
- `GET /api/v1/crm/contracts?account_id=&status=&limit=&offset=`：合同列表。
- `POST /api/v1/crm/contracts`：建合同 `{"account_id", "title", "amount_cents"?, "opportunity_id"?, "starts_on"?, "ends_on"?, "document_object_key"?}`（附件走对象存储引用，不入库）。成功 `201`。
- `GET /api/v1/crm/contracts/{contract_id}`：合同详情（含 `paid_cents` 回款进度）。
- `POST /api/v1/crm/contracts/{contract_id}/submit-for-sign`：提交待签（`draft → pending_sign`）。
- `POST /api/v1/crm/contracts/{contract_id}/register-signature`：**人工登记**签署结果 `{"signed_at", "document_object_key"?}`（`pending_sign → signed`；系统只做台账，**不承诺法律效力**）。
- `POST /api/v1/crm/contracts/{contract_id}/register-payment`：**人工登记**回款 `{"amount_cents"}`（原子增量；超合同金额 ⇒ `409`；`paid_cents` 受库级 CHECK 兜底）。
- `POST /api/v1/crm/contracts/{contract_id}/void`：作废合同（`draft` / `pending_sign` / `signed` 可作废）。
- `GET /api/v1/crm/targets?period_month=&limit=&offset=`：目标列表（employee 仅自己；管理角色全量）。
- `PUT /api/v1/crm/targets`：目标写入（UPSERT，月粒度归一为月首日）`{"owner_id", "period_month", "amount_target_cents"?, "count_target"?}`；**限 `ceo` / `super_admin`**（否则 `403`）。
- `GET /api/v1/crm/field-defs?object_key=`：自定义字段定义列表（前端渲染用；`object_key ∈ {account, contact, lead, opportunity, activity}`）。
- `PUT /api/v1/crm/field-defs`：字段定义写入 `{"object_key", "field_key", "label", "field_type", "required"?, "options"?}`（`select` 必须给受控选项）；**限 `ceo` / `super_admin`**。
- `GET /api/v1/crm/progress/summary?scope=me|all`：多维度进度指标（管线覆盖率 / 赢率 / 销售周期 / 阶段转化率 / 管线账龄 / 创建速率 / 健康分档分布 / 续约窗口 / 回款进度 / 目标达成度；**分母为零一律 `null`**）；`scope=all` 需 `department_lead` / `ceo` / `super_admin`，否则 `403`。

## 实时流与过程事件（P2b）

> 口径：`docs/superpowers/specs/2026-09-17-realtime-stream-p2b-design.md`（**已评审 2026-09-17**；迁移 `036_conversation_stream`，两表）。
> **状态 2026-09-17：已实现（后端）**；**前端消费属 P2c**（本期不动 `admin-web` / `companion-pwa`）。
> **推送底座**：PG 表 + 短轮询（**不引入** Redis Pub/Sub / WebSocket / 消息队列）。**先落库，再推送**。
> **零破坏声明（可验证）**：既有 `POST /api/v1/conversations/{conversation_id}/messages` **行为逐字节不变且不写任何流帧**
> （哨兵断言：走旧端点后帧表计数为 `0`）；`GET /api/v1/runs/{run_id}/events` 与消息表 / 审计 / 运行事件表**结构零变化**。
> **帧只作视图**：权威结果仍在消息表 / 运行记录 / 审计——**流写入失败绝不阻断或改变执行结果**。

### `POST /api/v1/conversations/{conversation_id}/messages:stream`

发送一条用户消息（**实时流路径**）。请求体（`{"content": string}`，`extra=forbid`）/ 请求头（`Idempotency-Key` 语义）/
响应体的字段与取值 / **全部状态码分支**（`201` 已执行 / `202` 待批 / 拒绝码 / `422` / `403` / `409` / `504`）
与旧 `POST .../messages` **逐字一致**（复用同一执行服务与同一幂等口径）。**唯一差异**：

- **响应头新增 `X-Stream-Run-Id: <run_id>`**（**有运行时**才出现；缺键桩路径为 `null` ⇒ 不写该头）；
- 执行过程写**流帧**（供 SSE 端点增量读取）；不带 `Idempotency-Key`（桩回复）时**不写帧**；
- **消息追加被拒**（如向归档会话发消息 ⇒ `409`）时：既有异常语义**不变**，但流以**终态帧**（`run.failed`，`reason=message_rejected`）收口——读端不会留下悬挂流。

**帧写入触发面**：**仅本端点**（旧 `POST .../messages` 零帧）。**幂等重放**：同键重放**不重复执行、不重复写帧**，
返回既有结果 + 既有 `X-Stream-Run-Id`（客户端打开流时按已落帧补发至终态后关流）。
**审批分支**：`202` 返回时流**不写终态帧**（保持 `streaming`；「待审批」展示由既有审批聚合承担）。
**2026-09-17（P2c-6）**：写权限与旧端点**同一判定**——「本人 ∪ `write` 成员」；`read` 成员 ⇒ `403`（**零帧、零落库**）。
**2026-09-17 修订（P2c-2）**：审批决议后的**推进路径接入同一帧写入**（推翻原「本期不做」）——推进时写既有 `kind`
（**不新增取值域**）、**同一 run 的 `seq` 继续单调递增**；该 run 状态行已终态时**先重开**（`status` 置回 `streaming`
并清 `expires_at`）再续写；`202` 后的推进帧与「首次结果帧」同属**一个 run 序列**。

### `GET /api/v1/conversations/{conversation_id}/stream?run_id=&after_seq=`

**SSE 增量读取**（`Content-Type: text/event-stream`）。响应头含 `Cache-Control: no-cache`、`X-Accel-Buffering: no`
（反代不缓冲）、**`X-Stream-Run-Id: <run_id>`（2026-09-17 修订（P2c-2）· 只增）**——**仅当连接建立时已解析到 run**
（显式 `?run_id=` 或该会话已有 run）才出现；会话尚无 run 而挂起等待时**不出现**（客户端据此可判定「本次没有过程流」；
后续新 run 出现时以帧内 `run_id` 归组，见下）。响应**不设 Content-Length**（长连接），由服务端在终态主动关流。

- **run 解析**：`?run_id=` 显式指定（**必须属于该会话与租户**，否则 `404`）；缺省 = 该会话**最新 run**（活跃优先，否则最新历史）；
  该会话一次都没有 run ⇒ **挂起**（仅心跳），轮询中发现新 run 后自动开始补发。
- **起点解析**：请求头 `Last-Event-ID` 与 `?after_seq=` **都解析，取 `max`**（防降级重放导致重复投递）；
  非法值 `422`；起点**大于** `last_seq` **不报错**（只等新帧）；重连且起点已覆盖终态 ⇒ **立即关流**（无新帧）。
- **跨源读取（2026-09-18 补正）**：`X-Stream-Run-Id` 已加入 CORS **响应头**白名单（`expose_headers`）。
  浏览器同源不受影响；**跨源时不 expose 则 JS 读该头恒为 `null`**，客户端会据此误判「服务端没有 run」并提前关流
  （表现为历史会话解析不到运行与审批）。客户端仍应把**帧内 `run_id`** 作为第二来源（连接建立时无 run、稍后出现的场景只有帧内才有）。
- **SSE 帧格式**（每个事件四行，末尾一个空行；**2026-09-17 只增 `run_id`**——覆盖「连接建立时无 run、稍后新 run 出现」与多客户端场景，客户端据此归组并解析「当前 run」）：

```
id: <seq>
event: <kind>
data: {"run_id":"<run_id>","seq":<n>,"is_terminal":<bool>,"kind":"<kind>","payload":{...}}

```

- **心跳**：每 15 秒发一行注释 `: hb`（注释不产生事件、不干扰 `Last-Event-ID`）。
- **关流**：读到并发出 `is_terminal=true` 的帧后**主动关流**；单连接超 `WORKBENCH_STREAM_MAX_CONNECTION_SECONDS`（默认 1800）⇒ 关流（客户端自动重连续播）。
  读端读库失败 ⇒ 关流（**不谎报**为正常结束）。
- **状态 `unavailable` 的告知**：熔断时**已落的告知帧优先**；悬挂兜底（不补写帧）则由读端**补发一帧** `stream.unavailable`（`is_terminal=true`）后关流。
- **错误语义**：未认证 `401`；`customer_admin`（非对话岗位）`403`；会话不存在 / 跨租户 / 他人会话 / 未知 run `404`；非法 `run_id` / `after_seq` / `Last-Event-ID` `422`；读端自身不可用 `503`。
  **归档会话可开流**（读语义同 `GET /conversations/{id}`）；向归档会话发消息仍 `409`。
  **2026-09-17（P2c-6）**：读路径 = 「**本人 ∪ 成员**」——被点名分享的成员可开流（其余 / 跨租户仍 `404`）。

### 帧 `kind` 取值域（冻结）与脱敏

| 类别 | 取值 | 说明 |
| --- | --- | --- |
| 消息 | `message.user` / `message.assistant` | 消息**落库后**写帧；payload 只含 `message_id` 与 `stub`，**不含正文** |
| 过程 | `plan.created` / `step.started` / `tool.call` / `tool.result` / `approval.requested` / `approval.decided` / `checkpoint.saved` / `run.paused` / `run.failed` / `run.completed` | 复用既有 `RuntimeEventType` **十种原值**（不另起一套） |
| 系统 | `stream.unavailable` | 熔断 / 写失败 / 悬挂兜底的**显式告知**帧（`is_terminal=true`；payload `reason` 为受控枚举 `frame_limit` / `byte_limit` / `write_failed` / `stalled`） |

**脱敏硬要求**：一切帧 `payload` **写入前**过 `redact_payload`（同一函数同一规则；掩码幂等）；
`tool.result` 帧含 `status` + 摘要 + `args_digest` + `sha256`（与 `027` 落库口径一致）**＋ 有界摘录字段**（见下节；
2026-09-17 修订（P2c-2）），**不含** stdout 全文、文件正文、宿主真实路径、凭据 / 认证头 / Cookie；`message.*` 帧**不落正文**。

### 内容级回传：执行输出与文件变更（**有界摘录** · 2026-09-17 P2c-2 新增）

> **边界修订留痕**：原「工具结果只落摘要，永不落内容」的绝对口径**修订为「有界摘录」**（Q9 修订）——
> **仍不落全文、不落二进制、不进审计、不进消息表**；`027` 密文列仍是唯一受控例外，其解密内容**不得外溢到帧**。

`tool.result` 帧 payload **只增**以下字段（无摘录可回传时不出现；字段缺失 ≠ 失败）：

| 字段 | 内容 |
| --- | --- |
| `output_excerpt` | `cmd.run` 的 stdout/stderr 与 `fs.read/list/stat` 的执行结果文本的**摘录**（UTF-8；按上限截断） |
| `output_truncated` / `output_bytes` | 是否被截断 + 本次**捕获输出**的字节数（截断**必须显式告知**） |
| `file_changes` | 文件变更数组 `[{"virtual_path","change_kind","bytes","sha256","diff_excerpt"?}]`（**P2c-3 起为真实数据源**：`fs.write/overwrite/delete` 执行时产出；`change_kind` ∈ `created` / `overwritten` / `deleted`；**最多 `WORKBENCH_FILE_CHANGES_MAX` 条/步**，超出**截断告知**） |
| `file_changes_truncated` | 变更条数被 `WORKBENCH_FILE_CHANGES_MAX` 截断时为 `true`（**只增**字段；**不出现 = 未截断**） |

**硬边界（不可协商）**：

1. **有界**：`WORKBENCH_OUTPUT_EXCERPT_MAX_BYTES`（默认 **16384**，范围 0–262144，**`0` = 关闭输出回传**——不读容器日志）；
   `WORKBENCH_FILE_DIFF_EXCERPT_MAX_BYTES`（默认 **8192**，范围 0–65536，**`0` = 不产出 `diff_excerpt`**，仍记 `bytes` + `sha256`）；
   `WORKBENCH_FILE_CHANGES_MAX`（默认 **50**，范围 0–200，**`0` = 关闭变更通道**——不解析变更标记、不登记产物）。
2. **非文本不回传**：非 UTF-8 / 二进制**只留** `bytes` + `sha256`（不落内容）。
3. **脱敏**：摘录一律过 `redact_payload`（键名 + 值形状；掩码幂等）；**宿主真实路径不得出现**（只用虚拟路径）。
4. **不进审计、不进消息表**：审计仍为最小集（`tool.executed` 明细键不变）；消息仍为 U23 摘要。
5. **保留期随帧（7 天）**；帧字节熔断（4 MiB/run）**继续生效**——大输出会更快触熔断（见下节，运维可调）。
6. **回传失败 / 超限不影响执行结果**（流是视图，绝不阻断或改变执行语义）。
7. **`fs.*` 语义以「工作卷随容器即毁」为前提（P2c-3）**：每次工具执行 = **独立容器 + 空工作卷**（tmpfs，运行结束销毁；容器边界见「工具执行（P2a 段二）」）——
   `fs.write` = **新建**（目标已存在 ⇒ 拒绝，不覆盖）；`fs.overwrite` = **覆盖语义写入**（目标存在 ⇒ 替换并记 `overwritten`；不存在 ⇒ 新建并记 `created`）；
   `fs.delete` = **幂等删除**（目标存在 ⇒ 删除并记 `deleted`；不存在 ⇒ 成功且**不产出变更记录**——不伪造变更）；
   `fs.read` 对非 UTF-8 / 二进制内容**只回一行摘要**（字节数 + sha256），不落内容。
   **文件不跨执行留存**（工作卷随容器销毁）⇒「产物」= **登记记录（元数据）**，不是可回读的文件副本；`fs.read/list/stat` 只能读**本次执行内**的文件。

### 保留期 · 熔断 · 悬挂 · 清理

- **保留期**：`WORKBENCH_STREAM_RETENTION_DAYS`（默认 **7 天**，范围 1–90）；**终态**时置 `expires_at = now() + 保留期`
  （**比运行事件的 30 天短**：流是体感数据、帧量大）。
- **双上限熔断**（每 run）：`WORKBENCH_STREAM_MAX_FRAMES`（默认 2000）/ `WORKBENCH_STREAM_MAX_BYTES`（默认 4 MiB）。
  超限 ⇒ **停止写后续帧** + 状态置 `unavailable` + **追加一帧显式告知**（`stream.unavailable`，终态）
  + 审计 `conversation.stream.unavailable`（明细 `{reason, run_id}`，**受控枚举，不落正文**）；**执行继续**（流是视图）。
  **不静默丢帧**。
- **写失败**：帧写入异常 ⇒ 尽力置 `unavailable('write_failed')` + 审计；**不得**阻断或改变执行结果。
- **悬挂兜底**：`status='streaming'` 且 `updated_at < now - WORKBENCH_STREAM_STALLED_HOURS`（默认 6h）⇒ 置 `unavailable('stalled')` + `expires_at`（**不补写帧**，由读端按状态告知）。
- **清理任务**（worker 周期 `conversation-stream-purge`，间隔 `WORKBENCH_STREAM_PURGE_INTERVAL_SECONDS` 默认 3600s）：
  先做悬挂兜底，再删除 `expires_at < now` 的 run 的**全部帧行 + 状态行**；**逐租户**执行（带 `tenant_id`）；
  **只清流帧**——消息表 / 审计 / 运行事件**不受影响**；清理**不写审计**（例行维护，与运行事件清理同口径）。
  序号**不复用**（清理后该 run 不再追加）。
- **已知限制**：~~审批决议后的推进过程事件**本期不做**~~（**2026-09-17 修订（P2c-2）**：已纳入，见上「审批分支」）；
  反代缓冲行为与长连接资源画像**未在 staging 实测**（`X-Accel-Buffering: no` 已预置）；多副本下的 SSE 路由语义属部署配置范畴。

### 产物登记与只读端点（**P2c-3 新增** · 2026-09-17）

> **性质**：产物登记 = **运行级的元数据登记**（虚拟路径 / 变更类型 / 字节 / sha256 / 时间），**不是**文件副本、**不含内容**；
> 保留期比帧长（**30 天**），供跨运行查询；**不进审计、不进消息表**（口径同「内容级回传」）。

`GET /api/v1/runs/{run_id}/artifacts`

只读列出本运行的产物登记。**归属判定与运行接口一致**（本人 / `ceo` / `super_admin`；跨租户 / 不可见 / 未知运行一律 `404`，不泄露存在性）。**2026-09-17（P2c-6）**：**会话成员可见**（承载任务不可见时用同一成员判定兜底）。
返回 `{"run_id": string, "items": [{"artifact_id", "virtual_path", "change_kind", "bytes", "sha256", "created_at", "expires_at"}], "total": int}`；
**不返回** `tenant_id`、宿主真实路径、文件内容。**保留期已到（`expires_at <= now`、尚未被周期任务清理）的条目不再返回**（保留期外如实降级，不静默延长）。

- **保留期**：`WORKBENCH_RUN_ARTIFACT_RETENTION_DAYS`（默认 **30**，范围 1–365）；登记时置 `expires_at = now() + 保留期`。
- **清理任务**（worker 周期 `run-artifacts-purge`，间隔 `WORKBENCH_RUN_ARTIFACT_PURGE_INTERVAL_SECONDS` 默认 3600s，范围 60–86400）：
  **逐租户**删除 `expires_at < now` 的行；清理**不写审计**（例行维护，与流帧 / 运行事件清理同口径）；**只清登记表**——帧、消息、审计、运行记录**不受影响**。
- **写入（唯一入口）**：**工具执行链路**在 `fs.write` / `fs.overwrite` / `fs.delete` 产生变更时逐条登记（一条变更 = 一行，`artifact_id` 服务端生成）；
  **登记失败不影响执行结果**（与回传同为「视图」，失败只记日志）。

## P2c 对话模式 · 导出与物理删除 · 候选端点 · 结构判定（P2c-4 · 2026-09-17）

> 口径：`docs/superpowers/specs/2026-09-17-frontend-interaction-p2c-design.md` §2.5 / §2.9 / §2.10 / §2.11（**已评审 2026-09-17**；迁移 `038_conversation_mode_and_soft_delete`）。
> **零破坏声明（可验证）**：`mode` 列带 `DEFAULT 'craft'` ⇒ 存量会话行为与改造前**逐字一致**；会话视图**只增** `mode`；
> 既有 `POST .../messages`、`.../messages:stream`、归档端点与全部状态码分支**不变**（`ask` / `plan` 只**收紧**，不放松任何既有判定）。

### 每会话模式（`ask` / `plan` / `goal` / `craft`）

- **落库**：`workbench_conversations.mode TEXT NOT NULL DEFAULT 'craft' CHECK (mode IN ('ask','plan','goal','craft'))`；**存量会话一律 `craft`**（不回填其它值）。
- **语义与合成（只收紧、不放松）**：

| 模式 | 语义 | 与自治三档 / 既有判定的合成 |
| --- | --- | --- |
| `ask` | 只问答：**拒绝一切真实执行**（问答与「缺键桩路径」不受影响） | **覆盖（最严）**：发起与推进**两处**受控拒绝 + 审计 |
| `plan` | 先计划后执行：**一律先落待批** | 强制 `requires_approval=true`（等价 `approval_for_all`）；**不放松** `critical` 仅 CEO/超管 |
| `goal` | 目标驱动：执行照常 | 不放松（按自治三档） |
| `craft` | 完整执行（**默认**，＝现状） | 不放松（按自治三档） |

- **判定在服务端、两处生效（fail-closed）**：
  - **发起**（`POST /api/v1/conversations/{conversation_id}/messages` 与 `.../messages:stream` 的**带 `Idempotency-Key`** 路径）：`ask` ⇒ **`409`**「该会话为只问答模式，已拒绝执行」+ 审计 `conversation.execution.rejected`（明细 `conversation_id` / `mode` / `reason`，受控枚举）；**不创建承载任务 / 运行 / 消息**（按幂等口径写 `rejected` 行，重放返回同一 `409`）。缺键桩路径**不受影响**（问答可用）。
  - **推进**（`POST /api/v1/runs/{run_id}/approvals/{approval_id}/approval`）：会话模式为 `ask` ⇒ 决议**整体拒绝**（`409`，**不落决议、不重跑**，待批动作保持 `pending`——切回模式后可再决议）；`plan` 的「强制待批」在发起处已生效，推进**只可能经「已批准」动作**（`find_approved` fail-closed `409`），故 `plan` 在推进处**天然不放松**。
  - **已知边界（如实登记）**：会话内容物理删除后，运行与待批动作按保留口径**继续可决议**（模式判定无可关联会话 ⇒ 不拦截）；但已删除会话**不得**再发起执行（`404`）。
- `POST /api/v1/conversations/{conversation_id}/mode`：改模式。请求体 `{"mode": "ask"|"plan"|"goal"|"craft"}`（未知字段 / 非法取值 `422`）。**仅会话本人**（他人 / 跨租户一律 `404`）；**归档会话 `409`**（沿用「归档不可再写」口径）。成功 `200` 返回会话视图（含 `mode`）；**设为同一值 = 无副作用**（不写审计，仍 `200`）。审计 `conversation.mode.changed`（明细 `conversation_id` / `from_mode` / `to_mode`，**受控枚举、不落自由文本**）。
- 其余会话视图（详情 / 归档）**只增** `mode`；`GET /api/v1/conversations` **不新增**模式过滤参数（本期）。

### 个人数据导出（本人）

`GET /api/v1/conversations/exports/mine?limit=&offset=`

- 返回**本人**（`operator_id` = 当前用户）的全部**未删除**会话（含归档）及其消息；**不含**他人数据、**不含**审计明细、**不含** `operator_id` / `dsh_session_id`。
- **如实说明**：用户原始输入自 U23 起只落**脱敏摘要**——导出返回的是**库中实际存在的字段**，不是原文重放。
- 分页：页单位为**会话**（`created_at` 降序），`limit` 1–500（默认 500）、`offset` ≥ 0。响应：
  `{"exported_at", "limit", "offset", "conversations": [{"conversation_id","agent_key","title","status","mode","created_at","updated_at","messages":[{"message_id","role","content","stub","tool_name","tool_call_id","created_at","sender_id"}],"messages_total"}], "total_conversations", "total_messages", "truncated", "limit_reason"}`。
- **规模上限（不静默截断）**：本人在库条目（**会话数 + 消息数**）合计超过 **50000** ⇒ `truncated=true` + `limit_reason="total_items_exceeded"`（本次只返回上限内的条目；用户按页继续导出）。单页装配同样受该上限保护。
- **2026-09-17（P2c-6）**：导出条目里的消息**只增** `sender_id`（与 `messages[]` 同一口径：`user` 为发言账号 id、助手 / 工具 / 系统恒 `null`、存量行 `null`）——导出的仍是**库中实际存在的字段**。
- 权限：仅对话岗位（`customer_admin` `403`；未认证 `401`）。审计 `conversation.exported`（明细 `conversation_count` / `message_count` / `truncated`，**不落正文**）。

### 物理删除（本人 · 同步 · 幂等）

`POST /api/v1/conversations/{conversation_id}/delete`

- **仅本人**；跨租户 / 他人 / 不存在一律 `404`；**复删幂等**（已删除会话再次调用仍 `200`，**不重复删除、不重复写审计**）。
- **真删内容行（固定顺序、每步各自原子、可重试）**：`workbench_execution_idempotency`（该会话全部键，**先删**——它同时引用消息行与会话行，必须先于消息行）→ `workbench_conversation_stream_frames` + `workbench_conversation_stream_state` → `workbench_conversation_messages` + **会话行软删**（消息删除与「置 `deleted_at` / `title=''`」在**同一事务**内完成）。
  失败语义：任一步失败 ⇒ 接口返回错误（`5xx`），**会话在最后一步完成前保持可见**（不会出现「看不见但内容还在」）；各步均可安全重试（重复删除不报错、不产生负面效果）；帧清理失败**不回滚**删除结果（孤儿帧由既有保留期清理兜底，且已不可见）。
- **会话行不物理删**：置 `deleted_at`（软删）+ **标题清空**（`title=''`）；此后**列表 / 详情 / 流 / 发消息 / 改模式**一律 `404`（与「不存在」不可区分）。
- **保留（不删）**：运行记录、待批动作、审计、产物登记（运行级、仅元数据）。
- 成功 `200`：`{"conversation_id", "deleted": true, "message_count", "frame_count", "stream_state_count", "idempotency_count"}`（复删各计数为 `0`）；审计 `conversation.deleted`（明细为上述四个计数 + `conversation_id`，**不含正文**）。
- **无管理端代删 / 批量删**；租户级导出 / 删除仍走既有租户生命周期口径（不变）。

### 模型 / 工具候选端点（**推翻 Y1**，见「本节开口的决议」）

两个端点均**只读**、**仅 `super_admin`**（其他角色 `403`）、**不返回任何凭据 / 内部地址 / 提示词**。

- `GET /api/v1/workforce/model-candidates` → `{"items": [model_key...], "total": n}`：`registered_model_keys(settings)`（与员工配置保存闸门**同一来源**）。候选**为空** = 本部署未注册模型键（`WORKBENCH_PLANNER_MODEL_NAME` 未配置）——界面如实告知「只能使用默认模型」。
- `GET /api/v1/tools/catalog` → `{"items": [{"tool_key","risk_level","requires_approval","has_side_effect","reversible","params":[{"name","role"}]}...], "allowlist": [tool_key...], "total": n}`：
  - `items` = **执行工具目录**（`ToolSpecCatalog`，与执行入口**同一实例语义**）；
  - `allowlist` = 员工配置 `tool_allowlist` 的**保存闸门集合**（`WORKBENCH_PLANNER_TOOLS` 声明的键）；**保存仍以服务端校验为准**（不在该集合内的键一律 `422`）——前端据此**灰显并给原因**，不改变后端校验；目录内不在闸门集合的键**如实标注不可用原因**。
- 既有 `GET /api/v1/workforce/candidates`（岗位 / 员工候选）行为**不变**（两者不同物，勿混用）。

### 运行结构判定（自动验收 · **不调模型** · **不改运行状态**）

`GET /api/v1/runs/{run_id}/acceptance`

- 归属判定同运行接口（跨租户 / 不可见 / 未知运行 `404`）；**纯读**：**不调模型、不写库、不改运行状态**。**2026-09-17（P2c-6）**：**会话成员可见**（承载任务不可见时用同一成员判定兜底）。
- **结构判定**（三条件**全满足** ⇒ `met`）：① 步骤全部完成（`completed_step_count >= step_count`；`step_count = 0` 视为满足）② 无未决审批（运行审批状态无 `pending`）③ `finish_reason` 为**正常终态**（`run_completed`；`cancelled_by_user` / `step_failed` / `approval_rejected` 均**不算**）。
- 响应 `{"run_id", "verdict": "met"|"unmet", "checks": {"steps_complete", "no_pending_approvals", "finish_reason_ok"}, "steps": {"completed", "total"}, "pending_approvals", "finish_reason", "status"}`；**非终态运行 ⇒ `unmet`**（如实，不谎报）。
- **一键重做属前端行为**：未达标时，**仅当页面仍持有原结构化调用**时以**新幂等键**重发（＝一次新的正常调用、新 run，与原运行**无状态耦合**）；跨页 / 刷新后按既有安全口径**不重放原参数**（界面如实告知「原始参数未留存，请重新输入」）。**不做自动重跑、不做 LLM 判分**。

### 干预动作的终态口径（2026-09-18 收紧 · M3/S4 收口）

`POST /runs/{run_id}/pause` · `POST /runs/{run_id}/resume` · `POST /runs/{run_id}/cancel`

- **仅非终态运行可干预**：`completed` / `failed` / `cancelled` **一律 `409`**（`运行已结束，无法暂停 / 恢复 / 取消`）。
  理由与审批侧 `RunNotDecidable` 同一原则——**终态即终态**：把已完成置回「运行中」、把已取消再暂停，
  都会让指标与审计口径失真（此前三条动作在终态上会被静默接受并改写状态，属**存量缺陷**，本批修掉）。
- **权限与可见性不变**：任务创建人 / `ceo` / `super_admin`；越权与跨租户一律 `404`（不泄露存在性）。
- `POST /runs/{run_id}/resume` 另外把授权闸门的拒绝（`ExecutionNotAuthorized`）映射为 **`409`**（原来会外抛 `500`）。
- **已知限制（如实登记）**：`dsh` 适配器的 `pause_run` / `resume_run` 目前是**空操作**（无外部暂停契约），
  即在这条真实执行路径上「暂停 / 恢复」不会改变运行状态；界面按服务端回流展示，不会假装成功。

### 运行验收决议（S2 · 人工验收 · 2026-09-18）

> 口径源：`docs/superpowers/specs/2026-09-18-workbench-closed-loop-design.md` §3 接缝 **S2**（「确认完成 / 打回重做（带原因）」）与 `docs/superpowers/specs/2026-09-18-workbench-ui-v2-design.md` §6（M3 范围）。**结构判定是机器结论，验收决议是人的结论**：本组端点只记录「人怎么判的」，**不改运行状态、不触发重跑、不发通知**。

**迁移**：`040_run_acceptance_decisions`，表 `workbench_run_acceptance_decisions(tenant_id, run_id, decision_id, decision, reason, idempotency_key, decided_by, decided_by_role, structural_verdict, created_at)`；主键 `(tenant_id, run_id, decision_id)`；**复合外键** `(tenant_id, run_id) → workbench_run_records`（跨租户写直接拒）；唯一 `(tenant_id, idempotency_key)`；表级 CHECK：`decision ∈ {confirmed, rejected}` 且 `rejected ⇒ length(reason) > 0`。**append-only**（历史保留：打回 → 重做 → 再确认的序列可追溯）；**不设保留期**（验收是合规记录，与运行记录同寿命）。

`POST /api/v1/runs/{run_id}/acceptance/decisions`

- 请求体（`extra=forbid`）：`{"decision": "confirmed"|"rejected", "reason": string, "idempotency_key": string}`。`reason`：`rejected` **必填**（1–500 字），`confirmed` 可省（缺省 `""`，≤500）；`idempotency_key` 必填（1–200）。
- **权限**：承载任务的**创建人**或 `ceo` / `super_admin`；其余身份（含**非成员**、跨租户、未知运行）一律 **`404`**（与运行控制类端点同一收敛口径：不区分「无权限」与「不存在」，避免探测）。**按钮隐藏不算权限**——服务端独立判定。
- **前置**：仅**终态运行**（`completed` / `failed` / `cancelled`）可决议；非终态 ⇒ **`409`**（如实拒绝，不排队等待）。
- **幂等**：同租户同 `idempotency_key` 重复提交 ⇒ **返回既有决议**（`200`，`created: false`，**不重复写审计**）。
- 响应：`{"run_id", "decision_id", "decision", "reason", "decided_by", "decided_at", "structural_verdict": "met"|"unmet", "created": bool}`。
- **达标与否都可决议**：`structural_verdict` 只是记录当时的机器结论（**供追溯**），不作为放行条件——人可以在未达标时确认完成（例如「我知道差一步，就这样吧」），也会在达标时打回（例如「结果不对」）。
- **审计**：动作 `run.acceptance_decided`（受控键），明细只记 `decision` / `structural_verdict` / `reason_present`（**不落理由正文**；正文只进本表并由有权读者读取）。
- **不做**：不改运行状态、不自动重跑（「一键重做」仍属前端行为，见上）、不发通知（下游「待确认」看板属 C2，未立项）、不做批量决议。

`GET /api/v1/runs/{run_id}/acceptance/decisions`

- 决议历史（**最新在前**）：`{"run_id", "items": [{"decision_id","decision","reason","decided_by","decided_at","structural_verdict"}], "latest": {...}|null, "promotion": {...}|null}`；`items` **不含** `tenant_id` / `idempotency_key`。
- 归属同运行级**读**路径（含会话成员可见口径，与 `/acceptance` 一致）。
- **`promotion`（2026-09-19 只增）**：该运行的沉淀状态（见下节）；未沉淀为 `null`，已沉淀为 `{"task_id","title","promoted_by","promoted_at"}`（**不含** `tenant_id`）。

### 运行沉淀（S2 · 存成任务 · 2026-09-19）

> 口径源：`docs/superpowers/specs/2026-09-18-workbench-closed-loop-design.md` §3 接缝 **S2**——「确认后出现「**存成任务 / 设为自动化**」（B5 的轻量入口，完整画布见 C3）」。本节交付**「存成任务」**；**「设为自动化」不在此列**（自动化调度属能力项 C2/C3，未立项，界面只给行内说明、不摆按钮）。

**迁移**：`042_run_promotions`，表 `workbench_run_promotions(tenant_id, run_id, task_id, title, promoted_by, created_at)`；**主键 `(tenant_id, run_id)`**（一个运行只能沉淀一次）；**复合外键** `(tenant_id, run_id) → workbench_run_records`（跨租户写直接拒）且 **`ON DELETE CASCADE`**（运行记录被删只解除链接，**任务不随之消失**）；**不设保留期**。

**语义**：沉淀是**链接**，任务是**产物**——新任务落既有任务仓储，字段从**这次运行的承载任务**复刻（执行员工 / 风险档 / 预算 / 项目），并由服务端**再走一次同款治理闸门**（`ensure_can_create` 与 `task_requires_approval`），因此「沉淀」不是绕过审批或预算的旁路。

`POST /api/v1/runs/{run_id}/acceptance/tasks`

- 请求体（`extra=forbid`）：`{"title": string}`（1–120 字，去首尾空白；**只有标题可由客户端给**）。
- **权限与验收决议同一判定**（承载任务创建人 / `ceo` / `super_admin`）：他人 / 跨租户 / 未知运行一律 **`404`**。
- **前置（fail-closed）**：① 仅**终态运行**（非终态 ⇒ **`409`**「运行尚未结束，暂不能沉淀成任务」）；② 最新验收决议必须是 **`confirmed`**（未决议 / 已打回 ⇒ **`409`**「先确认完成，再沉淀成任务」）。
- **幂等**：同一运行**只能沉淀一次**——服务端先占位（主键）再建任务；重复提交返回**既有任务**（`200`，`created: false`），**不建第二条任务、不重复写审计**；并发提交由主键拒绝，只有一个能占到。
- **闸门**：`ensure_can_create` 被挡 ⇒ **`403`**（原样返回策略文案）；任务侧幂等冲突 ⇒ **`409`**；两种失败都会**归还占位**（不留下悬挂链接）。
- 响应：`201`（首次）/ `200`（重复）`{"run_id", "task_id", "created": bool, "promotion": {...}, "task": <TaskView>|null, "task_created"?: bool}`——`task` 在承载任务对调用者**不可见**时为 `null`（界面只给标识，**不编造内容**）。
- **审计**：动作 `run.promoted_to_task`（受控键），明细**只记 `task_id`**（**不落标题正文**；标题只进本表作快照）。
- **不做**：不自动运行该任务、不建调度（自动化）、不改原运行状态、不发通知；删除任务仓储中的任务**不会**回写本表（沉淀是历史事实）。**平任务的列表 / 详情页属任务中心（C2）未立项** ⇒ 界面只给任务编号与如实说明，**不摆「打开任务」按钮**（点了只会落到空页面）。

## 会话协作：分享与多端协同（P2c-6 · 2026-09-17）

> 口径源：`docs/superpowers/specs/2026-09-17-frontend-interaction-p2c-design.md` §2.16（已评审 2026-09-17）。本批**推翻** P1 / P2b §1.3-8 的「不做会话分享与多端协同」；**保留**「不做实时在线态 / 不做协同编辑」（无 WebSocket 底座，消息 append-only）、「不做部门级 / 全租户 / 跨租户分享与公开链接」。
> **实现期裁定（2026-09-17，写入规格 §2.16）**：① 归档会话加 / 撤成员 ⇒ `409`（与「改模式」同口径：归档不可再写管理动作）；② `GET .../members` 的 `items` **含发起人**（`is_owner: true` / `permission: "owner"`，列首位、不可撤销）——参与者列表与消息发言者归属由此统一解析；③ 「最近活动时间」= 会话 `updated_at`（成员表**不**建活动时间列，不做在线态）；④ `read` 成员发言 ⇒ `403`（可读即不隐藏存在性），**非成员且非本人** 仍 `404`；⑤ 运行级**读**路径（`/runs/{id}/metrics`、`/events`、`/acceptance`、`/artifacts`、`/approvals`）成员可见——经「运行 → 会话（幂等行反查）→ 成员判定」的**同一读可见性辅助**放行，**控制类（pause / resume / cancel / 决议）不放松**。

**成员表（迁移 `039_conversation_members`）**：`workbench_conversation_members(tenant_id, conversation_id, member_id, permission, added_by, created_at)`；主键 `(tenant_id, conversation_id, member_id)`；复合外键引用 `workbench_conversations(tenant_id, conversation_id)`（**`ON DELETE CASCADE`**：会话行真删时成员行随之清理；生产路径的「物理删除」只软删会话行，不触发本级联）；`permission` 受控枚举 `read` / `write`（表级 CHECK）。成员必须**同租户、已审批、非 `customer_admin`**。

**可见性（唯一新增授权轴）**：
- **读路径统一为「本人 ∪ 成员」**：会话列表 / 详情 / 消息 / 帧流 / **运行概览**（`/runs/{id}/metrics`、`/events`、`/acceptance`、`/artifacts`）/ **审批**（`/runs/{id}/approvals`）；`ceo` / `super_admin` 既有只读口径**不变**（**未被点名就不是成员**，不因角色自动可见他人会话）。
- **写路径**：发言（含结构化调用与 `messages:stream`）＝**本人 ∪ `write` 成员**；归档 / 改模式 / 物理删除 / 增删成员**仍仅本人**（被分享者的管理动作一律 `404`，与「不属于本人」同口径——不区分「无权限」，避免探测）。
- **非成员口径的已知差异（如实）**：运行级读端点中 `/runs/{id}/events` 对「非发起人且非成员」沿用既有 `403`，其余四个（`metrics` / `acceptance` / `artifacts` / `approvals`）为 `404`；两者**本批均不改**。

**消息 `sender_id`（**只增**，可空）**：`messages[]` 只增 `sender_id`（发言账号 id；**助手 / 工具 / 系统消息恒 `null`**）；**存量行 `NULL` ⇒ 展示回退为「发起人」，零破坏**（不回填）。发言审计 `conversation.message.sent` 的 `actor_id` = **发言者本人**（明细键不变，**不含** `sender_id` / 正文）。

- `POST /api/v1/conversations/{conversation_id}/members`：添加成员。**仅会话本人**（他人 / 跨租户 `404`；未认证 `401`；`customer_admin` `403`）。请求体 `{"member_id": string, "permission"?: "read"|"write"}`（`permission` 缺省 `read`；未知字段 `422`）。**成员不合法**（未知账号 / 跨租户 / 未审批 / `customer_admin`）⇒ `422`。**幂等**：已存在且权限相同 ⇒ `201` 且**不重复写审计**；权限不同 ⇒ 以新权限覆盖并写审计。归档会话 `409`。成功 `201` 返回 `{"conversation_id","member_id","permission"}`。审计动作 `conversation.member.added`（明细：`conversation_id` / `member_id` / `permission`，**不含正文 / 姓名 / 手机号**）。
- `GET /api/v1/conversations/{conversation_id}/members`：**本人或成员可见**（`ceo` / `super_admin` 既有只读口径不变，同样可读；他人 / 跨租户 `404`）。**分页**：`limit` 1–200（默认 **200**）+ `offset` ≥ 0（默认 0），非法值 `422`；**不静默截断**——`items` 恒为分页后的一页，`total` 恒为**命中总数**（客户端据 `total` 与 `items.length` 判断还有下一页）。返回 `{"items":[{"member_id","display_name","role","permission","is_owner","added_by","created_at"}...],"total","limit","offset"}`——发起人为首项（`is_owner: true` / `permission: "owner"`，`added_by` 为 `null`）；`display_name` 由账号解析（账号缺失 ⇒ 回退 `member_id`，**不编造**）；`role` 取账号当前角色（缺失 ⇒ `null`）。**2026-09-18 修订（P2c-6 收尾裁决 B）**：补分页（原设计无 `limit` / `offset`，与「列表必须分页」的红线口径对齐）；`limit` / `offset` 为响应**只增**字段，`items` / `total` 语义不变。
- `DELETE /api/v1/conversations/{conversation_id}/members/{member_id}`：撤销成员。**仅会话本人**（他人 / 跨租户 `404`）。成功 `204`；**复删 / 目标不是成员（含发起人）一律 `204`（幂等 no-op，不重复写审计）**。审计动作 `conversation.member.removed`（同受控键）。**已读内容不可撤回**（如实告知，不做「收回」语义）。
- **发言与执行（`write` 成员）**：可发言（含结构化调用）并触发执行——**一律以其本人身份**走既有全部闸门（工具白名单 / 自治三档 / 审批 / `critical` 仅 CEO·超管 / **发起人不得自审**）；`read` 成员发言 ⇒ `403`（不做任何落库 / 执行 / 幂等写入）。
- **边界**：跨租户 / 部门级 / 全租户 / 公开链接**均不做**；成员**不得**归档、改模式、删会话、增删成员；**不做实时在线态**（参与者列表 + 最近活动时间为**非实时**呈现）。


