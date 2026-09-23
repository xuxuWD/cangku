# 交付就绪清单

> **用途**：把 `docs/delivery-gates.md` 的勾选状态摊开成可逐项追踪的底账，区分「代码在」「有测试守护」「在真实环境验收过」三种不同状态。
>
> **生成日期**：2026-09-10；**2026-09-11 同步三态**（第一次：容器化、弱口令策略、TOTP 二次验证、攻击面报告；第二次：数据分级闸门、协同动态表现层、运行指标采集、编排优化提案、GEO 阻塞更正；第三次：待办聚合接口、PWA 伴侣端、Electron 桌面端；第四次：死信通知渠道、并发探针、抓取器与发布器、门禁口径变更；第五次：内容安全评估用例；第六次：OIDC SSO 构建块 + 服务与接口；第七次：OIDC SSO 本地端到端预演 + SSO 预检脚本；第八次：IdP 配置模板与模板契约测试；第九次：外部依赖验收工具（Worker 运行态预检、迁移/备份恢复演练、密钥轮换演练、跨租户探针含正向对照）；第十次：项 8 两处代码缺口修复（运行时认证注入、注册表接入应用装配）+ 三项接入索取表（GEO 契约/公众号账号/外部运行时）；第十一次：分支 `feature/acceptance-tooling` 快进合入 `main`，基线口径由该分支改为 `main`；第十二次：TOTP 种子静态加密（HKDF 子密钥 + AES-256-GCM）与会话令牌服务端撤销（登出立即生效，迁移 018）；第十三次：补齐契约遗漏（内容任务列表、运行指标两接口）并新增路由覆盖守护测试；第十四次：审计明细嵌套值的递归敏感键校验（防御性加固），并订正过期口径——桌面端自动更新行拆出为已完成、通知能力范围改为「仅死信运维通知渠道」、核实记录注同步；第十五次：接入提交门禁 CI（`.github/workflows/ci.yml` + 静态契约守护）；第十六次：修复两个前端依赖版本漂移——`admin-web`、`companion-pwa` 的全部依赖由 `latest` 改为精确版本，并新增 lockfile 一致性守护；第十七次：CI 首次实跑通过（run `34590744934`）、Action 升到 v7 消除弃用告警并补齐 Action 版本守护，v7 版工作流再次实跑通过（run `34591258934`，4 job 全绿）；第十八次：员工站内通知收件箱——迁移 `019_inbox_items` + `app/inbox.py`（内存/PostgreSQL 双仓储）+ 三接口 + 两端入口，写入失败不阻断仅写审计；并登记「运行终态未落盘」缺口（E 节）；第十九次：补齐运行终态落盘（`RuntimeService` 统一回写 start/pause/resume/cancel、直启与内容生成运行一并纳入）、新增受控 `finish_reason`（迁移 020）与 Mock 确定性失败路径（`fail.` 前缀），接入运行失败/取消站内通知，并把「带审批步骤的运行终态」登记为新缺口；第二十次：补齐运行内审批决议闭环（`GET/POST /api/v1/runs/{run_id}/approvals[...]`、仅 CEO/超管且发起人不能自审、通过后执行步骤并落到终态、驳回立即 failed 并新增 `finish_reason=approval_rejected`、审计 `run.approval_decided`、通知 `run.approval_rejected`），关闭上一轮登记的缺口，并把「审批人无租户级待办入口」登记为新缺口；第二十一次：管理台运行详情页（指标 / 事件时间线 / 审批决议，通知跳转与 URL 直达），并修复两端收件箱 kind 漂移 + 新增 `test_frontend_inbox_kinds.py` 守护；第二十二次：审批人的运行审批待办入口（聚合第 4 类 `run_approval` + 伴侣端第 4 类卡片与决议动作），关闭 E 节最后一条 ❌；配套修复「终态运行可被剩余审批复活」的缺陷，并把「运行时状态未持久化（待办不跨重启、多进程不完整）」首次写入文档；第二十三次：运行时状态持久化——迁移 `021` + `PostgresRuntimeStateStore`（整行 JSONB upsert）+ 编解码与 `InvalidRuntimeState` + `build_runtime_state_store`（postgres 强制持久化、memory 仅限 development），事件 payload 写入前即脱敏，关闭「运行时状态持久化」缺口；第二十四次：通用审计查询接口 + 管理台审计页（严格本租户、动作/目标/操作者/时间筛选、`limit`+`offset`+`total`）与 33 个动作标签的漂移守护，把已落库审计变成可查证据）；第二十五次：交付就绪收口四项——① 镜像版本标签（`org.opencontainers.image.version` / `revision`）与三服务容器日志上限（本机容器演练 `docker inspect` 取证 + 测试守护）② worker 容量测算与 `--max-tasks-per-child` 参数决定（runbook 新增「容量与并发」「监控与告警」两章）③ 审计落 PG 的本机级实跑取证（1600 行 / `system:worker`）④ 客户侧验收维持「未验收」口径（**监控告警渠道仍未接入任何环境**））；第二十六次：剩余四项未验证项推进——① **运行事件有界**（迁移 `034`：事件从状态行 JSONB 迁到 append-only 表 `workbench_runtime_events`，worker 周期任务 `runtime-events-purge` 按保留期清理 ⇒ 行大小有界、写放大消除，`cursor` 断点读取语义不变）② **监控告警 9 条规则落成只读可执行探针** `scripts/monitoring_probe.py`（本机对真库实跑取证；**渠道仍未接入**，探针 ≠ 接入）③ **镜像构建独立工作流** `.github/workflows/image.yml`（构建 + OCI 标签校验；**推送默认关闭**、凭据走 secrets；ci.yml 的「零密钥只读」契约不变）④ **客户侧只读验收清单与探针** `docs/customer-side-acceptance-runbook.md` + `scripts/customer_acceptance_probe.py`（**客户环境未执行任何命令**）；组 10.3 的「运行事件有界」随之闭合，但因磁盘告警渠道未接入**仍不勾选**
> **基线**：分支 `main`（`feature/acceptance-tooling` 已于 2026-09-11 快进合入）。**当前口径（2026-09-12 CI 实测，2026-09-13 同步）：后端 1434 用例全绿**、`compileall` 退出码 0；四 job 全绿（`.github/workflows/ci.yml`）。**本节以下遗留的 1159 / 975 / 121 / 60 / 108 等数字为 2026-09-10 至 09-11 的历史快照，已过期，保留仅作留痕**。
>
> **证据口径（重要）**：本清单以 `docs/delivery-gates.md` 的勾选状态、`tests/` 目录的测试模块与用例（**当前 = 后端 1434，2026-09-12 CI 实测**）、`README.md` 的能力声明为准。标 ✅ 表示仓库内存在实现且门禁已勾选，**不等于我逐项重新验收过**；需要真实环境证据的项一律标 ⬜。
>
> **第二十七次（2026-09-24）：订正过期口径 —— 本次仅动文档，未改任何代码、未跑任何测试。**
> ① **「汇总」表的门禁计数由 62 / 53 / 9 更正为 65 / 56 / 9**。实测 `docs/delivery-gates.md`：`- [x]` = **56**、`- [ ]` = **9**、合计 **65**（原 62/53 为过期值）。
> ② 连带订正三处与 `decision-log.md` **D-058** 冲突的**真源级过期口径**：`ROADMAP.md` 第 5–9 条原写五份规格"未评审/待裁决"；`ROADMAP.md` 产品边界与 `docs/feature-inventory.md` §3.7 第 8 条原写"CRM 代码处置属待裁决"；`docs/architecture.md` §客户端原写"收敛属未决项"。
> ③ 执行 **Q5③ 硬闸门**：`docs/architecture.md` 四处修订已落地（3 处实改 + 「发布边界」1 处确认不改，逐字取自 B1 规格 §5 并经留痕）。
> **⚠️ 本次未核（不得读成已核）**：`sandbox` job 是否已有 push 触发记录 —— 有材料称 run `35894719592` 全绿，但本机**无网络取证手段**，故 `ROADMAP.md` 第 2 条、`docs/delivery-gates.md` 2026-09-15 行、`.github/workflows/ci.yml` 头部三处**维持原文未改**，待用户在有网环境核实后回填。
> **⚠️ 本表「测试文件数 121 / 用例数 1434」两行仍为 2026-09-12 快照**，**本次未重数**（仓库实际测试模块数已明显多于 121）——**引用前须重数**。

