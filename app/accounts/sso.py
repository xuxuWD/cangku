"""OIDC 单点登录构建块：配置校验、PKCE、令牌交换与 ID Token 校验。

设计要点：
- 纯逻辑 + 可注入传输层，全部可离线测试，任何真实 HTTP 调用只在默认传输层发生。
- 公开错误一律是面向用户的安全文案，不回吐 IdP 响应体或令牌内容。
- 签名校验严禁算法混淆：HS256 只用 client_secret 作为密钥，绝不使用 jwks 中的密钥；
  RS256 只从 jwks 取 RSA 公钥。`alg` 白名单只允许 HS256 / RS256。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx


class SsoNotConfigured(ValueError):
    """SSO 配置缺失或非法（fail-closed）。"""


class SsoError(ValueError):
    """SSO 流程失败，文案面向用户且不含内部细节。"""


class SsoTokenError(SsoError):
    """ID Token 校验失败。"""


_ALLOWED_ALGORITHMS = frozenset({"HS256", "RS256"})
_PKCE_UNRESERVED = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
_PKCE_VERIFIER_LENGTH = 64
_REQUIRED_CONFIG_FIELDS = (
    "issuer",
    "authorization_endpoint",
    "token_endpoint",
    "jwks_uri",
    "client_id",
    "client_secret",
    "redirect_uri",
)
_HTTPS_CONFIG_FIELDS = (
    "authorization_endpoint",
    "token_endpoint",
    "jwks_uri",
    "redirect_uri",
)


@dataclass(frozen=True)
class SsoConfig:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: tuple[str, ...] = ("openid", "email", "profile")
    timeout_seconds: float = 10.0
    allow_insecure: bool = False

    def __post_init__(self) -> None:
        for name in _REQUIRED_CONFIG_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SsoNotConfigured(f"SSO 配置缺少 {name}")
        if not self.allow_insecure:
            for name in _HTTPS_CONFIG_FIELDS:
                value = getattr(self, name).strip()
                if not value.startswith("https://"):
                    raise SsoNotConfigured(f"{name} 必须使用 https")


@dataclass(frozen=True)
class SsoIdentity:
    subject: str
    email: str
    email_verified: bool
    name: str | None = None


SsoTransport = Callable[..., Any]


def _default_transport(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    data: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    timeout: float,
):
    """默认传输层：真实 HTTP 调用，仅在装配环境启用。"""
    return httpx.request(method, url, headers=headers, data=data, params=params, timeout=timeout)


def generate_pkce_pair() -> tuple[str, str]:
    """生成 PKCE 的 (verifier, challenge)，challenge = base64url(sha256(verifier)) 去 padding。"""
    verifier = "".join(secrets.choice(_PKCE_UNRESERVED) for _ in range(_PKCE_VERIFIER_LENGTH))
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorization_url(
    config: SsoConfig, *, state: str, nonce: str, code_challenge: str
) -> str:
    """拼装授权码 + PKCE 的授权地址，参数统一交给 urlencode 转义。"""
    query = urlencode(
        {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "scope": " ".join(config.scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    separator = "&" if "?" in config.authorization_endpoint else "?"
    return f"{config.authorization_endpoint}{separator}{query}"


def exchange_code(
    config: SsoConfig, *, code: str, code_verifier: str, transport: SsoTransport | None = None
) -> dict:
    """用授权码换取令牌；非 2xx 或缺 id_token 一律抛 SsoError。"""
    transport = transport or _default_transport
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri,
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "code_verifier": code_verifier,
    }
    try:
        response = transport(
            "POST",
            config.token_endpoint,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data=data,
            params=None,
            timeout=config.timeout_seconds,
        )
    except SsoError:
        raise
    except Exception as exc:  # noqa: BLE001 - 传输层任何异常都视为交换失败
        raise SsoError("SSO 令牌交换失败") from exc
    status_code = getattr(response, "status_code", 200)
    if not 200 <= int(status_code) < 300:
        raise SsoError("SSO 令牌交换失败")
    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - 响应不可解析同样判定失败
        raise SsoError("SSO 令牌响应无法解析") from exc
    if not isinstance(payload, dict) or not payload.get("id_token"):
        raise SsoError("SSO 令牌响应缺少 id_token")
    return payload


def fetch_jwks(config: SsoConfig, *, transport: SsoTransport | None = None) -> dict:
    """获取 IdP 公钥集合；非 2xx 或非法 JSON 一律抛 SsoError。"""
    transport = transport or _default_transport
    try:
        response = transport(
            "GET",
            config.jwks_uri,
            headers={"Accept": "application/json"},
            data=None,
            params=None,
            timeout=config.timeout_seconds,
        )
    except SsoError:
        raise
    except Exception as exc:  # noqa: BLE001 - 传输层任何异常都视为获取失败
        raise SsoError("SSO 公钥获取失败") from exc
    status_code = getattr(response, "status_code", 200)
    if not 200 <= int(status_code) < 300:
        raise SsoError("SSO 公钥获取失败")
    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - 响应不可解析同样判定失败
        raise SsoError("SSO 公钥响应无法解析") from exc
    if not isinstance(payload, dict):
        raise SsoError("SSO 公钥响应无法解析")
    return payload


def _b64url_bytes(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded)


def _b64url_uint(value: object) -> int:
    if not isinstance(value, str) or not value:
        raise ValueError("empty rsa component")
    return int.from_bytes(_b64url_bytes(value), "big")


def _decode_json_segment(segment: str) -> dict:
    try:
        raw = _b64url_bytes(segment)
        value = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise SsoTokenError("IdP 返回的令牌格式无效") from exc
    if not isinstance(value, dict):
        raise SsoTokenError("IdP 返回的令牌格式无效")
    return value


def _verify_hs256(signing_input: bytes, signature: bytes, client_secret: str) -> None:
    expected = hmac.new(client_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, signature):
        raise SsoTokenError("IdP 令牌签名校验失败")


def _select_rsa_key(header: dict, jwks: dict) -> dict:
    kid = header.get("kid")
    keys = jwks.get("keys") if isinstance(jwks, dict) else None
    if isinstance(keys, list):
        for key in keys:
            if not isinstance(key, dict) or key.get("kty") != "RSA":
                continue
            if kid is not None and key.get("kid") != kid:
                continue
            return key
    raise SsoTokenError("未找到匹配的 IdP 公钥")


def _verify_rs256(signing_input: bytes, signature: bytes, header: dict, jwks: dict) -> None:
    key = _select_rsa_key(header, jwks)
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
    except ImportError as exc:  # pragma: no cover - 依赖齐全时不会触发
        raise SsoTokenError("缺少 cryptography 依赖，无法校验 RS256 令牌") from exc
    try:
        public_key = RSAPublicNumbers(_b64url_uint(key.get("e")), _b64url_uint(key.get("n"))).public_key()
        public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
    except SsoTokenError:
        raise
    except Exception as exc:  # noqa: BLE001 - 任何验签/解析失败都视为签名无效
        raise SsoTokenError("IdP 令牌签名校验失败") from exc


def _validate_claims(
    claims: dict, *, config: SsoConfig, nonce: str, now: datetime, leeway_seconds: int
) -> SsoIdentity:
    if claims.get("iss") != config.issuer:
        raise SsoTokenError("IdP 令牌签发方不匹配")
    aud = claims.get("aud")
    if isinstance(aud, str):
        audiences = {aud}
    elif isinstance(aud, list):
        audiences = {item for item in aud if isinstance(item, str)}
    else:
        audiences = set()
    if config.client_id not in audiences:
        raise SsoTokenError("IdP 令牌受众不匹配")
    if "azp" in claims:
        azp = claims.get("azp")
        if not isinstance(azp, str) or azp != config.client_id:
            raise SsoTokenError("IdP 令牌授权方不匹配")
    exp = claims.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        raise SsoTokenError("IdP 令牌缺少有效过期时间")
    current = now.timestamp()
    if not current < exp + leeway_seconds:
        raise SsoTokenError("IdP 令牌已过期")
    iat = claims.get("iat")
    if iat is not None:
        if isinstance(iat, bool) or not isinstance(iat, (int, float)):
            raise SsoTokenError("IdP 令牌签发时间无效")
        if iat > current + leeway_seconds:
            raise SsoTokenError("IdP 令牌签发时间异常")
    if claims.get("nonce") != nonce:
        raise SsoTokenError("IdP 令牌随机数不匹配")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise SsoTokenError("IdP 令牌缺少用户标识")
    email = claims.get("email")
    if not isinstance(email, str) or not email.strip():
        raise SsoTokenError("IdP 令牌缺少邮箱")
    if claims.get("email_verified") is not True:
        raise SsoTokenError("IdP 未验证邮箱，已拒绝登录")
    raw_name = claims.get("name")
    name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else None
    return SsoIdentity(
        subject=subject.strip(),
        email=email.strip().lower(),
        email_verified=True,
        name=name,
    )


def verify_id_token(
    token: str,
    *,
    config: SsoConfig,
    jwks: dict,
    nonce: str,
    now: datetime | None = None,
    leeway_seconds: int = 60,
) -> SsoIdentity:
    """校验 ID Token 的签名与声明，返回可信身份；任何失败一律抛 SsoTokenError。"""
    if not isinstance(token, str):
        raise SsoTokenError("IdP 令牌格式无效")
    parts = token.split(".")
    if len(parts) != 3:
        raise SsoTokenError("IdP 令牌格式无效")
    header_segment, payload_segment, signature_segment = parts
    header = _decode_json_segment(header_segment)
    alg = header.get("alg")
    if not isinstance(alg, str) or alg not in _ALLOWED_ALGORITHMS:
        raise SsoTokenError("不支持的签名算法")
    try:
        signature = _b64url_bytes(signature_segment)
    except (binascii.Error, ValueError) as exc:
        raise SsoTokenError("IdP 令牌签名格式无效") from exc
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    if alg == "HS256":
        _verify_hs256(signing_input, signature, config.client_secret)
    else:
        _verify_rs256(signing_input, signature, header, jwks)
    claims = _decode_json_segment(payload_segment)
    return _validate_claims(
        claims,
        config=config,
        nonce=nonce,
        now=now or datetime.now(UTC),
        leeway_seconds=leeway_seconds,
    )


def complete_authorization(
    config: SsoConfig,
    *,
    code: str,
    code_verifier: str,
    nonce: str,
    transport: SsoTransport | None = None,
    now: datetime | None = None,
) -> SsoIdentity:
    """串起令牌交换、公钥获取与 ID Token 校验，返回可信身份。"""
    token_payload = exchange_code(
        config, code=code, code_verifier=code_verifier, transport=transport
    )
    jwks = fetch_jwks(config, transport=transport)
    id_token = token_payload.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise SsoError("SSO 令牌响应缺少 id_token")
    return verify_id_token(id_token, config=config, jwks=jwks, nonce=nonce, now=now)
