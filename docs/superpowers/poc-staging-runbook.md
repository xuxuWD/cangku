# Harness POC Staging Runbook

## 前置条件

- 使用独立 staging 租户、脱敏知识库和测试账号。
- 工作台控制平面先启动，Mock Runtime 测试全绿。
- DeerFlow、Codex Worker、Hermes 各自独立进程、固定版本和最小网络白名单。
- 密钥通过部署环境注入，不写入仓库、配置文件、事件或日志。
- RAGFlow 与 AgentScope 使用独立的 HTTPS 地址、固定版本和最小网络白名单。

## 验收顺序

在接入任何外部服务前，先运行本地冒烟检查：

```bash
python -m app.runtime.staging
```

预期输出为 `status: pass`，并且 mock、deerflow、codex_worker、hermes 以及三项安全检查均为 `pass`。该结果只证明工作台适配边界和脱敏规则正常，不代表外部服务已达到生产可用。

真实 Runtime 接入前运行部署元数据预检：

```bash
python scripts/runtime_staging_preflight.py
```

预检必须为 `pass`，并确认非 development 环境、独立 staging 标识、网络白名单，以及五类 Runtime 均已登记：RAGFlow/AgentScope 用 HTTPS 地址 + 固定版本 + 非空能力白名单 + 认证注入标记；DeerFlow/Codex Worker/Hermes 为本地独立进程，地址允许 `http`、认证可选，但固定版本与非空能力白名单同样必填。上述 Runtime 变量裸名与 `WORKBENCH_` 前缀名均可，两者同时存在时以裸名为准。该脚本不发起网络请求、不读取密钥值，不能替代真实服务验收。

真实 staging 使用 `HttpRuntimeTransport` 注入到对应适配器，Runtime 地址只允许来自受控配置；认证头通过部署环境注入，不写入 YAML、任务载荷、事件或日志。外部服务必须提供 `/runs`、`/runs/{id}/events`、生命周期动作和 `/health`，任何非 2xx、超时、缺少运行号或事件格式错误都视为失败。

1. Mock Runtime：创建、审批、暂停、恢复、取消、回放和幂等。
2. DeerFlow：研究/内容长任务，验证上下文脱敏、事件转换和超时。
3. Codex Worker：仅 FDE 模式，授权目录读取和沙箱检查；目录外访问必须阻断。
4. Hermes：只生成成长/记忆提案，状态必须为 pending_review；不得写生产配置。
5. 在一个新鲜 staging 账号上跑评测矩阵，保存指标、失败回放和人工接管记录。
6. RAGFlow：用两个隔离租户验证知识库白名单、引用字段、空范围拒绝和跨租户结果整批拒绝；保存请求摘要与脱敏响应证据。
7. AgentScope：验证 `/health`、创建运行、事件游标、暂停/恢复/取消、审批、usage 和 replay；注入未知事件、超时和取消场景，确认统一失败、无自动越权和可人工接管。
8. 核对所有证据不包含 Authorization、API Key、Cookie、会话或客户原文。

## 回滚与人工接管

- 任意未知事件、验证码、登录失效、风险提示或未知回执立即暂停。
- 关闭外部 Runtime 注册项即可回退到 Mock/自建执行器，不改工作台任务事实源。
- 失败运行保留事件摘要和策略版本，禁止直接重放外部副作用。

未完成 staging、许可证和安全评测前，不得宣称任何外部 Harness 已达到生产可用。
