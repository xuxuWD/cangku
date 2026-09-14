"""`BodyCipher`（正文密文列）加解密口径（规格 §3.4 约束 1 / §4.1.6-1.1）。

判据：AES-256-GCM、布局 `nonce(12B) ‖ ciphertext ‖ tag(16B)`（overhead 恒 28 字节）；
**篡改密文 / 错密钥必须抛异常**（fail-closed，不得静默返回明文）；
**双密钥窗口**（§3.4 约束 1）：新密钥加密、旧密钥**仅用于解密**，窗口内不得因轮换导致解密失败。
"""

from __future__ import annotations

import base64
import os

import pytest

from app.settings import parse_previous_body_keys
from app.tool_execution.body_cipher import BodyCipher, rotation_window_seconds
from app.tool_execution.errors import BodyCipherError, ToolExecutionConfigError
from app.workforce.models import MAX_APPROVAL_TIMEOUT_MINUTES


def _key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def test_roundtrip_matches_layout_overhead() -> None:
    cipher = BodyCipher.from_base64(_key())
    blob = cipher.encrypt("机密正文")
    assert isinstance(blob, bytes)
    # overhead 恒为 28 字节（nonce 12 + tag 16）。
    assert len(blob) == len("机密正文".encode("utf-8")) + 28
    assert cipher.decrypt(blob) == "机密正文"


def test_nonce_is_random_so_ciphertext_differs() -> None:
    cipher = BodyCipher.from_base64(_key())
    assert cipher.encrypt("同一正文") != cipher.encrypt("同一正文")


def test_tampered_ciphertext_raises() -> None:
    cipher = BodyCipher.from_base64(_key())
    blob = bytearray(cipher.encrypt("正文"))
    blob[-1] ^= 0x01
    with pytest.raises(BodyCipherError):
        cipher.decrypt(bytes(blob))


def test_wrong_key_raises() -> None:
    blob = BodyCipher.from_base64(_key()).encrypt("正文")
    with pytest.raises(BodyCipherError):
        BodyCipher.from_base64(_key()).decrypt(blob)


def test_short_blob_raises() -> None:
    cipher = BodyCipher.from_base64(_key())
    with pytest.raises(BodyCipherError):
        cipher.decrypt(b"short")


def test_empty_plaintext_rejected() -> None:
    cipher = BodyCipher.from_base64(_key())
    with pytest.raises(BodyCipherError):
        cipher.encrypt("")


def test_invalid_key_material_rejected() -> None:
    with pytest.raises(ToolExecutionConfigError):
        BodyCipher.from_base64("")
    with pytest.raises(ToolExecutionConfigError):
        BodyCipher.from_base64("not-base64!!")
    with pytest.raises(ToolExecutionConfigError):
        BodyCipher.from_base64(base64.b64encode(os.urandom(16)).decode("ascii"))
    with pytest.raises(ToolExecutionConfigError):
        BodyCipher(os.urandom(16))


# ------------------------------------------- 双密钥窗口（§3.4 约束 1 / §9.6 P4）


def test_rotation_window_decrypts_old_ciphertext_with_previous_key() -> None:
    """轮换期：**新密钥加密**，旧密文仍可由**旧密钥**解密（窗口内不得因轮换解密失败）。"""
    old_key = _key()
    old_cipher = BodyCipher.from_base64(old_key)
    old_blob = old_cipher.encrypt("轮换前的正文")

    rotated = BodyCipher.from_base64(_key(), previous=(old_key,))

    assert rotated.decrypt(old_blob) == "轮换前的正文"
    # 旧密钥**只**用于解密：它单独解不开新密钥产出的密文（证明加密确实换成了新密钥）。
    new_blob = rotated.encrypt("轮换后的正文")
    with pytest.raises(BodyCipherError):
        old_cipher.decrypt(new_blob)
    assert rotated.decrypt(new_blob) == "轮换后的正文"


def test_rotation_window_without_previous_key_fails_closed() -> None:
    """对照（窗口外/未保留旧密钥）：只用活动密钥解密旧密文 → `BodyCipherError`，绝不静默降级。"""
    old_blob = BodyCipher.from_base64(_key()).encrypt("轮换前的正文")
    with pytest.raises(BodyCipherError):
        BodyCipher.from_base64(_key()).decrypt(old_blob)


def test_rotation_window_is_max_approval_timeout_plus_cleanup_interval() -> None:
    """窗口长度 = **最大审批超时 + 清理周期**（§3.4 约束 1；清理周期口径见 §8 U16）。"""
    assert (
        rotation_window_seconds(
            approval_timeout_minutes=MAX_APPROVAL_TIMEOUT_MINUTES,
            cleanup_interval_seconds=60,
        )
        == MAX_APPROVAL_TIMEOUT_MINUTES * 60 + 60
    )


# ------------------------------- 旧密钥多值配置（§8 U22：WORKBENCH_BODY_ENCRYPTION_PREVIOUS_KEYS）


def test_previous_keys_config_is_comma_separated_and_blank_means_none() -> None:
    """多值格式 = **逗号分隔**（base64 无逗号，分隔无歧义）；空 / 空白 / 仅分隔符 ⇒ 空列表。"""
    first, second = _key(), _key()
    assert parse_previous_body_keys("") == []
    assert parse_previous_body_keys("   ") == []
    assert parse_previous_body_keys(" , ") == []
    assert parse_previous_body_keys(f" {first} ,{second}, ") == [first, second]


def test_previous_keys_config_parses_into_usable_previous_keys() -> None:
    """配置串经解析后可交给 `BodyCipher.from_base64` 解密旧密文（与主密钥同口径的 base64）。"""
    old_key = _key()
    old_blob = BodyCipher.from_base64(old_key).encrypt("轮换前的正文")

    rotated = BodyCipher.from_base64(
        _key(), previous=parse_previous_body_keys(f" {old_key} ")
    )

    assert rotated.decrypt(old_blob) == "轮换前的正文"
