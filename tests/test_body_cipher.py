"""`BodyCipher`（正文密文列）加解密口径（规格 §3.4 约束 1 / §4.1.6-1.1）。

判据：AES-256-GCM、布局 `nonce(12B) ‖ ciphertext ‖ tag(16B)`（overhead 恒 28 字节）；
**篡改密文 / 错密钥必须抛异常**（fail-closed，不得静默返回明文）。
"""

from __future__ import annotations

import base64
import os

import pytest

from app.tool_execution.body_cipher import BodyCipher
from app.tool_execution.errors import BodyCipherError, ToolExecutionConfigError


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
