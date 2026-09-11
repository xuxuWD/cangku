"""staging 并发探针的离线测试：不发任何真实网络请求，全部使用假客户端。"""

import json
from threading import Lock
from urllib.parse import urlsplit

import pytest

from scripts.staging_concurrency_probe import (
    SCENES,
    HttpProbeClient,
    ProbeConfigError,
    ProbeResponse,
    ProbeTarget,
    evaluate_login_throttle,
    evaluate_plan_approval,
    evaluate_task_idempotency,
    main,
    resolve_base_url,
    run_probe,
)


# --------------------------------------------------------------------------- 护栏


def test_resolve_base_url_rejects_empty() -> None:
    with pytest.raises(ProbeConfigError) as excinfo:
        resolve_base_url("")

    assert "必须提供 staging 基础地址" in str(excinfo.value)


def test_resolve_base_url_requires_https() -> None:
    with pytest.raises(ProbeConfigError) as excinfo:
        resolve_base_url("http://staging.example.com")

    assert "HTTPS" in str(excinfo.value)


def test_resolve_base_url_allows_insecure_when_explicit() -> None:
    assert resolve_base_url("http://staging.example.com", allow_insecure=True) == (
        "http://staging.example.com"
    )


@pytest.mark.parametrize(
    "base_url",
    ["https://localhost:8000", "https://127.0.0.1", "https://[::1]:8000", "https://0.0.0.0"],
)
def test_resolve_base_url_rejects_local_hosts(base_url: str) -> None:
    with pytest.raises(ProbeConfigError) as excinfo:
        resolve_base_url(base_url)

    assert "独立 staging 主机" in str(excinfo.value)


def test_resolve_base_url_allows_local_when_explicit() -> None:
    assert resolve_base_url("https://localhost:8000", allow_local=True) == (
        "https://localhost:8000"
    )


def test_resolve_base_url_normalizes_trailing_slash() -> None:
    assert resolve_base_url("https://staging.example.com/") == "https://staging.example.com"
    assert resolve_base_url("https://staging.example.com//") == "https://staging.example.com"


# --------------------------------------------------------------------------- 判据


def test_evaluate_login_throttle_positive_and_negative() -> None:
    assert evaluate_login_throttle({401: 5, 429: 3}, 5)[0] == "pass"
    assert evaluate_login_throttle({401: 8}, 5)[0] == "fail"
    assert evaluate_login_throttle({500: 1, 429: 1}, 5)[0] == "fail"


def test_evaluate_task_idempotency_positive_and_negative() -> None:
    assert evaluate_task_idempotency({201: 1, 200: 7}, ["task-1"])[0] == "pass"
    assert evaluate_task_idempotency({201: 4, 200: 4}, ["task-1", "task-2"])[0] == "fail"
    assert evaluate_task_idempotency({500: 1}, ["task-1"])[0] == "fail"
    assert evaluate_task_idempotency({}, [])[0] == "fail"


def test_evaluate_plan_approval_positive_and_negative() -> None:
    assert evaluate_plan_approval({200: 1, 409: 7})[0] == "pass"
    assert evaluate_plan_approval({200: 2, 409: 6})[0] == "fail"
    assert evaluate_plan_approval({200: 1, 404: 7})[0] == "fail"
    assert evaluate_plan_approval({200: 0, 409: 8})[0] == "fail"
    assert evaluate_plan_approval({200: 1, 409: 6, 500: 1})[0] == "fail"


# --------------------------------------------------------------------------- 假客户端


class _CountingClient:
    """按路径路由的假客户端；每个路径独立计数以模拟并发结果分布。"""

    def __init__(self, routes: dict[str, list[tuple[int, object]]]) -> None:
        self._routes = routes
        self._counters: dict[str, int] = {}
        self._lock = Lock()
        self.calls: list[dict[str, object]] = []

    def request(self, method, url, *, json=None, headers=None, timeout=10.0) -> ProbeResponse:
        path = urlsplit(url).path
        with self._lock:
            self.calls.append({"method": method, "path": path, "headers": headers})
            index = self._counters.get(path, 0)
            self._counters[path] = index + 1
            schedule = self._routes[path]
            status_code, payload = schedule[min(index, len(schedule) - 1)]
        return ProbeResponse(status_code=status_code, payload=payload)


def _passing_client() -> _CountingClient:
    return _CountingClient(
        {
            "/api/v1/auth/sessions": [(429, {"detail": "locked"})],
            "/api/v1/tasks": [(201, {"id": "task-1"})],
            "/api/v1/plan-proposals/prop-1/approval": [(200, {"status": "approved"})]
            + [(409, {"detail": "conflict"})] * 64,
        }
    )


def _target() -> ProbeTarget:
    return ProbeTarget(
        base_url="https://staging.example.com",
        token="probe-token-secret-value",
        phone="+8613800000000",
        password="probe-password-value",
        tenant_id="tenant-probe",
        user_id="user-probe",
        role="admin",
    )


# --------------------------------------------------------------------------- run_probe


def test_run_probe_assembles_codes_and_passes() -> None:
    client = _passing_client()

    report = run_probe(
        _target(), client, scenes=SCENES, concurrency=6, timeout=5.0, proposal_id="prop-1"
    )

    scenes = {scene.name: scene for scene in report.scenes}
    assert report.passed is True
    assert set(scenes) == set(SCENES)
    assert scenes["login_throttle"].codes == {429: 6}
    assert scenes["task_idempotency"].codes == {201: 6}
    assert scenes["plan_approval"].codes == {200: 1, 409: 5}
    assert all(scene.requests == 6 for scene in report.scenes)
    assert all(scene.status == "pass" for scene in report.scenes)
    assert all(scene.p95_ms >= 0 for scene in report.scenes)
    assert "锁定" in scenes["login_throttle"].detail


