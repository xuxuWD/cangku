import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.main import app
from app.orchestration.service import OrchestrationProposalService
from app.orchestration.store import InMemoryOrchestrationProposalStore

client = TestClient(app)


def runtime(key: str, *, completion: float, run_count: int = 10, tools: float = 1.0) -> dict[str, object]:
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

    def summary(self, tenant_id: str, *, runtime_key: str | None = None) -> dict[str, object]:
        return {"tenant_id": tenant_id, "runtime_key": runtime_key, "by_runtime": self.by_runtime}


def build_service(
    by_runtime: list[dict[str, object]],
    *,
    default: str = "mock",
    min_samples: int = 2,
    threshold: float = 0.1,
) -> OrchestrationProposalService:
    return OrchestrationProposalService(
        InMemoryOrchestrationProposalStore(),
        metrics=StubMetrics(by_runtime),
        audit=AuditService(InMemoryAuditStore()),
        default_runtime_key=default,
        min_samples=min_samples,
        improvement_threshold=threshold,
    )


DEFAULT_METRICS = [runtime("mock", completion=0.60), runtime("agentscope", completion=0.90)]


@pytest.fixture(autouse=True)
def _wire(monkeypatch) -> OrchestrationProposalService:
    service = build_service(DEFAULT_METRICS)
    monkeypatch.setattr(main, "orchestration_service", service)
    return service


def headers(role: str = "ceo", user_id: str = "ceo-1", tenant_id: str = "t-1") -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def generate(headers_override: dict[str, str] | None = None) -> dict[str, object]:
    response = client.post(
        "/api/v1/orchestration-proposals", headers=headers_override or headers(), json={}
    )
    assert response.status_code == 200
    return response.json()


def test_generate_requires_admin_role() -> None:
    response = client.post(
        "/api/v1/orchestration-proposals", headers=headers(role="employee", user_id="u-1"), json={}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "只有 CEO 或超级管理员可以管理编排优化提案"


def test_generate_returns_proposal_with_reason() -> None:
    body = generate()

    assert body["reason"]
    proposal = body["proposal"]
    assert proposal["kind"] == "runtime_default"
    assert proposal["current_value"] == "mock"
    assert proposal["proposed_value"] == "agentscope"
    assert proposal["status"] == "pending_review"
    assert proposal["metrics_snapshot"]["current"]["runtime_key"] == "mock"


def test_generate_returns_null_proposal_with_reason(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "orchestration_service",
        build_service([runtime("mock", completion=0.9), runtime("agentscope", completion=0.5)]),
    )

    body = generate()

    assert body["proposal"] is None
    assert "已是表现最好" in body["reason"]


def test_generate_rejects_unknown_kind() -> None:
    response = client.post(
        "/api/v1/orchestration-proposals", headers=headers(), json={"kind": "unknown"}
    )

    assert response.status_code == 422


def test_list_and_get_detail() -> None:
    created = generate()["proposal"]

    listed = client.get("/api/v1/orchestration-proposals", headers=headers())
    assert listed.status_code == 200
    assert [item["proposal_id"] for item in listed.json()["items"]] == [created["proposal_id"]]

    detail = client.get(
        f"/api/v1/orchestration-proposals/{created['proposal_id']}", headers=headers()
    )
    assert detail.status_code == 200
    assert detail.json()["proposal_id"] == created["proposal_id"]


def test_detail_unknown_and_cross_tenant_are_404() -> None:
    created = generate()["proposal"]

    assert client.get("/api/v1/orchestration-proposals/orch-missing", headers=headers()).status_code == 404
    crossed = client.get(
        f"/api/v1/orchestration-proposals/{created['proposal_id']}",
        headers=headers(tenant_id="t-other"),
    )
    assert crossed.status_code == 404
    assert crossed.json()["detail"] == "优化提案不存在"


def test_approval_flow_conflict_and_not_found() -> None:
    proposal_id = generate()["proposal"]["proposal_id"]

    approved = client.post(
        f"/api/v1/orchestration-proposals/{proposal_id}/approval", headers=headers(user_id="ceo-2")
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    conflict = client.post(
        f"/api/v1/orchestration-proposals/{proposal_id}/approval", headers=headers(user_id="ceo-2")
    )
    assert conflict.status_code == 409

    missing = client.post(
        "/api/v1/orchestration-proposals/orch-missing/approval", headers=headers(user_id="ceo-2")
    )
    assert missing.status_code == 404


def test_rejection_flow_and_blank_reason() -> None:
    proposal_id = generate()["proposal"]["proposal_id"]

    rejected = client.post(
        f"/api/v1/orchestration-proposals/{proposal_id}/rejection",
        headers=headers(user_id="ceo-2"),
        json={"reason": "暂不采纳"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["rejection_reason"] == "暂不采纳"

    other_id = generate()["proposal"]["proposal_id"]
    blank = client.post(
        f"/api/v1/orchestration-proposals/{other_id}/rejection",
        headers=headers(user_id="ceo-2"),
        json={"reason": "   "},
    )
    assert blank.status_code == 422


def test_creator_cannot_approve_own_proposal() -> None:
    proposal_id = generate()["proposal"]["proposal_id"]

    response = client.post(
        f"/api/v1/orchestration-proposals/{proposal_id}/approval", headers=headers(user_id="ceo-1")
    )

    assert response.status_code == 403


def test_non_admin_cannot_list_or_approve() -> None:
    proposal_id = generate()["proposal"]["proposal_id"]
    employee = headers(role="employee", user_id="u-1")

    assert client.get("/api/v1/orchestration-proposals", headers=employee).status_code == 403
    assert (
        client.post(
            f"/api/v1/orchestration-proposals/{proposal_id}/approval", headers=employee
        ).status_code
        == 403
    )
