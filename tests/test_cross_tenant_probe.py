"""跨租户探针脚本的离线测试：全部使用注入的假传输层，不发任何真实网络请求。

覆盖：https/本地护栏、资源规格解析、双向交叉访问判定、反向用例（隔离失效 → fail）、
「输出只含状态码与资源类型、绝不打印令牌或响应正文」。
"""

from __future__ import annotations

import pytest

from scripts.cross_tenant_probe import (
    CrossTenantConfigError,
    evaluate_isolation_with_controls,
    main,
    parse_resource,
    resolve_base_url,
    run_probe,
)

BASE_URL = "https://staging.example.com"
A_TOKEN = "tenant-a-token-secret"
B_TOKEN = "tenant-b-token-secret"
A_ID = "task-a-1"
B_ID = "task-b-1"
PAYLOAD_SENTINEL = "TENANT-B-PRIVATE-DATA"


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: object = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class CrossTransport:
    """按「令牌 + 资源归属」路由的假传输层。

    - 令牌 A 读属于 A 的资源 → ``a_own``（正向对照，默认 200）；
    - 令牌 B 读属于 B 的资源 → ``b_own``（正向对照，默认 200）；
    - 令牌 A 读属于 B 的资源 → ``a_to_b``（交叉）；
    - 令牌 B 读属于 A 的资源 → ``b_to_a``（交叉）。
    """

    def __init__(
        self,
        *,
        a_to_b: int = 404,
        b_to_a: int = 404,
        a_own: int = 200,
        b_own: int = 200,
        a_ids: frozenset[str] = frozenset({A_ID}),
        b_ids: frozenset[str] = frozenset({B_ID}),
    ) -> None:
        self.a_to_b = a_to_b
        self.b_to_a = b_to_a
        self.a_own = a_own
        self.b_own = b_own
        self.a_ids = a_ids
        self.b_ids = b_ids
        self.calls: list[dict[str, object]] = []

    @staticmethod
    def _resource_id(url: str) -> str:
        segments = [segment for segment in url.split("/") if segment]
        if segments and segments[-1] == "metrics":
            return segments[-2] if len(segments) >= 2 else ""
        return segments[-1] if segments else ""

    def __call__(self, method, url, *, headers, data=None, params=None, timeout):
        authorization = (headers or {}).get("Authorization", "")
        token = authorization.removeprefix("Bearer ")
        resource_id = self._resource_id(url)
        self.calls.append({"method": method, "url": url, "token": token})
        if token == A_TOKEN:
            code = self.a_own if resource_id in self.a_ids else self.a_to_b
        elif token == B_TOKEN:
            code = self.b_own if resource_id in self.b_ids else self.b_to_a
        else:
            code = 401
        payload = (
            {"id": url.rsplit("/", 1)[-1], "secret": PAYLOAD_SENTINEL}
            if 200 <= code < 300
            else {"detail": "not found"}
        )
        return FakeResponse(code, payload)


# --------------------------------------------------------------------------- 护栏


def test_resolve_base_url_requires_https() -> None:
    with pytest.raises(CrossTenantConfigError) as excinfo:
        resolve_base_url("http://staging.example.com")

    assert "HTTPS" in str(excinfo.value)


@pytest.mark.parametrize(
    "base_url", ["https://localhost:8000", "https://127.0.0.1", "https://0.0.0.0"]
)
def test_resolve_base_url_rejects_local_hosts(base_url: str) -> None:
    with pytest.raises(CrossTenantConfigError) as excinfo:
        resolve_base_url(base_url)

    assert "本地" in str(excinfo.value)


def test_resolve_base_url_allows_explicit_overrides() -> None:
    assert resolve_base_url("http://staging.example.com", allow_insecure=True) == (
        "http://staging.example.com"
    )
    assert resolve_base_url("https://localhost:8000", allow_local=True) == (
        "https://localhost:8000"
    )


# --------------------------------------------------------------------------- 资源规格解析


def test_parse_resource_accepts_valid_spec() -> None:
    assert parse_resource("task:task-a-1:task-b-1") == ("task", "task-a-1", "task-b-1")


@pytest.mark.parametrize(
    "spec",
    [
        "task:only-one-part",  # 段数不足
        "task:a:b:c",  # 段数过多
        "unknown:a:b",  # 未知资源类型
        "task::b",  # 缺少 A 侧标识
        "task:a:",  # 缺少 B 侧标识
        "task:same:same",  # 两侧标识相同，无法构成跨租户对照
    ],
)
def test_parse_resource_rejects_invalid_spec(spec: str) -> None:
    with pytest.raises(CrossTenantConfigError):
        parse_resource(spec)


