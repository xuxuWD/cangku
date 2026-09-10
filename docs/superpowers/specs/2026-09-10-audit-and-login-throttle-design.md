# 关键操作审计与登录限流设计

## 目标

补齐项目宪法中两项硬要求：

1. **第二章 2.2 与第八章**：关键操作（登录、权限变更、删除等）必须写入结构化日志，并有审计轨迹。
2. **第三章第一道防线**：登录限流——同一账号 5 分钟内错误超 5 次锁定。

做法是建立**一套跨模块共用的安全审计设施**，账号模块与计划模块共用同一张审计表与同一套脱敏规则；并在登录路径上按手机号实施失败计数与锁定。

## 当前问题

- `app/` 全库**没有任何日志设施**（无 `logging`、无结构化输出），关键操作不留痕。
- 账号模块的注册申请、审批、驳回、登录成功/失败、改密、重置都无审计。
- 计划模块的生成、审批、驳回、执行都无审计。
- 登录接口可被无限尝试，且每次失败都带固定的 scrypt 成本（约 16 MiB / 70ms），构成资源放大面。

两项均已登记在 `docs/delivery-gates.md` 的未完成项中；计划模块的审计在计划功能设计文档的「实现偏差记录」中明确要求「执行该遗留专项时一并纳入」。

## 决策记录

| 议题 | 结论 |
| --- | --- |
| 审计落点 | 数据库审计表 + 结构化 stdout 日志，**两条通道都写** |
| 审计表形态 | **单张跨模块通用表**，不使用各模块自建表（避免多套并行审计） |
| 审计范围 | 账号（注册申请/审批/驳回/登录成功/登录失败/锁定/改密/重置）+ 计划（生成/审批/驳回/执行） |
| 手机号落库 | 审计表存**脱敏手机号**并在已知账号时附 `target_id`；限流计数以**手机号 HMAC 哈希**为键，手机号不明文入库 |
| 锁定语义 | 5 分钟滚动窗口内累计 5 次失败 → 锁定 15 分钟；成功登录清零计数 |
| 锁定与枚举 | 计数按手机号统一执行（不区分账号是否存在），因此锁定返回 `429` 不泄露账号存在性 |
| 日志级别 | 复用既有 `WORKBENCH_LOG_LEVEL`；生产默认 `INFO`，不开 `DEBUG` |
| 脱敏 | 审计字段只由服务端按白名单构造，禁止口令、口令哈希、令牌、Cookie、密钥与模型原始响应 |
| 审计写入失败 | fail-closed：写入失败即抛出，不静默吞掉（内存模式不会发生） |

## 方案

新增 `app/audit/` 领域包，与既有控制平面解耦但被账号与计划模块共同依赖：

- `app/audit/models.py`：`AuditAction`（动作枚举）、`AuditRecord`（审计记录）。
- `app/audit/store.py`：`AuditStore` 协议 + `InMemoryAuditStore` + `PostgresAuditStore`，沿用 `bootstrap.py` 的装配方式。
- `app/audit/logging.py`：`configure_audit_logging(settings)`（幂等的 JSON 格式化器安装）+ `emit_audit_line(record)`（把审计记录以单行 JSON 写到 stdout）。
- `app/audit/service.py`：`AuditService.record(action, *, actor_id, tenant_id, target_type, target_id, phone_masked, detail)`，先写仓储再写日志；两者都失败才抛出。

新增 `app/accounts/rate_limit.py`：

- `LoginAttemptState`：`phone_hash`、`failure_count`、`window_started_at`、`locked_until`。
- `LoginAttemptStore` 协议 + `InMemoryLoginAttemptStore` + `PostgresLoginAttemptStore`；`register_failure` 与 `register_success` 必须在锁内（或数据库事务内）原子完成计数与窗口推进。
- `LoginRateLimiter`：持有窗口、阈值、锁定时长与 `auth_secret`，对外提供 `is_locked(phone)`、`register_failure(phone)`、`register_success(phone)`；手机号键由 `hmac_sha256(auth_secret, phone)` 派生。
- `LoginRateLimited`（`ValueError` 子类）表示账号已被锁定，由接口层映射为 `429`。

不采用「按 IP 限流」：宪法明确要求按账号，且本仓库没有可信的客户端 IP 来源（可能存在代理），IP 限流容易误伤。

不采用「各模块自建审计表」：那会产生多套并行审计，跨模块排查需分别拼接，且脱敏规则会漂移。

## 组件与接口

### 审计模型

`AuditAction`（字符串枚举，落库为 `action`）：

```text
account.registration.requested
account.registration.approved
account.registration.rejected
account.login.succeeded
account.login.failed
account.login.locked
account.password.changed
account.password.reset
plan.proposed
plan.approved
plan.rejected
plan.run_started
```

