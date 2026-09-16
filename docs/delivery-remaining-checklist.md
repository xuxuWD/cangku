# 交付剩余清单（可勾选 · 需外部输入）

> **本文件的作用**：只说「**还差什么、谁提供输入、用什么命令验证、判据是什么**」。
> **状态真相仍在** [`docs/delivery-readiness-checklist.md`](delivery-readiness-checklist.md)（现状与 ✅/❌），本文件是它的**执行层**，编号与它的「阻塞项 1–8」一一对应，避免两处各说一套。
> **口径**：以下所有事项**代码无法代替**；代码侧缺口已归零，唯一例外是 GEO 适配器（需对端契约，见组 5）。
> **红线**：写操作（迁移演练、并发压测、密钥轮换、启动应用服务）**必须单独授权**并在专用账号下执行；只读部分用 [`docs/readonly-verification-runbook.md`](readonly-verification-runbook.md)。
> **本机已验证（2026-09-12，一次性本机环境，未触碰 staging）**：1.7 跨租户探测、1.8 并发压测三场景、2.2 密钥轮换两阶段 —— 命令与判据均按实测结论写成，可直接照抄。**2026-09-16 追加（本机 Docker，独立 project + 独立端口，演练后已 `down -v` 清理）**：容器编排三服务（app / worker / beat）起栈、镜像版本标签、容器日志上限与**容量测算**取证见 [`docs/private-deployment-runbook.md`](private-deployment-runbook.md)「容量与并发」「监控与告警」；组 1 的 1.9 因此获得**本机级**证据（见该项注记），**但告警渠道与 staging 侧仍未验收**，勾选框一律不动。

---

## 组 1 · 真实环境验收（阻塞项 1）—— 解锁项最多，建议先做

**需要谁提供**：基础设施方 / 运维 —— 一台独立主机（Linux）+ **PostgreSQL（必须预装 pgvector）** + Redis + 对象存储实例 + 全部凭据；一个可登录的租户与超管账号。

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
- [ ] 1.4 `python scripts/runtime_staging_preflight.py` → `pass`（未配置环境实测输出 20 条 `fail`；五类 Runtime 各 3 条 + 环境/标识/网络白名单）
- [ ] 1.4.1 `python scripts/worker_preflight.py --offline` → `pass`（本机实测输出 7 条，含「迁移清单不一致」；联网校验另需 `--base-url` 与 `--token`）
- [ ] 1.5 **只读核验清单全绿**（`docs/readonly-verification-runbook.md`）：pgvector 存在、迁移 022 已落地且复合外键存在、**归一风险 0 行**、**绑定侧未纳管为空**（`candidates.roles == []` 且 roster 绑定侧为空）
- [ ] 1.6 **迁移回滚演练**（写操作，需授权）：`scripts/migration_backup_drill.py`
      判据：能按备份恢复到指定版本，且 `WORKBENCH_APPLIED_MIGRATIONS` 与库内一致
- [ ] 1.7 **跨租户只读探测**（需两个不同租户的令牌 + **每个 KIND 在两租户各一个真实资源 ID**）：
      `python scripts/cross_tenant_probe.py --base-url … --token-a … --token-b … --resource "task:<A_ID>:<B_ID>"`（**漏掉 `--resource` 会 `exit=2`**）
      判据：`exit=0` 且报告 `A→A=200 B→B=200 A→B=404 B→A=404`（本机已实测通过）
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
- [ ] 1.9 **审计落 PG 的实跑验证 + 日志采集告警**
      判据：库里能查到审计行；采集侧有告警规则（此前只有假连接静态断言）
      - **2026-09-16 第二批进展（仍不勾选）**：9 条规则从「成文」推进到「可执行」——只读探针 `scripts/monitoring_probe.py` 按 runbook 逐条同口径判定（信号不可用显式 `skipped`，不会静默算作通过），并在本机对真库实跑取证（Outbox 0 条 / 死信 0 条 / 磁盘 67.3% / PG 连接 10-100 等实测值；未接渠道时 `--notify` 不生效）；客户侧「渠道接入 + 触发一次真实告警」的核对清单与配套只读探针见 `docs/customer-side-acceptance-runbook.md` + `scripts/customer_acceptance_probe.py`。**仍缺**：渠道未接入、无真实触发证据。
