# 实时流与过程事件（SSE + PG 流帧 + 过程事件） 阶段规格

> **性质**：**阶段规格（唯一真源）· 已评审**。本文定义 P2b「做什么 / 怎么做 / 怎么验收」；**实现按本文 §7 推进**（宪法 2.1；feature-inventory 维护规则②）。
> **上位真源**：[`2026-09-12-conversational-agent-platform-design.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md) §3 目标态、§4 决策 D15/D16/D17、§17.4 / §17.5 / §17.7（Q7–Q10）；[`feature-inventory.md`](file:///d:/徐徐AI学习/公司工作台/docs/feature-inventory.md) §2（P2b 行「实时流 + 过程事件」，前置 = P2a-2 稳定）。
> **依据**：[`evoflow-source-study-and-adaptation-plan.md`](file:///d:/徐徐AI学习/公司工作台/docs/evoflow-source-study-and-adaptation-plan.md) §2.3（九条工程借鉴，本规格 §2.7 逐条裁定）；[`api-contract.md`](file:///d:/徐徐AI学习/公司工作台/docs/api-contract.md)「对话式 AI 员工平台（P1）」「工具执行（P2a 段二）」「Agent Runtime 运行」；[`2026-09-12-dsh-integration-design.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-dsh-integration-design.md)（同步非流式现状的定死口径）。
> **日期**：2026-09-17
> **状态**：**已评审（2026-09-17，用户批准本文件）**；§5 待裁决**按推荐执行**（Q7 = 候选① `messages:stream`；Q8 = 7 天保留 + 双上限熔断 + 6h 悬挂兜底 + 逐租户清理；推送底座 = PG 表 + 短轮询；审批后推进的过程事件本期不做；借鉴第 6/7/8 条不纳入本期）。实现按 §7 实施顺序推进；**未经用户确认不提交、不推送**。
> **前置**：P2a-2 段二-2 / 段二-3 / 段二-4 已交付（真实工具执行 + 九步闸门 + 对话入口路由）；`RuntimeEventType` 十种枚举已在库；append-only 事件表（迁移 `034`）与保留期清理任务已运行。本规格**不依赖**前端改造（P2c 消费本层）。

***

## 0. 现状盘点（2026-09-17 起草时静态核对）