## 判定口径

| 状态 | 含义 | 判定依据 |
| --- | --- | --- |
| **实现** ✅ | 仓库内有可运行代码 | 门禁已勾选 + 对应模块存在 |
| **测试** ✅ | 有自动化测试守护 | `tests/` 下有对应测试文件（**仅按文件名与主题匹配，未逐条核对覆盖度**） |
| **验收** ⬜ | 在目标真实环境（staging / 生产 / 真实外部账号）跑过并有证据 | 需部署记录、压测报告或平台侧截图等；**目前无任何一项达到 staging 级验收** |
| ️— | 该维度不适用 | 例如纯文档项 |

## 汇总

| 维度 | 数量 |
| --- | --- |
| 门禁总项数 | **65**（`delivery-gates.md`） |
| 已勾选（实现） | **56** |
| 未勾选 | **9** |
| 达到**真实环境验收**（staging / 生产 / 真实外部账号） | **0**（另有本地真实验证 2 项、CI 环境验证 1 项，见下两行） |
| 本地已验证（真实 PostgreSQL 迁移与备份恢复演练、内容工作台内部闭环回归） | **2** |
| CI 环境已验证（提交门禁在 GitHub Actions 实跑通过） | **1** |
| 测试文件数 | **121** 个测试模块（`tests/`；**历史值**，2026-09-12 未重数；另有 `conftest.py` 与 `oidc_test_idp.py` 两个辅助文件，不计入） |
| 测试用例数 | **1434**（后端，2026-09-12 CI 实测）+ 前端 `admin-web` 147、`companion-pwa` 37、`desktop` 19（**后三项为段二规格头部口径，2026-09-12 未逐项复核**）。**历史快照**：本行原记「1159 + 60 + 37 + 19」，已过期 |

> **一句话结论**：服务端能力基本齐全，**本批次可独立实现的代码缺口已全部闭合（项 2 的死信通知渠道、项 9 的抓取器/发布器/内容安全评估、项 3 的 OIDC SSO 客户端）**；但项 3 的真实 IdP 联调与项 6 的 GEO 适配器**尚需先拿到口径/契约才能动工**，不属于本仓库可独立完成的范围。其余卡点全为外部依赖。
>
> **验收工具就绪情况**：项 1（并发探针）、项 2（`worker_preflight.py`）、项 3（`sso_preflight.py` + `secret_rotation_drill.py`）、项 4（`migration_backup_drill.py`）、项 5（同项 3 工具 + 并发探针扩容参数）、项 8（`cross_tenant_probe.py`）、项 9（`content_safety_evaluation.py`）**已有可执行验收工具**；项 6 因缺契约无工具、项 7 依赖真实平台账号。**工具就绪不等于已验收**——全部 9 项目前仍是 0 项真实环境验收。

---

## A. 平台骨架

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| 独立 Git 仓库与 GEO 边界确认 | ✅ | — | — | `README.md`「项目边界」「与 GEO 的边界」 |
| FastAPI 服务入口与健康检查 | ✅ | ✅ | ⬜ | `test_control_plane.py` |
| 开发期任务幂等、租户隔离、风险审批、审计计数 | ✅ | ✅ | ⬜ | `test_control_plane.py` |
| 基础依赖、环境示例、Docker Compose | ✅ | — | ⬜ | `.env.example`、`docker-compose.yml`（基础设施）；应用编排见 I 节「应用容器化」；三个客户端（`admin-web`、`companion-pwa`、`desktop`）依赖均已精确锁定，并由 `test_frontend_dependency_pins.py`、`test_desktop_assets.py` 守护 package.json 与 lockfile 一致 |
| 契约测试与 Python 编译检查 | ✅ | ✅ | — | `test_persistence_contract.py`、`test_api_contract_coverage.py`（守护每个 `/api/` 路由都已写入 `docs/api-contract.md`） |
| PostgreSQL 任务 CRUD、唯一约束、原子审批、迁移 runner | ✅ | ✅ | ⬜ | `test_persistence_contract.py`；**未在真实 PG 上运行** |
| PostgreSQL 连接池适配、审计读取、审批事务 | ✅ | ✅ | ⬜ | 同上 |
| Redis Streams/Celery 事件总线、Outbox 事务写入、幂等消费者**骨架** | ✅ | ✅ | ⬜ | `test_events.py`、`test_outbox.py`；门禁自述为「骨架」 |
| 按存储模式选择事件总线、生产 API 不重复直发 Outbox | ✅ | ✅ | ⬜ | `test_outbox.py` |

