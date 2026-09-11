"""TOTP 种子的静态加密（仅供账号持久化适配器使用）。

设计取舍
    - **密钥来源**：主密钥材料取 ``Settings.backup_encryption_key``，经 HKDF-SHA256 以独立
      info 标签（``workbench-totp-secret-v1``，RFC 5869）派生 32 字节子密钥——**不复用主密钥
      字节**，因此不会出现跨用途的密钥复用；同时**不新增部署必填项**：生产环境已由
      ``validate_runtime_settings`` 强制要求 ≥32 位备份加密密钥，所以生产必然加密。
    - **算法**：AES-256-GCM（AEAD），每次写入使用随机 96 位 nonce；存储格式
      ``v1:base64(nonce || ciphertext || tag)``。
    - **历史数据兼容**：不带 ``v1:`` 前缀的值按历史明文原样返回（只读兼容），新写入一律加密，
      因此**无需数据迁移**即可平滑过渡。
    - **fail-closed**：密文解密失败（密钥不匹配 / 数据被篡改 / 格式非法）一律抛
      ``TotpSecretError``；拿到 ``v1:`` 密文却没有配置密钥时由仓储层直接报错，绝不把密文当明文。
    - **不适用范围**：内存仓储（仅开发环境）不落盘，不做静态加密。

已知影响
    - 轮换 ``WORKBENCH_BACKUP_ENCRYPTION_KEY`` 会使既有 TOTP 密文不可解，需由 ``super_admin``
      重置相关账号的动态口令后重新绑定（该找回路径已存在）。
"""

from __future__ import annotations

import base64
import binascii
import os

CIPHER_PREFIX = "v1:"
TOTP_KEY_INFO = b"workbench-totp-secret-v1"
KEY_BYTES = 32
NONCE_BYTES = 12


class TotpSecretError(ValueError):
    """TOTP 种子加解密失败（fail-closed）。"""


def _load_crypto():
    """延迟加载 cryptography；缺失时给出明确报错（与 SSO 的 RS256 处理一致）。"""
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    except ImportError as exc:  # pragma: no cover - 依赖齐全时不会触发
        raise TotpSecretError("缺少 cryptography 依赖，无法启用 TOTP 种子加密") from exc
    return hashes, HKDF, AESGCM


class SecretCipher:
    """基于 HKDF 派生子密钥 + AES-256-GCM 的字符串封套。"""

    def __init__(self, key_material: str) -> None:
        if not isinstance(key_material, str) or not key_material.strip():
            raise TotpSecretError("TOTP 加密密钥材料不能为空")
        hashes, HKDF, _AESGCM = _load_crypto()
        self._key = HKDF(
            algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=TOTP_KEY_INFO
        ).derive(key_material.encode("utf-8"))

    def encrypt(self, plaintext: str) -> str:
        if not isinstance(plaintext, str) or not plaintext:
            raise TotpSecretError("待加密内容不能为空")
        _hashes, _HKDF, AESGCM = _load_crypto()
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = AESGCM(self._key).encrypt(nonce, plaintext.encode("utf-8"), None)
        return CIPHER_PREFIX + base64.b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, stored: str) -> str:
        if not isinstance(stored, str) or not stored:
            raise TotpSecretError("待解密内容不能为空")
        if not stored.startswith(CIPHER_PREFIX):
            # 历史明文：只读兼容，避免升级当天锁死既有账号。
            return stored
        try:
            payload = base64.b64decode(stored[len(CIPHER_PREFIX) :], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise TotpSecretError("TOTP 密文不是合法 base64") from exc
        if len(payload) <= NONCE_BYTES:
            raise TotpSecretError("TOTP 密文长度异常")
        nonce, ciphertext = payload[:NONCE_BYTES], payload[NONCE_BYTES:]
        _hashes, _HKDF, AESGCM = _load_crypto()
        try:
            plaintext = AESGCM(self._key).decrypt(nonce, ciphertext, None)
        except Exception as exc:  # noqa: BLE001 - 认证失败一律 fail-closed，不回吐内部细节
            raise TotpSecretError("TOTP 密文校验失败（密钥不匹配或数据被篡改）") from exc
        return plaintext.decode("utf-8")


def build_totp_cipher(key_material: str) -> SecretCipher | None:
    """主密钥材料为空时返回 ``None``（不加密）；否则返回可用封套。"""
    if not isinstance(key_material, str) or not key_material.strip():
        return None
    return SecretCipher(key_material)
