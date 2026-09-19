# 第 7 轮「知识库」模块 · 实施方案（**Stage B 写码前需你确认契约**）

> 状态：**方案 v1 · 2026-09-19**。
> **两个配置口径已由你裁决（2026-09-19）**：① **重建本机 WeKnora 实例以真验检索**；② **知识治理总开关在本机取证时打开**。
> **唯一权威不在本文件**：权限口径见 [`permission-matrix.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/permission-matrix.md)、知识分级见
> [`knowledge-acl.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/knowledge-acl.md)、知识治理行为以后端契约 `docs/api-contract.md` 与
> 规格 `docs/superpowers/specs/2026-09-15-knowledge-governance-design.md` 为准。本文件只写"这一轮做什么 / 怎么做 / 怎么验"。

## 1. 目标与范围

**做什么**
1. 「知识文档」治理台（占位页 ⇒ 真实页）：文档列表（状态 / 版本 / 来源 / 复核到期）+ 登记 + 发布 / 归档 / 复核（管理动作）+ 治理指标 + 待复核列表。
2. 「知识检索」入口：WeKnora 就绪后接**真检索**（范围过滤在检索阶段前置，fail-closed）；未就绪则如实呈现「服务未接入」。
3. 契约文件（新增）：`docs/contracts/knowledge-api.md`（**Stage B 写码前先落盘并请你确认**）。

**不做什么（禁止事项）**
- 不做**文档级四级 ACL**（`knowledge-acl.md` 字段未落库，属 Schema 线）。
- 不做**知识范围授权**（已由第 6 轮「权限配置」承载，本模块只**消费**绑定结果）。
- 不做**正文上传 / 解析 / 分块**（正文在 WeKnora 侧；本模块只登记元数据，视图不含正文）。
- **不改后端一行**；不新增接口。
- 不修**检索入口的角色缺口**（见 §5，属后端与权限模型，本轮只登记）。

**影响什么**：`workbench-web/src/features/knowledge/**`、新增 `docs/contracts/knowledge-api.md`、回写本文件与决策日志。

## 2. Stage A：环境（**先做**；已按你的裁决启动）

| 步骤 | 内容 | 验收 |
| --- | --- | --- |
| A1 镜像 | `paradedb/paradedb:v0.22.2-pg17`、`redis:7.0-alpine`、`wechatopenai/weknora-docreader:v0.8.0`、`wechatopenai/weknora-app:v0.8.0`、TEI（`text-embeddings-inference:cpu-1.5`，跑 `BAAI/bge-m3`，1024 维） | 5 个镜像就位 |
| A2 起栈 | 上述 5 容器（**不映射** DB/Redis 到宿主，避开保留端口；app `:8181`、TEI 内网） | 各容器 healthy / 日志无致命错误 |
| A3 建库 | 建 KB 时**必须指定 `embedding_model_id`**（上一轮实测：事后 `PUT /initialization/config/:kb_id` 会因 `llm_model_id` 必填而 400，**不指定则永远 `processing`**） | KB 状态不再是 `processing` |
| A4 索引 | 索引 2 篇文档（A / B），各自可分块 | `chunks ≥ 1`、`parse_status=completed` |
| A5 检索复验 | 复用上一轮的三场景矩阵：① 治理关 ⇒ 返回 N、请求计数 +1；② 治理开 + 白名单空 ⇒ **0 条且不向上游发请求**（fail-closed）；③ 治理开 + 有范围 ⇒ 只返回范围内的分块 | 三场景实测 + 请求计数证据 |
| A6 落盘 | 证据（判据 + 原始记录）落 `docs/`（沿用 `probe-evidence.json` 口径，**不进仓库**的脚手架与日志用完即清） | 结论可追溯 |

**失败回落（fail-closed，必须如实登记）**：若镜像 / 模型在本机网络下**不可行或超时**，则**不阻塞 Stage B**：
检索入口按「未配置 ⇒ `503`」诚实呈现，并把"重建失败的原因与实测证据"写进契约的「未验证」——
**不得把未验证写成已验**，也不得用假结果填充检索块。

## 3. Stage B：模块本体（契约先行 → 你确认 → 写码）

### 3.1 接口清单（**已有路由，实施第一步用真机复测并回写形状**）

| 方法 | 路径 | 用途 | 角色（据 `permission-matrix.md` §3） |
| --- | --- | --- | --- |
| GET | `/api/v1/knowledge/documents` | 文档列表（分页） | 登录（严格本租户） |
| POST | `/api/v1/knowledge/documents` | 登记（无正文） | 任意登录角色（`employee` ✅） |
| POST | `/api/v1/knowledge/documents/{id}/publish` \| `/archive` \| `/review` | 管理动作 | `ceo` / `super_admin` |
| POST | `/api/v1/knowledge/review-scan` | 触发到期扫描 | 管理角色 |
| GET | `/api/v1/knowledge/metrics` | 治理指标 | 管理角色 |
| GET | `/api/v1/knowledge/governance/eligible` | 待复核 / 可检索清单 | 管理角色 |
| POST | `/api/v1/knowledge/search` | 检索（**需 WeKnora 配置**；未配 ⇒ `503`） | **现状仅 `super_admin`**（见 §5 缺口） |

