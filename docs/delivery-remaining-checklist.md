# 交付剩余清单（可勾选 · 需外部输入）

> **本文件的作用**：只说「**还差什么、谁提供输入、用什么命令验证、判据是什么**」。
> **状态真相仍在** [`docs/delivery-readiness-checklist.md`](delivery-readiness-checklist.md)（现状与 ✅/❌），本文件是它的**执行层**，编号与它的「阻塞项 1–8」一一对应，避免两处各说一套。
> **口径**：以下所有事项**代码无法代替**；代码侧缺口已归零，唯一例外是 GEO 适配器（需对端契约，见组 5）。
> **红线**：写操作（迁移演练、并发压测、密钥轮换、启动应用服务）**必须单独授权**并在专用账号下执行；只读部分用 [`docs/readonly-verification-runbook.md`](readonly-verification-runbook.md)。
> **本机已验证（2026-09-12，一次性本机环境，未触碰 staging）**：1.7 跨租户探测、1.8 并发压测三场景、2.2 密钥轮换两阶段 —— 命令与判据均按实测结论写成，可直接照抄。**2026-09-16 追加（本机 Docker，独立 project + 独立端口，演练后已 `down -v` 清理）**：容器编排三服务（app / worker / beat）起栈、镜像版本标签、容器日志上限与**容量测算**取证见 [`docs/private-deployment-runbook.md`](private-deployment-runbook.md)「容量与并发」「监控与告警」；组 1 的 1.9 因此获得**本机级**证据（见该项注记），**但告警渠道与 staging 侧仍未验收**，勾选框一律不动。

---

## 组 1 · 真实环境验收（阻塞项 1）—— 解锁项最多，建议先做

**需要谁提供**：基础设施方 / 运维 —— 一台独立主机（Linux）+ **PostgreSQL（必须预装 pgvector）** + Redis + 对象存储实例 + 全部凭据；一个可登录的租户与超管账号。

**输入索取表（2026-09-16，可直接转发给基础设施方 / 运维）**：[`docs/infra-input-request.md`](infra-input-request.md) —— 14 项逐项要求与验证方式（I1 主机 / I2 PG 客户端 / I3 PG 实例 / I4 pgvector / I5 只读账号 / I6 迁移清单 / I7 Redis / I8 对象存储 / I9 双密钥注入 / I10 超管账号 / I11 备份介质与窗口 / I12 探针账号 / I13 死信渠道 / I14 变量对照单）+ 回执模板 + 安全红线。**未回执前组 1 的判据不做（只读命令待值到位后执行）**；预检 pass 路径与 runbook 漂移核对已于 2026-09-16 完成（见下方 1.3 / 1.4 / 1.4.1 / 1.5 子项）；**1.6–1.12 的「命令 / 参数 / 前置条件」逐项可执行性核对亦已完成（2026-09-16，见下方各子项）**——**1.12 的复测清单已于 2026-09-16 落文档（立项规格 + 复测手册，见下方 1.12 子项）**，各项均「值一到即可执行」；**写操作命令本身一条未跑**（runbook §5 未动）。

**转交与催办材料（2026-09-16 备）**：`docs/infra-input-request.md` §7 新增「转交说明与催办附言（发送人自用）」——含可复制的催办附言模板（回传渠道 / 期望回执时间留空待填）、发出人自查三条红线，以及「先回 I1–I6 + I10 即可先解锁只读核验面」的分批口径；**转交状态＝已发出（2026-09-16 · 飞书 · 首发存档至徐君本人私聊〔消息 ID `om_x100b6593b329aca0b2a22aba839549c`〕，尚未转交至基础设施方、待二次转发；回执未返回）**（回执状态由用户回填；回执到达后按索取表 §6 流程登记）。

> **两个已验证的实操前置（2026-09-12 本机实测，避免到 staging 白跑）**
> ① **部署机必须安装 PostgreSQL 客户端**（`pg_dump` / `pg_restore`）：缺客户端时 `scripts/migration_backup_drill.py --phase backup` 会在「pg_dump 可用性」这一步直接 `fail`（本机即如此）。
> ② `migration_backup_drill.py` 的**任何阶段（含 `--phase list`）都要求先设 `WORKBENCH_DATABASE_URL`**——安全护栏先于动作执行，缺它会以 `exit=2`「必须配置 WORKBENCH_DATABASE_URL」拒绝；本地演练另需显式 `--allow-local`（实测：本地地址不加该开关会被拒，`exit=2`）。另外 `WORKBENCH_APPLIED_MIGRATIONS` **必须从目标库读取**，否则 `--phase list` 会报「迁移清单不一致（缺少 22 项）」。

- [ ] 1.1 目标 PostgreSQL 已装 `pgvector`
      验证：`psql "$DSN" -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector'"`
      判据：**有一行返回**（官方 `postgres` 镜像不带该扩展，迁移 001 会直接失败）
- [ ] 1.1.1 只读账号已建（**怎么建：见 [`readonly-verification-runbook.md`](readonly-verification-runbook.md) §1.1**，含已在真实 PG 上验证的 `CREATE ROLE` + `pg_read_all_data` 语句，该角色可自动覆盖未来迁移新建的表）
- [ ] 1.2 填好生产/预发配置（**不进仓库**）：`WORKBENCH_ENV≠development`、`WORKBENCH_STORAGE_BACKEND=postgres`、`WORKBENCH_DATABASE_URL`、`WORKBENCH_AUTH_SECRET`（≥32）、`WORKBENCH_BACKUP_ENCRYPTION_KEY`（与前者分离）、从目标库读出的 `WORKBENCH_APPLIED_MIGRATIONS`
- [ ] 1.3 `python scripts/staging_preflight.py` → `pass`
      本期实测（未配置环境）会输出 32 条 `fail`（另有 3 条 `blocked`），可当作「你需要准备哪些配置」的清单
      - **2026-09-16 本机只读预演「pass 路径」（仍不勾选）**：以一套**合成非本地值**（变量集与 `.env.staging.example` 同口径；该模板的迁移清单已同步为仓内 34 项）实跑 ⇒ `Staging 前置预检结果：pass`、**36 项 `[pass]`、`exit=0`**。三个预检脚本均为**纯元数据校验、零网络请求**（`staging_preflight.py:3-5` 自述；`worker_preflight.py` 的 `--offline` 分支 `:317-318`）⇒ 未配置环境的 `fail` 只是缺值、不是脚本能力问题。**判据仍未达成：staging 上一项未执行**。
- [ ] 1.4 `python scripts/runtime_staging_preflight.py` → `pass`（未配置环境实测输出 20 条 `fail`；五类 Runtime 各 3 条 + 环境/标识/网络白名单）
      - **2026-09-16 本机只读预演「pass 路径」（仍不勾选）**：同组合成值实跑 ⇒ `外部 Runtime staging 预检结果：pass`、**20 项 `[pass]`、`exit=0`**。**判据仍未达成：staging 上一项未执行**。
- [ ] 1.4.1 `python scripts/worker_preflight.py --offline` → `pass`（本机实测输出 7 条，含「迁移清单不一致」；联网校验另需 `--base-url` 与 `--token`）
      - **2026-09-16 本机只读预演「pass 路径」（仍不勾选）**：同组合成值实跑 ⇒ `Worker 运行态前置预检结果：pass`、**6 项 `[pass]` + 1 项 `[skipped]`（`联网运行态校验`按 `--offline` 跳过）、`exit=0`**；迁移清单按仓内 34 项比对一致。**判据仍未达成：staging 上一项未执行**。
- [ ] 1.5 **只读核验清单全绿**（`docs/readonly-verification-runbook.md`）：pgvector 存在、迁移 022 已落地且复合外键存在、**归一风险 0 行**、**绑定侧未纳管为空**（`candidates.roles == []` 且 roster 绑定侧为空）
      - **2026-09-16 只读漂移核对（仍不勾选）**：runbook 命令与当前代码**逐面无漂移**——端点（`app/main.py`：`/api/v1/auth/sessions` `:3572`、`/auth/registrations` `:3412`（`bootstrap_token` 为请求体字段 `:3327`）、`/auth/me/totp` `:3721` 与 `/confirmation` `:3733`、`/workforce/roster` `:1072`、`/workforce/candidates` `:1343`、`/dead-letters` `:1021`、`/api/v1/health` `:616`、§1.3 默认探针 `/api/v1/approvals/pending` `:3504`）；SQL 面（`workbench_tasks`＝`migrations/001_initial.sql:3`、`binding_type`/`binding_key`＝`004:3-4`、目录两表与复合外键 `(tenant_id, role_key)`＝`022:9/24/35`、`workbench_schema_migrations` 由 `app/migrations.py:30` 创建＝§1.2 口径成立、`001:1` 含 `CREATE EXTENSION vector`＝1.1 判据前提）；§4 五个只读脚本全部存在、跨租户 6 类 KIND（`cross_tenant_probe.py:64-69`，缺 `--resource` `exit=2` `:336-338`）、并发三场景（`staging_concurrency_probe.py:49`）、`migration_backup_drill.py:452-462` 与 `secret_rotation_drill.py:336-347` 参数均与文档一致 ⇒ **命令一到 staging 即可执行**。**判据仍未达成：staging 上一项未执行**。
      - **2026-09-16 本机 Docker 全链路只读预演（仍不勾选）**：在**一次性本机 Docker 环境**（`pgvector/pgvector:pg16`〔PG 16.10 / vector **0.8.0**〕+ Redis 容器 + `uvicorn` 真实 HTTP 服务；**34 项迁移全部应用**、3 租户与最小种子、跑完即销毁）上，把 runbook §1–§4 命令**逐条实跑**并留档 `exit` 码与关键输出：① **§1.1 / §1.2**：`CREATE ROLE` + `pg_read_all_data` 建只读账号 ⇒ 属性 `workbench_ro|f|f|t`；从 `workbench_schema_migrations` 读出 **34 项（001–034）** 拼接清单，与仓内比对一致（`worker_preflight` 判「迁移清单一致（34 项）」）；② **§2 A–H 与 §7 样例逐项一致**（A 有行〔版本号差异见下〕；B 两表 + 复合外键 `FOREIGN KEY (tenant_id, role_key) REFERENCES workbench_job_roles(tenant_id, role_key)`；C **1 行** `role|Content-Operator|content-operator`；D `agent_bindings 2 / digital_employees 2 / job_roles 2 / role_bindings 3 / tasks 1`〔D 先于 §4 造数取得〕；E `Content-Operator, legacy-role`；F 空；G `role|geo-operator`；H `t-1|geo-analyst|geo-operator|disabled`）+ 只读包装**负例**（同会话 `CREATE TABLE` ⇒ `ERROR: cannot execute CREATE TABLE in a read-only transaction`、`exit=1`；`SELECT` `exit=0`）+ **未来表覆盖复验**（管理员建表 ⇒ 只读账号**免授权**可 `SELECT` 到行 ⇒ 删表）；③ **§1.3 令牌三情形**：引导注册 **201**（`super_admin`/`approved`/`reviewed_by=bootstrap`）→ 边界（已有超管后错口令 + 缺 `tenant_id`）**201 `pending`** → 无码登录 **200 `scope=totp_enrollment`/`expires_in=300`** → 受限令牌访问 roster **403**「账号需要先完成动态口令绑定」→ `POST /auth/me/totp` **200**（SHA1 / 6 位 / 30 秒）→ 确认绑定 **200 `{"status":"confirmed"}`** → 已消费码登录 **401** → 跨步长新码登录 **200 `scope=full`/`expires_in=900`** → 已绑不带码 **401**「需要动态验证码」；普通注册 **201 `pending`** → 超管审批（`department_lead`/`t-b`）**200** → B 登录 **200 `scope=full`**；④ **§3**：`candidates` **200 `{"roles":[],"agents":[]}`**、`roster` **200 `total=0`**、非超管 **403**「只有超级管理员可以查看岗位与数字员工清单」、无令牌 **401**「缺少登录身份信息」；⑤ **§4**：五个预检脚本实跑（`staging_preflight` 6 `[pass]`/28 `[fail]`/2 `[blocked]`；`runtime_staging_preflight` 0/20/0；`commercial_g0` 6/1/2 且「迁移状态一致」`[pass]`；`worker_preflight --offline` 4/2/1 且「迁移清单一致（34 项）」`[pass]`；`sso_preflight --offline` `[skipped]` **`exit=0`**——`fail` 项均为**本机开发态缺 staging 配置**的 fail-closed，非脚本能力问题）+ `cross_tenant_probe`（两个租户各一真实 task ⇒ **`exit=0`**、报告 `A→A=200 B→B=200 A→B=404 B→A=404`；漏 `--resource` ⇒ **`exit=2`**）；⑥ **审计佐证（只读）**：`workbench_audit_log` 有 `account.registration.requested×3` / `approved×2`（引导两条即 `requested`+`approved` 且 `detail={"bootstrap": true}`）、`login.succeeded×3` / `failed×3`、`totp.enrolled` / `confirmed` / `enrollment_required` 各 1，手机号一律脱敏。**差异与新发现**：A2 的 `extversion` 为 **0.8.0**（§7 样例 0.8.6 ⇒ 镜像自带版本差异，判据「有行」成立）；**同一步长内重复使用动态码（含确认绑定已消费的那一个）会被计为登录失败**（默认 `5` 次 / `300` 秒窗口 ⇒ 锁定 `900` 秒），按 runbook「等验证器翻到下一个码（≤30 秒）」执行即可（本机踩到并按此通过）。**判据仍未达成：staging 上一项未执行**。
