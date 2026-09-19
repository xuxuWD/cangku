# 保留策略服务侧执行器（B-4 选项 C）实施计划

> 状态：**实施计划（未开工）**。依据：用户 2026-09-19 裁决「B-4：**C**（B + `runs` 先子后父删）」，
> 且同批裁决「两个都先出实施计划」「清场扩围三个阻塞点按方案建议全选」。
> 关联：真源 `docs/superpowers/specs/2026-09-06-commercial-g0-design.md`（§6.3 保留 / §6.2 删除）、
> 差距台账 `docs/delivery-remaining-checklist.md`（10.1 / 10.7 的 B-4 条）、
> 清场扩围方案 `docs/superpowers/specs/2026-09-19-tenant-purge-expansion-design.md`（**本执行器的删除原语将被其复用**）。

## 1. 目标（用户已裁决的语义）

把「保留策略」从**声明式**（`DEFAULT_RETENTION_POLICY` 只被部署预检读）变为**服务侧可执行**，按租户策略
把**过期数据**清理掉；三条触发面（用户选项 C）：

| 面 | 默认天数 | 动作 | 用户已接受的代价 |
| --- | --- | --- | --- |
| `tasks` | 180 | 按龄删 `workbench_tasks` | 任务域事件流（`workbench_audit_events`，`ON DELETE CASCADE`）随任务消失 —— **已裁决接受，写进契约与手册** |
| `usage` | 365 | **结转**（净额单行）后按龄清明细 | 新增资金语义（结转行受控 `reason`，`SUM` 逐分不变） |
| `runs` | 180 | **先子后父**显式删（5 张子表 → 运行记录） | **销毁**工具执行证据（027）与运行验收决议（040）、运行→任务沉淀（042）、产物登记（037） |
| `events` | 365 | **不新建执行器** | `runtime_events` 已由全局 `runtime-events-purge` 按 **30 天**清理 ⇒ 实际保留期 = **更短者**（30 天），契约写明 |
| `audit` | 730 | **不删**（730 只作留存上限声明） | 与 10.1 / 10.3 判据一致（审计不可删） |

## 2. 现状取证（2026-09-19 实地勘定，非估算）

- **策略存储**：`workbench_retention_policies (tenant_id PK, policy JSONB, updated_by, updated_at)`（迁移 `007`）；
  服务侧读方法已存在（`CommercialLifecycleService.retention()`），**但没有消费方**。
- **运行域外键（决定删除顺序的关键事实）**：
  - `workbench_run_records`：`run_id` PK、`tenant_id`、`task_id`、`started_at`（索引 `(tenant_id, task_id, started_at DESC)`）；
    027 补 `UNIQUE (run_id, tenant_id)` 供复合外键引用。
  - 子表（**均无 `ON DELETE CASCADE`**，故必须显式先删）：`workbench_run_artifacts`（037）、
    `workbench_run_acceptance_decisions`（040）、`workbench_run_promotions`（042）、
    `workbench_tool_actions`（027，复合外键 `(tenant_id, run_id)`）、`workbench_execution_idempotency`（027，`run_id` 可空）。
  - 关联但**无外键**：`workbench_runtime_states`（021，`run_id` PK）、`workbench_runtime_events`（034，PK `(run_id, sequence)`）、
    `workbench_plan_proposals.run_id`（013 追加列）。
- **账本**：`workbench_usage_ledger (id, tenant_id, idempotency_key, units, cost_cents, reversal_of, reason, actor_id, occurred_at)`，
  `UNIQUE (tenant_id, idempotency_key)`；累计口径 = **全表 `SUM(...)`**（`app/commercial/usage.py`）；
  `reason` / `actor_id` **列已存在**（`reverse()` 已在用）⇒ 结转行**不需要新迁移**。
- **周期任务骨架**：`app/worker.py` 已有 10 个 beat 条目；新增一个条目即可（间隔用 settings 字段外置，
  与既有 `*_purge_interval_seconds` 同口径）。

## 3. 设计决定（实现前先钉死）

