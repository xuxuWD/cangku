# 商业化 PostgreSQL 持久化装配 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task with review checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让商业化租户、管理员、用量账本、生命周期作业和保留策略在 PostgreSQL 模式下持久化，并由启动装配自动选择正确实现。

**Architecture:** 保留开发环境的内存仓储，新增 PostgreSQL 租户/用量仓储和生命周期作业仓储。`CommercialLifecycleService` 通过小型协议依赖作业与保留策略存储，不再直接持有生产状态字典；`bootstrap.py` 使用同一连接池应用迁移并返回商业化组件，`main.py` 只消费装配结果。

**Tech Stack:** Python 3.11、dataclasses、FastAPI、psycopg/psycopg-pool、PostgreSQL、pytest。

---

## 文件边界

- `app/commercial/repository.py`：租户、工作区、客户管理员和用量 PostgreSQL 适配器；保留现有内存仓储。
- `app/commercial/lifecycle.py`：生命周期领域规则、内存作业存储和 PostgreSQL 作业/保留策略存储。
- `app/bootstrap.py`：商业化组件工厂，共享连接池并执行迁移。
- `app/main.py`：改为使用商业化工厂返回的组件，不直接实例化内存实现。
- `migrations/007_commercial_retention.sql`：租户保留策略持久化表。
- `tests/test_commercial_persistence.py`：PostgreSQL SQL、事务、租户条件和幂等契约。
- `tests/test_commercial_lifecycle.py`：生命周期服务使用可注入存储后的行为回归。
- `tests/test_persistence_contract.py`：商业化 bootstrap 选择和生产 fail-closed 契约。

---

### Task 1: 定义可注入的商业化存储边界

**Files:**
- Modify: `app/commercial/repository.py`
- Modify: `app/commercial/lifecycle.py`
- Modify: `tests/test_commercial_lifecycle.py`

- [ ] **Step 1: 写失败测试，固定生命周期存储注入行为**

在 `tests/test_commercial_lifecycle.py` 增加一个记录存储：

```python
def test_lifecycle_service_uses_injected_job_store():
    repository = InMemoryCommercialRepository()
    tenant = repository.create_tenant("客户 A", owner_id="owner-1")
    repository.add_customer_admin(tenant.id, "admin-1")
    jobs = InMemoryLifecycleJobStore()
    service = CommercialLifecycleService(repository, job_store=jobs)

    job = service.request_delete(Actor("admin-1", "customer_admin"), tenant.id)

    assert jobs.get(job.id).id == job.id
    assert service.get_job(job.id).tenant_id == tenant.id
```

- [ ] **Step 2: 运行测试确认红灯**

运行：

```powershell
python -m pytest tests/test_commercial_lifecycle.py::test_lifecycle_service_uses_injected_job_store -q
```

预期：因 `InMemoryLifecycleJobStore` 和 `job_store` 参数不存在而失败。

- [ ] **Step 3: 增加最小协议和内存实现**

在 `lifecycle.py` 增加 `LifecycleJobStore` 协议，包含 `create(job)`, `get(job_id)`, `save(job)`；增加 `InMemoryLifecycleJobStore`，内部用 `RLock` 保存 `dict[str, LifecycleJob]`。将 `CommercialLifecycleService.__init__` 改为接收 `job_store: LifecycleJobStore | None = None`，默认创建内存存储；`request_export`、`request_delete`、`mark_final_exported`、`execute_delete` 和 `get_job` 全部通过该存储读写。

- [ ] **Step 4: 运行生命周期回归**

运行：

```powershell
python -m pytest tests/test_commercial_lifecycle.py -q
```

预期：原有导出、删除冷静期、保留策略测试与新增注入测试全部通过。

- [ ] **Step 5: 提交领域存储边界**

```powershell
git add app/commercial/lifecycle.py tests/test_commercial_lifecycle.py
git commit -m "refactor: 注入商业化生命周期存储"
```

### Task 2: 完善 PostgreSQL 租户、管理员与用量仓储

**Files:**
- Modify: `app/commercial/repository.py`
- Modify: `tests/test_commercial_persistence.py`

- [ ] **Step 1: 写失败 SQL 契约测试**

增加 fake connection 测试，验证以下行为：

```python
def test_postgres_repository_reads_tenant_and_customer_admin_with_scope():
    connection = Connection([
        ("tenant-1", "客户 A", "owner-1", "active", None),
        ("tenant-1", "admin-1"),
    ])
    repository = PostgresCommercialRepository(connection)

    tenant = repository.get_tenant("tenant-1")
    assert tenant.id == "tenant-1"
    assert repository.is_customer_admin("tenant-1", "admin-1") is True
    assert all("tenant_id" in sql for sql, _ in connection.cursor_instance.statements)
```

