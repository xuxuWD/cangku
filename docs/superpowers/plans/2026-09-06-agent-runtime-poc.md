# Agent Runtime POC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变工作台控制平面事实源的前提下，建立可替换、可隔离、可回滚的 Agent Runtime 适配层，并用 Mock Runtime、DeerFlow、Codex Worker 和 Hermes 成长提案完成首轮可验收 POC。

**Architecture:** FastAPI 控制平面继续负责租户、岗位、权限、预算、审批、任务最终状态和审计。新增 app/runtime/ 只负责统一运行时契约、策略门禁、事件转译和运行状态，不直接连接数据库、GEO、生产账号或外部 Harness 的内部数据库。外部运行时通过独立进程/HTTP 或 App Server 边界接入，任何工具动作在服务端策略中心重新判定。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、pytest；开发期内存存储；外部运行时使用受限 HTTP/stdio 适配器；生产持久化遵循现有 PostgreSQL/Redis/Celery 边界。

---

## 现状与文件边界

已存在的控制平面代码位于 app/domain.py、app/main.py、app/agent_services.py，测试位于 tests/。本计划只新增 app/runtime/、对应测试、POC 配置和文档，并对 app/main.py 增加最小路由接线；不复制 DeerFlow、Codex、Hermes 或 DeepSeek 源码，不改动 GEO 仓库，不改变现有任务/知识库接口语义。

外部运行时只能收到脱敏的 RuntimeContext 和工作台签发的短期运行令牌。运行时返回的 thread/session/checkpoint 仅作为实现字段，不能覆盖工作台任务状态、审批结论或权限判断。

## Task 1：定义统一运行时契约

**Files**
- Create: app/runtime/__init__.py
- Create: app/runtime/contracts.py
- Create: tests/test_runtime_contracts.py

- [ ] 写失败测试：RuntimeContext 必须有租户、任务、设备、知识范围、文件范围、预算、策略版本和过期时间；AgentPlan 对 write、publish、delete、permission 等动作自动标记需审批；RuntimeEvent 支持 cursor 和敏感字段脱敏；AgentRuntimeAdapter 暴露十个生命周期方法。
- [ ] 运行 python -m pytest tests/test_runtime_contracts.py -q，确认因模块不存在而失败。
- [ ] 实现 RuntimeContext、PlanStep、AgentPlan、RuntimeEvent、RuntimeEventType 和 AgentRuntimeAdapter Protocol。时间必须带时区；is_valid_at 在过期时返回 false；脱敏键覆盖 password、cookie、api_key、secret、token、验证码。
- [ ] 运行 python -m pytest tests/test_runtime_contracts.py tests/test_agent_services.py -q，确认通过。
- [ ] 提交：git add app/runtime tests/test_runtime_contracts.py；git commit -m 'feat: 定义 Agent Runtime 统一契约'。

## Task 2：建立服务端策略门禁和短期运行授权

**Files**
- Create: app/runtime/policy.py
- Create: app/runtime/tokens.py
- Create: tests/test_runtime_policy.py

- [ ] 写失败测试：AI 产品经理模式允许 knowledge.search 和 plan.create，拒绝 file.write、production.workflow.update、external.publish；FDE 模式只允许受限目录下的 file.read 和白名单检查；过期令牌、目录越界、预算超额、策略版本不匹配必须拒绝；高风险动作产生审批请求。
- [ ] 运行 python -m pytest tests/test_runtime_policy.py -q，确认缺少 RuntimePolicy、ShortLivedGrant、PolicyDenied、ApprovalRequired。
- [ ] 实现 RuntimePolicy.check(context, action, path=None, cost_cents=0)，返回 allowed、approval_required、reason、policy_version；ShortLivedGrant.issue/verify 绑定运行号、任务号、设备号和过期时间，签名载荷不得保存原始凭据。
- [ ] 运行 python -m pytest tests/test_runtime_policy.py tests/test_control_plane.py tests/test_persistence_contract.py -q，确认跨租户、目录越界、超预算都不能 allowed=True。
- [ ] 提交：git add app/runtime/policy.py app/runtime/tokens.py tests/test_runtime_policy.py；git commit -m 'feat: 增加运行时策略门禁和短期授权'。