## B. 身份与账号

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| 自建账号注册审批、登录会话、管理员重置密码 | ✅ | ✅ | ⬜ | `test_account_{api,auth,service,repository,passwords,bootstrap,postgres}.py` |
| 账号登录限流与失败锁定 | ✅ | ✅ | ⬜ | `test_login_rate_limit.py`、`test_account_audit.py`；门禁注明「生产并发与网关层限流仍需 staging 验收」 |
| 生产密钥轮换、真实统一登录验收 | ❌ | ❌ | ⬜ | **口径变更**：原「设备绑定」已从该项移除（产品采用「注册申请 + 管理员审批」制，理由见 `delivery-gates.md`「门禁口径变更记录」）；SSO 客户端已实现（见下一行），密钥轮换需部署密钥系统，两者均待外部资源（TOTP 二次验证已完成，见下两行） |
| SSO（OIDC）实现 | ✅ | ✅ | ⬜ | `app/accounts/sso.py`、`app/accounts/sso_store.py`、`AccountService` 登录编排与 `/auth/sso/{authorize,callback,verification}` 三接口；迁移 017 + 算法白名单（HS256/RS256，拒绝 `none`）+ 不自动建号；测试见 `tests/test_sso_login.py`、`tests/test_sso_blocks.py`、`tests/test_sso_e2e.py`（真实 HTTP + 真实 RS256，进程内 WSGI）、夹具 `tests/oidc_test_idp.py`、预检 `scripts/sso_preflight.py`；**本地端到端预演已通过，真实 IdP 联调未验收** |
| 口令弱口令策略（禁止纯数字与常见口令） | ✅ | ✅ | ⬜ | `test_account_password_policy.py`；**已知限制**：不校验是否含手机号/姓名、不做变形归一 |
| 管理员动态口令二次验证（TOTP） | ✅ | ✅ | ⬜ | `test_totp.py`、`test_account_totp.py`、`test_account_totp_api.py`、`test_account_repository_totp.py`、`test_account_secrets.py`；TOTP 种子在持久化层静态加密（AES-256-GCM + HKDF 子密钥，密文带 `v1:` 前缀，旧明文只读兼容；内存仓储不落盘故不加密）；真实部署的验证器兼容性未验收 |
| 会话令牌服务端撤销（登出立即生效） | ✅ | ✅ | ⬜ | `test_session_revocation.py`、迁移 `018`（`workbench_session_revocations`）；登出后同一令牌立即 `401`，撤销条目保留至令牌自身过期，撤销查询失败按 `503` fail-closed；开发期头部身份不适用 |

## C. 权限与策略

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| 模型能力筛选与敏感数据阻断 | ✅ | ✅ | ⬜ | `test_agent_services.py`、`test_capabilities.py` |
| 高风险能力策略目录（第三方 Skill、Shell、特权沙箱、知识/提示词/流程变更） | ✅ | ✅ | ⬜ | `test_capabilities.py`、`test_runtime_policy.py` |
| 规划输入的数据分级与 `ModelGateway` 闸门 | ✅ | ✅ | ⬜ | `test_planner_classification.py`、`test_planner_gateway.py`、`test_planner_gateway_api.py`、`test_planner_bootstrap.py`；分级由服务端从 `Task.risk_level` 推导，Mock 后端不外发数据故不介入 |
| 分层记忆与受控成长提案 | ✅ | ✅ | ⬜ | `test_agent_services.py` |

## D. 知识权限与检索

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| 岗位/数字员工知识库范围注册表与自动解析 | ✅ | ✅ | ⬜ | `test_knowledge_policy.py` |
| 知识范围 PostgreSQL 持久化迁移与连接池适配 | ✅ | ✅ | ⬜ | `test_knowledge_policy.py`；**未在真实 PG 上运行** |
| 超级管理员知识范围配置接口 | ✅ | ✅ | ⬜ | 同上 |
| 知识范围变更审计（旧/新范围、操作者、时间） | ✅ | ✅ | ⬜ | 同上 |
| 超级管理员知识范围审计查询接口 | ✅ | ✅ | ⬜ | 同上 |
| WeKnora 只读检索适配器（租户与知识库白名单） | ✅ | ✅ | ⬜ | `test_knowledge.py` |
| WeKnora 文档详情读取与范围校验 | ✅ | ✅ | ⬜ | `test_knowledge.py` |