# --------------------------------------------------------------------------- 判定


def test_probe_passes_when_both_directions_blocked() -> None:
    transport = CrossTransport(a_to_b=404, b_to_a=403)

    report = run_probe(
        BASE_URL,
        token_a=A_TOKEN,
        token_b=B_TOKEN,
        resources=[("task", A_ID, B_ID)],
        transport=transport,
        timeout=5.0,
    )

    assert report.passed is True
    probe = report.probes[0]
    assert probe.kind == "task"
    assert probe.code_ab == 404
    assert probe.code_ba == 403
    assert probe.status == "pass"


def test_probe_fails_when_cross_tenant_read_succeeds() -> None:
    """反向用例：A 读到 B 的资源（200），必须判 fail。"""
    transport = CrossTransport(a_to_b=200, b_to_a=404)

    report = run_probe(
        BASE_URL,
        token_a=A_TOKEN,
        token_b=B_TOKEN,
        resources=[("task", A_ID, B_ID)],
        transport=transport,
        timeout=5.0,
    )

    assert report.passed is False
    probe = report.probes[0]
    assert probe.status == "fail"
    assert probe.code_ab == 200
    assert "隔离" in probe.message


def test_probe_fails_when_reverse_read_succeeds() -> None:
    transport = CrossTransport(a_to_b=404, b_to_a=200)

    report = run_probe(
        BASE_URL,
        token_a=A_TOKEN,
        token_b=B_TOKEN,
        resources=[("task", A_ID, B_ID)],
        transport=transport,
        timeout=5.0,
    )

    assert report.passed is False
    assert report.probes[0].code_ba == 200


def test_probe_fails_on_unexpected_status() -> None:
    transport = CrossTransport(a_to_b=500, b_to_a=404)

    report = run_probe(
        BASE_URL,
        token_a=A_TOKEN,
        token_b=B_TOKEN,
        resources=[("task", A_ID, B_ID)],
        transport=transport,
        timeout=5.0,
    )

    assert report.passed is False


def test_probe_fails_on_transport_error() -> None:
    class BrokenTransport:
        def __call__(self, *args, **kwargs):
            raise RuntimeError("connection refused")

    report = run_probe(
        BASE_URL,
        token_a=A_TOKEN,
        token_b=B_TOKEN,
        resources=[("task", A_ID, B_ID)],
        transport=BrokenTransport(),
        timeout=5.0,
    )

    assert report.passed is False
    assert report.probes[0].code_ab == 0
    assert report.probes[0].code_ba == 0


# --------------------------------------------------------------- 正向对照（positive control）


def test_positive_control_failure_makes_probe_fail_despite_blocked_cross() -> None:
    """核心修复：交叉虽然稳定返回 403/404，但 A 读自己的资源是 404（资源不存在/不可读），
    本用例无效，必须判 fail —— 否则就是「两端都 404」的空转通过。"""
    transport = CrossTransport(a_own=404, a_to_b=404, b_to_a=403)

    report = run_probe(
        BASE_URL,
        token_a=A_TOKEN,
        token_b=B_TOKEN,
        resources=[("task", A_ID, B_ID)],
        transport=transport,
        timeout=5.0,
    )

    assert report.passed is False
    probe = report.probes[0]
    assert probe.status == "fail"
    assert probe.code_aa == 404
    # 交叉状态码本身都属于「旧逻辑会误判为 pass」的 403/404
    assert probe.code_ab in (403, 404)
    assert probe.code_ba in (403, 404)
    assert "正向对照未通过" in probe.message
    assert "本用例无效" in probe.message


def test_positive_control_failure_for_owner_b_makes_probe_fail() -> None:
    transport = CrossTransport(b_own=404, a_to_b=404, b_to_a=404)

    report = run_probe(
        BASE_URL,
        token_a=A_TOKEN,
        token_b=B_TOKEN,
        resources=[("task", A_ID, B_ID)],
        transport=transport,
        timeout=5.0,
    )

    assert report.passed is False
    probe = report.probes[0]
    assert probe.status == "fail"
    assert probe.code_bb == 404
    assert "正向对照未通过" in probe.message


