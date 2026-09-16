import json
from datetime import UTC, datetime, timedelta

import pytest

from app.audit.models import AuditAction
from app.audit.redaction import has_sensitive_key
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.commercial.lifecycle import (
    EXPORT_PACKAGE_TTL,
    EXPORT_RESOURCE_CATEGORIES,
    UNIMPLEMENTED_EXPORT_CATEGORIES,
    CommercialLifecycleService,
    DeletionNotPending,
    ExportPackage,
    ExportPackageExpired,
    InMemoryExportPackageStore,
    InMemoryLifecycleJobStore,
    LifecycleJob,
)
from app.commercial.repository import InMemoryCommercialRepository, ResourceNotFound
from app.commercial.tenant import Actor, CommercialPolicyError, TenantStatus
from app.memory.embedding import FakeEmbeddingAdapter
from app.memory.service import MemoryService
from app.memory.store import InMemoryMemoryStore


def seeded_service(cooldown_days=7):
    repository = InMemoryCommercialRepository()
    tenant = repository.create_tenant("客户 A", owner_id="owner-1")
    repository.add_customer_admin(tenant.id, "admin-1")
    service = CommercialLifecycleService(
        repository,
        cooldown_days=cooldown_days,
        audit=AuditService(InMemoryAuditStore()),
    )
    return repository, tenant, service


def test_export_is_async_and_never_contains_secrets():
    repository, tenant, service = seeded_service()
    job = service.request_export(Actor("admin-1", "customer_admin"), tenant.id)

    assert job.status == "queued"
    payload = service.build_export_payload(tenant.id)
    assert "api_key" not in payload
    assert "cookie" not in payload


def test_delete_requires_cooldown_and_final_export():
    repository, tenant, service = seeded_service(cooldown_days=7)
    job = service.request_delete(Actor("admin-1", "customer_admin"), tenant.id)

    assert job.status == "cooling_down"
    with pytest.raises(CommercialPolicyError):
        service.execute_delete(tenant.id, now=job.execute_after)
    service.mark_final_exported(job.id)
    service.execute_delete(tenant.id, now=job.execute_after)
    assert service.tenant_status(tenant.id) == TenantStatus.DELETED


def test_retention_policy_has_positive_days_and_is_audited():
    repository, tenant, service = seeded_service()
    service.set_retention(tenant.id, {"tasks": 180, "audit": 730}, Actor("admin-1", "customer_admin"))
    assert service.retention(tenant.id)["tasks"] == 180
    with pytest.raises(CommercialPolicyError):
        service.set_retention(tenant.id, {"tasks": 0}, Actor("admin-1", "customer_admin"))


def test_lifecycle_service_uses_injected_job_store():
    repository = InMemoryCommercialRepository()
    tenant = repository.create_tenant("客户 A", owner_id="owner-1")
    repository.add_customer_admin(tenant.id, "admin-1")
    jobs = InMemoryLifecycleJobStore()
    service = CommercialLifecycleService(repository, job_store=jobs)

    job = service.request_delete(Actor("admin-1", "customer_admin"), tenant.id)

    assert jobs.get(job.id).id == job.id
    assert service.get_job(job.id).tenant_id == tenant.id


# ---------------------------------------------------------------------------
# E4：导出载荷落地（真源 commercial-g0-design.md §6.1 + api-contract.md:144）
# ---------------------------------------------------------------------------


def test_export_payload_lists_source_categories_as_metadata_only():
    """载荷结构必须与真源类别清单一致；无读取方法的类别一律为空数组（未实现）。"""
    repository, tenant, service = seeded_service()

    payload = service.build_export_payload(tenant.id)
    resources = payload["resources"]

    assert set(resources) == set(EXPORT_RESOURCE_CATEGORIES)
    # 商业化服务未持有任何跨模块读取通道 ⇒ 每一类**未实现**，必须是空数组（不臆造数据）。
    for category in EXPORT_RESOURCE_CATEGORIES:
        assert resources[category] == [], f"{category} 未实现，必须为空数组"
    assert set(payload["unimplemented_categories"]) == set(UNIMPLEMENTED_EXPORT_CATEGORIES)
    assert set(UNIMPLEMENTED_EXPORT_CATEGORIES) == set(EXPORT_RESOURCE_CATEGORIES)


