# 私有部署商业化 G0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为内部版和客户私有部署版建立可交付的租户、客户管理员、套餐额度、用量账本、数据生命周期和升级回滚基础能力，并保持未来 SaaS 复用同一套 API 契约。

**Architecture:** 继续由 FastAPI 控制平面作为唯一事实源，新增 `app/commercial/` 管理租户、套餐、用量和数据生命周期；客户端不直连数据库。开发环境使用内存实现验证行为，生产环境通过 PostgreSQL 迁移和仓储实现；导出、删除、备份和恢复以异步任务/运维命令为边界，不在请求线程执行大批量数据处理。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、PostgreSQL、psycopg、pytest；现有 Redis/Celery 用于后续异步执行，G0 先提供可注入任务接口和确定性内存实现。

---

## 文件边界

- `app/commercial/tenant.py`：租户、工作区、客户管理员和状态机。
- `app/commercial/plan.py`：套餐、额度策略和版本化配置。
- `app/commercial/usage.py`：追加式用量账本、幂等和冲正。
- `app/commercial/lifecycle.py`：导出、冷静期删除、保留策略和审计。
- `app/commercial/service.py`：组合领域服务，不直接处理 HTTP。
- `app/commercial/repository.py`：内存与 PostgreSQL 仓储协议。
- `migrations/006_commercial_g0.sql`：租户、套餐、用量、生命周期表和索引。
- `app/main.py`：只增加版本化 API 路由和身份校验接线。
- `tests/test_commercial_*.py`：每个领域行为的测试。
- `docs/api-contract.md`、`docs/delivery-gates.md`、`docs/private-deployment-runbook.md`：契约和交付文档。

不修改 GEO 仓库，不复制外部 Harness，不把 SaaS 在线支付放进 G0。

## Task 1：租户、工作区与客户管理员状态机

**Files:**
- Create: `app/commercial/__init__.py`
- Create: `app/commercial/tenant.py`
- Create: `app/commercial/repository.py`
- Create: `tests/test_commercial_tenant.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_tenant_state_transitions_require_authorized_actor():
    tenants = InMemoryCommercialRepository()
    tenant = tenants.create_tenant("客户 A", owner_id="owner-1")
    assert tenant.status == TenantStatus.TRIAL
    tenants.activate_tenant(tenant.id, actor=Actor("owner-1", "super_admin"))
    assert tenants.get_tenant(tenant.id).status == TenantStatus.ACTIVE
    with pytest.raises(CommercialPolicyError):
        tenants.suspend_tenant(tenant.id, actor=Actor("employee-1", "employee"))


def test_resources_are_scoped_to_tenant_and_workspace():
    tenants = InMemoryCommercialRepository()
    first = tenants.create_workspace("客户 A", "工作区 1")
    second = tenants.create_workspace("客户 B", "工作区 1")
    assert first.tenant_id != second.tenant_id
    with pytest.raises(ResourceNotFound):
        tenants.get_workspace(second.tenant_id, first.id)
```

- [ ] **Step 2: Run `python -m pytest tests/test_commercial_tenant.py -q` and confirm import failure.**
- [ ] **Step 3: Implement `TenantStatus`, `Actor`, `Tenant`, `Workspace`, `CustomerAdmin` and `InMemoryCommercialRepository`.** 状态只能按 `trial → active → suspended → exporting/deleting → deleted` 合法转换；跨租户读取统一抛出 `ResourceNotFound`。
- [ ] **Step 4: Run focused tests and `python -m pytest tests/test_control_plane.py tests/test_knowledge_policy.py -q`; expected PASS.**
- [ ] **Step 5: Commit `feat: 增加私有部署租户与客户管理员模型`。**

## Task 2：套餐、额度检查与追加式用量账本

**Files:**
- Create: `app/commercial/plan.py`
- Create: `app/commercial/usage.py`
- Create: `tests/test_commercial_usage.py`

- [ ] **Step 1: Write failing tests.**

