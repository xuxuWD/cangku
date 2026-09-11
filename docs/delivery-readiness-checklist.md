# 交付就绪清单

> **用途**：把 `docs/delivery-gates.md` 的勾选状态摊开成可逐项追踪的底账，区分「代码在」「有测试守护」「在真实环境验收过」三种不同状态。
>
> **生成日期**：2026-09-10；**2026-09-11 同步三态**（第一次：容器化、弱口令策略、TOTP 二次验证、攻击面报告；第二次：数据分级闸门、协同动态表现层、运行指标采集、编排优化提案、GEO 阻塞更正）
> **基线**：分支 `feature/planning-closure`，全量 **615 项测试通过**，`compileall` 退出码 0
>
> **证据口径（重要）**：本清单以 `docs/delivery-gates.md` 的勾选状态、`tests/` 目录的 75 个测试文件、`README.md` 的能力声明为准。标 ✅ 表示仓库内存在实现且门禁已勾选，**不等于我逐项重新验收过**；需要真实环境证据的项一律标 ⬜。

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
| 门禁总项数 | **56**（`delivery-gates.md`） |
| 已勾选（实现） | **46** |
| 未勾选 | **10** |
| 达到**真实环境验收** | **0**（部分是本地真实验证，见「本地已验证」一行） |
| 本地已验证（真实 PostgreSQL 迁移与备份恢复演练、内容工作台内部闭环回归） | **2** |
| 测试文件数 | **75**（`tests/`，不含 `conftest.py`） |
| 测试用例数 | **615** |

> **一句话结论**：服务端能力基本齐全，**剩余卡点集中在「真实环境验收」「外部系统契约（GEO）」与「客户端」三处**，而不是功能缺口。

---

## A. 平台骨架

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| 独立 Git 仓库与 GEO 边界确认 | ✅ | — | — | `README.md`「项目边界」「与 GEO 的边界」 |
| FastAPI 服务入口与健康检查 | ✅ | ✅ | ⬜ | `test_control_plane.py` |
| 开发期任务幂等、租户隔离、风险审批、审计计数 | ✅ | ✅ | ⬜ | `test_control_plane.py` |
| 基础依赖、环境示例、Docker Compose | ✅ | — | ⬜ | `.env.example`、`docker-compose.yml`（基础设施）；应用编排见 I 节「应用容器化」 |
| 契约测试与 Python 编译检查 | ✅ | ✅ | — | `test_persistence_contract.py` |
| PostgreSQL 任务 CRUD、唯一约束、原子审批、迁移 runner | ✅ | ✅ | ⬜ | `test_persistence_contract.py`；**未在真实 PG 上运行** |
| PostgreSQL 连接池适配、审计读取、审批事务 | ✅ | ✅ | ⬜ | 同上 |
| Redis Streams/Celery 事件总线、Outbox 事务写入、幂等消费者**骨架** | ✅ | ✅ | ⬜ | `test_events.py`、`test_outbox.py`；门禁自述为「骨架」 |
| 按存储模式选择事件总线、生产 API 不重复直发 Outbox | ✅ | ✅ | ⬜ | `test_outbox.py` |