## E. 运行时与外部适配器

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| 运行时契约、注册表、策略、Mock 执行器 | ✅ | ✅ | ⬜ | `test_runtime_{contracts,registry_config,policy,evaluation}.py`、`test_mock_runtime.py` |
| 运行时 HTTP 传输与适配器（DeerFlow / Codex Worker / Hermes） | ✅ | ✅ | ⬜ | `test_runtime_http_transport.py`、`test_runtime_adapters.py` |
| 开发期 RAGFlow/AgentScope 适配器契约与受控注册表 | ✅ | ✅ | ⬜ | `test_ragflow_adapter.py`、`test_runtime_adapters.py` |
| 外部 Runtime staging 前置预检脚本（五类 Runtime） | ✅ | ✅ | ⬜ | `test_runtime_staging_preflight.py`；门禁注明「不替代真实联调」 |
| RAGFlow/AgentScope 密钥注入、跨租户实测、并发压测、沙箱验证、真实外部服务验收 | ❌ | ❌ | ⬜ | **仅剩外部资源**：认证注入与注册表装配两处代码缺口已于 2026-09-11 修复（`docs/external-dependency-acceptance-plan.md` §6 第 5、6 条）。接入资料与索取表见 `docs/runtime-onboarding-request.md` |
| 真实模型、网页抓取、公众号自动发布验收 | ❌ | ❌ | ⬜ | **未做** |
| 计划生成与审核闸门（目标→`AgentPlan`→服务端风险推导→审批→复用 Runtime） | ✅ | ✅ | ⬜ | `test_planner_{api,service,models,generator,store,audit,bootstrap,postgres}.py` |
| 计划执行的反馈与指标采集（子项目②） | ✅ | ✅ | ⬜ | `test_run_records.py`、`test_run_metrics.py`、`test_run_metrics_api.py`、`test_planner_run_wiring.py`、`test_run_finish_reason.py`、`test_runtime_lifecycle.py`、`test_run_approval.py`、`test_run_approval_api.py`；终态与受控 `finish_reason`（迁移 `020`）已落盘，运行内审批决议闭环；**已知限制**：`knowledge_hits` 依赖运行时上报，Mock 下恒为 0 |
| 基于指标的编排优化提案（子项目③） | ✅ | ✅ | ⬜ | `test_orchestration_{models,store,postgres,service,api,bootstrap}.py`；设计见 `docs/superpowers/specs/2026-09-11-orchestration-proposal-design.md`；**审批通过不自动改配置** |
| 运行失败通知（站内） | ✅ | ✅ | ⬜ | 已接入：运行进入 `failed`/`cancelled` 终态时通知任务创建人（`run.failed` / `run.cancelled`）；接收人经 `task_id → created_by` 反查，任务不可见时跳过并写审计 `run.notify_skipped`。测试 `test_run_terminal_notifications.py` |
| 运行终态落盘与结束原因 | ✅ | ✅ | ⬜ | 写入者收敛到 `RuntimeService`（`start`/`pause`/`resume`/`cancel`/`decide_approval` 都回写同一记录并保留原始启动时间）；`finish_reason` 为受控枚举（含 `approval_rejected`），迁移 `020`；Mock 提供 `fail.` 前缀的确定性失败路径。测试 `test_run_finish_reason.py`、`test_runtime_lifecycle.py` |
| 运行内审批决议闭环 | ✅ | ✅ | ⬜ | `GET /api/v1/runs/{run_id}/approvals` 列审批项、`POST .../approvals/{approval_id}/approval` 决议；仅 CEO/超管且**发起人不能自审**；通过后执行被批准步骤并落到终态，驳回立即 `failed` + `finish_reason=approval_rejected`；审计 `run.approval_decided`、通知 `run.approval_rejected`。测试 `test_run_approval.py`、`test_run_approval_api.py`；管理台运行详情页可决议（见 J 节） |
| 审批人的运行审批待办入口 | ✅ | ✅ | ⬜ | 「待我审批」聚合新增第 4 类 `run_approval`（ceo/super_admin 可见、剔除发起人自审、`counts` 新增键、`detail` 带 `run_id`/`approval_id`）；伴侣端第 4 类卡片与通过/驳回动作（打到运行决议接口，**不会误发账号注册接口**）。测试 `test_approvals_run_kind.py`、`test_run_approval_todo.py` + 伴侣端 Vitest。**限制**：无「指派给某个审批人」概念；管理台仍无待办聚合页 |
| 运行时状态持久化（待办跨重启 / 多进程） | ✅ | ✅ | ⬜ | 迁移 `021` + `PostgresRuntimeStateStore`（整行 JSONB upsert，接口与内存实现对等）+ `app/runtime/serialization.py`（编解码、损坏数据抛 `InvalidRuntimeState`）+ `build_runtime_state_store`（postgres 强制持久化、memory 仅限 development、随启动跑迁移）；事件 payload **写入前即脱敏**。测试 `test_runtime_state_{serialization,postgres,write_through}.py`。**限制**：事件与状态同存一行（长运行写放大）；并发修改最后写入获胜；敏感键为精确匹配；**真实 PostgreSQL 重启恢复仍需 staging 验收** |
| 终态运行的审批复用（缺陷修复） | ✅ | ✅ | ✅（单测/接口） | 修复「先驳回一条审批使运行 `failed`，再批准另一条仍 `pending` 的审批会把运行**复活为 `completed`**」；新增 `RunNotDecidable` → `409`，Mock 在决议前校验终态。测试 `test_run_approval_todo.py`、`test_run_approval_api.py` |

## F. 事件与异步

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| Celery Worker/Outbox 可注入运行骨架、死信登记、人工重放接口 | ✅ | ✅ | ⬜ | `test_dead_letters.py`；门禁自述为「开发期」 |
| Worker 启动命令与生产模式自动绑定 Outbox 发布器 | ✅ | ✅ | ⬜ | 同上 |
| 死信通知渠道（脱敏 webhook + `notified_at` 原子去重 + 通知失败只写审计） | ✅ | ✅ | ⬜ | `test_dead_letter_notifications.py`、迁移 `015`；未配置 webhook 则不发送通知，死信仍可查可重放 |
| Celery Worker 实跑、Outbox 生产连接池、staging 验收 | ❌ | ❌ | ⬜ | **未做**（需真实 Redis 与 Worker 运行环境） |

## G. 内容工作台

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| 公众号内容工作台 Mock Alpha（素材→确定性草稿→自确认→Markdown 导出） | ✅ | ✅ | ⬜ | `test_content_{alpha,api,generator,service}.py` |
| 内容工作台 10 次内部闭环回归与幂等验收 | ✅ | ✅ | ✅（内部） | 门禁已勾选；**属内部回归，非平台侧验收** |
| 真实模型接入（OpenAI 兼容后端） | ✅ | ✅ | ⬜ | `test_content_openai_compatible.py`；**未用真实密钥联调** |
| 网页抓取器（域名白名单 / robots / 限速 / 体积截断 / 留痕） | ✅ | ✅ | ⬜ | `test_content_scraper.py`（19 项）；白名单为空即关闭（fail-closed）；**真实抓取未验收** |
| 公众号发布器（幂等键 `task:revision` + 唯一约束 / 回执核对 / 失败人工接管且绝不自动重发） | ✅ | ✅ | ⬜ | `test_content_publications.py`（16 项）、迁移 `016`；**真实发布未验收** |
| 内容安全评估用例（提示词注入 / 数据泄露 / 越权输出，canary 判定 + 反向控制） | ✅ | ✅ | ⬜ | `app/content/safety.py`、`scripts/content_safety_evaluation.py`、`test_content_safety.py`（10 项）；方法见 `docs/content-safety-evaluation.md`；**离线通过只证明仪器可用，真实模型结论需重跑** |

