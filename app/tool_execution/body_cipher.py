"""受控正文密文列（`body_ciphertext`）的应用层 AEAD 封套（规格 §3.4 约束 1）。

算法与布局**定死**：AES-256-GCM；`body_ciphertext` = `nonce(12B) ‖ ciphertext ‖ tag(16B)`
（overhead 恒 28 字节）。密钥来自独立配置 `WORKBENCH_BODY_ENCRYPTION_KEY`
（32 字节原始密钥的 base64），**不复用** `backup_encryption_key`（单一职责）。

**密钥轮换 = 双密钥窗口（§3.4 约束 1 / §9.6 P4）**：轮换期**新密钥用于加密、旧密钥仅用于解密**；
窗口长度 = **最大审批超时 + 清理周期**（`rotation_window_seconds`）。窗口内**不得**因轮换导致
解密失败，故 `decrypt` 依次尝试「活动密钥 + 旧密钥」，任一认证通过即还原明文。

fail-closed：加解密失败一律抛异常，**绝不静默降级**；明文不进日志 / 审计 / 错误信息。
"""

from __future__ import annotations

import base64
import binascii
import os
from typing import Sequence

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


def _coerce_key(key: bytes) -> bytes:
    if not isinstance(key, (bytes, bytearray)) or len(key) != KEY_BYTES:
        raise ToolExecutionConfigError("正文加密密钥必须是 32 字节原始密钥")
    return bytes(key)


def rotation_window_seconds(*, approval_timeout_minutes: int, cleanup_interval_seconds: int) -> int:
    """双密钥窗口长度（秒）= **最大审批超时 + 清理周期**（规格 §3.4 约束 1 / §9.6 P4）。

    口径**严格照真源**，不做任何外推：

    * 「最大审批超时」= 审批超时的**上限**（`app/workforce/models.py` 的
      `MAX_APPROVAL_TIMEOUT_MINUTES`，按每个员工可配置的审批超时上界）；窗口内**不可能**再有
      未判决的待批动作（超过该上界的密文早已到期被清），故窗口内不存在需要旧密钥解密的密文。
    * 「清理周期」= `WORKBENCH_BODY_CLEANUP_INTERVAL_SECONDS`（规格 §8 U16：**该值决定 P4 的
      密钥轮换窗口长度**）。

    **轮换的触发方式真源未定义**（规格只给了窗口长度与「新加密 / 旧解密」的语义），故本函数只
    负责窗口长度本身，**不**假定任何轮换触发方式、**不**读取任何配置。
    """
    if approval_timeout_minutes < 0 or cleanup_interval_seconds < 0:
        raise ToolExecutionConfigError("窗口长度入参必须为非负整数")
    return int(approval_timeout_minutes) * 60 + int(cleanup_interval_seconds)


class BodyCipher:
    """正文密文列封套：加解密 + 加解密失败抛异常（fail-closed）。

    **双密钥窗口**：`key` 为**活动密钥**（唯一用于加密）；`previous_keys` 为轮换期**仅用于解密**的
    旧密钥（§3.4 约束 1）。`decrypt` 依次尝试全部密钥，认证失败即换下一把；全部失败才抛
    `BodyCipherError`（fail-closed，绝不返回猜测的明文）。
    """

    def __init__(self, key: bytes, *, previous_keys: Sequence[bytes] = ()) -> None:
        self._keys = (_coerce_key(key),) + tuple(_coerce_key(item) for item in previous_keys)

    @property
    def key(self) -> bytes:
        """活动密钥（**仅用于加密**；对外只读，不得写入日志 / 审计 / 响应）。"""
        return self._keys[0]

    @classmethod
    def from_base64(cls, encoded: str, *, previous: Sequence[str] = ()) -> "BodyCipher":
        return cls(_decode_key(encoded), previous_keys=tuple(_decode_key(item) for item in previous))

    def encrypt(self, plaintext: str) -> bytes:
        if not isinstance(plaintext, str) or not plaintext:
            raise BodyCipherError("待加密正文不能为空")
        AESGCM = _load_aesgcm()
        # 每次加密随机生成 12 字节 nonce（CSPRNG，严禁重用）。
        nonce = os.urandom(NONCE_BYTES)
        sealed = AESGCM(self.key).encrypt(nonce, plaintext.encode("utf-8"), None)
        return nonce + sealed

    def decrypt(self, blob: bytes) -> str:
        if not isinstance(blob, (bytes, bytearray)) or len(blob) <= OVERHEAD_BYTES:
            raise BodyCipherError("正文密文长度异常")
        AESGCM = _load_aesgcm()
        nonce, sealed = bytes(blob[:NONCE_BYTES]), bytes(blob[NONCE_BYTES:])
        for key in self._keys:
            try:
                return AESGCM(key).decrypt(nonce, sealed, None).decode("utf-8")
            except Exception:  # noqa: BLE001 - 认证失败一律换下一把；不得回吐内部细节
                continue
        raise BodyCipherError("正文密文校验失败（密钥不匹配或数据被篡改）")


def _decode_key(encoded: str) -> bytes:
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
    return raw
