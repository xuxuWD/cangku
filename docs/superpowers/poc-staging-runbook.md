# Harness POC Staging Runbook

## 前置条件

- 使用独立 staging 租户、脱敏知识库和测试账号。
- 工作台控制平面先启动，Mock Runtime 测试全绿。
- DeerFlow、Codex Worker、Hermes 各自独立进程、固定版本和最小网络白名单。
- 密钥通过部署环境注入，不写入仓库、配置文件、事件或日志。

## 验收顺序

在接入任何外部服务前，先运行本地冒烟检查：

```bash
python -m app.runtime.staging
```

预期输出为 `status: pass`，并且 mock、deerflow、codex_worker、hermes 以及三项安全检查均为 `pass`。该结果只证明工作台适配边界和脱敏规则正常，不代表外部服务已达到生产可用。

真实 staging 使用 `HttpRuntimeTransport` 注入到对应适配器，Runtime 地址只允许来自受控配置；认证头通过部署环境注入，不写入 YAML、任务载荷、事件或日志。外部服务必须提供 `/runs`、`/runs/{id}/events`、生命周期动作和 `/health`，任何非 2xx、超时、缺少运行号或事件格式错误都视为失败。

1. Mock Runtime：创建、审批、暂停、恢复、取消、回放和幂等。
2. DeerFlow：研究/内容长任务，验证上下文脱敏、事件转换和超时。
3. Codex Worker：仅 FDE 模式，授权目录读取和沙箱检查；目录外访问必须阻断。
4. Hermes：只生成成长/记忆提案，状态必须为 pending_review；不得写生产配置。
5. 在一个新鲜 staging 账号上跑评测矩阵，保存指标、失败回放和人工接管记录。

## 回滚与人工接管

- 任意未知事件、验证码、登录失效、风险提示或未知回执立即暂停。
- 关闭外部 Runtime 注册项即可回退到 Mock/自建执行器，不改工作台任务事实源。
- 失败运行保留事件摘要和策略版本，禁止直接重放外部副作用。

未完成 staging、许可证和安全评测前，不得宣称任何外部 Harness 已达到生产可用。