def test_export_payload_never_contains_secrets_or_original_content():
    """逐条断言：载荷数据面不含密码/Cookie/验证码/令牌/原始密钥/客户原文。"""
    repository, tenant, service = seeded_service()

    payload = service.build_export_payload(tenant.id)
    # 数据面（resources）序列化后不得出现任何敏感词元。
    resources_text = json.dumps(payload["resources"], ensure_ascii=False).lower()
    for forbidden in ("password", "cookie", "验证码", "token", "api key", "api_key", "客户原文"):
        assert forbidden not in resources_text
    # 递归：全载荷不得出现敏感键名。
    from app.audit.redaction import has_sensitive_key

    assert has_sensitive_key(payload) is False
    # 顶层不得出现凭据类键。
    for key in ("password", "cookie", "token", "api_key", "verification_code"):
        assert key not in payload


def test_export_package_lands_with_explicit_expiry():
    """载荷写入新表；expires_at 由调用方显式给出（真源未给时长，不自造默认）。"""
    repository, tenant, service = seeded_service()
    expires_at = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

    package = service.store_export_package(tenant.id, "job-1", expires_at=expires_at)

    stored = service.export_store.get(package.id, tenant_id=tenant.id)
    assert stored.tenant_id == tenant.id
    assert stored.job_id == "job-1"
    assert stored.expires_at == expires_at
    assert stored.payload["tenant_id"] == tenant.id
    assert stored.payload["resources"]["users"] == []
    with pytest.raises(ResourceNotFound):
        service.export_store.get(package.id, tenant_id="other-tenant")


# ---------------------------------------------------------------------------
# E4：保留策略接线（真源 commercial-g0-design.md:118）
# ---------------------------------------------------------------------------


def test_retention_defaults_match_source_three_tiers():
    """默认值必须与真源三档一致：任务/运行 180、事件/用量 365、审计 730。"""
    repository, tenant, service = seeded_service()

    assert service.retention(tenant.id) == {"tasks": 180, "events": 365, "usage": 365, "audit": 730}


def test_set_retention_persists_and_writes_audit():
    """保留策略写入 DB（服务侧口径）且**写入审计**（真源 :118）。"""
    repository, tenant, service = seeded_service()

    service.set_retention(
        tenant.id,
        {"tasks": 90, "events": 365, "usage": 365, "audit": 730},
        Actor("admin-1", "customer_admin"),
    )

    assert service.retention(tenant.id)["tasks"] == 90
    records = service.audit.store.list_recent(tenant.id)
    assert [record.action for record in records] == [AuditAction.COMMERCIAL_RETENTION_UPDATED]
    assert records[0].actor_id == "admin-1"
    assert records[0].target_type == "retention_policy"


def test_set_retention_fails_closed_without_audit_channel():
    """没有审计通道就拒绝变更，绝不静默跳过审计。"""
    repository = InMemoryCommercialRepository()
    tenant = repository.create_tenant("客户 A", owner_id="owner-1")
    repository.add_customer_admin(tenant.id, "admin-1")
    service = CommercialLifecycleService(repository)

    with pytest.raises(CommercialPolicyError):
        service.set_retention(tenant.id, {"tasks": 90}, Actor("admin-1", "customer_admin"))


# ---------------------------------------------------------------------------
# E2/E3：worker 执行层（导出落库 / 删除执行 / 撤销）
# ---------------------------------------------------------------------------


class _RecordingExportStore(InMemoryExportPackageStore):
    """记录写入的导出包，供断言 payload 与过期时刻。"""

    def __init__(self):
        super().__init__()
        self.saved: list = []

    def save(self, package):  # type: ignore[override]
        self.saved.append(package)
        return super().save(package)


def worker_service(cooldown_days=7):
    repository = InMemoryCommercialRepository()
    tenant = repository.create_tenant("客户 A", owner_id="owner-1")
    repository.add_customer_admin(tenant.id, "admin-1")
    exports = _RecordingExportStore()
    service = CommercialLifecycleService(
        repository,
        cooldown_days=cooldown_days,
        export_store=exports,
        audit=AuditService(InMemoryAuditStore()),
    )
    return repository, tenant, service, exports


