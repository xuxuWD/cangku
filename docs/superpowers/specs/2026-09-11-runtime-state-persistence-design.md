# 运行时状态持久化设计 · 口径（已确认）

> **状态**：**口径已确认**（§9 四项均已定），进入实现（先写失败测试，再写实现）。
> **日期**：2026-09-11　**基线**：`main`（后端 1115 项测试通过，CI 实跑通过）

## 1. 目标与非目标

**目标**：把运行时状态从「进程内」改为「可持久化」，让这些能力**跨重启与多进程**成立：

- 运行审批待办列表（`run_approval`）不再重启即空；
- 旧 `run_id` 的决议 / 暂停 / 恢复 / 取消 / 事件查询在重启后仍然可用；
- `postgres` 模式下不再存在「运行记录已落库、运行时状态却在内存」的口径分裂。

**非目标（明确不做）**：

| 不做 | 原因 |
| --- | --- |
| 事件独立成表 | 当前事件量受计划步数约束（Mock 每步 1–3 条），单行 JSONB 足够；拆表会改动 Mock 的写路径与事件查询语义（见 §10 限制 1） |
| 并发乐观锁（version） | 现状（含内存实现）本就没有原子的读-改-写；加锁会改动存储接口、Mock 写路径与接口错误语义，规模独立（见 §10 限制 2） |
| 历史内存状态的迁移 | 重启后旧运行本就在内存里消失；本设计只保证**新的**运行可恢复 |
| 外部运行时（RAGFlow/AgentScope 等）远端状态同步 | 远端状态仍由对方持有；本设计持久化的是工作台侧的本地镜像 |

## 2. 事实核查（实际读码确认）

| # | 事实 | 位置 |
| --- | --- | --- |
| 1 | `build_runtime_service` 在**所有模式**都用进程内 `RuntimeStateStore`（postgres 也一样） | `app/bootstrap.py:540-553` |
| 2 | `RuntimeState` 持有 context / plan / events / completed_steps / status / checkpoint / approvals / usage / created_at | `app/runtime/state.py` |
| 3 | Mock 的写路径是 `_emit(...)`（内部 `store.append`）与 `store.save_checkpoint(...)`；**`request_approval` 与 `replay_run` 只发事件、不存检查点** | `app/runtime/mock.py` |
| 4 | 事件 payload 在**读取时**才脱敏（`RuntimeEvent.to_public_dict`），落库(内存)时原样保存 | `app/runtime/contracts.py:86-116` |
| 5 | 迁移风格统一使用 `CREATE TABLE IF NOT EXISTS` + JSONB + `idx_workbench_*` 索引；`WORKBENCH_APPLIED_MIGRATIONS` 必须同步登记 | `migrations/*.sql`、`.env.staging.example` |

## 3. 存储结构（迁移 `021_runtime_states.sql`）

```sql
CREATE TABLE IF NOT EXISTS workbench_runtime_states (
    run_id          TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    task_id         TEXT NOT NULL,
    status          TEXT NOT NULL,
    context         JSONB NOT NULL,
    plan            JSONB NOT NULL,
    events          JSONB NOT NULL DEFAULT '[]'::jsonb,
    completed_steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    approvals       JSONB NOT NULL DEFAULT '{}'::jsonb,
    usage           JSONB NOT NULL DEFAULT '{}'::jsonb,
    checkpoint      JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_workbench_runtime_states_tenant
    ON workbench_runtime_states (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_workbench_runtime_states_task
    ON workbench_runtime_states (tenant_id, task_id);
```

- `tenant_id` / `task_id` / `status` **冗余成列**：租户列表与状态过滤走 SQL，不必在 JSONB 里取字段。
- 无外键：运行生命周期可以早于/独立于任务对象，且现有 `workbench_run_records` 也未建外键。

## 4. 序列化与脱敏

新增 `app/runtime/serialization.py`：

| 函数 | 说明 |
| --- | --- |
| `encode_context` / `decode_context` | `RuntimeContext` ↔ JSON（时间用 ISO 8601，含时区；scope 用数组） |
| `encode_plan` / `decode_plan` | `AgentPlan` ↔ JSON（步骤 id/kind/tool/requires_approval） |
| `encode_event` / `decode_event` | `RuntimeEvent` ↔ JSON（**落库前先脱敏 payload**） |
| `encode_state` / `decode_state` | 整行编解码（供存储实现使用） |

- **脱敏下沉**：把 `RuntimeEvent.to_public_dict` 里现有的递归脱敏抽成共享函数 `redact_payload(payload)`（放在 `app/runtime/contracts.py`），**读取路径行为保持不变**；持久化实现调用同一函数，做到「写入时即脱敏」，数据库不长期保存凭据类键。
- **解码严格失败**：结构不合法（缺字段、类型不符、时间无法解析）抛 `InvalidRuntimeState`，**不做「读不到就返回空」的降级**——静默降级会让损坏状态被当成新运行。

## 5. 存储实现与写路径

`app/runtime/state.py` 新增 `PostgresRuntimeStateStore`，接口与内存实现**逐一对齐**：

| 方法 | 语义 |
| --- | --- |
| `create(context, plan, run_id=None)` | 生成运行号并写入整行 |
| `get(run_id)` | 读整行并解码；**不存在时抛 `KeyError`**（与内存实现一致，调用方已按此处理） |
| `list_for_tenant(tenant_id, *, statuses=None)` | 按租户列出，可选状态过滤（SQL `WHERE`） |
| `append(state, event)` | 事件入 state 列表后**整行 upsert** |
| `save_checkpoint(state)` | 写 checkpoint 后**整行 upsert**，返回 checkpoint dict |

