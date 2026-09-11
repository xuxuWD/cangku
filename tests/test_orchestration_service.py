import pytest

from app.audit.models import ALLOWED_DETAIL_KEYS, AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import PolicyError, UserContext
from app.orchestration.models import (
    OrchestrationProposalKind,
    OrchestrationProposalNotFound,
    OrchestrationProposalStateConflict,
    OrchestrationProposalStatus,
)
from app.orchestration.service import OrchestrationProposalService
from app.orchestration.store import InMemoryOrchestrationProposalStore

CEO_ONE = UserContext("t-1", "ceo-1", "ceo")
CEO_TWO = UserContext("t-1", "ceo-2", "ceo")
EMPLOYEE = UserContext("t-1", "u-1", "employee")


def runtime(key: str, *, run_count: int, completion: float, tools: float = 1.0) -> dict[str, object]:
    return {
        "runtime_key": key,
        "run_count": run_count,
        "task_completion_rate": completion,
        "tool_success_rate": tools,
        "knowledge_hit_rate": 0.0,
        "latency_p95_ms": 100,
    }


class StubMetrics:
    def __init__(self, by_runtime: list[dict[str, object]]) -> None:
        self.by_runtime = by_runtime
        self.calls: list[tuple[str, str | None]] = []

    def summary(self, tenant_id: str, *, runtime_key: str | None = None) -> dict[str, object]:
        self.calls.append((tenant_id, runtime_key))
        return {"tenant_id": tenant_id, "runtime_key": runtime_key, "by_runtime": self.by_runtime}


def build(
    by_runtime: list[dict[str, object]],
    *,
    default: str = "mock",
    min_samples: int = 2,
    threshold: float = 0.1,
) -> tuple[OrchestrationProposalService, InMemoryOrchestrationProposalStore, InMemoryAuditStore]:
    store = InMemoryOrchestrationProposalStore()
    audit_store = InMemoryAuditStore()
    service = OrchestrationProposalService(
        store,
        metrics=StubMetrics(by_runtime),
        audit=AuditService(audit_store),
        default_runtime_key=default,
        min_samples=min_samples,
        improvement_threshold=threshold,
    )
    return service, store, audit_store


def test_generate_rejects_unsupported_kind() -> None:
    service, _store, _audit = build([runtime("mock", run_count=10, completion=0.5)])

    with pytest.raises(ValueError, match="优化提案类型"):
        service.generate(CEO_ONE, kind="other")


def test_generate_returns_none_when_fewer_than_two_qualified_runtimes() -> None:
    service, store, _audit = build(
        [
            runtime("mock", run_count=10, completion=0.5),
            runtime("agentscope", run_count=1, completion=0.9),
        ]
    )

    proposal, reason = service.generate(CEO_ONE)

    assert proposal is None
    assert "运行时不足" in reason
    assert "2" in reason
    assert store.list_for_tenant("t-1", limit=10) == []


def test_generate_returns_none_when_default_is_already_best() -> None:
    service, _store, _audit = build(
        [
            runtime("mock", run_count=10, completion=0.9),
            runtime("agentscope", run_count=10, completion=0.5),
        ]
    )

    proposal, reason = service.generate(CEO_ONE)

    assert proposal is None
    assert "已是表现最好" in reason


def test_generate_returns_none_when_default_has_insufficient_samples() -> None:
    service, _store, _audit = build(
        [
            runtime("mock", run_count=1, completion=0.5),
            runtime("agentscope", run_count=10, completion=0.95),
            runtime("hermes", run_count=10, completion=0.8),
        ]
    )

    proposal, reason = service.generate(CEO_ONE)

    assert proposal is None
    assert "样本不足" in reason


def test_generate_returns_none_when_improvement_below_threshold() -> None:
    service, _store, _audit = build(
        [
            runtime("mock", run_count=10, completion=0.80),
            runtime("agentscope", run_count=10, completion=0.85),
        ],
        threshold=0.1,
    )

    proposal, reason = service.generate(CEO_ONE)

    assert proposal is None
    assert "阈值" in reason


def test_generate_creates_proposal_with_whitelisted_snapshot() -> None:
    service, store, audit_store = build(
        [
            runtime("mock", run_count=10, completion=0.60),
            runtime("agentscope", run_count=10, completion=0.90),
        ]
    )

    proposal, reason = service.generate(CEO_ONE)

    assert proposal is not None
    assert proposal.kind is OrchestrationProposalKind.RUNTIME_DEFAULT
    assert proposal.current_value == "mock"
    assert proposal.proposed_value == "agentscope"
    assert proposal.status is OrchestrationProposalStatus.PENDING_REVIEW
    assert proposal.created_by == "ceo-1"
    assert "0.90" in proposal.rationale
    assert "0.60" in proposal.rationale
    assert "10" in proposal.rationale
    assert proposal.rationale == reason
    assert store.get("t-1", proposal.proposal_id) is proposal

    assert set(proposal.metrics_snapshot) == {"current", "proposed"}
    for entry in proposal.metrics_snapshot.values():
        assert set(entry) <= {
            "runtime_key",
            "run_count",
            "task_completion_rate",
            "tool_success_rate",
            "knowledge_hit_rate",
            "latency_p95_ms",
        }

    actions = [record.action for record in audit_store.list_recent(None, limit=100)]
    assert AuditAction.ORCHESTRATION_PROPOSED in actions