def test_export_package_ttl_ruling_is_seven_days():
    assert EXPORT_PACKAGE_TTL == timedelta(days=7)


def test_worker_completes_export_and_lands_package_with_seven_day_expiry():
    repository, tenant, service, exports = worker_service()
    now = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
    job = service.request_export(Actor("admin-1", "customer_admin"), tenant.id)

    counts = service.run_pending_jobs(now=now)

    assert counts == {"exports": 1, "deletions": 0}
    assert service.get_job(job.id).status == "completed"
    package = exports.saved[0]
    # 裁决 2：expires_at = created_at + 7 天（断言到天）。
    assert package.created_at == now
    assert package.expires_at == now + timedelta(days=7)
    assert (package.expires_at.date() - package.created_at.date()).days == 7
    # 脱敏 + 类别结构为空数组（裁决 3：数据面本期不建）。
    assert has_sensitive_key(package.payload) is False
    assert package.payload["resources"]["users"] == []
    # 数据面（resources）序列化后不得出现任何敏感词元（redaction 列是「排除声明」不是数据）。
    text = json.dumps(package.payload["resources"], ensure_ascii=False).lower()
    for forbidden in ("password", "cookie", "token", "api_key", "客户原文"):
        assert forbidden not in text


def test_worker_export_is_idempotent():
    repository, tenant, service, exports = worker_service()
    job = service.request_export(Actor("admin-1", "customer_admin"), tenant.id)
    service.run_pending_jobs(now=datetime(2026, 9, 14, tzinfo=UTC))

    counts = service.run_pending_jobs(now=datetime(2026, 9, 15, tzinfo=UTC))

    assert counts == {"exports": 0, "deletions": 0}
    assert service.get_job(job.id).status == "completed"
    assert len(exports.saved) == 1  # 不重复落库


def test_final_export_marks_first_export_after_delete_request_only():
    """裁决 4：删除申请之前完成的不置；之后首次完成置；再次完成不重复置。"""
    repository, tenant, service, _ = worker_service()
    actor = Actor("admin-1", "customer_admin")
    now = datetime(2026, 9, 14, tzinfo=UTC)
    # 删除申请之前完成的导出 ⇒ 不置 final_exported
    service.request_export(actor, tenant.id)
    service.run_pending_jobs(now=now)
    delete_job = service.request_delete(actor, tenant.id)
    assert service.get_job(delete_job.id).final_exported is False
    # 删除申请之后首次完成 ⇒ 置
    service.request_export(actor, tenant.id)
    service.run_pending_jobs(now=now)
    assert service.get_job(delete_job.id).final_exported is True
    # 之后再次完成 ⇒ 不重复置（mark_final_exported 不再被调用）
    calls: list[str] = []
    original = service.mark_final_exported

    def spy(job_id):
        calls.append(job_id)
        return original(job_id)

    service.mark_final_exported = spy  # type: ignore[method-assign]
    service.request_export(actor, tenant.id)
    service.run_pending_jobs(now=now)
    assert calls == []
    assert service.get_job(delete_job.id).final_exported is True


def test_worker_does_not_delete_before_cooldown():
    repository, tenant, service, _ = worker_service(cooldown_days=7)
    actor = Actor("admin-1", "customer_admin")
    delete_job = service.request_delete(actor, tenant.id)
    service.request_export(actor, tenant.id)

    service.run_pending_jobs(now=delete_job.execute_after - timedelta(seconds=1))

    assert service.get_job(delete_job.id).final_exported is True
    assert service.tenant_status(tenant.id) == TenantStatus.DELETING


def test_worker_does_not_delete_without_final_export():
    repository, tenant, service, _ = worker_service(cooldown_days=7)
    actor = Actor("admin-1", "customer_admin")
    delete_job = service.request_delete(actor, tenant.id)

    counts = service.run_pending_jobs(now=delete_job.execute_after)

    assert counts["deletions"] == 0
    assert service.tenant_status(tenant.id) == TenantStatus.DELETING
    actions = [record.action for record in service.audit.store.list_recent(tenant.id)]
    assert AuditAction.COMMERCIAL_DELETION_EXECUTED not in actions


