# 外部依赖项详细执行计划（剩余 9 项门禁）

> **定位与边界**：本文件只负责**执行编排**——顺序、依赖、分工、检查点、输入交接、风险预案。
> **判定口径与证据要求不在本文件重复**，以 `docs/external-dependency-acceptance-plan.md` 为唯一来源；两者冲突时以该文件为准。
>
> **基线**：分支 `feature/planning-closure`，后端 **753 项测试通过**；`docs/delivery-gates.md` 中 **9 项未勾选**，**0 项达到真实环境验收**。
>
> **前提事实**：9 项里有 **8 项缺外部输入**、**1 项（GEO）缺外部契约**。本计划的作用就是把这些"缺的东西"变成可交接、可检查、可执行的动作。

---

## 0. 开工前必须先定的两个口径

这两个口径不确认，项 3 与项 6 无法开工（其余 7 项不受影响）：

| # | 待确认口径 | 选项 | 影响 |
| --- | --- | --- | --- |
| A | **项 3 的「真实统一登录」指什么？** | ① 指「在真实环境验证现有统一入口（手机号 + 口令 + TOTP）可用」→ **无代码缺口**，属纯外部验收<br>② 指「接入外部 IdP 的 SSO」→ **仍是代码缺口**，需先实现 OIDC 客户端（本仓库可做，但需 IdP 的 client id/secret 与回调域名） | 决定项 3 是否要先排一段开发 |
| B | **项 6 的「GEO 契约到位」如何判定？** | 需 GEO 侧交付：端点清单、认证方式、数据模型、错误语义、幂等键、**固定版本号与兼容规则**、读写边界 | 决定项 6 何时可从"阻塞"转为"可开工" |

> 建议：口径 A 选 ① 时，项 3 直接进入外部验收；选 ② 时，把 SSO 实现作为项 3 的**前置开发任务**单独登记，不与验收混在一起。

---

## 1. 执行原则（对 9 项一致生效）

1. **一票否决**：`py scripts/staging_preflight.py` 未返回 `pass` 时，**不进入任何真实环境验收**（项 6 的契约评审除外）。
2. **五步法**：每项都走「① 开工检查 → ② 执行 → ③ 判定 → ④ 存档 → ⑤ 登记」，不允许跳步。
3. **写验分离**：执行人与复核人不得为同一人；复核人只看证据、不改代码。
4. **证据不入库**：原始证据统一放仓库根 `.acceptance/<日期>-<项号>-<slug>/`（已被 `.gitignore` 忽略）；仓库只提交结论行。
5. **不再声明**：未走完五步之前，任何文档/汇报不得写「已上线 / 已发布 / 已收录 / 已验收」。
6. **失败即停**：任一项判定为 `fail` 立即停止该项，不在原环境试错；回退只用**已演练过的**备份与清单。
7. **可复现**：每项完成时，必须留下一条**别人照着能重跑**的命令。

---

## 2. 分工（角色定义，不指具体人）

| 角色 | 职责 | 约束 |
| --- | --- | --- |
| **输入提供方**（客户/外部平台/运维） | 提供凭据、账号、域名、白名单、阈值、GEO 契约 | 通过部署密钥系统注入，**不得在聊天/邮件/工单里明文传密钥** |
| **执行人**（后端负责人） | 跑脚本、采证据、填验收记录 | 不得自行放宽判据 |
| **复核人** | 核对证据与判据、登记结论、勾选门禁 | 不得修改代码或证据 |
| **双方共同** | 确认维护窗口、回退方案 | 变更前留检查点 |

---

## 3. 阶段、依赖与关键路径

