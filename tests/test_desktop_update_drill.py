"""桌面端自动更新链路演练脚本的离线测试：全部使用注入的假传输层，不发任何真实网络请求。

覆盖：HTTPS / 本地主机护栏、频道白名单、元数据形状解析与 fail-closed、
sha512 完整性比对（含反向用例）、版本递增判定、体积上限，
以及「报告与退出码不含密钥、且如实把人工步骤标为 skipped」。
"""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from scripts.desktop_update_drill import (
    DEFAULT_CHANNEL,
    RUN_CHANNELS,
    DrillConfigError,
    decode_sha512,
    main,
    metadata_name,
    parse_update_metadata,
    parse_version,
    resolve_update_url,
    run_drill,
    sha512_base64,
)

UPDATE_URL = "https://updates.example.com/workbench"
ARTIFACT_BYTES = b"fake-nsis-installer-payload"
ARTIFACT_NAME = "Workbench-Setup-1.0.1.exe"


def metadata_text(
    *,
    version: str = "1.0.1",
    name: str = ARTIFACT_NAME,
    payload: bytes = ARTIFACT_BYTES,
    sha512: str | None = None,
    size: int | None = None,
) -> str:
    digest = sha512 if sha512 is not None else sha512_base64(payload)
    declared_size = len(payload) if size is None else size
    return (
        f"version: {version}\n"
        "files:\n"
        f"  - url: {name}\n"
        f"    sha512: {digest}\n"
        f"    size: {declared_size}\n"
        f"path: {name}\n"
        f"sha512: {digest}\n"
        "releaseDate: '2026-09-11T00:00:00.000Z'\n"
    )


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content


class UpdateTransport:
    """按 URL 路由的假传输层：元数据与安装包各自可配状态码与正文。"""

    def __init__(
        self,
        *,
        metadata_status: int = 200,
        metadata_body: str | None = None,
        artifact_status: int = 200,
        artifact_body: bytes = ARTIFACT_BYTES,
    ) -> None:
        self.metadata_status = metadata_status
        self._metadata_body = metadata_body
        self.artifact_status = artifact_status
        self.artifact_body = artifact_body
        self.calls: list[str] = []

    def __call__(self, method, url, *, headers, data=None, params=None, timeout):
        self.calls.append(url)
        if url.endswith(".yml"):
            body = self._metadata_body
            if body is None:
                body = metadata_text()
            return FakeResponse(self.metadata_status, body.encode("utf-8"))
        return FakeResponse(self.artifact_status, self.artifact_body)


def test_resolve_update_url_enforces_https_and_non_local() -> None:
    assert resolve_update_url(f"{UPDATE_URL}/") == UPDATE_URL

    with pytest.raises(DrillConfigError):
        resolve_update_url("http://updates.example.com/workbench")
    with pytest.raises(DrillConfigError):
        resolve_update_url("https://localhost:8000/workbench")
    with pytest.raises(DrillConfigError):
        resolve_update_url("")

    assert (
        resolve_update_url("http://updates.example.com/workbench", allow_insecure=True)
        == "http://updates.example.com/workbench"
    )
    assert (
        resolve_update_url("https://127.0.0.1/workbench", allow_local=True)
        == "https://127.0.0.1/workbench"
    )


def test_metadata_name_follows_channel_whitelist() -> None:
    assert DEFAULT_CHANNEL == "latest"
    assert RUN_CHANNELS == ("latest", "beta", "alpha")
    assert metadata_name("latest") == "latest.yml"
    assert metadata_name("beta") == "beta.yml"
    with pytest.raises(DrillConfigError):
        metadata_name("nightly")


def test_parse_version_rejects_floating_refs_and_accepts_semver() -> None:
    assert parse_version("1.2.3") == (1, 2, 3)
    assert parse_version("1.2.3-beta.1") == (1, 2, 3)
    assert parse_version("v1.2.3") == (1, 2, 3)

    for floating in ("latest", "main", "HEAD", "master", "", "1.2"):
        assert parse_version(floating) is None


def test_decode_sha512_requires_real_64_byte_digest() -> None:
    digest = sha512_base64(ARTIFACT_BYTES)
    assert decode_sha512(digest) == hashlib.sha512(ARTIFACT_BYTES).digest()

    for bad in ("", "not-base64!!", base64.b64encode(b"short").decode("ascii")):
        with pytest.raises(DrillConfigError):
            decode_sha512(bad)


def test_parse_update_metadata_reads_electron_updater_shape() -> None:
    parsed = parse_update_metadata(metadata_text())

    assert parsed["version"] == "1.0.1"
    assert parsed["path"] == ARTIFACT_NAME
    assert parsed["sha512"] == sha512_base64(ARTIFACT_BYTES)
    assert parsed["files"] == [
        {"url": ARTIFACT_NAME, "sha512": sha512_base64(ARTIFACT_BYTES), "size": len(ARTIFACT_BYTES)}
    ]


def test_parse_update_metadata_fails_closed_on_missing_or_malformed() -> None:
    with pytest.raises(DrillConfigError):
        parse_update_metadata("path: Setup.exe\nsha512: abc\n")
    with pytest.raises(DrillConfigError):
        parse_update_metadata("version: 1.0.1\nfiles:\n  - url: Setup.exe\n")
    with pytest.raises(DrillConfigError):
        parse_update_metadata("version: 1.0.1\npath: Setup.exe\nsha512: abc\nfiles: []\n")
    with pytest.raises(DrillConfigError):
        parse_update_metadata("just a bare line\n")