- [ ] 1.6 **迁移回滚演练**（写操作，需授权）：`scripts/migration_backup_drill.py`
      判据：能按备份恢复到指定版本，且 `WORKBENCH_APPLIED_MIGRATIONS` 与库内一致
      - **2026-09-16 只读可执行性核对（仍不勾选）**：四阶段（`list` / `backup` / `restore` / `verify`，`scripts/migration_backup_drill.py:389`）与参数（`:452-462`）和判据口径一致；**默认 dry-run，`--execute` 才真跑**。前置可枚举：`WORKBENCH_DATABASE_URL`（须 `postgresql+psycopg://`，缺 `exit=2` `:103`）、`pg_dump` / `pg_restore`（I2；缺即 `fail` `:196-205` / `:277-287`）、`WORKBENCH_BACKUP_ENCRYPTION_KEY` ≥32（I11 / I9；缺即 `fail` `:211-223`）、隔离恢复库 `--restore-dsn`（缺则 `skipped` `:258-267`）、`WORKBENCH_APPLIED_MIGRATIONS` 自目标库读（I6）。**口径差异登记**：脚本无「回退到指定历史版本」参数，其恢复口径＝恢复到隔离库 → `apply_migrations` 前滚至最新 → 清单逐一比对（`:310-317`）；回退能力旁证为 10.12 本机一次性容器 027 回退（run `35080905772`），staging 同款需另行授权。**判据仍未达成：需 I1 / I2 / I3 / I6 / I9 / I11 到位 + 授权**。
- [ ] 1.7 **跨租户只读探测**（需两个不同租户的令牌 + **每个 KIND 在两租户各一个真实资源 ID**）：
      `python scripts/cross_tenant_probe.py --base-url … --token-a … --token-b … --resource "task:<A_ID>:<B_ID>"`（**漏掉 `--resource` 会 `exit=2`**）
      判据：`exit=0` 且报告 `A→A=200 B→B=200 A→B=404 B→A=404`（本机已实测通过）
      - **2026-09-16 只读可执行性核对（仍不勾选）**：脚本参数与 runbook 一致（`scripts/cross_tenant_probe.py:309-320`；缺 `--resource` ⇒ `exit=2` `:335-337`）；6 类 KIND ↔ 端点逐一对应（`:63-70` ↔ `app/main.py`：`task :3028` / `plan_proposal :3853` / `content_task :741` / `run_metrics :3128` / `orchestration_proposal :3995` / `commercial_lifecycle :1000`）。**对照组造数路径已可枚举**：task → `POST /api/v1/tasks`；content_task → `POST /api/v1/content-tasks`（`:679`）；plan_proposal → `POST /api/v1/tasks/{task_id}/plan-proposals`（`:3834`，需 `WORKBENCH_PLANNER_TOOLS` 非空）；run_metrics → 建 run（`:3103` / `:3905`）；orchestration_proposal → `POST /api/v1/orchestration-proposals`（`:3966`）；commercial_lifecycle → `POST /api/v1/commercial/exports` / `deletion-requests`（`:934` / `:976`）。**执行注意**：I10 只含「一个租户 + 超管」⇒ 第二租户须由超管走「注册 + 审批」自建（本机已验证路径，需额外一个手机号）；建任务角色限 `employee` / `department_lead` / `ceo` / `super_admin`（`customer_admin` `403`）。**判据仍未达成：需 I1 / I3 / I10 + 第二租户 + 逐 KIND 造数**（本机已实测 task 一种全绿）。
- [ ] 1.8 **并发压测**（写操作，需专用账号）：

      ```bash
      python scripts/staging_concurrency_probe.py --base-url "$BASE" \
        --token "$TOKEN" --phone "$PROBE_PHONE" --password "$PROBE_PASSWORD" \
        --scene login_throttle --scene task_idempotency --scene plan_approval \
        --proposal-id "$PROPOSAL_ID" --concurrency 8
      ```

      - `--base-url` / `--token` / `--phone` / `--password` 四个**必填**；**`--phone` 必须是专用探针账号**（登录场景会把它锁定一段时间），**绝不能用真人账号**。
      - **`login_throttle` 第一次跑必然 `fail`（`{401:8}`），这不是缺陷**：8 个并发请求在账号被锁定之前**同时通过了「未锁定」检查**，而锁定是在失败计数之后才生效。**紧接着再跑一次即 `pass`（`{429:8}`）**，报告还会自己推出「部署最大失败次数约为 5」（与默认 `WORKBENCH_LOGIN_MAX_FAILURES=5` 一致）——**不要因为这个 fail 去改代码或调配置**。
      - **`plan_approval` 的前置**：需要一个处于 `pending_review`、且**发起人 ≠ 令牌用户**的提案（自审会被拒）；另外**创建提案要求 `WORKBENCH_PLANNER_TOOLS` 非空**（默认空时建提案直接 `422`「未配置任何可用工具」，本机实测），所以要在 staging 上先备好真实提案，**不能临时现造**。
      判据（2026-09-12 本机实测三场景全部跑通）：`login_throttle` 第二次 `{429:8}`；`task_idempotency` `{200:7,201:1}`（同一幂等键只产生 1 条记录）；`plan_approval` `{200:1,409:7}`（并发审批保持原子）
      - **2026-09-16 只读可执行性核对（仍不勾选）**：参数与实现一致（`scripts/staging_concurrency_probe.py:421-436`；`--base-url` 强制 HTTPS 且非本地、越界 `exit=2` `:63-74`；`--concurrency` 限 1–64）；三场景端点逐一对应：`login_throttle` → `POST /api/v1/auth/sessions`（故意错口令、不带令牌 `:254-268`）、`task_idempotency` → `POST /api/v1/tasks`（带令牌 + 同一幂等键 `:271-295`）、`plan_approval` → `POST /api/v1/plan-proposals/{id}/approval`（`:297-318`）。**缺 `--proposal-id` 时 `plan_approval` 记 `skipped` 而非 `fail`（`:300-308`）——不计失败，但也拿不到该场景判据证据**。前置可枚举：I12 专用探针账号（口令不进报告）、`pending_review` 且发起人 ≠ 令牌用户的提案、`WORKBENCH_PLANNER_TOOLS` 非空（建提案前置）。**执行前核对项**：同一 `--token` 同时用于 `task_idempotency`（建任务）与 `plan_approval`（审批），探针账号角色须同时覆盖「建任务 + 审批提案」两种权限。**判据仍未达成：需 I12 + 真实提案 + 角色核对 + 授权**。
- [ ] 1.9 **审计落 PG 的实跑验证 + 日志采集告警**
      判据：库里能查到审计行；采集侧有告警规则（此前只有假连接静态断言）
      - **2026-09-16 第二批进展（仍不勾选）**：9 条规则从「成文」推进到「可执行」——只读探针 `scripts/monitoring_probe.py` 按 runbook 逐条同口径判定（信号不可用显式 `skipped`，不会静默算作通过），并在本机对真库实跑取证（Outbox 0 条 / 死信 0 条 / 磁盘 67.3% / PG 连接 10-100 等实测值；未接渠道时 `--notify` 不生效）；客户侧「渠道接入 + 触发一次真实告警」的核对清单与配套只读探针见 `docs/customer-side-acceptance-runbook.md` + `scripts/customer_acceptance_probe.py`。**仍缺**：渠道未接入、无真实触发证据。
      - **2026-09-16 只读可执行性核对（仍不勾选）**：三份资产齐备且与判据同口径——9 条告警规则表 ↔ `docs/private-deployment-runbook.md:65-75`（部署侧采集配置）；只读采样探针 `scripts/monitoring_probe.py`（参数 `:924-947`；信号不可用显式 `skipped`，不静默算通过）；客户侧「渠道接入 + 真实触发」清单 `docs/customer-side-acceptance-runbook.md`（§2.5 `:144-179` / §2.6 `:181-212` / §3 `:216-246`）+ 配套探针 `scripts/customer_acceptance_probe.py`（含 `_check_audit_log:521`；参数 `:659-683`）。**判据口径**：以**渠道侧收到一次真实告警**为准——只跑采样探针不算取证；「库里能查到审计行」须在真实 PG 上查（本机内存仓储不算）。**判据仍未达成：需 I5 / I7 到位 + I13 渠道接入 + 客户侧执行 + 授权**。