```text
Phase 0  输入交接（外部方，可与 Phase 0.5 并行）
   │
Phase 0.5 不等外部输入即可做的准备（我方，立即开工）
   │  ├─ 内容安全评估离线跑 → 留存基线报告
   │  ├─ 并发探针护栏自检（--example / 错误地址）
   │  ├─ 桌面端依赖版本固定 + 签名证书申请（阻塞项 7 的前置）
   │  └─ (口径 A 选② 时) SSO 设计 + 实现
   ▼
Phase 1  基础设施就绪 ── G1 总闸门：py scripts/staging_preflight.py = pass
   │
   ├────────────┬─────────────┐
   ▼            ▼             ▼
Phase 2a       Phase 2b      Phase 2c
项 1 数据/迁移/  项 2 Worker/   项 8 RAGFlow/
回滚/并发压测    Outbox/死信    AgentScope 联调
   │            │             │
   └────┬───────┴──────┬──────┘
        ▼              ▼
   Phase 3a 项 4     Phase 3b 项 7
   商业化客户验收     真实平台账号
        │              │
        └──────┬───────┘
               ▼
        Phase 4 项 5 试点交付 + 容量压测 + 密钥轮换
               │
        Phase 5 并行专项：项 3（密钥轮换/统一登录）、项 6（GEO，等契约）、项 9（真实模型/抓取/发布）
```

**关键路径**：`Phase 0 → G1 → 项 1 → 项 4 → 项 5`。项 2、项 8 可在 G1 后与项 1 并行；项 3/6/9 不占关键路径。

### Phase 0.5 进度（2026-09-11）

- ✅ **内容安全评估基线**：离线跑通并留存 `.acceptance/2026-09-11-9-content-safety/baseline.json`（6/6 用例通过）。**该结论只证明仪器可用**，不代表任何模型安全。
- ✅ **并发探针护栏自检**：`http://` 与非独立主机地址均被拒（退出码 `2`，文案准确），日志存 `.acceptance/2026-09-11-1-concurrency-probe/`。
- ✅ **桌面端依赖固定**：`electron 44.3.0`、`electron-builder 26.15.3` 精确版本，已提交 `package-lock.json`（含 integrity）；本机用 `npm install --ignore-scripts` 有意跳过 Electron 二进制，`node --test` 13 项通过。
- ⬜ **桌面端代码签名证书申请**：属**外部/人工动作**（采购 OV/EV 证书 + 可信时间戳服务），我方无法代办；它是阻塞项 7 的前置。
- ✅ **SSO 构建块 + 服务与接口已实现**（口径 A 选②）：OIDC 客户端、一次性 state 仓储、`AccountService` 登录编排与三个接口（`/auth/sso/authorize`、`/auth/sso/callback`、`/auth/sso/verification`）均已落地，并有离线测试守护。**本地 OIDC 兼容端到端预演已通过（进程内 WSGI，真实 RS256）**：`tests/oidc_test_idp.py` + `tests/test_sso_e2e.py`（13 项，全程无 socket）。**真实 IdP 联调仍属未验收**（须先拿到 IdP 的 client id/secret 与回调域名）。

**SSO 已确认口径（2026-09-11）**：

| 取舍 | 最终口径 |
| --- | --- |
| ID Token 签名算法与依赖 | **引入 `cryptography` 作为显式依赖并锁定版本**，同时支持 `HS256` 与 `RS256`；`cryptography` 缺失时 fail-closed 并给出明确报错。严格算法白名单，**拒绝 `alg=none` 与未知算法** |
| 与 TOTP 的关系 | **新增配置开关，默认仍要求应用内 TOTP**（`sso_trust_idp_mfa` 默认 `false`）；只有部署方显式声明「IdP 已承担 MFA」才可关闭 |
| 账号绑定 | **仅允许登录已审批账号，不自动建号**；按 IdP 返回的 `email_verified` 邮箱匹配，并把 `sub` 落库（迁移 017 增加 `sso_subject`/`sso_provider`） |

---

## 4. 通用执行模板（每项照着走）