def test_worker_deletes_after_cooldown_and_final_export_with_audit():
    repository, tenant, service, _ = worker_service(cooldown_days=7)
    actor = Actor("admin-1", "customer_admin")
    delete_job = service.request_delete(actor, tenant.id)
    service.request_export(actor, tenant.id)

    counts = service.run_pending_jobs(now=delete_job.execute_after)

    assert counts == {"exports": 1, "deletions": 1}
    assert service.tenant_status(tenant.id) == TenantStatus.DELETED
    assert service.get_job(delete_job.id).status == "completed"
    records = service.audit.store.list_recent(tenant.id)
    executed = [r for r in records if r.action == AuditAction.COMMERCIAL_DELETION_EXECUTED]
    assert len(executed) == 1
    assert executed[0].target_type == "tenant"
    assert executed[0].target_id == tenant.id


def test_delete_execution_fails_closed_without_audit_channel():
    repository = InMemoryCommercialRepository()
    tenant = repository.create_tenant("客户 A", owner_id="owner-1")
    repository.add_customer_admin(tenant.id, "admin-1")
    service = CommercialLifecycleService(repository)
    actor = Actor("admin-1", "customer_admin")
    delete_job = service.request_delete(actor, tenant.id)
    service.mark_final_exported(delete_job.id)

    with pytest.raises(CommercialPolicyError, match="审计"):
        service.execute_delete(tenant.id, now=delete_job.execute_after)


def test_cancel_delete_returns_tenant_to_active_and_blocks_worker():
    """裁决 5：撤销后租户回 ACTIVE，且后续 worker 不再执行删除。"""
    repository, tenant, service, _ = worker_service(cooldown_days=7)
    actor = Actor("owner-1", "customer_admin")
    delete_job = service.request_delete(actor, tenant.id)

    cancelled = service.cancel_delete(actor, tenant.id)

    assert cancelled.status == "cancelled"
    assert service.tenant_status(tenant.id) == TenantStatus.ACTIVE
    counts = service.run_pending_jobs(now=delete_job.execute_after)
    assert counts["deletions"] == 0
    assert service.tenant_status(tenant.id) == TenantStatus.ACTIVE


def test_cancel_delete_goes_through_state_machine(monkeypatch):
    from app.commercial import lifecycle as lifecycle_module

    repository, tenant, service, _ = worker_service(cooldown_days=7)
    actor = Actor("owner-1", "customer_admin")
    service.request_delete(actor, tenant.id)
    seen: list[TenantStatus] = []
    real = lifecycle_module.transition_tenant

    def spy(tenant_obj, target, spy_actor):
        seen.append(target)
        return real(tenant_obj, target, spy_actor)

    monkeypatch.setattr(lifecycle_module, "transition_tenant", spy)

    service.cancel_delete(actor, tenant.id)

    # 断言：撤销经 `transition_tenant`（状态机）而非直接改状态字段。
    assert seen == [TenantStatus.ACTIVE]


def test_cancel_without_pending_delete_raises():
    repository, tenant, service, _ = worker_service()

    with pytest.raises(DeletionNotPending):
        service.cancel_delete(Actor("owner-1", "customer_admin"), tenant.id)


# ---------------------------------------------------------------------------
# E2+E3 真库演练暴露：list_for_tenant 排序确定性 + execute_delete 走状态机
# （内存实现；PG 实现见 tests/test_commercial_lifecycle_postgres.py 门控用例）
# ---------------------------------------------------------------------------