`AuditRecord` 字段：`action`、`actor_id`（可空，匿名注册时为空）、`tenant_id`、`target_type`、`target_id`、`phone_masked`（可空）、`detail`（JSON 对象）、`occurred_at`（UTC）。

`detail` 只允许出现服务端明确写入的结构化值（例如驳回原因、生成器标识、步骤数、运行时标识）；**不允许**写入请求体原文、模型原始响应、口令、哈希、令牌或密钥。

### 审计仓储

`AuditStore` 协议：`append(record) -> AuditRecord`、`list_recent(tenant_id, limit) -> list[AuditRecord]`。

> `list_recent` 供测试与后续管理端使用；**本轮不提供任何读取审计的 HTTP 接口**，审计表只写不读。

PostgreSQL 实现使用迁移 `010_audit_log.sql` 建表；写入在事务内完成；写入失败向上抛出。

### 审计日志

`configure_audit_logging(settings)` 安装一个输出单行 JSON 的 `logging.Formatter`，级别取 `settings.log_level`；函数必须幂等（重复调用不叠加 handler）。`emit_audit_line(record)` 输出固定字段：`event="audit"`、`action`、`actor_id`、`tenant_id`、`target_type`、`target_id`、`phone_masked`、`detail`、`occurred_at`。

### 登录限流

`workbench_login_attempts`（迁移 `011_login_attempts.sql`）：`phone_hash` 主键、`failure_count`、`window_started_at`、`locked_until`、`updated_at`。

规则：

- `register_failure(phone)`：若 `window_started_at` 已超出窗口则把窗口重置为当前时间、计数置 1；否则计数加一。若计数达到阈值则 `locked_until = now + 锁定时长`。
- `register_success(phone)`：清除计数与锁定。
- `is_locked(phone)`：`locked_until` 存在且尚未到期即视为锁定。

内存实现与 PostgreSQL 实现的行为必须一致，且计数与窗口推进必须原子。

### 服务接入

`AccountService` 注入 `audit` 与 `login_limiter`（必填关键字参数，避免生产环境漏注入导致静默失去审计或限流）：

- `login(phone, password)`：先判断锁定，命中则记 `account.login.locked` 并抛 `LoginRateLimited`；随后按既有逻辑校验身份；失败时 `register_failure` 并记 `account.login.failed`，若本次失败触发锁定则额外记 `account.login.locked`；成功时 `register_success` 并记 `account.login.succeeded`。
- `request_registration`：成功落库后记 `account.registration.requested`；首管理员自助申请同时记 `account.registration.approved`。
- `approve` / `reject`：成功流转后记 `account.registration.approved` / `account.registration.rejected`。
- `change_password` / `reset_password`：成功后记 `account.password.changed` / `account.password.reset`。

`PlannerService` 注入 `audit`：`propose` 落库后记 `plan.proposed`；`approve` / `reject` 后记 `plan.approved` / `plan.rejected`；`start_run` 成功后记 `plan.run_started`（`detail` 含 `runtime_key`）。

审计记录中的 `tenant_id` 与 `actor_id` 一律取自服务端身份上下文，不接受客户端传入。

### 接口

`POST /api/v1/auth/sessions` 新增响应码：

- 账号被锁定 → `429`，固定文案「登录尝试过于频繁，请稍后再试」。

其余接口路径、请求体与既有响应保持不变。

## 配置

- `WORKBENCH_LOGIN_MAX_FAILURES`：默认 `5`，范围 `1`–`20`。
- `WORKBENCH_LOGIN_WINDOW_SECONDS`：默认 `300`，范围 `30`–`3600`。
- `WORKBENCH_LOGIN_LOCK_SECONDS`：默认 `900`，范围 `30`–`86400`。
- 三项越界时应用拒绝启动。
- 审计日志级别复用既有 `WORKBENCH_LOG_LEVEL`。
- 审计仓储与限流仓储跟随既有 `WORKBENCH_STORAGE_BACKEND`（开发内存 / 生产 PostgreSQL），不新增后端开关。

## 错误与一致性

- 账号锁定：返回 `429`；由于计数按手机号统一执行，已存在与不存在的手机号在达到阈值后表现一致，不泄露账号是否存在。
- 手机号不存在、口令错误、状态非 `approved`：仍一律返回同一种 `401`（保持既有语义）。
- 审计写入失败：向上抛出（fail-closed），不吞掉；开发内存模式不会触发。
- 审计与限流记录中不得出现口令、口令哈希、令牌、Cookie、密钥、模型原始响应或未脱敏手机号。
- 内存与 PostgreSQL 两种实现对同一输入必须给出相同判定。

