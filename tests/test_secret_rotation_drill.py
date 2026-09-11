"""密钥轮换演练脚本的离线测试：全部使用注入的假传输层，不发任何真实网络请求。

覆盖：https/本地护栏、令牌指纹、before 落盘、after 三断言、反向用例（旧令牌仍 200 → fail）、
以及「输出与证据文件提示里绝不出现令牌原文」。
"""

from __future__ import annotations

import json

import pytest

from scripts.secret_rotation_drill import (
    DEFAULT_PROBE_PATH,
    DrillConfigError,
    fingerprint,
    main,
    resolve_base_url,
    run_after,
    run_before,
)

BASE_URL = "https://staging.example.com"
PHONE = "+8613800000000"
PASSWORD = "probe-password-value"
OLD_TOKEN = "old-token-secret-value"
NEW_TOKEN = "new-token-secret-value"
PAYLOAD_SENTINEL = "TENANT-B-PAYLOAD-SENTINEL"


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: object = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class DrillTransport:
    """按方法 + Authorization 头路由的假传输层；记录全部调用以便断言。"""

    def __init__(
        self,
        *,
        old_status: int = 401,
        new_status: int = 200,
        login_status: int = 200,
        login_payload: object = None,
        new_token: str = NEW_TOKEN,
    ) -> None:
        self.old_status = old_status
        self.new_status = new_status
        self.login_status = login_status
        self._login_payload = login_payload
        self.new_token = new_token
        self.calls: list[dict[str, object]] = []

    def __call__(self, method, url, *, headers, data=None, params=None, timeout):
        authorization = (headers or {}).get("Authorization", "")
        self.calls.append({"method": method, "url": url, "authorization": authorization})
        if method == "POST":
            if self._login_payload is not None:
                return FakeResponse(self.login_status, self._login_payload)
            return FakeResponse(
                self.login_status,
                {
                    "access_token": self.new_token,
                    "token_type": "Bearer",
                    "tenant_id": "tenant-b",
                    "user_id": "user-b",
                    "role": "employee",
                    "scope": "full",
                },
            )
        if authorization == f"Bearer {OLD_TOKEN}":
            return FakeResponse(self.old_status, {"items": [], "counts": {}})
        if authorization == f"Bearer {self.new_token}":
            return FakeResponse(
                self.new_status, {"items": [{"title": PAYLOAD_SENTINEL}], "counts": {}}
            )
        return FakeResponse(401, {"detail": "unauthorized"})


def _write_token_file(tmp_path):
    path = tmp_path / "token.json"
    path.write_text(
        json.dumps({"access_token": OLD_TOKEN, "base_url": BASE_URL}), encoding="utf-8"
    )
    return path


# --------------------------------------------------------------------------- 护栏


def test_resolve_base_url_requires_https() -> None:
    with pytest.raises(DrillConfigError) as excinfo:
        resolve_base_url("http://staging.example.com")

    assert "HTTPS" in str(excinfo.value)


@pytest.mark.parametrize(
    "base_url", ["https://localhost:8000", "https://127.0.0.1", "https://0.0.0.0"]
)
def test_resolve_base_url_rejects_local_hosts(base_url: str) -> None:
    with pytest.raises(DrillConfigError) as excinfo:
        resolve_base_url(base_url)

    assert "本地" in str(excinfo.value)


def test_resolve_base_url_allows_explicit_overrides() -> None:
    assert resolve_base_url("http://staging.example.com", allow_insecure=True) == (
        "http://staging.example.com"
    )
    assert resolve_base_url("https://localhost:8000", allow_local=True) == (
        "https://localhost:8000"
    )
    assert resolve_base_url("https://staging.example.com/") == "https://staging.example.com"


# --------------------------------------------------------------------------- 指纹


def test_fingerprint_is_stable_and_does_not_reveal_token() -> None:
    value = fingerprint(OLD_TOKEN)

    assert len(value) == 8
    assert value == fingerprint(OLD_TOKEN)
    assert value != fingerprint(NEW_TOKEN)
    assert OLD_TOKEN not in value


# --------------------------------------------------------------------------- before


def test_run_before_writes_token_and_reports_fingerprint(tmp_path) -> None:
    output = tmp_path / "token.json"

    report = run_before(
        BASE_URL,
        phone=PHONE,
        password=PASSWORD,
        output_path=str(output),
        transport=DrillTransport(),
        timeout=5.0,
    )

    assert report.status == "pass"
    assert report.token_fingerprint == fingerprint(NEW_TOKEN)
    stored = json.loads(output.read_text(encoding="utf-8"))
    assert stored["access_token"] == NEW_TOKEN
    text = report.to_text()
    assert NEW_TOKEN not in text
    assert PASSWORD not in text
    assert fingerprint(NEW_TOKEN) in text
    assert "用完即删" in text


def test_run_before_fails_when_login_rejected_and_writes_nothing(tmp_path) -> None:
    output = tmp_path / "token.json"
    transport = DrillTransport(login_status=401, login_payload={"detail": "bad credentials"})

    report = run_before(
        BASE_URL,
        phone=PHONE,
        password=PASSWORD,
        output_path=str(output),
        transport=transport,
        timeout=5.0,
    )

    assert report.status == "fail"
    assert not output.exists()
    assert PASSWORD not in report.to_text()