def test_run_drill_passes_when_feed_and_artifact_are_consistent() -> None:
    report = run_drill(
        UPDATE_URL,
        current_version="1.0.0",
        transport=UpdateTransport(),
    )

    assert report.status == "pass"
    by_name = {check.name: check for check in report.checks}
    assert by_name["更新元数据可达"].status == "pass"
    assert by_name["元数据形状"].status == "pass"
    assert by_name["版本递增"].status == "pass"
    assert by_name["安装包完整性（sha512）"].status == "pass"
    assert by_name["安装包大小一致"].status == "pass"
    # 真实安装环节必须如实标为人工/未跑，不得计为 pass。
    manual = [check for check in report.checks if check.status == "skipped"]
    assert manual, "必须给出人工步骤的 skipped 清单"
    assert any("旧版" in check.name for check in manual)


def test_run_drill_fails_when_metadata_hash_does_not_match_artifact() -> None:
    transport = UpdateTransport(metadata_body=metadata_text(sha512=sha512_base64(b"other")))

    report = run_drill(UPDATE_URL, current_version="1.0.0", transport=transport)

    assert report.status == "fail"
    assert any(
        check.name == "安装包完整性（sha512）" and check.status == "fail" for check in report.checks
    )


def test_run_drill_fails_when_artifact_missing_or_metadata_unreachable() -> None:
    missing = run_drill(
        UPDATE_URL, current_version="1.0.0", transport=UpdateTransport(artifact_status=404)
    )
    assert missing.status == "fail"

    unreachable = run_drill(
        UPDATE_URL, current_version="1.0.0", transport=UpdateTransport(metadata_status=503)
    )
    assert unreachable.status == "fail"
    by_name = {check.name: check for check in unreachable.checks}
    assert by_name["更新元数据可达"].status == "fail"


def test_run_drill_fails_on_size_mismatch_and_oversized_artifact() -> None:
    size_mismatch = run_drill(
        UPDATE_URL, current_version="1.0.0", transport=UpdateTransport(metadata_body=metadata_text(size=1))
    )
    assert size_mismatch.status == "fail"

    oversized = run_drill(
        UPDATE_URL, current_version="1.0.0", transport=UpdateTransport(), max_bytes=4
    )
    assert oversized.status == "fail"
    assert any("体积" in check.name for check in oversized.checks)


def test_run_drill_fails_when_version_not_greater() -> None:
    report = run_drill(UPDATE_URL, current_version="1.0.1", transport=UpdateTransport())

    assert report.status == "fail"
    by_name = {check.name: check for check in report.checks}
    assert by_name["版本递增"].status == "fail"


def test_run_drill_skips_version_check_without_current_version() -> None:
    report = run_drill(UPDATE_URL, transport=UpdateTransport())

    by_name = {check.name: check for check in report.checks}
    assert by_name["版本递增"].status == "skipped"
    assert report.status == "pass"


def test_run_drill_metadata_phase_does_not_download_artifact() -> None:
    transport = UpdateTransport()

    report = run_drill(
        UPDATE_URL, current_version="1.0.0", phase="metadata", transport=transport
    )

    assert report.status == "pass"
    assert all(url.endswith(".yml") for url in transport.calls)
    assert any("安装包完整性（sha512）" == check.name and check.status == "skipped" for check in report.checks)


def test_report_never_echoes_url_query_or_credentials() -> None:
    secret = "SECRET-TOKEN-VALUE"
    transport = UpdateTransport(metadata_body=metadata_text())

    report = run_drill(
        f"https://updates.example.com/workbench?a={secret}",
        current_version="1.0.0",
        transport=transport,
    )

    assert secret not in report.to_text()
    assert secret not in json.dumps(report.to_dict(), ensure_ascii=False)


def test_run_drill_guards_run_before_any_request() -> None:
    transport = UpdateTransport()

    with pytest.raises(DrillConfigError):
        run_drill("http://updates.example.com/workbench", transport=transport)

    assert transport.calls == []


def test_run_drill_honours_allow_flags_for_insecure_local_feed() -> None:
    # 回归：main 放行的 http + 本地组合，run_drill 内部二次校验也必须沿用同一组放行标志。
    report = run_drill(
        "http://127.0.0.1:8000/workbench",
        current_version="1.0.0",
        transport=UpdateTransport(),
        allow_insecure=True,
        allow_local=True,
    )

    assert report.status == "pass"


def test_main_exit_codes_and_example(capsys) -> None:
    assert main(["--example"]) == 2
    assert "fail-closed" in capsys.readouterr().out

    assert main(["--update-url", "http://updates.example.com/workbench"]) == 2
    assert main(["--update-url", UPDATE_URL, "--channel", "nightly"]) == 2


def test_main_returns_zero_on_pass_with_injected_transport() -> None:
    code = main(
        ["--update-url", UPDATE_URL, "--current-version", "1.0.0"],
        transport=UpdateTransport(),
    )

    assert code == 0
