# 组 1「真实环境验收」基础设施输入索取表（草案 · 待基础设施方 / 运维回执）

> **本文件性质**：可直接转发给基础设施方 / 运维的**输入索取表 + 回执模板**；是索取草案，**不是已确认的部署契约**，**不改变任何门禁状态**。
> **编制日期**：2026-09-16　**对应清单**：`docs/delivery-remaining-checklist.md` 组 1（阻塞项 1，「解锁项最多，建议先做」）
> **判据与证据口径**：`docs/external-dependency-acceptance-plan.md`（§2 通用约定 · 项 1 / 项 4）；只读核验命令：`docs/readonly-verification-runbook.md`
> **范围边界**：本表**只覆盖基础设施 / 运维**提供的输入（主机、PG、Redis、对象存储、账号、凭据注入、备份介质、通知渠道）。外部 Runtime（RAGFlow / AgentScope）、平台账号（公众号）、真实模型、GEO 契约、IdP 等各由对应方提供，见 `runtime-onboarding-request.md` / `platform-account-onboarding.md` / `geo-contract-request.md`。

---

## 0. 结论：值一到即可执行

我方已完成「无外部输入即可执行」的全部只读面（2026-09-16）：

1. 三个预检脚本的 **pass 路径**已本机只读预演（合成非本地值）：`staging_preflight.py` ⇒ 36 项 `[pass]`；`runtime_staging_preflight.py` ⇒ 20 项；`worker_preflight.py --offline` ⇒ 6 `[pass]` + 1 `[skipped]`，均 `exit=0`。三个脚本均为**纯元数据校验、零网络请求**——未配置环境的 `fail` 只是缺值，不是脚本能力问题。
2. `readonly-verification-runbook.md` 的命令与当前代码**无漂移**（端点 / 9 条 SQL / 复合外键 / 脚本参数逐面核对）。
3. 总闸门：`py scripts/staging_preflight.py` 返回 `pass`。

⇒ **本表各项就是缺的「值」**；到位后按 runbook 直接执行，无需我方再改代码。

---

## 1. 索取表（14 项）