## Task 3：实现 Mock Runtime 与可恢复执行状态

**Files**
- Create: app/runtime/mock.py
- Create: app/runtime/state.py
- Create: tests/test_mock_runtime.py

- [ ] 写失败生命周期测试：start_run 产生 plan.created；写动作先产生 approval.requested；pause 保存 checkpoint；resume 不重复已完成工具；cancel 产生终止事件；cursor 回放不重复事件；request_approval 只能关联当前运行；失败最多有限重试。
- [ ] 运行 python -m pytest tests/test_mock_runtime.py -q，确认实现不存在。
- [ ] 实现 RuntimeStateStore 保存上下文、计划、事件序列、步骤状态、checkpoint、审批状态和用量。MockRuntime 只执行 read/search 无副作用步骤，写、发布、删除、权限和生产动作永远停在审批事件；以 run_id 与 step_id 去重。
- [ ] 运行 python -m pytest tests/test_mock_runtime.py tests -q，确认全套测试通过。
- [ ] 提交：git add app/runtime/mock.py app/runtime/state.py tests/test_mock_runtime.py；git commit -m 'feat: 增加可暂停恢复的 Mock Runtime'。

## Task 4：将 Runtime 接入 FastAPI 控制平面

**Files**
- Create: app/runtime/registry.py
- Create: app/runtime/service.py
- Create: tests/test_runtime_api.py
- Modify: app/main.py
- Modify: docs/api-contract.md

- [ ] 写失败 API 测试：POST /api/v1/tasks/{task_id}/runs 创建运行并返回 run_id、runtime_key、策略版本和状态；GET /api/v1/runs/{run_id}/events 支持 cursor；pause、resume、cancel 做权限检查；高风险动作返回 202 和审批号；跨租户运行号统一 404。
- [ ] 运行 python -m pytest tests/test_runtime_api.py -q，确认路由和注册表不存在。
- [ ] 实现 RuntimeRegistry 和 RuntimeService。开发默认只注册 mock；创建运行时从现有任务重建 RuntimeContext，执行策略检查，再调用适配器；客户端不能覆盖角色、预算、知识范围或文件范围。
- [ ] 运行 python -m pytest tests/test_runtime_api.py tests -q，确认 OpenAPI 出现 /api/v1/runs 且不泄露内部 session、凭据或原始事件。
- [ ] 更新 docs/api-contract.md，说明运行时不是权限事实源、计划阶段不执行副作用动作、所有工具动作回到策略中心。
- [ ] 提交：git add app/main.py app/runtime/registry.py app/runtime/service.py tests/test_runtime_api.py docs/api-contract.md；git commit -m 'feat: 接入 Agent Runtime 控制平面接口'。

## Task 5：外部 Harness 隔离适配器

**Files**
- Create: app/runtime/adapters/__init__.py
- Create: app/runtime/adapters/deerflow.py
- Create: app/runtime/adapters/codex_worker.py
- Create: app/runtime/adapters/hermes.py
- Create: tests/test_runtime_adapters.py
- Create: docs/superpowers/poc-runtime-config.example.yaml

- [ ] 用本地 fake transport 写失败测试：DeerFlow 只接收研究/内容长任务并携带租户、任务、岗位、预算、过期时间和策略版本；Codex Worker 只接收 FDE 和受限文件范围；Hermes 只接收成长/记忆提案且始终返回 pending_review；未知事件转换为 run.failed；超时不伪造成功；请求体脱敏。
- [ ] 运行 python -m pytest tests/test_runtime_adapters.py -q，确认适配器和 transport 不存在。
- [ ] 实现注入式 RuntimeTransport，默认使用受控 HTTP/stdio；禁止导入第三方 Harness 内部数据库模块。保存远端 run id 到工作台 run id 映射，统一事件类型，健康检查返回版本、能力和沙箱状态。配置只含地址、固定版本、超时和能力白名单，不含密钥。
- [ ] 运行 python -m pytest tests/test_runtime_adapters.py -q；再用 Python AST 检查 app/runtime 下的导入，确认没有 PostgreSQL、Redis、GEO 或浏览器会话直连。
- [ ] 提交：git add app/runtime/adapters tests/test_runtime_adapters.py docs/superpowers/poc-runtime-config.example.yaml；git commit -m 'feat: 增加隔离的外部 Harness 适配器'。

