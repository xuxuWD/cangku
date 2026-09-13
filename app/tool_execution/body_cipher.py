"""受控正文密文列（`body_ciphertext`）的应用层 AEAD 封套（规格 §3.4 约束 1）。

算法与布局**定死**：AES-256-GCM；`body_ciphertext` = `nonce(12B) ‖ ciphertext ‖ tag(16B)`
（overhead 恒 28 字节）。密钥来自独立配置 `WORKBENCH_BODY_ENCRYPTION_KEY`
（32 字节原始密钥的 base64），**不复用** `backup_encryption_key`（单一职责）。

fail-closed：加解密失败一律抛异常，**绝不静默降级**；明文不进日志 / 审计 / 错误信息。
"""

from __future__ import annotations

import base64
import binascii
import os

from .errors import BodyCipherError, ToolExecutionConfigError

NONCE_BYTES = 12
KEY_BYTES = 32
TAG_BYTES = 16
OVERHEAD_BYTES = NONCE_BYTES + TAG_BYTES


def _load_aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover - 依赖齐全时不会触发
        raise ToolExecutionConfigError("缺少 cryptography 依赖，无法启用正文密文") from exc
    return AESGCM


class BodyCipher:
    """正文密文列封套：加解密 + 加解密失败抛异常（fail-closed）。"""

    def __init__(self, key: bytes) -> None:
        if not isinstance(key, (bytes, bytearray)) or len(key) != KEY_BYTES:
            raise ToolExecutionConfigError("正文加密密钥必须是 32 字节原始密钥")
        self._key = bytes(key)

    @classmethod
    def from_base64(cls, encoded: str) -> "BodyCipher":
        if not isinstance(encoded, str) or not encoded.strip():
            raise ToolExecutionConfigError(
                "未配置正文加密密钥 WORKBENCH_BODY_ENCRYPTION_KEY，拒绝启用真实执行"
            )
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ToolExecutionConfigError("正文加密密钥不是合法 base64") from exc
        if len(raw) != KEY_BYTES:
            raise ToolExecutionConfigError("正文加密密钥解码后必须为 32 字节")
        return cls(raw)

    def encrypt(self, plaintext: str) -> bytes:
        if not isinstance(plaintext, str) or not plaintext:
            raise BodyCipherError("待加密正文不能为空")
        AESGCM = _load_aesgcm()
        # 每次加密随机生成 12 字节 nonce（CSPRNG，严禁重用）。
        nonce = os.urandom(NONCE_BYTES)
        sealed = AESGCM(self._key).encrypt(nonce, plaintext.encode("utf-8"), None)
        return nonce + sealed

    def decrypt(self, blob: bytes) -> str:
        if not isinstance(blob, (bytes, bytearray)) or len(blob) <= OVERHEAD_BYTES:
            raise BodyCipherError("正文密文长度异常")
        AESGCM = _load_aesgcm()
        nonce, sealed = bytes(blob[:NONCE_BYTES]), bytes(blob[NONCE_BYTES:])
        try:
            plaintext = AESGCM(self._key).decrypt(nonce, sealed, None)
        except Exception as exc:  # noqa: BLE001 - 认证失败一律 fail-closed，不回吐内部细节
            raise BodyCipherError("正文密文校验失败（密钥不匹配或数据被篡改）") from exc
        return plaintext.decode("utf-8")
