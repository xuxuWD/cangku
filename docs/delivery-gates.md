# 交付门禁

## 当前阶段

- [x] 独立 Git 仓库与 GEO 边界确认
- [x] FastAPI 服务入口和健康检查
- [x] 开发期任务幂等、租户隔离、风险审批和审计计数
- [x] 模型能力筛选与敏感数据阻断
- [x] 分层记忆和受控成长提案
- [x] 基础依赖、环境示例和 Docker Compose
- [x] 契约测试和 Python 编译检查
- [x] PostgreSQL 任务 CRUD、唯一约束、原子审批和迁移 runner 契约
- [x] PostgreSQL 连接池适配、审计读取和审批事务契约
- [ ] staging 数据库实测、迁移回滚演练和真实并发压测 —— 并发探针脚本 `scripts/staging_concurrency_probe.py` **已实现**（登录限流 / 任务幂等 / 审批原子性三场景，含 HTTPS 与非本地护栏、离线单测覆盖）；仍缺独立 staging 主机、备份介质与专用探针账号
- [x] Redis Streams/Celery 事件总线、Outbox 事务写入与幂等消费者骨架
- [x] 按存储模式选择事件总线，生产 API 不重复直发 Outbox 事件
- [x] 高风险能力策略目录（第三方 Skill、Shell、特权沙箱、知识/提示词/流程变更）
- [x] WeKnora 只读检索适配器（租户与知识库白名单）
- [x] WeKnora 文档详情读取与租户/知识库范围校验
- [x] 岗位/数字员工知识库范围注册表与自动解析
- [x] 岗位/数字员工知识范围 PostgreSQL 持久化迁移与连接池适配
- [x] 超级管理员岗位/数字员工知识范围配置接口
- [x] 知识范围变更审计（旧范围/新范围/操作者/时间）
- [x] 超级管理员知识范围审计查询接口
- [x] 开发期 RAGFlow/AgentScope 适配器契约与受控注册表
- [x] 外部 Runtime staging 前置预检脚本（五类 Runtime：RAGFlow/AgentScope + DeerFlow/Codex Worker/Hermes）与验收证据要求（不替代真实联调）
- [x] staging 独立主机部署模板与统一前置预检（基础设施隔离 + 商业化 G0 + 外部 Runtime）
- [x] 应用容器化（Dockerfile 非 root、健康检查走标准库、密钥仅从环境注入）—— 静态资产校验通过；真实镜像构建与容器运行需在具备 Docker 的环境验收。**2026-09-16 追加**：镜像带 OCI 版本标签（`org.opencontainers.image.version` / `revision`）、三服务容器日志上限（`json-file` / `max-size=10m` / `max-file=5`）已在本机 Docker 演练取证（`docker image inspect` / `docker inspect`；见 `docs/private-deployment-runbook.md`「容器化部署」第 1、5 条），并由 `tests/test_container_assets.py`、`tests/test_compose_worker_assets.py` 守护；**客户侧 / 生产拓扑仍未验收**（告警渠道亦未接入）
- [x] 攻击面八类检查正式报告（docs/security-attack-surface-report.md）—— 基于本机 TestClient 实测；真实 staging、真实 PostgreSQL 与真实外部平台验收仍未完成
- [x] Celery Worker/Outbox 的可注入运行骨架、死信登记与人工重放接口（开发期）
- [x] Worker 启动命令与生产模式自动绑定 Outbox 发布器
- [ ] Celery Worker 实跑、Outbox 生产连接池、死信通知渠道和 staging 验收 —— **代码缺口已补齐**：死信通知渠道已实现（迁移 015 + `app/notifications.py` 的脱敏 webhook、原子去重、通知失败只写审计不打断发布循环），并已补 `docs/private-deployment-runbook.md` 的异步链路章节；仍缺真实 Redis、Worker 运行环境与通知渠道地址。**2026-09-16 本机级取证**：容器编排三服务（app / worker / beat）同镜像起栈、`beat` 三类排程（outbox-publisher / lifecycle-jobs / knowledge-review-scan）均派发并被执行、Outbox 600 条经真实 Redis 发布、审计真实落 PG（4 轮共 1600 行 / actor=`system:worker`）、容量测算与 `--max-tasks-per-child` 参数决定（runbook「容量与并发」）；**仍缺**：staging / 客户侧环境与死信通知渠道地址（**告警规则已成文、渠道未接**，见 runbook「监控与告警」）
- [x] 自建账号注册审批、登录会话与管理员重置密码（开发期接口验证）
- [x] 计划生成与审核闸门：目标到 AgentPlan 提案、服务端风险推导、审批后复用既有 Runtime（开发期接口验证）
- [x] 计划执行的反馈与指标采集（子项目②）—— 运行记录表（迁移 013）+ 结束原因（迁移 020）+ `RunRecord` 双仓储 + `RunMetricsService` 聚合 + `GET /api/v1/runs/{run_id}/metrics` 与 `GET /api/v1/metrics/summary`；提案回写 `run_id`。**运行终态已落盘**：记录的写入者收敛到 `RuntimeService`（直启运行、计划驱动运行、内容生成运行与暂停/恢复/取消都回写同一记录，保留原始启动时间）；`finish_reason` 为受控枚举（`run_completed`/`cancelled_by_user`/`step_failed`/`approval_rejected`），Mock 提供 `fail.` 前缀的确定性失败路径。**运行内审批已闭环**：`GET /api/v1/runs/{run_id}/approvals` 列出审批项、`POST /api/v1/runs/{run_id}/approvals/{approval_id}/approval` 决议（仅 CEO/超管且发起人不能自审），通过后执行被批准步骤并落到终态、驳回立即 `failed`，写审计 `run.approval_decided` 并通知提交人 `run.approval_rejected`。开发期接口验证，`knowledge_hits` 依赖运行时上报，Mock 下恒为 0（已知限制）；审批人仍**没有租户级待办入口**（缺口见就绪清单 E 节）
- [x] 基于指标的编排优化提案（子项目③）—— 迁移 014 + `app/orchestration/` 提案生成/状态机/审批/审计 + 5 个接口；样本门槛与改善阈值双闸门，样本不足不出提案；**审批通过不自动改配置**。设计见 `docs/superpowers/specs/2026-09-11-orchestration-proposal-design.md`
- [x] 账号登录限流与失败锁定（宪法第一道防线要求）—— 开发期接口验证，429 行为已测试；生产并发与网关层限流仍需 staging 验收
- [x] 账号关键操作结构化审计日志（注册、审批、登录、改密、重置）—— 审计表 + stdout 结构化日志，开发期接口验证；PostgreSQL 实跑与日志采集仍需 staging 验收
- [x] 计划模块的生成、审批与执行纳入审计（与上一项一并落地）—— plan.proposed/approved/rejected/run_started 已写入审计，开发期接口验证；PostgreSQL 实跑仍需 staging 验收
- [x] 规划输入的数据分级与 `ModelGateway` 闸门 —— 数据分级由服务端从 `Task.risk_level` 推导（low→internal / medium→confidential / high→restricted），拒绝客户端指定；真实模型后端在生成前经 `ModelGateway` 授权，未获准则 403，Mock 后端不外发数据不介入
- [x] 口令弱口令策略（禁止纯数字、重复单一字符与常见弱口令）—— 在 `hash_password` 统一实施，注册/改密/重置三条链路生效；不校验是否包含手机号或姓名，且不做变形归一（已知限制已写入 API 契约）
- [x] 管理员动态口令二次验证（TOTP）—— 自建实现（仅标准库）、绑定/确认/重置与受限令牌；**TOTP 种子在持久化适配器静态加密**（AES-256-GCM，子密钥由备份加密密钥经 HKDF-SHA256 派生，密文 `v1:` 前缀，历史明文只读兼容，内存仓储不落盘故不加密）；开发期接口验证，真实部署的验证器兼容性仍需验收
- [x] 会话令牌服务端撤销（登出立即生效）—— 迁移 `018` + `workbench_session_revocations` 撤销名单（内存 / PostgreSQL 双实现）+ `POST /api/v1/auth/logout`；鉴权依赖在每次请求校验撤销状态，登出后同一令牌立即 `401`；撤销查询失败按 `503` fail-closed，缺少 `jti` 的令牌按无效处理，开发期头部身份不适用
- [ ] 生产密钥轮换与真实统一登录验收 —— **口径变更（2026-09-11）**：原门禁写法的「设备绑定」不再列入，产品决定采用「注册申请 + 管理员审批」制（重复手机号有提示、审批时由管理员指定角色、发起人不能自审），设备绑定明确不做；本项剩余要求为部署密钥系统的生产轮换与真实 IdP 的统一登录验收，均需外部资源。变更理由见文末「门禁口径变更记录」
- [x] Electron 桌面端和 PWA 伴侣端 —— 桌面端 `desktop/`（Electron 安全壳：contextIsolation、禁用 nodeIntegration、沙箱、导航白名单、外链走系统浏览器、禁 webview；远程/内置两种加载模式；electron-builder NSIS 配置、**未配置签名**）；伴侣端 `companion-pwa/`（登录、待办轮询、四类审批、手写 service worker 且**不缓存 `/api/`**、manifest 与图标）。配套后端新增 `GET /api/v1/approvals/pending` 待办聚合接口。**真实安装包构建/代码签名/公证/干净电脑测试与真机 PWA 安装均未验收**
- [x] 员工站内通知收件箱 —— 迁移 `019_inbox_items` + `app/inbox.py`（内存 / PostgreSQL 双仓储、服务端固定文案不含用户输入与手机号、幂等已读、按保留期惰性清理）+ 三个接口（`GET /api/v1/inbox`、`POST /api/v1/inbox/{inbox_id}/read`、`POST /api/v1/inbox/read-all`）；触发点覆盖任务审批通过、计划与编排提案通过/驳回、内容发布转人工接管、运行失败与被取消、运行内审批被驳回、账号注册通过。通知写入失败**不阻断**主流程并写审计 `inbox.write_failed`。两端入口：管理台「通知」页、伴侣端未读通知区块。**未接入**：服务端推送仍未实现。设计见 `docs/superpowers/specs/2026-09-11-inbox-notification-design.md`、`docs/superpowers/specs/2026-09-11-run-lifecycle-design.md` 与 `docs/superpowers/specs/2026-09-11-run-approval-decision-design.md`
- [x] 通用审计查询接口与管理台审计页 —— `GET /api/v1/audits`（仅 `ceo`/`super_admin`；**严格本租户**，不含 `tenant_id` 为空的全局记录；按动作（可重复）/目标/操作者/时间范围筛选；`limit` 1–200 + `offset` + `total`；未知动作码与无时区时间 `422`；只读）+ 管理台 `features/auditLog/`（筛选、列表、分页、空/错态，侧栏「安全与审计」）。33 个审计动作的中文标签由 `tests/test_frontend_audit_labels.py` 守护。**已知限制**：`offset` 分页在翻页期间有新写入时可能错位；`total` 为额外 COUNT；不支持导出与 `detail` 模糊搜索。设计见 `docs/superpowers/specs/2026-09-11-audit-query-design.md`
- [x] 岗位与数字员工清单（只读）—— `GET /api/v1/workforce/roster`（仅 `super_admin`；严格本租户；**三个事实源并集**：知识范围 `role` 绑定、`agent` 绑定、任务中出现过的 `employee_key`；排序 `task_count` 倒序 + `key` 升序；只读且不返回 PII）+ 两个只读查询 `KnowledgeAccessRegistry.list_bindings` 与 `TaskStore.count_by_employee`（内存 / PostgreSQL 双实现）+ 管理台 `features/workforce/`（标识、两类知识范围、任务数；加载/空/错态），侧栏「员工与岗位」接上真实页面并**删除写死的「18 个岗位 / 42 个数字员工」假数据块**。**已知限制**：不是目录管理（无实体、无增删改）；不含系统角色分布；`task_count` 为 `employee_key` 精确匹配（大小写/空格不同即视为不同标识）。设计见 `docs/superpowers/specs/2026-09-11-workforce-roster-design.md`
- [x] 岗位与数字员工目录（「数字员工设置」**阶段 1**）—— 迁移 `022_workforce_directory.sql`（`workbench_job_roles` / `workbench_digital_employees`，**复合外键把租户隔离写进约束**）+ `app/workforce/`（标识规范 `^[a-z0-9][a-z0-9._-]{0,63}$` 且强制小写、内存与 PostgreSQL 双实现、仓储层与接口层各强制一次权限、写审计的服务层）+ 7 个接口（`GET`/`POST /api/v1/workforce/roles`、`PATCH /api/v1/workforce/roles/{role_key}`、`GET`/`POST /api/v1/workforce/agents`、`PATCH /api/v1/workforce/agents/{agent_key}`、`GET /api/v1/workforce/candidates`；仅 `super_admin`；严格本租户；列表必分页；**标识创建后不可改**；**停用不删除**；岗位不存在或已停用不能挂载员工）+ 管理台 `features/workforceSettings/`（岗位/数字员工两个页签、新建、改中文名与所属岗位、停用/启用、**未纳管标识一键纳管**），并**删除「知识权限管理」页写死的岗位/员工下拉与「内容中心 · 6 名员工」文案**，改为读取目录。新增 6 个审计动作（33 → 39）。**阶段 2 已完成（2026-09-12）**：知识范围**写**路径要求标识已在目录且启用（未纳管/已停用/格式非法/跨租户一律 `409`「该标识尚未纳入目录，请先在「数字员工设置」中纳管」；**数字员工还要求其所属岗位也是 `active`**），判定顺序为**先 `403` 后 `409`**（`DirectoryNotManaged` 刻意不继承 `PolicyError`），并按口径 D5 把绑定键归一到 `strip().lower()`（读/写/审计统一）；**读路径与检索解析不变**，历史自由文本绑定仍可用。**已在真实 PostgreSQL（本机一次性 `pgvector/pgvector:pg16`）回归通过**：迁移 022 可建、复合外键真实存在且能拦住孤儿员工、闸门/归一/跨租户/鉴权优先全部符合预期（设计文档 §14.6）。**已知限制**：目录用 `agent_key`、任务用 `employee_key`（同值不同名，未统一）；不含模型/Runtime/技能绑定与组织部门。设计见 `docs/superpowers/specs/2026-09-12-agent-directory-design.md`（实施与验证记录见 §14.5/§14.6）
- [x] 管理台「用量与费用」页（只读）—— 复用既有 `GET /api/v1/commercial/usage`（追加式账本 `workbench_usage_ledger` 的两个租户级累计 `units` / `cost_cents`；权限沿用 `super_admin` 或本租户登记的 `customer_admin`），**不改后端、无迁移**；前端 `admin-web/src/features/billing/`（只读展示、加载/正常/空/403/404/错误重试六态；金额按**整数分**精确换算为元、支持冲正后的负数，不使用浮点）。侧栏占位项「模型与费用」**改名为「用量与费用」**（宪法：做不到的功能不上界面）。**已知限制**：只有租户级累计（无时间/模型/任务维度）；`units` 只展示原值不解释语义；`404`（本租户未登记）是未初始化环境的常见态；**模型侧未做**——模型由配置注入，无实体表与接口，需专项评审后单独立项。设计见 `docs/superpowers/specs/2026-09-12-usage-billing-page-design.md`
- [x] 运行时状态持久化（迁移 `021`）—— `PostgresRuntimeStateStore`（整行 JSONB upsert，接口与内存实现对等）+ `app/runtime/serialization.py`（编解码、`InvalidRuntimeState` 严格失败）+ `build_runtime_state_store`（postgres 强制持久化、memory 仅限 development、随启动跑迁移）。事件 payload **写入前即脱敏**（与读取共用同一套敏感键规则）。因此暂停/恢复/取消/决议/事件与指标查询、以及运行审批待办**跨重启与多进程可用**。**已知限制**：事件与状态同存一行（长运行有写放大）；并发修改最后写入获胜；敏感键为精确匹配。设计见 `docs/superpowers/specs/2026-09-11-runtime-state-persistence-design.md`
- [x] 审批人的运行审批待办入口 —— 「待我审批」聚合新增第 4 类 `run_approval`（ceo/super_admin 可见、剔除发起人自审、`counts` 新增键），伴侣端提供第 4 类卡片与通过/驳回动作（打到 `POST /runs/{run_id}/approvals/{approval_id}/approval`，不会误发账号注册接口）。配套修复「终态运行可被剩余审批复活」的缺陷（新增 `RunNotDecidable` → `409`）。**已知限制**：无「指派给某个审批人」概念；管理台仍无待办聚合页。设计见 `docs/superpowers/specs/2026-09-11-run-approval-todo-design.md`
- [x] 管理台运行详情页（运行可观测） —— `admin-web/src/features/runDetail/`：运行指标（含 `finish_reason`）、事件时间线（只渲染白名单字段）、审批项与「通过/驳回」决议；入口为通知页 `run.*` 提醒跳转与 `?view=run&run=<run_id>` 直达。**没有运行列表页**（后端无租户级运行索引），**不含**暂停/恢复/取消控制。配套修复两端收件箱 kind 漂移并新增守护测试 `tests/test_frontend_inbox_kinds.py`。设计见 `docs/superpowers/specs/2026-09-11-run-detail-page-design.md`
- [x] 协同动态表现层（静态状态列表：网页管理台「协同动态」页，含加载/空/错误态与查看任务跳转）—— 仅呈现 `TaskStatus` 现有三态，文档 5 态词表中的「执行中/等待发布/已完成/需要人工处理」尚无领域状态支撑（已知限制已写入 `docs/collaboration-dynamics.md`）；Pixi/Spine 动画仍待评估
- [x] 协同动态只读接口与任务权限过滤
- [x] 微信公众号内容工作台 Mock Alpha：素材提交、确定性草稿、自确认和 Markdown 导出
- [x] 内容工作台 10 次内部闭环回归与幂等验收
- [x] 私有部署 G0 租户、工作区、客户管理员、**套餐配置**与追加式用量账本（**注 2026-09-14**：「套餐」指**配置与存储**（`workbench_plan_versions` 表与 `PlanVersion` 结构），**不含配额强制** —— 配额/超额策略经用户裁决**不属本期**，见规格 §8 U25 的 E5 条；`delivery-gates` 勾选不做撤回）
- [x] 私有部署 G0 PostgreSQL 迁移与商业化接口（开发期接口验证）
- [x] 商业化 PostgreSQL 代码装配与契约测试（未替代真实数据库验收）
- [x] 本地真实 PostgreSQL 迁移与备份/恢复演练（未替代 staging 验收）
- [x] Staging 验收清单、证据要求与阻塞条件
- [x] 租户导出/删除冷静期、保留策略与脱敏预检脚本
- [ ] 真实 PostgreSQL 商业化迁移、备份/恢复演练与客户管理员验收
- [ ] 私有部署生产预检、容量压测、独立密钥轮换与试点客户交付 —— **2026-09-16 注记**：容量测算已完成**本机级**（`docs/private-deployment-runbook.md`「容量与并发」：实测表、连接账目与参数决定），**不替代** staging / 客户侧真实容量压测与试点交付
- [ ] GEO 版本化适配器 —— **外部依赖阻塞**：GEO 属独立仓库的外部系统，本仓库内无其 API 契约、版本规则与认证方式（`app/`、`tests/` 中 GEO 零命中）；需 GEO 侧先提供契约文档后才能实现并做契约测试
- [ ] 真实 staging 与真实平台账号验收
- [ ] RAGFlow/AgentScope 密钥注入、跨租户实测、并发压测、沙箱验证和真实外部服务验收
- [ ] 真实模型、网页抓取和公众号自动发布验收 —— **代码缺口已全部闭合**：`app/content/scraper.py`（域名白名单 / robots / 限速 / 体积上限 / 留痕）、`app/content/publisher.py` + 迁移 016（幂等键 `task:revision` + 数据库唯一约束、回执核对、失败转人工接管且绝不自动重发）、`app/content/safety.py` + `scripts/content_safety_evaluation.py`（内容安全评估：提示词注入 / 数据泄露 / 越权输出，canary 判定 + 反向控制，方法见 `docs/content-safety-evaluation.md`）；导出层已按脱敏词元表遮蔽来源链接中的凭证。真实部分仍缺真实模型密钥、平台凭据与发布授权

