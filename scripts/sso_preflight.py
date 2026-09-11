"""SSO 配置与 IdP 元数据预检（项 3「真实统一登录」验收取证用）。

用途：在真实 IdP 联调前核对部署环境注入的 `WORKBENCH_SSO_*` 配置是否齐备、四个 URL 是否均为 https，
并按 OIDC discovery 校验 IdP 元数据与配置是否自洽（issuer / 授权、令牌、JWKS 三个端点 / 支持的签名算法 / JWKS 可用密钥）。

前置：真实 IdP 与部署密钥系统注入的凭据（client id/secret、已在 IdP 登记的回调地址）。
**本脚本只读取配置与非敏感元数据，不发起任何登录，也绝不打印 client_secret；
因此它只验证配置与元数据自洽，不构成真实登录验收证据。**

默认联网校验（拉 discovery 与 JWKS）；加 `--offline` 只做本地配置校验、不发任何网络请求。
退出码：pass / skipped → 0；fail → 1；参数错误 → 2（argparse 默认）。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.settings import Settings

_REDIRECT_FIELD = ("redirect_uri", "sso_redirect_uri")
_REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("issuer", "sso_issuer"),
    ("authorization_endpoint", "sso_authorization_endpoint"),
    ("token_endpoint", "sso_token_endpoint"),
    ("jwks_uri", "sso_jwks_uri"),
    ("client_id", "sso_client_id"),
    ("client_secret", "sso_client_secret"),
    _REDIRECT_FIELD,
)
_HTTPS_FIELDS: tuple[tuple[str, str], ...] = (
    ("authorization_endpoint", "sso_authorization_endpoint"),
    ("token_endpoint", "sso_token_endpoint"),
    ("jwks_uri", "sso_jwks_uri"),
    _REDIRECT_FIELD,
)
_ENDPOINT_FIELDS: tuple[tuple[str, str], ...] = (
    ("authorization_endpoint", "sso_authorization_endpoint"),
    ("token_endpoint", "sso_token_endpoint"),
    ("jwks_uri", "sso_jwks_uri"),
)
_SUPPORTED_ALGORITHMS = frozenset({"RS256", "HS256"})

Transport = Callable[..., object]


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: str
    message: str


@dataclass(frozen=True)
class PreflightReport:
    status: str
    checks: tuple[PreflightCheck, ...]

    def to_text(self) -> str:
        lines = [f"SSO 预检结果：{self.status}"]
        lines.extend(f"[{check.status}] {check.name}：{check.message}" for check in self.checks)
        return "\n".join(lines)


def _host(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return ""
    return (parsed.hostname or "").lower()


def _value(settings: Settings, attr: str) -> str:
    raw = getattr(settings, attr, "")
    return raw.strip() if isinstance(raw, str) else ""


def _config_checks(settings: Settings) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []
    for label, attr in _REQUIRED_FIELDS:
        if _value(settings, attr):
            checks.append(PreflightCheck(f"配置 {label}", "pass", "已配置"))
        else:
            checks.append(PreflightCheck(f"配置 {label}", "fail", "缺少必填配置"))
    for label, attr in _HTTPS_FIELDS:
        value = _value(settings, attr)
        if not value:
            checks.append(PreflightCheck(f"{label} 协议", "fail", "缺少必填配置"))
        elif value.startswith("https://"):
            checks.append(PreflightCheck(f"{label} 协议", "pass", f"https://{_host(value)}"))
        else:
            checks.append(PreflightCheck(f"{label} 协议", "fail", "必须使用 https"))
    return checks


def _get_json(url: str, *, transport: Transport | None, timeout: float) -> dict:
    headers = {"Accept": "application/json"}
    if transport is None:
        response = httpx.get(url, headers=headers, timeout=timeout)
    else:
        response = transport(
            "GET", url, headers=headers, data=None, params=None, timeout=timeout
        )
    if not 200 <= int(getattr(response, "status_code", 0)) < 300:
        raise RuntimeError(f"HTTP {getattr(response, 'status_code', 0)}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("响应不是 JSON 对象")
    return payload


def _network_checks(settings: Settings, *, transport: Transport | None) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []
    timeout = settings.sso_timeout_seconds
    issuer = _value(settings, "sso_issuer").rstrip("/")
    discovery_url = f"{issuer}/.well-known/openid-configuration"
    try:
        discovery = _get_json(discovery_url, transport=transport, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - 任何网络/解析失败都判 fail（fail-closed）
        checks.append(PreflightCheck("OIDC 发现文档", "fail", f"获取失败：{type(exc).__name__}"))
        return checks
    checks.append(PreflightCheck("OIDC 发现文档", "pass", f"https://{_host(discovery_url)}"))

    discovered_issuer = str(discovery.get("issuer", "")).rstrip("/")
    if discovered_issuer == issuer:
        checks.append(PreflightCheck("发现文档 issuer 一致", "pass", "与配置一致"))
    else:
        checks.append(PreflightCheck("发现文档 issuer 一致", "fail", "发现文档 issuer 与配置不一致"))

    mismatched = [
        label
        for label, attr in _ENDPOINT_FIELDS
        if discovery.get(label) != _value(settings, attr)
    ]
    if mismatched:
        checks.append(
            PreflightCheck("发现文档端点一致", "fail", f"以下端点与配置不一致：{', '.join(mismatched)}")
        )
    else:
        checks.append(PreflightCheck("发现文档端点一致", "pass", "授权/令牌/JWKS 三端点与配置一致"))

    algorithms = discovery.get("id_token_signing_alg_values_supported")
    if isinstance(algorithms, list) and any(item in _SUPPORTED_ALGORITHMS for item in algorithms):
        checks.append(PreflightCheck("ID Token 签名算法", "pass", "包含 RS256 或 HS256"))
    else:
        checks.append(PreflightCheck("ID Token 签名算法", "fail", "未声明 RS256 或 HS256"))

    jwks_uri = _value(settings, "sso_jwks_uri")
    try:
        jwks = _get_json(jwks_uri, transport=transport, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - 同上，fail-closed
        checks.append(PreflightCheck("JWKS 可用密钥", "fail", f"获取失败：{type(exc).__name__}"))
        return checks
    keys = jwks.get("keys")
    usable = isinstance(keys, list) and any(
        isinstance(key, dict)
        and key.get("kty") in {"RSA", "oct"}
        and str(key.get("kid", "")).strip()
        for key in keys
    )
    if usable:
        checks.append(PreflightCheck("JWKS 可用密钥", "pass", f"https://{_host(jwks_uri)}"))
    else:
        checks.append(PreflightCheck("JWKS 可用密钥", "fail", "未发现带 kid 的 RSA/oct 公钥"))
    return checks


def run_preflight(
    settings: Settings | None = None,
    *,
    offline: bool = False,
    transport: Transport | None = None,
) -> PreflightReport:
    resolved = settings or Settings()
    if not resolved.sso_enabled:
        return PreflightReport(
            status="skipped",
            checks=(PreflightCheck("SSO 未启用", "skipped", "配置未启用 SSO，跳过校验"),),
        )
    checks = _config_checks(resolved)
    if resolved.sso_trust_idp_mfa:
        checks.append(
            PreflightCheck(
                "IdP 承担 MFA",
                "warn",
                "已声明由 IdP 承担 MFA：请在交付记录里确认 IdP 侧已开启 MFA",
            )
        )
    if offline:
        checks.append(PreflightCheck("联网元数据校验", "skipped", "已按 --offline 跳过"))
    else:
        checks.extend(_network_checks(resolved, transport=transport))
    status = "fail" if any(check.status == "fail" for check in checks) else "pass"
    return PreflightReport(status=status, checks=tuple(checks))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="公司工作台 SSO 配置与 IdP 元数据预检")
    parser.add_argument("--offline", action="store_true", help="只做本地配置校验，不发起任何网络请求")
    parser.add_argument("--example", action="store_true", help="使用不完整配置演示 fail-closed 输出")
    args = parser.parse_args(argv)
    settings = Settings(sso_enabled=True) if args.example else Settings()
    report = run_preflight(settings, offline=args.offline)
    print(report.to_text())
    return 0 if report.status in {"pass", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