# --------------------------------------------------------------------------- after


def test_run_after_passes_when_rotation_enforced(tmp_path) -> None:
    token_path = _write_token_file(tmp_path)
    transport = DrillTransport(old_status=401, new_status=200)

    report = run_after(
        BASE_URL,
        phone=PHONE,
        password=PASSWORD,
        token_path=str(token_path),
        probe_path=DEFAULT_PROBE_PATH,
        transport=transport,
        timeout=5.0,
    )

    assert report.status == "pass"
    assert all(check.status == "pass" for check in report.checks)
    # 旧令牌探针与新令牌探针都打到默认受保护路径
    probed = [call for call in transport.calls if call["method"] == "GET"]
    assert len(probed) == 2


def test_run_after_fails_when_old_token_still_valid(tmp_path) -> None:
    """反向用例：轮换后旧令牌仍返回 200，必须判 fail。"""
    token_path = _write_token_file(tmp_path)

    report = run_after(
        BASE_URL,
        phone=PHONE,
        password=PASSWORD,
        token_path=str(token_path),
        transport=DrillTransport(old_status=200, new_status=200),
        timeout=5.0,
    )

    assert report.status == "fail"
    assert any(check.name.startswith("旧令牌") and check.status == "fail" for check in report.checks)


def test_run_after_fails_when_new_token_rejected(tmp_path) -> None:
    token_path = _write_token_file(tmp_path)

    report = run_after(
        BASE_URL,
        phone=PHONE,
        password=PASSWORD,
        token_path=str(token_path),
        transport=DrillTransport(old_status=401, new_status=401),
        timeout=5.0,
    )

    assert report.status == "fail"
    assert any(check.name.startswith("新令牌") and check.status == "fail" for check in report.checks)


def test_run_after_fails_when_relogin_rejected(tmp_path) -> None:
    token_path = _write_token_file(tmp_path)
    transport = DrillTransport(
        old_status=401, login_status=401, login_payload={"detail": "bad credentials"}
    )

    report = run_after(
        BASE_URL,
        phone=PHONE,
        password=PASSWORD,
        token_path=str(token_path),
        transport=transport,
        timeout=5.0,
    )

    assert report.status == "fail"
    assert any(check.name.startswith("重新登录") and check.status == "fail" for check in report.checks)


def test_run_after_fails_when_token_file_missing(tmp_path) -> None:
    report = run_after(
        BASE_URL,
        phone=PHONE,
        password=PASSWORD,
        token_path=str(tmp_path / "missing.json"),
        transport=DrillTransport(),
        timeout=5.0,
    )

    assert report.status == "fail"
    assert report.checks[0].name.startswith("读取")


def test_run_after_never_prints_token_or_payload(tmp_path) -> None:
    token_path = _write_token_file(tmp_path)

    report = run_after(
        BASE_URL,
        phone=PHONE,
        password=PASSWORD,
        token_path=str(token_path),
        transport=DrillTransport(old_status=401, new_status=200),
        timeout=5.0,
    )

    text = report.to_text()
    for leaked in (OLD_TOKEN, NEW_TOKEN, PASSWORD, PAYLOAD_SENTINEL):
        assert leaked not in text


# --------------------------------------------------------------------------- main


def _argv(tmp_path, **overrides) -> list[str]:
    values = {
        "--phase": "before",
        "--base-url": BASE_URL,
        "--phone": PHONE,
        "--password": PASSWORD,
        "--output": str(tmp_path / "token.json"),
    }
    values.update(overrides)
    argv: list[str] = []
    for key, value in values.items():
        if value is None:
            continue
        argv.extend([key, value])
    return argv


def test_main_before_returns_zero_and_hides_token(tmp_path, capsys) -> None:
    rc = main(_argv(tmp_path), transport=DrillTransport())

    assert rc == 0
    output = capsys.readouterr().out
    assert NEW_TOKEN not in output
    assert PASSWORD not in output


def test_main_after_returns_zero_when_rotation_enforced(tmp_path, capsys) -> None:
    token_path = _write_token_file(tmp_path)
    rc = main(
        _argv(tmp_path, **{"--phase": "after", "--output": str(token_path)}),
        transport=DrillTransport(old_status=401, new_status=200),
    )

    assert rc == 0
    assert "pass" in capsys.readouterr().out


def test_main_after_returns_one_when_old_token_survives(tmp_path) -> None:
    token_path = _write_token_file(tmp_path)
    rc = main(
        _argv(tmp_path, **{"--phase": "after", "--output": str(token_path)}),
        transport=DrillTransport(old_status=200, new_status=200),
    )

    assert rc == 1


def test_main_returns_two_on_insecure_base_url(capsys) -> None:
    rc = main(
        [
            "--phase",
            "before",
            "--base-url",
            "http://staging.example.com",
            "--phone",
            PHONE,
            "--password",
            PASSWORD,
            "--output",
            "token.json",
        ],
        transport=DrillTransport(),
    )

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_returns_two_when_required_args_missing(capsys) -> None:
    rc = main(["--phase", "before", "--base-url", BASE_URL], transport=DrillTransport())

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_example_returns_two_and_uses_no_network(capsys) -> None:
    rc = main(["--example"])

    assert rc == 2
    output = capsys.readouterr().out
    assert "护栏" in output