再增加汇总测试，要求 `total` 和 `total_cost_cents` SQL 都带 `WHERE tenant_id = %s`，并增加重复追加返回已有记录的 fake cursor 场景。

- [ ] **Step 2: 运行测试确认缺失方法导致红灯**

运行：

```powershell
python -m pytest tests/test_commercial_persistence.py -q
```

预期：因 `get_tenant`、`is_customer_admin`、用量汇总等方法不存在而失败。

- [ ] **Step 3: 实现 PostgreSQL 租户与管理员读取**

在 `PostgresCommercialRepository` 增加：

```python
def get_tenant(self, tenant_id: str) -> Tenant: ...
def is_customer_admin(self, tenant_id: str, user_id: str) -> bool: ...
def get_workspace(self, tenant_id: str, workspace_id: str) -> Workspace: ...
def add_customer_admin(self, tenant_id: str, user_id: str) -> CustomerAdmin: ...
```

所有 SELECT/UPDATE/INSERT 均带 `tenant_id` 条件；不存在或跨租户统一抛出 `ResourceNotFound`。状态变更使用事务内条件 UPDATE，并根据受影响行数抛出领域冲突。

- [ ] **Step 4: 增加 PostgreSQL 用量仓储**

实现 `PostgresUsageLedger`，提供与 `InMemoryUsageLedger` 相同的 `append`, `total`, `total_cost_cents`, `reverse` 方法。`append` 使用 `ON CONFLICT (tenant_id, idempotency_key) DO NOTHING` 后回读原记录；`reverse` 只执行 INSERT...SELECT 负向记录并带 `tenant_id` 和 `reversal_of IS NULL` 条件；不提供更新原账本行的方法。

- [ ] **Step 5: 运行持久化测试**

运行：

```powershell
python -m pytest tests/test_commercial_persistence.py -q
```

预期：迁移、租户范围、管理员读取、用量幂等和冲正 SQL 测试全部通过。

- [ ] **Step 6: 提交 PostgreSQL 租户与用量适配器**

```powershell
git add app/commercial/repository.py tests/test_commercial_persistence.py
git commit -m "feat: 完善商业化 PostgreSQL 租户与用量仓储"
```

### Task 3: 持久化生命周期作业与保留策略

**Files:**
- Create: `migrations/007_commercial_retention.sql`
- Modify: `app/commercial/lifecycle.py`
- Modify: `tests/test_commercial_persistence.py`

- [ ] **Step 1: 写失败测试**

增加 fake connection 测试，验证 `PostgresLifecycleJobStore`：

- 创建导出作业写入 `workbench_lifecycle_jobs` 并在事务中返回作业。
- 按作业号读取时带 `tenant_id` 条件，找不到抛出 `ResourceNotFound`。
- 标记最终导出和完成删除使用条件 UPDATE。
- 保留策略写入 `workbench_retention_policies`，读取结果按租户隔离。

- [ ] **Step 2: 运行测试确认红灯**

运行：

```powershell
python -m pytest tests/test_commercial_persistence.py -q
```

预期：因迁移表和 `PostgresLifecycleJobStore` 尚不存在而失败。

- [ ] **Step 3: 增加保留策略迁移**

创建 `migrations/007_commercial_retention.sql`：

```sql
CREATE TABLE IF NOT EXISTS workbench_retention_policies (
    tenant_id TEXT PRIMARY KEY REFERENCES workbench_tenants(id),
    policy JSONB NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- [ ] **Step 4: 实现 PostgreSQL 生命周期作业存储**

增加 `PostgresLifecycleJobStore`，实现 `LifecycleJobStore` 协议和保留策略读写。数据库时间字段转换为 `datetime`，`final_exported` 根据作业状态或独立字段映射；若现有表缺少该字段，增加迁移中的兼容列并保持旧迁移可重复执行。所有作业查询和更新必须包含租户条件，状态更新使用事务和条件谓词。

- [ ] **Step 5: 扩展生命周期服务的保留策略依赖**

将保留策略字典抽象为 `RetentionPolicyStore`，开发环境使用内存实现，生产环境由 `PostgresLifecycleJobStore` 或配套存储实现。`set_retention` 继续拒绝空策略、非整数和小于 1 的值；`retention` 读取持久化值，不存在时返回现有默认值 `{ "tasks": 180, "audit": 730 }`。

- [ ] **Step 6: 运行生命周期与持久化回归**

运行：

```powershell
python -m pytest tests/test_commercial_lifecycle.py tests/test_commercial_persistence.py -q
```

预期：内存生命周期行为和 PostgreSQL fake SQL 契约全部通过。

- [ ] **Step 7: 提交生命周期持久化**

```powershell
git add migrations/007_commercial_retention.sql app/commercial/lifecycle.py tests/test_commercial_persistence.py
git commit -m "feat: 持久化商业化生命周期作业"
```

### Task 4: 增加商业化组件 bootstrap 并接入主应用

**Files:**
- Modify: `app/bootstrap.py`
- Modify: `app/main.py`
- Modify: `tests/test_persistence_contract.py`

- [ ] **Step 1: 写 bootstrap 失败测试**

增加：

```python
def test_commercial_bootstrap_selects_memory_in_development():
    repository, usage, lifecycle = build_commercial_components(
        Settings(env="development", storage_backend="memory")
    )
    assert isinstance(repository, InMemoryCommercialRepository)
    assert isinstance(usage, InMemoryUsageLedger)
    assert isinstance(lifecycle, CommercialLifecycleService)