- [ ] 1.10 **Outbox / Celery Worker 实跑**：Redis + Worker 进程 + 死信通知渠道地址
      判据：事件经 Outbox 投递成功；失败进死信并能通知
      - **2026-09-16 只读可执行性核对（仍不勾选）**：资产齐备——异步链路与 worker/beat 命令见 `docs/private-deployment-runbook.md:43-54`（beat 必须独立进程 `:27`、启动命令 `:46-49`）；死信查询/回放端点 `GET /api/v1/dead-letters`（`app/main.py:1021`）；通知渠道配置项 `WORKBENCH_DEAD_LETTER_WEBHOOK_URL`（`app/settings.py:33`）与实现 `app/notifications.py` 均已存在。**差异登记**：`docs/external-dependency-acceptance-plan.md` 项 2（`:141-157`）仍写「死信通知渠道未实现 / runbook 未覆盖异步链路」两项待补代码——**现均已落地**，该文本滞后，本轮只登记不改动。前置可枚举：I7 Redis + Worker/beat 部署（判据前半「Outbox 投递成功」）；I13 渠道地址未到位时可暂缺，但判据后半「能通知」无法取证。**判据仍未达成：需 I7 + I13（可跳过）+ 部署 + 授权**。
- [ ] 1.11 **商业化迁移与备份/恢复演练**：真跑一次恢复（不是只看脚本）
      - **2026-09-16 只读可执行性核对（仍不勾选）**：执行资产与 1.6 同源（`scripts/migration_backup_drill.py` 四阶段；「真跑恢复」＝`--execute` + `--restore-dsn` 指向隔离恢复库后前滚比对清单，`:248-317`）；补 `scripts/commercial_g0_preflight.py` 复核商业化 G0 与迁移状态一致；步骤口径对齐 `docs/staging-acceptance-checklist.md` 执行顺序 4–8（`:29-33`：健康/租户读取/低风险任务持久化/用量账本/导出与删除冷静期/备份恢复到隔离库后记录可读）。前置同 1.6：I1 / I2（`pg_dump`、`pg_restore`）/ I3 / I6（清单自目标库读）/ I9 / I11（备份介质与窗口）+ 客户管理员（I10）走导出/删除链路。**判据仍未达成：需 I1 / I2 / I3 / I6 / I9 / I11 + 客户管理员 + 授权**。
- [ ] 1.12 **攻击面八类检查在真实环境复测**（本机报告 `docs/security-attack-surface-report.md` 已有，需真实环境结论）
      - **2026-09-16 只读可执行性核对（仍不勾选）**：**本项是 1.6–1.12 中唯一「无现成可执行资产」的判据**——仓内无对应复测脚本、也无成文的 staging 请求清单；报告 §5（`:223-234`）逐条列出未覆盖范围与真实环境要求，§6（`:236-240`）明确不代表生产验收，`:12` 已声明未在真实环境执行。**可复用映射**：第 1 类（水平越权）↔ `scripts/cross_tenant_probe.py`；第 8 类（资源滥用）中的登录限流并发部分 ↔ `scripts/staging_concurrency_probe.py`（`login_throttle` 场景）；第 7 类（信息泄露）中的脱敏/审计部分 ↔ `scripts/customer_acceptance_probe.py`。**其余类别（第 2–6 类）需把本机 `TestClient` 用例转写为 staging 请求清单，多数为写操作**。**判据仍未达成：复测清单已于 2026-09-16 落文档（见下子项）；执行仍待 I1–I14 到位 + 单独写授权**。
      - **2026-09-16 立项 + 复测清单落文档（仍不勾选）**：**V1 已产出两份文档**——立项规格 [`docs/superpowers/specs/2026-09-16-attack-surface-retest-design.md`](superpowers/specs/2026-09-16-attack-surface-retest-design.md)（**草案待评审**；分期 **V1 清单落文档＝本轮 / V2 staging 执行＝待 I1–I14 + 单独写授权 / V3 结论回写**；复测口径＝**严格重放八类不扩面**；不可造场景替代口径〔过期令牌→登出撤销后复用 / 生成器伪造 `kind`→观察式 / dev 态 `200`→不复测〕；**5 条待裁决点 A1–A5** 各附推荐）+ 复测手册 [`docs/attack-surface-retest-runbook.md`](attack-surface-retest-runbook.md)（八类逐项：复用资产 / staging 请求清单〔端点行号齐备〕/ 前置账号角色 / 判据 / 读写标记 / 证据模板；命名对齐 `readonly-verification-runbook.md`）。**判据仍未达成：清单已成文，执行待 I1–I14 到位 + 单独写授权**。
      - **2026-09-16 立项评审通过 + A4 指针落地（仍不勾选）**：用户审阅立项规格后**批准** ⇒ **A1–A5 逐条按推荐落定为裁决**（A1 采纳替代口径〔过期令牌→登出撤销后复用、生成器伪造 `kind`→观察式、dev 态 `200`→不复测〕/ A2 严格重放八类不扩面 / A3 造数落演练租户 + I12 专用账号 / A4 报告 §5 加指针 / A5 V2 先手工 / curl 不新增脚本）；立项规格状态更新为「**已评审**」并回填审批记录（§4 尾注）；**A4 已落地**——`docs/security-attack-surface-report.md` §5 尾注加「复测指针」（不改报告任何结论）。**判据仍未达成：执行待 I1–I14 到位 + 单独写授权**。

**解锁**：就绪清单中 12 条 ❌ 里的绝大多数，以及 65 条「代码完成但未验收」中的大部分。

---

## 组 2 · 生产密钥与轮换（阻塞项 2）

**需要谁提供**：部署密钥系统（Vault/KMS/云密钥服务）与轮换流程。

- [ ] 2.1 两把密钥由密钥系统注入（`WORKBENCH_AUTH_SECRET`、`WORKBENCH_BACKUP_ENCRYPTION_KEY`，≥32 位且互不相同），仓库内无明文
- [ ] 2.2 **轮换演练**（写操作，需授权）：`scripts/secret_rotation_drill.py`
      两阶段，**`before` 与 `after` 之间必须替换 `WORKBENCH_AUTH_SECRET` 并重启应用**（密钥只在启动期读取）：

      ```bash
      # ① 轮换前：登录取令牌，写入证据文件（含令牌，用完即删）
      python scripts/secret_rotation_drill.py --phase before --base-url "$BASE" \
        --phone "$PHONE" --password "$PASSWORD" --output /tmp/rot-token.json

      # ② 替换 WORKBENCH_AUTH_SECRET 并重启应用

      # ③ 轮换后：断言旧令牌失效 / 重登成功 / 新令牌可用
      python scripts/secret_rotation_drill.py --phase after --base-url "$BASE" \
        --phone "$PHONE" --password "$PASSWORD" --output /tmp/rot-token.json
      ```

      - **前置：应用必须使用持久化账号仓储**（`WORKBENCH_STORAGE_BACKEND=postgres`）。默认 `memory` 下账号只存在于进程内，重启即丢，会导致 `after` 阶段「重新登录」返回 `401 手机号或密码不正确`——这是**运行配置问题，不是轮换缺陷**（本机已踩过一次，见下）。staging 本就是 postgres，正常不会遇到。
      - 令牌是无状态 HMAC-SHA256（`auth_secret` 参与签名），因此**重启本身不会**让旧令牌失效；`after` 阶段的 401 只可能来自密钥变化。本机做了对照实验确认这一点。
      - 受保护探针默认 `GET /api/v1/approvals/pending`（任意已登录角色均 200），可用 `--probe-path` 覆盖；报告**只打印令牌指纹（SHA-256 前 8 位），绝不打印令牌原文**。
      判据（2026-09-12 本机 PG16 + `WORKBENCH_STORAGE_BACKEND=postgres` 实测）：
      - 对照（**同密钥**重启）：旧令牌 `200`、重新登录 `200` → 证明重启不影响会话
      - 轮换（S1→S2）后：旧令牌 `401`、重新登录成功（新指纹 `sha256:aa523ec5`）、新令牌 `200`，`exit=0` 全 `pass`
      - 落库旁证：`workbench_accounts` 中该账号 `scrypt$` 哈希与轮换前一致（改密钥不动口令哈希）

---

## 组 3 · 外部 Runtime 联调（阻塞项 3）

**需要谁提供**：RAGFlow / AgentScope 各自的 HTTPS 地址、**固定版本号**、认证注入方式、隔离测试账号。

- [ ] 3.1 capability 白名单已登记（模板由 `tests/test_staging_assets.py` 守护）
- [ ] 3.2 真实联调 + 沙箱验证
      判据：`GET /api/v1/runtimes/health` 返回 `ok`；知识检索返回**带引用的**片段；不直连工作台数据库、不决定审批结果

---

## 组 4 · 真实模型与发布验收（阻塞项 5）

**需要谁提供**：真实模型密钥；公众号平台账号与**发布授权**。

- [ ] 4.1 内容生成走真实模型（`content_model_*`）
- [ ] 4.2 网页抓取真实站点（域名白名单 / robots / 限速 / 体积上限）
- [ ] 4.3 公众号自动发布 + 回执核对（幂等键 `task:revision`、失败转人工接管、**绝不自动重发**）
      判据：每项留一条真实证据（回执 ID / 检索引用 / 抓取留痕），并把脱敏结论写回就绪清单

---

## 组 5 · GEO 版本化适配器（阻塞项 6）—— 唯一未闭合的代码缺口

**需要谁提供**：GEO 侧 API 契约（端点、认证、数据模型、错误语义）、固定版本号与兼容/升级规则、读写边界。索取表见 `docs/geo-contract-request.md`（**草案，尚未回执**）。

- [ ] 5.1 索取表全部项拿到回执（**没有回执不得开工**，也不做占位实现）
- [ ] 5.2 适配器 + 契约测试（`FakeTransport`）+ 版本固定校验（拒绝 `latest`/`main`/`head`）
- [ ] 5.3 staging 真实联调

---

## 组 6 · 桌面端签名 / 公证 / 干净电脑测试（阻塞项 7）

**需要谁提供**：Windows 代码签名证书（OV/EV）+ 可信时间戳服务 + 一台干净 Windows 机器。

- [ ] 6.1 固定依赖版本 → 构建安装包（NSIS）
- [ ] 6.2 代码签名 + 时间戳
- [ ] 6.3 干净机器跑「安装 → 打开 → 自动更新（旧版→新版）」全流程

---

## 组 7 · PWA 真机安装与推送（阻塞项 8）

**需要谁提供**：真机（iOS/Android）；若要真推送，还需 HTTPS 域名 + VAPID 密钥。

- [ ] 7.1 真机安装性验证（manifest、图标、离线壳；**不缓存 `/api/`**）
- [ ] 7.2 （可选）Web Push 真推送；不做则如实说明「提醒为轮询」

---

## 组 8 · 真实统一登录（IdP）与密钥轮换验收

**需要谁提供**：真实 IdP 的 `client_id` / `client_secret` / endpoints / 回调白名单。

- [ ] 8.1 SSO 真实联调（自建账号 + TOTP 二次验证已在开发期验证）
- [ ] 8.2 生产密钥轮换见组 2

---

## 组 9 · 明确不做（口径已变更，避免重复询问）

- [ ] **设备绑定**：**不做**。理由与变更记录见 `docs/delivery-gates.md`「门禁口径变更记录」（产品采用「注册申请 + 管理员审批」制）。
- 不做即视为该项关闭，不再列入剩余。

---

## 组 10 · 我方实现自查（**无需外部输入** · 2026-09-13 新增）

