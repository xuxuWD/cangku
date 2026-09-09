# 开源企业智能体平台调研

调研日期：2026-09-09

本调研用于技术选型和架构对比，不代表对第三方项目生产可用性、许可证适用性的最终法律或安全审查。GitHub Stars、提交时间和文档内容会变化，正式引入前需要锁定具体版本并重新核验许可证、依赖和漏洞。

## 结论

当前最适合本项目的组合是：

1. 保留本项目的 FastAPI 控制平面，继续作为租户、身份、权限、预算、审批、审计、生命周期和最终任务状态的唯一事实源。
2. 优先评估 `infiniflow/ragflow` 作为独立 RAG/文档解析服务。它是 Apache-2.0，适合通过租户范围适配器接入，不应把其权限模型直接当成本项目的授权事实源。
3. 优先评估 `agentscope-ai/agentscope` 作为 Agent Runtime 或执行器框架。它是 Apache-2.0，具备工具权限、人工确认、工作区/沙箱、RAG 服务和多租户 Agent Service 能力，但仍需由本项目策略中心重新判定每个动作。
4. 将 `dataelement/bisheng` 和 `coze-dev/coze-studio` 作为完整产品形态和工作流交互的对照实现。两者都适合搭建独立 POC，暂不建议直接替换本项目控制平面。

推荐架构：

```text
本项目控制平面
  租户 / 登录 / 权限 / 预算 / 审批 / 审计 / 生命周期
       |
       +-- RAGFlow 适配器：只读检索、文档解析、引用返回
       +-- AgentScope 适配器：运行时、工具调用、人工确认、沙箱
       +-- MCP 网关：工具白名单、租户范围、预算、幂等、审计
       +-- Redis/Celery/Outbox：异步投递、重试、死信、人工重放
```

## 候选矩阵

