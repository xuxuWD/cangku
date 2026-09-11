"""TOTP 种子静态加密的离线测试（不依赖数据库、不发网络请求）。

覆盖：往返加解密、随机 nonce、历史明文只读兼容、篡改与密钥不匹配 fail-closed、
空密钥退化为不加密，以及「密文不得包含明文种子」。
"""

from __future__ import annotations

import base64

import pytest

from app.accounts.secrets import (
    CIPHER_PREFIX,
    SecretCipher,
    TotpSecretError,
    build_totp_cipher,
)

MASTER_KEY = "k" * 40
SECRET = "JBSWY3DPEHPK3PXP"


def test_round_trip_returns_original_plaintext() -> None:
    cipher = SecretCipher(MASTER_KEY)

    stored = cipher.encrypt(SECRET)

    assert stored.startswith(CIPHER_PREFIX)
    assert stored != SECRET
    assert cipher.decrypt(stored) == SECRET


def test_ciphertext_hides_plaintext_and_uses_random_nonce() -> None:
    cipher = SecretCipher(MASTER_KEY)

    first = cipher.encrypt(SECRET)
    second = cipher.encrypt(SECRET)

    # 判定依据：密文不得包含明文种子；同一明文两次加密必须不同（随机 nonce）。
    assert SECRET not in first
    assert first != second
    assert cipher.decrypt(first) == cipher.decrypt(second) == SECRET


def test_legacy_plaintext_is_readable_but_new_writes_are_encrypted() -> None:
    cipher = SecretCipher(MASTER_KEY)

    # 判定依据：历史明文（无 v1: 前缀）必须可读，否则升级即锁死既有账号。
    assert cipher.decrypt(SECRET) == SECRET
    assert cipher.decrypt("GEZDGNBVGY3TQOJQ") == "GEZDGNBVGY3TQOJQ"


def test_tampered_ciphertext_fails_closed() -> None:
    cipher = SecretCipher(MASTER_KEY)
    stored = cipher.encrypt(SECRET)
    payload = bytearray(base64.b64decode(stored[len(CIPHER_PREFIX) :]))
    payload[-1] ^= 0x01
    tampered = CIPHER_PREFIX + base64.b64encode(bytes(payload)).decode("ascii")

    with pytest.raises(TotpSecretError):
        cipher.decrypt(tampered)


def test_wrong_key_fails_closed() -> None:
    stored = SecretCipher(MASTER_KEY).encrypt(SECRET)

    with pytest.raises(TotpSecretError):
        SecretCipher("z" * 40).decrypt(stored)


def test_malformed_ciphertext_fails_closed() -> None:
    cipher = SecretCipher(MASTER_KEY)

    for bad in (f"{CIPHER_PREFIX}not-base64!!", f"{CIPHER_PREFIX}AAAA"):
        with pytest.raises(TotpSecretError):
            cipher.decrypt(bad)


def test_constructor_and_encrypt_reject_empty_values() -> None:
    with pytest.raises(TotpSecretError):
        SecretCipher("")
    with pytest.raises(TotpSecretError):
        SecretCipher("   ")

    cipher = SecretCipher(MASTER_KEY)
    with pytest.raises(TotpSecretError):
        cipher.encrypt("")
    with pytest.raises(TotpSecretError):
        cipher.decrypt("")


def test_build_totp_cipher_returns_none_without_key_material() -> None:
    # 判定依据：开发环境未配置主密钥时退化为不加密；生产已由 validate_runtime_settings
    # 强制要求备份加密密钥，因此生产必然加密。
    assert build_totp_cipher("") is None
    assert build_totp_cipher("   ") is None
    assert isinstance(build_totp_cipher(MASTER_KEY), SecretCipher)