### 3.1 结转（`usage`）—— 为什么这样能保证「逐分不变」
设过期集合 `A`（`occurred_at < cutoff`）、其余集合 `B`。动作 = ① 插入一行结转行 `S = SUM(A)`（`units` 与
`cost_cents` 各自求和；`occurred_at = cutoff`；`reason = 'retention_carryover'`；`actor_id = 'system:worker'`；
`idempotency_key = 'retention-carryover:' + cutoff.isoformat()`）⇒ ② `DELETE` 掉 `A`。
则 `SUM(新表) = S + SUM(B) = SUM(A) + SUM(B) = SUM(旧表)` —— **与是否含冲正对无关**，恒等式成立。
- `cutoff` 必须是**确定性时刻**（由 `now - N 天` 生成，同一轮内固定），使 `idempotency_key` 唯一且重放幂等。
- 结转行**自身也受龄**：下一轮若它已过期，会被并入下一笔结转（净额继续前滚）；反之则留在窗口内（不会双算）。
- **冲正对**不需要特殊处理（恒等式已覆盖）；但契约要写明「明细可能被结转行替代，累计不含丢失」。

### 3.2 任务（`tasks`）—— 不制造孤儿运行
`workbench_run_records.task_id` **无外键** ⇒ 直接删任务会留下悬挂运行。规则：
**仅当该任务的运行（若有）全部已过期时才删它**（SQL 谓词：`NOT EXISTS (SELECT 1 FROM workbench_run_records r
WHERE r.task_id = t.id AND r.started_at >= cutoff)`）；不满足则本轮跳过（下一轮其运行过期后自然可删）。
- 同批删除顺序：**先运行域后任务域**，避免「刚删任务、其运行还在」的中间态被观察到。
- `workbench_plan_proposals` / `workbench_plan_versions` / `workbench_orchestration_proposals` 也按龄删
  （它们按 `task_id` / 租户挂靠，成批处理时与任务同轮，避免残留）。
- **审计口径**：`workbench_audit_events` 随任务级联删除 —— 用户已裁决接受；契约、手册与审计动作码说明里
  都要写「任务域事件流不保留」。

### 3.3 运行（`runs`）—— 先子后父（同一事务）
删除顺序（逐 run_id，或按 `(tenant_id, run_id)` 批量）：
`run_artifacts` → `run_acceptance_decisions` → `run_promotions` → `tool_actions` → `execution_idempotency` →
`runtime_states`（无外键，但属运行状态）→ `run_records`。
**不删** `runtime_events`（属 `events` 面，由全局 30 天清理器处理；在同一事务里删它会让两套清理互相看不清）。
`workbench_plan_proposals.run_id` 是**引用列**（无外键）⇒ 不置空也不删除（提案有自己的龄规则；若同轮按龄删除
则自然消失）。

### 3.4 触发与可观测
- **触发**：worker 周期任务 `app.worker.purge_expired_tenant_data`（beat 条目名 `retention-purge`，
  间隔 `WORKBENCH_RETENTION_PURGE_INTERVAL_SECONDS`，默认 3600、范围 30–604800，与既有清理任务同口径）。
- **逐租户**：按 `workbench_retention_policies` 有策略的租户逐个跑（无策略的租户 ⇒ **空转**，不默认套用
  `DEFAULT_RETENTION_POLICY`？**决定：套用默认**——真源 §6.3 给的是默认保留期；契约写明「未自定义的租户按默认策略清理」）。
- **审计**：每租户每轮写一条 `commercial.retention.purged`（新增动作码；明细只含受控值：
  各面删除行数与结转金额（整数分）、`cutoff`，**不含自由文本**）。
- **有界**：每轮每面设 `limit`（默认沿用既有清理器的量级，如 5000 行/轮），避免一次事务过大；剩余留给下一轮。
- **未接线返回零值**：与既有周期任务同口径（`_lifecycle_runner` 注入点复用或新开一个注入点；**决定：复用
  `_lifecycle_runner`**，因为删除原语归生命周期服务持有）。

## 4. 实施清单（步骤级）

1. **契约先行**（`docs/api-contract.md`）：
   - 新增「保留策略执行口径」段：五面语义（含 `events` 取更短者、`audit` 不删、`tasks` 级联审计、
     `usage` 结转行的 `reason`/`idempotency_key` 形态、`runs` 先子后父与其销毁面清单）、触发间隔配置、审计动作码、
     「未自定义策略按默认策略清理」；
   - `GET /api/v1/commercial/usage` 段补一句：明细中可能出现结转行（`reason='retention_carryover'`），累计不变。
2. **服务层**（`app/commercial/lifecycle.py`，与既有 `run_pending_jobs` 同文件同风格）：
   - `purge_expired_data_for_tenant(tenant_id, *, now=None) -> dict[str, int]`：读策略 → 依次结转账本、
     删运行域（先子后父）、删任务域 → 写审计 → 返回各面计数；
   - `purge_expired_data_across_tenants(*, now=None, limit_tenants=...) -> dict[str, int]`：遍历有策略租户
     （`RetentionPolicyStore` 增 `list_tenants()` 方法，内存 + PG 双实现）。