| 项目 | 定位 | 许可证/限制 | 主要能力 | 对本项目的适配判断 |
|---|---|---|---|---|
| [RAGFlow](https://github.com/infiniflow/ragflow) | RAG 与 Agent 上下文引擎 | Apache-2.0 | 文档解析、RAG、Agent Workflow、MCP、自托管 Docker | 首选 RAG 外部服务；保留本项目租户和权限边界 |
| [AgentScope](https://github.com/agentscope-ai/agentscope) | Python Agent 框架与 Agent Service | Apache-2.0 | 工具管理、MCP、Skills、权限/HITL、沙箱、多租户服务、持久化 | 首选 Runtime 研究对象；接入现有 Runtime 适配层 |
| [BISHENG](https://github.com/dataelement/bisheng) | 企业 LLMOps/应用平台 | Apache-2.0 | 工作流、RAG、Agent、模型管理、评测、RBAC、SSO/LDAP、观测 | 企业能力完整；适合独立 POC，对控制平面有较大重叠 |
| [Coze Studio](https://github.com/coze-dev/coze-studio) | 一体化 Agent/Workflow 可视化平台 | Apache-2.0 | Agent、应用、工作流、知识库、插件、API/SDK、Docker | 适合作为工作流产品参考；公开文档明确提示 Python 节点、SSRF 和横向越权风险 |
| [MaxKB](https://github.com/1Panel-dev/MaxKB) | 中文企业级 Agent 平台 | GPL-3.0 | RAG、Workflow、MCP、Docker | 功能贴近需求，但 GPL 对交付和修改分发有合规影响，暂不作为核心依赖 |
| [Langflow](https://github.com/langflow-ai/langflow) | 可视化 Agent/Workflow 开发平台 | MIT | Flow 编排、MCP Server、模型和向量库连接 | 适合开发和原型，不替代本项目控制平面 |
| [Flowise](https://github.com/FlowiseAI/Flowise) | 可视化 Agent 构建平台 | 核心 Apache-2.0；`enterprise` 目录和部分文件为商业许可证 | AgentFlow、Workflow、自托管 | 可做 POC；必须隔离商业目录，先做许可证清单 |
| [LibreChat](https://github.com/danny-avila/LibreChat) | 多用户 AI Chat 与 Agent 门户 | MIT | MCP、Agents、RAG API、OAuth/LDAP/SAML、RBAC、Docker | 可作交互门户参考或独立前端，不作为任务事实源 |
| [Open WebUI](https://github.com/open-webui/open-webui) | 自托管 AI 对话入口 | Open WebUI License，含品牌限制；历史代码另有许可证 | RBAC、LDAP/SSO/SCIM、MCP、RAG、工具和 Skills | 功能强，但品牌与许可证限制不适合作为白标核心产品 |
| [Dify](https://github.com/langgenius/dify) | LLM 应用、Workflow、RAG 平台 | 修改版 Apache-2.0；多租户 SaaS 需书面授权，前端品牌不可移除 | Workflow、RAG Pipeline、Agent、模型管理、观测、自托管 | 可作外部应用引擎 POC；不纳入多租户核心链路前先完成商业授权核验 |
| [FastGPT](https://github.com/labring/FastGPT) | 知识库与可视化 Workflow 平台 | 修改版 Apache-2.0；类似 FastGPT 的多租户 SaaS 需书面授权，前端品牌不可移除 | RAG、Workflow、双向 MCP、模型接入、自托管 | 中文场景成熟，但许可证限制与本项目商业化方向冲突 |
| [DB-GPT](https://github.com/eosphoros-ai/DB-GPT) | Agentic AI 数据助手 | MIT | SQL/代码分析、Agent、AWEL、RAG、多模型 | 适合数据分析岗位或 SQL Agent 试点，不是通用控制平面 |
| [QAnything](https://github.com/netease-youdao/QAnything) | 企业文档问答/RAG | AGPL-3.0；并需核验模型依赖许可证 | 文档解析、向量检索、重排、Docker 私有部署 | 适合 RAG 对比测试，AGPL 不作为默认商用依赖 |

## 重点判断

### 最值得做 POC 的两个项目

**RAGFlow** 更适合承担“知识层”：文档解析、切分、检索、引用和 RAG 上下文。它不应接管本项目的租户身份、知识库授权和任务审计。适配器应只传入服务端解析出的知识库白名单，并校验返回结果中的租户和知识库范围。

**AgentScope** 更适合承担“运行层”：工具调用循环、MCP、Skills、人工确认、工作区和沙箱。它的权限系统可以作为执行器的第二道防线，但本项目策略中心仍必须在动作执行前重新检查租户、岗位、预算、审批和文件范围。

### 可以参考但暂不直接引入的项目

**BISHENG** 的企业运维功能覆盖得比较完整，尤其是 RBAC、用户组、SSO/LDAP、流量控制、评测和观测，适合用来补齐本项目后续的企业管理清单。由于它同时覆盖控制平面、工作流和 Agent，直接嵌入会引入第二套用户、权限和任务事实源。

**Coze Studio** 的工作流和 Agent 产品体验值得研究，但其官方 README 明确提示公开网络部署要评估账号注册、Python 执行节点、SSRF 和部分 API 横向越权风险。即使使用 Apache-2.0，也必须在隔离网络中进行安全评测。

**Dify** 和 **FastGPT** 的功能与本项目重合度高，但许可证都不是无条件的标准 Apache-2.0：两者都对相似多租户 SaaS 和前端品牌作了额外限制。客户私有部署与多租户商业化边界尚未完成法律核验前，不应把它们作为核心代码来源。

### 不应混淆的三类能力

- 产品平台：Dify、FastGPT、MaxKB、BISHENG、Coze Studio，适合快速搭建应用，但会带来第二套用户、权限、工作流和审计模型。
- 基础编排/运行时：AgentScope、Langflow、Flowise，适合嵌入或作为外部执行器，但仍需要本项目的策略与审计边界。
- 知识或入口组件：RAGFlow、QAnything、LibreChat、Open WebUI，分别偏知识层或交互层，不能单独解决企业任务治理问题。

## 建议的验证顺序

1. 先做 RAGFlow POC：建立一个脱敏知识库，验证租户/岗位知识范围、引用来源、删除和重建索引行为。
2. 再做 AgentScope POC：只开放一个无副作用工具和一个需要人工确认的工具，验证运行状态、超时、取消、重放、沙箱和审计事件。
3. 做 MCP 网关契约：把工具发现、调用、预算、幂等、审批和死信全部纳入本项目 API，不让客户端直接配置任意 MCP Server。
4. 对 BISHENG、Coze Studio、Dify、FastGPT 做独立产品体验评测，不复制其权限或任务数据模型。
5. 完成许可证、依赖漏洞、容器镜像、SSRF、越权、密钥注入和数据外发评估后，才进入 staging。

## 当前不应作出的结论

本调研没有证明任何候选项目已经满足本项目的生产要求，也没有完成真实安装、并发压测、跨租户越权测试、数据删除验证、密钥轮换或供应链扫描。候选项目的 GitHub Stars 只能作为活跃度信号，不能作为安全、性能或商业许可证明。