## 每次提交必须满足

1. 先增加或更新行为测试，再修改生产代码。
2. `python -m pytest -q` 全部通过。
3. `python -m compileall -q app tests extract_pdf.py` 通过。
4. 新接口同步更新 `docs/api-contract.md`（由 `tests/test_api_contract_coverage.py` 守护：每个 `/api/` 路由都必须能在契约中查到完整路径）。
5. 不提交 `.env`、密钥、Cookie、浏览器会话、客户原文或临时媒体。
6. 未通过真实验收的能力不能写成“已上线”“已发布”或“已收录”。

> **CI 强制范围**：第 2–4 条中机器可判定的部分由 `.github/workflows/ci.yml` 在 push / PR 上执行——后端 `pytest` + `compileall`、`admin-web` 与 `companion-pwa` 的 `vitest run` + 生产构建、`desktop` 的 `node --test`（跳过 Electron 二进制下载）。第 1、5、6 条属人工约定，CI 不覆盖。**已在 GitHub Actions 实跑通过**：push 触发 run `34591258934`（当时 v7 版工作流），4 个 job 全绿（后端 31s / 管理台 14s / 伴侣端 13s / 桌面端 13s）；首次实跑为 run `34590744934`。门禁命令与安全约束另由 `tests/test_ci_assets.py` 静态守护。
>
> **真库 job（2026-09-14 新增）**：工作流新增第 5 个 job **`postgres`**——用一次性 `pgvector/pgvector:0.8.0-pg16`（按镜像摘要钉死）起真库、以**仓库自身的 `app.migrations.apply_migrations`** 应用 `migrations/*.sql`、设 `WORKBENCH_TEST_DATABASE_URL`，逐个跑「真连库」模块（当前 3 个：`tests/test_tool_action_store_postgres.py` / `tests/test_dsh_execution_postgres.py` / `tests/test_commercial_lifecycle_postgres.py`）并**要求 `skipped == 0`**；用于把这些此前「无 DSN 即整体 skip ⇒ CI 与一键跑全量都不含它 ⇒ 未受守护」的模块纳入 CI（模块清单可增列，守护方式不变）。默认 `backend` job（无库）行为不变。**✅ 已在 GitHub Actions 实跑通过（2026-09-14）**：push `c17ae5d` 触发 run **`34834157946`**（`2026-09-14T10:38Z` 起）——**run 级 `conclusion=success` ⇒ 5 个 job 全绿**（含本 `postgres` job，显示名「后端真库（Postgres service + *_postgres.py）」）；在此之前本机一次性容器已验证其步骤可跑通。（**原"未验证：该 job 尚未在 GitHub Actions 实跑过"一项，据此销掉。**）该 job 另有 **6 条静态守护**（`tests/test_ci_assets.py`：job 存在 / **镜像摘要值钉死为常量** / 应用仓库自身迁移 / 设 DSN / 逐个逐字断言所列真库模块（漏跑任一模块即红） / **`skipped == 0` 零容忍**）⇒ **防止被删除或改弱**。