## B. 身份与账号

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| 自建账号注册审批、登录会话、管理员重置密码 | ✅ | ✅ | ⬜ | `test_account_{api,auth,service,repository,passwords,bootstrap,postgres}.py` |
| 账号登录限流与失败锁定 | ✅ | ✅ | ⬜ | `test_login_rate_limit.py`、`test_account_audit.py`；门禁注明「生产并发与网关层限流仍需 staging 验收」 |
| 设备绑定、生产密钥轮换、真实统一登录验收 | ❌ | ❌ | ⬜ | **未实现**（SSO 与设备绑定未做；TOTP 二次验证已完成，见下两行） |
| 口令弱口令策略（禁止纯数字与常见口令） | ✅ | ✅ | ⬜ | `test_account_password_policy.py`；**已知限制**：不校验是否含手机号/姓名、不做变形归一 |
| 管理员动态口令二次验证（TOTP） | ✅ | ✅ | ⬜ | `test_totp.py`、`test_account_totp.py`、`test_account_totp_api.py`、`test_account_repository_totp.py`；真实部署的验证器兼容性未验收 |

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
| RAGFlow/AgentScope staging 前置预检脚本 | ✅ | ✅ | ⬜ | `test_runtime_staging_preflight.py`；门禁注明「不替代真实联调」 |
| RAGFlow/AgentScope 密钥注入、跨租户实测、并发压测、沙箱验证、真实外部服务验收 | ❌ | ❌ | ⬜ | **未做**（等外部资源） |
| 真实模型、网页抓取、公众号自动发布验收 | ❌ | ❌ | ⬜ | **未做** |
| 计划生成与审核闸门（目标→`AgentPlan`→服务端风险推导→审批→复用 Runtime） | ✅ | ✅ | ⬜ | `test_planner_{api,service,models,generator,store,audit,bootstrap,postgres}.py` |
| 计划执行的反馈与指标采集（子项目②） | ✅ | ✅ | ⬜ | `test_run_records.py`、`test_run_metrics.py`、`test_run_metrics_api.py`、`test_planner_run_wiring.py`；**已知限制**：`knowledge_hits` 依赖运行时上报，Mock 下恒为 0 |
| 基于指标的编排优化提案（子项目③） | ✅ | ✅ | ⬜ | `test_orchestration_{models,store,postgres,service,api,bootstrap}.py`；设计见 `docs/superpowers/specs/2026-09-11-orchestration-proposal-design.md`；**审批通过不自动改配置** |

## F. 事件与异步

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| Celery Worker/Outbox 可注入运行骨架、死信登记、人工重放接口 | ✅ | ✅ | ⬜ | `test_dead_letters.py`；门禁自述为「开发期」 |
| Worker 启动命令与生产模式自动绑定 Outbox 发布器 | ✅ | ✅ | ⬜ | 同上 |
| Celery Worker 实跑、Outbox 生产连接池、死信通知渠道、staging 验收 | ❌ | ❌ | ⬜ | **未做** |

## G. 内容工作台

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| 公众号内容工作台 Mock Alpha（素材→确定性草稿→自确认→Markdown 导出） | ✅ | ✅ | ⬜ | `test_content_{alpha,api,generator,service}.py` |
| 内容工作台 10 次内部闭环回归与幂等验收 | ✅ | ✅ | ✅（内部） | 门禁已勾选；**属内部回归，非平台侧验收** |
| 真实模型接入（OpenAI 兼容后端） | ✅ | ✅ | ⬜ | `test_content_openai_compatible.py`；**未用真实密钥联调** |

## H. 商业化私有部署

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| G0 租户、工作区、客户管理员、套餐、追加式用量账本 | ✅ | ✅ | ⬜ | `test_commercial_{tenant,usage,api,lifecycle}.py` |
| G0 PostgreSQL 迁移与商业化接口 | ✅ | ✅ | ⬜ | `test_commercial_persistence.py` |
| 商业化 PostgreSQL 代码装配与契约测试 | ✅ | ✅ | ⬜ | 同上；门禁注明「未替代真实数据库验收」 |
| 租户导出/删除冷静期、保留策略、脱敏预检脚本 | ✅ | ✅ | ⬜ | `test_commercial_preflight.py`、`test_commercial_lifecycle.py` |
| 本地真实 PostgreSQL 迁移与备份/恢复演练 | ✅ | ✅ | ✅（本地） | 门禁已勾选；**未替代 staging 验收** |
| 真实 PostgreSQL 商业化迁移、备份/恢复演练、客户管理员验收 | ❌ | ❌ | ⬜ | **未做** |
| 私有部署生产预检、容量压测、独立密钥轮换、试点客户交付 | ❌ | ❌ | ⬜ | **未做** |

