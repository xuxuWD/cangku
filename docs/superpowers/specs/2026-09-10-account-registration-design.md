# 账号注册审批与登录设计

## 目标

为工作台引入自建账号体系：员工提交注册申请，管理员审批并指定角色与归属租户，审批通过后才能登录；首个管理员凭部署注入的 bootstrap 口令自助建立。本轮同时提供本人修改密码和管理员重置密码。

本设计只覆盖账号、注册审批和登录会话，不改变任务、权限策略、知识和商业化领域逻辑，也不引入设备绑定或第三方统一登录。

## 当前问题

`app/auth.py` 只提供无过期的 HMAC 签名令牌，`app/main.py` 在生产模式接受该令牌，但仓库内没有任何账号来源：既无账号表，也无注册、审批和登录流程。README 要求的“统一登录、短期会话”尚未落地，生产环境无法安全地产生受控身份。

## 决策记录

| 议题 | 结论 |
| --- | --- |
| 登录来源 | 自建账号，不用 OIDC/SSO |
| 密码存储 | 只存 scrypt 哈希，绝不存明文；密码哈希不进响应、事件和日志 |
| 登录标识 | 手机号，部署内全局唯一 |
| 首个管理员 | 凭部署注入的 bootstrap 口令自助申请，角色强制为超级管理员 |
| 职位 | 仅展示信息，不参与鉴权 |
| 角色 | 由管理员在审批时指定 |
| 归属租户 | 普通申请由管理员在审批时指定；首管理员申请时自行声明 |
| 修改密码 | 本人修改必须验证原密码 |
| 忘记密码 | 由管理员重置 |
| 设备绑定 | 本轮不做 |
| 账号状态 | 只保留 `pending`、`approved`、`rejected`；不做禁用/吊销 |

## 方案

新增独立的账号领域模块，与现有控制平面解耦：

- 账号仓储负责账号的创建、按手机号查询、状态流转和审批留痕；开发环境使用内存实现，PostgreSQL 模式使用持久化实现，沿用 `bootstrap.py` 的装配方式。
- 账号服务负责注册申请、审批、登录校验、改密和重置，不直接依赖具体存储实现，只依赖最小仓储接口。
- 密码模块只暴露哈希与校验两个函数，调用方拿不到哈希算法细节。
- 会话沿用现有 HMAC 签名模式，增加过期时间和签发时间；不新增签名库。
- 接口层只做参数校验、身份解析和错误映射，业务规则留在服务层。

不采用“首个申请者自动成为管理员”，避免匿名抢注；不在本轮引入服务端会话撤销表，避免把认证路径绑到数据库。

## 组件与接口

### 账号模型

新增 `app/accounts/models.py`：

- `AccountStatus`：`pending`、`approved`、`rejected`。
- `Account`：`account_id`、`phone`、`password_hash`、`position`、`full_name`、`email`、`role`、`tenant_id`、`status`、`requested_at`、`reviewed_at`、`reviewed_by`、`rejection_reason`。
- 账号的 `tenant_id` 和 `role` 在审批通过时写入；`pending` 状态下两者为空。

### 仓储

`app/accounts/repository.py` 定义最小接口并给出内存实现：

- `add_request(account)`：写入申请；手机号已存在时抛出冲突错误。
- `find_by_phone(phone)`：登录与重复校验使用。
- `get(account_id)`：审批使用。
- `list_by_status(status)`：管理员查看申请列表。
- `update(account)`：审批、改密、重置使用。

PostgreSQL 实现使用 `migrations/008_accounts.sql` 新建 `workbench_accounts` 表，`phone` 上建唯一约束；查询与更新都带状态条件，避免并发下重复审批。跨租户或不存在账号统一表现为不存在，不泄露存在性。

### 密码

`app/accounts/passwords.py`：