## 测试验收

先新增或更新行为测试，再修改生产代码：

- 审计设施：`record` 同时写入仓储与日志；`AuditRecord` 序列化不含禁用字段；日志行为单行 JSON 且字段齐全；`configure_audit_logging` 幂等（重复调用不叠加 handler）。
- 审计脱敏：传入含口令/令牌的 `detail` 或构造非法记录时被拒或脱敏；账号与计划的既有响应与日志中不出现口令与哈希。
- 账号审计覆盖：注册申请、审批、驳回、登录成功/失败/锁定、改密、重置各自写入对应的 `action`。
- 计划审计覆盖：生成、审批、驳回、执行各自写入对应的 `action`。
- 限流单元：窗口内累加、窗口过期后重置、达到阈值即锁定、锁定期内 `is_locked` 为真、锁定到期后解除、成功登录清零。
- 限流原子性：并发失败计数不丢失（内存实现用多线程实测，断言最终计数等于尝试次数）。
- 接口：同一手机号第 6 次尝试返回 `429`；锁定对存在与不存在的手机号表现一致；解锁后可正常登录。
- 配置：三项越界时启动失败。
- PostgreSQL 仓储：以假连接验证 SQL 的列与参数顺序、租户过滤与事务边界。
- 回归：既有测试全部通过，账号与计划的既有状态码与文案不变。

真实 staging 联调、并发压测与生产限流网关不在本设计范围内，不据此宣称已上线。

## 对既有代码的影响

- `AccountService` 与 `PlannerService` 的构造函数新增**必填关键字参数**（审计服务；账号另加登录限流器）。必填而非可选默认，是为了避免生产环境漏注入而静默失去审计或限流。
- 需要同步更新：`app/bootstrap.py` 的两个装配函数、`tests/test_account_service.py` 的 `service()` 辅助函数、`tests/test_account_api.py` 的 `accounts` fixture、`tests/test_planner_service.py` 的 `service()` 辅助函数、`tests/test_planner_api.py` 的 `planner` fixture。
- 既有测试对同一手机号最多触发 2 次登录失败，阈值默认 5 不会改变它们的预期。
- `POST /api/v1/auth/sessions` 新增 `429`，其余既有状态码与文案保持不变。

## 交付物与文档同步

- 新增 `migrations/010_audit_log.sql` 与 `migrations/011_login_attempts.sql`。
- 同步 `.env.staging.example` 的 `WORKBENCH_APPLIED_MIGRATIONS` 清单与 `docs/private-deployment-runbook.md` 的迁移范围（至 `011`）。
- 更新 `docs/api-contract.md`：登录接口新增 `429`，并说明审计覆盖的动作。
- 更新 `.env.example`：补入三项限流配置。
- 更新 `docs/delivery-gates.md`：勾掉「账号登录限流与失败锁定」「账号关键操作结构化审计日志」「计划模块的生成、审批与执行纳入审计」三项。

## 非目标

- 不做管理员读取审计的接口（本轮只写不读）。
- 不做按 IP 限流、设备指纹或封禁名单。
- 不做账号解锁接口（锁定到期自动解除）。
- 不改造全项目日志设施：只覆盖上述审计事件，不顺手迁移既有模块的输出来源。
- 不引入第三方日志或限流库（使用标准库 `logging` 与既有 `hmac`/`hashlib`）。
- 不改变账号与计划模块既有的权限模型与响应文案。

## 已知限制

- 限流按手机号计数，无法阻止攻击者轮换手机号（每个号仍可消耗 5 次 scrypt）。生产环境仍需在网关层补充全局或按来源的限流。
- 审计写入与业务在同一请求内完成，PostgreSQL 模式下会带来一次额外写入；本轮不与业务写入合并为同一事务（业务仓储与审计仓储相互独立），因此极端情况下可能出现「业务成功但审计失败」并抛出。若后续要求严格同事务，需在仓储层做联合事务设计。
- 审计日志输出到 stdout，依赖部署侧采集；本轮不引入日志聚合与告警通道。
- 锁定状态为部署级共享（同一 PostgreSQL），但内存模式下仅进程内有效，多进程开发部署不共享。
- 开发环境 `WORKBENCH_AUTH_SECRET` 允许为空，此时 `hmac_sha256("", phone)` 可被穷举还原；仅影响本地内存实现，生产环境已有「密钥至少 32 位」的启动校验。
- 审计 `detail` 只写入服务端明确设置的结构化短文本（如驳回原因、生成器标识、运行时标识）。其中运行时标识来自客户端但受接口 schema 的长度约束（≤80），不写入请求体原文。
