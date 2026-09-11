# 交付剩余清单（可勾选 · 需外部输入）

> **本文件的作用**：只说「**还差什么、谁提供输入、用什么命令验证、判据是什么**」。
> **状态真相仍在** [`docs/delivery-readiness-checklist.md`](delivery-readiness-checklist.md)（现状与 ✅/❌），本文件是它的**执行层**，编号与它的「阻塞项 1–8」一一对应，避免两处各说一套。
> **口径**：以下所有事项**代码无法代替**；代码侧缺口已归零，唯一例外是 GEO 适配器（需对端契约，见组 5）。
> **红线**：写操作（迁移演练、并发压测、密钥轮换、启动应用服务）**必须单独授权**并在专用账号下执行；只读部分用 [`docs/readonly-verification-runbook.md`](readonly-verification-runbook.md)。

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
      本期实测（未配置环境）会输出 24 条 `fail`，可当作「你需要准备哪些配置」的清单
- [ ] 1.4 `python scripts/runtime_staging_preflight.py` → `pass`（未配置环境实测输出 11 条 `fail`）
- [ ] 1.4.1 `python scripts/worker_preflight.py --offline` → `pass`（本机实测输出 7 条，含「迁移清单不一致」；联网校验另需 `--base-url` 与 `--token`）
- [ ] 1.5 **只读核验清单全绿**（`docs/readonly-verification-runbook.md`）：pgvector 存在、迁移 022 已落地且复合外键存在、**归一风险 0 行**、**绑定侧未纳管为空**（`candidates.roles == []` 且 roster 绑定侧为空）
- [ ] 1.6 **迁移回滚演练**（写操作，需授权）：`scripts/migration_backup_drill.py`
      判据：能按备份恢复到指定版本，且 `WORKBENCH_APPLIED_MIGRATIONS` 与库内一致
- [ ] 1.7 **跨租户只读探测**（需两个不同租户的令牌）：`scripts/cross_tenant_probe.py --base-url … --token-a … --token-b …`
      判据：全部返回 `404`/空，不泄露他租户数据
- [ ] 1.8 **并发压测**（写操作，需专用账号）：`scripts/staging_concurrency_probe.py`
      判据：登录限流、任务幂等、审批原子性三场景行为与离线断言一致
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
- [ ] 2.2 轮换演练（写操作，需授权）：`scripts/secret_rotation_drill.py`
      判据：轮换后旧密钥失效、新密钥生效，**不改代码、不重启改配置以外的动作**

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