> **来源**：[OpenMausBot 源码研读报告](file:///d:/徐徐AI学习/公司工作台/docs/openmausbot-source-study-and-adaptation-plan.md) §5.2——从**对方暴露的缺口**反查「我们是否同类风险」。以下各条**此前均未逐条自查**，**不构成对我们现状的定性结论**（沿用"没验证的必须写未验证"）；**2026-09-16 已查的条目在各项下附「结论 + 证据（`文件:行`）」**（10.1 已查〔应用层无 DELETE/清理路径通过；数据库层 REVOKE 未做 ⇒ 差距，仍不勾选〕；10.2 通过；10.4 通过（键名归一 + 值形态扫描 + 掩码幂等）；10.5 已查〔用量账本 / `daily_budget_cents` / 评测费用 / 展示层全整数分，均通过；任务预算 `budget`（`NUMERIC(18,6)` 元 + 接口 float 链路）为差距，运行时「元→分」换算已最小加固并登记 ⇒ 仍不勾选〕；10.6 已查〔生产强制 `state_postgres` 成立（配置层 + 装配层双保险 + 部署口径 + 预检 + 守护测试）；唯一边界「`build_runtime_service` 缺省兜底不带 env 校验」已按 2026-09-16 拍板做 fail-closed 最小加固 + 先红后绿 + 反假两轮 ⇒ 勾选〕；10.8 已查〔8 类人工决议入口逐条核对：计划提案 / 运行内审批 / 编排优化提案 / 技能版本复核 / 对话入口（复用运行内审批）均成立；账号注册审批与知识文档复核语义 N/A（申请人无账号 / 系统到期触发）；未接线入口已登记；唯一缝隙「任务审批允许发起人自审」已按 2026-09-16 拍板收紧（403 + 列表剔除）+ 先红后绿 + 反假两轮 ⇒ 勾选〕；10.7 已查〔导出 / 删除路径均存在但覆盖不全（导出 15 类仅 `memories` 已接线；删除清场仅记忆层、`skills` / `knowledge_governance` 的 `delete_all_for_tenant` 已具备未接线；「记录确认人」未实现；保留策略无服务侧执行器；用户级个人导出 / 删除无）；本轮按 2026-09-16 拍板加固两项——新增导出包取回端点（admin-only、租户服务端解析、跨租户统一 404、过期 404）+ worker 周期任务按 `expires_at` 清理过期包（beat 间隔默认 3600），先红后绿 + 反假两轮 ⇒ 仍不勾选（差距如实登记，不改码）〕；10.3 的「运行事件有界」「日志有界」两条已于 2026-09-16 闭合，但因「磁盘容量告警渠道未接入」仍不勾选；10.11 已查〔五层证据（构建机制 / 源码 grep / 本机构建产物实测扫描 / 仓库卫生 / 守护测试 42 项全绿）：构建产物与静态资源**无密钥、无内部地址、`VITE_*` 变量名零泄漏**；开发 fallback（`localhost:8000` / `super_admin`）非密钥非内部地址，且后端非 development 只信 Bearer（`app/main.py:548-554`）⇒ 勾选〕；10.9 已查〔**判据成立 ⇒ 勾选**：① 容器侧零外网出口五层证据——装配 fail-closed（`--network` 恒内网桥 + 生产构造不传 `network_name` + 起容器前校验 `Internal=True`，`internal=False` 拒绝执行）、工具面 ④-1 只读白名单 + ④-2 A4 网络黑名单双闸门、真容器实测零出网（DNS 不外泄 / `1.1.1.1:443` / `8.8.8.8:53` / 裸 UDP DNS / `169.254.169.254` 全 `Network is unreachable`）、真容器 + 真实供应商双轮对照（`supplierDomain=BLOCKED` / `gateway REACHABLE status=403`）、13 项联网 / 遥测插件禁用 + `read-only` 剖面锁死；② 容器内无供应商密钥（env 白名单仅网关地址 + 短期令牌两项）；③ 工作台侧出网调用点逐条枚举 12 处（受控抓取 / 知识适配器 / 模型 4 / 发布集成 3 / 内部受控 3），全外置配置 + 显式超时；④ 三项阴性核查（无硬编码第三方域名 / 无遥测埋点 / 无第二类出网原语）；⑤ C1/C2 不立项明写「不引入第二套出网归口」〕；10.12 已查〔**判据成立 ⇒ 勾选**（用户授权全链路写操作）：一次性独立容器（digest 钉死、仅回环端口、无卷）六步全过——前滚 34 项（含 027）→ 对象核对（约束 1 + 两表 21/10 列、CHECK 4/2、FK 1/3）→ 备份/恢复（`pg_dump`/`pg_restore` 退出码 0，恢复库逐项一致）→ 回退 027（两条 `DROP TABLE` + `DROP CONSTRAINT` + `DELETE 1`，不用 CASCADE）⇒ 归零 → 再前滚（仅 1 项＝`027`，计数全同）→ 容器销毁无残留〕；10.10 已查〔**判据成立 ⇒ 勾选**：工具面 4 个审计落点 `reason` 全为受控枚举或空（`executed` 恒 `None` / `blocked` 取 `ReasonCode.value` / 令牌守卫固定 `"not_authorized"` / 到期清理不写 `reason` 键）；9 值 `ReasonCode` 枚举 + 写入侧 `_validate` 运行时校验（InMemory / Postgres 同日径）+ 5 组正负向守护测试；动作码为 `AuditAction` 枚举 + 查询侧 422 + 读取侧水合三重闸门；边界登记：DB 层无 CHECK、非工具类审批驳回理由为自由文本（有意设计，超本条范围）〕），**未附结论的仍未查**。
> **与本文件口径的偏差说明**：本文件其余各组均为「代码无法代替、需外部输入」；本组是**纯内部核查**，放在此处仅为集中可勾选，**不代表需要外部资源**。

- [ ] 10.1 审计是否有 **DELETE / 清理路径**（`app/audit/store.py` 与数据库层是否 REVOKE）——判据：**可删即不合规**
      - **结论（2026-09-16 自查，两分）：应用层「无 DELETE / 清理路径」已查实（强证据）；数据库层「REVOKE」未做（差距）⇒ 按判据「可删即不合规」仍不勾选。** ① **应用层无删除能力**：`app/audit/store.py` 的 `AuditStore` 协议只有 `append` / `list_recent` / `query`（`:12-27`），两个实现只有 INSERT + SELECT（`:55-114` / `:117-271`；`app/audit/service.py` 同为只有 `record` / `query`）⇒ 接口级不可删；`app/` 全目录 **18 处 `DELETE FROM` 逐条核对，无一指向 `workbench_audit_log`**（清单见 change-record 本条），`scripts/` 无 DELETE ⇒ 语句级亦无。② **保留策略无执行器**：`WORKBENCH_RETENTION_POLICY` 的 `audit:730` 仅被 `scripts/commercial_g0_preflight.py` 部署预检读取、**不被服务侧消费**（`app/commercial/lifecycle.py:14-17`）⇒ 不是清理路径。③ **租户删除不删审计**：物理清场只清记忆层（`app/commercial/lifecycle.py:339`），且删除执行**本身写审计**（`:342-349`，`commercial.deletion.executed`）。④ **worker 清理只动运行事件**：`app/worker.py:235-236`（守护 `tests/test_runtime_events_postgres.py::test_purge_never_touches_the_audit_log`）。⑤ **检测层**：审计为空告警 + 客户验收探针「不轮转、不删除」（`scripts/monitoring_probe.py:157` / `scripts/customer_acceptance_probe.py:521-535`）。
      - **数据库层差距（未做，不得读成已验）**：全仓 `*.sql` 无 `REVOKE` / `GRANT`、`migrations/010_audit_log.sql` 无删除/改保护 ⇒ 按当前部署口径（应用 DSN 兼作迁移账号＝表属主）账号天然有 DELETE / UPDATE 权限 ⇒「不可篡改」目前靠**应用层无路径 + 检测层**，**不靠 DB 硬约束**；且 **REVOKE 生效前提是账号分离**（属主角色 vs 应用 DML 角色），非单条 SQL 可毕 ⇒ **处置（2026-09-16 用户拍板）：仅登记，暂不做 DB 加固**（不写 runbook 加固预案、不加迁移/触发器）；待组 1 真实环境验收时一并考虑。
      - **附：任务域事件流 `workbench_audit_events`（迁移 001，非通用审计）存在删除路径（设计内）**：结构级 `ON DELETE CASCADE`（`migrations/001_initial.sql:25/31`）＋ 应用级失败补偿（`app/repository.py:194`），由 `app/conversation/execution.py:406-411` 在 ⑥ 落库失败（503）时触发；真库守护 `tests/test_dsh_execution_postgres.py:454-474`（零残留、含 `audit_events=0`）⇒ 定性＝**失败请求痕迹清零**（该请求「从未发生」，也不写通用审计），非删除已生效的审计证据。034 注释「审计表（`workbench_audit_log` / `workbench_audit_events`）不可删除」的准确口径应读作「**保留期清理/后台任务不得触碰**：`workbench_audit_log` 全口径不可删；`workbench_audit_events` 仅随任务生命周期/失败补偿删除」——迁移已应用，**不回改**。
- [x] 10.2 审计与运行日志的**轮转策略**是否避免「只留一份 `.1`、覆盖历史」；是否有**日期分段或外部归档**
      - **结论（2026-09-16 自查）：无「只留 `.1`」风险，且日志有界。** 证据：① 应用侧审计日志只有 `StreamHandler(sys.stdout)`、**无 `FileHandler`**（`app/audit/logging.py:22`）⇒ 不存在应用内「覆盖式保留 `.1`」的机制（由 `tests/test_audit_logging.py` 守护）；② 落盘与轮转交给容器运行时：三服务已设 `json-file` / `max-size=10m` / `max-file=5`（`docker-compose.app.yml`，2026-09-16 本机演练 `docker inspect` 实查生效；`tests/test_compose_worker_assets.py::test_app_services_bound_container_log_growth` 守护）；③ 数据库里的审计行**不轮转、不删除**（不可篡改口径，见 10.1）。**未做**：外部归档与日期分段——长期留存需由客户侧日志采集承担（runbook「监控与告警」接入方式）。
- [ ] 10.3 运行事件 / 日志是否**有界**（容量与保留），并配**磁盘容量告警**
      - **结论（2026-09-16 自查，两批）：前两条已闭合，仅剩「磁盘容量告警」的渠道接入 ⇒ 仍不勾选。** ① **日志有界 ✓**（同 10.2 证据②）；② **运行事件有界 ✓（2026-09-16 第二批闭合）**——事件已从状态行的行内 JSONB（改造前 `app/runtime/state.py` 的无界 list，经 `app/runtime/serialization.py` 整段序列化）迁到 **append-only 表 `workbench_runtime_events`**（迁移 `034`：主键 `(run_id, sequence)`，一次追加只写一行，状态行只留计数 `event_count` ⇒ 行大小有界、且消除写放大），并由 worker 周期任务 `runtime-events-purge` 按 **保留期**（`WORKBENCH_RUNTIME_EVENTS_RETENTION_DAYS`，默认 30 天）清理 `occurred_at` 超期的行 ⇒ **容量与保留都有上限**；清理**不触碰审计**（`tests/test_runtime_events_postgres.py::test_purge_never_touches_the_audit_log` 守护），`GET /api/v1/runs/{run_id}/events` 的 cursor 断点读取语义不变（同一文件另有游标与序号单调断言）；③ **磁盘容量告警**：规则已写入 runbook「监控与告警」第 7 条（≥80% 预警 / ≥90% 严重），并已落成只读探针 `scripts/monitoring_probe.py`（本机实跑取证），但**渠道仍未接入任何环境** ⇒ 尚未生效，故本条不勾选（与 1.9 同因）。
- [x] 10.4 `redact_payload` 是否覆盖**值的形态**（不只看键名：工具标题 / 命令摘要 / 回复正文里可能带 key），且掩码**幂等**（重复脱敏不改变 payload hash）
      - **结论（2026-09-16 自查 + 修补）：两条判据均已覆盖。** 改造前只按**键名精确匹配**（`key.lower() in 白名单`）：判据①**未覆盖**（只读取证：值形态 **6/6 全漏**、键名另漏 5 个变体 `apiKey` / `X-Api-Key` / `authToken` / `api-key` / `clientSecret`）；判据②当时成立但无守护。现按「**键名归一 + 值扫描**」收口（用户拍板）；**读取输出（`to_public_dict`）与持久化写入（`serialization.encode_event`）共用同一入口**这一点未变（`app/runtime/contracts.py:180`）。
      - **① 键名归一**：`app/runtime/contracts.py:105-130` 复用审计侧 `key_tokens`（`app/audit/redaction.py:23-26`，先例已跨模块复用）做词元归一 ⇒ `apiKey` / `X-Api-Key` / `api-key` / `authToken` / `clientSecret` 与下划线小写同口径；**裸 `key` 单列不纳入**（`{"key": "plan-42"}` 是正常业务字段），`api` + `key` 组合另行命中。原 `SENSITIVE_PAYLOAD_KEYS`（精确匹配用）随之删除（全仓仅本文件两处引用，已核实）。
      - **② 值形态扫描**：`app/runtime/contracts.py:136-152` 三段**有限模式集**，字符串值统一替换为 `[已隐藏]`——`Bearer <token>` / 敏感词 `k[:=]v`（含引号包裹的 JSON 形态，负向断言避免与前者重复替换）/ 已知凭据前缀（`sk-` / `ghp_` / `glpat-` / `xox?-` / `AKIA`）；未命中的文本原样返回。
      - **③ 幂等取证**：掩码取值字符类排除 `[` `]`（`:122`）⇒ 已掩码片段不再被任一模式命中（不依赖「替换结果恰好相同」）；混合样本实测 `raw 5e724d83…` → `once = twice = thrice = 8e592fb1…`（逐字节一致），5 个凭据形态 `leaks` 为空。
      - **测试与反假**：`tests/test_runtime_contracts.py:115-237` 共 8 条（值形态 / 键名形态 / 反误伤 ×2 / 幂等 ×2 / 端到端 / 边界登记），**先红**（3 红 5 绿）后绿；**反假三轮**均按要求变红并还原——绕过值扫描 ⇒ 2 红、裸 `key` 纳入判定 ⇒ 反误伤红、去掉 `api`+`key` 组合 ⇒ 2 红（含既有 `api_key` 守护用例）。写库路径由真库用例 `tests/test_runtime_state_postgres.py:144-148`、`tests/test_runtime_events_postgres.py:158-184` 守护。
      - **全量回归**：`2147 passed / 0 failed / 0 skipped`（junit `tests="2147" errors="0" failures="0" skipped="0"`；基线 2139 ⇒ ＋8，无既有用例被跳过或删除）；`compileall` 退出码 0。
      - **未覆盖边界（登记，属有意保留）**：① `-p<password>` 短选项形态不覆盖（覆盖它必然误伤 `-production` 之类，`tests/test_runtime_contracts.py:214-222` 钉住该边界）；② `Bearer` 后不足 4 字符的 token 不替换（阈值取舍：过松会把普通词当凭据）；③ 值扫描是**有限模式集**（不认识的形态不替换），**不构成**「任意值内凭据都能识别」的承诺。
      - **未做（不得读成已验）**：历史已落库事件仍是**旧规则**产物（值内凭据可能仍在库内）⇒ 读取路径会按新规则再次收敛，但**库内存量数据未清洗**（无回溯重扫）；本批**已推送并取得 CI 结论**（2026-09-16 销账：提交 `7107fae` + `2a4bb82`，run `35064405339` **6/6 job success**，后端 `2051 passed, 96 skipped` = 2147 与本机一致、真库 `tests=68 skipped=0 failed=0`）。
- [ ] 10.5 金额 / 费用是否**全部整数分**（`usage_ledger` 与展示层；`daily_budget_cents` 已合规，其余待核）
      - **结论（2026-09-16 自查 + 最小加固，两分）：用量账本 / `daily_budget_cents` / 评测费用 / 展示层「全整数分」已查实（强证据）；任务预算 `budget`（`NUMERIC(18,6)`「元」+ 接口 float 链路）为**差距**，本轮按用户拍板做**最小加固**（运行时「元→分」换算精确化）并如实登记 ⇒ 按判据仍不勾选。** ① **用量账本**：`cost_cents` 为 `BIGINT NOT NULL`（`migrations/006_commercial_g0.sql:40`），应用层全 `int` 链路（`app/commercial/usage.py:18` 契约、`:31`/`:79` 拒绝负值、`:52`/`:120` 冲正写 `-cost_cents`、`:95`/`:102`/`:104-109` 读回与累计均 `int(...)`）；契约口径「`cost_cents` 为**整数分**」（`docs/api-contract.md:128`）。② **`daily_budget_cents`**：`BIGINT NOT NULL DEFAULT 0 CHECK (>= 0)` + 迁移注释「金额按宪法用整数分」（`migrations/023_conversational_agent.sql:58`/`:65-66`）；服务端校验拒绝非整数（`app/workforce/config.py:210-212` `_validate_non_negative_int`；真值用例含 `1.5` 拒绝，`tests/test_agent_config_store.py:220-221`）；前端按「元」输入、提交前 `Math.round(yuan * 100)`（`admin-web/src/features/workforceSettings/WorkforceSettingsPage.tsx:62`/`:78`，测试钉住 `12.34 → 1234`）、展示 `(cents / 100).toFixed(2)`（`:58`）。③ **评测费用**：`INTEGER NOT NULL DEFAULT 0 CHECK (>= 0)` + 注释「整数分（不用浮点）」（`migrations/033_evolution_eval.sql:47`）；runner 全整数（`app/evolution/runner.py:57`/`:161` 预算闸门 `int(...) * len(cases) * repeats`、`:180` fail-closed 文案）。④ **记忆预算闸门**：整数分累计（`app/memory/service.py:43`/`:49-51`/`:57`）。⑤ **展示层**：`formatCents` 纯整数运算（`admin-web/src/features/billing/state.ts:7-13`，含冲正负值；测试 `UsageBillingPage.test.tsx:19-30` 钉住整数分换算）⇒ 管理台金额面仅两处（用量与费用页 / 每日预算字段）已逐一核过；`companion-pwa` / `desktop` 全目录金额类键 grep **零命中**（无金额代码）。⑥ **运行时契约本身是整数分**：`RuntimeContext.budget_cents: int`（`app/runtime/contracts.py:62`）+ 反序列化强制 int（`app/runtime/serialization.py:148`）+ 策略闸门按分比较（`app/runtime/policy.py:44`）。
      - **差距（登记，不得读成已验）**：**任务预算 `budget` 不是整数分**——存储为「元」`NUMERIC(18, 6) NOT NULL CHECK (budget >= 0)`（`migrations/001_initial.sql:11`），链路全程 float（`app/domain.py:67` `budget: float`、`:187`/`:190`/`:196` 闸门比较；`app/main.py:332` `TaskCreate.budget: float`、`:345` `TaskView.budget: float`；`app/repository.py:223` `budget=float(row[7])`），仅在运行时换算为分（`app/runtime/service.py:97`；阴性核查：`app/` 全目录无其他「元→分」换算点——`* 100` 命中仅本处金额，其余 `* 1000` 为时延 / 过期时间）。**本轮最小加固（2026-09-16 用户拍板）**：换算由 `int(task.budget * 100)`（二进制浮点截断：`0.29 × 100 = 28.999…` ⇒ **28**，少 1 分）改为 `_yuan_to_cents`（`Decimal(str(amount)) * 100` + `ROUND_HALF_UP`，`app/runtime/service.py:29-36`）；测试钉住（`tests/test_runtime_adapters.py:219-243`：`0.29 → 29` / `19.99 → 1999`，**先红**（28/1998）后绿，反假变红后还原）。**未做**：存储改整数分、API 契约改分（`budget` 仍为「元」）、前端任务表单口径、亚分精度（`NUMERIC(18,6)` 可表示 `0.005` 元）拦截 —— 均属「地基改动」（宪法 §1.4），建议**另立专项**。
      - **全量回归**：`2149 passed / 0 failed / 0 skipped`（junit `tests="2149" errors="0" failures="0" skipped="0"`；基线 2147 ⇒ ＋2，无既有用例被跳过或删除）；`compileall` 退出码 0。
      - **未验证（不得读成已验）**：① 真实环境（staging / 生产）的存量任务预算值**未回溯核**（`budget` 为「元」、亚分精度未被拒绝；本机测试库无生产数据）；② 「任务预算改整数分」的迁移方案与兼容影响**未评估**（未立项，含 `TaskView` / `TaskCreate` 契约变更与 `1000` 元闸门口径）；③ 前端任务创建入口的存在性未核（管理台金额面仅上述两处；本项未展开任务表单核查）。
- [x] 10.6 生产是否**强制 `state_postgres`**（内存态仅限 development）
      - **结论（2026-09-16 自查 + 最小加固）：判据成立——生产强制链完整（配置层 + 装配层 + worker + 部署口径 + 预检 + 守护测试），边界已按用户拍板 fail-closed 收口 ⇒ 勾选。** ① **配置层**：`validate_runtime_settings` 非 development 强制 `storage_backend == "postgres"`（`app/settings.py:667-689`；`:676-677` 抛「生产环境必须使用 PostgreSQL 持久化仓储」、`:678-679` 内容仓储禁 memory、`:680-681` 数据库地址必须 PostgreSQL）；`env` 为**精确比较** ⇒ 任何非 `"development"` 值（含拼错 / 大小写偏差）都走强制分支（fail-closed 方向）。② **API 主进程（顺序保证）**：`app/main.py:154` 模块级先校验 ⇒ `:202` 再 `build_runtime_state_store(settings)` ⇒ `:213-220` 显式注入 `build_runtime_service(state_store=…)` ⇒ 生产必为 `PostgresRuntimeStateStore`。③ **装配层双保险**：`build_runtime_state_store` 的 memory 分支非 development 直接 `ValueError("生产环境禁止使用内存运行时状态仓储")`（`app/bootstrap.py:584-587`）；postgres 分支返回 `PostgresRuntimeStateStore`（`:588-598`）。④ **worker**：`configure_runtime` 非 postgres ⇒ `ValueError("Worker 必须使用 PostgreSQL")`（`app/worker.py:66-67`；守护 `tests/test_outbox.py:195`）；运行事件 purger 同为 Postgres（`:91-96`）；惰性装配 `_ensure_runtime`（`:170-185`）development 不装配、非 development 首次任务时装配、失败不吞。⑤ **beat**：不装配 runtime（`docker-compose.app.yml:128-134`）。⑥ **部署口径与预检**：compose 三服务（app `:38-39` / worker `:89-90` / beat `:139-140`）全部 `WORKBENCH_ENV=production` + `WORKBENCH_STORAGE_BACKEND=postgres`；`scripts/commercial_g0_preflight.py:63-73`、`scripts/worker_preflight.py:136-146` 双强制；`.env.staging.example:10` 为 postgres。⑦ **测试守护**：`tests/test_persistence_contract.py:12-16`、`tests/test_runtime_state_write_through.py:223-231`/`:234-245`、`tests/test_outbox.py:195`。
      - **边界与最小加固（2026-09-16 用户拍板）**：`build_runtime_service` 原 `state_store or RuntimeStateStore()` 缺省兜底**不带 env 校验** ⇒「生产强制」此前靠装配注入而非 fail-closed（唯一生产调用点 `app/main.py` 已注入、无实际触发点，但未来新增生产入口漏传会**静默回内存且无报错**）。现改为：非 development 且未注入 ⇒ 装配期抛 `ValueError("生产环境必须显式注入运行时状态仓储（禁止内存回退）")`（`app/bootstrap.py:631-632`，docstring 同步 `:623-624`）；守护 `tests/test_runtime_state_write_through.py:248-260`（**先红** `DID NOT RAISE` 后绿；**反假两轮**均按要求变红并还原：去抛错 ⇒ 本用例红；条件反转 ⇒ 本用例 + `tests/test_runtime_registry_wiring.py` 3 用例红）。`registry.py:130` / `service.py:68` 内层兜底**未改**（生产链路均经 `build_runtime_service` 注入；单测直接构造场景保留）。**保留边界（登记，属设计选择）**：`app/runtime/staging.py:31` 冒烟脚本用内存 store（`python -m app.runtime.staging` 工具，非生产链路）；worker 强制时机为「首次任务执行」而非进程启动（fork 安全的惰性装配）。
      - **全量回归（含真库）**：`2150 passed / 0 failed / 0 skipped`（junit `tests="2150" errors="0" failures="0" skipped="0"`；基线 2149 ⇒ ＋1，无既有用例被跳过或删除）；`compileall` 退出码 0。
      - **未验证（不得读成已验）**：① staging / 生产**真实环境**的部署配置未验收（属组 1.2 外部任务；本仓库 compose 已硬编码 production + postgres）；② worker 惰性装配的**生产路径本机未实跑**（静态核查 + 守护测试覆盖异常文本）。
- [ ] 10.7 是否存在**用户数据导出 / 删除**路径（宪法九章）；若无，明确归档与保留策略的补位口径
      - **结论（2026-09-16 自查 + 加固两项）：导出 / 删除路径均存在但覆盖不全；本轮按用户拍板补「导出包取回端点 + 过期清理」⇒ 仍不勾选（差距如实登记，不改码）。** ① **导出面**：真源 15 类导出类别已定义（`app/commercial/lifecycle.py:25-41`），但**仅 `memories` 已接线**（记忆层生命周期通道 `:264-276`），其余 14 类一律空数组（`UNIMPLEMENTED_EXPORT_CATEGORIES`，`:42-43`，注释自证「均无现成读取方法……不臆造字段」）。② **删除面**：`execute_delete`（`:355-393`）物理清场**仅清记忆层**（`:380-383`）；`skills` / `knowledge_governance` 的租户级 `delete_all_for_tenant`（`app/skills/store.py:80`、`app/knowledge_governance/store.py:80`）**已具备但未接线**；**「记录确认人」未实现**（真源 `docs/superpowers/specs/2026-09-06-commercial-g0-design.md:114` 要求「删除前必须生成最终导出包并记录确认人」，全仓无确认人落库点）。③ **保留面**：`DEFAULT_RETENTION_POLICY`（`:19`）**仅被部署预检读取、不被服务侧消费**（`:16-18` 注释自证）⇒ **保留策略无服务侧执行器**（与 10.1 同证据）。④ **用户级面**：commercial 路由面（`app/main.py:900-1000`）**均为租户级**，**无用户级个人导出 / 删除路径**（宪法九章「用户可删除、可导出」属差距）。
      - **本轮加固（用户 2026-09-16 拍板「两项都做」）**：**a) 导出包取回端点** `GET /api/v1/commercial/exports/{package_id}`（契约先行 `docs/api-contract.md:146-148`）——admin-only、租户由服务端从登录上下文解析、**跨租户与不存在统一 `404`**（不泄露他租户资源是否存在）、`expires_at <= now` 过期返 `404`「导出包已过期」；实现：异常 `ExportPackageExpired`（`app/commercial/lifecycle.py:57-64`，继承异常族但语义为 `404`、路由**先捕获**；先例 `DeletionNotPending → 409`）+ 服务 `get_export_package`（`:303-317`，`_ensure_admin` + 租户限定取包）+ 路由（`app/main.py:945-973`）。**b) 过期清理**：worker 任务 `purge_export_packages`（`app/worker.py:253-267`，复用既有 `_lifecycle_runner` 注入点、**未接线返回 0**）+ beat 排程 `export-packages-purge`（`:137-140`）+ `export_package_purge_interval_seconds`（默认 3600、范围 30–604800，`app/settings.py:538-546`）+ 两存储实现（InMemory `:202-209` / Postgres `:599-611` 单条 DELETE，迁移 028 既有索引支撑）；过期口径 = 包自身 `expires_at`（完成时刻 + 7 天，`EXPORT_PACKAGE_TTL` `:48-50`），清理后与「从未存在」不可区分；compose / 两 env 模板已同步（beat 与 worker 同值）。
      - **测试与反假**：+13 条（lifecycle 6 / API 2 / worker 4 / 真库 1）；**反假两轮真变红后还原**——① 去过期校验 ⇒ `DID NOT RAISE ExportPackageExpired` + `assert 200 == 404`；② 去租户归属限定 ⇒ `DID NOT RAISE ResourceNotFound` + `assert 200 == 404`；**全量回归（含真库）`2165 passed / 0 failed / 0 skipped`**（基线 2152 ⇒ ＋13）、`compileall` 退出码 0。
      - **未验证（不得读成已验）**：① staging / 生产**未验收**（属组 1 外部任务）；② 管理台**前端未接入**取回端点（本机未跑前端套件）；③ 真库清理用例只覆盖「删过期行」语义，**未做跨租户大规模数据演练**；④ CI **不覆盖真实 beat 排程下的「到点清理」现场**；⑤ 差距面（其余 14 类导出类别 / 删除清场扩围 / 确认人 / 保留策略执行器 / 用户级导出删除）**本轮明确不改码**，属后续专项；⑥ ~~本批**尚未推送 ⇒ CI 未取证**~~ ⇒ **已销账（2026-09-16）**：两提交已推送（`0de21be..fd564bd`），run `35077056683` **6/6 job success**（后端 `2068 passed, 97 skipped` = 2165 与本机一致；真库 `tests=69 skipped=0 failed=0`；沙箱加固与逃逸回归〔真容器〕/ 桌面端 / 手机伴侣端 / 网页管理台均 ✓）。