`KnowledgeDocView` 已确认键：`document_id / title / owner_id / status / version / source_key / last_reviewed_at / review_due_at / registered_by / created_at / updated_at`（**无正文**）。

### 3.2 页面与四态
- 列表：状态标签（受控枚举，未知取值**不误标**）、复核到期提示、来源（`source_key`）。空态解释"为什么空"（如"本租户还没有登记任何文档；登记后才可检索"）。
- 登记 / 发布 / 归档 / 复核：**成功只用服务端回读值**；失败就地呈现、**不关抽屉、不假装成功**（沿用第 6 轮口径）。
- 检索块：未配置 ⇒ 「服务未接入」说明（**不是空结果**）；已配置 ⇒ 真检索 + `truncated` 等真实字段。
- 无权限：管理动作对非管理角色**禁用 + 原因**（不静默隐藏）。

### 3.3 取证拓扑（本机）
- 后端以**取证配置**启动：`KNOWLEDGE_GOVERNANCE_ENABLED=true` + `WORKBENCH_WEKNORA_BASE_URL/API_KEY` 指向 A2 的实例（**该配置仅本机取证，不代表生产默认**，必须写进契约）。
- 账号：沿用 **136 号段**（139/138 段被后端测试夹具占用，禁止使用）；取证数据用完即清（审计行按只追加口径保留）。

## 4. 交付物与验收（可检查）
1. `features/knowledge/**` 四件套 + 契约 `knowledge-api.md`（含实测形状、错误码原文、未验证）。
2. **四态齐备**；管理动作对无权限角色禁用 + 原因；检索未配置态与就绪态可区分。
3. **先红后绿** + **≥2 组反假**（改坏 ⇒ 指定用例变红 ⇒ 还原）。
4. **门禁**：`tsc` / `vitest`（现有 232 条不破）/ `build` + 产物 grep 无样例字样。
5. **真机取证**：① 登记 → 查库核对；② 发布 / 归档 / 复核各一次（含状态流转与审计）；③ 指标与待复核列表取真实值；④ **A5 三场景**（若 Stage A 成功）；⑤ 浏览器走查（由收口人统一做）。
6. **清理**：Stage A 的脚手架/日志按清理纪律列出清单；测试库数据残留逐条登记（含"无删除接口"的说明）。

## 5. 已知缺口与风险（预告，实施时不重复发现）

| 事项 | 现状 | 本轮处置 |
| --- | --- | --- |
| **检索入口仅 `super_admin`** | `permission-matrix.md` §7 第 1 行（P0，KB-02 不达标） | **不改后端**；界面按真实角色呈现（员工侧为无权限说明），缺口继续登记 |
| 无知识库**枚举**接口 | 第 6 轮已登记的同类缺口 | 检索块不做"库选择器"；范围由绑定决定 |
| WeKnora 是**外部实例** | 本机自建仅用于取证 | 契约与报告均注明"不代表生产 / 客户侧" |
| 检索侧无法用假数据代替 | — | 未就绪即 `503`，**绝不返回空结果冒充"没查到"** |

**未验证（预告）**：Linux/容器拓扑下的 beat 与并发；真实 LLM 摘要 / 问答链路（本机无 LLM）；生产网络与凭据；逐文档 N+1 性能。

## 8. Stage A 执行记录（2026-09-19 · **已完成并超出原范围**）

**结论**：本机 WeKnora 最小栈立起并跑通到**工作台侧端到端检索**；上一轮记录的 **fail-open 行为在真机复现**（见 §8.3 ①），
⇒「绑定即已过滤」**不能**作为防线，`scoped_search` 的返回后收敛**仍是必需**。

### 8.1 拓扑与版本（脚手架在**仓库外** `D:\徐徐AI学习\_weknora-verify\`）

| 组件 | 镜像 / 版本 | 备注 |
| --- | --- | --- |
| postgres | `paradedb/paradedb:v0.22.2-pg17` | WeKnora 库（服务名 `postgres`，仅内网） |
| redis | `redis:7.0-alpine` | 队列/流（`requirepass`，仅内网） |
| docreader | `wechatopenai/weknora-docreader:v0.8.0` | 解析（gRPC 50051，仅内网） |
| app | `wechatopenai/weknora-app:v0.8.0` | 仅映射宿主 `8181 → 8080` |
| **tee（嵌入）** | `ghcr.io/huggingface/text-embeddings-inference:cpu-1.5` | **读本地已下载的 `BAAI/bge-m3`**，OpenAI 兼容 `/v1/embeddings`（1024 维） |