- `hash_password(password)`：使用标准库 `hashlib.scrypt` 加随机盐，输出可自描述字符串 `scrypt$n$r$p$salt$hash`。
- `verify_password(password, encoded)`：解析参数后重算并用 `hmac.compare_digest` 恒定时间比较，任何解析失败都返回失败而不是抛异常。
- 口令长度 10–128；为空、超长或含控制字符直接拒绝。

### 服务

`app/accounts/service.py` 的 `AccountService`：

- `request_registration(payload, bootstrap_token=None)`：校验手机号与口令策略；若系统中尚无已通过的管理员，则必须携带正确的 bootstrap 口令且在申请中声明 `tenant_id`，否则拒绝；首管理员角色固定为超级管理员、状态直接 `approved`；普通申请状态为 `pending`，`role` 与 `tenant_id` 留空，且普通申请携带的 `tenant_id` 与 `role` 一律忽略；手机号重复返回冲突提示。
- `list_requests(actor, status)`：仅超级管理员可调用。
- `approve(actor, account_id, role, tenant_id)`：仅超级管理员可调用；只允许 `pending`，写入角色与租户，重复审批返回冲突。
- `reject(actor, account_id, reason)`：仅超级管理员可调用；只允许 `pending`。
- `login(phone, password)`：校验口令与状态；手机号不存在、口令错误或状态非 `approved` 一律返回同一种失败，不区分细节，避免账号枚举；成功返回身份上下文。
- `change_password(actor, old_password, new_password)`：验证原密码后再更新。
- `reset_password(actor, account_id, new_password)`：仅超级管理员可调用，用于忘记密码。

### 会话

扩展现有 `app/auth.py`：令牌载荷增加 `exp`、`iat`、`jti`；`create_access_token` 增加必填的 `ttl_seconds` 参数用于计算过期时间，`auth.py` 本身不读取配置，由调用方传入 TTL，保持该模块纯函数、便于测试；`verify_access_token` 校验签名与过期，过期、缺 `exp` 或签名错误统一抛出无效错误。现有调用点同步更新。

`app/main.py` 的 `current_user`：

- 非开发环境：只接受 Bearer 会话令牌，校验签名与过期。
- 开发环境：继续支持 `X-Tenant-Id`、`X-User-Id`、`X-User-Role`，同时接受会话令牌，便于本地自测。

### 接口

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| `POST` | `/api/v1/auth/registrations` | 匿名 | 提交注册申请，首个管理员需携带 bootstrap 口令并声明 `tenant_id` |
| `GET` | `/api/v1/auth/registrations` | 超级管理员 | 按状态查看申请列表，默认 `pending` |
| `POST` | `/api/v1/auth/registrations/{account_id}/approval` | 超级管理员 | 通过并指定 `role` 与 `tenant_id` |
| `POST` | `/api/v1/auth/registrations/{account_id}/rejection` | 超级管理员 | 驳回并记录原因 |
| `POST` | `/api/v1/auth/sessions` | 匿名 | 手机号与密码换取会话令牌 |
| `PUT` | `/api/v1/auth/me/password` | 已登录 | 修改本人密码，必须提供原密码 |
| `POST` | `/api/v1/auth/accounts/{account_id}/password` | 超级管理员 | 重置他人密码 |

响应视图只包含账号号、手机号（按需脱敏）、职位、姓名、角色、租户、状态和时间；不包含口令、口令哈希、bootstrap 口令或会话密钥。

## 配置

- `WORKBENCH_BOOTSTRAP_TOKEN`：首管理员自助申请所需的口令；未配置时禁止首管理员自助申请；系统中一旦存在已通过的管理员，该口令即不再生效。口令值只从部署环境读取，不写入响应或日志。
- `WORKBENCH_SESSION_TTL_SECONDS`：会话有效期，默认 `900`，允许范围 `60`–`3600`，越界时应用拒绝启动。
- 复用现有 `WORKBENCH_AUTH_SECRET`（非开发环境至少 32 字符）作为会话签名密钥。

