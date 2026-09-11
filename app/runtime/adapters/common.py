from __future__ import annotations

import re
from typing import Any, Mapping
from uuid import uuid4

import httpx

from ..contracts import AgentPlan, AgentRuntimeAdapter, RuntimeContext, RuntimeEvent, RuntimeEventType


_SAFE_REMOTE_TYPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")


def _safe_remote_type(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown"
    candidate = value.strip()
    return candidate if _SAFE_REMOTE_TYPE.fullmatch(candidate) else "unknown"


class TransportError(RuntimeError):
    """外部运行时传输失败，禁止把失败伪装成成功。"""


class RuntimeUnavailable(LookupError):
    """已注册但当前不支持该类运行时操作。"""


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
        self.requests.append({"endpoint": endpoint, "remote_run_id": remote_run_id, **payload, "action": action})
        return {"status": "accepted", "approval_id": f"approval-{uuid4().hex[:8]}"}

    def health(self, endpoint: str) -> dict[str, Any]:
        return {"runtime": endpoint, "status": "ok"}


class HttpRuntimeTransport:
    """通过约定的 HTTP 边界调用独立 Runtime 服务。"""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 30.0,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self.headers = dict(headers or {})

    @staticmethod
    def _base(endpoint: str) -> str:
        return endpoint.rstrip("/")

    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        merged_headers = {**self.headers, **kwargs.pop("headers", {})}
        try:
            response = self.client.request(method, url, headers=merged_headers, **kwargs)
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
        self._state_store: Any | None = None

    def bind_state_store(self, state_store: Any) -> None:
        """让服务层控制面能够按外部运行号执行租户校验。"""
        self._state_store = state_store

    def _payload(self, context: RuntimeContext, plan: AgentPlan) -> dict[str, Any]:
        return {"context": {"tenant_id": context.tenant_id, "task_id": context.task_id, "role_key": context.role_key, "mode": context.mode, "project_id": context.project_id, "device_id": context.device_id, "knowledge_scope": list(context.knowledge_scope), "file_scope": list(context.file_scope), "budget_cents": context.budget_cents, "risk_level": context.risk_level, "policy_version": context.policy_version, "expires_at": context.expires_at.isoformat()}, "plan": [{"step_id": step.step_id, "kind": step.kind, "tool": step.tool, "requires_approval": step.requires_approval} for step in plan.steps]}

    def start_run(self, context: RuntimeContext, plan: AgentPlan) -> str:
        run_id = f"run-{uuid4().hex[:12]}"
        remote = self.transport.start(self.endpoint, self._payload(context, plan))
        self._runs[run_id] = (remote, context)
        if self._state_store is not None:
            self._state_store.create(context, plan, run_id=run_id)
        return run_id

    def stream_events(self, run_id: str, cursor: str | None = None) -> list[RuntimeEvent]:
        remote, _context = self._runs[run_id]; raw=self.transport.events_for(self.endpoint, remote) or [{"type":"plan.created","payload":{}}]; result=[]
        for index,item in enumerate(raw,1):
            mapping={"plan.created":RuntimeEventType.PLAN_CREATED,"step.started":RuntimeEventType.STEP_STARTED,"tool.call":RuntimeEventType.TOOL_CALL,"tool.result":RuntimeEventType.TOOL_RESULT,"approval.requested":RuntimeEventType.APPROVAL_REQUESTED,"approval.decided":RuntimeEventType.APPROVAL_DECIDED,"checkpoint.saved":RuntimeEventType.CHECKPOINT_SAVED,"run.paused":RuntimeEventType.RUN_PAUSED,"run.completed":RuntimeEventType.RUN_COMPLETED,"run.failed":RuntimeEventType.RUN_FAILED}
            remote_type = item.get("type")
            event_type=mapping.get(remote_type, RuntimeEventType.RUN_FAILED) if isinstance(remote_type, str) else RuntimeEventType.RUN_FAILED
            payload=item.get("payload",{})
            if not isinstance(remote_type, str) or remote_type not in mapping:
                payload={"reason":"外部运行时返回未知事件","remote_type":_safe_remote_type(remote_type)}
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

    def decide_approval(self, run_id: str, approval_id: str, approved: bool) -> None:
        """把决议下发给外部运行时；真实平台的决议协议尚未联调（与其它外部命令同一验收状态）。"""
        remote, _ = self._runs[run_id]
        self.transport.command(
            self.endpoint, remote, "approval_decision", {"approval_id": approval_id, "approved": approved}
        )

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
        raw = self.transport.health(self.endpoint)
        if not isinstance(raw, dict):
            raise TransportError("Runtime 健康检查响应格式无效")
        summary: dict[str, Any] = {
            "runtime": self.endpoint,
            "status": "ok",
        }
        if isinstance(raw.get("version"), str):
            summary["version"] = raw["version"]
        capabilities = raw.get("capabilities")
        if isinstance(capabilities, (list, tuple)) and all(isinstance(item, str) for item in capabilities):
            summary["capabilities"] = list(capabilities)
        if isinstance(raw.get("sandbox"), str):
            summary["sandbox"] = raw["sandbox"]
        if isinstance(raw.get("reason"), str):
            summary["reason"] = raw["reason"]
        return summary