## I. 审计与合规

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| 账号关键操作结构化审计（8 类动作，审计表 + stdout JSON） | ✅ | ✅ | ⬜ | `test_audit_{redaction,models,logging,store,postgres,bootstrap}.py`、`test_account_audit.py` |
| 计划模块生成/审批/驳回/执行纳入审计（4 类动作） | ✅ | ✅ | ⬜ | `test_planner_audit.py` |
| 审计落 PG 的实跑验证与日志采集告警 | ❌ | ❌ | ⬜ | **未做**（PG 仓储仅用假连接做静态断言） |
| 攻击面八类检查**正式报告**（宪法第八章） | ✅ | — | ⬜ | `docs/security-attack-surface-report.md`；基于本机 `TestClient` 实测，**真实 staging / 生产环境验收未做** |
| 应用容器化（Dockerfile） | ✅ | ✅ | ⬜ | `Dockerfile`、`docker-compose.app.yml`、`test_container_assets.py`（静态资产校验）；**真实镜像构建与容器运行未验收** |
| 桌面应用签名/公证/自动更新/干净电脑测试（宪法 2.5） | ❌ | — | ⬜ | **未开始** |

## J. 客户端

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| 网页管理台（知识权限、公众号内容工作台、内容历史、协同动态） | ✅ | ✅（Vitest） | ⬜ | `admin-web/`（4 个 feature 页面） |
| 协同动态只读接口与任务权限过滤 | ✅ | ✅ | ⬜ | 门禁已勾选；响应已含租户/项目/责任人 |
| 协同动态表现层（静态状态列表） | ✅ | ✅ | ⬜ | `admin-web/src/features/collaborationDynamics/`（页面 + 4 项 Vitest）；**已知限制**：仅呈现 `TaskStatus` 三态，文档 5 态词表无领域支撑 |
| Electron 桌面端（README 声明为主员工端） | ❌ | ❌ | ⬜ | **未开工** |
| 手机 PWA 伴侣端（审批与提醒） | ❌ | ❌ | ⬜ | **未开工** |

## K. 交付与运维

| 项 | 实现 | 测试 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| staging 独立主机部署模板与统一前置预检 | ✅ | ✅ | ⬜ | `test_staging_preflight.py`、`.env.staging.example` |
| Staging 验收清单、证据要求与阻塞条件 | ✅ | — | — | `docs/staging-acceptance-checklist.md` |
| 迁移回滚演练 | ❌ | ❌ | ⬜ | **未做** |
| staging 数据库实测与真实并发压测 | ❌ | ❌ | ⬜ | **未做** |
| 真实 staging 与真实平台账号验收 | ❌ | ❌ | ⬜ | **未做** |
| GEO 版本化适配器 | ❌ | ❌ | ⬜ | **外部依赖阻塞**：GEO 属独立仓库的外部系统，本仓库无其 API 契约/版本规则/认证方式（`app/`、`tests/` 中 GEO 零命中），无法仅靠本仓库落地 |

---

## README 能力声明 vs 实际

| README 声明 | 实际状态 |
| --- | --- |
| 「主员工端采用 Windows 桌面端」 | **未开工**（无 Electron 工程） |
| 「网页端用于管理和远程协作」 | 部分：4 个页面的管理台（知识权限、内容工作台、内容历史、协同动态） |
| 「手机端先以 PWA 伴侣形式提供审批与提醒」 | **未开工** |
| 「生产部署切换到 PostgreSQL、Redis、对象存储和异步 Worker」 | 代码路径具备，**从未在真实环境跑通** |
| 「统一登录和短期会话」 | 自建账号 + 短期会话 + TOTP 二次验证已实现；**SSO 与设备绑定未做** |
| 「通知」 | 门禁中无对应实现项，**未见实现** |
| 「GEO 版本化适配器接入」 | **外部依赖阻塞**（见 K 节与阻塞项 6） |

## 阻塞项：需要外部资源（代码无法代替）

| # | 阻塞项 | 需要的输入 |
| --- | --- | --- |
| 1 | 真实环境全部验收 | 独立主机/云上的 PostgreSQL、Redis、对象存储实例与凭据 |
| 2 | 生产密钥与轮换 | 部署密钥系统注入 `WORKBENCH_AUTH_SECRET`、`WORKBENCH_BACKUP_ENCRYPTION_KEY`（≥32 位且不同），以及轮换流程 |
| 3 | 外部 Runtime 联调 | RAGFlow / AgentScope 的 HTTPS 地址、固定版本、认证注入、隔离测试账号 |
| 4 | 跨租户测试与并发压测 | 上述 1–3 就绪后执行 |
| 5 | 真实模型与发布验收 | 真实模型密钥、目标平台账号与发布授权 |
| 6 | GEO 版本化适配器 | GEO 侧的 API 契约（端点、认证、数据模型、错误语义）、固定版本号与版本兼容/升级规则、读写边界。GEO 在独立 Git 仓库，本仓库内无任何 GEO 定义，**无法仅靠代码落地** |