## H. 商业化私有部署

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| G0 租户、工作区、客户管理员、套餐、追加式用量账本 | ✅ | ✅ | ⬜ | `test_commercial_{tenant,usage,api,lifecycle}.py` |
| G0 PostgreSQL 迁移与商业化接口 | ✅ | ✅ | ⬜ | `test_commercial_persistence.py` |
| 商业化 PostgreSQL 代码装配与契约测试 | ✅ | ✅ | ⬜ | 同上；门禁注明「未替代真实数据库验收」 |
| 租户导出/删除冷静期、保留策略、脱敏预检脚本 | ✅ | ✅ | ⬜ | `test_commercial_preflight.py`、`test_commercial_lifecycle.py` |
| 本地真实 PostgreSQL 迁移与备份/恢复演练 | ✅ | ✅ | ✅（本地） | 门禁已勾选；**未替代 staging 验收** |
| 真实 PostgreSQL 商业化迁移、备份/恢复演练、客户管理员验收 | ❌ | ❌ | ⬜ | **未做** |
| 私有部署生产预检、容量压测、独立密钥轮换、试点客户交付 | ❌ | ❌ | ⬜ | **未做**；**部分进展（2026-09-16）**：容量测算已完成**本机级**（`docs/private-deployment-runbook.md`「容量与并发」：实测表 + 连接账目 + `--max-tasks-per-child` 参数决定），**不替代**客户侧 / staging 容量压测与试点交付 |

## I. 审计与合规

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| 账号关键操作结构化审计（8 类动作，审计表 + stdout JSON） | ✅ | ✅ | ⬜ | `test_audit_{redaction,models,logging,store,postgres,bootstrap}.py`、`test_account_audit.py`；顶层键走白名单，明细值若为嵌套结构则按敏感键递归拒绝 |
| 计划模块生成/审批/驳回/执行纳入审计（4 类动作） | ✅ | ✅ | ⬜ | `test_planner_audit.py` |
| 通用审计查询接口 + 管理台审计页 | ✅ | ✅ | ⬜ | `GET /api/v1/audits`（仅 CEO/超管、严格本租户、动作/目标/操作者/时间筛选、`limit`+`offset`+`total`、未知动作码与无时区时间 422）；管理台 `admin-web/src/features/auditLog/`（Vitest 13 项，侧栏「安全与审计」）；33 个动作的中文标签由 `test_frontend_audit_labels.py` 守护。**限制**：offset 翻页在并发写入下可能错位；不支持导出与 `detail` 模糊搜索 |
| 审计落 PG 的实跑验证与日志采集告警 | ❌ | ❌ | ⬜ | **部分完成（2026-09-16）**：① 审计落 PG 已获**本机级实跑证据**——容器演练中知识治理扫描 4 轮共写 1600 行 `workbench_audit_log`（actor=`system:worker`，另见「本地真实 PostgreSQL 迁移与备份/恢复演练」的本机口径）；② **告警规则已成文**（`docs/private-deployment-runbook.md`「监控与告警」9 条，含「审计是否在落」信号）；**但告警渠道未接入任何环境、也未在真实环境复测** ⇒ 本项仍为未验收（此前 PG 仓储仅有假连接静态断言） |
| 攻击面八类检查**正式报告**（宪法第八章） | ✅ | — | ⬜ | `docs/security-attack-surface-report.md`；基于本机 `TestClient` 实测，**真实 staging / 生产环境验收未做** |
| 应用容器化（Dockerfile） | ✅ | ✅ | ⬜ | `Dockerfile`、`docker-compose.app.yml`、`test_container_assets.py`（静态资产校验）；**2026-09-16 追加**：镜像带 OCI 版本标签（`org.opencontainers.image.version` / `revision`，测试守护）、三服务容器日志上限（`json-file` / `10m`×`5`，`docker inspect` 实查生效），真实镜像构建与容器运行已在本机 Docker 演练取证（2026-09-15 / 09-16，见 runbook「容器化部署」第 5 条）；**客户侧 / 生产拓扑未验收**（告警渠道亦未接入） |
| 桌面端自动更新（接线 + 搬运层演练） | ✅ | ✅ | ⬜ | `desktop/src/config.cjs`（fail-closed 更新策略）、`desktop/src/main.cjs`（electron-updater 接线）、`scripts/desktop_update_drill.py`、`test_desktop_assets.py`、`test_desktop_update_drill.py`；**「旧版 → 新版」真实更新链路未验收** |
| 桌面应用签名/公证/干净电脑测试（宪法 2.5） | ❌ | — | ⬜ | **未做**：需 Windows 代码签名证书（OV/EV）+ 可信时间戳 + 干净 Windows 机器，属外部资源 |