## 错误与一致性

- 手机号重复：返回 `409`，提示“该手机号已提交申请或已注册”。
- 待审批或已驳回账号登录：返回 `401`，不区分具体原因，避免枚举。
- bootstrap 口令错误或缺失：拒绝首管理员申请，提示需要初始化口令。
- 非管理员调用审批、查看申请、重置密码：返回 `403`。
- 并发审批同一申请：条件更新受影响行数为零时返回冲突，不重复写入。
- 过期或签名错误的会话令牌：返回 `401`。
- 账号不存在：统一表现为不存在，不泄露账号是否申请过。

## 已知限制（本轮接受，不视为缺陷）

- 首管理员判定与写入不是单一原子操作：并发提交两个携带正确 bootstrap 口令的首管理员申请时，理论上可能产生多个已通过的超级管理员。触发前提是攻击者已掌握部署注入的 bootstrap 口令，届时其本就可建立管理员，因此本轮不引入额外的仓储原语；若后续要求强唯一，再补原子写入。
- 登录失败的时间开销不完全一致：手机号不存在或状态非 `approved` 时提前返回，不执行口令校验，理论上可通过响应耗时差异推断手机号是否为已通过账号。错误文案已统一，耗时差异本轮不做抹平。
- 注册接口未做限流，口令哈希的固定成本由调用方按部署需要自行加限流或网关保护。

## 测试验收

先新增或更新行为测试，再修改生产代码：

- 口令：哈希可校验、错误口令拒绝、同一口令两次哈希不同、超长或空白被拒、编码损坏时校验返回失败。
- 注册：重复手机号 `409`；无 bootstrap 口令或口令错误时首管理员申请被拒；配置正确口令后首管理员为 `approved` 且角色为超级管理员；普通申请为 `pending` 且不能登录。
- 审批：仅超级管理员可调用；通过后写入角色与租户且可登录；驳回后仍不可登录；重复审批冲突；跨租户读取返回不存在。
- 登录与会话：状态非 `approved` 拒绝；口令错误拒绝；成功返回令牌；过期令牌返回 `401`；被篡改令牌返回 `401`。
- 改密与重置：原密码错误拒绝；改密后旧密码失效、新密码可用；管理员重置后新密码可用；非管理员重置返回 `403`。
- 配置：`WORKBENCH_SESSION_TTL_SECONDS` 越界时应用启动失败。
- 脱敏：响应、事件与日志中不出现口令、口令哈希和 bootstrap 口令。
- 回归：现有后端测试全部通过；开发环境请求头流程不受影响。

真实统一登录、设备绑定、服务端会话撤销和 staging 验收不在本设计范围内，不据此宣称已上线。

## 交付物与文档同步

按仓库「每次提交必须满足」的约定，本设计同时交付以下文档变更：

- 更新 `docs/api-contract.md`：补入 7 个账号接口的路径、请求字段、状态码和脱敏约定，作为客户端的唯一依据。
- 更新 `README.md` 安全边界：明确区分“不保存第三方系统密码”与“自建账号只保存密码哈希、不存明文”，消除现有措辞的歧义。
- 更新 `docs/delivery-gates.md`：只勾选本轮真实完成的部分，不整体勾掉“统一登录、设备绑定和生产密钥管理”。
- 新增 `migrations/008_accounts.sql` 并保持迁移清单可核对。

## 非目标

- 不接 OIDC/SSO 或任何第三方登录。
- 不做设备绑定、设备注册或设备审批。
- 不做账号禁用、吊销或删除；如需收回权限后续单独设计。
- 不做服务端会话撤销表、登出即失效或并发会话限制。
- 不存储或上传第三方系统的密码、Cookie、验证码或会话快照。
- 不实现短信验证码、邮箱验证或找回密码自助流程；忘记密码走管理员重置。
- 不改变现有任务、知识权限、内容工作台和商业化接口契约。