- [x] 10.8 「**发起人不得自审**」在**所有审批入口**都成立（含段二新增的对话入口）
      - **结论（2026-09-16 自查 + 加固）：8 类人工决议入口逐条核对，其余均已成立；唯一缝隙「任务审批允许发起人自审」已按用户拍板收紧（`403` + 待办剔除）+ 先红后绿 + 反假两轮 ⇒ 勾选。** ① **已成立入口（逐条证据）**：计划提案「发起人 ≠ 审批人」（`app/planner/service.py:163-167`，`_ensure_approver`）；运行内审批（`app/runtime/service.py:311-316`，`_ensure_decider`；且 `:91-100` 的 `_context` 以 `user_id=task.created_by` 构造运行身份 ⇒ 比对对象从根上就是发起人）；编排优化提案（`app/orchestration/service.py:159-163`）；技能版本复核（`app/skills/service.py:147-152`，`owner_id == user_id` ⇒ `PolicyError`）。② **对话入口（段二新增）复用运行内审批 ⇒ 同样成立**：对话创建运行（`app/conversation/execution.py:260-276`）时承载任务 `created_by` = 触发者；其审批的**唯一决议路径**是运行审批端点（`app/main.py:3200-3237`，`approval_id` = 承载计划步 id）⇒ 由 `_ensure_decider` 覆盖，**不存在绕开自审校验的独立入口**。③ **语义 N/A（登记理由）**：账号注册审批（`app/accounts/service.py:178-214`）仅 `super_admin` 可办、申请人**尚无账号** ⇒ 不存在「本人 = 审批人」；知识文档复核（`app/knowledge_governance/service.py:174-213`）为 `ensure_can_manage` + **系统到期触发** ⇒ 无「发起人」概念。④ **未接线入口已登记**（不构成入口）：`app/agent_services.py:101-152`、`app/capabilities.py:34-56`（无实例化）。⑤ **唯一缝隙与加固**：判据来源 `docs/openmausbot-source-study-and-adaptation-plan.md:155` §5.2 第 3 条（已定「仅 ceo/超管 + 发起人不得自审」），但任务审批入口原仅 `ensure_can_approve`（`app/repository.py:35-64` 无自审校验）⇒ CEO 自建需审批任务可自批（**先红值 `assert 200 == 403`**）。现按 2026-09-16 用户拍板收紧：路由**先取任务做归属比对**、`task.created_by == context.user_id` ⇒ `403`「发起人不能审批自己创建的任务」（`app/main.py:2989-2999`；检查顺序「403 先于 409」与既有审批入口一致；`store.approve` 生产唯一调用点即本路由 ⇒ 无误伤面）；待办列表**同口径剔除**（`app/approvals.py:64-71`，**先红值 `assert 2 == 1`**），避免展示点不动的待办。⑥ **影响面（如实）**：该缝隙原影响为「状态闸门自放行」（`pending_approval → queued` + 事件/通知），**不解锁工具执行**——执行解锁仅在运行内审批决议后的重跑（`app/main.py:3246-3254`）⇒ 无执行绕过面。⑦ **测试与反假**：`tests/test_control_plane.py:73-105`（CEO 自建 → 本人 `403` 且 detail 含「发起人」→ 另一审批人 `200`）＋ `tests/test_approvals_service.py:184-193`（CEO 视角列表仅剩他人条目）；**先红后绿**；**反假两轮**均按要求变红并还原——① 去路由校验 ⇒ 用例红（`assert 200 == 403`）；② 列表过滤条件反转（`!=` → `==`）⇒ 用例红（items 由 `['task-other']` 变 `['task-own']`）。
      - **全量回归（含真库）**：`2152 passed / 0 failed / 0 skipped`（junit 原文 `tests="2152" errors="0" failures="0" skipped="0" time="122.495"`；DSN 指向本机测试库 `wb-test-postgres-1:55433/workbench_test`）——基线 2150（10.6 收口）⇒ **＋2 恰为本批两用例**，无既有用例被跳过或删除；静态 `compileall -q app` 退出码 0。
      - **保留边界（登记，属设计选择；可用性代价已由用户拍板接受）**：单管理员部署（仅一名 `ceo`/`super_admin`）下，该管理员自建的需审批任务**无人可批**（须另有第二名 `ceo`/`super_admin` 审批）——与计划提案 / 运行内审批的既有锁死口径一致（非本批引入的新语义）。
      - **未验证（不得读成已验）**：① staging / 生产环境**未验收**（属组 1 外部任务）；② 前端**未改动**（`companion-pwa` 任务待办仍走既有端点 `/tasks/{id}/approve` 路径不变），本机未跑前端套件（CI 前端 job 覆盖）；③ 文档改动无独立测试（不构成对外证据）。