### ① 开工检查（前置不齐就不开工）
- 打开该门禁项在 `docs/delivery-gates.md` 的条目，读完整描述（含已知限制）。
- 对照 `docs/external-dependency-acceptance-plan.md` 的「需要的输入」逐条确认到位。
- 跑一次总闸门：`py scripts/staging_preflight.py` → 必须 `pass`（项 6 豁免）。
- 建证据目录：`.acceptance/<YYYY-MM-DD>-<项号>-<slug>/`，复制验收记录模板（见 acceptance plan 2.5）。

### ② 执行
- 严格按 acceptance plan 该项的「验收步骤」顺序执行，**不跳步、不合并**。
- 每条命令的输出**原样重定向**到证据目录（`... 2>&1 | Tee-Object <证据目录>/<步骤>.log`）。
- 涉及写入/发布/推送的步骤，先确认 `idempotency_key` 与回退手段。

### ③ 判定
- 逐条核对 acceptance plan 的「通过判据」，在验收记录模板的表格里逐行填 `pass/fail`。
- 阈值类判据（容量、延迟）必须填**客户书面确认的数值**，否则记「不可判定」而不是「通过」。
- 出现未解释 4xx/5xx、跨租户可读、密钥落盘落日志 → **直接判 fail**，不豁免。

### ④ 存档
- 证据目录内至少包含：预检原文、脚本原始输出（JSON/日志）、审计片段、操作记录（操作人/时间/结果）。
- 全目录做一次**敏感物自查**：`Authorization`、API Key、Cookie、验证码、客户原文、连接串一律不得出现。

### ⑤ 登记
- 在 `docs/acceptance-log.md`（首次验收时创建）追加一行：`日期 | 项号 | 结论 | 证据目录名 | 执行人 | 复核人`。
- 只有判定为 `pass` 才去 `docs/delivery-gates.md` 勾选该门禁，并同步 `docs/delivery-readiness-checklist.md` 三态。
- 判定为 `fail` 时：登记失败项与原因，在门禁条目后补「未通过原因」，**不勾选**。

---

## 5. 逐项执行卡

> 每张卡的「执行序列」只列关键命令与顺序；判据细节见 acceptance plan 对应小节。

### 项 1 · staging 数据库实测、迁移回滚演练和真实并发压测
- **前置**：独立 staging PG（非 localhost）+ 凭据；备份介质与独立加密密钥；维护窗口；专用探针账号。
- **执行序列**：
  1. `py scripts/staging_preflight.py` → `pass`（留存原文）
  2. 一致性备份 + 记录校验值
  3. 启动应用让迁移 runner 应用 `001`–`016`，记录实际迁移清单
  4. 冒烟：`GET /api/v1/health`、租户读取、跨租户 404
  5. `py scripts/staging_concurrency_probe.py --base-url <https://staging> --token <探针令牌> --phone <探针号> --password <探针口令> --proposal-id <待审提案> --output <证据目录>/probe.json`
  6. 回滚演练：按备份恢复到迁移前，验证可启动/可读/隔离仍成立
- **检查点/门**：G1 已过；探针三场景（`login_throttle` 出现 429、`task_idempotency` 唯一 id、`plan_approval` 恰 1×200 其余 409）全 `pass`。
- **产出**：预检原文、迁移清单、探针 JSON、审计片段、回滚记录。
- **风险**：探针会锁定专用账号 → 必须用**专用探针账号**，不要用真实人员账号。

### 项 2 · Celery Worker 实跑、Outbox 生产连接池、死信通知渠道和 staging 验收
- **前置**：真实 Redis（独立实例/逻辑库）；Worker 运行环境；**死信通知渠道地址**（`WORKBENCH_DEAD_LETTER_WEBHOOK_URL`）+ 收件人。
- **执行序列**：
  0. 运行态前置预检：`py scripts/worker_preflight.py --token <管理员令牌>` → 期望无 `fail`（**已知缺口**：仓库内无 Outbox 积压的可读接口，该项固定输出 `skipped`）
  1. 配置通知渠道后启动 Worker：`celery -A app.worker:celery_app worker --loglevel=INFO`
  2. 创建任务 → 验证 Outbox 写入 → Worker 发布 → Redis Stream 消费 → 重复投递不重复生效
  3. 制造失败（外部适配器指向不可达地址），使事件重试至 `WORKBENCH_OUTBOX_MAX_ATTEMPTS` 后进死信
  4. `GET /api/v1/dead-letters` 查死信（确认 `notified_at` 非空）→ 确认**通知渠道收到脱敏通知** → `POST /api/v1/dead-letters/{event_id}/replay`
  5. 短时批量写入观察积压与回落