- [ ] 1.10 **Outbox / Celery Worker 实跑**：Redis + Worker 进程 + 死信通知渠道地址
      判据：事件经 Outbox 投递成功；失败进死信并能通知
- [ ] 1.11 **商业化迁移与备份/恢复演练**：真跑一次恢复（不是只看脚本）
- [ ] 1.12 **攻击面八类检查在真实环境复测**（本机报告 `docs/security-attack-surface-report.md` 已有，需真实环境结论）

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

> **来源**：[OpenMausBot 源码研读报告](file:///d:/徐徐AI学习/公司工作台/docs/openmausbot-source-study-and-adaptation-plan.md) §5.2——从**对方暴露的缺口**反查「我们是否同类风险」。以下各条**此前均未逐条自查**，**不构成对我们现状的定性结论**（沿用"没验证的必须写未验证"）；**2026-09-16 已查的条目在各项下附「结论 + 证据（`文件:行`）」**（10.1 已查〔应用层无 DELETE/清理路径通过；数据库层 REVOKE 未做 ⇒ 差距，仍不勾选〕；10.2 通过；10.4 通过（键名归一 + 值形态扫描 + 掩码幂等）；10.5 已查〔用量账本 / `daily_budget_cents` / 评测费用 / 展示层全整数分，均通过；任务预算 `budget`（`NUMERIC(18,6)` 元 + 接口 float 链路）为差距，运行时「元→分」换算已最小加固并登记 ⇒ 仍不勾选〕；10.6 已查〔生产强制 `state_postgres` 成立（配置层 + 装配层双保险 + 部署口径 + 预检 + 守护测试）；唯一边界「`build_runtime_service` 缺省兜底不带 env 校验」已按 2026-09-16 拍板做 fail-closed 最小加固 + 先红后绿 + 反假两轮 ⇒ 勾选〕；10.8 已查〔8 类人工决议入口逐条核对：计划提案 / 运行内审批 / 编排优化提案 / 技能版本复核 / 对话入口（复用运行内审批）均成立；账号注册审批与知识文档复核语义 N/A（申请人无账号 / 系统到期触发）；未接线入口已登记；唯一缝隙「任务审批允许发起人自审」已按 2026-09-16 拍板收紧（403 + 列表剔除）+ 先红后绿 + 反假两轮 ⇒ 勾选〕；10.7 已查〔导出 / 删除路径均存在但覆盖不全（导出 15 类仅 `memories` 已接线；删除清场仅记忆层、`skills` / `knowledge_governance` 的 `delete_all_for_tenant` 已具备未接线；「记录确认人」未实现；保留策略无服务侧执行器；用户级个人导出 / 删除无）；本轮按 2026-09-16 拍板加固两项——新增导出包取回端点（admin-only、租户服务端解析、跨租户统一 404、过期 404）+ worker 周期任务按 `expires_at` 清理过期包（beat 间隔默认 3600），先红后绿 + 反假两轮 ⇒ 仍不勾选（差距如实登记，不改码）〕；10.3 的「运行事件有界」「日志有界」两条已于 2026-09-16 闭合，但因「磁盘容量告警渠道未接入」仍不勾选），**未附结论的仍未查**。
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
- [ ] 10.9 **出网归口唯一性**：除受控抓取 / 知识适配器外，是否还存在第二条出网路径（宪法 4.8 + 段二 A4）
- [ ] 10.10 **`reason` 不含自由文本**：工具类动作码的**取值**是否有枚举校验（而非只做键名白名单）
- [ ] 10.11 **密钥不进前端产物**：构建产物 / 静态资源中不得出现密钥或内部地址（宪法 4.1 禁止项 + 8.6 上线自检）
- [ ] 10.12 **`027` 迁移的升级与回退演练**（含对既有表 `workbench_run_records` 的约束增补；宪法 4.4 备份与恢复；登记口径见 `docs/change-record.md`）

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
