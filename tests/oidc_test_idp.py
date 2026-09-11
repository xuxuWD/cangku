"""进程内 OIDC 兼容测试 IdP：标准库 WSGI + cryptography 真实 RS256 签名。

用途：在不使用 socket / 端口 / 线程 / 外部网络的前提下，用**真实的 HTTP 语义**
（`httpx.WSGITransport` 进程内 WSGI 传输）和**真实的 RS256 签名**端到端预演 SSO 全链路。
它不是被测对象，而是测试夹具；文件名刻意不以 `test_` 开头，避免被 pytest 当作用例收集。

路由：
- `GET /.well-known/openid-configuration`：issuer / 三个端点 / jwks_uri / 支持的响应类型与签名算法。
- `GET /jwks`：发布启动时生成的原 RSA 公钥（`kty=RSA`、`use=sig`、`alg=RS256`、`n`/`e` 为 base64url 无 padding）。
- `GET /authorize`：校验 `client_id`/`redirect_uri`/`state`/`nonce`/`code_challenge`/`code_challenge_method=S256`，
  通过则生成一次性 code 并把「nonce + code_challenge」与该 code 绑定，返回 302 且 `Location` 带 `code` 与 `state`。
- `POST /token`：解析 `application/x-www-form-urlencoded`，校验 grant_type / client 凭据 / redirect_uri /
  一次性 code / PKCE `code_verifier`，通过则用 RS256 真签 id_token 返回，失败返回 400 + `{"error": ...}`。

可控开关（构造参数，供负向用例使用）：
- `sign_with_unknown_key`：用另一把未发布的 RSA 私钥签名，但 JWKS 仍只发布原公钥 → 触发验签失败。
- `kid_override`：把 id_token 头部 `kid` 改成任意值 → 触发「JWKS 中找不到匹配公钥」。
- `nonce_override`：覆盖 id_token 中的 `nonce`（默认取该 code 绑定的 nonce）→ 触发 nonce 不匹配。
- `email_verified`：id_token 中 `email_verified` 的值（默认 True）→ 传 False 触发「未验证邮箱」拒绝。
- `omit_code_challenge_check`：跳过 token 端点的 PKCE 校验（默认 False）。
- `subject` / `email` / `name`：id_token 的身份声明（默认 `sso-user-1` / `user@example.com` / `张三`）。
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from http import HTTPStatus
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.accounts.sso import SsoConfig


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _rsa_jwk(private_key: rsa.RSAPrivateKey, kid: str) -> dict[str, str]:
    numbers = private_key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _b64url(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
        "e": _b64url(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
    }


def _json_segment(value: dict) -> str:
    return _b64url(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def _first(values: dict[str, list[str]], name: str) -> str:
    items = values.get(name)
    return items[0] if items else ""


class OidcTestIdp:
    """进程内 OIDC 兼容 IdP；通过 `httpx.WSGITransport` 提供真实 HTTP 语义。"""

    def __init__(
        self,
        *,
        issuer: str = "https://idp.test",
        client_id: str = "workbench-client",
        client_secret: str = "idp-test-secret",
        redirect_uri: str = "https://workbench.test/auth/callback",
        sign_with_unknown_key: bool = False,
        kid_override: str | None = None,
        nonce_override: str | None = None,
        email_verified: bool = True,
        omit_code_challenge_check: bool = False,
        subject: str = "sso-user-1",
        email: str = "user@example.com",
        name: str | None = "张三",
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.sign_with_unknown_key = sign_with_unknown_key
        self.kid_override = kid_override
        self.nonce_override = nonce_override
        self.email_verified = email_verified
        self.omit_code_challenge_check = omit_code_challenge_check
        self.subject = subject
        self.email = email
        self.name = name

        self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._unpublished_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._published_kid = f"kid-{secrets.token_hex(8)}"
        self._jwks: dict[str, object] = {"keys": [_rsa_jwk(self._private_key, self._published_kid)]}
        self._codes: dict[str, dict[str, str]] = {}
        # 预先构造 WSGI 传输实例：测试可据此断言全程未使用 socket / 端口。
        self.wsgi_transport = httpx.WSGITransport(app=self.app)

    # --- 元数据 ---------------------------------------------------------------

    def discovery_document(self) -> dict[str, object]:
        return {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/authorize",
            "token_endpoint": f"{self.issuer}/token",
            "jwks_uri": f"{self.issuer}/jwks",
            "response_types_supported": ["code"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "subject_types_supported": ["public"],
            "grant_types_supported": ["authorization_code"],
        }

    def jwks_document(self) -> dict[str, object]:
        return self._jwks

    # --- 装配辅助 -------------------------------------------------------------

    def config(self, **overrides: object) -> SsoConfig:
        """构造与该 IdP 匹配的 `SsoConfig`（字段与 `build_authorization_url` 同款）。"""
        values: dict[str, object] = {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/authorize",
            "token_endpoint": f"{self.issuer}/token",
            "jwks_uri": f"{self.issuer}/jwks",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
        }
        values.update(overrides)
        return SsoConfig(**values)  # type: ignore[arg-type]

    def as_transport(self):
        """返回符合 `SsoTransport` 签名的可调用对象，内部走进程内 WSGI 传输。"""

        def transport(method, url, *, headers, data=None, params=None, timeout):
            with httpx.Client(transport=self.wsgi_transport) as client:
                return client.request(
                    method,
                    url,
                    headers=dict(headers or {}),
                    data=data,
                    params=params,
                    timeout=timeout,
                )

        return transport

    @staticmethod
    def location_of(response) -> str:
        return response.headers["location"]

    def authorize(
        self,
        state: str,
        nonce: str,
        code_challenge: str,
        *,
        code_challenge_method: str = "S256",
    ) -> str:
        """像浏览器一样发起授权：拿到 302 后解析 `Location` 中的一次性 code。"""
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
            }
        )
        response = self.as_transport()(
            "GET",
            f"{self.issuer}/authorize?{query}",
            headers={"Accept": "text/html"},
            data=None,
            params=None,
            timeout=10.0,
        )
        if response.status_code != HTTPStatus.FOUND:
            raise AssertionError(f"授权端点未返回 302：{response.status_code}")
        location = self.location_of(response)
        return _first(parse_qs(urlsplit(location).query), "code")

    # --- WSGI 应用 ------------------------------------------------------------

    def app(self, environ, start_response):
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/"))
        try:
            if method == "GET" and path == "/.well-known/openid-configuration":
                return self._json(start_response, HTTPStatus.OK, self.discovery_document())
            if method == "GET" and path == "/jwks":
                return self._json(start_response, HTTPStatus.OK, self._jwks)
            if method == "GET" and path == "/authorize":
                return self._authorize(environ, start_response)
            if method == "POST" and path == "/token":
                return self._token(environ, start_response)
        except Exception:  # noqa: BLE001 - 测试夹具：任何意外都归为 500，避免泄漏堆栈
            return self._json(start_response, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "server_error"})
        return self._json(start_response, HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _json(self, start_response, status: HTTPStatus, payload: dict) -> list[bytes]:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        start_response(
            f"{int(status)} {status.phrase}",
            [("Content-Type", "application/json"), ("Content-Length", str(len(body)))],
        )
        return [body]

    def _redirect(self, start_response, location: str) -> list[bytes]:
        start_response(
            f"{int(HTTPStatus.FOUND)} {HTTPStatus.FOUND.phrase}",
            [("Location", location), ("Content-Length", "0")],
        )
        return [b""]

    def _authorize(self, environ, start_response) -> list[bytes]:
        params = parse_qs(str(environ.get("QUERY_STRING", "")), keep_blank_values=True)
        if _first(params, "response_type") != "code":
            return self._json(start_response, HTTPStatus.BAD_REQUEST, {"error": "unsupported_response_type"})
        if _first(params, "client_id") != self.client_id:
            return self._json(start_response, HTTPStatus.BAD_REQUEST, {"error": "invalid_client"})
        if _first(params, "redirect_uri") != self.redirect_uri:
            return self._json(start_response, HTTPStatus.BAD_REQUEST, {"error": "invalid_redirect_uri"})
        state = _first(params, "state")
        nonce = _first(params, "nonce")
        code_challenge = _first(params, "code_challenge")
        if not state or not nonce or not code_challenge:
            return self._json(start_response, HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
        if _first(params, "code_challenge_method") != "S256":
            return self._json(start_response, HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
        code = secrets.token_urlsafe(24)
        self._codes[code] = {"nonce": nonce, "code_challenge": code_challenge}
        location = f"{self.redirect_uri}?code={quote(code)}&state={quote(state)}"
        return self._redirect(start_response, location)

    def _read_form(self, environ) -> dict[str, list[str]]:
        length = int(environ.get("CONTENT_LENGTH") or 0)
        raw = environ["wsgi.input"].read(length) if length else b""
        return parse_qs(raw.decode("utf-8"), keep_blank_values=True)

    def _token(self, environ, start_response) -> list[bytes]:
        form = self._read_form(environ)
        if _first(form, "grant_type") != "authorization_code":
            return self._json(start_response, HTTPStatus.BAD_REQUEST, {"error": "unsupported_grant_type"})
        if _first(form, "client_id") != self.client_id or _first(form, "client_secret") != self.client_secret:
            return self._json(start_response, HTTPStatus.BAD_REQUEST, {"error": "invalid_client"})
        code = _first(form, "code")
        record = self._codes.pop(code, None)
        if record is None:
            return self._json(start_response, HTTPStatus.BAD_REQUEST, {"error": "invalid_grant"})
        if _first(form, "redirect_uri") != self.redirect_uri:
            return self._json(start_response, HTTPStatus.BAD_REQUEST, {"error": "invalid_grant"})
        if not self.omit_code_challenge_check:
            verifier = _first(form, "code_verifier")
            challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
            if challenge != record["code_challenge"]:
                return self._json(start_response, HTTPStatus.BAD_REQUEST, {"error": "invalid_grant"})
        id_token = self._issue_id_token(record["nonce"])
        return self._json(
            start_response,
            HTTPStatus.OK,
            {
                "access_token": secrets.token_urlsafe(24),
                "token_type": "Bearer",
                "expires_in": 300,
                "id_token": id_token,
            },
        )

    def _issue_id_token(self, bound_nonce: str) -> str:
        signing_key = self._unpublished_key if self.sign_with_unknown_key else self._private_key
        header = {"alg": "RS256", "typ": "JWT", "kid": self.kid_override or self._published_kid}
        now = int(time.time())
        claims: dict[str, object] = {
            "iss": self.issuer,
            "sub": self.subject,
            "aud": self.client_id,
            "azp": self.client_id,
            "exp": now + 300,
            "iat": now,
            "nonce": self.nonce_override if self.nonce_override is not None else bound_nonce,
            "email": self.email,
            "email_verified": self.email_verified,
        }
        if self.name is not None:
            claims["name"] = self.name
        signing_input = f"{_json_segment(header)}.{_json_segment(claims)}".encode("ascii")
        signature = signing_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return f"{signing_input.decode('ascii')}.{_b64url(signature)}"