- **检查点/门**：通知只发一次（去重生效）；通知载荷不含事件 payload 与凭证；重放不产生重复业务结果。
- **风险**：通知渠道不可达时会持写 `dead_letter.notification_failed` 审计但不重发 → 复核人需核对审计条数。

### 项 3 · 生产密钥轮换与真实统一登录验收
- **前置（按口径 A 分支）**：
  - A①（无代码缺口）：部署密钥系统可注入并轮换；真实验证器设备。
  - A②（有代码缺口）：**先实现 OIDC/SSO 客户端并合入**，再进入验收；另需 IdP 的 client id/secret 与回调域名。
- **执行序列**：
  1. 轮换前取证：`py scripts/secret_rotation_drill.py --phase before --output .acceptance/<目录>/old-token.json`（只打印令牌指纹；**该文件含令牌原文，用完即删**）
  2. 轮换 `WORKBENCH_AUTH_SECRET`（与 `WORKBENCH_BACKUP_ENCRYPTION_KEY` 保持不同），记录操作人与窗口
  3. 轮换后断言：`py scripts/secret_rotation_drill.py --phase after --token-file <同一文件>` → 旧令牌 `401`、重登成功、新令牌可访问受保护接口 `200`
  4. **轮换后重跑** `py scripts/staging_preflight.py` → 仍 `pass`
  5. A①：用真实设备验证手机号 + 口令 + TOTP 全流程；A②：与 IdP 联调首次登录绑定、失败回退到口令登录、越权拒绝
- **检查点/门**：轮换后预检仍 `pass`；旧令牌失效符合预期；验证器真机可用。
- **风险**：轮换失败 → 用密钥系统回退上一版本密钥，再重跑预检。

#### 项 3 附：SSO 联调（口径 A② 的后续动作）

> 本地已用进程内 OIDC 兼容测试 IdP（`tests/oidc_test_idp.py`，标准库 WSGI + 真实 RS256）跑通全链路预演（`tests/test_sso_e2e.py`，13 项，全程无 socket）；**这不等于真实 IdP 验收**。

**需要 IdP 侧提供**：
- `issuer`、`authorization_endpoint`、`token_endpoint`、`jwks_uri`（或一份 discovery 地址，由我方据此填四项）。
- `client_id` / `client_secret`（经部署密钥系统注入，**不得在聊天/邮件/工单里明文传**）。
- 回调地址登记：与 `WORKBENCH_SSO_REDIRECT_URI` **完全一致**（含 https 与路径）。
- `email_verified` 必须为真：未验证邮箱一律拒绝登录。
- ID Token 签名算法为 `RS256`（或 `HS256`）；算法不在允许清单时 fail-closed。
- 明确 IdP 是否承担 MFA：承担则 `WORKBENCH_SSO_TRUST_IDP_MFA=true`（预检会输出 warn 提示），否则保持 `false` 走应用内 TOTP。

**配置与交付清单**：`.env.sso.example`（内含完整的 `WORKBENCH_SSO_*` 配置项与「IdP 侧需提供或确认」的勾选清单，可直接作为交接底稿）。