def test_list_for_tenant_orders_deterministically_by_time_then_id():
    """插入顺序与时间顺序不一致时，仍按 (requested_at, id) 升序返回（与 list_pending 同口径）。"""
    store = InMemoryLifecycleJobStore()
    newer = LifecycleJob(
        tenant_id="tenant-ord", kind="delete", status="cooling_down", requested_by="admin-1",
        requested_at=datetime(2026, 9, 12, 10, 0, tzinfo=UTC), id="job-newer",
    )
    older = LifecycleJob(
        tenant_id="tenant-ord", kind="delete", status="cooling_down", requested_by="admin-1",
        requested_at=datetime(2026, 9, 10, 10, 0, tzinfo=UTC), id="job-older",
    )
    # 故意先插入时间更晚的 ⇒ 插入顺序 != 时间顺序
    store.create(newer)
    store.create(older)

    listed = store.list_for_tenant("tenant-ord", kind="delete")

    assert [job.id for job in listed] == ["job-older", "job-newer"]


def test_list_for_tenant_breaks_same_timestamp_ties_by_id():
    """同刻多行：以 id 作稳定次级键 ⇒ 顺序仍确定（不依赖插入/物理行序）。"""
    store = InMemoryLifecycleJobStore()
    same = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    store.create(LifecycleJob(
        tenant_id="tenant-tie", kind="delete", status="cooling_down", requested_by="admin-1",
        requested_at=same, id="job-b",
    ))
    store.create(LifecycleJob(
        tenant_id="tenant-tie", kind="delete", status="cooling_down", requested_by="admin-1",
        requested_at=same, id="job-a",
    ))

    listed = store.list_for_tenant("tenant-tie", kind="delete")

    assert [job.id for job in listed] == ["job-a", "job-b"]


def test_execute_delete_targets_most_recent_delete_job():
    """同租户多条删除作业时，执行的是「最近」那条（显式取最新，不依赖行序）。"""
    repository, tenant, service = seeded_service(cooldown_days=7)
    tenant.status = TenantStatus.DELETING  # 测试造景：租户已进入冷静期（等价 request_delete 的效果）
    newer = LifecycleJob(
        tenant_id=tenant.id, kind="delete", status="cooling_down", requested_by="admin-1",
        requested_at=datetime(2026, 9, 12, 8, 0, tzinfo=UTC),
        execute_after=datetime(2026, 9, 13, 8, 0, tzinfo=UTC), final_exported=True, id="job-newer",
    )
    older = LifecycleJob(
        tenant_id=tenant.id, kind="delete", status="cooling_down", requested_by="admin-1",
        requested_at=datetime(2026, 9, 10, 8, 0, tzinfo=UTC),
        execute_after=datetime(2026, 9, 11, 8, 0, tzinfo=UTC), final_exported=True, id="job-older",
    )
    service.job_store.create(newer)  # 先插入时间更晚的 ⇒ 插入顺序 != 时间顺序
    service.job_store.create(older)

    service.execute_delete(tenant.id, now=datetime(2026, 9, 14, 8, 0, tzinfo=UTC))

    assert service.get_job("job-newer").status == "completed"
    assert service.get_job("job-older").status == "cooling_down"
    assert service.tenant_status(tenant.id) == TenantStatus.DELETED


def test_execute_delete_goes_through_state_machine(monkeypatch):
    from app.commercial import lifecycle as lifecycle_module

    repository, tenant, service = seeded_service(cooldown_days=7)
    actor = Actor("admin-1", "customer_admin")
    job = service.request_delete(actor, tenant.id)
    service.mark_final_exported(job.id)
    seen: list[TenantStatus] = []
    real = lifecycle_module.transition_tenant

    def spy(tenant_obj, target, spy_actor):
        seen.append(target)
        return real(tenant_obj, target, spy_actor)

    monkeypatch.setattr(lifecycle_module, "transition_tenant", spy)

    service.execute_delete(tenant.id, now=job.execute_after)

    # 断言：删除执行经 `transition_tenant`（状态机）而非直接改状态字段。
    assert seen == [TenantStatus.DELETED]


# ---------------------------------------------------------------------------
# N2：P3 记忆层生命周期接线（注入 memory_store 后导出含 memories、删除物理清场）
# 口径：docs/superpowers/specs/2026-09-15-memory-layer-p3-design.md §4 N2
# ---------------------------------------------------------------------------