compose 依据上游 v0.8.0 裁剪（去掉 frontend / sandbox / searxng / minio / odl-hybrid / mcp），上游副本留存 `docker-compose.upstream.yml`。

### 8.2 五个「必须照做」的配置坑（**本机实测，逐条带报错原文**）

1. **注册默认被拒**：`/auth/register` 返回 `401 {"error":"Unauthorized: missing authentication"}` ⇒ 必须显式 `DISABLE_REGISTRATION=false`。
2. **空间 Key 从"建空间"响应取**：`WEKNORA_TENANT_AUTO_CREATE_API_KEY=true` 时，`POST /api/v1/tenants` 的响应含 `data.api_key`（`sk-…`，46 字符）——即工作台适配层使用的 `X-API-Key`。
3. **建库必须带 `embedding_model_id`**（复现上一轮结论）：带 ⇒ `is_processing=false`；不带 ⇒ 永远 `processing`。
4. **SSRF 守卫拦内网**：解析时报 `base URL SSRF check failed: … hostname tee resolves to restricted IP …: private IP address`
   ⇒ 必须 `SSRF_WHITELIST=tee,host.docker.internal`（**app 与 docreader 共用同名变量**）。
5. **TEI 不在容器内下载模型**：镜像内下载报 `relative URL without a base`；大文件下载被 Windows 套接字中断
   （`httpx.ReadError: [WinError 10038]`）⇒ 宿主机 `snapshot_download` 预下（2.16GB）后 `--model-id /model` 挂本地目录。

### 8.3 检索复验（真机、真 HTTP、真 Key）

**上游直连矩阵**（`POST {base}/api/v1/knowledge-search`，`X-API-Key`；`query="线索跟进与合规检查"`）：

| # | 请求 | 实测 | 判定 |
| --- | --- | --- | --- |
| ① | `knowledge_base_ids=[kb]` + `knowledge_ids=[A]` | `200`，**2 条**（B 与 A） | **fail-open 复现**：带 kb 参数时上游静默忽略 `knowledge_ids` ⇒ 下游收敛是必需防线 |
| ② | 只给 `knowledge_ids=[A]` | `200`，**1 条**（A） | 过滤真下推 ✔ |
| ③ | 只给 `knowledge_ids=[不存在]` | `200`，**0 条** | fail-closed ✔ |
| ④ | 只给 `knowledge_ids=[B]` | `200`，1 条（B） | ✔ |
| ⑤ | 缺全部范围参数 | `400` | 上游原文：`At least one knowledge_base_id, knowledge_base_ids, knowledge_ids, or …` |
| ⑥ | 错密钥 | `401` | 上游原文：`Unauthorized: invalid API key` |

**工作台侧端到端**（超出原 Stage A 范围，一并取证）：
`POST /api/v1/knowledge/documents` 登记两篇（`document_id` = WeKnora 侧知识 id）→ `…/publish` ⇒ 各 `200/201`
→ `PUT /api/v1/knowledge-access/roles/evidence-ops` 绑定 KB ⇒ `200`
→ `POST /api/v1/knowledge/search {query, role_key}` ⇒ **`200` + 2 条真实引用**（`citation_id / content / source_title / knowledge_id / score`）。

- **fail-closed 也被真机验证**：登记+发布**之前**同一次检索返回 `200 items=0 reason=empty_whitelist`（**未请求上游**）✔
- 索引事实：两篇 `parse_status=completed`、`chunks=2`、`embeddings=2`（真实 bge-m3 向量落库）。
- 中文经 HTTP/JSON 往返**逐字节正确**（Python 脚本按 UTF-8 hex 比对：`first_content_prefix_utf8_hex` 与期望一致）
  ⇒ 终端里看到的乱码是 PowerShell 5.1 解码显示问题，**非数据问题**。

### 8.4 未验证 / 收口清单（不得读成已验）

- 未测并发、未压测；**未验证 LLM 摘要 / 问答链路**（本机无 LLM）。
- 本机栈**非生产**：单机 Windows + Docker Desktop；凭据为本机自生成。
- **空间 Key 曾在执行终端被打印一次**（脱敏正则漏了 `sk-` 前缀）：属本机非生产实例的自生成 Key，随实例一并清理。
- **清理清单（待你确认后执行）**：5 个容器（`wk-*`）与其命名卷、脚手架目录 `D:\徐徐AI学习\_weknora-verify\`
  （含 `.venv`、`models/bge-m3` 2.16GB、`swagger-doc.json`、`verify_utf8.py`、上游 compose/env 副本）、以及测试库内的取证账号 / 角色 `evidence-ops`（审计行按只追加口径保留）。