**验收命令**：
1. 配置就绪自检（不发网络）：`py scripts/sso_preflight.py --offline` → 退出码 `0`。
2. 元数据自洽校验（默认联网，需 IdP 可达）：`py scripts/sso_preflight.py` → 退出码 `0`（不一致/不可达均 fail-closed）。
3. 无 IdP 时的 fail-closed 演示：`py scripts/sso_preflight.py --example` → 退出码 `1`。

**预检覆盖面**（`fail` = 已确定会导致对接失败；`warn` = 需人工确认的风险）：
- 本地（离线可跑）：配置齐备性、四个 URL 必须 `https`、**请求作用域必须含 `openid` 与 `email`**（缺 `email` 会导致账号匹配全线失败）；并提示 `redirect_uri` 应指向**客户端**（后端 `/api/v1/auth/sso/callback` 是 POST+JSON，不能作为浏览器跳转目标）。
- 联网：issuer 与三端点一致性、ID Token 签名算法（RS256/HS256）、JWKS 可用密钥、**授权码模式**（`response_types_supported` 含 `code`）、**PKCE S256**（本系统固定发 `code_challenge_method=S256`）、**令牌端点认证方式**（本系统把 `client_secret` 放在表单体，需支持 `client_secret_post`）、**本机与 IdP 的时钟偏移**（> 60 秒判 fail，因 `exp`/`iat` 容差为 60 秒）。

**联调动作**（按序执行并留证）：
1. 发起授权 → 完成回调：`GET /api/v1/auth/sso/authorize` → IdP 登录 → `POST /api/v1/auth/sso/callback`。
2. 若回调返回 `requires_totp=true`（`scope=sso_pending`）→ 用受限令牌走 `POST /api/v1/auth/sso/verification` 换完整会话。
3. 用完整会话访问受保护接口（如 `GET /api/v1/approvals/pending`）应成功；用受限令牌访问应 `403`。
4. 核对审计：`account.sso.identity_bound` / `account.sso.login_succeeded`（或 `account.sso.mfa_required`）/ `account.sso.login_rejected` 齐全，且**审计中不出现邮箱原文**。
5. 负向抽验：篡改 `state` / `code_verifier`、未验证邮箱、非允许签名算法均应被拒，且不回吐 IdP 原始响应。

> 注意：`py scripts/sso_preflight.py` 只验证配置与元数据自洽，**不构成真实登录验收证据**；真实登录验收以第 1–5 步的联调证据 + `.acceptance/` 存档为准。

### 项 4 · 真实 PostgreSQL 商业化迁移、备份/恢复演练与客户管理员验收
- **前置**：客户 staging PG；备份介质；**客户管理员账号**与联系人；维护窗口。
- **执行序列**：
  0. 迁移与备份/恢复演练（**默认 dry-run，加 `--execute` 才真跑**）：`py scripts/migration_backup_drill.py --phase list` → `--phase backup --execute` → 恢复到**隔离库** `--phase restore --execute` → `--phase verify`；目标库禁 localhost/sqlite，生产库需 `--confirm-production`，**输出中 DSN 口令脱敏为 `***`**
  1. `py scripts/commercial_g0_preflight.py` → `pass`
  2. 按 `docs/staging-acceptance-checklist.md` 执行顺序 4–8（租户/用量/生命周期/导出/删除冷静期/备份恢复）
  3. 客户管理员自助验收：查租户与用量、申请导出、申请删除后撤销或等冷静期
  4. 按 `docs/private-deployment-runbook.md`「客户交接」核对交付清单
- **检查点/门**：导出**只含授权范围**且不含密码/Cookie/令牌/客户原文；删除走冷静期；恢复后记录一致。
- **风险**：客户管理员无法自助完成 → 属验收失败，先补交付材料再验。