def _service_with_memory_store(cooldown_days=7):
    """构造注入了 InMemoryMemoryStore 的生命周期服务，返回 (repo, tenant, service, memory_store)。"""
    repository = InMemoryCommercialRepository()
    tenant = repository.create_tenant("客户 A", owner_id="owner-1")
    repository.add_customer_admin(tenant.id, "admin-1")
    memory_store = InMemoryMemoryStore()
    service = CommercialLifecycleService(
        repository,
        cooldown_days=cooldown_days,
        memory_store=memory_store,
        audit=AuditService(InMemoryAuditStore()),
    )
    return repository, tenant, service, memory_store


def test_export_payload_includes_memories_when_store_injected():
    """注入 memory_store 后：导出载荷的 memories 类别含实际数据，且该类别移出 unimplemented。"""
    from app.domain import UserContext

    repository, tenant, service, memory_store = _service_with_memory_store()
    svc = MemoryService(memory_store, FakeEmbeddingAdapter(), audit=AuditService(InMemoryAuditStore()))
    actor = UserContext(tenant.id, "u-1", "super_admin")
    svc.create_fact(
        actor, content="客户偏好邮件沟通", scope="user",
        owner_kind="user", owner_id="u-1", idempotency_key="lc-export-1",
    )

    payload = service.build_export_payload(tenant.id)

    memories = payload["resources"]["memories"]
    assert len(memories) == 1
    assert memories[0]["content"] == "客户偏好邮件沟通"
    assert memories[0]["scope"] == "user"
    assert "memories" not in payload["unimplemented_categories"]
    # 其余类别保持未实现（不臆造数据）。
    assert set(payload["resources"].keys()) == set(EXPORT_RESOURCE_CATEGORIES)
    assert "users" in payload["unimplemented_categories"]


def test_execute_delete_purges_memories_when_store_injected():
    """删除执行后：租户记忆被物理清场（list_all_for_tenant 返回空），且其它租户数据不受影响。"""
    from app.domain import UserContext

    repository, tenant, service, memory_store = _service_with_memory_store(cooldown_days=1)
    svc = MemoryService(memory_store, FakeEmbeddingAdapter())
    actor = UserContext(tenant.id, "u-1", "super_admin")
    svc.create_fact(
        actor, content="待清场记忆", scope="user",
        owner_kind="user", owner_id="u-1", idempotency_key="lc-purge-1",
    )
    # 另一个租户的数据必须保留（隔离）。
    other_tenant = repository.create_tenant("客户 B", owner_id="owner-2")
    svc.create_fact(
        UserContext(other_tenant.id, "u-9", "super_admin"),
        content="别的租户记忆", scope="user",
        owner_kind="user", owner_id="u-9", idempotency_key="lc-other-1",
    )

    delete_job = service.request_delete(Actor("admin-1", "customer_admin"), tenant.id)
    service.mark_final_exported(delete_job.id)
    service.execute_delete(tenant.id, now=delete_job.execute_after + timedelta(seconds=1))

    assert service.tenant_status(tenant.id) == TenantStatus.DELETED
    assert memory_store.list_all_for_tenant(tenant.id) == []
    # 其它租户不受牵连。
    assert len(memory_store.list_all_for_tenant(other_tenant.id)) == 1


# ---------------------------------------------------------------------------
# 组 10.7 加固（2026-09-16 用户拍板，两项都做）：
#   ① 导出包**取回**（admin-only + 租户归属 + 过期拒绝）；② 过期包**物理清理**。
# 口径：docs/api-contract.md「GET /api/v1/commercial/exports/{package_id}」。
# 背景：改造前 `POST /commercial/exports` 只落库、**无取回端点**（设计验收要求「申请并下载」，
# docs/superpowers/specs/2026-09-06-commercial-g0-design.md:173），且过期包无清理路径
# ⇒ 表 `workbench_export_packages` 只增不减（含租户数据副本，宪法九章）。
# ---------------------------------------------------------------------------


def _completed_package(service, exports, actor, tenant_id: str, *, now: datetime) -> object:
    """请求导出 → worker 完成 → 返回落库的导出包（过期时刻 = now + 7 天）。"""
    service.request_export(actor, tenant_id)
    service.run_pending_jobs(now=now)
    return exports.saved[-1]