## Task 6：运行指标、失败回放和安全评测夹具

**Files**
- Create: app/runtime/metrics.py
- Create: app/runtime/evaluation.py
- Create: tests/test_runtime_evaluation.py
- Create: docs/superpowers/runtime-evaluation-matrix.md

- [ ] 写失败评测：任务完成率、工具成功率、知识库命中率、首字节/单步/整任务 P95、越权检测、Prompt 注入检测、数据泄露检测、版本前后质量对比和失败案例回放；夹具包含跨租户、越界文件、恶意文档指令、敏感日志、断点重连和重复点击。
- [ ] 运行 python -m pytest tests/test_runtime_evaluation.py -q，确认指标收集器和评测器不存在。
- [ ] 实现 RuntimeMetrics 按运行号聚合，禁止保存原始 prompt、Cookie、Token 或客户隐私；EvaluationRunner 输出 JSON/Markdown 报告并标记 pass/fail/blocked；失败回放只重放事件和工具输入摘要，不重新执行外部副作用。
- [ ] 运行 python -m pytest tests/test_runtime_evaluation.py -q，确认敏感字符串不出现在报告和日志。
- [ ] 提交：git add app/runtime/metrics.py app/runtime/evaluation.py tests/test_runtime_evaluation.py docs/superpowers/runtime-evaluation-matrix.md；git commit -m 'test: 建立 Agent Runtime 评测与失败回放'。

## Task 7：Staging 验收、许可证和退出门禁

**Files**
- Create: docs/superpowers/poc-staging-runbook.md
- Create: docs/superpowers/poc-license-checklist.md
- Modify: docs/evoflow-research.md
- Modify: README.md（只追加短状态段，不覆盖用户现有内容）

- [ ] 写 staging runbook：本地 Mock、DeerFlow staging、Codex Worker staging、Hermes 隔离验证的前置条件、脱敏数据、网络白名单、密钥注入、设备绑定、回滚、人工接管和真实账号验收；未完成 staging 不得宣称生产可用。
- [ ] 写许可证清单：源码许可证、第三方依赖、商标、容器镜像、模型权利、版本锁定、SBOM、漏洞扫描和退出方案。EvoFlow 继续标记为不可作为商业底座；DeepSeek Harness 仅实验；OpenClaw 需完成依赖和许可证声明审查。
- [ ] 运行 python -m pytest tests -q 和 git diff --check，确认全套测试通过且无空白错误。
- [ ] 提交文档：git add docs/superpowers/poc-staging-runbook.md docs/superpowers/poc-license-checklist.md docs/evoflow-research.md README.md；git commit -m 'docs: 增加 Harness POC 交付与许可证门禁'。

## 验收顺序

1. Task 1-3 完成后，只能声明 Mock Runtime 可暂停、恢复和回放。
2. Task 4 完成后，才可声明工作台 API 能管理运行生命周期。
3. Task 5 完成后，才可在脱敏 staging 中比较 DeerFlow、Codex Worker 和 Hermes；不自动进入生产。
4. Task 6-7 完成后，输出决策表：保留哪个 Runtime、哪些能力自建、版本和升级策略、许可证结果、退出方案。

## 自检清单

- [ ] AgentRuntimeAdapter 十个方法都有任务覆盖。
- [ ] AI 产品经理模式和 FDE 模式有不同的动作、知识和文件策略。
- [ ] 计划阶段不会执行写入、发布、删除、权限或生产工作流动作。
- [ ] Harness 不连接工作台数据库、Redis、GEO 或生产账号。
- [ ] 暂停、恢复、取消、重试、幂等和回放都有自动化测试。
- [ ] 事件、日志、报告和授权载荷不会出现密码、Cookie、验证码、Token 或原始 API Key。
- [ ] Hermes 成长结果只能进入审核提案；未经批准不能修改生产提示词、技能、记忆或工作流。
- [ ] POC 结束前不把任何外部 Harness 宣称为生产能力。

计划保存路径：docs/superpowers/plans/2026-09-06-agent-runtime-poc.md。执行时按任务逐项提交，任何第三方源码保持仓库外独立部署。