> 体例说明：本阶段的「真库回归记录」在**开工日**按 [`knowledge-governance-design.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-15-knowledge-governance-design.md) §0 同体例补写（迁移从零应用 + 真库用例 + CI 销账）。本节先登记**起草时已核实的实现事实**（静态核对，非运行时取证）——它们是本设计全部「复用」断言的依据。

| #  | 事实（静态核对）                                                                                                                                                                                                  | 证据                                                                                                        |
| -- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| 1  | 过程事件枚举**十种已存在**（`plan.created` / `step.started` / `tool.call` / `tool.result` / `approval.requested` / `approval.decided` / `checkpoint.saved` / `run.paused` / `run.failed` / `run.completed`）⇒ 复用，不另起枚举 | [contracts.py](file:///d:/徐徐AI学习/公司工作台/app/runtime/contracts.py#L17-L27)                                  |
| 2  | append-only 运行事件表已在库（`workbench_runtime_events`，主键 `(run_id, sequence)`）                                                                                                                                  | [034\_runtime\_events.sql](file:///d:/徐徐AI学习/公司工作台/migrations/034_runtime_events.sql#L17-L25)             |
| 3  | 断点读取端点已存在（`cursor` 语义 = 严格大于；返回已脱敏摘要）                                                                                                                                                                     | [main.py](file:///d:/徐徐AI学习/公司工作台/app/main.py#L3117-L3125)、契约 L628                                        |
| 4  | 运行事件保留期清理**已在运行**：默认 30 天，worker 周期任务 `runtime-events-purge`                                                                                                                                              | 034 头注释、契约 L624                                                                                           |
| 5  | 对话消息执行是**同步、非流式**（P2a-2 定死；「过程事件属 P2b」写在契约已知限制里）                                                                                                                                                          | 契约 L688、L749                                                                                              |
| 6  | 全仓 `app/` 与 `admin-web/`、`companion-pwa/` **无 SSE /** **`EventSource`** **/** **`StreamingResponse`**（本层为净新增）                                                                                             | 起草时全仓 grep                                                                                                |
| 7  | 会话/消息表与**复合外键**写法已确立（跨租户引用在数据库层直接拒绝），流帧表沿用同一手法                                                                                                                                                            | [023\_conversational\_agent.sql](file:///d:/徐徐AI学习/公司工作台/migrations/023_conversational_agent.sql#L14-L45) |
| 8  | 脱敏函数 `redact_payload` 已落地且**掩码幂等**（键名词元归一 + 值正文有限模式集）                                                                                                                                                     | [contracts.py](file:///d:/徐徐AI学习/公司工作台/app/runtime/contracts.py#L155-L170)                                |
| 9  | Q9 落点已在 P2a 定死：工具结果只落「摘要 + `args_digest` + `sha256`」，**永不落文件正文**                                                                                                                                          | 契约 L738                                                                                                   |
| 10 | 迁移最大号 = `034`（开工时取仓库实号 `+1`，本文记作 `035`）                                                                                                                                                                   | `migrations/` 目录清单                                                                                        |

***

## 1. 范围

### 1.1 什么是「实时流与过程事件」（边界定义）

在**不改执行语义**的前提下，为「对话触发的一次运行」补上两条能力：

1. **可推流**：运行过程中的内容（消息落定、助手回复、过程事件）以 SSE 帧形式对外可见；**先落库、再推送**（D15），断线后按 `seq` **真增量**续播。
2. **过程可见**：agent 在运行中的**计划 / 步骤 / 工具调用与结果 / 审批 / 检查点 / 终态**作为**可订阅的过程事件**暴露（D16），与审计**分离**（审计 = 谁改了什么；过程事件 = agent 在做什么）。

它**不是**新的执行引擎（执行仍走 `ConversationExecutionService` + 九步闸门 + 容器执行器）；**不是**审计替身（审计不可清空，过程事件按保留期清理）；**不是**前端改造（P2c 消费本层；本层只冻结契约与后端实现）。

### 1.2 做什么（六项）

| # | 事项                 | 一句话                                                                                                                                                                                                                                       |
| - | ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A | **流帧存储（迁移）**       | 两张表：帧明细表 `(tenant_id, conversation_id, run_id, seq, kind, payload, is_terminal)`（append-only）+ 每 run 一行的**状态表**（`last_seq` / `frame_count` / `byte_count` / `is_terminal` / `status` / `expires_at` / `persisted_to_message_id`）；复合外键写进约束 |
| B | **SSE 读取端点**       | `GET /api/v1/conversations/{conversation_id}/stream`：认人（401）、认归属（404）、按 `Last-Event-ID` / `?after_seq=` 续播、心跳保活、终态主动关流                                                                                                                    |
| C | **Q7 裁决落点（写入侧）**   | 新增 `POST /api/v1/conversations/{conversation_id}/messages:stream`（候选①，零破坏）；**只有它**触发帧写入；旧 `POST /messages` 行为**逐字节不变**（含状态码全分支与审计）                                                                                                        |
| D | **断线续播（真增量）**      | 服务端从 `seq+1` 补发；水位列 `persisted_to_message_id` 标记「已落到消息表」；终态后收窄 `expires_at`                                                                                                                                                               |
| E | **过程事件（复用十种枚举）**   | 运行中的 `RuntimeEventType` 十种**原值**即帧的 `kind`；**先落库再推送**；与审计三表分工；帧 payload 写入前过 `redact_payload`                                                                                                                                             |
| F | **脱敏 + 有界（熔断与清理）** | 默认只落摘要不落原文（Q9 沿用）；**帧数 + 字节双上限熔断**（超限置 `unavailable` 并**显式告知**，不静默丢帧）；清理任务**必须带** **`tenant_id`**；悬挂流 6 小时兜底收口                                                                                                                            |

### 1.3 不做什么（明确排除）

1. **不做前端改造**：对话主轴 / 右侧舞台 / 侧栏重组 = P2c；本层只保证契约可消费（P2c 开工时接入）。
2. **不破坏既有契约**：`POST /messages`（`201/202/422/403/409/504` 全分支）、`GET /runs/{run_id}/events`、PWA / 桌面端行为**不变**（Q7 候选①）。
3. **不做 LLM 摘要与上下文预算参数化**：第一版不做 LLM 压缩（evoflow §2.3 第 9 条）；`context_policy` / `context_used_tokens`（第 6 条）与摘要反幻觉前缀（第 7 条）**登记为后续专项**——理由：dsh 自带压缩；无真实长会话数据校准前写死阈值是假精确。
4. **不做用量归因与日汇总**（evoflow §2.3 第 8 条）：登记为后续专项，**须与其上游「日预算熔断」同批设计**（避免造一张没人读的账本）；本层不碰 `workbench_usage_ledger`。
5. **不建「工具调用记录表」**：X5 不变（契约 L740）；工具调用仍进既有 append-only 审计 + 本层过程事件。
6. **不落原文**：文件内容 / 命令 stdout 全文**不进帧表**（Q9 默认结论）；`027` 的加密正文列是唯一受控例外，其解密内容**不得外溢到帧**。
7. **不引入新实时底座**：不引入 Redis Pub/Sub、WebSocket、消息队列——**第一版用「PG 表 + 短轮询」**（单一存储、断线语义天然正确、不新增运维组件）。
8. **不做流历史回放 UI / 不做跨端同步**：帧到期即不可查（与运行事件同口径）；不做会话分享与多端协同。

### 1.4 影响什么（改动面）

| 层      | 影响                                                                                                                                                                   |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 数据库    | 新迁移（实号开工取，记作 `035`）：`workbench_conversation_stream_frames` + `workbench_conversation_stream_state`（幂等 DDL + 回放索引 + 清理索引）                                             |
| 后端     | 新模块 `app/conversation/stream.py`（帧/状态仓储 + 序号分配 + 熔断）与 `app/conversation/stream_writer.py`（写入网关：脱敏 → 熔断 → 落库）；`app/conversation/execution.py` 增加**帧写入钩子**（不改其判定与错误语义） |
| 路由     | 新增 2 条：`GET /api/v1/conversations/{conversation_id}/stream`（SSE）与 `POST /api/v1/conversations/{conversation_id}/messages:stream`；**既有路由不动**                          |
| 契约     | `docs/api-contract.md` 新增「实时流与过程事件（P2b）」章节；**回改**既有「工具执行」节的「已知限制·非流式」表述（指向新章节；不改其余语义）                                                                                |
| 审计     | 新增动作码 **1 个**：`conversation.stream.unavailable`（reason 为受控枚举 `frame_limit` / `byte_limit` / `write_failed` / `stalled`）；明细键按存在性复用，缺则**同步扩白名单并配测试**（未声明键会直接抛错）        |
| Worker | 新增周期任务 `conversation-stream-purge`（beat 间隔可配，默认 3600s；**逐租户**清理，带 `tenant_id`）；同时收口 6 小时未更新的悬挂流                                                                      |
| 既有行为   | `POST /messages` **零变化**（可验证断言：走旧端点后帧表计数为 0）；`GET /runs/{run_id}/events` 零变化；消息表 / 审计 / 运行事件表结构零变化                                                                   |
| 前端     | **本期不动**（`admin-web` / `companion-pwa` 不消费新端点；P2c 接入）                                                                                                                |

***

## 2. 设计

### 2.1 事项 A：流帧两表（迁移 035）

```sql
-- 明细表：append-only 帧序列（不建 updated_at，与消息表/审计表同构）
CREATE TABLE IF NOT EXISTS workbench_conversation_stream_frames (
    tenant_id       TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    seq             INTEGER NOT NULL,            -- 从 1 开始，同一 (conversation, run) 内单调递增且唯一
    kind            TEXT NOT NULL,               -- §2.5 冻结的取值域
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 写入前已过 redact_payload
    is_terminal     BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, conversation_id, run_id, seq),
    FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES workbench_conversations (tenant_id, conversation_id)
);