## J. 客户端

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| 网页管理台（知识权限、公众号内容工作台、内容历史、协同动态、通知、安全与审计、员工与岗位、数字员工设置、用量与费用） | ✅ | ✅（Vitest，**147 项**——2026-09-12 口径；原记 108 项已过期） | ⬜ | `admin-web/`（9 个侧栏 feature 页面 + 运行详情页） |
| 协同动态只读接口与任务权限过滤 | ✅ | ✅ | ⬜ | 门禁已勾选；响应已含租户/项目/责任人 |
| 协同动态表现层（静态状态列表） | ✅ | ✅ | ⬜ | `admin-web/src/features/collaborationDynamics/`（页面 + 4 项 Vitest）；**已知限制**：仅呈现 `TaskStatus` 三态，文档 5 态词表无领域支撑 |
| 伴侣端待办聚合接口 `GET /api/v1/approvals/pending` | ✅ | ✅ | ⬜ | `test_approvals_{service,store,api}.py`、`test_approvals_run_kind.py`；四类 kind（含 `run_approval`）+ 按角色过滤 + 计划提案与运行审批自审排除 + 注册标识脱敏 |
| Electron 桌面端（README 声明为主员工端） | ✅ | ✅ | ⬜ | `desktop/`（Electron 安全壳 + electron-builder NSIS 配置）；`node --test` 19 项 + `test_desktop_assets.py` 10 项；**未签名、未打包、未做干净电脑测试** |
| 手机 PWA 伴侣端（审批与提醒） | ✅ | ✅ | ⬜ | `companion-pwa/`（登录、待办轮询、四类审批、manifest 与 service worker）；Vitest 37 项 + `test_pwa_assets.py` 8 项；**提醒是轮询而非 Web Push，真机安装未验收** |
| 员工站内通知收件箱（通知页 + 未读角标） | ✅ | ✅ | ⬜ | 后端 `app/inbox.py` + 迁移 `019_inbox_items` + 三接口（`test_inbox_{store,service,api}.py`）；管理台 `admin-web/src/features/inbox/`（含「通知」导航入口）、伴侣端 `companion-pwa/src/features/inbox/`（Vitest 8 项）；写入失败不阻断主流程并写审计 `inbox.write_failed`；十类触发点（含运行失败 `run.failed`、被取消 `run.cancelled`、审批被驳回 `run.approval_rejected`），服务端推送未实现 |
| 管理台运行详情页（指标 / 事件时间线 / 审批决议） | ✅ | ✅ | ⬜ | `admin-web/src/features/runDetail/`（Vitest 20 项，含分区独立失败与自审隐藏）；入口为通知页 `run.*` 跳转与 `?view=run&run=<run_id>` 直达；事件 payload 只渲染白名单字段；**无运行列表页**（后端无租户级运行索引），**不含**暂停/恢复/取消；两端收件箱 kind 漂移已修复并由 `test_frontend_inbox_kinds.py` 守护 |
| 管理台「员工与岗位」只读清单页 | ✅ | ✅ | ⬜ | 后端 `GET /api/v1/workforce/roster`（仅超管、严格本租户、三源并集）+ `KnowledgeAccessRegistry.list_bindings` 与 `TaskStore.count_by_employee` 双实现（`test_workforce_roster_{store,api}.py`）；前端 `admin-web/src/features/workforce/`（Vitest 12 项）；侧栏「员工与岗位」接上真实页面并删除写死的 18/42 假数据块。**限制**：不是目录管理（无实体、无增删改）、不含系统角色分布、`task_count` 为精确匹配 |

| 管理台「数字员工设置」岗位/员工目录（阶段 1） | ✅ | ✅ | ⬜ | 迁移 `022_workforce_directory.sql`（复合外键 `(tenant_id, role_key)` 写进约束）+ `app/workforce/`（标识规范与强制小写、内存与 PG 双实现、仓储层与接口层各拦一次权限、写审计的服务层）+ 7 个接口（仅超管、严格本租户、列表分页、标识不可改、停用不删除）（`test_workforce_directory_{store,api}.py`）+ 管理台 `admin-web/src/features/workforceSettings/`（Vitest 17 项，含未纳管纳管）；**并删掉「知识权限管理」页写死的岗位/员工下拉**（改为读目录），6 个审计动作 33→39。**未做（阶段 2）**：无 —— 阶段 2 已于 2026-09-12 完成（知识范围写路径强制「标识已在目录且启用」→ `409`，**员工还要求所属岗位 `active`**，判定顺序先 `403` 后 `409`，绑定键按 D5 归一；读/检索不变）；**并已在本机一次性真实 PostgreSQL（`pgvector/pgvector:pg16`）回归通过**：迁移 022、复合外键拦截、闸门/归一/跨租户/鉴权优先均符合预期。**限制**：`agent_key` 与任务 `employee_key` 同名不同值域、不含模型/Runtime/技能绑定与组织部门；staging 仍未验收 |

| 管理台「用量与费用」只读页 | ✅ | ✅ | ⬜ | 复用既有 `GET /api/v1/commercial/usage`（账本 `workbench_usage_ledger` 的租户级累计 `units` / `cost_cents`）+ `admin-web/src/features/billing/`（Vitest 14 项）；六态齐备（加载/正常/空/403/404/错误重试），金额按整数分精确换算、支持冲正负值；**不改后端、无迁移**。侧栏「模型与费用」改名「用量与费用」。**限制**：只有租户级累计（无时间/模型/任务维度）、`units` 不解释语义、`404`（未登记租户）是常见态；**模型侧未做**（需专项评审后立项） |

## K. 交付与运维

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| staging 独立主机部署模板与统一前置预检 | ✅ | ✅ | ⬜ | `test_staging_preflight.py`、`.env.staging.example` |
| Staging 验收清单、证据要求与阻塞条件 | ✅ | — | — | `docs/staging-acceptance-checklist.md` |
| 提交门禁 CI（push / PR 强制跑全量测试与编译） | ✅ | ✅ | ✅（CI 环境） | `.github/workflows/ci.yml`（后端 pytest+compileall、两个前端 vitest+build、桌面 node --test）、`tests/test_ci_assets.py` 静态契约守护；**已在 GitHub Actions 实跑通过：run `34591258934`（当前 v7 版工作流），4 个 job 全绿**（首次实跑 run `34590744934`；该 ✅ 指 CI 环境，不代表 staging / 生产验收） |
| 迁移回滚演练 | ❌ | ❌ | ⬜ | **未做** |
| staging 数据库实测与真实并发压测 | ❌ | ❌ | ⬜ | **未做**；**部分进展（2026-09-16）**：并发探针脚本 `scripts/staging_concurrency_probe.py` 已就绪、容量测算已在本机级完成（runbook「容量与并发」），但 **staging 数据库实测与真实并发压测仍未做** |
| 真实 staging 与真实平台账号验收 | ❌ | ❌ | ⬜ | **未做**。平台已确定为**公众号**（`docs/external-dependency-acceptance-plan.md` §5）；接入资料与索取表见 `docs/platform-account-onboarding.md`（含账号权限硬约束与两条落地路径） |
| GEO 版本化适配器 | ❌ | ❌ | ⬜ | **外部依赖阻塞**：GEO 属独立仓库的外部系统，本仓库无其 API 契约/版本规则/认证方式（`app/`、`tests/` 中 GEO 零命中），无法仅靠本仓库落地。已产出契约索取表 `docs/geo-contract-request.md`（**索取草案，非已确认契约**） |

---

## README 能力声明 vs 实际

