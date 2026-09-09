import httpx
import pytest

from app.runtime.adapters.common import HttpRuntimeTransport, TransportError


def test_http_transport_starts_run_and_reads_events() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/runs"):
            return httpx.Response(201, json={"run_id": "remote-1"})
        return httpx.Response(200, json={"events": [{"type": "run.completed", "payload": {}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    transport = HttpRuntimeTransport(client=client)

    remote_id = transport.start("https://runtime.example/api", {"task_id": "task-1"})
    events = transport.events_for("https://runtime.example/api", remote_id)

    assert remote_id == "remote-1"
    assert events[0]["type"] == "run.completed"
    assert requests[0].url.path == "/api/runs"


def test_http_transport_searches_knowledge_without_exposing_internal_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"items": [{"document_id": "doc-1"}]})

    transport = HttpRuntimeTransport(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    data = transport.knowledge_search(
        "https://ragflow.example/api",
        {"tenant_id": "tenant-1", "knowledge_base_ids": ["kb-1"], "query": "故障", "limit": 1},
    )

    assert data["items"][0]["document_id"] == "doc-1"
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/api/knowledge-search"


def test_http_transport_rejects_error_and_malformed_responses() -> None:
    def error_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "unavailable"})

    client = httpx.Client(transport=httpx.MockTransport(error_handler))
    transport = HttpRuntimeTransport(client=client)
    with pytest.raises(TransportError, match="503"):
        transport.start("https://runtime.example", {})

    def malformed_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    malformed = HttpRuntimeTransport(
        client=httpx.Client(transport=httpx.MockTransport(malformed_handler))
    )
    with pytest.raises(TransportError, match="运行号"):
        malformed.start("https://runtime.example", {})
