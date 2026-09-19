"""B-2（2026-09-19）导出读取器：字段口径 / 租户隔离 / 上限与截断 / 失败如实标注 / 统一脱敏。

判据来源：
  - `docs/api-contract.md`「私有部署商业化 G0」导出段（字段口径、上限与三类如实标注）；
  - `app/commercial/export_readers.py`（读者契约：`(rows, total)`、无状态、不跨租户）。

本文件用**真实内存存储**（workforce / knowledge / audit / run records）而不是假对象：
读的是读者与上游「按租户列出」方法的真实签名契合度，假对象测不出签名漂移。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.accounts.models import Account, AccountStatus  # noqa: F401
from app.accounts.repository import InMemoryAccountRepository
from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.commercial.export_readers import (
    account_export_reader,
    artifact_export_reader,
    audit_export_reader,
    build_export_readers,
    knowledge_document_export_reader,
    memory_export_reader,
    run_export_reader,
    step_export_reader,
    task_export_reader,
    usage_export_reader,
    workforce_agent_export_reader,
    workforce_role_export_reader,
)
from app.commercial.lifecycle import EXPORT_RESOURCE_CATEGORIES, CommercialLifecycleService
from app.commercial.repository import InMemoryCommercialRepository
from app.commercial.usage import InMemoryUsageLedger, UsageEntry
from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.knowledge_governance.models import KnowledgeDoc, KnowledgeDocStatus
from app.knowledge_governance.store import InMemoryKnowledgeGovStore
from app.runtime.artifacts import InMemoryRunArtifactStore
from app.runtime.contracts import AgentPlan, RuntimeContext
from app.runtime.records import InMemoryRunRecordStore, RunRecord
from app.runtime.state import RuntimeStateStore
from app.tool_execution.file_ops import FileChange
from app.workforce.store import InMemoryWorkforceDirectoryStore

TENANT = "t-export"
OTHER = "t-export-other"

ROLE_FIELDS = {"role_key", "name", "description", "status", "created_by", "created_at", "updated_at"}
AGENT_FIELDS = {"agent_key", "role_key", "name", "description", "status", "created_by", "created_at", "updated_at"}
DOCUMENT_FIELDS = {
    "document_id",
    "title",
    "owner_id",
    "status",
    "version",
    "source_key",
    "registered_by",
    "last_reviewed_at",
    "review_due_at",
    "created_at",
    "updated_at",
}
AUDIT_FIELDS = {"record_id", "action", "actor_id", "target_type", "target_id", "phone_masked", "detail", "occurred_at"}
RUN_FIELDS = {
    "run_id",
    "task_id",
    "proposal_id",
    "runtime_key",
    "status",
    "step_count",
    "completed_step_count",
    "tool_calls",
    "successful_tools",
    "knowledge_hits",
    "latency_ms",
    "started_at",
    "finished_at",
    "finish_reason",
}
# `memories` 三类（2026-09-19 整层口径）：事实沿用既有字段并**新增 `kind` 判别**；
# 规则 = 事实字段 + `rule_key` / `version`；身份类画像 = 自身的 KV 字段（无状态列）。
MEMORY_FACT_FIELDS = {"kind", "memory_id", "scope", "status", "content", "created_at"}
MEMORY_RULE_FIELDS = MEMORY_FACT_FIELDS | {"rule_key", "version"}
MEMORY_PROFILE_FIELDS = {"kind", "owner_kind", "owner_id", "profile_key", "value", "updated_at"}


def _ctx(tenant_id: str, role: str = "super_admin", user: str = "admin-1") -> UserContext:
    return UserContext(tenant_id=tenant_id, user_id=user, role=role)


def _seed_service(**kwargs) -> CommercialLifecycleService:
    repository = InMemoryCommercialRepository()
    # 固定 ID 的租户（`create_tenant` 会自动生成 id，导出读者断言需要可预期的租户号）。
    repository.ensure_test_tenant(TENANT, owner_id="owner-1", admins={"admin-1"})
    repository.ensure_test_tenant(OTHER, owner_id="owner-2", admins={"admin-9"})
    return CommercialLifecycleService(repository, **kwargs)


def _workforce(roles: int = 1) -> InMemoryWorkforceDirectoryStore:
    store = InMemoryWorkforceDirectoryStore()
    for index in range(roles):
        store.create_role(
            _ctx(TENANT), role_key=f"content-operator-{index}", name=f"内容运营 {index}", description="负责选题"
        )
    store.create_role(_ctx(OTHER), role_key="other-role", name="他租户岗位")
    store.create_employee(_ctx(TENANT), agent_key="writer-1", name="写作助手", role_key="content-operator-0")
    store.create_employee(_ctx(OTHER), agent_key="other-agent", name="他租户员工", role_key="other-role")
    return store


def _doc(document_id: str, tenant_id: str = TENANT) -> KnowledgeDoc:
    return KnowledgeDoc(
        tenant_id=tenant_id,
        document_id=document_id,
        title=f"文档 {document_id}",
        owner_id="owner-1",
        status=KnowledgeDocStatus.DRAFT,
        version="v1",
        source_key="weknora",
        registered_by="admin-1",
    )


def _record(run_id: str, *, tenant_id: str = TENANT, day: int = 1) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        tenant_id=tenant_id,
        task_id="task-1",
        runtime_key="mock",
        status="completed",
        started_at=datetime(2026, 9, day, 8, 0, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# 读者：字段口径与租户隔离
# ---------------------------------------------------------------------------


def test_role_reader_exports_directory_fields_of_own_tenant_only():
    reader = workforce_role_export_reader(_workforce())

    rows, total = reader(TENANT, limit=50)

    assert total == 1
    assert rows[0]["role_key"] == "content-operator-0"
    assert set(rows[0]) == ROLE_FIELDS
    assert "tenant_id" not in rows[0]


def test_agent_reader_carries_no_config_or_pg_default_value_columns():
    """数字员工只导出目录字段：配置列在 PG 列表读模型里会回落默认值（导出自洽性优先）。"""
    reader = workforce_agent_export_reader(_workforce())

    rows, total = reader(TENANT, limit=50)

    assert total == 1 and rows[0]["agent_key"] == "writer-1"
    assert set(rows[0]) == AGENT_FIELDS
    for forbidden in ("system_prompt", "model_key", "tool_allowlist", "memory_policy", "autonomy_level", "daily_budget_cents"):
        assert forbidden not in rows[0]


def test_knowledge_document_reader_scopes_tenant_and_reports_total_before_slicing():
    store = InMemoryKnowledgeGovStore()
    for index in range(3):
        store.register_document(_ctx(TENANT), doc=_doc(f"doc-{index}"))
    store.register_document(_ctx(OTHER), doc=_doc("doc-other", tenant_id=OTHER))
    reader = knowledge_document_export_reader(store)

    rows, total = reader(TENANT, limit=2)

    assert total == 3  # 总数如实：切片不改变「共多少」
    assert len(rows) == 2
    assert {row["document_id"] for row in rows} <= {"doc-0", "doc-1", "doc-2"}
    assert set(rows[0]) == DOCUMENT_FIELDS


def test_audit_reader_pages_and_uses_store_total():
    audit = AuditService(InMemoryAuditStore())
    for index in range(3):
        audit.record(
            AuditAction.ACCOUNT_LOGIN_SUCCEEDED,
            tenant_id=TENANT,
            actor_id="admin-1",
            target_type="account",
            target_id=f"acc-{index}",
        )
    audit.record(AuditAction.ACCOUNT_LOGIN_SUCCEEDED, tenant_id=OTHER, actor_id="admin-9", target_id="acc-other")
    reader = audit_export_reader(audit)

    rows, total = reader(TENANT, limit=2)

    assert total == 3
    assert len(rows) == 2
    assert all(row["target_id"] != "acc-other" for row in rows)
    assert set(rows[0]) == AUDIT_FIELDS


def test_run_reader_reports_tenant_count_and_newest_first():
    store = InMemoryRunRecordStore()
    for index in range(3):
        store.upsert(_record(f"run-{index}", day=1 + index))
    store.upsert(_record("run-other", tenant_id=OTHER))
    reader = run_export_reader(store)

    rows, total = reader(TENANT, limit=2)

    assert total == 3
    assert [row["run_id"] for row in rows] == ["run-2", "run-1"]  # 最近在前（day 3 → day 2）
    assert set(rows[0]) == RUN_FIELDS
    assert "execution_authorization" not in rows[0]


def test_memory_reader_covers_three_kinds_with_discriminator():
    """`memories` 读**整层三类**（事实 / 规则 / 身份类画像），行内以 `kind` 判别。

    2026-09-19：此前只读事实（`list_all_for_tenant`）⇒ 真源 §6.1「记忆」导出不完整。
    本用例用**真实内存存储**（真签名契合度，假对象测不出漂移），三类各两行：
    """
    from app.memory.embedding import FakeEmbeddingAdapter
    from app.memory.service import MemoryService
    from app.memory.store import InMemoryMemoryStore

    store = InMemoryMemoryStore()
    service = MemoryService(store, FakeEmbeddingAdapter())
    actor = _ctx(TENANT)
    for index in range(2):
        service.create_fact(actor, content=f"事实{index}", scope="user", owner_kind="user",
                            owner_id="admin-1", idempotency_key=f"exp-fact-{index}")
        service.create_rule(actor, rule_key=f"rule-{index}", content=f"规则{index}",
                            scope="user", owner_kind="user", owner_id="admin-1")
        service.set_profile_key(actor, key=f"key-{index}", value=f"值{index}",
                                owner_kind="user", owner_id="admin-1")
    other = InMemoryMemoryStore()
    MemoryService(other, FakeEmbeddingAdapter()).create_fact(
        _ctx(OTHER), content="别的租户", scope="user", owner_kind="user",
        owner_id="admin-9", idempotency_key="exp-other-1")

    reader = memory_export_reader(store)

    rows, total = reader(TENANT, limit=100)
    kinds = [row["kind"] for row in rows]
    assert kinds == ["fact", "fact", "rule", "rule", "profile", "profile"]  # 分组顺序确定
    assert total == 6
    # 三类行**字段集各不相同**（判别字段 + 各自字段）；组内顺序只断言「稳定」而不赌内容顺序。
    assert set(rows[0]) == MEMORY_FACT_FIELDS
    assert set(rows[2]) == MEMORY_RULE_FIELDS
    assert set(rows[4]) == MEMORY_PROFILE_FIELDS
    assert {row["content"] for row in rows[:2]} == {"事实0", "事实1"}
    assert {row["rule_key"] for row in rows[2:4]} == {"rule-0", "rule-1"}
    # 画像按 `(owner_kind, owner_id, profile_key)` 排序 ⇒ 键序是确定的。
    assert [row["profile_key"] for row in rows[4:]] == ["key-0", "key-1"]
    assert rows[4]["value"] == "值0"
    assert all("别的租户" != row.get("content") for row in rows)  # 不跨租户
    assert reader(TENANT, limit=100)[0] == rows  # 同一份数据两次读取结果逐字相同（顺序稳定）

    # 上限切片按**合并后的整层列表**生效，总数仍是三类之和（不拿返回条数冒充）。
    sliced, total_all = reader(TENANT, limit=4)
    assert [row["kind"] for row in sliced] == ["fact", "fact", "rule", "rule"]
    assert total_all == 6


# ---------------------------------------------------------------------------
# 装配：只接有能力的上游
# ---------------------------------------------------------------------------


def test_build_readers_wires_only_available_sources():
    readers = build_export_readers(workforce=_workforce())

    assert set(readers) == {"roles", "agents"}
    assert build_export_readers() == {}


def test_build_readers_skips_run_store_without_count_capability():
    """只有「最近 N 条」而没有计数的上游**不接**：宁缺，也不导出无法声明完整性的残缺列表。"""

    class _NoCount:
        def list_recent(self, tenant_id: str, *, limit: int):
            return []

    assert "runs" not in build_export_readers(runs=_NoCount())


# ---------------------------------------------------------------------------
# 服务层：载荷填充 / 上限截断 / 失败如实标注 / 统一脱敏
# ---------------------------------------------------------------------------


def test_payload_fills_wired_categories_and_keeps_others_unimplemented():
    service = _seed_service(export_readers=build_export_readers(workforce=_workforce()))

    payload = service.build_export_payload(TENANT)

    assert [row["role_key"] for row in payload["resources"]["roles"]] == ["content-operator-0"]
    assert payload["resources"]["agents"][0]["agent_key"] == "writer-1"
    assert "roles" not in payload["unimplemented_categories"]
    assert "agents" not in payload["unimplemented_categories"]
    assert "users" in payload["unimplemented_categories"]  # 未接的类别如实标注
    assert set(payload["resources"]) == set(EXPORT_RESOURCE_CATEGORIES)  # 未接类别仍是空数组
    assert payload["unavailable_categories"] == []
    assert payload["truncated_categories"] == {}


def test_rows_over_cap_are_declared_in_truncated_categories():
    service = _seed_service(
        export_readers=build_export_readers(workforce=_workforce(roles=3)),
        export_category_max_rows=2,
    )

    payload = service.build_export_payload(TENANT)

    assert len(payload["resources"]["roles"]) == 2
    # 不静默截断：取了多少 / 共多少都要给出来。
    assert payload["truncated_categories"] == {"roles": {"exported": 2, "total": 3}}


def test_reader_failure_is_declared_and_does_not_poison_other_categories():
    def boom(tenant_id: str, *, limit: int):  # noqa: ARG001
        raise RuntimeError("上游读取失败")

    service = _seed_service(
        export_readers={"roles": boom, "agents": workforce_agent_export_reader(_workforce())}
    )

    payload = service.build_export_payload(TENANT)

    assert "roles" not in payload["resources"]  # 读不到 ≠ 没有：不冒充空数组
    assert payload["unavailable_categories"] == ["roles"]
    assert "roles" not in payload["unimplemented_categories"]  # 它已接线，只是这次读不到
    assert payload["resources"]["agents"][0]["agent_key"] == "writer-1"  # 其余类别照常


def test_exported_texts_go_through_the_shared_redactor():
    store = InMemoryWorkforceDirectoryStore()
    store.create_role(
        _ctx(TENANT),
        role_key="role-secret",
        name="岗位",
        description="应急联系：api_key: sk-abcdef123456",
    )
    service = _seed_service(export_readers=build_export_readers(workforce=store))

    payload = service.build_export_payload(TENANT)

    description = payload["resources"]["roles"][0]["description"]
    assert "sk-abcdef123456" not in description
    assert "[已隐藏]" in description


def test_unknown_reader_category_is_ignored():
    service = _seed_service(
        export_readers={"not_a_category": lambda tenant_id, *, limit: ([{"x": 1}], 1)}  # noqa: ARG005
    )

    payload = service.build_export_payload(TENANT)

    assert "not_a_category" not in payload["resources"]
    assert "not_a_category" not in payload["unimplemented_categories"]


# ---------------------------------------------------------------------------
# B-2b（2026-09-19）：tasks / users / usage 三类接线
# ---------------------------------------------------------------------------

TASK_FIELDS = {"task_id", "project_id", "created_by", "employee_key", "title", "risk_level", "budget", "status"}
USER_FIELDS = {
    "account_id",
    "phone_masked",
    "position",
    "full_name",
    "email",
    "role",
    "status",
    "requested_at",
    "reviewed_at",
    "reviewed_by",
}
USAGE_FIELDS = {"id", "units", "cost_cents", "reversal_of", "occurred_at"}


def _memory_only_store():
    """真实内存记忆仓储（三类各一行）——**不用假对象**：读者现在读三张表，假对象测不出签名漂移。"""
    from app.memory.embedding import FakeEmbeddingAdapter
    from app.memory.service import MemoryService
    from app.memory.store import InMemoryMemoryStore

    store = InMemoryMemoryStore()
    service = MemoryService(store, FakeEmbeddingAdapter())
    actor = _ctx(TENANT)
    service.create_fact(actor, content="记住了：周五发周报", scope="user",
                        owner_kind="user", owner_id="admin-1", idempotency_key="exp-only-1")
    service.create_rule(actor, rule_key="exp-rule", content="先结论后背景",
                        scope="user", owner_kind="user", owner_id="admin-1")
    service.set_profile_key(actor, key="language", value="中文",
                            owner_kind="user", owner_id="admin-1")
    return store


def _knowledge_store() -> InMemoryKnowledgeGovStore:
    store = InMemoryKnowledgeGovStore()
    store.register_document(_ctx(TENANT), doc=_doc("doc-0"))
    return store


def _audit_service() -> AuditService:
    audit = AuditService(InMemoryAuditStore())
    audit.record(AuditAction.ACCOUNT_LOGIN_SUCCEEDED, tenant_id=TENANT, actor_id="admin-1", target_id="acc-0")
    return audit


def _run_store() -> InMemoryRunRecordStore:
    store = InMemoryRunRecordStore()
    store.upsert(_record("run-0"))
    return store


def _task_store() -> TaskStore:
    store = TaskStore()
    for index in range(2):
        store._tasks[f"task-{index}"] = _task(f"task-{index}", tenant_id=TENANT)
    store._tasks["task-other"] = _task("task-other", tenant_id=OTHER)
    return store


def _task(task_id: str, *, tenant_id: str) -> Task:
    return Task(
        tenant_id=tenant_id,
        project_id="p-1",
        created_by="u-1",
        employee_key="content-writer",
        title="周报整理",
        risk_level=RiskLevel.LOW,
        budget=5.0,
        idempotency_key=f"idem-{task_id}",
        request_fingerprint="fingerprint",
        status=TaskStatus.QUEUED,
        id=task_id,
    )


def _accounts() -> InMemoryAccountRepository:
    repository = InMemoryAccountRepository()
    account = repository.add(
        Account(phone="13800000001", password_hash="scrypt$salt$hash", position="内容运营", full_name="张三")
    )
    repository.mark_approved(account.account_id, role="employee", tenant_id=TENANT, reviewed_by="admin-1")
    other = repository.add(
        Account(phone="13800000002", password_hash="scrypt$salt$hash", position="岗位", full_name="李四")
    )
    repository.mark_approved(other.account_id, role="employee", tenant_id=OTHER, reviewed_by="admin-9")
    repository.add(Account(phone="13800000003", password_hash="scrypt$salt$hash", position="待审", full_name="王五"))
    return repository


def _usage_ledger() -> InMemoryUsageLedger:
    ledger = InMemoryUsageLedger()
    ledger.append(UsageEntry(idempotency_key="run-1", tenant_id=TENANT, units=10, cost_cents=50))
    ledger.append(UsageEntry(idempotency_key="run-2", tenant_id=TENANT, units=5, cost_cents=25))
    ledger.append(UsageEntry(idempotency_key="run-other", tenant_id=OTHER, units=99, cost_cents=990))
    return ledger


def test_task_reader_scopes_tenant_and_never_exports_internal_keys():
    reader = task_export_reader(_task_store())

    rows, total = reader(TENANT, limit=1)

    assert total == 2  # 计数按租户（他租户不计）
    assert len(rows) == 1
    assert set(rows[0]) == TASK_FIELDS
    for forbidden in ("idempotency_key", "request_fingerprint", "tenant_id"):
        assert forbidden not in rows[0]


def test_user_reader_masks_phone_and_drops_credential_columns():
    reader = account_export_reader(_accounts())

    rows, total = reader(TENANT, limit=10)

    assert total == 1  # 他租户与未审批账号都不出
    assert rows[0]["role"] == "employee"
    assert set(rows[0]) == USER_FIELDS
    assert rows[0]["phone_masked"] == "138****0001"
    for forbidden in ("password_hash", "totp_secret", "sso_subject", "phone", "email_verified"):
        assert forbidden not in rows[0]


def test_usage_reader_scopes_tenant_and_counts_entries():
    reader = usage_export_reader(_usage_ledger())

    rows, total = reader(TENANT, limit=1)

    assert total == 2 and len(rows) == 1
    assert set(rows[0]) == USAGE_FIELDS
    assert "idempotency_key" not in rows[0]  # 幂等键是内部去重键，不进包


def test_build_readers_covers_tasks_users_usage_and_memories_defaults():
    readers = build_export_readers(
        accounts=_accounts(), tasks=_task_store(), usage=_usage_ledger()
    )

    assert set(readers) == {"tasks", "users", "usage"}


def test_payload_fills_three_new_categories_and_shrinks_unimplemented():
    service = _seed_service(
        export_readers=build_export_readers(
            accounts=_accounts(), tasks=_task_store(), usage=_usage_ledger()
        )
    )

    payload = service.build_export_payload(TENANT)

    assert {row["task_id"] for row in payload["resources"]["tasks"]} == {"task-0", "task-1"}
    assert [row["role"] for row in payload["resources"]["users"]] == ["employee"]
    assert len(payload["resources"]["usage"]) == 2
    for category in ("tasks", "users", "usage"):
        assert category not in payload["unimplemented_categories"]
    assert payload["truncated_categories"] == {}
    assert payload["unavailable_categories"] == []


# ---------------------------------------------------------------------------
# B-2c（2026-09-19）：artifacts / steps 两类接线
# ---------------------------------------------------------------------------

ARTIFACT_FIELDS = {
    "run_id",
    "artifact_id",
    "virtual_path",
    "change_kind",
    "bytes",
    "sha256",
    "created_at",
    "expires_at",
}
STEP_FIELDS = {"run_id", "step_id", "kind", "tool", "requires_approval", "completed"}


def _file_change(index: int, kind: str = "created") -> FileChange:
    return FileChange(
        virtual_path=f"/workspace/{index}.txt",
        change_kind=kind,
        bytes=10 + index,
        sha256=f"sha256:{index:064d}",
    )


def _artifact_store() -> InMemoryRunArtifactStore:
    store = InMemoryRunArtifactStore(retention_days=30)
    store.register(TENANT, "run-own", [_file_change(0)])
    store.register(OTHER, "run-other", [_file_change(1)])
    # 一行已过期（保留期为负 ⇒ `expires_at` 落在过去）：与运行产物端点同口径，**不入包、不计入总数**。
    store.register(TENANT, "run-own", [_file_change(9)], now=datetime.now(UTC) - timedelta(days=40))
    return store


def _state_store() -> RuntimeStateStore:
    store = RuntimeStateStore()
    context = RuntimeContext(
        TENANT, "u-1", "content-operator", "craft", "p-1", "task-1", "dev-1",
        ("kb-1",), ("/ws",), 100, "low", "policy-1", datetime(2026, 9, 30, tzinfo=UTC),
    )
    state = store.create(
        context,
        AgentPlan.from_steps(
            [
                {"step_id": "s1", "kind": "read", "tool": "knowledge.search"},
                {"step_id": "s2", "kind": "write", "tool": "file.write"},
            ]
        ),
        run_id="run-own",
    )
    state.completed_steps.append("s1")
    store.create(
        RuntimeContext(
            OTHER, "u-2", "content-operator", "craft", "p-2", "task-2", "dev-2",
            ("kb-1",), ("/ws",), 100, "low", "policy-1", datetime(2026, 9, 30, tzinfo=UTC),
        ),
        AgentPlan.from_steps([{"step_id": "s-other", "kind": "read", "tool": "knowledge.search"}]),
        run_id="run-other",
    )
    return store


def test_artifact_reader_scopes_tenant_and_keeps_run_context():
    reader = artifact_export_reader(_artifact_store())

    rows, total = reader(TENANT, limit=10)

    assert total == 1  # 过期行不计入总数（保留期外不算可读数据）
    assert rows[0]["virtual_path"] == "/workspace/0.txt"
    assert rows[0]["run_id"] == "run-own"  # 租户级导出必须能看出产物属于哪个运行
    assert set(rows[0]) == ARTIFACT_FIELDS
    assert "tenant_id" not in rows[0]


def test_step_reader_expands_plan_steps_with_completion_and_scopes_tenant():
    reader = step_export_reader(_state_store())

    rows, total = reader(TENANT, limit=10)

    assert total == 2  # 每个计划步骤一行；他租户状态不计
    assert {row["step_id"] for row in rows} == {"s1", "s2"}
    assert all(row["run_id"] == "run-own" for row in rows)
    completed = {row["step_id"]: row["completed"] for row in rows}
    assert completed == {"s1": True, "s2": False}
    assert set(rows[0]) == STEP_FIELDS

    page, same_total = reader(TENANT, limit=1)

    assert same_total == 2 and len(page) == 1


def test_build_readers_covers_artifacts_and_steps():
    readers = build_export_readers(artifacts=_artifact_store(), steps=_state_store())

    assert set(readers) == {"artifacts", "steps"}


def test_payload_fills_artifacts_and_steps_and_leaves_entity_gaps_unimplemented():
    """全部可用上游都接上时：11 类出真实行，只剩「无实体可读」的 4 类未实现。"""
    service = _seed_service(
        export_readers=build_export_readers(
            memory_store=_memory_only_store(),
            workforce=_workforce(),
            knowledge=_knowledge_store(),
            audits=_audit_service(),
            runs=_run_store(),
            accounts=_accounts(),
            tasks=_task_store(),
            usage=_usage_ledger(),
            artifacts=_artifact_store(),
            steps=_state_store(),
        )
    )

    payload = service.build_export_payload(TENANT)

    assert [row["virtual_path"] for row in payload["resources"]["artifacts"]] == ["/workspace/0.txt"]
    assert {row["step_id"] for row in payload["resources"]["steps"]} == {"s1", "s2"}
    # 只剩「无实体可读」的四类：不造数据，如实标注未实现。
    assert payload["unimplemented_categories"] == [
        "approvals",
        "growth_proposals",
        "knowledge_references",
        "knowledge_versions",
    ]
    # 未实现 ≠ 读不到：两者分列，且本次没有任何读取失败。
    assert payload["unavailable_categories"] == []