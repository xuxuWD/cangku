# EvoFlow 完整源码研读报告与修改方案

> **性质**：**调研 + 改造提案**。本文件不是决策记录；由其推导的决策经评审后写入 [`2026-09-12-conversational-agent-platform-design.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md) §4。
> **日期**：2026-09-12
> **方法**：`git clone --depth 1` 完整克隆到 `d:\徐徐AI学习\_evoflow-study\EvoFlow`（**仓库之外**，107.7 MB / 4750 文件 / 1973 个 Python 文件），按 6 个研究域并行深读**完整源码**（不是片段）。**全程只读，未修改对方仓库，未向本项目引入其任何代码。**
> **许可边界**：参考项目为 **PolyForm Noncommercial License 1.0.0**（源码可见、**非 OSI 开源**）。复制、修改、分发在其许可下允许，但**商业用途需书面授权**——本项目是营利公司业务系统，故**只提炼设计，不搬运代码**。

---

## 1. 最重要的五个发现

### 1.1 🔴 我们自己的安全回归点：`full_auto` 比参照产品更宽松

| | 参照产品 | 我们（P1a 已交付） |
| --- | --- | --- |
| 自治三档 | `full_auto` / `approval_for_risky` / `approval_for_all` | 同名三档 |
| 风险档位数 | **4 档**（low / medium / high / **critical**） | **3 档**（low / medium / high） |
| 判定 | `needs_approval = risk_order >= threshold_order`，三档阈值分别为 critical / medium / low → **critical 对任何自治档都必须审批** | **`full_auto` = 免批**，无例外 |
| 默认 | `approval_for_all`（最保守） | `approval_for_risky` |

**证据**：`evoflow/proactive/models.py:71-99`（`needs_approval` 与阈值映射）。
**结论**：我们缺 `critical` 档，且 `full_auto` 没有任何兜底 → **一个 `full_auto` 的数字员工可以无人工审批地执行最高风险动作**。这是 P1a 引入的回归点，**必须在 P2a 开放真实工具前修掉**。
**修法**：`024` 迁移把 `risk_threshold` 的 `CHECK` 扩为 4 档；治理判定里写死「`risk = critical` ⇒ 必须审批，`full_auto` 不豁免」；加反假测试（把 `full_auto` 下的 critical 判成免批必须变红）。

### 1.2 我们有三处比它强，且是**结构性**的（不要退化成它）

| 维度 | 参照产品（证据） | 我们 |
| --- | --- | --- |
| **租户隔离** | `org_id` 只是普通列；119 张表**零 `CHECK` 约束**、仅 14 处 `FOREIGN KEY`，**无一处含 `org_id` 的复合外键**，全靠应用层 `WHERE` | `(tenant_id, conversation_id)` 复合外键，**跨租户引用在数据库层直接 `ForeignKeyViolation`**（§16.2 已在真实 PG 实测） |
| **审计不可篡改** | 审计表是**普通表**，schema 里 **0 个 `CREATE TRIGGER`**，可 UPDATE/DELETE；沙箱审计还提供 `clear_all_sandbox_audit()` **一键清空** | `workbench_audit_log` 只有 INSERT/SELECT；明细走严格白名单 `ALLOWED_DETAIL_KEYS`，未声明键直接抛错 |
| **金额精度** | `usage_events.quantity REAL` / `amount REAL`（浮点） | `cost_cents BIGINT`（整数分），并有 `reversal_of` 冲正链路 |

**另有两条**：它是「一个 DDL 串 + 一个 `PRAGMA user_version`」的**单基线**，旧库没有逐步迁移路径（只能把 142 硬压成 1）；我们有 23 个有序迁移 + staging 清单守护。它的 `orphan_ownership_heal` 会把「无主数据」**批量盖成本地管理员且不写审计**——我们没有这种隐式改归属的路径。

### 1.3 确认：它**没有**自进化闭环（比此前判断缺口更大）

**最终判断（完整源码复核）**：不存在「候选 → 评测 → 人工批准 → 灰度 → 回滚」流水线。**缺的不只是人审，还缺评测门禁与版本指针式回滚。**

| 环节 | 它的实际状态（证据） |
| --- | --- |
| 评测 | `eval/` 是**旁路**：`eval_engine.py` 只做 run/case/result/alert/compare，全部消费者是 admin/cli/dashboard/observability，**没有任何「评测通过 → 接受候选」的写路径**；评测用例也不覆盖「新技能 vs 旧技能在 held-out 上严格提升」 |
| 技能沉淀 | `assets/phase2.py` 由 LLM 输出**直接写** `craft/*/SKILL.md`；`person_kernel.py:1685` 的 `consolidate_craft_overnight` docstring 明写 **"No human approval"**，启发式阈值（≥2 sightings）达成即 `graduated` 并自动建技能 |
| 晋升 | `assets/promote.py::promote_craft_to_custom` = `shutil` 拷贝 + 改 frontmatter，`overwrite=True` 先 `rmtree`；**无版本、无灰度、无指针切换** |
| 回滚 | 全库 `rollback` 只命中软件更新回滚、DB 事务回滚、安装回滚三处，**与资产自进化无关** |
| 人工确认 | 唯一一处是**提示词软约束**（`prompt_blocks_zh.py` 要求先问用户是否沉淀），不是硬闸门 |

**推论**：§14.1 P6 的「FlowEvo 技能沉淀 + SkillOpt held-out 准入 + Langfuse 灰度回滚 + 人工闸门」**必须自建**，参照产品只能供记忆/资产的**形态**参考，供不了闭环。

### 1.4 它的「断线续播」其实是退化的——我们要做得比它真

- 前端全仓 grep `Last-Event-ID` **零命中**；续播触发条件**只有用户手动刷新**（`react/hooks/useStreamResume.ts`）。
- 后端 `stream_resume` 实际是**历史轮询**：每 800ms 轮 DB 推 `historySnapshot`，TTL 300s。
- 帧级镜像表确实存在（`evoflow_chat_stream_mirror` + `_meta`，含 `seq` / `is_terminal` / `last_persisted_seq`），但 `routers/stream_resume.py` 侧 **`afterSeq` 被接受后忽略**（注释：`mirror seq watermark retired`）。

**结论**：它的 seq 帧落库**没有给聊天续播用**（已退役）。D15 定的「先落库再推送 + 按 `seq` 真续播」**比它强**，应坚持。

### 1.5 它做**全表暴力向量检索**，我们已有 pgvector 应建索引

- `knowledge/owned/retrieve.py::search_vector` 是**把全表拉回逐条算 cosine**（无 ANN 索引）；另一条 `sqlite-vec` 的 `vec0` 表**未被检索路径使用**。
- 我们的 `pgvector` 已装好但从未使用（§2.1 事实 12）。

**结论**：P3 上 pgvector 时**要建 HNSW/IVFFlat 索引**，这是**改进而非照抄**；并加 `embedding_model` / `embedding_dim` 两列防混模型（对齐 D12）。

---

## 2. 修改方案（按期）

### 2.1 P2a 开工前必做：`024` 治理字段校正

| # | 改动 | 依据 |
| --- | --- | --- |
| 1 | `risk_threshold` 的 `CHECK` 由 3 档扩为 **4 档**（加 `critical`） | §1.1 |
| 2 | 治理判定写死「`risk = critical` ⇒ 必须审批，`full_auto` 不豁免」+ 反假测试 | §1.1 |
| 3 | `approval_timeout_by_type JSONB NOT NULL DEFAULT '{}'`（按动作类型分设超时；解析后 clamp `[5,10080]`，未命中回落 `approval_timeout_minutes`） | `proactive/decision_gate.py:61-101` |
| 4 | `per_run_budget_cents BIGINT NOT NULL DEFAULT 0 CHECK (>= 0)`（单轮预算，轮末按 `usage_ledger` 聚合比对） | `proactive/runner.py:1795-1830` |
| 5 | 驳回**强制填原因**，并把原因回写该员工的记忆/反思字段供下一轮注入 | `router.py:1609-1618`、`decision_gate.py:420-450` |
| 6 | 审批在 **50% 超时**处发一次升级提醒（补齐「先提醒、后拒绝」） | `decision_gate.py:457-546` |
| 7 | **不改** `daily_budget_cents` 的「0 = 用租户默认」语义，但要在文档里显式标注「与之相反（它 0 = 不限）」，避免误读 | `proactive/models.py` |

**⚠️ 一处需评审的冲突**：参照产品有「预算超额三策略」（`skip_patrol` / `pause_role` / `notify_only`），与我们 D 系列「超限**直接拒绝而非降级**」冲突。**建议维持我们的口径**，只吸收它「单轮预算」这个维度，不引入三策略。

### 2.2 P2a：工具闸门与运行时（服务 D5 / D8）

| # | 改动 | 依据 |
| --- | --- | --- |
| 1 | **授权位 + 计划摘要比对**：运行行上加 `execution_authorized_at` / `execution_authorized_by` / `authorized_plan_digest`。工具执行前算 `current_plan_digest`，**不等即视为已撤销**（不依赖任何人记得发撤销事件）。计划/参数一变自动失效 | `collab/authorize_execution.py`、`plan_session_task.py:627-646` |
| 2 | **授权 actor 白名单**：`{user, system, api, ui, automation}`；**审批接口不接受请求体里的 `authorized_by`**，由服务端从认证态推导；显式拒绝 `agent` 来源 | `authorize_execution.py:16,40-45` |
| 3 | **运行状态转换白名单表** + `validate_transition`（注意：查询函数不拦人，必须在写库前调用 validate） | `collab/state_transitions.py:45-127` |
| 4 | **中间件链四点钩子**（`before_model` / `after_model` / `wrap_model_call` / `wrap_tool_call`）；**审批挂 `wrap_tool_call`**；顺序写进 `docs/architecture.md` 并在启动时断言关键顺序 | `agents/middlewares/`（78 个文件） |
| 5 | **被拦截也回一条 `tool.result(status=blocked, block_reason=...)`** 让循环继续，而不是抛错终止 | `plan_guard_middleware.py:812-829` |
| 6 | **指纹化循环检测**：过程事件表加 `args_hash`，按 `(tenant_id, run_id)` 统计最近 N 步指纹；超阈值写 `loop.detected` + 回 blocked。**必须落 PG**，不抄它的进程内窗口 | `loop_detection_middleware.py:302-499` |
| 7 | **区分「自动 run」与「人工会话 run」的预算档位**：自动触发的 run 默认更严 | `automation_run_guard_middleware.py:24-27` |
| 8 | **审批先落库再阻塞**：写进 P2b 契约——`approval.requested` 必须先落库并推送，才允许进入等待（否则 UI 停在 pending 变 orphan） | `tool_approval_middleware.py:279-321` |
| 9 | **危险命令黑名单不可被 `grant_all` 覆盖，且执行前二次校验**（防「批准后参数被替换」） | `tool_approval_denylist.py`、`tool_approval_executor.py:144` |
| 10 | **工具白名单五级回退、永不回落全局 dump**；空交集记 warning 并降级，全落空时兜底为「本模式绑定的最小集」 | `collab/worker_tool_allowlist.py:97-180` |
| 11 | **阶段 × 工具白名单双重强制**：组装工具面时过滤一次，**执行入口再校验一次**（不能只在 prompt/前端收窄） | `plan_guard_middleware.py:1811,1951` |
| 12 | **沙箱三道正交控制**对齐 `profile(read-only/workspace/danger-full-access)` × `approval(untrusted/on-request/never)` × 会话预设；虚拟路径映射 + **输出反向脱敏**（不暴露宿主路径） | `execution_security/config.py`、`sandbox/tools.py` |

### 2.3 P2b：流与过程事件（服务 D15 / D16，并回答 Q9）

| # | 改动 | 依据 |
| --- | --- | --- |
| 1 | **流帧拆两张表**：明细表 `(tenant_id, conversation_id, run_id, seq, kind, payload, is_terminal)` + 状态表 `(..., last_seq, frame_count, byte_count, expires_at, is_terminal)`。避免对大表频繁 `COUNT/SUM` | `stream_mirror_repositories.py:246-324` |
| 2 | **续播按 `seq` 真增量**（`after_seq`）+ 水位列 `persisted_to_message_id`（空 = 尚未落消息表）；完成后缩短 TTL | 同上 `:337-375` |
| 3 | **帧数 + 字节双上限熔断**；超限置 `unavailable` 而非静默丢帧；换 `run_id` 时清旧帧；清理任务**必须带 `tenant_id`** | `stream_mirror_repositories.py:20-21,277-284` |
| 4 | **过程事件与审计三表分工**：trace 事件（agent 在做什么）/ 工具调用（耗时与结果）/ 审批审计（谁批了哪个调用）。`event_type` **复用既有 `RuntimeEventType` 十种**，不另起枚举；加 `retention_class` 与 `retention_days` | `observability/tables.py:4-12` |
| 5 | **🔴 Q9 的落点**：工具结果**默认只落「摘要 + `args_digest` + `sha256`」**，原文走对象存储并只存引用；「送模型视图」按 `tool_history_keep_rounds` 保留最近 N 轮原文，更老的合并为 `[tool:history]` 块 | `tools/large_result_store.py`、`config/tool_results_config.py` |
| 6 | **上下文预算参数化**：`context_policy JSONB`（`threshold_ratio=0.90`、`protect_tail_messages=12`、`protect_tail_tool_rounds=3`、`summary_content_ratio=0.22`）；会话表加 `context_used_tokens` / `context_window_tokens`；**压缩摘要作为一条 message 落库**（复用既有消息表 + 新 `kind='summary'`），天然获得续播能力 | `context_compaction_core.py:42-49,762-819` |
| 7 | 摘要素材**照抄它的反幻觉前缀口径**（明确声明「摘要里的已完成是未经验证的主张，必须先复验」） | `context_compaction_core.py:121-136` |
| 8 | **用量账本补归因维度与日汇总**：给 `workbench_usage_ledger` 加 `conversation_id / agent_key / run_id / message_id`（可空）、`quantity_in / quantity_out`、`unit / category / provider / model_key / meta`；**新增 `workbench_usage_daily`**（UPSERT 增量累加）。这是 `daily_budget_cents` 熔断的落点 | `usage_ledger.py:52-167` |
| 9 | **第一版不做 LLM 摘要**：只做**无 LLM 的分层裁剪**（清旧工具结果 + 保尾部）。LLM 摘要列为后续可选项，且必须走 `usage_ledger` 计费 | 见 §3 第 3 条 |

### 2.4 P2c：前端交互模型（服务 D14）

**最小可行路径（四步，逐步验收）**

| 步 | 改动 | 依据 |
| --- | --- | --- |
| **P2c-0** | **把「整页卸载」改成「常驻外壳 + `hidden` 切换」**：`App.tsx` 只挂一次 `AppShell`，`workspace` 区拆 `<ConversationHost>` + `<StageHost>`；11 个 view 用 `hidden` 切换而非 `return <XxxPage/>`。**这是「对话主轴」的物理前提，且不触碰任何页面内部实现** | `router.js` 的 `chat-persistent-host` |
| **P2c-1** | 新建 `admin-web/src/features/stage/`：`stage-types.ts` + `stage-store.ts`（外部 store + `useSyncExternalStore`）+ **`stage-decide.ts`（纯函数决策）** + `StageHost.tsx`（kind 注册表）。**先为 `stage-decide` 写失败单测**，再写组件。**首批只注册两类已有真实数据的面板：审批待办 + 计划** | `decide-right-stage.ts`、`right-stage-store.ts`、`right-stage-registry.tsx` |
| **P2c-2** | `ContentWorkbenchPage` 列表改**树形（父子）+ 来源分段**（对话/员工/工作流），把「任务与项目」分组做实；不必新建页面 | `pages/tasks.js` + `lib/task-tree.js` |
| **P2c-3**（依赖 P2b） | 注册 `工具流水 / 文件 diff / 终端` 三个 kind；diff 用**前端 LCS**，且**只有落定才渲染 diff**（运行中不铺内容），全部加 cap | `react/file-diff-util.ts`、`worker-file-tools.ts` |

**三件套决策输入（最容易漏、也最影响体感）**：Stage 的展开由 `userPinned + dismissedThisRun + autoPreviewEnabled + currentKind + intent` 决定，**优先「用户钉住」与「本轮已关过」**，避免「用户刚关掉又被自动拉开」。

**面板分层**：「产物 / 上下文用量 / 员工信息」这类**轻信息**放对话右缘的 Info Rail（tab），**不占舞台**；舞台只留给重型内容。这与 §17.3 的表一一对应，避免舞台塞满小卡片。

**流合并范式（P2b 消费时用）**：按 `tool_call_id`（**不是 `id`**）聚合；收到终态后**拒绝回退**；`final` 时深拷贝冻结快照防串台；双源（token 流 vs 整段快照）去重。**这段逻辑放 store 层而非组件**，并配单测。

**侧栏**：把 `AppShell.tsx` 硬编码的 `SECTIONS(from/to)` 换成**显式分组对象**（按 §17.2 命名），加一个「更多」组收纳低频入口。**只改标签与归属，不动页面**。

### 2.5 P3：记忆层

| # | 改动 | 依据 |
| --- | --- | --- |
| 1 | **记忆原子表** `workbench_memory_atoms(tenant_id, atom_id, namespace_kind, namespace_ref, layer, kind, content, summary, importance, confidence, vitality, subject_key, revision, superseded_by, pin, evidence JSONB, tags JSONB, embedding vector(N), deleted_at, created_at, updated_at)`，主键 `(tenant_id, atom_id)`。**命名空间必须以 `tenant_id` 为首要维度**（它缺这一维，直接映射会串租户） | `memory/store.py`、`namespaces.py` |
| 2 | **确定性 consolidate（不用 LLM）**：同 `subject_key` 合并 + `semantic/procedural` 相似合并（阈值 0.85）+ vitality 指数衰减 + 低置信 GC（`pin` 豁免）；被合并者写 `superseded_by` **不物理删** | `memory/consolidate.py` |
| 3 | **混合检索**：PG `tsvector`（+ `pg_trgm`）与 pgvector 走 **RRF 融合**（K=60）；**中文必须带二元组兜底** | `owned/retrieve.py::rrf_fuse` |
| 4 | **建向量索引**（HNSW/IVFFlat）+ `embedding_model` / `embedding_dim` 两列 | §1.5（改进） |
| 5 | **知识 chunk 上下文化**：加 `heading_path` / `context_header` 两列（chunk 带上标题面包屑） | `owned/chunking.py` |
| 6 | **权限过滤在检索之前**（先定可见库，再检索），不是检索后过滤 | `owned/service.py` |

### 2.6 P4：技能 / MCP / 沙箱

| # | 改动 | 依据 |
| --- | --- | --- |
| 1 | 技能注册表加 `scope`（8 级优先级：SYSTEM < PUBLIC < ORG < REPO < GROUP < CUSTOM < PERSONAL < EXTERNAL）与 `enabled`；提示词只注入 `skill:<key>` **简引用**而非全文 | `skills/skill_scope.py`、`skill_uri.py` |
| 2 | `.skill` / zip 安装沿用其**六道校验**（路径穿越 / 符号链接 / zip bomb / frontmatter / 目录结构 / 内容扫描） | `skills/installer.py`、`skills/security.py` |
| 3 | **额外加「来源白名单 + 签名/哈希」**——它没有这道（§15.3 已登记技能市场是攻击面） | 我们的更强项 |
| 4 | **MCP 双向**：客户端（stdio/sse/http 三传输 + OAuth 的并发去重/提前刷新/轮换持久化）+ **服务端**（`CapabilityRegistry` 暴露 tools/list 与 tools/call，带权限门禁） | `mcp/client.py`、`mcp/oauth.py`、`mcp/server.py` |
| 5 | **延迟工具发现**：MCP 工具先只注入名字，运行时经 `tool_search` 取 schema（省上下文） | `tools/builtins/tool_search.py` |
| 6 | 子代理规格：**默认继承父级工具集而非全局目录**、默认禁递归类工具、`max_turns / timeout / lease` 三上限、独立事件循环 + 父 contextvars 复刻 | `subagents/config.py`、`executor.py` |

### 2.7 P6：自进化（结论 = 必须自建）

§1.3 已确认参照产品没有闭环。**维持原方案**，并明确各方分工：

| 层 | 采用 | 职责 |
| --- | --- | --- |
| 技能沉淀 | **FlowEvo 范式** | 成功 workflow → 编译成可执行技能 → 持久技能库 → 效用追踪 → 抑制负迁移 |
| 准入闸门 | **SkillOpt 范式** | held-out 验证集严格提升才接受（**生成者 ≠ 评审者**） |
| 灰度回滚 | **Langfuse labels 范式** | 改指针，不原地覆盖 |

**参照产品唯一可借的**是记忆/资产的**形态**（`mem_atoms` 的 layer/kind/vitality/superseded_by 设计），**不是**其晋升机制。

---

## 3. 明确不采纳清单

| # | 不采纳 | 原因 |
| --- | --- | --- |
| 1 | **一切「跨请求状态」放进程内或 SQLite 单文件**（`_pending_goal_nudges`、`_deny_counters`、`_PAUSED_THREADS`、loop detection 窗口、graph cache、`evoflow_goal_sessions`） | 单机成立；我们多副本 + 重启会丢状态或**重复执行**。跨请求状态必须落 PG/Redis 且带 `tenant_id` + 乐观锁 |
| 2 | **全表暴力向量检索**（无 ANN 索引） | 我们已有 pgvector，必须建索引 |
| 3 | **LLM 摘要 + 后台线程池 + 同步 120s 兜底**（超时后「用未压缩历史继续跑」） | 与我们「默认拒绝而非降级」+ 成本熔断冲突。第一版只做无 LLM 分层裁剪 |
| 4 | **用同一模型家族做完成度裁判**（`goal_reply_interpreter` 自评） | 违反「生成者 ≠ 评审者」 |
| 5 | **可清空的沙箱审计**（`clear_all_sandbox_audit()`） | 与 append-only 审计直接冲突 |
| 6 | **无闸门自动晋升技能**（`consolidate_craft_overnight` 的 "No human approval"） | 与「人工批准」相反 |
| 7 | **命名空间不含租户**（`user:` / `agent:` / `workspace:` / `person:`） | 直接映射会跨租户串号 |
| 8 | **`org_id` 软隔离、审计表可改、金额浮点、单基线迁移** | 我们已有更强的做法，退化即损失 |
| 9 | **硬编码 68 个实例的中间件 append 链**（同一类挂两次、顺序靠注释维系） | 我们应做**声明式配置 + 启动时断言关键顺序** |
| 10 | **两代 UI 并存 + 手写 hash 路由 registry + 660KB 单文件** | 历史债，不学 |
| 11 | **AG-UI / openai / evf 三套 wire format 并存** | 我们消费方只有自家 PWA/Electron，D15 的单一帧模型更简单 |
| 12 | **把「先问用户」写进提示词当确认机制** | 提示词不是控制面，不能替代硬闸门 |
| 13 | **Tauri 桌面专有传输**（`data-tauri-drag-region`、Rust 代理流） | PWA/Electron 行为不同 |

---

## 4. 待决策项

| # | 问题 | 影响 |
| --- | --- | --- |
| **A** | 是否采纳 §2.1 的 `024` 治理字段校正（尤其 **`critical` 档 + `full_auto` 不豁免**）？ | **安全**；建议无条件采纳，且必须在 P2a 开放真实工具前完成 |
| **B** | 预算超额：只吸收「单轮预算」维度、**不引入三策略**（维持我们「超限直接拒绝」）？ | 决定 `024` 是否加 `budget_exceed_policy` 列 |
| **C** | §2.4 的 P2c-0（常驻外壳 + hidden 切换）**是否提前到 P2a 就做**？它零后端依赖，且能立刻解决「切页丢会话草稿」 | 影响 P2a 范围 |
| **D** | 原 Q7（流式接口形态）、Q8（过程事件保留期）、Q9（是否落文件原文，本报告建议**不落原文**）、Q10（侧栏分组） | 见立项文档 §17.7 |
| **E** | 是否把 §2.4 的「Info Rail（轻信息栏）」纳入 P2c 范围（否则舞台会被小卡片塞满） | P2c 范围 |

---

## 5. 方法与局限（如实登记）

- **已做**：完整克隆（107.7 MB / 4750 文件）；6 个研究域并行深读**完整源码**；结论均附文件路径或行号。
- **未做**：**未运行**参照产品（未安装依赖、未起服务、未接模型），因此所有结论为**静态代码分析**，运行期行为未经复现。
- **未逐行读完**：`agents/` 2.2 MB、`persistence/schema.py` 81 KB、`context_compaction_core.py` 110 KB、`ChatApp.tsx` 660 KB 等巨型文件只读了与结论相关的部分。
- **未核实**：其 `ToolTimeoutMiddleware` 是否真的生效（在 lead 链上没有挂载点，全 harness 仅命中自身文件）；`zombie_run_sweeper` 未找到（进程重启后遗留 `running` run 如何回收未确认）；`evoflow_orgs` 的完整生命周期未读。
- **文档与代码不一致处**（以代码为准）：其 `DESIGN.md` 称「审批超时 30 分钟升级 / 2 小时自动拒绝」，代码实为 `timeout × 0.5` 升级、`timeout × 1.0` 自动拒绝；常量 `_ESCALATION_LEVEL1/2_MINUTES` 全库无其他引用，**疑为死代码**。
- **临时目录**：`d:\徐徐AI学习\_evoflow-study\`（在仓库之外），可随时删除。

---

## 6. 专项：它的「中间件链」与我们的「九步闸门」对照（2026-09-13 增补）

> **触发**：用户要求分析 EvoFlow 中间件链设计能否借鉴到九步闸门。
> **方法**：只读深读 `backend/packages/harness/evoflow/agents/middlewares/`（**78 项** = 76 个中间件/模块 + 空 `__init__.py` + 辅助模块）× 入口 `agents/lead_agent/agent.py:683` 的 `_build_middlewares`；**汇总方亲验 3 条**（denylist Layer 0、放行后二次校验、拒绝重试拦截）。**未运行**其代码。
> **许可**：PolyForm Noncommercial——本节**只提炼设计语义**，引用均为短摘录，未复制其代码。

### 6.1 它是什么形态

- **机制**：LangChain `AgentMiddleware` + LangGraph；实测只用 **6 组 hook**（`before_agent` / `after_agent` / `before_model` / `after_model` / `wrap_model_call` / `wrap_tool_call`，均含异步版）。
- **规模**：lead 链实际装配 **67 项**（含条件项）；**顺序语义 = 列表中越靠前越外层**（其注释自证 `agent.py:795`：「MUST be before DynamicSystemPrompt（**first=outermost in langchain**）」）。
- ⚠️ **顺序靠注释与人工纪律维护，`tests/` 中无任何顺序断言**——这是**它的弱点，不是可借项**（我们已有更硬的"执行入口唯一 + 顺序固定"契约）。
- **真正承担执行门禁的只有 2 个**：`ToolApprovalMiddleware`（含 denylist，装配于 `agent.py:866`）与 `PlanGuardMiddleware`（`agent.py:794`）；其余 60+ 项是提示注入 / 持久化 / 遥测 / 上下文管理，**不属闸门职责**。

### 6.2 结构性差异（为什么"载体"不可搬）

| 维度 | EvoFlow | 我们（段二） |
| --- | --- | --- |
| 挂载位置 | **引擎内部**的 agent 循环 hook（`wrap_tool_call`） | **引擎之外**的独立执行入口（`api-contract.md` 九步闸门） |
| 拦截手段 | LangGraph `interrupt()` 暂停**同一个 run** | 入口全检 → 落库 → 阻塞 → 审批后**从 ① 重跑** |
| 执行引擎 | 自己的 LangChain agent（同进程） | **dsh（外部进程）**——**拿不到其内部 hook** |
| 拦住恶意逻辑 | 每次 tool call 都过中间件（**边执行边拦**） | 入口**一次性全检**，靠"重跑全套"补偿（`§3.2`） |

**结论**：两者**语义同向、载体不可互换**——它的实现（hook + interrupt）在我们这里**不存在挂载点**，段二规格已定「**闸门全在我们这一侧**」（§3.2 / §2.1）。两条设计互为证据：**正因为我们拿不到引擎内 hook，才必须"审批后从 ① 重跑"**。

### 6.3 亲验条目（4 条）

| # | 它的机制 | 原文（已亲验） | 与我们的关系 |
| --- | --- | --- | --- |
| **1** | **黑名单是 Layer 0：先于一切策略，且不可被覆盖** | `tool_approval_middleware.py:855-859`：`# Layer 0: denylist — non-overridable, blocks before any policy check`；`tool_approval_denylist.py:3-5`：*"runs BEFORE risk-level assessment… **Even when the session policy is `grant_all`, patterns matched here are blocked unconditionally**"* | ✅ 与我们 §3.2.1 **R3**（命中即拒、先于风险定档与授权位、不提供审批后放行）**同构** → 可作**外部佐证** |
| **2** | **放行后、真正执行前再查一次黑名单** | `tool_approval_executor.py:143-145`：`# Defense in depth: re-check denylist at replay time` | ✅ 与我们 §3.2「审批通过后从 ① 重跑」同向；**我们更严**（它只复查黑名单，我们重跑 ②③④） |
| **3** | **拒绝后重试硬拦**（同一工具被拒超 `_DENY_MAX_RETRIES` 次即硬拦，防"拒绝→再试→再拒"死循环） | `tool_approval_middleware.py:867-878` | ⚠️ **我们没有** → P2b 多轮后有价值 |
| **4** | **逐项授权的边界语义：空集合 ≠ 全部批准** | `tool_approval_middleware.py:455`（**未亲验**，标「未核实」） | ⚠️ 我们 ⑦ 缺一条"**空授权集合一律拒**"的负向用例 |

### 6.4 它做了、我们缺的（逐条判适用性）

| 它的机制 | 对我们是否适用 |
| --- | --- |
| **循环检测**（同参批次哈希重复 → 提示 + 拦截，**不终止 run**，让模型换策略） | ✅ **P2b 起适用**（段二为同步单次执行，用不上） |
| **模型降级分层上限**：限流 3 次 / 服务端错误 3 次 / 凭证轮换 3 次 / 模型降级 3 次；**编排中 fail-closed 重抛、空闲会话 fail-open 给用户消息** | ⚠️ 部分适用：模型调用在我们这边（平台既有能力），但这套「**分场景策略 + 分层上限**」正好可填我们 **§8 U7**（重试上限与单次失败降级，现为"未定"） |
| **按阶段/场景动态收窄工具面**（模型看不到 → 对已产出的调用二次过滤并注入**可执行反馈**） | ⚠️ 思路可借，但涉及岗位/角色维度 → **需先裁决** |
| 上下文压缩 / 会话级工具预算 / 子代理上限 / 悬空 tool_call 修补 / 大内容卸载 / 前缀缓存锁定 | ❌ **不适用**（段二 §1.2 明确排除；属 P3/P6） |

### 6.5 它没做、我们已做（**确认不必回退**）

结构化命令（`executable` + `args[]`、禁管道）／**④-0 可执行来源**／realpath + TOCTOU 对策／**B 层参数 + C 层路径黑名单**／`Idempotency-Key`（无键不执行）／append-only 审计 + `reason` 受控枚举 + 明细键白名单 + 不建第二事实源／跨租户数据归属／**审批后从 ① 重跑全套**／容器隔离（分主机 + `--network none` + 只读根 + 无长寿命凭据）。
> **关键区别**：它的黑名单匹配对象是 **`command` 字符串 + 正则**，且只覆盖少量工具；**我们是结构化命令 + A/B/C 三层 + 规范化算法**。**这条不要退化。**

### 6.6 反向教训（不能学）

1. 它的风险判定支持 **`allow` 前缀跳过审批** —— **fail-open**，与我们 fail-closed 相反（**未亲验，标「未核实」**）。
2. **顺序无回归测试守护**，只靠注释——不可复制；我们应保持"顺序即契约 + 用例覆盖"。
3. 审计/追踪为**自由文本 + 自定义文件日志**——与我们"`reason` 受控枚举码 + 明细键白名单"冲突。

### 6.7 建议（4 条）

| # | 建议 | 层次 | 需裁决？ |
| --- | --- | --- | --- |
| 1 | 把「**黑名单 Layer 0 不可覆盖 + 放行后执行前二次校验**」写进 §3.2.1 **R3** 与 §3.2 的**证据链**（用其实现作外部佐证，**不改设计**） | 规约（补证据） | 否 |
| 2 | 补两条**边界用例**：⑦ 的"空授权集合一律拒"；⑨ 前"放行后执行前必须再查黑名单" | 规约（用例） | 否 |
| 3 | 登记一条**未来规约**（P2b 起）：拒绝后重试拦截 + 循环检测；并顺带把 **§8 U7**（重试上限与单次降级）按"3/3/3/3 分层 + 分场景 fail-closed/fail-open"填上 | 规约（未来段） | 否 |
| **4** | 用它的黑名单模式清单（`tool_approval_denylist.py:25-91`）对 §3.2.1 **A/B/C 做一次查漏** | 规约 | ⚠️ **需裁决**：§3.2.1 已"用户确认定稿"，条目增补属**口径变更** |

### 6.8 本节未核实

1. 第 4 条亲验项的原文（`tool_approval_middleware.py:455`）**未逐行亲验**；
2. `allow` 前缀跳过审批的具体实现**未亲验**；
3. `plan_guard` / `loop_detection` / `model_fallback` 的机制细节来自只读视角报告，**汇总方未逐条亲验**；
4. 其仓内文档称"固定顺序构建 13 个中间件"，与代码实测 67 项不一致（**文档漂移**，以代码为准）；
5. **未运行其代码**，全部为静态分析。