- [x] 10.9 **出网归口唯一性**：除受控抓取 / 知识适配器外，是否还存在第二条出网路径（宪法 4.8 + 段二 A4）
      - **结论（2026-09-16 自查，纯只读）：判据成立 ⇒ 勾选。** 判据来源＝段二 A4（`docs/dsh-integration-preflight-checklist.md:27`：工具进程**不允许出网**；联网需求由**工作台侧受控抓取 / 知识适配器**归口；模型调用由工作台侧发起、容器不持有模型密钥）。① **容器侧零外网出口（五层证据）**：a) **装配 fail-closed**——网络面恒为内网桥（CLI `--network` `app/tool_execution/executor.py:156-157`、SDK `network` `:179`），生产装配 `from_settings` **不传** `network_name` ⇒ 恒用默认 `INTERNAL_NETWORK_NAME="workbench-exec-internal"`（`:51` / `:268-284`），且每次起容器前校验既有网络 `Internal=True`（`:450-467`：`internal=False` ⇒ `ToolExecutionConfigError`「非内网桥（internal=False），拒绝执行」；缺失则 `create(internal=True)`）；部署侧同口径（`scripts/ensure_exec_internal_network.py:39-50`）。b) **工具面双闸门**：④-1 只读白名单 `ls/cat/head/tail/wc/stat/file`（`app/tool_execution/blacklist.py:35`）＋ ④-2 A4 网络与外联黑名单（`curl/wget/nc/ncat/netcat/socat/telnet/ssh/scp/sftp/ftp/tftp/ping/traceroute/dig/nslookup/host/ntpdate/iptables/nft/ip/ifconfig/route/tcpdump`，`:45-47`）；dsh 侧工具面另收窄至只读检视集（`app/runtime/adapters/dsh.py:110`）。c) **真容器实测零出网**：DNS 解析不外泄（`gaierror`）、`1.1.1.1:443` / `8.8.8.8:53` / 裸 UDP DNS / 云元数据 `169.254.169.254` 全部 `Network is unreachable`（`docs/sandbox-boundary-decision.md:78-80`，按 §3.3 加固口径 Probe 1）。d) **真容器 + 真实供应商双轮对照**：容器内 `supplierDomain = BLOCKED`、`gateway = REACHABLE status=403`（`docs/dsh-integration-preflight-checklist.md:912`；网关挂双网「只有它能出网」、执行容器只在内部网 `:902`）。e) **联网类插件与遥测兜底关闭**：13 项禁用插件含 `web` / `web-search-deepseek` / `web-fetch-http` / `tool-web` / `session-telemetry-otel`（`app/runtime/adapters/dsh.py:91-105`），`DSH_PERMISSION_MODE=read-only`（`:24`）、`DSH_TELEMETRY_DISABLED=1`（`:26`）、启动期剖面锁死自检（`:167-177`）。
      - **② 容器内无供应商密钥（不存在「有 key 自行联网」形态）**：容器 env 白名单仅「网关内网地址 + 短期网关令牌」两项（`dsh.py:45`），装配期逐键 fail-closed（`executor.py:121-133`），`build_token_env` 剔除供应商密钥字段名（`dsh.py:69-70`）并自检白名单（`:73-77`）。
      - **③ 工作台侧出网调用点逐条枚举（12 处，全部外置配置 + 显式超时）**：**受控抓取归口（A4 允许）** `app/content/scraper.py:71-75`/`:242`（域名白名单 `:238`、robots fail-closed `:186-202`、限速 `:212-221`、字节上限随调用传入 `:242-244`）；**知识适配器归口（A4 允许）** `app/knowledge.py:69`（共享 `httpx.Client`，构造见 `app/bootstrap.py:1229`）；**模型类 4**：内容模型 `app/content/openai_compatible.py:32`、规划模型 `app/planner/generator.py:106`、Embedding `app/memory/embedding.py:36`、网关上游 `app/model_gateway/upstream.py:83-88`/`:112`（传输级重试上限、收到响应后不重试）；**发布 / 集成类 3**：公众号发布 `app/content/publisher.py:50`/`:52`、Webhook 通知 `app/notifications.py:53`、SSO `app/accounts/sso.py:105`（https 强制 `:80`）；**内部受控 3**：外部 Runtime 传输 `app/runtime/adapters/common.py:68`、边车回传 `app/exec_callback/server.py:86`（预共享密钥）、网关控制面令牌 `app/tool_execution/gateway_token.py:67`。
      - **④ 三项阴性核查**：全仓无硬编码第三方域名（仅文档样例 `app/content/safety.py:108-184`、`app/model_gateway/server.py:369` 自身绑定址、`app/runtime/staging.py:49-68` 冒烟桩）；无遥测埋点（`analytics|telemetry|sentry|datadog|usage_report` 仅命中 dsh 禁用清单）；无第二类出网原语（`smtplib|ftplib|paramiko|websocket` 零命中）；两前端 apiBase 仅本产品 API（admin-web 12 处 / companion-pwa 2 处），desktop 仅本产品 URL + 构建期注入更新源。
      - **⑤ 治理闭环**：C1（电脑控制）/ C2（浏览器操作）不立项，明写「**不引入第二套出网归口**」（`docs/capability-ownership-map.md:48`/`:76`、`docs/feature-inventory.md:94`）。
      - **未验证（不得读成已验）**：① 真实生产宿主 / staging **未复测**（`--internal` 行为不得由本机结论外推生产拓扑，`docs/sandbox-boundary-decision.md:139`；属组 1 外部任务）；② §B17「加固形态下复跑」**未做**（`docs/dsh-integration-preflight-checklist.md:920`，门禁项独立成立）；③ **网关自身出网面未独立自检**（本次核的是「容器侧零出网 + 工作台侧调用点枚举」；网关作为唯一模型出网归口的 host 白名单 / 出网加固未单独演练）；④ 用例 41（云元数据）**反假不可构造**（`docs/sandbox-boundary-decision.md:135`）；⑤ 阴性 grep 结论**限于当前快照**，不构成运行时阻断证据（运行时阻断依赖 ①②③ 的机制与实测）；⑥ **宪法 4.8 逐依赖登记表未逐条核对**（全仓仅有外部依赖验收 / 执行计划类文档，未发现逐依赖的用途 / 密钥归属 / 重试 / 降级 / 验签 / 对账登记表 ⇒ 作为边界登记）。
      - **推送与 CI 取证（2026-09-16 销账）**：本批回写提交 `22b4903` 已推送，run `35079935924` **6/6 job success**（后端 `2068 passed, 97 skipped` = 2165 与本机一致；真库 `tests=69 skipped=0 failed=0`；沙箱加固与逃逸回归〔真容器〕/ 桌面端 / 手机伴侣端 / 网页管理台均 ✓）。⚠️ 边界保留：本销账回写提交（docs-only）触发的后续 run 不再另行登记（口径同 10.4–10.11）。
