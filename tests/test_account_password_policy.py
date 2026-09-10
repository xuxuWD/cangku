"""口令弱口令策略。

策略在 `app.accounts.passwords._validate` 中统一实施，因此注册、改密与管理员重置
三条链路自动生效（它们都经过 `hash_password`）。
"""

import pytest

from app.accounts.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    verify_password,
)


def test_strong_passwords_are_accepted() -> None:
    for password in ("correct-horse-battery", "Tr0ub4dor&3xample", "Zq7#mK2$pL"):
        assert hash_password(password)


def test_all_digits_is_rejected() -> None:
    with pytest.raises(PasswordPolicyError, match="纯数字"):
        hash_password("13800000001")


def test_repeated_single_character_is_rejected() -> None:
    with pytest.raises(PasswordPolicyError, match="重复的单一字符"):
        hash_password("a" * 12)


def test_common_password_is_rejected() -> None:
    with pytest.raises(PasswordPolicyError, match="过于常见"):
        hash_password("password123")


def test_common_password_matching_lowercases_input() -> None:
    """比对时把输入转小写后精确查表，因此大小写变体同样被拦截。"""
    with pytest.raises(PasswordPolicyError, match="过于常见"):
        hash_password("PASSWORD123")
    with pytest.raises(PasswordPolicyError, match="过于常见"):
        hash_password("Password123")


def test_known_limitation_variants_are_not_matched_by_common_list() -> None:
    """已知限制：不做变形归一。

    列表收录的是固定字符串；对已收录口令再做追加或更冷门的 leetspeak 变形不会命中。
    该限制写入 API 契约。
    """
    # `password123` 在列表中，但追加字符后的 `password1239` 不在
    assert hash_password("password1239")
    # 列表只收录了最常见的 leetspeak 形式，更长的变形不在其中
    assert hash_password("P@ssw0rd123456")


def test_length_boundaries_still_enforced() -> None:
    assert hash_password("Zq7#mK2$pL")

    with pytest.raises(PasswordPolicyError, match="口令长度"):
        hash_password("Zq7#mK2$p"[: MIN_PASSWORD_LENGTH - 1])
    with pytest.raises(PasswordPolicyError, match="口令长度"):
        hash_password("A" + "b" * MAX_PASSWORD_LENGTH)
    assert hash_password("A" + "b" * (MAX_PASSWORD_LENGTH - 1))


def test_control_characters_still_rejected() -> None:
    with pytest.raises(PasswordPolicyError, match="控制字符"):
        hash_password("line\nbreak-passwords")


def test_length_rule_takes_precedence_over_weak_rules() -> None:
    """过短的纯数字口令应报长度错误，而不是纯数字错误（既有测试依赖此顺序）。"""
    with pytest.raises(PasswordPolicyError, match="口令长度"):
        hash_password("1380000")


def test_verify_password_does_not_apply_policy() -> None:
    """校验函数只做恒定时间比对，不对输入做策略校验，也不能抛异常。"""
    encoded = hash_password("Zq7#mK2$pL")

    assert verify_password("password123", encoded) is False
    assert verify_password("13800000001", encoded) is False
    assert verify_password("a" * 12, encoded) is False