def test_get_export_package_returns_redacted_payload_for_admin():
    repository, tenant, service, exports = worker_service()
    actor = Actor("admin-1", "customer_admin")
    now = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
    package = _completed_package(service, exports, actor, tenant.id, now=now)

    fetched = service.get_export_package(actor, tenant.id, package.id, now=now + timedelta(days=6))

    assert fetched.id == package.id
    assert fetched.tenant_id == tenant.id
    assert fetched.payload["tenant_id"] == tenant.id
    assert has_sensitive_key(fetched.payload) is False


def test_get_export_package_rejects_employee_and_cross_tenant():
    """普通员工 403（服务层 PolicyError）；他租户管理员对同包取回 ⇒ 404（不泄露存在性）。"""
    repository, tenant, service, exports = worker_service()
    other = repository.create_tenant("客户 B", owner_id="owner-2")
    repository.add_customer_admin(other.id, "admin-2")
    actor = Actor("admin-1", "customer_admin")
    now = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
    package = _completed_package(service, exports, actor, tenant.id, now=now)

    with pytest.raises(CommercialPolicyError):
        service.get_export_package(Actor("emp-1", "employee"), tenant.id, package.id, now=now)
    with pytest.raises(ResourceNotFound):
        service.get_export_package(Actor("admin-2", "customer_admin"), other.id, package.id, now=now)


def test_get_export_package_expiry_boundary_is_inclusive():
    """过期判定 `expires_at <= now`：早 1 秒可取，正点即过期（边界钉住，不靠"大约过了期"）。"""
    repository, tenant, service, exports = worker_service()
    actor = Actor("admin-1", "customer_admin")
    now = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
    package = _completed_package(service, exports, actor, tenant.id, now=now)
    assert package.expires_at == now + timedelta(days=7)

    with pytest.raises(ExportPackageExpired):
        service.get_export_package(actor, tenant.id, package.id, now=package.expires_at)
    available = service.get_export_package(
        actor, tenant.id, package.id, now=package.expires_at - timedelta(seconds=1)
    )
    assert available.id == package.id


def test_get_export_package_is_not_found_for_unknown_id():
    repository, tenant, service, _ = worker_service()

    with pytest.raises(ResourceNotFound):
        service.get_export_package(
            Actor("admin-1", "customer_admin"), tenant.id, "export-missing",
            now=datetime(2026, 9, 14, 8, 0, tzinfo=UTC),
        )


def test_purge_expired_export_packages_removes_only_expired():
    """清理只删 `expires_at <= now` 的行（正点即过期）；未过期包与生命周期作业不受影响。"""
    repository, tenant, service, exports = worker_service()
    actor = Actor("admin-1", "customer_admin")
    now = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
    package = _completed_package(service, exports, actor, tenant.id, now=now)

    # 未到期：一条也不删（`now` 早于 expires_at）。
    assert service.purge_expired_export_packages(now=package.expires_at - timedelta(seconds=1)) == 0
    assert service.export_store.get(package.id, tenant_id=tenant.id).id == package.id

    # 正点：过期即清（物理删除 ⇒ 取回 404 同「不存在」）。
    assert service.purge_expired_export_packages(now=package.expires_at) == 1
    with pytest.raises(ResourceNotFound):
        service.export_store.get(package.id)
    # 作业记录不随之删除（导出作业本身是生命周期事实，非数据副本）。
    assert service.get_job(package.job_id).status == "completed"


def test_in_memory_export_store_purge_is_scoped_to_expiry_and_keeps_others():
    """存储层直测：只删过期行、返回删除条数（内存实现与 PG 实现同语义）。"""
    store = InMemoryExportPackageStore()
    now = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
    expired = ExportPackage(tenant_id="t-1", payload={"tenant_id": "t-1"}, expires_at=now, id="export-old")
    fresh = ExportPackage(
        tenant_id="t-1", payload={"tenant_id": "t-1"},
        expires_at=now + timedelta(seconds=1), id="export-fresh",
    )
    store.save(expired)
    store.save(fresh)

    assert store.purge_expired(now=now) == 1
    assert store.get(fresh.id).id == fresh.id
    with pytest.raises(ResourceNotFound):
        store.get(expired.id)
