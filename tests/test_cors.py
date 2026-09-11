"""跨源部署的 CORS 配置契约。

桌面端（远程模式）与 PWA 伴侣端在跨源部署时必须能把 `Authorization` 头带到后端，
否则预检失败、请求被浏览器拦截。这里守护两件事：
1. **fail-closed**：非 development 环境未配置允许来源时，**不注册任何 CORS 中间件**；
2. **放行范围最小**：只放行显式配置的来源，且头白名单含 `Authorization`；
   通配符 `*` 与带路径的地址一律拒绝。
"""

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.settings import Settings, parse_cors_origins, resolve_cors_options, validate_runtime_settings

CUSTOM_METHODS = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]


def production_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "env": "production",
        "storage_backend": "postgres",
        "database_url": "postgresql+psycopg://workbench:pw@db.example.com:5432/workbench",
        "auth_secret": "a" * 32,
        "backup_encryption_key": "b" * 32,
        "content_store_backend": "sqlite",
    }
    base.update(overrides)
    return Settings(**base)


def build_client(settings: Settings) -> TestClient:
    app = FastAPI()
    options = resolve_cors_options(settings)
    if options is not None:
        app.add_middleware(CORSMiddleware, **options)

    @app.get("/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def preflight(client: TestClient, origin: str) -> object:
    return client.options(
        "/ping",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )


def test_development_keeps_localhost_regex_and_allows_authorization() -> None:
    options = resolve_cors_options(Settings(env="development"))

    assert options is not None
    assert options["allow_origins"] == []
    assert "localhost" in options["allow_origin_regex"]
    assert "Authorization" in options["allow_headers"]
    for method in CUSTOM_METHODS:
        assert method in options["allow_methods"]


def test_production_without_origins_registers_no_cors() -> None:
    # 判定依据：未显式配置来源即视为「不允许任何跨源」，不得静默放行。
    assert resolve_cors_options(production_settings()) is None
    assert resolve_cors_options(production_settings(cors_allowed_origins="  ")) is None


def test_production_options_use_explicit_origins_without_regex() -> None:
    options = resolve_cors_options(
        production_settings(cors_allowed_origins="https://app.example.com, https://admin.example.com")
    )

    assert options is not None
    assert options["allow_origins"] == ["https://app.example.com", "https://admin.example.com"]
    assert "allow_origin_regex" not in options
    assert options["allow_credentials"] is False
    assert "Authorization" in options["allow_headers"]


def test_production_cors_preflight_allows_authorization_header() -> None:
    client = build_client(
        production_settings(cors_allowed_origins="https://app.example.com")
    )

    response = preflight(client, "https://app.example.com")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_production_cors_does_not_allow_unlisted_origin() -> None:
    client = build_client(
        production_settings(cors_allowed_origins="https://app.example.com")
    )

    response = preflight(client, "https://evil.example.com")

    assert "access-control-allow-origin" not in response.headers


def test_production_without_origins_denies_cross_origin_preflight() -> None:
    client = build_client(production_settings())

    response = preflight(client, "https://app.example.com")

    assert "access-control-allow-origin" not in response.headers


def test_parse_cors_origins_rejects_wildcard_and_paths() -> None:
    for raw in ("*", "https://app.example.com/", "https://app.example.com/app", "app.example.com"):
        with pytest.raises(ValueError):
            parse_cors_origins(raw)

    assert parse_cors_origins(" https://a.example.com ,, http://b.example.com ") == [
        "https://a.example.com",
        "http://b.example.com",
    ]
    assert parse_cors_origins("") == []


def test_validate_runtime_settings_rejects_invalid_cors_origin() -> None:
    # 判定依据：生产环境配置错误必须在启动期暴露，而不是静默降级为「不放行」。
    with pytest.raises(ValueError):
        validate_runtime_settings(production_settings(cors_allowed_origins="*"))

    validate_runtime_settings(
        production_settings(cors_allowed_origins="https://app.example.com")
    )
