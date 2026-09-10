"""TOTP 算法层（RFC 4226 / RFC 6238）。

只用标准库实现，不引入新依赖。
"""

import base64
from datetime import UTC, datetime, timedelta

import pytest

from app.accounts.totp import (
    DIGITS,
    STEP_SECONDS,
    current_step,
    generate_secret,
    hotp,
    normalize_code,
    provisioning_uri,
    verify_code,
)

# RFC 6238 附录 B 的 SHA1 种子：ASCII "12345678901234567890"
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)


def test_constants_match_rfc_recommendations() -> None:
    assert DIGITS == 6
    assert STEP_SECONDS == 30


def test_generate_secret_is_base32_without_padding() -> None:
    secret = generate_secret()

    assert len(secret) == 32  # 20 字节 → 32 个 base32 字符
    assert secret == secret.upper()
    assert "=" not in secret
    assert set(secret) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    assert generate_secret() != generate_secret()


@pytest.mark.parametrize(
    ("unix_time", "expected_six_digits"),
    [
        (59, "287082"),
        (1111111109, "081804"),
        (1111111111, "050471"),
        (1234567890, "005924"),
        (2000000000, "279037"),
        (20000000000, "353130"),
    ],
)
def test_hotp_matches_rfc6238_vectors_truncated_to_six_digits(unix_time: int, expected_six_digits: str) -> None:
    """RFC 6238 给出的是 8 位码；6 位码等于其末 6 位（等价于对 10^6 取模）。"""
    step = unix_time // STEP_SECONDS

    assert hotp(RFC_SECRET, step) == expected_six_digits


def test_current_step_advances_every_thirty_seconds() -> None:
    assert current_step(NOW) == int(NOW.timestamp()) // STEP_SECONDS
    assert current_step(NOW + timedelta(seconds=29)) == current_step(NOW)
    assert current_step(NOW + timedelta(seconds=30)) == current_step(NOW) + 1


def test_verify_code_accepts_current_and_adjacent_steps() -> None:
    secret = generate_secret()
    step = current_step(NOW)

    assert verify_code(secret, hotp(secret, step), at=NOW) == step
    assert verify_code(secret, hotp(secret, step - 1), at=NOW) == step - 1
    assert verify_code(secret, hotp(secret, step + 1), at=NOW) == step + 1


def test_verify_code_rejects_steps_outside_window() -> None:
    secret = generate_secret()
    step = current_step(NOW)

    assert verify_code(secret, hotp(secret, step - 2), at=NOW) is None
    assert verify_code(secret, hotp(secret, step + 2), at=NOW) is None


def test_verify_code_rejects_malformed_code_or_secret() -> None:
    secret = generate_secret()

    for bad_code in ("", "12345", "1234567", "abcdef", None, 123456):
        assert verify_code(secret, bad_code, at=NOW) is None

    assert verify_code("not-base32!!!", "123456", at=NOW) is None
    assert verify_code("", "123456", at=NOW) is None


def test_verify_code_accepts_spaced_input() -> None:
    secret = generate_secret()
    step = current_step(NOW)
    spaced = f" {hotp(secret, step)[:3]} {hotp(secret, step)[3:]} "

    assert verify_code(secret, spaced, at=NOW) == step


def test_normalize_code() -> None:
    assert normalize_code("123456") == "123456"
    assert normalize_code(" 123 456 ") == "123456"
    assert normalize_code("12345") is None
    assert normalize_code("1234567") is None
    assert normalize_code("abcdef") is None
    assert normalize_code("") is None
    assert normalize_code(None) is None


def test_provisioning_uri_is_well_formed() -> None:
    uri = provisioning_uri("ABCDEFGHIJKLMNOP", account_name="138****0001")

    assert uri.startswith("otpauth://totp/")
    assert "secret=ABCDEFGHIJKLMNOP" in uri
    assert f"digits={DIGITS}" in uri
    assert f"period={STEP_SECONDS}" in uri
    assert "138****0001" in uri


def test_provisioning_uri_never_carries_plain_phone() -> None:
    uri = provisioning_uri("ABCDEFGHIJKLMNOP", account_name="138****0001")

    assert "13800000001" not in uri