3. **存储方法**（只加「按龄删除」所需的最小面）：
   - `PostgresUsageLedger.carry_over_before(tenant_id, cutoff)`（插入结转行 + 删除过期明细，**同一事务**）+ 内存实现；
   - `PostgresRunRecordStore.purge_expired_for_tenant(tenant_id, cutoff, *, limit)`（**先子后父**，同一事务）+ 内存实现；
   - `PostgresTaskRepository.purge_expired_for_tenant(tenant_id, cutoff, *, limit)`（含「运行全部过期」谓词）+ 内存实现；
   - 提案域同理（`plan_proposals` / `plan_versions` / `orchestration_proposals`）。
4. **worker 装配**：`app/worker.py` 注册任务与 beat 条目；`app/main.py` 侧**不需要**（清理只在 worker 跑），
   但 `configure_runtime` 需注入上述存储（与既有 `lifecycle` 同一装配块）。
5. **settings**：`retention_purge_interval_seconds`（默认 3600、范围 30–604800）+ `.env.staging.example` /
   compose 注释同步（beat 与 worker 同值口径）。
6. **审计动作码**：`AuditAction.COMMERCIAL_RETENTION_PURGED`（`commercial.retention.purged`）+
   `ALLOWED_DETAIL_KEYS` 白名单键（`tasks_deleted` / `runs_deleted` / `usage_carried_cents` / `cutoff` 等受控键）
   + 前端 `AUDIT_ACTION_LABELS`（`tests/test_frontend_audit_labels.py` 守护两端一致）。
7. **测试（先红 → 绿）**：
   - 单元：结转恒等式（含「过期原行 + 新冲正行」的错位情形 ⇒ 总额仍逐分不变）；运行域先子后父（漏删子表必外键失败 ⇒ 红）；
     任务域「运行未过期则跳过」；`audit` 面**不删**；`events` 面不新建执行器；
   - 真库：上四类各一条（真库结转账本 + 真库先子后父删 + 真库任务跳过谓词）；
   - worker：任务未接线返回零值、装配注入断言（**静态钉住 `configure_runtime`**，沿用 2026-09-19 的教训）；
   - 反假：① 去掉先子后父 ⇒ 真库外键报错（红）；② 结转不写净额（只删行）⇒ 总额变（红）；
     ③ 任务谓词放宽（不检查运行）⇒ 孤儿运行用例红；④ 审计面误删 ⇒ 红。
8. **验收口径**：① 真机（worker + 测试库）跑一轮，逐面**查库计数**（本轮删除行数、结转行内容、SUM 前后相等）；
   ② 他租户零影响；③ 契约/手册/审计三处文本与实现对得上；④ 全量回归 + 前端套件。
9. **手册**：客户管理员手册「保留策略与审计」段由「本期为声明式、无执行器」改为**执行器口径**（含五面语义与
   「任务域事件流不保留」「运行域证据不保留」两句醒目提示）；员工手册无需改（用户不可见）。

## 5. 风险与边界（写进契约）

- **销毁性**：`runs` 面一旦执行，工具执行证据与验收决议**不可恢复**（用户已裁决接受）；因此
  `limit` 默认保守、每轮审计留痕、且**不提供**「立即全量清理」入口（只按龄、按轮次）。
- **窗口口径**：结转只保证**总额**不变；按时间窗的报表若依赖明细，窗口内数值会因结转而位移
  （契约写明「累计与总额口径不变；窗口口径以结转后明细为准」）。
- **不加迁移**：本批**预计零迁移**（`usage_ledger.reason/actor_id` 已存在；无需新列）。
  若实施中发现需要新列，按「迁移 + 回退演练」补做（口径同 044 演练）。
- **不在本批**：清场扩围（另案，见上条文档）；对象存储 / 向量 / 缓存。

## 6. 未验证（不得读成已验）

- 各面在**真实规模数据**上的耗时与锁影响未测（本机测试库接近空库）；
- 「运行未过期则跳过任务」这一谓词对**长跑任务**（运行持续时间 > 保留期）的影响未评估；
- 结转行在**导出包 `usage` 类别**里的呈现（当前导出为明细字段 `id/units/cost_cents/reversal_of/occurred_at`；
  结转行的 `reason` **不在字段集内** ⇒ 导出包里「结转行」与普通明细不可区分）——**需一并裁决**：
  A) 导出补 `reason`（字段口径变更）；B) 导出保持现状并在契约写明「不计 reason」。