## 建议推进顺序

1. ~~先把审计与登录限流分支合入 `main`~~ ✅（2026-09-11 已合入）。
2. ~~容器化：补应用 `Dockerfile`~~ ✅（本轮已完成，见 I 节）。
3. ~~补齐宪法硬缺口：口令弱口令策略、管理员 TOTP 二次验证~~ ✅（本轮已完成）；登录限流的生产并发原子性验证仍待 staging。
4. ~~产出攻防八类检查正式报告~~ ✅（本轮已完成，见 I 节）。
5. ~~合并本批次分支 `feature/compliance-deployable` 回 `main`~~ ✅（2026-09-11 已合入）。
6. ~~规划能力闭环：数据分级闸门、运行指标采集、编排优化提案~~ ✅（本批次已完成，见 C/E 节）。
7. ~~协同动态表现层（静态状态列表）~~ ✅（本批次已完成，见 J 节）。
8. **合并本批次分支 `feature/planning-closure` 回 `main`**（本轮成果，615 项测试已绿）。
9. **拿到外部资源后**：跑 `py scripts/staging_preflight.py` → 跨租户测试 → 并发压测 → 沙箱验证 → 真实联调。
10. **客户端**：剩下的 Electron 桌面端与 PWA 伴侣端（建议先做 PWA 审批提醒，再评估桌面端）。
11. **GEO 适配器**：待 GEO 侧提供契约后再启动（见阻塞项 6），本轮已按外部依赖阻塞处理，不做占位实现。

## 生成时的核实记录

以下「❌ 未实现」的判定在生成本清单时**实际执行命令核实过**，非凭印象：

| 判定 | 核实方式 | 结果 |
| --- | --- | --- |
| 无应用 `Dockerfile` | 全仓递归查 `Dockerfile*` | 0 个命中（仅有基础设施 `docker-compose.yml`） |
| 无 Electron / 桌面端工程 | 全仓查 `package.json`（排除 `node_modules`） | 仅 `admin-web/package.json` 一个 |
| 管理台仅 3 个页面 | 列 `admin-web/src/features/` 下的页面组件 | 命中 `knowledgeAccess`、`contentWorkbench`、`contentHistory` 三组 |
| 无通知实现 | 在 `app/` 内检索 `notification` / `notify` / `webhook` | 0 个命中 |
| 无弱口令策略与管理员二次验证 | 在 `app/` 内检索 `weak_password` / `common_password` / `mfa` / `totp` / `second_factor` | 0 个命中 |

> **注**：以上是 2026-09-10 生成本清单时的**一次性**核实记录。其中「无应用 Dockerfile」「无弱口令策略与管理员二次验证」已于 2026-09-11 第一批次落地；「管理台仅 3 个页面」已于 2026-09-11 第二批次变为 4 个（新增协同动态）。最新状态以正文各节点为准；「无 Electron 工程」「无通知实现」仍与当前一致。

其余「✅ 实现」项依据是 `delivery-gates.md` 已勾选；「测试 ✅」依据是 `tests/` 下存在对应主题的测试文件（**仅按文件名与主题匹配，未逐条核对覆盖度**）。

## 维护约定

- 本清单**不引入新的事实源**：每项状态以 `docs/delivery-gates.md` 的勾选与仓库文件为准；`delivery-gates.md` 更新后本清单应同步。
- **未通过真实验收的能力不得标为已上线/已发布/已收录**（宪法与 README Git 约定）。
- 本清单**不使用百分比**，因为「完成度」在本项目里无法客观度量；请以「已实现 / 已测试 / 已验收」三档计数为准。
