from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx

from ..contracts import AgentPlan, AgentRuntimeAdapter, RuntimeContext, RuntimeEvent, RuntimeEventType


class TransportError(RuntimeError):
    """外部运行时传输失败，禁止把失败伪装成成功。"""


class FakeTransport:
    def __init__(
        self,
        events: list[dict[str, Any]] | None = None,
        knowledge_items: list[dict[str, Any]] | None = None,
    ) -> None:
        self.requests: list[dict[str, Any]] = []
        self.events = events or []
        self.knowledge_items = knowledge_items or []

    def start(self, endpoint: str, payload: dict[str, Any]) -> str:
        self.requests.append(payload)
        return f"remote-{uuid4().hex[:8]}"

    def events_for(self, endpoint: str, remote_run_id: str) -> list[dict[str, Any]]:
        return list(self.events)

    def knowledge_search(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.requests.append({"endpoint": endpoint, "action": "knowledge_search", **payload})
        return {"items": list(self.knowledge_items)}

    def command(self, endpoint: str, remote_run_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.requests.append({"endpoint": endpoint, "remote_run_id": remote_run_id, "action": action, **payload})
        return {"status": "accepted", "approval_id": f"approval-{uuid4().hex[:8]}"}

    def health(self, endpoint: str) -> dict[str, Any]:
        return {"runtime": endpoint, "status": "ok"}


class HttpRuntimeTransport:
    """通过约定的 HTTP 边界调用独立 Runtime 服务。"""

    def __init__(self, *, client: httpx.Client | None = None, timeout_seconds: float = 30.0) -> None:
        self.client = client or httpx.Client(timeout=timeout_seconds)

    @staticmethod
    def _base(endpoint: str) -> str:
        return endpoint.rstrip("/")

    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.client.request(method, url, **kwargs)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TransportError(f"Runtime 请求失败: {exc}") from exc
        if not isinstance(data, dict):
            raise TransportError("Runtime 返回格式无效")
        return data

    def start(self, endpoint: str, payload: dict[str, Any]) -> str:
        data = self._request("POST", f"{self._base(endpoint)}/runs", json=payload)
        run_id = data.get("run_id") or data.get("id")
        if not isinstance(run_id, str) or not run_id:
            raise TransportError("Runtime 返回中缺少运行号")
        return run_id

    def events_for(self, endpoint: str, remote_run_id: str) -> list[dict[str, Any]]:
        data = self._request("GET", f"{self._base(endpoint)}/runs/{remote_run_id}/events")
        events = data.get("events", data.get("items", []))
        if not isinstance(events, list) or not all(isinstance(item, dict) for item in events):
            raise TransportError("Runtime 事件格式无效")
        return events

    def knowledge_search(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"{self._base(endpoint)}/knowledge-search", json=payload)

    def command(self, endpoint: str, remote_run_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"{self._base(endpoint)}/runs/{remote_run_id}/{action}", json=payload)

    def health(self, endpoint: str) -> dict[str, Any]:
        return self._request("GET", f"{self._base(endpoint)}/health")


class ExternalAdapter(AgentRuntimeAdapter):
    def __init__(self, transport: Any, endpoint: str, runtime_key: str) -> None:
        self.transport = transport
        self.endpoint = endpoint
        self.runtime_key = runtime_key
        self._runs: dict[str, tuple[str, RuntimeContext]] = {}

    def _payload(self, context: RuntimeContext, plan: AgentPlan) -> dict[str, Any]:
        return {"context": {"tenant_id": context.tenant_id, "task_id": context.task_id, "role_key": context.role_key, "mode": context.mode, "project_id": context.project_id, "device_id": context.device_id, "knowledge_scope": list(context.knowledge_scope), "file_scope": list(context.file_scope), "budget_cents": context.budget_cents, "risk_level": context.risk_level, "policy_version": context.policy_version, "expires_at": context.expires_at.isoformat()}, "plan": [{"step_id": step.step_id, "kind": step.kind, "tool": step.tool, "requires_approval": step.requires_approval} for step in plan.steps]}

    def start_run(self, context: RuntimeContext, plan: AgentPlan) -> str:
        run_id=f"run-{uuid4().hex[:12]}"; remote=self.transport.start(self.endpoint, self._payload(context, plan)); self._runs[run_id]=(remote, context); return run_id

    def stream_events(self, run_id: str, cursor: str | None = None) -> list[RuntimeEvent]:
        remote, _context = self._runs[run_id]; raw=self.transport.events_for(self.endpoint, remote) or [{"type":"plan.created","payload":{}}]; result=[]
        for index,item in enumerate(raw,1):
            mapping={"plan.created":RuntimeEventType.PLAN_CREATED,"step.started":RuntimeEventType.STEP_STARTED,"tool.result":RuntimeEventType.TOOL_RESULT,"approval.requested":RuntimeEventType.APPROVAL_REQUESTED,"run.completed":RuntimeEventType.RUN_COMPLETED,"run.failed":RuntimeEventType.RUN_FAILED}
            event_type=mapping.get(item.get("type"), RuntimeEventType.RUN_FAILED); payload=item.get("payload",{})
            if item.get("type") not in mapping: payload={"reason":"外部运行时返回未知事件","remote_type":item.get("type"), **item.get("payload", {})}
            event=RuntimeEvent(run_id,index,event_type,payload)
            if not cursor or index > int(cursor.rsplit(":",1)[1]): result.append(event)
        return result

    def pause_run(self, run_id: str, reason: str) -> None:
        remote, _ = self._runs[run_id]
        self.transport.command(self.endpoint, remote, "pause", {"reason": reason})

    def resume_run(self, run_id: str) -> None:
        remote, _ = self._runs[run_id]
        self.transport.command(self.endpoint, remote, "resume", {})

    def cancel_run(self, run_id: str, reason: str) -> None:
        remote, _ = self._runs[run_id]
        self.transport.command(self.endpoint, remote, "cancel", {"reason": reason})

    def request_approval(self, run_id: str, action: dict[str, Any]) -> str:
        remote, _ = self._runs[run_id]
        result = self.transport.command(self.endpoint, remote, "approvals", {"action": action})
        return str(result.get("approval_id") or f"approval-{uuid4().hex[:8]}")

    def get_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        return {"status": "external"} if run_id in self._runs else None

    def replay_run(self, run_id: str, from_step: str | None = None) -> str:
        remote, _ = self._runs[run_id]
        self.transport.command(self.endpoint, remote, "replay", {"from_step": from_step})
        return run_id

    def get_usage(self, run_id: str) -> dict[str, Any]:
        remote, _ = self._runs[run_id]
        return self.transport.command(self.endpoint, remote, "usage", {})

    def health(self) -> dict[str, Any]:
        return self.transport.health(self.endpoint)