def test_commercial_bootstrap_selects_postgres_in_production():
    settings = Settings(
        env="production", storage_backend="postgres",
        database_url="postgresql://localhost/workbench", auth_secret="x" * 32,
    )
    repository, usage, lifecycle = build_commercial_components(
        settings, connection=Connection(), migrate=False,
    )
    assert isinstance(repository, PostgresCommercialRepository)
    assert isinstance(usage, PostgresUsageLedger)
    assert isinstance(lifecycle.job_store, PostgresLifecycleJobStore)
```

- [ ] **Step 2: 运行测试确认工厂不存在**

运行：

```powershell
python -m pytest tests/test_persistence_contract.py::test_commercial_bootstrap_selects_memory_in_development -q
```

预期：因 `build_commercial_components` 未定义而失败。

- [ ] **Step 3: 实现 `build_commercial_components`**

在 `bootstrap.py` 增加工厂：

- `memory + development` 返回内存租户仓储、内存用量账本、注入内存作业存储的生命周期服务。
- `postgres` 创建或复用一个 `ConnectionPool`，执行 `apply_migrations`，返回 PostgreSQL 租户仓储、用量仓储和生命周期服务。
- 非开发环境若配置为 memory，抛出中文 `ValueError`，不静默回退。
- 支持 `connection` 和 `migrate=False` 注入以便契约测试。

- [ ] **Step 4: 修改主应用装配**

在 `app/main.py` 改为从 `build_commercial_components(settings)` 获取 `commercial_repository`、`commercial_usage`、`commercial_lifecycle`，删除对 `InMemoryCommercialRepository` 和 `InMemoryUsageLedger` 的直接实例化。保留 API 路由和测试使用的模块级变量名称，避免改变外部契约。

- [ ] **Step 5: 运行 API 与 bootstrap 回归**

运行：

```powershell
python -m pytest tests/test_persistence_contract.py tests/test_commercial_api.py tests/test_commercial_lifecycle.py -q
```

预期：开发环境 API 仍全部通过，生产配置下商业化组件不会使用内存实现。

- [ ] **Step 6: 提交装配接入**

```powershell
git add app/bootstrap.py app/main.py tests/test_persistence_contract.py
git commit -m "feat: 接入商业化 PostgreSQL 启动装配"
```

### Task 5: 全量验证与文档同步

**Files:**
- Modify: `docs/delivery-gates.md`
- Modify: `docs/private-deployment-runbook.md`
- Modify: `docs/api-contract.md` only if persistence behavior wording needs clarification

- [ ] **Step 1: 更新交付门禁**

只将“商业化 PostgreSQL 代码装配与契约测试”标记为完成；保留“真实 PostgreSQL、备份/恢复、staging 验收、压测和客户管理员验收”为未完成。

- [ ] **Step 2: 更新运行手册**

明确生产启动会自动应用 `migrations/001` 至 `007`，商业化租户、用量和生命周期作业不允许使用内存回退；真实数据库连接和恢复演练仍需单独验收。

- [ ] **Step 3: 执行完整验证**

运行：

```powershell
python -m pytest -q
python -m compileall -q app tests scripts/commercial_g0_preflight.py
git diff --check
```

预期：全部命令退出码为 0；不启动真实 PostgreSQL，不将 fake connection 测试描述为生产验收。

- [ ] **Step 4: 检查工作区并提交文档**

```powershell
git status --short --branch
git add docs/delivery-gates.md docs/private-deployment-runbook.md docs/api-contract.md
git commit -m "docs: 更新商业化持久化交付边界"
```

## 自检结果

- 设计中的租户、管理员、用量、生命周期、保留策略和 bootstrap 选择均有任务覆盖。
- 所有生产代码步骤都安排在对应失败测试之后。
- 真实 PostgreSQL、备份恢复和 staging 压测明确留在后续验收，不会被测试替代。
- 未引入在线支付、SaaS 自动开通或外部生产账号。