| README 声明 | 实际状态 |
| --- | --- |
| 「主员工端采用 Windows 桌面端」 | 已建 `desktop/` Electron 安全壳；**安装包构建/签名/公证/干净电脑测试未验收** |
| 「网页端用于管理和远程协作」 | 已建成管理台 **9 个侧栏页面**（内容工作台、通知、员工与岗位、知识权限管理、数字员工设置、用量与费用、历史草稿、协同动态、安全与审计）+ 运行详情页 |
| 「手机端先以 PWA 伴侣形式提供审批与提醒」 | 已建 `companion-pwa/`（登录 + 待办轮询 + **四类审批**（含运行审批 `run_approval`）+ 未读通知区块）；**提醒为轮询，未做 Web Push** |
| 「生产部署切换到 PostgreSQL、Redis、对象存储和异步 Worker」 | 代码路径具备，**从未在真实环境跑通** |
| 「统一登录和短期会话」 | 自建账号 + 短期会话 + TOTP 二次验证 + OIDC SSO 客户端已实现；**SSO 真实 IdP 联调与设备绑定未做** |
| 「通知」 | **部分**：① 已实现**死信运维通知渠道**（脱敏 webhook + 原子去重，`app/notifications.py`、迁移 `015`）；② 已实现面向员工的**站内通知收件箱**（`app/inbox.py`、迁移 `019`，覆盖任务审批、计划与编排提案审核、内容发布转人工接管、运行失败与被取消、账号注册通过；两端已接入口）；**仍未实现**：服务端推送，伴侣端提醒为客户端轮询。运行记录在终态落盘并带受控 `finish_reason`（迁移 `020`） |
| 「GEO 版本化适配器接入」 | **外部依赖阻塞**（见 K 节与阻塞项 6） |

## 阻塞项：需要外部资源（代码无法代替）

> **怎么做（可勾选执行清单、每项含「谁提供输入 + 验证命令 + 通过判据」）**：见 [`docs/delivery-remaining-checklist.md`](delivery-remaining-checklist.md)，其编号与本表 1–8 一一对应。

| # | 阻塞项 | 需要的输入 |
| --- | --- | --- |
| 1 | 真实环境全部验收 | 独立主机/云上的 PostgreSQL、Redis、对象存储实例与凭据 |
| 2 | 生产密钥与轮换 | 部署密钥系统注入 `WORKBENCH_AUTH_SECRET`、`WORKBENCH_BACKUP_ENCRYPTION_KEY`（≥32 位且不同），以及轮换流程 |
| 3 | 外部 Runtime 联调 | RAGFlow / AgentScope 的 HTTPS 地址、固定版本、认证注入、隔离测试账号 |
| 4 | 跨租户测试与并发压测 | 上述 1–3 就绪后执行 |
| 5 | 真实模型与发布验收 | 真实模型密钥、目标平台账号与发布授权 |
| 6 | GEO 版本化适配器 | GEO 侧的 API 契约（端点、认证、数据模型、错误语义）、固定版本号与版本兼容/升级规则、读写边界。GEO 在独立 Git 仓库，本仓库内无任何 GEO 定义，**无法仅靠代码落地** |
| 7 | 桌面端签名、公证与干净电脑测试 | Windows 代码签名证书（OV/EV）与可信时间戳服务；一台干净的 Windows 机器做安装→打开→更新全流程（宪法 2.5） |
| 8 | PWA 真机安装与推送验收 | 真机（iOS/Android）安装性验证；若要真推送，还需 HTTPS 域名与 VAPID 密钥 |

## 建议推进顺序

