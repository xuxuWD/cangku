# 交付剩余清单（可勾选 · 需外部输入）

> **本文件的作用**：只说「**还差什么、谁提供输入、用什么命令验证、判据是什么**」。
> **状态真相仍在** [`docs/delivery-readiness-checklist.md`](delivery-readiness-checklist.md)（现状与 ✅/❌），本文件是它的**执行层**，编号与它的「阻塞项 1–8」一一对应，避免两处各说一套。
> **口径**：以下所有事项**代码无法代替**；代码侧缺口已归零，唯一例外是 GEO 适配器（需对端契约，见组 5）。
> **红线**：写操作（迁移演练、并发压测、密钥轮换、启动应用服务）**必须单独授权**并在专用账号下执行；只读部分用 [`docs/readonly-verification-runbook.md`](readonly-verification-runbook.md)。
> **本机已验证（2026-09-12，一次性本机环境，未触碰 staging）**：1.7 跨租户探测、1.8 并发压测三场景、2.2 密钥轮换两阶段 —— 命令与判据均按实测结论写成，可直接照抄。

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

## 开工顺序建议

1. **组 1 先行**（只读部分今天就能做：1.1 → 1.5），它一次解锁最多 ❌，且会暴露配置/迁移层面的真实问题；
2. 组 2、组 3 并行（都需要密钥/账号）；
3. 组 4（平台授权到齐后）；
4. 组 6、组 7（采购证书/真机）；
5. 组 5 只等对端契约，拿到即做。

## 回传与判读

每组完成后，把命令输出与证据（**脱敏**）回传；由我判读并更新 `docs/delivery-readiness-checklist.md` 的对应行（状态真相只在该文件维护，本文件只勾选进度）。
