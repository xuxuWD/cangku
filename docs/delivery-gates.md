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
- [x] RAGFlow/AgentScope staging 前置预检脚本与验收证据要求（不替代真实联调）
- [x] staging 独立主机部署模板与统一前置预检（基础设施隔离 + 商业化 G0 + 外部 Runtime）
- [x] 应用容器化（Dockerfile 非 root、健康检查走标准库、密钥仅从环境注入）—— 静态资产校验通过；真实镜像构建与容器运行需在具备 Docker 的环境验收
- [x] 攻击面八类检查正式报告（docs/security-attack-surface-report.md）—— 基于本机 TestClient 实测；真实 staging、真实 PostgreSQL 与真实外部平台验收仍未完成
- [x] Celery Worker/Outbox 的可注入运行骨架、死信登记与人工重放接口（开发期）
- [x] Worker 启动命令与生产模式自动绑定 Outbox 发布器
- [ ] Celery Worker 实跑、Outbox 生产连接池、死信通知渠道和 staging 验收 —— **代码缺口已补齐**：死信通知渠道已实现（迁移 015 + `app/notifications.py` 的脱敏 webhook、原子去重、通知失败只写审计不打断发布循环），并已补 `docs/private-deployment-runbook.md` 的异步链路章节；仍缺真实 Redis、Worker 运行环境与通知渠道地址
- [x] 自建账号注册审批、登录会话与管理员重置密码（开发期接口验证）
- [x] 计划生成与审核闸门：目标到 AgentPlan 提案、服务端风险推导、审批后复用既有 Runtime（开发期接口验证）
- [x] 计划执行的反馈与指标采集（子项目②）—— 运行记录表（迁移 013）+ `RunRecord` 双仓储 + `RunMetricsService` 聚合 + `GET /api/v1/runs/{run_id}/metrics` 与 `GET /api/v1/metrics/summary`；提案回写 `run_id`。开发期接口验证，`knowledge_hits` 依赖运行时上报，Mock 下恒为 0（已知限制）
- [x] 基于指标的编排优化提案（子项目③）—— 迁移 014 + `app/orchestration/` 提案生成/状态机/审批/审计 + 5 个接口；样本门槛与改善阈值双闸门，样本不足不出提案；**审批通过不自动改配置**。设计见 `docs/superpowers/specs/2026-09-11-orchestration-proposal-design.md`
- [x] 账号登录限流与失败锁定（宪法第一道防线要求）—— 开发期接口验证，429 行为已测试；生产并发与网关层限流仍需 staging 验收
- [x] 账号关键操作结构化审计日志（注册、审批、登录、改密、重置）—— 审计表 + stdout 结构化日志，开发期接口验证；PostgreSQL 实跑与日志采集仍需 staging 验收
- [x] 计划模块的生成、审批与执行纳入审计（与上一项一并落地）—— plan.proposed/approved/rejected/run_started 已写入审计，开发期接口验证；PostgreSQL 实跑仍需 staging 验收
- [x] 规划输入的数据分级与 `ModelGateway` 闸门 —— 数据分级由服务端从 `Task.risk_level` 推导（low→internal / medium→confidential / high→restricted），拒绝客户端指定；真实模型后端在生成前经 `ModelGateway` 授权，未获准则 403，Mock 后端不外发数据不介入
- [x] 口令弱口令策略（禁止纯数字、重复单一字符与常见弱口令）—— 在 `hash_password` 统一实施，注册/改密/重置三条链路生效；不校验是否包含手机号或姓名，且不做变形归一（已知限制已写入 API 契约）
- [x] 管理员动态口令二次验证（TOTP）—— 自建实现（仅标准库）、绑定/确认/重置与受限令牌；**TOTP 种子在持久化适配器静态加密**（AES-256-GCM，子密钥由备份加密密钥经 HKDF-SHA256 派生，密文 `v1:` 前缀，历史明文只读兼容，内存仓储不落盘故不加密）；开发期接口验证，真实部署的验证器兼容性仍需验收
- [x] 会话令牌服务端撤销（登出立即生效）—— 迁移 `018` + `workbench_session_revocations` 撤销名单（内存 / PostgreSQL 双实现）+ `POST /api/v1/auth/logout`；鉴权依赖在每次请求校验撤销状态，登出后同一令牌立即 `401`；撤销查询失败按 `503` fail-closed，缺少 `jti` 的令牌按无效处理，开发期头部身份不适用
- [ ] 生产密钥轮换与真实统一登录验收 —— **口径变更（2026-09-11）**：原门禁写法的「设备绑定」不再列入，产品决定采用「注册申请 + 管理员审批」制（重复手机号有提示、审批时由管理员指定角色、发起人不能自审），设备绑定明确不做；本项剩余要求为部署密钥系统的生产轮换与真实 IdP 的统一登录验收，均需外部资源。变更理由见文末「门禁口径变更记录」
- [x] Electron 桌面端和 PWA 伴侣端 —— 桌面端 `desktop/`（Electron 安全壳：contextIsolation、禁用 nodeIntegration、沙箱、导航白名单、外链走系统浏览器、禁 webview；远程/内置两种加载模式；electron-builder NSIS 配置、**未配置签名**）；伴侣端 `companion-pwa/`（登录、待办轮询、三类审批、手写 service worker 且**不缓存 `/api/`**、manifest 与图标）。配套后端新增 `GET /api/v1/approvals/pending` 待办聚合接口。**真实安装包构建/代码签名/公证/干净电脑测试与真机 PWA 安装均未验收**
- [x] 协同动态表现层（静态状态列表：网页管理台「协同动态」页，含加载/空/错误态与查看任务跳转）—— 仅呈现 `TaskStatus` 现有三态，文档 5 态词表中的「执行中/等待发布/已完成/需要人工处理」尚无领域状态支撑（已知限制已写入 `docs/collaboration-dynamics.md`）；Pixi/Spine 动画仍待评估
- [x] 协同动态只读接口与任务权限过滤
- [x] 微信公众号内容工作台 Mock Alpha：素材提交、确定性草稿、自确认和 Markdown 导出
- [x] 内容工作台 10 次内部闭环回归与幂等验收
- [x] 私有部署 G0 租户、工作区、客户管理员、套餐与追加式用量账本
- [x] 私有部署 G0 PostgreSQL 迁移与商业化接口（开发期接口验证）
- [x] 商业化 PostgreSQL 代码装配与契约测试（未替代真实数据库验收）
- [x] 本地真实 PostgreSQL 迁移与备份/恢复演练（未替代 staging 验收）
- [x] Staging 验收清单、证据要求与阻塞条件
- [x] 租户导出/删除冷静期、保留策略与脱敏预检脚本
- [ ] 真实 PostgreSQL 商业化迁移、备份/恢复演练与客户管理员验收
- [ ] 私有部署生产预检、容量压测、独立密钥轮换与试点客户交付
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