1. ~~先把审计与登录限流分支合入 `main`~~ ✅（2026-09-11 已合入）。
2. ~~容器化：补应用 `Dockerfile`~~ ✅（本轮已完成，见 I 节）。
3. ~~补齐宪法硬缺口：口令弱口令策略、管理员 TOTP 二次验证~~ ✅（本轮已完成）；登录限流的生产并发原子性验证仍待 staging。
4. ~~产出攻防八类检查正式报告~~ ✅（本轮已完成，见 I 节）。
5. ~~合并本批次分支 `feature/compliance-deployable` 回 `main`~~ ✅（2026-09-11 已合入）。
6. ~~规划能力闭环：数据分级闸门、运行指标采集、编排优化提案~~ ✅（本批次已完成，见 C/E 节）。
7. ~~协同动态表现层（静态状态列表）~~ ✅（本批次已完成，见 J 节）。
8. ~~客户端三端：待办聚合接口 + PWA 伴侣端 + Electron 桌面端~~ ✅（本批次已完成，见 J 节）。
9. ~~合并批次分支回 `main`~~ ✅（`feature/compliance-deployable`、规划能力闭环与 `feature/acceptance-tooling` 的内容均已进入 `main`；`feature/acceptance-tooling` 于 2026-09-11 **快进合入**，`main` 基线为后端 **975** 项 + `admin-web` 18 + `companion-pwa` 24 + `desktop` 13 全绿——**该组为 2026-09-11 历史快照，当前基线见文档头部**）。
10. ~~内容安全评估用例（项 9 的最后一块代码缺口）~~ ✅（已完成：canary 判定 + 反向控制，见 G 节与 `docs/content-safety-evaluation.md`）。
11. **拿到外部资源后**：跑 `py scripts/staging_preflight.py` → `py scripts/staging_concurrency_probe.py` → 跨租户测试 → 并发压测 → 沙箱验证 → 真实联调；内容侧另跑 `py scripts/content_safety_evaluation.py` 并留存 JSON 报告。
12. **桌面端发布链**：固定依赖版本 → 代码签名与时间戳 → 安装包构建 → 干净 Windows 机器验收（阻塞项 7）。
13. **PWA 真机验收**：真机安装性验证；若要真推送再引入 HTTPS + VAPID（阻塞项 8）。
14. **GEO 适配器**：待 GEO 侧提供契约后再启动（见阻塞项 6），不做占位实现。
15. ~~员工站内通知收件箱~~ ✅（本批次已完成：迁移 `019` + `app/inbox.py` 双仓储 + 三接口 + 两端入口，见 J 节）；配套登记「运行终态未落盘」缺口（E 节），运行失败通知待运行终态落盘后再接入；服务端推送仍属未实现。
16. ~~运行终态落盘 + 运行结果通知~~ ✅（已完成：`RuntimeService` 统一回写 start/pause/resume/cancel、受控 `finish_reason`（迁移 `020`）、Mock `fail.` 失败路径、`run.failed`/`run.cancelled` 站内通知，见 E/J 节）；新登记缺口「带审批步骤的运行终态」（E 节）。
17. ~~运行内审批决议闭环~~ ✅（已完成：两个接口 + 仅 CEO/超管且发起人不能自审 + 通过/驳回驱动终态 + `finish_reason=approval_rejected` + 审计与通知，见 E 节）；新登记缺口「审批人的租户级待办入口」（E 节）。
18. ~~管理台运行详情页~~ ✅（已完成：指标 / 事件时间线 / 审批决议，通知跳转与 URL 直达，见 J 节）；配套修复两端收件箱 kind 漂移并加守护测试。运行列表页与暂停/恢复/取消仍属未做（见 J 节限制）。
19. ~~审批人的运行审批待办入口~~ ✅（已完成：聚合第 4 类 `run_approval` + 伴侣端第 4 类卡片与决议动作，见 E/J 节），**E 节原有 ❌ 项已清零**；新登记缺口「运行时状态持久化」（E 节）。
20. ~~运行时状态持久化~~ ✅（已完成：迁移 `021` + PG 状态仓储 + 编解码与写入即脱敏 + postgres 强制持久化装配，见 E 节）；**E 节当前无 ❌ 项**。真实 PostgreSQL 的重启恢复仍需 staging 验收（阻塞项 1）。
21. ~~通用审计查询接口 + 管理台审计页~~ ✅（已完成：`GET /api/v1/audits` + `admin-web/src/features/auditLog/`，见 I 节）；配套 33 个动作标签的漂移守护测试。
22. ~~管理台「员工与岗位」只读清单页~~ ✅（已完成：`GET /api/v1/workforce/roster` + 两个只读查询 + `admin-web/src/features/workforce/`，见 J 节）；同时**删掉侧栏写死的「18 个岗位 / 42 个数字员工」假数据块**。（该项写入时「数字员工设置」与「模型与费用」都还没有数据源，后续分别由推进项 23、24 落地。）
23. ~~岗位与数字员工目录（「数字员工设置」）立项~~ ✅（立项文档 `docs/superpowers/specs/2026-09-12-agent-directory-design.md`，4 项口径已确认）；**阶段 1 已实现**：迁移 `022` + `app/workforce/` + 7 个接口 + 管理台「数字员工设置」页，并删掉「知识权限管理」页写死的岗位/员工下拉（见 J 节）。**阶段 2 已完成（2026-09-12）**：知识范围写路径强制「标识已在目录且启用」（未纳管/已停用/格式非法/跨租户 `409`），判定顺序先 `403` 后 `409`，绑定键按口径 D5 归一到 `strip().lower()`；读/检索解析不变。**已知限制**：目录用 `agent_key`、任务用 `employee_key`（同值不同名，未统一）；不含模型/Runtime/技能绑定与组织部门。设计见 `docs/superpowers/specs/2026-09-12-agent-directory-design.md`（实施与验证记录见 §14.5）。
24. ~~管理台「用量与费用」只读页~~ ✅（2026-09-12 已完成：复用 `GET /api/v1/commercial/usage` + 新增 `admin-web/src/features/billing/`，**不改后端、无迁移**，见 J 节）；侧栏占位项「模型与费用」改名为「用量与费用」。**同时修正一处文档口径**：费用侧**本来就有**追加式账本与只读接口（早前笼统记为「无数据源」不准确），缺的是页面与维度；**模型侧仍未做**——模型由配置注入（`content_model_*` / `planner_model_*`），无实体表与接口，要落地必须先立项定「配置即真源还是建表并改 `ModelGateway` 取数」，属地基层面变更。

## 生成时的核实记录

以下「❌ 未实现」的判定在生成本清单时**实际执行命令核实过**，非凭印象：

| 判定 | 核实方式 | 结果 |
| --- | --- | --- |
| 无应用 `Dockerfile` | 全仓递归查 `Dockerfile*` | 0 个命中（仅有基础设施 `docker-compose.yml`） |
| 无 Electron / 桌面端工程 | 全仓查 `package.json`（排除 `node_modules`） | 仅 `admin-web/package.json` 一个 |
| 管理台仅 3 个页面 | 列 `admin-web/src/features/` 下的页面组件 | 命中 `knowledgeAccess`、`contentWorkbench`、`contentHistory` 三组 |
| 无通知实现 | 在 `app/` 内检索 `notification` / `notify` / `webhook` | 0 个命中 |
| 无弱口令策略与管理员二次验证 | 在 `app/` 内检索 `weak_password` / `common_password` / `mfa` / `totp` / `second_factor` | 0 个命中 |

> **注**：以上是 2026-09-10 生成本清单时的**一次性**核实记录。其中「无应用 Dockerfile」「无弱口令策略与管理员二次验证」已于 2026-09-11 第一批次落地；「管理台仅 3 个页面」已于第二批次变为 4 个（新增协同动态）、第十八批次变为 5 个（新增通知），**截至 2026-09-12 为 9 个**（新增员工与岗位、数字员工设置、用量与费用、安全与审计）；「无 Electron 工程」已于第三批次落地（新增 `desktop/`）；**「无通知实现」已不再成立**——死信运维通知渠道（脱敏 webhook）已于同批次实现（`app/notifications.py`、迁移 `015`），面向员工的**站内通知收件箱**已于第十八批次实现（`app/inbox.py`、迁移 `019`）；**仍未实现**的是**服务端推送**（伴侣端提醒是**客户端轮询**）；而「运行失败通知」**已不再成立**——运行终态已落盘（迁移 `020`、受控 `finish_reason`），`run.failed` / `run.cancelled` / `run.approval_rejected` 已接入站内通知（见 E 节）。最新状态以正文各节点为准。

其余「✅ 实现」项依据是 `delivery-gates.md` 已勾选；「测试 ✅」依据是 `tests/` 下存在对应主题的测试文件（**仅按文件名与主题匹配，未逐条核对覆盖度**）。

## 维护约定

- 本清单**不引入新的事实源**：每项状态以 `docs/delivery-gates.md` 的勾选与仓库文件为准；`delivery-gates.md` 更新后本清单应同步。
- **未通过真实验收的能力不得标为已上线/已发布/已收录**（宪法与 README Git 约定）。
- 本清单**不使用百分比**，因为「完成度」在本项目里无法客观度量；请以「已实现 / 已测试 / 已验收」三档计数为准。
