import pytest

from app.accounts.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
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