-- 回放路径：按 (conversation, run, seq) 升序读增量（主键已覆盖，此索引服务「跨 run 列表」场景，按需保留）
CREATE INDEX IF NOT EXISTS idx_wb_stream_frames_replay
    ON workbench_conversation_stream_frames (tenant_id, conversation_id, run_id, seq);

-- 清理路径：按写入时刻扫描（无状态行兜底时用）
CREATE INDEX IF NOT EXISTS idx_wb_stream_frames_created_at
    ON workbench_conversation_stream_frames (created_at);

-- 状态表：每 (conversation, run) 一行（避免对大表频繁 COUNT/SUM）
CREATE TABLE IF NOT EXISTS workbench_conversation_stream_state (
    tenant_id               TEXT NOT NULL,
    conversation_id         TEXT NOT NULL,
    run_id                  TEXT NOT NULL,
    last_seq                INTEGER NOT NULL DEFAULT 0,
    frame_count             INTEGER NOT NULL DEFAULT 0,
    byte_count              BIGINT  NOT NULL DEFAULT 0,
    is_terminal             BOOLEAN NOT NULL DEFAULT false,
    status                  TEXT NOT NULL DEFAULT 'streaming'
        CHECK (status IN ('streaming', 'completed', 'failed', 'unavailable')),
    persisted_to_message_id TEXT,                -- 水位：最后一条已落消息表的助手消息 id（空 = 尚未落）
    expires_at              TIMESTAMPTZ,          -- 终态时置 now() + 保留期；悬挂兜底置位
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, conversation_id, run_id),
    FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES workbench_conversations (tenant_id, conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_wb_stream_state_expires
    ON workbench_conversation_stream_state (expires_at);

-- 悬挂兜底扫描路径：未终态且久未更新
CREATE INDEX IF NOT EXISTS idx_wb_stream_state_stalled
    ON workbench_conversation_stream_state (status, updated_at);
```

**设计要点**（对齐 evoflow §2.3 第 1 / 3 条）：

* **两表拆分**：明细表只追加；状态表只改一行。「还有多少帧 / 是否终态 / 何时过期」查状态表，**不扫明细**。

* **序号分配**：由状态行原子递增（`INSERT ... ON CONFLICT DO UPDATE SET last_seq = last_seq + 1 ... RETURNING last_seq`），与写帧同事务 ⇒ 不会出现重复或跳号。

* **不删数据换 run**：**偏离** evoflow「换 run 清旧帧」——同一会话多 run 各自独立（各自状态行），互不置位；悬挂由 6 小时兜底收口（§2.2）。理由：同步执行下并发 run 虽罕见但真实存在，互踩比悬挂更糟；帧由统一保留期治理，不依赖删除。

* **`seq`** **不被复用**：清理删除整 run 的帧与状态行后，该 run 不再追加（终态或 unavailable），无复用风险。

### 2.2 事项 F：写入网关（顺序 / 熔断 / 兜底）

写入路径（在 `messages:stream` 触发的一次同步执行内，逐事件调用）：

1. **脱敏**：`redact_payload`（同一函数、同一套键名/值模式规则；掩码幂等 ⇒ 不双重掩码）。
2. **组装帧**：`kind`（§2.5）+ `payload` + `is_terminal`（仅终态事件为真）。
3. **同事务落库**：`INSERT` 帧行 + `UPDATE` 状态行（`last_seq` / `frame_count += 1` / `byte_count += len(规范化 JSON)` / `updated_at`）。
4. **熔断判定**（落库前）：`frame_count` 或 `byte_count` 超上限 ⇒ **停止写后续帧**，状态置 `unavailable`，**追加写一帧** **`stream.unavailable`（`is_terminal=true`，payload 只含受控枚举 reason）**，同时写审计 `conversation.stream.unavailable`；**执行继续**（流是视图，权威结果在消息/运行/审计）。
5. **写失败**：帧写入异常 ⇒ 尽力置 `unavailable` + 审计（`write_failed`）；**不得**让流写入失败阻断或改变执行结果。
6. **终态**：收到 `run.completed` / `run.failed` ⇒ 帧 `is_terminal=true`，状态 `status='completed'/'failed'`、`is_terminal=true`、`expires_at = now() + 保留期`。
7. **水位**：助手消息落进消息表后，回填 `persisted_to_message_id`（供客户端判断「结果已可经消息表读取」）。

**配置项（全部带范围校验，缺省安全）**：

| 配置                                        | 默认    | 范围             | 说明                                                                 |
| ----------------------------------------- | ----- | -------------- | ------------------------------------------------------------------ |
| `WORKBENCH_STREAM_RETENTION_DAYS`         | **7** | 1–90           | Q8 答复：比运行事件（30 天）短——流是体感数据，帧量大                                     |
| `WORKBENCH_STREAM_MAX_FRAMES`             | 2000  | 100–20000      | 每 run 帧数上限                                                         |
| `WORKBENCH_STREAM_MAX_BYTES`              | 4 MiB | 256 KiB–64 MiB | 每 run payload 累计字节上限                                               |
| `WORKBENCH_STREAM_MAX_CONNECTION_SECONDS` | 1800  | 60–7200        | SSE 连接最长生命周期，到点关流（客户端自动重连）                                         |
| `WORKBENCH_STREAM_POLL_INTERVAL_MS`       | 500   | 200–5000       | 读端轮询增量间隔                                                           |
| `WORKBENCH_STREAM_STALLED_HOURS`          | 6     | 1–72           | 未终态且 `updated_at` 超此值 ⇒ 置 `unavailable('stalled')` 并设 `expires_at` |
| `WORKBENCH_STREAM_PURGE_INTERVAL_SECONDS` | 3600  | 60–86400       | 清理任务 beat 间隔                                                       |

**悬挂兜底（`stalled`** **收口）**：清理任务每轮先扫「`status='streaming'` 且 `updated_at < now() - STALLED_HOURS`」的状态行 ⇒ 置 `unavailable`（reason `stalled`）+ 设 `expires_at`（**不补写帧**，由读端按状态告知）；再删到期 run 的帧与状态行。

### 2.3 事项 B：SSE 读取端点

`GET /api/v1/conversations/{conversation_id}/stream?run_id=&after_seq=`

* **认证与归属**：`current_user`；岗位同对话入口（`customer_admin` → `403`）；`ensure_can_view` 同口径（本人；`ceo` / `super_admin` 可读本租户他人会话）⇒ 否则 `404`（不泄露存在性）。未认证 `401`。

* **run 解析**：`?run_id=` 显式指定（属于其它会话 / 租户 ⇒ `404`）；缺省 = 该会话**最新 run**（活跃优先，否则最新历史 run）。会话一次都没有 run ⇒ **挂起**（仅心跳），轮询中发现新 run 后自动开始补发。

* **起点解析**：`Last-Event-ID` 头与 `?after_seq=` **都解析**，起点 = **max(两者)**（防降级重放导致重复投递）；非法值 `422`；起点大于 `last_seq` 时**不报错**，只等新帧。

* **SSE 帧格式**（`Content-Type: text/event-stream`；`Cache-Control: no-cache`；`X-Accel-Buffering: no`）：

```
id: <seq>
event: <kind>
data: {"seq":<n>,"kind":"<kind>","payload":{...},"is_terminal":false}

```

* **心跳**：每 15 秒发一行注释 `: hb`（SSE 注释不产生事件、不干扰 `Last-Event-ID`）。

* **关流**：读到并发出 `is_terminal=true` 帧后**主动关流**；重连且起点已覆盖终态 ⇒ 立即关流（无新帧）。单连接超过 `MAX_CONNECTION_SECONDS` ⇒ 关流（客户端自动重连续播）。

* **实现注**：`StreamingResponse` + 生成器内**短轮询读增量**（同步 DB 读在线程池执行）；生成器须处理客户端断开（正常回收，无副作用）。

* **错误语义汇总**：`401` 未认证；`403` 非对话岗位；`404` 会话不存在 / 跨租户 / 不属于；`422` 非法 `run_id` / `after_seq`。

* **读端与状态**：读到状态 `unavailable` ⇒ 服务端补发一帧 `stream.unavailable`（`is_terminal=true`）后关流（**熔断时已落的那帧优先**，语义等价：显式告知 + 终态）。

### 2.4 事项 C：Q7 裁决 —— 候选① `POST /messages:stream`

**推荐并采用候选①**（零破坏）：

* **请求**：路径参数 + 请求体与 `POST /messages` **完全一致**（`{"content": string}`，`extra=forbid`）+ 请求头 `Idempotency-Key` 语义**完全一致**（带键 ⇒ 真实执行 + 幂等；不带键 ⇒ 桩回复，**不写帧**）。

* **响应**：**非流式**——沿用既有响应体与状态码（`201` 已执行 / `202` 待批 / `422` / `403` / `409` / `504`），**外加响应头** **`X-Stream-Run-Id: <run_id>`**（有运行时）；客户端据此打开 SSE 续看过程。

* **为什么不把响应本身做成流**：把执行契约整体流化会复制全部错误语义（幂等、`504` 超时、审批 `202` 分支），并直接冲击 PWA / 桌面端既有契约；「POST 保持同步语义 + 伴随 SSE 通道」是**最小且零破坏**的形态，P2a 的硬上限与闸门语义**原样保留**。

* **帧写入触发面**：**仅** **`messages:stream`** 触发（带键真实执行路径；桩路径不写帧）。旧 `POST /messages` **完全不写帧**——「零破坏」由此拥有**可验证断言**（哨兵：走旧端点后帧表计数为 0，§4 用例 8）。

* **幂等重放**：同键重放**不重复执行、不重复写帧**；返回既有结果 + 既有 `X-Stream-Run-Id`；客户端打开流时按已落帧补发至终态后关流。

* **审批分支**：`202`（需审批）时流以 `approval.requested` 帧 + 非终态暂停？——**定**：`202` 返回时该次执行暂停在待批态，帧不写 `is_terminal`（流保持 `streaming`，客户端显示「待审批」由既有审批聚合承担）；审批决议后的推进（既有机制）**不新增帧写入触发**（推进不经过 `messages:stream`）——**本期流只覆盖「发起执行 → 首次结果（含待批 / 终态）」**，审批后推进的过程事件**不在本期**（登记为已知限制，P2c 可先用既有审批聚合展示）。⚠️ 此点为**待评审确认项**（§5）。

### 2.5 事项 E：过程事件（十种枚举复用 + 三表分工）

**帧** **`kind`** **取值域（本期冻结）**：

| 类别 | 取值                                   | 说明                                                                                                                                                                                           |
| -- | ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 消息 | `message.user` / `message.assistant` | 消息落库后写帧（payload：`message_id`、`stub`；**不含正文**——正文写进消息表，帧只作「已落定」信号 + id）                                                                                                                       |
| 过程 | `RuntimeEventType` **十种原值**          | `plan.created` / `step.started` / `tool.call` / `tool.result` / `approval.requested` / `approval.decided` / `checkpoint.saved` / `run.paused` / `run.failed` / `run.completed`（复用既有枚举，不另起一套） |
| 系统 | `stream.unavailable`                 | 熔断 / 写失败 / 悬挂兜底的**显式告知**帧（`is_terminal=true`，reason 为受控枚举）                                                                                                                                   |

**与审计的分工**（守住设计文档 §17.5 表格口径）：

| <br /> | 审计（既有）                                | 过程事件（本层）                               |
| ------ | ------------------------------------- | -------------------------------------- |
| 回答的问题  | **谁改了什么**                             | **agent 在做什么**                         |
| 存储     | `workbench_audit_log`                 | `workbench_conversation_stream_frames` |
| 明细     | 严格白名单（`ALLOWED_DETAIL_KEYS`），未声明键直接拒绝 | 可含工具参数与输出摘要（**仍须脱敏**）                  |
| 可清空    | **不可**（只有 INSERT / SELECT）            | 按保留期清理                                 |

**脱敏硬要求（复述为不可协商项）**：

1. 一切帧 `payload` **写入前**过 `redact_payload`（同一函数、同一规则；掩码幂等）。
2. **默认只落摘要**：`tool.result` 帧只含 `status` + 摘要 + `args_digest` + `sha256`（与 `027` 落库口径一致）；**不含** stdout 全文、文件正文、宿主真实路径（对外虚拟路径）、凭据 / 认证头 / Cookie。
3. **跨租户隔离同审计口径**：帧表带 `tenant_id` 且写进复合外键；读端按归属过滤。
4. `message.*` 帧**不落正文**（正文在消息表，帧只落 `message_id` 与状态标记）——降低帧表敏感面。

### 2.6 事项 F 之二：Q8 保留期与清理（答复）

* **保留期**：默认 **7 天**（`WORKBENCH_STREAM_RETENTION_DAYS`，1–90）；终态时 `expires_at = now() + 保留期`。

* **清理任务** `conversation-stream-purge`（worker 周期；**独立于运行事件清理**）：① 先做**悬挂兜底**（§2.2）；② 删除 `expires_at < now()` 的 run 的**全部帧行 + 状态行**；③ **逐租户**执行（带 `tenant_id`，沿用知识治理到期扫描的跨租户手法），**只清流帧**——消息表 / 审计 / 运行事件**不受影响**。

* **不回退序号**：清理后该 run 不再追加，`seq` 不复用。

* **审计不动**：清理**不写审计**（清理是例行维护；与运行事件清理同口径）；熔断 / 写失败 / 悬挂收口**写审计**（治理事件）。

### 2.7 借鉴清单裁定（evoflow §2.3 九条逐条）

| # | 借鉴点                                                | 裁定                    | 落点 / 理由                                                                        |
| - | -------------------------------------------------- | --------------------- | ------------------------------------------------------------------------------ |
| 1 | 流帧拆两张表（明细 + 状态，含计数与过期）                             | **纳入**                | §2.1                                                                           |
| 2 | 续播按 `seq` 真增量 + 水位列 `persisted_to_message_id`      | **纳入**                | §2.1 / §2.3                                                                    |
| 3 | 帧数 + 字节双上限熔断；换 `run_id` 清旧帧；清理带 `tenant_id`        | **纳入（一处偏离）**          | §2.2 / §2.6：熔断与租户清理纳入；「换 run 清旧帧」改为**多 run 独立 + 6h 悬挂兜底**（并发互踩比悬挂更糟，且删除不是治理手段） |
| 4 | 过程事件与审计三表分工 + 复用十种枚举 + `retention_class`           | **纳入（retention 换形态）** | §2.5 / §2.6：复用十种枚举与三表分工；保留期由**状态行** **`expires_at`** 表达（每 run 一行，不加单值枚举列）      |
| 5 | 工具结果默认只落摘要 + `args_digest` + `sha256`              | **纳入（沿用 P2a 已定死口径）**  | §2.5：本层不新增落点、不放松                                                               |
| 6 | 上下文预算参数化（`context_policy` / `context_used_tokens`） | **不纳入本期**             | 登记为后续专项（dsh 自带压缩；无真实长会话校准）                                                     |
| 7 | 摘要反幻觉前缀                                            | **不纳入本期**             | 依赖 LLM 摘要（第一版不做）；随上下文专项                                                        |
| 8 | 用量账本归因 + `workbench_usage_daily`                   | **不纳入本期**             | 登记为后续专项，**须与「日预算熔断」同批设计**                                                      |
| 9 | 第一版不做 LLM 摘要                                       | **纳入（= 本版不做）**        | §1.3-3                                                                         |

### 2.8 并发与异常边界（设计口径）

| 场景                           | 口径                                                            |
| ---------------------------- | ------------------------------------------------------------- |
| 同一会话并发两次 `messages:stream`   | 各自独立 run / 状态行 / 帧序列，互不影响；SSE 缺省取「最新活跃 run」，读端可显式 `run_id` 指定 |
| 旧端点 `POST /messages`（带键真实执行） | **不写帧**、不产生任何新表写入（零破坏哨兵断言）                                    |
| 帧写入失败                        | `unavailable('write_failed')` + 审计；**执行继续**，结果以消息表 / 运行为准     |
| 熔断                           | `unavailable('frame_limit'/'byte_limit')` + 终态告知帧 + 审计；执行继续   |
| 悬挂（未终态久无更新）                  | 清理任务置 `unavailable('stalled')` + `expires_at`；读端按状态补终态帧关流     |
| SSE 连接超时 / 客户端断开             | 关流 / 正常回收；客户端（浏览器 `EventSource`）自动重连续播                        |
| 会话归档后开流                      | **允许开流**（读语义同 `GET /conversations/{id}`）；发消息仍 `409`           |
| 执行 `504` 超时                  | POST 请求内超时语义不变；已落帧保留（客户端可从流读到截至超时前的过程 + 现有失败帧）                |

***

## 3. 六要素（feature-inventory 回填稿）

| 要素        | 内容                                                                                                                                             |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| **谁用**    | 对话入口岗位（`employee` / `department_lead` / `ceo` / `super_admin`）；`ceo` / `super_admin` 可读本租户他人会话流。**本期后端先行**，前端消费方 = P2c                         |
| **输什么**   | `POST .../messages:stream`：`{"content"}`（`extra=forbid`）+ 可选 `Idempotency-Key`；`GET .../stream`：`?run_id=` / `?after_seq=` / `Last-Event-ID` 头 |
| **得什么结果** | 帧落库（两表，含状态与水位）；SSE 增量事件（`id`/`event`/`data`）；终态主动关流；熔断 / 写失败 / 悬挂写审计；清理任务删除到期帧                                                                 |
| **角色与权限** | 未认证 `401`；`customer_admin` `403`；跨租户 / 改他人会话 / 未知 run `404`；归档会话发消息 `409`；非法参数 `422`                                                           |
| **正常流程**  | ① 带键 POST `messages:stream` → ② 同步执行逐步写帧（先落库）→ ③ 客户端 `GET .../stream` 尾随 → ④ 收到 `is_terminal` 关流 → ⑤ 断线重连带 `Last-Event-ID` 从 `seq+1` 续播        |
| **异常与边界** | 无 run 挂起仅心跳；超限熔断 `unavailable`（显式告知）；写失败不阻断执行；悬挂 6h 收口；`after_seq` 越界不报错；帧到期由清理任务删除（只清流帧）                                                      |

***

## 4. 测试与判据（先红后绿；风险分级：流属 P1 级）

**真库用例**（`tests/test_conversation_stream_postgres.py`，纳入 `ci.yml` postgres job 清单并在 `tests/test_ci_assets.py` 钉死）：

1. **序号与顺序**：同 run 内 `seq` 从 1 单调递增无跳号；`is_terminal` 帧最多一帧且为末帧。
2. **续播真增量**：`after_seq=k` 只返回 `seq > k`；`Last-Event-ID` 与 `after_seq` 并存取 **max**；越界起点不报错只等新帧。
3. **跨租户拒写**：伪造 `tenant_id` 的帧写入 → 数据库复合外键 `ForeignKeyViolation`。
4. **熔断**：帧数 / 字节超限 ⇒ 状态 `unavailable` + **重开流可读到** **`stream.unavailable`** **终态帧**（反静默丢帧）+ 审计 `conversation.stream.unavailable`；后续帧不再写入。
5. **清理跨租户 + 只清流帧**：两租户各一到期 run ⇒ 一次清理全清、未到期不动；清理后消息表 / 审计 / 运行事件行数不变。
6. **悬挂兜底**：`updated_at` 超阈的 `streaming` 行 ⇒ 置 `unavailable('stalled')` + `expires_at` 置位；读端补终态帧关流。
7. **幂等重放不重复写帧**：同 `Idempotency-Key` 重放 ⇒ 帧表计数不变、返回既有 run\_id。
8. **零破坏哨兵**：走旧 `POST /messages`（带键真实执行）⇒ 帧表**计数为 0**；且其响应体 / 状态码 / 审计与改造前逐字节一致（回归用既有测试原样重跑）。
9. **脱敏**：payload 注入凭据键 / `Bearer` 形态 / `sk-` 前缀 ⇒ 落库为掩码；重复脱敏幂等（`hash` 不变）。
10. **权限矩阵**：`401` / `403`（`customer_admin`）/ `404`（跨租户、他人会话）/ `409`（归档会话发消息）/ `422`（非法 `after_seq`、未知字段）。

**SSE 读端用例**（ASGI 流式测试，`StreamingResponse` 逐块断言）：事件序列与 `id` 单调、`event` = `kind`、`data` JSON 可解析、心跳注释存在、终态关流、重连续播不重复投递。

**反假测试（必须变红）**：① 把写入改成「先推后落」（缺帧表行）→ 用例 1/2 红；② 熔断改为静默丢帧（不写告知帧）→ 用例 4 红；③ 去掉 `tenant_id` 过滤 → 用例 3/5 红；④ SSE 起点改为固定 0（不续播）→ 用例 2 红。

**一键全量**：`pytest`（含新文件）+ `compileall` + 两端 vitest/build + 桌面 `node --test`；CI 6/6 job 全绿后销账（销账行按 knowledge-governance §0 体例写入本文 §0）。

***

## 5. 待裁决项（评审时答复）

| #   | 事项                                | 推荐                                             | 备选                         |
| --- | --------------------------------- | ---------------------------------------------- | -------------------------- |
| Q7  | 接口候选                              | **候选①**：新增 `messages:stream`（§2.4）             | ② `?stream=true`；③ 破坏性改旧契约 |
| Q8  | 保留期与清理                            | **7 天 + 双上限熔断 + 6h 悬挂兜底 + 逐租户清理**（§2.2 / §2.6） | 与运行事件同为 30 天；更短（如 3 天）     |
| —   | 帧写入触发面                            | **仅** **`messages:stream`**（旧端点零帧，零破坏可断言）      | 两个端点都写帧                    |
| —   | 推送底座                              | **PG 表 + 短轮询**（不引入 Redis / WS）                 | Redis Pub/Sub（多副本时再评估）     |
| —   | **审批后推进的过程事件**                    | **本期不做**（流只覆盖「发起 → 首次结果」；待批后推进走既有审批聚合）         | 纳入本期（需把推进路径也接入帧写入）         |
| —   | 熔断阈值默认值                           | 2000 帧 / 4 MiB per run                         | 评审另定                       |
| —   | 借鉴第 6/7/8 条（上下文预算 / 反幻觉前缀 / 用量归因） | **本期不纳入，登记后续专项**（§2.7）                         | 评审要求纳入则另立专项规格              |
| Q10 | §17.2 分组与归属                       | **留给 P2c**（本规格不答）                              | —                          |

***

## 6. 未验证登记（如实）

1. **本规格全部内容尚未实现**（未验证）；本文件为草案，未开工。
2. **SSE 在反代（Nginx / Caddy）下的缓冲行为未验证**：`X-Accel-Buffering: no` 已预置，但真实部署的反代配置需在 staging 实测（登记为 staging 验收项）。
3. **长连接资源占用未压测**：SSE 连接数 × uvicorn worker 数的资源画像未取证；读轮询间隔与连接上限需在 staging 校准。
4. **多副本部署语义未定义**：本层设计不依赖进程内状态（读端只读 PG），但「SSE 路由到不同副本」的实测未做；如需粘性会话，属部署配置范畴。
5. **`027`** **加密正文列与帧的关系**：本层不触碰（只落摘要）；「待批动作重跑后产生的过程事件」属 §5 待裁决项，未实现前**不得**声称覆盖。

***

## 7. 实施顺序（评审通过后，逐段独立验收）

1. **迁移 035 + 仓储 + 真库用例（先红）**：两表 DDL 幂等、复合外键、序号分配、跨租户拒写。
2. **写入网关 +** **`messages:stream`** **端点**：脱敏 → 熔断 → 落库 → 水位回填；零破坏哨兵用例。
3. **SSE 端点**：续播（`Last-Event-ID` / `after_seq`）、心跳、终态关流、错误语义矩阵。
4. **清理任务 + 悬挂兜底 + worker 接线**（Windows 独立 beat 口径沿用既有部署约定）。
5. **契约回写**：`api-contract.md` 新章节 + 回改「非流式」已知限制；`feature-inventory` §2 / §3 六要素登记；`change-record` 条目。
6. **CI 收尾**：`ci.yml` postgres 清单 + `test_ci_assets.py` 钉死 → 6/6 全绿 → 销账行回写本文 §0 → **交用户确认后推送**。