| # | 事项 | 要求与验证方式 | 为什么必需 | 填写 |
| --- | --- | --- | --- | --- |
| I1 | 独立 Linux 主机（部署 / 探针运行机） | 能访问 staging 各服务；与开发机、生产分离 | 组 1 只读核验（`runbook` §2/§3）与迁移演练都在该主机上执行 | |
| I2 | 部署机安装 PostgreSQL 客户端 | `psql` / `pg_dump` / `pg_restore` 可用（`postgresql-client`；版本与被操作库兼容） | **2026-09-12 实测**：缺客户端时 `migration_backup_drill.py --phase backup` 在「pg_dump 可用性」一步直接 `fail`；`psql` 是九条只读 SQL 的执行工具 | |
| I3 | 独立 PostgreSQL 实例（非 localhost） | 提供主机名 + 库名 + **应用账号**；地址不得为 `localhost` / `127.0.0.1` / `::1` / `0.0.0.0` | 预检「PostgreSQL 独立主机」fail-closed（`scripts/staging_preflight.py:88-99`）；迁移、仓储、备份演练都打这个库 | |
| I4 | **pgvector 扩展**（迁移 001 硬依赖） | 目标库执行 `psql "$DSN" -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector'"` ⇒ **有一行返回** | `migrations/001_initial.sql:1` 第一行即 `CREATE EXTENSION vector`；官方 `postgres` 镜像不带该扩展，缺它**迁移直接失败** | |
| I5 | 只读库账号（DBA 执行） | 按 `runbook` §1.1：`CREATE ROLE workbench_ro LOGIN PASSWORD '<强口令>'` → `GRANT CONNECT` + `GRANT pg_read_all_data` → 核对属性应得 `workbench_ro|f|f|t`。（多租户共用实例若不接受 `pg_read_all_data`，改用显式 `GRANT SELECT` + `ALTER DEFAULT PRIVILEGES`，runbook 已写明） | 只读核验清单（1.5）用它在目标库跑 9 条 SQL；`pg_read_all_data` 自动覆盖未来迁移新建的表 | |
| I6 | 目标库「已应用迁移清单」读数 | 执行 `SELECT version, applied_at FROM workbench_schema_migrations ORDER BY version;` 回传逗号拼接结果（填入 `WORKBENCH_APPLIED_MIGRATIONS`）。**若该表不存在**：说明迁移非由应用执行——按实际执行记录登记并注明，**不要凭猜填写** | `staging_preflight.py` 与 `migration_backup_drill.py --phase list` 均据此比对；本机实测清单不符会被拒（`--phase list` 报「迁移清单不一致」） | |
| I7 | 独立 Redis（非 localhost） | 独立实例或独立逻辑库，提供 `redis://` / `rediss://` 地址 | 预检「Redis 独立主机」（`scripts/staging_preflight.py:90-99`）；Worker 实跑（1.10）依赖 | |
| I8 | 独立对象存储（非 localhost + 独立命名空间） | 实例地址 + **独立命名空间**（示例 `staging-customer-a`）+ 凭据 | 预检「对象存储独立主机 / 命名空间」（`scripts/staging_preflight.py:92`、`:103`）；租户数据隔离要求 | |
| I9 | 部署密钥系统注入双密钥 | 注入 `WORKBENCH_AUTH_SECRET` 与 `WORKBENCH_BACKUP_ENCRYPTION_KEY`：**均 ≥32 位、互不相同**、只经密钥系统注入 | 商业化 G0 预检项「双密钥 ≥32 且分离」（`scripts/commercial_g0_preflight.py`）；组 2 轮换的前置 | |
| I10 | 可登录的租户 + 超管账号（或声明首次部署） | 二选一告知：① 已有超管账号（手机号 / 口令 / TOTP）；② 首次部署：走 `POST /api/v1/auth/registrations` + 部署注入 `WORKBENCH_BOOTSTRAP_TOKEN` | 只读核验 §3（令牌获取）与后续全部验收都需登录；两种情形命令已在 `runbook` §1.3 备好 | |
| I11 | 备份介质 + 独立备份加密密钥 + 维护窗口 | 可写备份文件的介质；备份加密密钥（与 I9 双密钥分离）；一次维护窗口 | `migration_backup_drill.py`（迁移 / 回滚演练，1.6 / 1.11）属**写操作**——先备条件，执行需我方另行授权 | |
| I12 | **专用**探针账号（并发压测） | 独立手机号 + 口令；**不能用真人账号**（`login_throttle` 场景会把它短时锁定） | `scripts/staging_concurrency_probe.py` 前置；1.8（写操作，需授权） | |
| I13 | 死信通知渠道（可选） | IM webhook 或 SMTP 任一 + 收件人；也接受「本轮不接渠道」——死信仍可查可重放，判据相应调整为跳过通知项 | 1.10 判据「失败进死信并能通知」；`worker_preflight.py` 联网层核对此项 | |
| I14 | 变量对照单回执 | 以 `.env.staging.example`（模板 205 行，迁移清单已同步 34 项）为对照单，逐项回填「已注入 / 待注入 / 不适用」+ **元数据值**（主机名、命名空间、版本、渠道地址）；**密钥值一律不回传** | 「值一到即可执行」的对照单；1.3 / 1.4 / 1.4.1 预检即按它比对 | |

**交接方式**：元数据（主机名 / 库名 / 命名空间 / 版本 / 渠道地址）登记进 `.env.staging`（模板 `.env.staging.example`）；**密钥值只经部署密钥系统注入**，不写入任何环境文件、不进仓库。

---

## 2. 回执模板（复制填写）

| 项号 | 状态（就绪 / 待办 / 不适用） | 脱敏值或说明（口令、密钥一律 `***`） | 备注 |
| --- | --- | --- | --- |
| I1 | | | |
| I2 | | | |
| I3 | | | |
| I4 | | | |
| I5 | | | |
| I6 | | | |
| I7 | | | |
| I8 | | | |
| I9 | | | |
| I10 | | | |
| I11 | | | |
| I12 | | | |
| I13 | | | |
| I14 | | | |

回执人 / 日期：__________　环境标识（`WORKBENCH_STAGING_ID`）：__________

---

## 3. 安全红线（先读）

1. **不要把 DSN、口令、密钥、令牌贴进聊天或邮件**；回传一律用 `***` 替换（`runbook` §0 第 3 条）。
2. 密钥只由部署密钥系统注入；**进了仓库的密钥按「已泄露」处理——更换，而不是删掉那一行**。
3. 本轮**只准备输入，不执行**任何写命令（迁移 / 回滚演练、并发压测、密钥轮换；也**不要直接启动应用服务**——启动即跑迁移）（`runbook` §0 第 4 条）。
4. 我方 AI **不连** staging / 生产：只读核验由你在服务器上执行、回传输出后判读（`runbook` §0 前言）。

---

## 4. 到位后的执行与判据（1.1–1.5 摘要）