- [x] 10.10 **`reason` 不含自由文本**：工具类动作码的**取值**是否有枚举校验（而非只做键名白名单）
      - **结论（2026-09-16 自查，纯只读）：判据成立 ⇒ 勾选。** 核查范围＝**工具类**面（`tool.executed` / `tool.blocked` 两个动作码 + `027` 表 `reason_code`）。
      - **① `reason` 取值全为受控枚举或空，绝无自由文本**（工具面全部 4 个审计落点逐一核对）：`tool.executed` 恒 `None`（`app/tool_execution/service.py:528-541`）；`tool.blocked` 取 `ReasonCode.value`（`service.py:603-647`，两分支 `:625` / `:644`）；回传令牌守卫复用 `tool.blocked` 写固定字面量 `"not_authorized"`（`app/tool_execution/token_binding.py:142-159`，值＝`ReasonCode.NOT_AUTHORIZED`）；到期清理复用 `run.approval_decided` 只写 `status="expired"`、**连 `reason` 键都不写**（`app/tool_execution/cleanup.py:137-144`）。失败语义表 9 个键的 `reason_code` 全部是 `ReasonCode` 枚举成员（`service.py:68-82`）。
      - **② `reason_code` 取值有真正的枚举校验（而非只做键名白名单）**：9 值受控枚举 `ReasonCode(StrEnum)`，docstring 明写「自由文本一律不得落库 / 落审计」（`app/tool_execution/store.py:25-36`）；写入侧运行时校验 `_validate` → `ReasonCode(action.reason_code)`，未知值抛 `ValueError`（`store.py:77-90`），**InMemory 与 Postgres 两个实现共用同一校验**（Postgres `upsert` `:275`；读取侧水合 `ReasonCode(str(row[20]))` 往返归一 `:245`）。守护测试齐备：9 值精确集合（`tests/test_tool_action_store.py:56-68`）、负向「`free_text_reason` 被拒」（`:70-74`）、9 值逐值接受（`:76-86`）、PG 负向「`free_text_日本語` 被拒」（`tests/test_tool_action_store_postgres.py:200`）、PG 枚举往返（`:329-341`）。
      - **③ 动作码取值本身是枚举 + 三重闸门**：`tool.*` 均为 `AuditAction(StrEnum)` 成员（`app/audit/models.py:11-90`），工具面 4 个落点逐一无裸字符串（见 ①）；**查询侧**未知动作码 `AuditAction(raw)` → `422`（`app/main.py:2887-2897`，端点 `:2909-2925`）；**读取侧**水合 `AuditAction(str(row[1]))` 未知值即抛（`app/audit/store.py:140`）。
      - **④ 键名白名单与取值枚举的分工**：`ALLOWED_DETAIL_KEYS`（`app/audit/models.py:97-163`）是**键名**白名单（拒未声明字段 + 嵌套敏感键递归拒绝 `:196-200`）；**取值**的枚举收口在产生侧（①②③）——即本判据问的「而非只做键名白名单」在工具类面**不成立**（键名白名单之外，取值另有枚举校验）。
      - **边界登记（不改码，如实登记）**：a) **DB 层无 CHECK 约束**——迁移 `027` 的 `reason_code` 列仅注释声明「受控枚举码（9 值）…自由文本一律不落」（`migrations/027_dsh_tool_execution.sql:73`，无列级 CHECK；`workbench_audit_log.action` 同为 `TEXT NOT NULL` 无 CHECK，`migrations/001_initial.sql:28`）⇒ 应用层 `_validate` 是唯一闸门（绕过应用层直写 SQL 才可能落非枚举值，与 10.1 已登记的「DB 层账号权限未管」同域）。b) **非工具类的审批驳回理由落审计 `reason` 键为管理员输入自由文本**（≤500 字：账号驳回 `app/accounts/service.py:197-213`、计划提案驳回 `app/planner/service.py:114-127`、编排提案驳回 `app/orchestration/service.py:131-146`，均同时落业务列 `rejection_reason`）——**超出本条「工具类」范围**，属审批决议业务数据的有意设计；若未来要求审计零自由文本需专项口径变更。c) 非工具面受控字面量（`"totp_required"` / `"no_binding"` / `"task_unavailable"`，`app/accounts/service.py:265`/`:440`、`app/main.py:2797`/`:2823`/`:3085`）无统一枚举定义——值受控但散落。d) 写入侧无 `AuditAction(...)` 归一转换（依赖类型标注 + 调用点自律；查询侧与读取侧有枚举闸门）。
      - **未验证（不得读成已验）**：① staging / 生产环境**未复测**（属组 1 外部任务）；② 文档改动无独立测试（不构成对外证据）。
      - **推送与 CI 取证（2026-09-16 销账）**：本批回写提交 `ae14a9d` 已推送，run `35081745668` **6/6 job success**（后端 `2068 passed, 97 skipped` = 2165 与本机一致；真库 `tests=69 skipped=0 failed=0`；沙箱加固与逃逸回归〔真容器〕/ 桌面端 / 手机伴侣端 / 网页管理台均 ✓）。⚠️ 边界保留：本销账回写提交（docs-only）触发的后续 run 不再另行登记（口径同 10.4–10.12）。
