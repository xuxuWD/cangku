# P3 记忆层（记忆 / 画像） 设计

> **性质**：**阶段规格（唯一真源）**。本文定义「P3 记忆层」做什么、怎么做、怎么验收。
> **上位真源**：[`2026-09-12-conversational-agent-platform-design.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md) §14.1 P3、§4 D12/D13、§15 已知风险；[`moat-boundaries.md`](file:///d:/徐徐AI学习/公司工作台/docs/moat-boundaries.md) §2（M2 沉淀层 = 「越用越强」唯一载体）；[`capability-ownership-map.md`](file:///d:/徐徐AI学习/公司工作台/docs/capability-ownership-map.md) #18（记忆层 = A 自研 + pgvector）。
> **依据**：[`iteration-research-2026-09-15.md`](file:///d:/徐徐AI学习/公司工作台/docs/iteration-research-2026-09-15.md) §6（资产中心四件套落地判断）、本次 embedding 选型调研（2026-09-15）。
> **日期**：2026-09-15
> **状态**：**已实现（2026-09-15）**——迁移 029、`app/memory/`、路由、审计扩键、env 模板、api-contract 均已落地；全量回归 **1775 passed / 33 skipped**（新增 14 个记忆层用例）。实现与本期规格口径一致；既有已交付组件未改动（除 `audit/models.py` 扩 4 动作码、`admin-web` 审计标签同步、`settings/env` 加配置外）。
> **前置**：P1 已交付（对话层与数字员工配置，`023`）；P2a 段一治理收口已交付；P2a 段二（dsh 接入）为**并行而非前置**——本层只消费既有的 `workbench_conversation_messages`，不依赖真实 agent loop。

---

## 1. 范围

### 1.1 做什么（四项）

| # | 事项 | 一句话 |
| --- | --- | --- |
| A | **记忆存储与画像模型** | 三类记忆（身份类 / 规则类 / 事实类）各自独立表 + 公共档案表；租户隔离写进约束 |
| B | **向量检索** | pgvector 列 + 索引（维度 1024）；稠密检索 + 关联召回路由（检索时解析画像，禁止客户端自选 scope） |
| C | **本地 Embedding 服务适配器** | 独立进程 HTTP 边界接入 Qwen3-Embedding-0.6B（Apache-2.0），复用 `HttpRuntimeTransport` 模式 |
| D | **写入采纳链** | 会话消息 →（异步）→ 候选记忆 → 人工确认 / 自动采纳（短期类）→ 落库 + 审计；成本熔断 |

### 1.2 不做什么（明确排除）

1. **不升级 embedding 模型档位**：维度固定 1024，模型固定 0.6B（自托管）；不在此规格内切换 4B/8B（未来经 MRL 同维度截断，pgvector 列**无需重建**）。
2. **不做技能层 / 自进化**（P4 / P6）：本层只输出「可检索的记忆」，不产出技能包、不生成成长提案。
3. **不做跨租户记忆共享**：一切记忆按租户隔离；无「组织级全局记忆」概念。
4. **不做 LLM 自动改写人格**：规则类记忆写入**强制人工在环**（§2.4），生成者 ≠ 评审者硬约束先行（不引入 LLM 提取器，规则类由人写；事实类本期手写 + 人工采纳）。
5. **不做向量清洗 / 全量重建工具**：换模型维度时由运维按迁移流程重建，本期不做在线重建 GUI。
6. **不接任何闭源 API 向量服务**（OpenAI / 火山 / 智谱）作为生产唯一源：数据出域与私有化方向冲突。

### 1.3 影响什么（改动面）

| 层 | 影响 |
| --- | --- |
| 数据库 | 一个新迁移 `029_memory_layer.sql`：档案表 + 三类记忆表 + audit 表 + pgvector 列/索引 |
| 后端 | 新模块 `app/memory/`（模型 / 仓储 / 服务 / embedding 适配器 / 幂等）；`app/main.py` 增路由；`app/audit/models.py` 扩动作与明细键 |
| 配置 | `.env.example` / `.env.staging.example` 增 embedding 服务地址与超时配置 |
| 契约文档 | `docs/api-contract.md` 新增「记忆与画像（P3）」章节 |
| 前端 | 本期 **不改前端**（reader 页为可选，见 §2.6）——记忆接口先纯 API，前端在 `admin-web` 后续迭代接入 |

---

## 2. 设计

### 2.1 事项 A：记忆存储与画像模型

**埋点决策（用户 2026-09-15 拍板）**：embedding 模型 = **Qwen3-Embedding-0.6B**（Apache-2.0，自托管本地 HTTP 服务，数据不出内网），**维度固定 1024**。这一决策写入本规格为真源；`memory_policy` 里的 embedding 档位配置以本规格为准。

**三类记忆互不合并**（调研 §6.1 坑 1 的规避）：

| 类 | 内容 | 检索方式 | 写入方式 | 可累积 / 可 supersede |
| --- | --- | --- | --- | --- |
| **身份类** | KV 画像（岗位偏好、语言、风格默认值…） | **不进向量检索，每轮常驻会话上下文** | 人工（`super_admin` / 本人） | 同键覆盖 |
| **规则类** | 整段文本准则（判断逻辑、反例、边界） | 精确 + 语义辅助 | **强制人工在环** + 版本快照可回滚 | supersede（软删旧条目） |
| **事实类** | 短句 + 向量（发生过的可检索事实） | **向量检索（pgvector）** | 人工采纳（候选 → 采纳） | 可累积 / 可 supersede |

**档案表（每租户内、归属于「操作者或数字员工」）**：`memory_profile` 一处记录上下文引用（当前命名空间、有效记忆条目计数），三类记忆各自独立表。**命名空间（scope）为域内枚举（§2.3）**，由服务端从解析规则得出，客户端**不得**直接指定。

### 2.2 向量列与索引

`migrations/029_memory_layer.sql`（节选，正式写法以本规格 + 迁移文件为准）：

```sql
-- 前置：001 已 CREATE EXTENSION vector（0.8.6 在容器回归已验证）
CREATE TABLE IF NOT EXISTS workbench_memory_facts (
    tenant_id      TEXT NOT NULL,
    memory_id      TEXT NOT NULL,
    owner_kind     TEXT NOT NULL CHECK (owner_kind IN ('user','agent')),
    owner_id       TEXT NOT NULL,
    scope          TEXT NOT NULL,               -- 域内枚举，服务端解析，禁止客户端直传
    content        TEXT NOT NULL,
    embedding      VECTOR(1024),                -- 维度一锤定音（D12 一次性建列）
    status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded')),
    superseded_by  TEXT,
    created_by     TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, memory_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_facts_hnsw
    ON workbench_memory_facts USING hnsw (embedding vector_cosine_ops);
```

- **维度固定 1024**：写死在迁移 `VECTOR(1024)`，并登记进 `docs/api-contract.md` 与 `.env.staging.example` 的校验清单。
- **软删口径**：事实类/规则类「作废」用 `status='superseded' + superseded_by`（宪法：重要数据软删除 `deleted_at`），**不物理删除**（`deleted_at` 与 `superseded` 二选一，本规采用 supersede 链，与调研 §6.2 一致）。
- **owner_kind 校验**：归属校验在仓储 + 接口各拦一次；`owner_id` 与当前身份一致，否则按「未找到」处理（沿用对话层 `ensure_can_view` 口径）。

### 2.3 命名空间（scope）解析

- 域内枚举 `MemoryScope`：`user` / `role` / `project` / `organization`（**沿用既有** `app/agent_services.py` 的 `MemoryScope` 枚举 —— 已有但未接线）。
- **解析规则（服务端）**：由当前身份（tenant + role + 可选的 task/project 上下文）推导作用域；**客户端传入的 scope 一律忽略并重算或拒绝**（宪法信息安全防线）。
- `organization` 级记忆本期**不开放写入**（只有 `user` / `role` 可写；`role` 级仅 `super_admin`/相应汇聚角色可写）。

### 2.4 事项 D：写入采纳链（写路径）

```
对话消息（workbench_conversation_messages，append-only 不变）
   └─ 短链触发写：由服务端在会话消息落库后调用记忆服务（幂等 + 熔断）
        ├─ 候选事实类：人工采纳（schema: {text, memory_id?, scope}）→ 采纳 → 落库 + 审计
        ├─ 候选规则类：人工书写 → 服务端二次校验（Prompt 防护复用 D11 的白名单/长度）→ 落库 + 版本快照
        └─ 身份类：人工覆写同键 → 直接更新（记录审计）
```

- **人工在环是硬约束**：LLM 不自评也不自动改写人格；候选身份类/规则类必须人工确认后才落库（调研 §6.2 + 立项 §2.2 实证「LLM 自评 46.4%」）。
- **幂等**：写入带 `idempotency_key`（参考任务创建幂等，`usage:{task_id}:{run_id}` 同款思路），重复提交不重复落库、不重复审计。

### 2.5 事项 C：Embedding 适配器

```
app/memory/embedding.py
  class EmbeddingAdapter:
      def embed(self, text) -> list[float]      # POST {base}/v1/embeddings
      def health(self) -> dict
```
- 独立进程 HTTP 服务（Qwen3-Embedding-0.6B 或同协议实现），**复用 `common.HttpRuntimeTransport` 的传输模式**，端口/地址走 `WORKBENCH_EMBEDDING_BASE_URL` 配置（外置，不进代码）。
- **超时 + 上限**：`WORKBENCH_EMBEDDING_TIMEOUT_SECONDS`（默认 10s）、单文本最大长度（默认 8K token，超出走截断，截断口径与 0.6B 32K 上下文配合留 `token` 数登记在契约）；embedding 失败**默认拒绝写入**（fail-closed，不静默降级为「无向量」入库）。
- **证书/密钥**：白名单 IP 或内网 VPC；无长寿命凭据进镜像（遵循既有容器化红线）。

### 2.6 事项 B：检索（读路径）

```
GET /api/v1/memory/search?q=…&scope=…
   → 服务端解析 scope（忽略客户端值）
   → EmbeddingAdapter.embed(q)
   → 「画像 Constraint 过滤 + 向量 KNN」联合查询（NamedTuple/参数化）
   → 返回 {items: [{memory_id, content, score, scope, created_at}]}
```
- **范围预过滤（pre-filter）**：与知识检索同口径——把租户/scope/owner 过滤写进 SQL 谓词而非「召回后裁剪」（信息不出库前不得让 LLM 读，调研 §6.4）。
- **画像常驻路径**：身份类记忆在会话上下文的注入走「读取画像 → 拼上下文」服务端渲染，**不走向量检索**（调研 §6.1「身份类不进检索、必须每轮常驻」）。

### 2.7 权限与审计

- 写：本人「自己的记忆」或 `super_admin`；规则类写仅 `super_admin`（或经专属灰度）。
- 读：本人自己的；`ceo`/`super_admin` 可读本租户内他人记忆（沿用对话层 `VIEW_ANY_ROLES` 口径 —— 语义一致：治理者可见）。
- 审计码：`memory.fact.created` / `memory.fact.superseded` / `memory.rule.created` / `memory.rule.superseded` / `memory.profile.updated`；明细键进 `ALLOWED_DETAIL_KEYS` 白名单（[audit/models.py](file:///d:/徐徐AI学习/公司工作台/app/audit/models.py) 事实 15）。
- 敏感信息：返回不含 embedding 向量本身，不返回内部路径、不返回 prompt；`content` 属业务数据按既有审计脱敏口径。

### 2.8 配置项（外置）

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `WORKBENCH_EMBEDDING_BASE_URL` | 必填（无默认，缺则拒绝启动，符合 fail-closed） | 本地 embedding 服务地址 |
| `WORKBENCH_EMBEDDING_TIMEOUT_SECONDS` | 10 | 单次调用超时（宪法：第三方调用设超时） |
| `WORKBENCH_EMBEDDING_MAX_TOKENS` | 8192 | 单文本上限 |
| `WORKBENCH_MEMORY_DAILY_BUDGET_CENTS` | 0（= 走员工 `daily_budget_cents`） | 记忆写入成本配额（三级熔断之一） |

### 2.9 已知限制（如实登记）

1. **0.6B 为 CPU 可跑档**（约 1.5GB fp16），本地 P3 起步无 GPU 可用；质量上限受 0.6B 限制，4B/8B 升级属未来（dim 同 1024 不重建列）。
2. **版本快照粒度**：规则类只做「整条 supersede 链」，不做子段落级 diff（本期不做 diff 工具）。
3. **「每日预算」接线**：本期仅在 `create` path 检查且只查 `daily_budget_cents` 累计（追加到 usage ledger 的口径与「用量账本」一致，整数分）；「配额强制」仍**不属本期**（沿用 `capability-ownership-map.md` #27 口径）。

---

## 3. 验收

### 3.1 正常流程（查库验证）

1. `POST /api/v1/memory/facts` 写入事实类 → 查 `workbench_memory_facts` 存在一条 `status='active'`、tenant/owner 正确、embedding 非空且长度 = 1024。
2. 写入同内容 + 同 `idempotency_key` 再提交 → 表内仍 1 条；审计仅 1 条（幂等成立，查库证明）。
3. `POST /api/v1/memory/rules`（`super_admin`）写入规则类 → 落库 + 生成 supersede 链：再次写入同 `rule_key` → 旧条 `status='superseded'` + `superseded_by` 指向新条，新条 active。
4. `GET /api/v1/memory/search?q=…` → 返回相关命中（向量维度 1024，scope 由服务端解析，命中 `order by score desc`）。

### 3.2 临界 / 异常与非法输入

| 用例 | 期望 |
| --- | --- |
| 未登录 / 过期 Token 调任意记忆接口 | 401 |
| 普通员工调 `owner_kind='user', owner_id=他人` 的读/写/删 | 404（不暴露存在性） |
| 普通员工写 `scope=organization` | 403 或 422（服务端拒绝客户端 scope） |
| 员工直传 `scope` 与解析结果不符 | 拒绝（忽略客户端值） |
| embedding 服务不可达 | 写入接口 502/503（fail-closed，**不得**静默降级入库） |
| 内容超 `MAX_MEMORY_LENGTH` / 非法字符 | 422（服务端二次校验） |
| 重复提交同 idempotency_key 但内容不同 | 409 或幂等键冲突（再断言不重复落库） |
| 传 SQL 注入串 / 超长向量输入 | 参数化查询，拒绝 |

### 3.3 反假测试

- 故意把 embedding 维度改为 1025 → 「校验维度 == 1024」用例必须变红（防写错维度）。
- 故意把幂等键逻辑去掉 → 重跑幂等用例必须变红。
- 故意伪装 `scope` 穿透 → 服务端忽略客户端 scope 的用例必须变红。

### 3.4 一键回归

新增代码后跑 `pytest` 全量（含新 `tests/test_memory_*.py`），红则先修再继续；`docs/api-contract.md` 同步预览。

### 3.5 真实 PostgreSQL 回归（2026-09-15，本机一次性容器）

> **环境**：Docker `pgvector/pgvector:pg16`，端口 55434，容器 `workbench-pg-029`，**跑完即删**。
> **这不是 staging**：无独立主机 / TLS / 独立密钥 / 回滚演练，仅用于消除「PG 仓储只用假连接断言」这一缺口（与 023 的 §16 同口径）。

**① 从零应用迁移**：29 条（`001_initial` → `029_memory_layer`），含三条新记忆表与 `VECTOR(1024)` HNSW 索引；`vector` 扩展由 001 装好。

**② 真库用例 `tests/test_memory_postgres.py`：8 条全绿**（`WORKBENCH_TEST_DATABASE_URL` 指向该容器）：

| # | 用例 | 结果 |
| --- | --- | --- |
| 1 | `embedding` 列存在且 `udt_name='vector'` | ✅ |
| 2 | 事实写入读回 `embedding` 长度 == 1024（经 `_parse_embedding` 解析后断言） | ✅ |
| 3 | 事实幂等：同 idempotency_key 重放返回既有记录，表内仅 1 行 | ✅ |
| 4 | 向量检索 `<=> %s::vector` 余弦排序、query 精确命中排第一 | ✅ |
| 5 | 检索可见性：普通员工搜不到他人事实；ceo 可搜 | ✅ |
| 6 | 规则 supersede 链：旧版 `superseded` + `superseded_by` 指向新版，active 仅 1 条 | ✅ |
| 7 | 画像 UPSERT：同键覆盖，表内仅 1 行 | ✅ |
| 8 | `list_all_for_tenant` / `delete_all_for_tenant`（N2 生命周期前置） | ✅ |

**③ 真库暴露并修复的三个实现缺陷（2026-09-15）**：

| # | 缺陷 | 修复 |
| --- | --- | --- |
| F1 | `workbench_memory_rules` 表**缺 `version` 列**（store 已引用），真库 `create_rule` 报 `UndefinedColumn` | `029` 补 `version INTEGER NOT NULL DEFAULT 1`；`_hydrate_rule_with_version` 下标改为 `row[:11]`（11 列 + version 在索引 11） |
| F2 | `search_facts` SQL 参数顺序错：`%s::vector` 在 SELECT 子句最先出现但参数把 tenant_id 放在首位，真库报 `invalid input syntax for type vector: "test-memory-pg"` | psycopg 按占位符出现顺序绑定——把 `query_text` 移到参数列表**第一个**（psycopg 规则，注释已写明） |
| F3 | psycopg 未注册 pgvector 类型时读回 `embedding` 是**字符串**，直接 `len()` 会得到字符数（8962）而非 1024 | 测试经 `_parse_embedding()` 解析后再断言维度（store 内部 hydrate 已正确解析） |

**④ 回归确认**：修复后全量 `pytest` **1775 passed / 41 skipped**（41 = 默认 skip 的真库 8 条 + 其它条件 skip 33 条）；`tests/test_memory_postgres.py` 已纳入 CI `postgres` job（与三个既有真库模块并列，`skipped == 0` 门禁同口径）。

**⑤ CI 实跑证据（2026-09-15 已回填）**：push `670190d` 触发 GitHub Actions **run `34946907594`**，6/6 job **conclusion=success**——后端（pytest+compileall）、三端前端构建、**后端真库（Postgres service + `*_postgres.py`）**、沙箱加固与逃逸回归（真容器）。其中「后端真库」job 因 `skipped==0` 门禁（失败即红）且结论 success ⇒ `tests/test_memory_postgres.py` 的 8 条真库用例全部实跑且无一 skip；沙箱 job 同口径通过 ⇒ 容器加固回归未回归。**此前「CI 真库 job 未实跑」一项自此销账。**
> **代理注记（供后续 push）**：本机 git 全局代理 `http://127.0.0.1:7892` 指向未监听端口（代理软件未运行）→ push 用 `git -c http.proxy= -c https.proxy= push`（命令行临时覆盖，**不改全局配置**；GitHub 直连可达）。

---

## 4. 未决项 / 不在本期

| # | 项 | 状态 |
| --- | --- | --- |
| N1 | 事实类「自动抽取」候选链路（LLM 提取器） | **砍掉**：本期全部人工采纳；自动抽取留 P4/P6（评测集与自进化接入时再议） |
| N2 | 记忆「租户导出 / 删除」`lifecycle` 接线 | ✅ **已接线（2026-09-15）**：`CommercialLifecycleService` 新增可选 `memory_store`（`MemoryExportStore` 协议），注入后导出载荷 `memories` 类别含实际数据并移出 `unimplemented_categories`，`execute_delete` 物理清场（含跨租户隔离断言，`tests/test_commercial_lifecycle.py` 2 用例）；`app/main.py` 装配时传入与记忆服务**同一仓储实例**。未注入时保持「memories 未实现」现状（既有契约不变） |
| N3 | 前端 reader / 画像管理页 | 本期 API 先行，前端归 admin-web 后续迭代（不在本规格实现范围） |
| N4 | 规则类版本 diff / 回放 | 本期不做 |
| N5 | `MemoryStore`（`agent_services.py` 旧类） | 本规格落地后以工作台领域模型为准；既有未接线类不删（避免改既有已交付），但**不被本层使用** |