def test_passes_when_controls_ok_and_cross_blocked() -> None:
    transport = CrossTransport(a_own=200, b_own=200, a_to_b=403, b_to_a=404)

    report = run_probe(
        BASE_URL,
        token_a=A_TOKEN,
        token_b=B_TOKEN,
        resources=[("task", A_ID, B_ID)],
        transport=transport,
        timeout=5.0,
    )

    assert report.passed is True
    probe = report.probes[0]
    assert probe.status == "pass"
    assert probe.code_aa == 200
    assert probe.code_bb == 200
    assert "正向对照通过" in probe.message
    assert "租户隔离成立" in probe.message


def test_evaluate_isolation_with_controls_delegates_after_controls_pass() -> None:
    # 正向对照通过 → 委托原判定：交叉 403/404 判 pass
    assert evaluate_isolation_with_controls(200, 200, 404, 403)[0] == "pass"
    # 正向对照通过后，交叉 200（越权成功）仍按原逻辑判 fail
    assert evaluate_isolation_with_controls(200, 200, 200, 404)[0] == "fail"
    # 正向对照失败时，即使交叉全 404 也判 fail
    status, message = evaluate_isolation_with_controls(404, 200, 404, 404)
    assert status == "fail"
    assert "正向对照未通过" in message


def test_probe_issues_controls_and_both_cross_directions_per_resource() -> None:
    transport = CrossTransport(
        a_to_b=404,
        b_to_a=404,
        a_ids=frozenset({A_ID, "p-a"}),
        b_ids=frozenset({B_ID, "p-b"}),
    )

    run_probe(
        BASE_URL,
        token_a=A_TOKEN,
        token_b=B_TOKEN,
        resources=[("task", A_ID, B_ID), ("plan_proposal", "p-a", "p-b")],
        transport=transport,
        timeout=5.0,
    )

    # 每个资源 4 次请求：A→A、B→B（正向对照）+ A→B、B→A（交叉）
    assert len(transport.calls) == 8
    assert sum(1 for call in transport.calls if call["token"] == A_TOKEN) == 4
    assert sum(1 for call in transport.calls if call["token"] == B_TOKEN) == 4


def test_report_never_prints_token_or_payload() -> None:
    transport = CrossTransport(a_to_b=200, b_to_a=200)

    report = run_probe(
        BASE_URL,
        token_a=A_TOKEN,
        token_b=B_TOKEN,
        resources=[("task", A_ID, B_ID)],
        transport=transport,
        timeout=5.0,
    )

    text = report.to_text()
    for leaked in (A_TOKEN, B_TOKEN, PAYLOAD_SENTINEL):
        assert leaked not in text
    assert "task" in text
    assert report.to_text().count("200") >= 1


# --------------------------------------------------------------------------- main


def _argv(**overrides) -> list[str]:
    values = {
        "--base-url": BASE_URL,
        "--token-a": A_TOKEN,
        "--token-b": B_TOKEN,
        "--resource": "task:task-a-1:task-b-1",
    }
    values.update(overrides)
    argv: list[str] = []
    for key, value in values.items():
        if value is None:
            continue
        argv.extend([key, value])
    return argv


def test_main_returns_two_when_a_token_missing(capsys) -> None:
    rc = main(_argv(**{"--token-a": None}))

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_returns_two_when_b_token_missing(capsys) -> None:
    rc = main(_argv(**{"--token-b": None}))

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_returns_two_when_no_resource(capsys) -> None:
    rc = main(_argv(**{"--resource": None}))

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_returns_two_on_bad_resource_spec(capsys) -> None:
    rc = main(_argv(**{"--resource": "bogus:a:b"}), transport=CrossTransport())

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_returns_two_on_insecure_base_url(capsys) -> None:
    rc = main(
        _argv(**{"--base-url": "http://staging.example.com"}), transport=CrossTransport()
    )

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_returns_zero_when_isolated(capsys) -> None:
    rc = main(_argv(), transport=CrossTransport(a_to_b=404, b_to_a=403))

    assert rc == 0
    assert "pass" in capsys.readouterr().out


def test_main_returns_one_when_leak(capsys) -> None:
    rc = main(_argv(), transport=CrossTransport(a_to_b=200, b_to_a=404))

    assert rc == 1
    assert "fail" in capsys.readouterr().out


def test_main_example_returns_two(capsys) -> None:
    rc = main(["--example"])

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out