### 项 5 · 私有部署生产预检、容量压测、独立密钥轮换与试点客户交付
- **前置**：试点客户环境；**容量与延迟阈值（书面确认）**；双密钥；支持联系人。
- **执行序列**：
  1. `py scripts/commercial_g0_preflight.py` → `pass`
  2. 容量压测：`py scripts/staging_concurrency_probe.py` 的扩容参数（`--concurrency` 提到上限、增加重复轮次）+ 用量写入压测，记录 P95/错误率/资源水位
  3. 独立密钥轮换（同项 3 的执行序列步骤 1–4，用 `py scripts/secret_rotation_drill.py` 取证），轮换后重跑预检与冒烟
  4. 按 runbook 完成交付，逐项标注未验收能力
- **检查点/门**：阈值以客户书面数值为准；无未解释 5xx。
- **风险**：阈值未确认 → 该判据记「不可判定」，不得判 pass。

### 项 6 · GEO 版本化适配器
- **前置（硬阻塞）**：口径 B 确认的 GEO 契约交付。
- **执行序列**：
  1. **契约评审**：逐条核对端点/认证/数据模型/错误语义/幂等键/固定版本/读写边界，评审记录存档
  2. 实现适配器（可复用 `app/runtime/registry.py` 的固定版本校验范式）+ 关联字段（任务号/项目号/产物版本/证据引用）
  3. 契约测试（`FakeTransport`）+ 扩展 `scripts/staging_preflight.py` 的元数据校验
  4. 真实联调：只读边界冒烟 + 错误语义核对 + 跨租户拒绝
- **检查点/门**：版本必须固定（拒绝 `latest`/`main`/`head`）；不跨库写入；错误语义与契约一致。
- **风险**：**契约未到之前不做任何占位实现**（避免臆造接口后返工）。

### 项 7 · 真实 staging 与真实平台账号验收
- **前置**：项 1 完成；真实平台账号与发布授权；回执核对人。
- **执行序列**：凭据注入 → 账号可达与权限最小验证 → 一次**无外部副作用**的只读调用 → 失败回执路径核对 → 凭据泄漏排查（grep 关键字 + 人工复核）
- **检查点/门**：日志/事件/配置/导出产物中均无凭据。
- **风险**：发现任何凭据泄漏迹象 → 立即暂停并轮换该凭据。

### 项 8 · RAGFlow/AgentScope 密钥注入、跨租户实测、并发压测、沙箱验证和真实外部服务验收
- **前置**：两者的 HTTPS 地址 + 固定版本 + 认证注入 + 隔离测试账号 + 网络白名单。
- **执行序列**：
  1. `py scripts/runtime_staging_preflight.py` → `pass`
  2. `py -m app.runtime.staging` → `status: pass`（仅证明适配边界与脱敏）
  3. 按 `docs/superpowers/poc-staging-runbook.md` ⑥⑦⑧：RAGFlow 两租户白名单与跨租户整批拒绝；AgentScope 健康/事件游标/暂停恢复取消/审批/usage/replay，并注入未知事件与超时
  4. 跨租户隔离实测：`py scripts/cross_tenant_probe.py --base-url <staging> --token-a <A> --token-b <B> --resource task:<A的资源id>:<B的资源id>` → 全 `pass`；**含正向对照**（须先用所有者令牌读到自己的资源，否则判 `fail（用例无效）`），防止 ID 写错导致的假通过；输出只含状态码
  5. 并发压测（复用项 1 探针主机）
- **检查点/门**：跨租户结果**整批拒绝**；空范围拒绝；非 2xx/超时/缺运行号/事件格式错误一律判失败且无自动越权。
- **风险**：外部服务不稳定 → 关闭注册项回退 Mock，保留事件摘要，**禁止直接重放外部副作用**。

### 项 9 · 真实模型、网页抓取和公众号自动发布验收
- **前置**：真实模型 `base_url`/`model`/`key`；平台凭据与发布授权；抓取白名单与合规确认；回执核对人。
- **执行序列**：
  1. 配置真实内容模型后跑 `py scripts/content_safety_evaluation.py --json --output <证据目录>/report.json` → 用例全过
  2. 真实模型生成质量与合规抽检
  3. 抓取：配置 `WORKBENCH_CONTENT_SCRAPE_ALLOWED_DOMAINS` 后调用 `POST /api/v1/content-sources/scrape`，确认仅白名单可抓且留痕
  4. 发布：`POST /api/v1/content-tasks/{task_id}/publications` 一次 → 核对回执 → `POST /api/v1/content-publications/{publication_id}/verification`
  5. 注入失败：确认转 `manual_takeover` 且**不自动重发**