def test_generate_is_idempotent_for_pending_proposal() -> None:
    service, store, _audit = build(
        [
            runtime("mock", run_count=10, completion=0.60),
            runtime("agentscope", run_count=10, completion=0.90),
        ]
    )

    first, _ = service.generate(CEO_ONE)
    second, reason = service.generate(CEO_ONE)

    assert first is not None and second is not None
    assert first.proposal_id == second.proposal_id
    assert len(store.list_for_tenant("t-1", limit=10)) == 1
    assert reason == first.rationale


def test_generate_is_deterministic_on_ties_by_runtime_key() -> None:
    service, _store, _audit = build(
        [
            runtime("mock", run_count=10, completion=0.50),
            runtime("zeta", run_count=10, completion=0.90),
            runtime("alpha", run_count=10, completion=0.90),
        ]
    )

    first, _ = service.generate(CEO_ONE)
    second, _ = service.generate(CEO_ONE)

    assert first is not None and second is not None
    assert first.proposed_value == "alpha"
    assert second.proposed_value == "alpha"


def test_generate_queries_metrics_for_actor_tenant() -> None:
    service, _store, _audit = build(
        [
            runtime("mock", run_count=10, completion=0.60),
            runtime("agentscope", run_count=10, completion=0.90),
        ]
    )

    service.generate(CEO_ONE)

    assert service.metrics.calls == [("t-1", None)]


def test_get_and_list_are_tenant_scoped() -> None:
    service, store, _audit = build(
        [
            runtime("mock", run_count=10, completion=0.60),
            runtime("agentscope", run_count=10, completion=0.90),
        ]
    )
    proposal, _ = service.generate(CEO_ONE)
    assert proposal is not None

    assert service.list(CEO_ONE, limit=10) == [proposal]
    with pytest.raises(OrchestrationProposalNotFound):
        service.get(UserContext("t-other", "ceo-1", "ceo"), proposal.proposal_id)
    with pytest.raises(OrchestrationProposalNotFound):
        service.get(CEO_ONE, "orch-missing")


def test_approve_requires_ceo_and_blocks_self_approval() -> None:
    service, _store, _audit = build(
        [
            runtime("mock", run_count=10, completion=0.60),
            runtime("agentscope", run_count=10, completion=0.90),
        ]
    )
    proposal, _ = service.generate(CEO_ONE)
    assert proposal is not None

    with pytest.raises(PolicyError):
        service.approve(EMPLOYEE, proposal.proposal_id)
    with pytest.raises(PolicyError, match="发起人"):
        service.approve(CEO_ONE, proposal.proposal_id)

    approved = service.approve(CEO_TWO, proposal.proposal_id)

    assert approved.status is OrchestrationProposalStatus.APPROVED
    assert approved.reviewed_by == "ceo-2"


def test_reject_requires_reason_and_writes_audit() -> None:
    service, _store, audit_store = build(
        [
            runtime("mock", run_count=10, completion=0.60),
            runtime("agentscope", run_count=10, completion=0.90),
        ]
    )
    proposal, _ = service.generate(CEO_ONE)
    assert proposal is not None

    with pytest.raises(PolicyError):
        service.reject(EMPLOYEE, proposal.proposal_id, "原因")
    with pytest.raises(PolicyError, match="发起人"):
        service.reject(CEO_ONE, proposal.proposal_id, "原因")
    with pytest.raises(ValueError, match="驳回原因不能为空"):
        service.reject(CEO_TWO, proposal.proposal_id, "   ")

    rejected = service.reject(CEO_TWO, proposal.proposal_id, "  信息不足  ")

    assert rejected.status is OrchestrationProposalStatus.REJECTED
    assert rejected.rejection_reason == "信息不足"
    actions = [record.action for record in audit_store.list_recent(None, limit=100)]
    assert AuditAction.ORCHESTRATION_REJECTED in actions


def test_duplicate_approval_conflicts() -> None:
    service, _store, _audit = build(
        [
            runtime("mock", run_count=10, completion=0.60),
            runtime("agentscope", run_count=10, completion=0.90),
        ]
    )
    proposal, _ = service.generate(CEO_ONE)
    assert proposal is not None
    service.approve(CEO_TWO, proposal.proposal_id)

    with pytest.raises(OrchestrationProposalStateConflict):
        service.approve(CEO_TWO, proposal.proposal_id)


def test_all_audit_details_use_declared_keys() -> None:
    service, _store, audit_store = build(
        [
            runtime("mock", run_count=10, completion=0.60),
            runtime("agentscope", run_count=10, completion=0.90),
        ]
    )
    first, _ = service.generate(CEO_ONE)
    assert first is not None
    service.approve(CEO_TWO, first.proposal_id)

    second, _ = service.generate(CEO_ONE)
    assert second is not None
    service.reject(CEO_TWO, second.proposal_id, "暂不采纳")

    records = audit_store.list_recent(None, limit=100)
    actions = {record.action for record in records}
    assert {
        AuditAction.ORCHESTRATION_PROPOSED,
        AuditAction.ORCHESTRATION_APPROVED,
        AuditAction.ORCHESTRATION_REJECTED,
    } <= actions
    for record in records:
        assert set(record.detail) <= ALLOWED_DETAIL_KEYS