| 判据 | 命令 / 方式 | 期望 |
| --- | --- | --- |
| 1.1 | `psql` 查 `pg_extension`（见 I4） | 有一行返回 |
| 1.2 | 配置填好（I3 / I6 / I9 等；见 I14 对照单） | `WORKBENCH_ENV≠development`、`WORKBENCH_STORAGE_BACKEND=postgres` |
| 1.3 | `py scripts/staging_preflight.py` | `pass`（36 项，纯元数据、零网络） |
| 1.4 | `py scripts/runtime_staging_preflight.py` | `pass`（20 项；Runtime 元数据由外部 Runtime 方按另一份索取表提供） |
| 1.4.1 | `py scripts/worker_preflight.py --offline` | `pass`（6 项 + 1 `skipped`） |
| 1.5 | 只读核验清单（`runbook` §1–§4） | 全绿：pgvector 存在 / 迁移 022 复合外键存在 / 归一风险 0 行 / 绑定侧未纳管为空 |

---

## 5. 待确认（本文件不猜测）

| # | 事项 | 状态 |
| --- | --- | --- |
| U1 | 主机发行版与 PostgreSQL 版本（决定 `postgresql-client` 版本对齐） | 待提供 |
| U2 | Redis 形态（独立实例 / 独立逻辑库） | 待提供 |
| U3 | 对象存储类型与凭据形态 | 待提供 |
| U4 | 维护窗口时段（1.6 / 1.11 用） | 待提供 |
| U5 | 死信通知渠道是否本轮接入（I13） | 待提供 |

---

## 6. 声明

1. 本文件是**输入索取表草案**；未回执不影响任何既有能力，但**组 1 不开工验收**。
2. 本文件**不改变任何门禁状态**：组 1 全部判据仍未达成（`docs/delivery-remaining-checklist.md` 勾选框未动）。
3. 回执到达后按既有流程登记（真源回写 → 提交推送 → CI 取证）。

---

## 7. 转交说明与催办附言（2026-09-16 备 · 发送人自用，不影响 §1–§6 对基础设施方的口径）

| 项 | 填写 |
| --- | --- |
| 转交对象（基础设施方 / 运维） | **待定**——本飞书租户内检索（「运维 / 基础设施 / IT / 技术」等关键词 + 常见姓氏抽样 + 「聊过的人」/ 会话列表）**无其他真人成员（仅本人）**；2026-09-16 先发本人私聊存档，待二次转发 |
| 回传渠道（IM / 邮件 / 工单） | 首发：飞书私聊（存档）；**正式回传渠道随二次转发确定** |
| 期望回执时间 | 待定（随正式转交填写） |
| 转交状态 | **已发出（2026-09-16 19:39 · 渠道＝飞书 · 接收人＝徐君本人私聊存档；消息 ID `om_x100b6593b329aca0b2a22aba839549c`）**——**尚未转交至基础设施方（待二次转发）**；回执到达后按 §6 流程登记 |

**催办附言模板（复制后随文档一并发送）**：

> 您好，随附《组 1「真实环境验收」基础设施输入索取表》（14 项 I1–I14 + 回执模板；文档内已含每项的验证命令与期望结果）。组 1 是本项目当前**最大的交付阻塞项**——清单侧对应「就绪清单 12 条  里的绝大多数」与「65 条『代码完成但未验收』中的大部分」；我方预检与只读核验命令已全部备妥，**值一到位即可执行、无需再改代码**。
>
> 烦请按文档 §2 回执模板逐项回填「状态（就绪 / 待办 / 不适用）+ 脱敏值或说明」，其中：
> 1. **口令、密钥、DSN、令牌一律用 `***` 替换回传**；密钥值只经部署密钥系统注入、不回传；
> 2. 「待办 / 不适用」项请注明原因；§5 的 5 个待确认项（U1–U5）一并给结论；
> 3. 若一次性难齐，**可先回只读核验相关前置（I1–I6 + I10）**，即可先解锁 `readonly-verification-runbook.md` §1–§4 全量只读面，其余项随后补齐。
>
> 本轮**只准备输入、不执行任何写命令**（迁移 / 回滚演练、并发压测、密钥轮换均待我方单独授权后进行），**也请勿直接启动应用服务**（启动即跑迁移）。
>
> 回执请回传至：__________（发出人填写）。

**发出人自查（三条红线）**：① 附言与文档全文均不含密钥 / 口令 / DSN（红线见 §3）；② 回执只填在 §2 表内、按「脱敏值」口径回传；③ 回执到达后**先登记**（真源回写 → 提交推送），再由我方按 runbook 执行——**不因催办而压缩授权流程**。