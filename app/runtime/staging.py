from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from .adapters import CodexWorkerAdapter, DeerFlowAdapter, FakeTransport, HermesAdapter
from .contracts import AgentPlan, RuntimeContext, RuntimeEvent, RuntimeEventType
from .mock import MockRuntime
from .state import RuntimeStateStore


def _context(mode: str) -> RuntimeContext:
    return RuntimeContext(
        tenant_id="staging-tenant",
        user_id="staging-user",
        role_key="ai-product-delivery",
        mode=mode,
        project_id="staging-project",
        task_id="staging-task",
        device_id="staging-device",
        knowledge_scope=("kb-staging",),
        file_scope=("D:/staging/project-1",),
        budget_cents=5000,
        risk_level="low",
        policy_version="policy-1",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


def _check_mock() -> bool:
    runtime = MockRuntime(RuntimeStateStore())
    plan = AgentPlan.from_steps(
        [
            {"step_id": "read", "kind": "read", "tool": "knowledge.search"},
            {"step_id": "write", "kind": "write", "tool": "file.write"},
        ]
    )
    run_id = runtime.start_run(_context("product_manager"), plan)
    events = runtime.stream_events(run_id)
    return (
        events[0].event_type is RuntimeEventType.PLAN_CREATED
        and any(event.event_type is RuntimeEventType.APPROVAL_REQUESTED for event in events)
    )


def _check_external_adapters() -> tuple[bool, bool, bool, bool]:
    deer_transport = FakeTransport()
    deer = DeerFlowAdapter(deer_transport, "http://staging-deerflow")
    deer_run = deer.start_run(_context("product_manager"), AgentPlan.from_steps([]))
    deer_events = deer.stream_events(deer_run)
    context_payload = deer_transport.requests[0]["context"]
    context_scope_ok = set(context_payload) >= {
        "tenant_id",
        "task_id",
        "knowledge_scope",
        "file_scope",
        "budget_cents",
        "policy_version",
    }

    codex = CodexWorkerAdapter(FakeTransport(), "http://staging-codex")
    codex_run = codex.start_run(
        _context("fde"), AgentPlan.from_steps([{"step_id": "read", "kind": "read", "tool": "file.read"}])
    )
    codex_ok = codex_run.startswith("run-")

    hermes = HermesAdapter(FakeTransport(), "http://staging-hermes")
    hermes_run = hermes.start_run(_context("product_manager"), AgentPlan.from_steps([]))
    hermes_ok = any(
        event.payload.get("status") == "pending_review" for event in hermes.stream_events(hermes_run)
    )

    secret_event = RuntimeEvent(
        run_id="staging-run",
        sequence=1,
        event_type=RuntimeEventType.TOOL_RESULT,
        payload={"api_key": "secret", "cookie": "session"},
    )
    secret_ok = secret_event.to_public_dict()["payload"] == {
        "api_key": "[已隐藏]",
        "cookie": "[已隐藏]",
    }
    return context_scope_ok, codex_ok, hermes_ok, secret_ok


def run_smoke_check() -> dict[str, Any]:
    """运行无网络、无生产副作用的 staging 冒烟检查。"""
    mock_ok = _check_mock()
    context_ok, codex_ok, hermes_ok, secret_ok = _check_external_adapters()
    runtimes = {
        "mock": "pass" if mock_ok else "fail",
        "deerflow": "pass" if context_ok else "fail",
        "codex_worker": "pass" if codex_ok else "fail",
        "hermes": "pass" if hermes_ok else "fail",
    }
    security = {
        "context_scope": "pass" if context_ok else "fail",
        "secret_redaction": "pass" if secret_ok else "fail",
        "hermes_review_gate": "pass" if hermes_ok else "fail",
    }
    return {
        "status": "pass" if all(value == "pass" for value in (*runtimes.values(), *security.values())) else "fail",
        "runtimes": runtimes,
        "security": security,
    }


if __name__ == "__main__":
    print(json.dumps(run_smoke_check(), ensure_ascii=False, indent=2))