**关键性质（也是让 Mock 零改动的原因）**：`append` 与 `save_checkpoint` 都是「整行 upsert」，即每次写入都把**当前对象的全部字段**落库。因此：

- `request_approval` 虽不调用 `save_checkpoint`，但它修改 `approvals` 之后会 `_emit` → `append` → 整行落库，**不会丢写**；
- `replay_run` 同理；
- `pause_run` / `resume_run` / `cancel_run` / `decide_approval` / `start_run` 都已有 `_emit` 或 `save_checkpoint` 兜底。

`get()` 每次返回**新对象**（不做进程内缓存）：这要求「所有变更都必须经过 append / save_checkpoint」——上一条已保证，且有专门测试守护（§8 的回环存储测试）。

## 6. 装配（fail-closed）

新增 `build_runtime_state_store(settings, *, connection=None, migrate=True)`（`app/bootstrap.py`），与 `build_run_metrics` 同构：

- `storage_backend == "memory"`：仅 `env == "development"` 允许，否则 `ValueError("生产环境禁止使用内存运行时状态仓储")`；
- `storage_backend == "postgres"`：缺连接时自建连接池（`database_url`），`migrate=True` 时执行迁移，返回 `PostgresRuntimeStateStore`；
- `main.py`：先建 `run_metrics_service`，再建 `runtime_state_store`，把两者一起注入 `build_runtime_service`。

## 7. 行为不变性

- **对外接口零变化**：路径、状态码、字段、权限一律不变（持久化是内部实现细节）。
- 重启后**能力增强**：旧运行可决议/暂停/恢复/取消、可查事件与指标。
- 重启后**待办不再凭空消失**：`list_pending_approvals` 从存储读，而非只读进程内字典。

## 8. 测试计划（先写测试，后写实现）

| 层次 | 覆盖 |
| --- | --- |
| 序列化 | context / plan / event / 整行 **round-trip 相等**；含时区时间、空 scope、requires_approval；**缺字段或类型不符抛 `InvalidRuntimeState`**；事件 payload 编码时敏感键被替换为「[已隐藏]」 |
| 读取路径不变 | `to_public_dict` 的脱敏输出与抽取前**逐字段一致**（抽取 `redact_payload` 的回归守护） |
| PG 存储（假连接） | `create`/`append`/`save_checkpoint` 的 upsert 语句包含全部列且参数齐全；`get` 按 run_id 取整行、缺失抛 `KeyError`；`list_for_tenant` 带租户条件、可选状态过滤；解码失败抛 `InvalidRuntimeState` |
| **写路径无丢写（回环存储）** | 用「写入即 encode、读取即 decode」的回环存储替换内存存储，跑 Mock 的 start / pause / resume / cancel / request_approval / decide_approval / replay_run，断言**每次调用的效果都能被重新解码看到**（这是本设计最关键的性质测试） |
| 装配 | memory+development 得到内存实现；memory+非 development 报错；postgres 注入连接得到 PG 实现并执行迁移 |
| 迁移与 staging | `test_staging_assets.py` 守护迁移文件与 `WORKBENCH_APPLIED_MIGRATIONS` 一致 |
| 端到端不变 | 既有运行相关接口测试全部保持通过（重启恢复另行以回环存储覆盖） |

## 9. 决策记录（已确认）

| # | 决策 | 结论 |
| --- | --- | --- |
| D1 | 存储结构 | **单行 JSONB**（事件与状态同行） |
| D2 | 事件 payload | **写入时即脱敏**（复用同一套敏感键规则） |
| D3 | postgres 模式装配 | **强制持久化**，缺连接即报错（延续「生产禁止内存仓储」） |
| D4 | 并发修改 | **最后写入获胜**，登记为已知限制 |

## 10. 已知限制（实现后需如实登记）

1. **事件与状态同存一行**：每次写入都重写整行，长运行会出现写放大与行体积增长；事件量受计划步数约束（Mock 每步 1–3 条），超出该量级时应拆出事件表。
2. **并发修改最后写入获胜**：同一运行被两个进程同时修改（如并发决议）时可能相互覆盖；内存实现同样没有原子读-改-写，本轮不加乐观锁。
3. **重启不迁移历史内存状态**：重启前创建的运行不会凭空出现（它们从未落库），这是预期行为。
4. **外部运行时的远端状态仍不持久化**：落库的是工作台侧镜像，远端运行是否可继续由对方决定。
5. **敏感键规则是「键名精确匹配（忽略大小写）」，不是子串匹配**：因此 `cookies`、`session_id` 这类变体不会被替换（沿用既有规则，本轮不扩大匹配范围以免改变读取输出）。

## 11. 落地清单

1. `migrations/021_runtime_states.sql` + `.env.staging.example` 登记。
2. `app/runtime/contracts.py`：抽出 `redact_payload`；`to_public_dict` 改用它（行为不变）。
3. `app/runtime/serialization.py`：编解码 + `InvalidRuntimeState`。
4. `app/runtime/state_postgres.py`：`PostgresRuntimeStateStore`（接口与内存实现对齐）。**放在独立模块**而非 `state.py`：`serialization` 需要 `RuntimeState`，若把 PG 仓储写进 `state.py` 会与 `serialization` 形成循环导入。
5. `app/bootstrap.py`：`build_runtime_state_store`。
6. `app/main.py`：装配顺序与注入。
7. `docs/api-contract.md`（运行章节说明状态落库与限制）、`docs/delivery-gates.md`、`docs/delivery-readiness-checklist.md`（关闭「运行时状态持久化」缺口）。
8. 全量回归（`pytest` + `compileall` + 两端 vitest/build + desktop `node --test`），CI 实跑确认。
