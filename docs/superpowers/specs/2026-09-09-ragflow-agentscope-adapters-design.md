# RAGFlow 与 AgentScope 适配器设计

## 背景

项目已有统一 Agent Runtime 契约、外部 HTTP 传输层、Runtime 注册表和策略中心。调研表明 RAGFlow 适合承担知识检索与文档上下文，AgentScope 适合承担 Agent 执行、工具管理、人工确认和沙箱能力。本阶段只建立可测试的适配器边界，不引入第三方 SDK，不将第三方服务作为租户、权限、审计或任务状态事实源。

## 目标

- 增加 `RAGFlowAdapter`，提供租户范围内的只读检索和文档引用读取。
- 增加 `AgentScopeAdapter`，复用现有 Runtime 生命周期契约，承接外部 AgentScope 服务的运行、事件和人工确认。
- 让注册表支持显式配置启用两个适配器，默认仍只有 Mock Runtime。
- 固定请求载荷、响应映射、错误和安全边界，并通过 FakeTransport/HTTP 契约测试验证。
- 同步 API 契约、架构说明和交付门禁，明确真实外部服务仍需 staging 验收。

## 非目标

- 不在本阶段安装或调用 RAGFlow、AgentScope 的 Python SDK。
- 不开放知识库写入、删除、索引重建、Skill 安装、Shell、任意 MCP Server 或生产系统写操作。
- 不让外部服务决定租户、用户、岗位、预算、审批结果或最终任务状态。
- 不把 FakeTransport 测试当作真实 RAGFlow/AgentScope staging 验收。

## 架构

```text
FastAPI 控制平面
  租户 / 身份 / 权限 / 预算 / 审批 / 审计 / 最终状态
        |
        +-- RAGFlowAdapter -- HttpRuntimeTransport -- RAGFlow HTTP 服务
        |       只读检索 / 文档引用
        |
        +-- AgentScopeAdapter -- HttpRuntimeTransport -- AgentScope 服务
                运行 / 事件 / 暂停恢复取消 / 人工确认
```

两个适配器均继承现有 `ExternalAdapter`，复用 endpoint 校验、运行号映射、事件游标、命令接口和健康检查。适配器只负责协议转换，不复制外部服务的数据库或权限模型。

## RAGFlowAdapter 契约

适配器提供一个显式的只读方法：

```python
search(
    *,
    context: RuntimeContext,
    query: str,
    limit: int = 10,
) -> list[KnowledgeCitation]
```

`KnowledgeCitation` 至少包含 `document_id`、`knowledge_base_id`、`title`、`snippet` 和可选 `score`。请求载荷为：

```json
{
  "tenant_id": "tenant-1",
  "knowledge_base_ids": ["kb-1"],
  "query": "设备故障原因",
  "limit": 10
}
```

规则：

- `query` 必须是非空字符串，长度限制为 1 到 2000 个字符。
- `limit` 限制为 1 到 50，超出范围直接抛出 `ValueError`。
- `knowledge_base_ids` 始终来自 `RuntimeContext.knowledge_scope`，客户端不能覆盖。
- 外部结果缺少文档号、知识库号或片段文本时视为协议错误。
- 外部返回的 `tenant_id` 或知识库号不在当前上下文范围时，抛出 `TransportError`，不返回部分结果。
- 适配器不提供写入、删除、索引和任意 URL 访问方法。

外部接口约定为 `POST {endpoint}/knowledge-search`，返回 `{ "items": [...] }`。文档详情读取沿用同一边界，若需要新增时必须先扩展测试和 API 契约。

## AgentScopeAdapter 契约

适配器继承 `ExternalAdapter`，运行入口和生命周期方法保持现有 `AgentRuntimeAdapter` 接口不变。启动时发送现有 `_payload` 结构，并额外固定 `runtime_key: "agentscope"`。`AgentPlan` 中每一步的 `requires_approval` 原样传给外部服务，但外部服务不得把它解释为工作台审批已完成。

运行规则：

- 只接受工作台生成的 `RuntimeContext` 和 `AgentPlan`。
- 不允许通过运行请求覆盖租户、用户、岗位、预算、知识范围、文件范围、策略版本或过期时间。
- `kind` 为 `write`、`external_send`、`publish`、`delete` 或 `permission` 的步骤必须保留审批标记。
- 外部事件只允许映射到现有 `RuntimeEventType`；未知类型统一转为 `run.failed`。
- 事件载荷继续使用现有公开脱敏逻辑，不能返回 Token、Cookie、API Key、密钥或外部会话标识。
- 暂停、恢复、取消和审批请求都通过现有命令边界发送，命令失败直接返回传输错误。

外部服务约定：

- `POST /runs` 创建运行并返回 `run_id` 或 `id`。
- `GET /runs/{id}/events` 返回 `events` 或 `items` 列表。
- `POST /runs/{id}/pause`、`resume`、`cancel`、`approvals`、`replay`、`usage` 复用现有传输接口。
- `GET /health` 返回健康摘要。

## 配置与注册

注册表新增两个受控 key：`ragflow` 和 `agentscope`。配置必须包含：

- `enabled`
- `endpoint`，仅允许 `http://` 或 `https://`
- `capabilities`，不能为空
- `timeout_seconds`
- `version`，要求为非空固定版本字符串，禁止 `latest`、`main` 和 `head`

默认配置不启用任何外部 Runtime。API Key、认证头和 Cookie 不进入 YAML、任务载荷或日志，由部署环境注入到 `HttpRuntimeTransport` 的客户端配置；本阶段不改变现有传输层签名，认证注入作为后续 staging 任务单独实现。

## 错误处理

- HTTP 非 2xx、JSON 无效、缺少运行号或事件格式错误统一抛出 `TransportError`。
- RAGFlow 引用越权、字段缺失和空结果格式错误不得静默吞掉。
- AgentScope 未知事件映射为 `run.failed`，载荷只保留脱敏后的原因和外部类型。
- 适配器不自动切换到 Mock，不自动重试副作用命令；重试由上层 Celery/Outbox 或人工重放策略控制。

## 测试策略

- 增加 RAGFlow 检索成功、空知识范围、输入边界、越权结果和 malformed 响应测试。
- 增加 AgentScope 运行启动、事件映射、未知事件失败、审批标记和生命周期命令测试。
- 增加注册表显式启用两个 Runtime、缺失版本、未固定版本和默认不启用测试。
- 复用 `FakeTransport`，不需要网络或第三方服务；真实服务验收仍按 staging 清单执行。
- 每次提交运行 `python -m pytest -q`、`python -m compileall -q app tests scripts/commercial_g0_preflight.py` 和 `git diff --check`。

## 交付边界

本阶段完成后，只能声明“开发期 RAGFlow/AgentScope 适配器契约和注册表支持已完成”。真实 RAGFlow/AgentScope 部署、密钥注入、跨租户测试、并发压测、沙箱验证、告警和 staging 验收继续保持未完成。