def test_run_probe_marks_conflict_as_failure() -> None:
    client = _CountingClient(
        {
            "/api/v1/auth/sessions": [(429, {"detail": "locked"})],
            "/api/v1/tasks": [(201, {"id": "task-1"})],
            "/api/v1/plan-proposals/prop-1/approval": [(200, {}), (200, {}), (409, {})],
        }
    )

    report = run_probe(
        _target(), client, scenes=SCENES, concurrency=3, timeout=5.0, proposal_id="prop-1"
    )

    scenes = {scene.name: scene for scene in report.scenes}
    assert scenes["plan_approval"].status == "fail"
    assert report.passed is False


def test_run_probe_skips_plan_approval_without_proposal_id() -> None:
    client = _passing_client()

    report = run_probe(
        _target(),
        client,
        scenes=SCENES,
        concurrency=4,
        timeout=5.0,
        proposal_id=None,
    )

    scenes = {scene.name: scene for scene in report.scenes}
    assert scenes["plan_approval"].status == "skipped"
    assert scenes["plan_approval"].requests == 0
    assert "--proposal-id" in scenes["plan_approval"].detail
    assert report.passed is True


def test_run_probe_reports_transport_errors_as_failure() -> None:
    class _ExplodingClient:
        def request(self, method, url, *, json=None, headers=None, timeout=10.0):
            raise RuntimeError("connection refused")

    report = run_probe(
        _target(),
        _ExplodingClient(),
        scenes=SCENES,
        concurrency=3,
        timeout=5.0,
        proposal_id=None,
    )

    scenes = {scene.name: scene for scene in report.scenes}
    assert scenes["login_throttle"].status == "fail"
    assert scenes["task_idempotency"].status == "fail"
    assert report.passed is False


# --------------------------------------------------------------------------- 脱敏


def test_report_does_not_leak_password_or_token() -> None:
    report = run_probe(
        _target(),
        _passing_client(),
        scenes=SCENES,
        concurrency=4,
        timeout=5.0,
        proposal_id="prop-1",
    )

    text = report.to_text()
    data = json.dumps(report.to_dict(), ensure_ascii=False)

    for leaked in ("probe-password-value", "probe-token-secret-value"):
        assert leaked not in text
        assert leaked not in data
    assert report.to_dict()["base_url_host"] == "staging.example.com"


def test_authorization_header_is_sent_for_non_login_scenes() -> None:
    client = _passing_client()

    run_probe(
        _target(), client, scenes=SCENES, concurrency=2, timeout=5.0, proposal_id="prop-1"
    )

    task_calls = [call for call in client.calls if call["path"] == "/api/v1/tasks"]
    assert task_calls
    assert task_calls[0]["headers"]["Authorization"] == "Bearer probe-token-secret-value"
    login_calls = [call for call in client.calls if call["path"] == "/api/v1/auth/sessions"]
    assert login_calls
    assert "Authorization" not in login_calls[0]["headers"]


# --------------------------------------------------------------------------- main


def _main_argv(**overrides) -> list[str]:
    args = {
        "--base-url": "https://staging.example.com",
        "--token": "probe-token-secret-value",
        "--phone": "+8613800000000",
        "--password": "probe-password-value",
        "--proposal-id": "prop-1",
        "--concurrency": "4",
        "--timeout": "3",
    }
    args.update(overrides)
    argv: list[str] = []
    for key, value in args.items():
        if value is None:
            continue
        argv.extend([key, value])
    return argv


def test_main_returns_two_on_config_error() -> None:
    called = False

    def factory():
        nonlocal called
        called = True
        return _passing_client()

    rc = main(
        _main_argv(**{"--base-url": "http://staging.example.com"}),
        client_factory=factory,
    )

    assert rc == 2
    assert called is False


def test_main_returns_zero_when_all_scenes_pass(capsys) -> None:
    rc = main(_main_argv(), client_factory=_passing_client)

    assert rc == 0
    assert "pass" in capsys.readouterr().out


def test_main_returns_one_when_a_scene_fails(capsys) -> None:
    client = _CountingClient(
        {
            "/api/v1/auth/sessions": [(401, {"detail": "invalid"})],
            "/api/v1/tasks": [(201, {"id": "task-1"})],
            "/api/v1/plan-proposals/prop-1/approval": [(200, {})],
        }
    )
    rc = main(_main_argv(), client_factory=lambda: client)

    assert rc == 1
    assert "登录限流" in capsys.readouterr().out


def test_main_writes_redacted_json_report(tmp_path) -> None:
    output = tmp_path / "probe.json"

    rc = main(
        _main_argv(**{"--output": str(output)}),
        client_factory=_passing_client,
    )

    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["base_url_host"] == "staging.example.com"
    body = output.read_text(encoding="utf-8")
    assert "probe-password-value" not in body
    assert "probe-token-secret-value" not in body


def test_main_rejects_out_of_range_concurrency() -> None:
    rc = main(_main_argv(**{"--concurrency": "0"}), client_factory=_passing_client)

    assert rc == 2


def test_http_probe_client_uses_injected_transport() -> None:
    import httpx

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(429, json={"detail": "locked"})

    client = HttpProbeClient(transport=httpx.MockTransport(handler))
    response = client.request("POST", "https://staging.example.com/api/v1/auth/sessions", timeout=1.0)

    assert response.status_code == 429
    assert response.json() == {"detail": "locked"}
    assert seen == ["/api/v1/auth/sessions"]
