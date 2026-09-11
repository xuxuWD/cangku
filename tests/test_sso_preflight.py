"""SSO 预检脚本测试：配置 fail-closed、离线/联网分支与「不打印 client_secret」。

联网分支全部通过注入的假传输层验证，测试本身不发任何网络请求。
"""

from __future__ import annotations

import sys
import time
from email.utils import formatdate

import pytest

from app.settings import Settings
from scripts.sso_preflight import PreflightReport, main, run_preflight

ISSUER = "https://idp.example"
CLIENT_SECRET = "super-secret-client-value"


def make_settings(**overrides) -> Settings:
    values: dict[str, object] = {
        "sso_enabled": True,
        "sso_issuer": ISSUER,
        "sso_authorization_endpoint": f"{ISSUER}/authorize",
        "sso_token_endpoint": f"{ISSUER}/token",
        "sso_jwks_uri": f"{ISSUER}/jwks",
        "sso_client_id": "workbench-client",
        "sso_client_secret": CLIENT_SECRET,
        "sso_redirect_uri": "https://workbench.example/auth/callback",
    }
    values.update(overrides)
    return Settings(**values)


class FakeResponse:
    def __init__(self, *, status_code: int = 200, payload=None, headers=None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers if headers is not None else {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def discovery_document(**overrides) -> dict:
    values: dict[str, object] = {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "jwks_uri": f"{ISSUER}/jwks",
        "response_types_supported": ["code"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
    }
    values.update(overrides)
    return values


def jwks_document(**overrides) -> dict:
    key = {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": "kid-1", "n": "abc", "e": "AQAB"}
    key.update(overrides)
    return {"keys": [key]}


def make_transport(*, discovery=None, jwks=None, date_header: str | None = "auto"):
    """默认带上当前时刻的 Date 头，让时钟偏移检查走 pass 分支。"""
    resolved_date = formatdate(usegmt=True) if date_header == "auto" else date_header

    def transport(method, url, *, headers, data=None, params=None, timeout):
        if url.endswith("/.well-known/openid-configuration"):
            return FakeResponse(
                payload=discovery if discovery is not None else discovery_document(),
                headers={"Date": resolved_date} if resolved_date else {},
            )
        if url.endswith("/jwks"):
            return FakeResponse(payload=jwks if jwks is not None else jwks_document())
        return FakeResponse(status_code=404, payload={})

    return transport


def find(report: PreflightReport, name: str) -> str:
    for check in report.checks:
        if check.name == name:
            return check.status
    raise AssertionError(f"未找到检查项：{name}")


def test_disabled_reports_skipped() -> None:
    report = run_preflight(Settings(sso_enabled=False))

    assert report.status == "skipped"
    assert report.checks[0].name == "SSO 未启用"
    assert report.checks[0].status == "skipped"


def test_enabled_but_incomplete_fails_closed() -> None:
    report = run_preflight(Settings(sso_enabled=True))

    assert report.status == "fail"
    assert any(check.status == "fail" for check in report.checks)


def test_trust_idp_mfa_emits_warning_but_still_passes() -> None:
    report = run_preflight(
        make_settings(sso_trust_idp_mfa=True),
        offline=True,
        transport=lambda *a, **k: pytest.fail("--offline 不应发起网络请求"),
    )

    assert report.status == "pass"
    assert any(check.status == "warn" for check in report.checks)


def test_offline_never_uses_transport() -> None:
    report = run_preflight(
        make_settings(),
        offline=True,
        transport=lambda *a, **k: pytest.fail("--offline 不应发起网络请求"),
    )

    assert report.status == "pass"


def test_online_matching_metadata_passes() -> None:
    report = run_preflight(make_settings(), transport=make_transport())

    assert report.status == "pass"
    assert find(report, "OIDC 发现文档") == "pass"
    assert find(report, "发现文档端点一致") == "pass"
    assert find(report, "JWKS 可用密钥") == "pass"


def test_online_mismatched_endpoint_fails() -> None:
    discovery = discovery_document(token_endpoint="https://evil.example/token")
    report = run_preflight(make_settings(), transport=make_transport(discovery=discovery))

    assert report.status == "fail"
    assert find(report, "发现文档端点一致") == "fail"


def test_online_mismatched_issuer_fails() -> None:
    discovery = discovery_document(issuer="https://evil.example")
    report = run_preflight(make_settings(), transport=make_transport(discovery=discovery))

    assert report.status == "fail"
    assert find(report, "发现文档 issuer 一致") == "fail"


def test_online_jwks_without_usable_key_fails() -> None:
    report = run_preflight(
        make_settings(),
        transport=make_transport(jwks={"keys": [{"kty": "EC", "kid": "kid-1"}]}),
    )

    assert report.status == "fail"
    assert find(report, "JWKS 可用密钥") == "fail"


def test_online_unsupported_algorithm_fails() -> None:
    discovery = discovery_document(id_token_signing_alg_values_supported=["ES256"])
    report = run_preflight(make_settings(), transport=make_transport(discovery=discovery))

    assert report.status == "fail"
    assert find(report, "ID Token 签名算法") == "fail"


def test_online_network_failure_fails_closed() -> None:
    def broken(*_a, **_k):
        raise RuntimeError("connection refused")

    report = run_preflight(make_settings(), transport=broken)

    assert report.status == "fail"


def test_report_never_prints_client_secret() -> None:
    report = run_preflight(make_settings(), transport=make_transport())

    text = report.to_text()
    assert CLIENT_SECRET not in text
    assert "idp.example" in text


def test_offline_report_never_prints_client_secret() -> None:
    report = run_preflight(make_settings(), offline=True)

    assert CLIENT_SECRET not in report.to_text()


# --- 作用域 / 回调归属 / 授权码 / PKCE / 认证方式 / 时钟偏移 --------------------


def test_scope_missing_email_fails() -> None:
    report = run_preflight(make_settings(sso_scopes="openid profile"), offline=True)

    assert report.status == "fail"
    assert find(report, "请求作用域") == "fail"


def test_redirect_uri_guidance_is_warning_not_failure() -> None:
    report = run_preflight(make_settings(), offline=True)

    # 浏览器跳转目标是客户端，不能硬性要求等于后端接口路径，因此只提示。
    assert report.status == "pass"
    assert find(report, "回调地址归属") == "warn"


def test_discovery_without_authorization_code_fails() -> None:
    discovery = discovery_document(response_types_supported=["id_token"])
    report = run_preflight(make_settings(), transport=make_transport(discovery=discovery))

    assert report.status == "fail"
    assert find(report, "授权码模式") == "fail"


def test_pkce_explicitly_without_s256_fails_but_absent_only_warns() -> None:
    explicit = discovery_document(code_challenge_methods_supported=["plain"])
    report = run_preflight(make_settings(), transport=make_transport(discovery=explicit))
    assert find(report, "PKCE S256") == "fail"

    silent = discovery_document()
    silent.pop("code_challenge_methods_supported")
    report2 = run_preflight(make_settings(), transport=make_transport(discovery=silent))
    assert find(report2, "PKCE S256") == "warn"
    assert report2.status == "pass"


def test_token_auth_method_must_support_client_secret_post() -> None:
    explicit = discovery_document(token_endpoint_auth_methods_supported=["client_secret_basic"])
    report = run_preflight(make_settings(), transport=make_transport(discovery=explicit))
    assert find(report, "令牌端点认证方式") == "fail"

    silent = discovery_document()
    silent.pop("token_endpoint_auth_methods_supported")
    report2 = run_preflight(make_settings(), transport=make_transport(discovery=silent))
    assert find(report2, "令牌端点认证方式") == "warn"
    assert report2.status == "pass"


def test_clock_skew_thresholds() -> None:
    far = formatdate(time.time() - 600, usegmt=True)
    report = run_preflight(make_settings(), transport=make_transport(date_header=far))
    assert find(report, "时钟偏移") == "fail"

    near = formatdate(time.time() - 30, usegmt=True)
    report2 = run_preflight(make_settings(), transport=make_transport(date_header=near))
    assert find(report2, "时钟偏移") == "warn"
    assert report2.status == "pass"

    missing = run_preflight(make_settings(), transport=make_transport(date_header=None))
    assert find(missing, "时钟偏移") == "warn"


# --- main() 退出码 -------------------------------------------------------------


def test_main_example_exits_nonzero(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["sso_preflight.py", "--example"])

    assert main() == 1
    assert CLIENT_SECRET not in capsys.readouterr().out


def test_main_offline_complete_exits_zero(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["sso_preflight.py", "--offline"])
    monkeypatch.setenv("WORKBENCH_SSO_ENABLED", "true")
    monkeypatch.setenv("WORKBENCH_SSO_ISSUER", ISSUER)
    monkeypatch.setenv("WORKBENCH_SSO_AUTHORIZATION_ENDPOINT", f"{ISSUER}/authorize")
    monkeypatch.setenv("WORKBENCH_SSO_TOKEN_ENDPOINT", f"{ISSUER}/token")
    monkeypatch.setenv("WORKBENCH_SSO_JWKS_URI", f"{ISSUER}/jwks")
    monkeypatch.setenv("WORKBENCH_SSO_CLIENT_ID", "workbench-client")
    monkeypatch.setenv("WORKBENCH_SSO_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("WORKBENCH_SSO_REDIRECT_URI", "https://workbench.example/auth/callback")

    assert main() == 0
    output = capsys.readouterr().out
    assert CLIENT_SECRET not in output
