import pytest

from app.accounts.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    _SCRYPT_N,
    _SCRYPT_P,
    _SCRYPT_R,
    hash_password,
    verify_password,
)


def test_hash_then_verify_succeeds() -> None:
    encoded = hash_password("correct-horse-battery")

    assert verify_password("correct-horse-battery", encoded) is True


def test_wrong_password_is_rejected() -> None:
    encoded = hash_password("correct-horse-battery")

    assert verify_password("wrong-horse-battery", encoded) is False


def test_same_password_hashes_differently_because_of_salt() -> None:
    assert hash_password("correct-horse-battery") != hash_password("correct-horse-battery")


def test_password_length_policy_is_enforced() -> None:
    with pytest.raises(PasswordPolicyError, match="口令长度"):
        hash_password("short")
    with pytest.raises(PasswordPolicyError, match="口令长度"):
        hash_password("x" * (MAX_PASSWORD_LENGTH + 1))
    with pytest.raises(PasswordPolicyError, match="控制字符"):
        hash_password("line\nbreak-passwords")


def test_verify_returns_false_for_damaged_encoding() -> None:
    assert verify_password("correct-horse-battery", "not-a-valid-encoding") is False
    assert verify_password("correct-horse-battery", "") is False


def test_minimum_length_constant_matches_policy() -> None:
    with pytest.raises(PasswordPolicyError):
        hash_password("x" * (MIN_PASSWORD_LENGTH - 1))


def test_verify_rejects_tampered_parameters_without_hanging() -> None:
    import base64 as _base64

    salt = _base64.urlsafe_b64encode(b"0123456789abcdef").decode().rstrip("=")
    digest = _base64.urlsafe_b64encode(b"s" * 32).decode().rstrip("=")

    assert verify_password("correct-horse-battery", f"scrypt${_SCRYPT_N}${_SCRYPT_R}$1000${salt}${digest}") is False
    assert verify_password("correct-horse-battery", f"scrypt$1024${_SCRYPT_R}${_SCRYPT_P}${salt}${digest}") is False
    assert verify_password("correct-horse-battery", f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt}${digest}") is False


def test_verify_rejects_valid_format_with_changed_hash() -> None:
    encoded = hash_password("correct-horse-battery")
    scheme, n, r, p, salt, digest = encoded.split("$")
    flipped = ("A" if digest[0] != "A" else "B") + digest[1:]

    assert verify_password("correct-horse-battery", "$".join([scheme, n, r, p, salt, flipped])) is False


def test_hash_password_rejects_non_string() -> None:
    with pytest.raises(PasswordPolicyError, match="必须是文本"):
        hash_password(12345)