- [x] 10.11 **密钥不进前端产物**：构建产物 / 静态资源中不得出现密钥或内部地址（宪法 4.1 禁止项 + 8.6 上线自检）
      - **结论（2026-09-16 自查）：判据成立 ⇒ 勾选。** 五层证据：① **机制层**：两前端 `vite.config.ts` 均无 `define` / 无 `envPrefix` 覆盖（`admin-web/vite.config.ts:1-9`、`companion-pwa/vite.config.ts:1-8`；默认仅 `VITE_` 前缀可进客户端）；桌面端打包 `files` 白名单仅 `src/**` / `web/**` / `package.json`（`desktop/electron-builder.yml:11-14`），更新源构建时 fail-closed 注入（`:22-27`）。② **源码层（grep 全扫描）**：三包 `src/` / `scripts/` / `public/` 密钥类模式（`sk-` / `ghu_` / `ghp_` / `AKIA` / `PRIVATE KEY` / `postgres://` / `redis://`）**零实质命中**（全部命中项为业务代码：登录密码输入框 `companion-pwa/src/features/session/LoginPage.tsx:21-72`、审计文案 `admin-web/src/features/auditLog/types.ts:53-54`、安全测试串 `desktop/src/config.test.cjs:98`）；内部地址类（`192.168.` / `10.x` / `172.16-31` / 容器名）**零命中**；静态资源仅两个 SVG 的 `xmlns="http://www.w3.org/2000/svg"`（标准命名空间）。③ **产物层（实测，最强证据）**：本机 `npm run build`（两前端均成功）⇒ dist 全文件正则扫描：密钥类 5 模式 **0**、内部地址类 4 模式 **0**、`VITE_*` 变量名 **0**（构建期完全替换）；产物内 fallback 值仅 `http://localhost:8000/api/v1`（admin-web 11 处 / pwa 2 处）与 `super_admin`（11 / 2 处）——开发便利默认，**非密钥非内部地址**。④ **仓库卫生层**：根 `.gitignore` 排除 `dist/` / `.env` / `.env.*` / `*.pem` / `*.key` / `desktop/web/`（`companion-pwa/dist/` 由 `tests/test_pwa_assets.py:132-133` 守护）；三 env 模板全占位符（`.env.sso.example:59` / `.env.staging.example:23-24` / `.env.example:14-15`）；CI 三个前端 job **无 secrets / env 注入**（`.github/workflows/ci.yml:49-106`）。⑤ **守护测试层（42 项全绿）**：Dockerfile **不得**烤入 5 个密钥赋值（`tests/test_container_assets.py:56-66`）、**不得** `COPY tests` / `COPY admin-web`（`:69-73`）、`.dockerignore` 排除 `.env*` 与 `admin-web`（`:91-105`）；CI 三前端 job 与 build 守护（`tests/test_ci_assets.py:47-57`）。
      - **关联核实（开发身份 fallback 的风险链，已闭合）**：产物内 `super_admin` fallback 是否可利用——后端 `current_user` 在**非 development 环境只信 `Bearer` 令牌**（`app/main.py:548-554`；X-Tenant-Id / X-User-Id / X-User-Role 仅 development `elif` 分支生效），与「only for development configuration」口径一致（`docs/superpowers/plans/2026-09-06-knowledge-access-admin.md:105`）。`settings.env` 默认 `development`（`app/settings.py:11`）的残余面（非编排部署漏配）已由四重缓解覆盖：compose 三服务硬编码 `production`（`docker-compose.app.yml:39/90/142`）+ 三个预检脚本强制非 development（`scripts/commercial_g0_preflight.py:64-65`、`scripts/worker_preflight.py:136-140`、`scripts/runtime_staging_preflight.py:108`）+ `validate_runtime_settings` 全套强制（`app/settings.py:687-700`）+ `docs/private-deployment-runbook.md:10` 条款 ⇒ 与 N2 已登记未验证项（开发环境 X-User-Role 伪造）关联，不重复立条。
      - **未验证（不得读成已验）**：① staging / 生产**真实构建与部署未跑**（属组 1 外部任务；CI 构建为干净环境、无 API 地址注入）；② **前端生产产物注入流程未定义**（`VITE_API_BASE_URL` 指向生产 API 的注入点无真源定义）——CI 产物带开发 fallback `localhost:8000`，直接用于部署会指向 localhost（**功能问题、非泄漏**），登记待组 1.2 一并验收；③ 桌面端**安装包本体未实测扫描**（受签名 / 打包环境限制，属组 6；内置 web 部分即 admin-web/dist 已扫描、壳源码已 grep）；④ 文档改动无独立测试（不构成对外证据）。
      - **推送与 CI 取证（2026-09-16 销账）**：本批回写提交 `980dd32` 已推送，run `35078247188` **6/6 job success**（后端 `2068 passed, 97 skipped` = 2165 与本机一致；真库 `tests=69 skipped=0 failed=0`；沙箱加固与逃逸回归〔真容器〕/ 桌面端 / 手机伴侣端 / 网页管理台均 ✓）。⚠️ 边界保留：本销账回写提交（docs-only）触发的后续 run 不再另行登记（口径同 10.4–10.8）。
- [x] 10.12 **`027` 迁移的升级与回退演练**（含对既有表 `workbench_run_records` 的约束增补；宪法 4.4 备份与恢复；登记口径见 `docs/change-record.md`）
      - **结论（2026-09-16 演练，用户已授权全链路写操作）：判据成立 ⇒ 勾选。** 环境：**一次性独立容器**（digest 钉死 `pgvector/pgvector:0.8.0-pg16@sha256:a132765…`、仅绑 `127.0.0.1:55600`、无卷、`POSTGRES_HOST_AUTH_METHOD=trust`；库 `workbench_drill` + 恢复库 `workbench_restore`），**非生产、不碰** 既有 `wb-test-*` / `infra-*` 栈。① **前滚**：真实迁移器 `app.migrations.apply_migrations` 对空库应用**全部 34 项**迁移（`001_initial`→`034_runtime_events`，含 `027_dsh_tool_execution`）。② **对象核对**（只读 SQL）：约束 `workbench_run_records_run_tenant_unique`=1；`workbench_tool_actions`（21 列 / CHECK 4 / FK 1 / PK 1 / 索引 4）、`workbench_execution_idempotency`（10 列 / CHECK 2 / FK 3 / PK 1 / 索引 2）。③ **备份 / 恢复（宪法 4.4）**：容器内 `pg_dump --format=custom`（退出码 0、102550 字节）→ `createdb workbench_restore` → `pg_restore --clean --if-exists`（退出码 0；首次因缺 `-U postgres` 以 OS 用户连库被拒 `role "root" does not exist`，补角色后成功）→ 恢复库核对与源库**逐项一致**（34 项 / has_027=1 / 约束与两表计数全同）。④ **回退 `027`**（按 change-record 2026-09-13 已登记口径、**不用 CASCADE**）：`DROP TABLE workbench_tool_actions` → `DROP TABLE workbench_execution_idempotency` → `ALTER TABLE workbench_run_records DROP CONSTRAINT workbench_run_records_run_tenant_unique` → `DELETE FROM workbench_schema_migrations WHERE version='027_dsh_tool_execution'`（`DELETE 1`）⇒ 核对归零：33 项 / has_027=0 / 约束=0 / 两表 `<none>`。⑤ **再前滚（回退可逆）**：重跑迁移器**仅应用 1 项＝`027_dsh_tool_execution`**，对象计数与 ① 完全一致。⑥ **销毁**：`docker rm -f wb-027-drill-pg`（退出码 0），无容器 / 卷残留；dump 仅存于容器 `/tmp`、随销毁消失，未落宿主、未进仓库。
      - **未验证（不得读成已验）**：① **staging / 生产目标库未演练**（AI 不连生产；本演练为一次性本地空库；生产库上的升级 / 回退仍须按组 1 外部流程在服务器执行并回传）；② 回退演练**不覆盖有数据场景**（异构回填风险不在本条范围）；③ **宿主 `pg_dump` / `pg_restore` 路径未跑通**（宿主无客户端 ⇒ 备份恢复走容器内镜像自带客户端等价命令；`scripts/migration_backup_drill.py` 的宿主执行面未演练）；④ 备份**未落盘加密**（`WORKBENCH_BACKUP_ENCRYPTION_KEY` 面未演练；空库无敏感数据且随容器销毁 ⇒ 边界登记）；⑤ 文档改动无独立测试（不构成对外证据）。
      - **推送与 CI 取证（2026-09-16 销账）**：本批回写提交 `a312182` 已推送，run `35080905772` **6/6 job success**（后端 `2068 passed, 97 skipped` = 2165 与本机一致；真库 `tests=69 skipped=0 failed=0`；沙箱加固与逃逸回归〔真容器〕/ 桌面端 / 手机伴侣端 / 网页管理台均 ✓）。⚠️ 边界保留：本销账回写提交（docs-only）触发的后续 run 不再另行登记（口径同 10.4–10.11）。

**判据**：每条给出「结论 + 证据（`文件:行`）」；未查的写「未验证」。

---

## 开工顺序建议

1. **组 1 先行**（只读部分今天就能做：1.1 → 1.5），它一次解锁最多 ❌，且会暴露配置/迁移层面的真实问题；
2. 组 2、组 3 并行（都需要密钥/账号）；
3. 组 4（平台授权到齐后）；
4. 组 6、组 7（采购证书/真机）；
5. 组 5 只等对端契约，拿到即做。

## 回传与判读

每组完成后，把命令输出与证据（**脱敏**）回传；由我判读并更新 `docs/delivery-readiness-checklist.md` 的对应行（状态真相只在该文件维护，本文件只勾选进度）。