RAGFlow/AgentScope 当前仅完成开发期适配器契约与受控注册表验证；`FakeTransport` 测试不等于真实 staging 或真实平台账号验收。

## 门禁口径变更记录

| 日期 | 原口径 | 新口径 | 理由 |
| --- | --- | --- | --- |
| 2026-09-11 | 设备绑定、生产密钥轮换和真实统一登录验收 | 生产密钥轮换与真实统一登录验收（**移除设备绑定**） | 产品决定登录采用「注册申请 + 管理员审批」制：申请人提交账号/密码/职位/个人信息，管理员审批通过即可登录，重复手机号有提示，角色由管理员在审批时指定。设备绑定在该模型下不再是必要条件，故从门禁移除并明确不做；该项剩余部分（密钥轮换、统一登录）仍需外部资源，保持未勾选。 |
| 2026-09-15 | `postgres` job 只跑 2 个「真连库」模块 | `postgres` job **逐个跑 3 个**（纳入 `tests/test_commercial_lifecycle_postgres.py`） | 新增的真库模块（PG 侧排序确定性等）由 `WORKBENCH_TEST_DATABASE_URL` 门控、本机与默认 `backend` job 均无该变量 ⇒ **整体 skip，无人自动跑**；纳入后该模块随 job 一并真跑，且 `skipped == 0` 判定与镜像摘要钉死均未放宽，另由 `tests/test_ci_assets.py` 逐字断言所列模块（漏跑任一即红）。**未改变**任何既有代码事实。**✅ 已在 GitHub Actions 实跑通过**：push `e602a44` 触发 run **`34870650538`**（`2026-09-14T16:46Z` 起 = 本地 `2026-09-15 00:46`）——run 级 `conclusion=success` ⇒ 5 个 job 全绿，该 job 日志末行 **`真库用例：tests=33 skipped=0 failed=0`**。 |

