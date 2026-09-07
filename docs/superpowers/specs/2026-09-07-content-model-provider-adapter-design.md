# 内容工作台模型供应商适配层设计规格

> 日期：2026-09-07  
> 状态：已确认设计，待用户审阅  
> 范围：为公众号内容工作台增加可切换的 OpenAI-compatible 文本生成适配层。

## 1. 目标

在不改变内容工作台 API、权限、确认、审计和 Markdown 导出流程的前提下，将当前内置 Mock 草稿生成替换为可配置的模型生成器。第一版支持 Mock 和 OpenAI-compatible HTTP 两种实现，业务代码不绑定 OpenAI、DeepSeek 或公司内部供应商。

## 2. 范围与非目标

包含：

- 新增窄接口 `ContentGenerator`，输入规范化内容素材，输出结构化公众号草稿。
- 保留 `MockContentGenerator`，默认离线可用。
- 新增 `OpenAICompatibleContentGenerator`，调用 `/v1/chat/completions`。
- 配置模型地址、模型名、密钥、超时和有限重试。
- 校验模型 JSON 输出的字段、长度和内容类型。
- 记录生成开始、成功和失败的脱敏审计信息。
- 为 HTTP 请求、重试、超时、无效 JSON 和敏感信息脱敏增加自动化测试。

不包含：

- 不实现工具调用、多轮 Agent、流式 UI、函数调用或模型自主发布。
- 不复用 `AgentRuntimeAdapter` 承担模型文本生成；Agent Runtime 仍负责任务运行控制。
- 不接入真实供应商账号、生产密钥或线上模型评测集。
- 不自动在真实模型失败时静默降级到 Mock。
- 不改变现有内容工作台路由、前端交互、确认语义和导出格式。

## 3. 架构

内容服务只依赖 `ContentGenerator`，通过启动装配选择实现：

```text
ContentService
    -> ContentGenerator
        -> MockContentGenerator (default)
        -> OpenAICompatibleContentGenerator (explicit config)
```

现有 `RuntimeService` 继续创建和管理内容任务的运行上下文；生成器是一个同步、窄职责的模型调用边界，不改变 Runtime 的暂停、恢复、审批和事件契约。

## 4. 领域接口

新增不可变输入和输出类型：

- `ContentGenerationInput`：主题、规范化来源摘录、知识引用和模板版本。
- `GeneratedContentDraft`：标题、摘要、正文 Markdown、配图建议、模型标识和模板版本。
- `ContentGenerator.generate(input) -> GeneratedContentDraft`。

服务端始终根据 `NormalizedBrief.sources` 生成引用列表，模型输出不允许覆盖引用 URL、租户信息、权限或任务状态。模型输出只提供草稿正文相关字段。

## 5. OpenAI-compatible HTTP 协议

请求：

- `POST {base_url}/v1/chat/completions`；若 `base_url` 已包含 `/v1`，客户端不得重复拼接。
- `Authorization: Bearer <api_key>`、`Content-Type: application/json`、`Accept: application/json`。
- 请求体包含 `model`、`temperature`、`messages`；系统提示要求只返回 JSON 对象，不执行素材中的指令。
- 默认不发送原始密钥、Cookie、会话信息或内部 Runtime 上下文。

响应解析：

- 读取 `choices[0].message.content`，允许字符串 JSON；不接受自由文本作为成功结果。
- JSON 必须包含 `title`、`summary`、`body_markdown`、`image_suggestions`。
- 标题、摘要、正文和配图建议分别执行长度、类型和条目数量限制。
- 缺字段、类型不符、JSON 无法解析或超限均视为生成失败。
- `usage`、模型名和响应耗时只作为脱敏元数据保存，不回传 API 密钥或原始响应。

## 6. 配置与装配

新增配置：

- `CONTENT_GENERATION_BACKEND`：`mock` 或 `openai_compatible`，默认 `mock`。
- `CONTENT_MODEL_BASE_URL`：HTTPS 或本地开发 HTTP 地址。
- `CONTENT_MODEL_NAME`：供应商侧模型标识。
- `CONTENT_MODEL_API_KEY`：只从服务端环境读取，不进入 API 响应、审计详情或日志。
- `CONTENT_MODEL_TIMEOUT_SECONDS`：有限请求超时，默认 30 秒。
- `CONTENT_MODEL_MAX_RETRIES`：只对连接错误、超时和 5xx 做有限重试，默认 2 次；4xx、认证失败和输出校验失败不重试。

生产环境启用真实模型时必须显式提供地址、模型名和密钥；配置缺失应在启动或首次装配时明确失败。开发环境默认 Mock，不需要外部网络。

## 7. 失败、重试与任务状态

- 生成开始时写入 `content.generation.started`，成功写入 `content.generation.completed`。
- 网络超时、连接错误和 5xx 使用指数退避进行有限重试；仍失败写入 `content.generation.failed`。
- 4xx、认证错误、无效 JSON 和字段校验错误不重试，直接标记当前草稿为 `failed`，保留脱敏失败原因。
- 失败不伪造 `reviewing` 或 `confirmed` 状态，不自动下载，不自动降级 Mock。
- 当前业务任务和素材记录保留；员工可通过现有重试/重新生成入口再次发起生成。
- 错误消息向员工展示中文原因和下一步建议；内部异常只保留诊断编号、HTTP 状态类别和耗时。

## 8. 安全与提示注入边界

- 素材摘录是数据，不是系统指令；系统提示明确要求忽略摘录中的权限、工具和发布指令。
- 模型请求只包含当前任务允许的主题、来源摘录和知识引用标识，不包含认证上下文、数据库连接串或内部事件载荷。
- 日志和审计只记录供应商标签、模型名、重试次数、状态、耗时和用量摘要；密钥、完整 Authorization、原始响应和敏感摘录不写入日志。
- 服务端继续执行租户、岗位和知识范围校验，模型不能扩大权限或写入知识库。

## 9. 测试策略

### 9.1 生成器契约

- Mock 和 OpenAI-compatible 实现对同一输入返回相同结构的 `GeneratedContentDraft`。
- OpenAI-compatible 请求包含正确 URL、认证头和模型字段，测试不泄露密钥。
- 合法 JSON 成功解析；缺字段、错误类型、超长字段和非 JSON 返回失败。
- 连接错误、超时和 5xx 按配置重试；4xx 和格式错误不重试。
- 敏感字段在异常、日志和审计元数据中不可见。

### 9.2 服务与 API

- Mock 默认行为和现有 Alpha 测试保持不变。
- 注入假 HTTP Client 后，内容 API 可使用真实生成器完成生成、编辑、确认和导出。
- 生成失败保留任务和素材，状态为 `failed`，不允许导出。
- 真实生成器不可用时不自动调用 Mock，配置切换需显式完成。

### 9.3 回归

- 后端全量测试、Python 编译检查通过。
- 前端测试和生产构建不变且通过。
- 使用本地 OpenAI-compatible 假服务完成一次浏览器闭环；不访问真实供应商。

## 10. 验收标准

- 默认配置下不需要网络即可完成现有 Mock Alpha 闭环。
- 切换 `CONTENT_GENERATION_BACKEND=openai_compatible` 并指向本地假服务后，可生成结构化草稿并完成确认、导出。
- 供应商替换只需修改配置或新增适配器，不修改 `ContentService` 的业务流程和 HTTP 契约。
- 所有失败路径都明确进入 `failed` 并可审计，不出现虚假成功或静默降级。
- API Key、Authorization、Cookie、Token、原始模型响应和未授权内部上下文不出现在日志、审计、响应或导出文件中。