```python
def test_usage_is_idempotent_and_corrections_are_reversals():
    ledger = InMemoryUsageLedger()
    entry = ledger.append(UsageEntry(idempotency_key="run-1", tenant_id="t1", units=10, cost_cents=50))
    assert ledger.append(entry) == entry
    correction = ledger.reverse(entry.id, reason="供应商回调重复", actor_id="admin-1")
    assert correction.reversal_of == entry.id
    assert ledger.total("t1") == 0


def test_quota_policy_blocks_or_requires_approval_when_exceeded():
    plan = PlanVersion("pro-private", limits={"task_runs": 2, "model_cost_cents": 100})
    quota = QuotaService(plan)
    quota.consume("task_runs", 2)
    assert quota.check("task_runs", 1).action == "block"
    quota.set_overage_policy("model_cost_cents", "approval")
    assert quota.check("model_cost_cents", 101).action == "approval"
```

- [ ] **Step 2: Run `python -m pytest tests/test_commercial_usage.py -q`; expected import failure.**
- [ ] **Step 3: Implement immutable `PlanVersion`, `QuotaService`, `UsageEntry` and `InMemoryUsageLedger`.** 账本只追加；同一幂等键返回原记录；冲正新增负向记录；额度结果只允许 `allow`、`degrade`、`approval`、`block`。
- [ ] **Step 4: Run focused tests and existing model gateway tests; expected PASS.**
- [ ] **Step 5: Commit `feat: 增加套餐额度与用量账本`。**

## Task 3：PostgreSQL 持久化与迁移

**Files:**
- Create: `migrations/006_commercial_g0.sql`
- Modify: `app/commercial/repository.py`
- Create: `tests/test_commercial_persistence.py`
- Modify: `app/migrations.py` only if migration metadata requires it

- [ ] **Step 1: Write fake-connection tests** verifying SQL includes tenant predicates, unique usage idempotency, append-only reversal, and indexes on tenant/status and tenant/occurred_at.
- [ ] **Step 2: Run `python -m pytest tests/test_commercial_persistence.py -q`; expected failure because tables and repository methods are absent.**
- [ ] **Step 3: Add tables:** `workbench_tenants`, `workbench_workspaces`, `workbench_customer_admins`, `workbench_plan_versions`, `workbench_usage_ledger`, `workbench_lifecycle_jobs`; every table has `tenant_id`, timestamps, and restrictive foreign keys. `workbench_usage_ledger` has a unique `(tenant_id, idempotency_key)` and no update API.
- [ ] **Step 4: Implement `PostgresCommercialRepository` with transaction-scoped create, state transition, append usage, reversal, and lifecycle job methods.** Every query includes tenant scope; cross-tenant misses return `ResourceNotFound`.
- [ ] **Step 5: Run `python -m pytest tests/test_commercial_persistence.py tests/test_persistence_contract.py -q`; expected PASS.**
- [ ] **Step 6: Commit `feat: 持久化商业化 G0 数据模型`。**

## Task 4：导出、删除、保留策略与审计

**Files:**
- Create: `app/commercial/lifecycle.py`
- Create: `app/commercial/service.py`
- Create: `tests/test_commercial_lifecycle.py`

- [ ] **Step 1: Write failing tests.**

```python
def test_export_is_async_and_never_contains_secrets():
    service = CommercialLifecycleService(InMemoryCommercialRepository())
    job = service.request_export(Actor("admin-1", "customer_admin"), tenant_id="t1")
    assert job.status == "queued"
    payload = service.build_export_payload("t1")
    assert "api_key" not in payload
    assert "cookie" not in payload


def test_delete_requires_cooldown_and_final_export():
    service = CommercialLifecycleService(InMemoryCommercialRepository(), cooldown_days=7)
    job = service.request_delete(Actor("admin-1", "customer_admin"), "t1")
    assert job.status == "cooling_down"
    with pytest.raises(CommercialPolicyError):
        service.execute_delete("t1", now=job.requested_at)
    service.mark_final_exported(job.id)
    service.execute_delete("t1", now=job.execute_after)
    assert service.tenant_status("t1") == TenantStatus.DELETED
```