| 2026-09-15 | 无（**新增门禁**） | **新增 `sandbox` job**：按 digest 拉取钉死镜像，真跑 `tests/test_container_executor.py`（§3.3 加固口径 + G7′）与 `tests/test_exec_sandbox_escape.py`（G5 逃逸回归 13 条），并要求 `skipped == 0` | G5 / 规格 §8 U28：两组真容器回归均由「Docker + 钉死镜像」门控 ⇒ 在默认 `backend` job 里**整体 skip、无人自动跑**（本机 Docker 未启动时亦同）⇒「把沙箱边界变成可复现的取证」会退化成纸面动作。纳入后**真跑且零容忍 skip**；镜像摘要与所列测试文件另由 `tests/test_ci_assets.py` 逐字断言（漏跑或换镜像即红）。该 job 同时是 **G1/G3/G4 在 Linux 宿主上的复测点**。**未改变**任何既有代码事实。**⚠ 未验证**：本 job **尚无 push 触发的运行记录**（本机 Docker 守护进程未启动 ⇒ 该组用例本机亦整组 skip），**在实跑回填前不得声称"13 条全绿"**。 |

> 口径变更只调整**要求本身**，不改变任何既有代码事实；变更后 9 项未勾选门禁与 `docs/delivery-readiness-checklist.md` 保持同步。