> **CI 强制范围**：第 2–4 条中机器可判定的部分由 `.github/workflows/ci.yml` 在 push / PR 上执行——后端 `pytest` + `compileall`、`admin-web` 与 `companion-pwa` 的 `vitest run` + 生产构建、`desktop` 的 `node --test`（跳过 Electron 二进制下载）。第 1、5、6 条属人工约定，CI 不覆盖。**已在 GitHub Actions 实跑通过**：push 触发 run `34591258934`（当前 v7 版工作流），4 个 job 全绿（后端 31s / 管理台 14s / 伴侣端 13s / 桌面端 13s）；首次实跑为 run `34590744934`。门禁命令与安全约束另由 `tests/test_ci_assets.py` 静态守护。

RAGFlow/AgentScope 当前仅完成开发期适配器契约与受控注册表验证；`FakeTransport` 测试不等于真实 staging 或真实平台账号验收。

## 门禁口径变更记录

| 日期 | 原口径 | 新口径 | 理由 |
| --- | --- | --- | --- |
| 2026-09-11 | 设备绑定、生产密钥轮换和真实统一登录验收 | 生产密钥轮换与真实统一登录验收（**移除设备绑定**） | 产品决定登录采用「注册申请 + 管理员审批」制：申请人提交账号/密码/职位/个人信息，管理员审批通过即可登录，重复手机号有提示，角色由管理员在审批时指定。设备绑定在该模型下不再是必要条件，故从门禁移除并明确不做；该项剩余部分（密钥轮换、统一登录）仍需外部资源，保持未勾选。 |

> 口径变更只调整**要求本身**，不改变任何既有代码事实；变更后 9 项未勾选门禁与 `docs/delivery-readiness-checklist.md` 保持同步。