- **检查点/门**：canary 用例全过（**离线通过不算**，必须真实模型重跑）；抓取不越白名单；发布有可核对回执。
- **风险**：真实模型下 canary 命中 → 判 fail，**不得**通过放宽用例来"修好"。

---

## 6. 输入交接规范

| 输入类型 | 交接方式 | 我方确认动作 |
| --- | --- | --- |
| 双密钥（`AUTH_SECRET` / `BACKUP_ENCRYPTION_KEY`） | 部署密钥系统注入 | 只确认「已注入」与长度/互异，**不索取明文** |
| staging 主机与 PG/Redis/对象存储凭据 | 部署密钥系统或受控密码库 | 跑 `staging_preflight.py` 确认连通与隔离 |
| 死信通知渠道地址 | 配置文件注入 `WORKBENCH_DEAD_LETTER_WEBHOOK_URL` | 发一条测试通知，确认真实收到 |
| RAGFlow/AgentScope 地址、版本、账号 | `.env.staging` 登记元数据，账号口令由密钥系统注入 | 跑 `runtime_staging_preflight.py` |
| 真实平台账号与发布授权 | 平台侧开通 + 授权说明 | 项 7 只读验证；发布授权留给项 9 |
| 真实模型 key | 密钥系统注入 `CONTENT_MODEL_*` | 先跑内容安全评估，再做质量抽检 |
| 容量/延迟阈值 | **书面**确认（邮件/工单留痕） | 抄进验收记录的判据表 |
| GEO 契约 | 文档交付（版本号 + 端点 + 认证 + 错误语义 + 读写边界） | 契约评审记录建档 |

> **红线**：任何凭据不得出现在聊天记录、工单正文、代码、配置文件或证据目录中。

---

## 7. 风险登记与分支预案

| 风险 | 预案 |
| --- | --- |
| 外部输入延迟到不了 | 执行 Phase 0.5 的"不等输入即可做"清单；**不降低判据**去凑结论 |
| 总闸门始终 `blocked` | 先按 `staging_preflight.py` 的逐行输出定位是元数据缺失还是迁移清单不一致（后者已有 `tests/test_staging_assets.py` 守护） |
| 压测未达阈值 | 回容量评估并重新确认阈值；**不把未达标写成"基本达标"** |
| 密钥轮换异常 | 回退上一版本密钥 → 重跑预检 → 记入审计 |
| 外部服务不稳/回执未知 | 暂停并转人工接管；关闭 Runtime 注册项回退 Mock；**禁止重放外部副作用** |
| 内容安全用例在真实模型下命中 | 判 fail，按发现的问题修链路（例如本轮已修的导出链接凭证遮蔽），**不得放宽用例** |
| 客户管理员无法自助验收 | 视为交付材料不足，先补料再验 |

---

## 8. 完成定义（DoD）

一项门禁只有在**同时满足**下面全部条件时才算完成：

1. 走完五步法，验收记录模板的判据表**逐行为 pass**（无"不可判定"）；
2. 证据目录已归档且通过敏感物自查；
3. `docs/acceptance-log.md` 已登记结论行（含执行人与复核人）；
4. `docs/delivery-gates.md` 已勾选该门禁，`docs/delivery-readiness-checklist.md` 三态已同步；
5. 留下一条**别人可复现**的命令。

> 9 项全部满足后，`docs/delivery-gates.md` 方可将「当前阶段」整体标记为完成；在此之前，任何对外表述都必须保持「未验收」口径。