- [ ] **Step 2: Run `python -m pytest tests/test_commercial_lifecycle.py -q`; expected import failure.**
- [ ] **Step 3: Implement export jobs, deletion cooldown, retention policy and redacted lifecycle audit.** 导出只包含租户内元数据、产物引用、用量和审计；删除清理业务数据、对象索引和缓存，保留最小删除审计，不保留客户原文。
- [ ] **Step 4: Run lifecycle, security and full backend tests; expected PASS.**
- [ ] **Step 5: Commit `feat: 增加租户数据导出删除与保留策略`。**

## Task 5：FastAPI 商业化接口

**Files:**
- Modify: `app/main.py`
- Create: `tests/test_commercial_api.py`
- Modify: `docs/api-contract.md`

- [ ] **Step 1: Write failing API tests** for customer-admin-only tenant summary, plan/usage view, export request, delete request, and cross-tenant 404. Client payload must not be able to set `tenant_id`, quota result, lifecycle status, or billing cost.
- [ ] **Step 2: Run `python -m pytest tests/test_commercial_api.py -q`; expected 404 for routes.**
- [ ] **Step 3: Add Pydantic request/response models and routes:**
  - `GET /api/v1/commercial/tenant`
  - `GET /api/v1/commercial/usage`
  - `POST /api/v1/commercial/exports`
  - `POST /api/v1/commercial/deletion-requests`
  - `GET /api/v1/commercial/lifecycle/{job_id}`
  All routes derive tenant from authenticated context and return Chinese business errors.
- [ ] **Step 4: Run API, control-plane and persistence tests; expected PASS.**
- [ ] **Step 5: Update API contract with no-online-payment statement and commit `feat: 暴露商业化 G0 管理接口`。**

## Task 6：私有部署交付、备份恢复与发布门禁

**Files:**
- Create: `docs/private-deployment-runbook.md`
- Create: `scripts/commercial_g0_preflight.py`
- Create: `tests/test_commercial_preflight.py`
- Modify: `docs/delivery-gates.md`

- [ ] **Step 1: Write failing preflight tests** for missing database URL, missing backup key, migration drift, absent retention policy, and unpinned Runtime versions.
- [ ] **Step 2: Run `python -m pytest tests/test_commercial_preflight.py -q`; expected import failure.**
- [ ] **Step 3: Implement preflight checks** that return structured `pass/fail/blocked` results and never print secret values. Add runbook sections for backup before migration, restore into isolated database, smoke test, rollback, customer handoff, and support escalation.
- [ ] **Step 4: Run:**

```powershell
python -m pytest tests -q
python -m compileall -q app tests scripts/commercial_g0_preflight.py
python scripts/commercial_g0_preflight.py --example
git diff --check
```

Expected: all tests pass; preflight example fails closed with actionable Chinese reasons when required production variables are absent.
- [ ] **Step 5: Update delivery gates:** mark only tested capabilities complete; keep real staging database, backup/restore, real login, capacity and customer Pilot unchecked. Commit `docs: 增加私有部署 G0 交付门禁`。

## 自检与验收顺序

1. 先完成 Task 1-2，证明租户隔离、额度和账本行为。
2. 完成 Task 3 后，才允许在 staging 数据库验证持久化。
3. 完成 Task 4-5 后，才允许客户管理员通过 API 申请导出/删除。
4. 完成 Task 6 后，才允许安排第一个内部版 Pilot。

规格覆盖检查：租户/工作区/客户管理员、套餐、用量、冲正、导出、删除、保留、备份、恢复、升级、回滚、许可证和威胁模型均有任务覆盖；SaaS 在线支付明确不在 G0。

禁止项：不提交 `.env`、原始密钥、Cookie、客户原文、浏览器会话或外部 Harness 源码；不把内部测试通过描述为客户生产可用。
