"""SSO 构建块离线测试：配置校验、PKCE、授权地址、令牌交换、ID Token 校验、state 仓储。

全部离线：外部 HTTP 一律通过注入的 transport 假实现；RS256 用 cryptography 生成临时密钥。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.accounts.models import Account
from app.accounts.repository import InMemoryAccountRepository, PostgresAccountRepository
from app.accounts.sso import (
    SsoConfig,
    SsoError,
    SsoNotConfigured,
    SsoTokenError,
    build_authorization_url,
    complete_authorization,
    exchange_code,
    fetch_jwks,
    generate_pkce_pair,
    verify_id_token,
)
from app.accounts.sso_store import (
    InMemorySsoStateStore,
    PostgresSsoStateStore,
    SsoState,
    SsoStateNotFound,
)
from app.bootstrap import build_sso_config, build_sso_state_store
from app.settings import Settings

ISSUER = "https://idp.example"
CLIENT_ID = "workbench-client"
CLIENT_SECRET = "s3cret"
REDIRECT_URI = "https://workbench.example/auth/callback"
NONCE = "nonce-abc"


def make_config(**overrides) -> SsoConfig:
    values = {
        "issuer": ISSUER,
        "authorization_endpoint": "https://idp.example/authorize",
        "token_endpoint": "https://idp.example/token",
        "jwks_uri": "https://idp.example/jwks",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
    }
    values.update(overrides)
    return SsoConfig(**values)


class FakeResponse:
    def __init__(self, *, status_code: int = 200, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _segment(value: dict) -> str:
    return _b64url(json.dumps(value, separators=(",", ":")).encode("utf-8"))


# --- SsoConfig 校验 -----------------------------------------------------------


def test_sso_config_requires_all_fields() -> None:
    for field in (
        "issuer",
        "authorization_endpoint",
        "token_endpoint",
        "jwks_uri",
        "client_id",
        "client_secret",
        "redirect_uri",
    ):
        with pytest.raises(SsoNotConfigured, match=field):
            make_config(**{field: ""})


def test_sso_config_rejects_non_https_endpoints() -> None:
    for field in (
        "authorization_endpoint",
        "token_endpoint",
        "jwks_uri",
        "redirect_uri",
    ):
        with pytest.raises(SsoNotConfigured, match=field):
            make_config(**{field: "http://idp.example/x"})


def test_sso_config_allow_insecure_permits_http() -> None:
    config = make_config(
        authorization_endpoint="http://localhost:8080/authorize",
        allow_insecure=True,
    )
    assert config.authorization_endpoint.startswith("http://")


# --- PKCE ---------------------------------------------------------------------


def test_generate_pkce_pair_verifier_charset_and_length() -> None:
    verifier, challenge = generate_pkce_pair()

    assert 43 <= len(verifier) <= 128
    assert set(verifier) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    assert challenge == _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def test_generate_pkce_pair_is_random() -> None:
    assert generate_pkce_pair()[0] != generate_pkce_pair()[0]


# --- 授权地址 -----------------------------------------------------------------


def test_build_authorization_url_carries_all_params() -> None:
    config = make_config()

    url = build_authorization_url(
        config, state="st-1", nonce="n-1", code_challenge="ch-1"
    )

    assert url.startswith("https://idp.example/authorize?")
    assert "response_type=code" in url
    assert "client_id=workbench-client" in url
    assert "code_challenge_method=S256" in url
    assert "code_challenge=ch-1" in url
    assert "state=st-1" in url
    assert "nonce=n-1" in url
    # scope 空格由 urlencode 转义（application/x-www-form-urlencoded 用 +）
    assert "scope=openid+email+profile" in url
    # redirect_uri 必须被转义，不能原样出现裸冒号与斜杠组合
    assert "redirect_uri=https%3A%2F%2Fworkbench.example%2Fauth%2Fcallback" in url


def test_build_authorization_url_appends_when_query_present() -> None:
    config = make_config(authorization_endpoint="https://idp.example/authorize?tenant=a")

    url = build_authorization_url(config, state="s", nonce="n", code_challenge="c")

    assert url.startswith("https://idp.example/authorize?tenant=a&response_type=code")


# --- 令牌交换 -----------------------------------------------------------------


def test_exchange_code_posts_form_with_client_and_verifier() -> None:
    captured: list[dict] = []

    def transport(method, url, *, headers, data=None, params=None, timeout):
        captured.append({"method": method, "url": url, "headers": headers, "data": data, "timeout": timeout})
        return FakeResponse(payload={"id_token": "tok"})

    payload = exchange_code(
        make_config(), code="code-1", code_verifier="verifier-1", transport=transport
    )

    assert payload == {"id_token": "tok"}
    request = captured[0]
    assert request["method"] == "POST"
    assert request["url"] == "https://idp.example/token"
    assert request["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert request["data"] == {
        "grant_type": "authorization_code",
        "code": "code-1",
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code_verifier": "verifier-1",
    }
    assert request["timeout"] == 10.0


def test_exchange_code_rejects_non_2xx_without_leaking_body() -> None:
    def transport(method, url, *, headers, data=None, params=None, timeout):
        return FakeResponse(status_code=400, payload={"error": "super-secret-detail"})

    with pytest.raises(SsoError) as excinfo:
        exchange_code(make_config(), code="c", code_verifier="v", transport=transport)

    assert "super-secret-detail" not in str(excinfo.value)


def test_exchange_code_rejects_missing_id_token() -> None:
    def transport(method, url, *, headers, data=None, params=None, timeout):
        return FakeResponse(payload={"access_token": "a"})

    with pytest.raises(SsoError, match="id_token"):
        exchange_code(make_config(), code="c", code_verifier="v", transport=transport)


# --- JWKS ---------------------------------------------------------------------


def test_fetch_jwks_returns_payload() -> None:
    def transport(method, url, *, headers, data=None, params=None, timeout):
        assert method == "GET"
        assert url == "https://idp.example/jwks"
        return FakeResponse(payload={"keys": []})

    assert fetch_jwks(make_config(), transport=transport) == {"keys": []}


def test_fetch_jwks_rejects_non_2xx_and_bad_json() -> None:
    with pytest.raises(SsoError):
        fetch_jwks(make_config(), transport=lambda *a, **k: FakeResponse(status_code=500, payload={}))
    with pytest.raises(SsoError):
        fetch_jwks(
            make_config(),
            transport=lambda *a, **k: FakeResponse(payload=ValueError("bad json")),
        )


# --- ID Token 校验 ------------------------------------------------------------


def _claims(**overrides) -> dict:
    now = int(datetime.now(UTC).timestamp())
    values = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "exp": now + 300,
        "iat": now,
        "nonce": NONCE,
        "sub": "user-1",
        "email": "User@Example.com ",
        "email_verified": True,
        "name": "张三",
    }
    values.update(overrides)
    return values


def _hs256_token(claims: dict, *, secret: str = CLIENT_SECRET, header: dict | None = None) -> str:
    header_value = {"alg": "HS256", "typ": "JWT"}
    if header:
        header_value.update(header)
    signing_input = f"{_segment(header_value)}.{_segment(claims)}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{signing_input.decode('ascii')}.{_b64url(signature)}"


def _rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": "kid-1",
        "n": _b64url(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
        "e": _b64url(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
    }
    return private_key, {"keys": [jwk]}


def _rs256_token(claims: dict, private_key, *, kid: str = "kid-1") -> str:
    header = {"alg": "RS256", "typ": "JWT", "kid": kid}
    signing_input = f"{_segment(header)}.{_segment(claims)}".encode("ascii")
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input.decode('ascii')}.{_b64url(signature)}"


def test_verify_id_token_accepts_valid_hs256() -> None:
    identity = verify_id_token(
        _hs256_token(_claims()), config=make_config(), jwks={}, nonce=NONCE
    )

    assert identity.subject == "user-1"
    assert identity.email == "user@example.com"
    assert identity.email_verified is True
    assert identity.name == "张三"


def test_verify_id_token_rejects_alg_none() -> None:
    token = f"{_segment({'alg': 'none'})}.{_segment(_claims())}."

    with pytest.raises(SsoTokenError, match="签名算法"):
        verify_id_token(token, config=make_config(), jwks={}, nonce=NONCE)


def test_verify_id_token_rejects_hs256_signed_with_rsa_public_key() -> None:
    # 算法混淆防护：攻击者用 RSA 公钥当 HMAC 密钥签 HS256，必须被拒。
    private_key, jwks = _rsa_keypair()
    jwk = jwks["keys"][0]
    forged_secret = f"{jwk['n']}.{jwk['e']}"

    with pytest.raises(SsoTokenError):
        verify_id_token(
            _hs256_token(_claims(), secret=forged_secret),
            config=make_config(),
            jwks=jwks,
            nonce=NONCE,
        )


def test_verify_id_token_accepts_valid_rs256() -> None:
    private_key, jwks = _rsa_keypair()

    identity = verify_id_token(
        _rs256_token(_claims(), private_key), config=make_config(), jwks=jwks, nonce=NONCE
    )

    assert identity.subject == "user-1"


def test_verify_id_token_rejects_unknown_kid() -> None:
    private_key, jwks = _rsa_keypair()

    with pytest.raises(SsoTokenError, match="公钥"):
        verify_id_token(
            _rs256_token(_claims(), private_key, kid="kid-x"),
            config=make_config(),
            jwks=jwks,
            nonce=NONCE,
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"iss": "https://evil.example"}, "签发方"),
        ({"aud": "other-client"}, "受众"),
        ({"aud": ["other-client"]}, "受众"),
        ({"azp": "other-client"}, "授权方"),
        ({"nonce": "wrong"}, "随机数"),
    ],
)
def test_verify_id_token_rejects_mismatched_claims(overrides: dict, message: str) -> None:
    with pytest.raises(SsoTokenError, match=message):
        verify_id_token(
            _hs256_token(_claims(**overrides)), config=make_config(), jwks={}, nonce=NONCE
        )


def test_verify_id_token_accepts_audience_list_containing_client() -> None:
    identity = verify_id_token(
        _hs256_token(_claims(aud=[CLIENT_ID, "other"])),
        config=make_config(),
        jwks={},
        nonce=NONCE,
    )
    assert identity.subject == "user-1"


def test_verify_id_token_rejects_expired() -> None:
    now = int(datetime.now(UTC).timestamp())

    with pytest.raises(SsoTokenError, match="过期"):
        verify_id_token(
            _hs256_token(_claims(exp=now - 3600)), config=make_config(), jwks={}, nonce=NONCE
        )


def test_verify_id_token_within_leeway_is_accepted() -> None:
    now = int(datetime.now(UTC).timestamp())

    identity = verify_id_token(
        _hs256_token(_claims(exp=now - 10)), config=make_config(), jwks={}, nonce=NONCE
    )
    assert identity.subject == "user-1"


def test_verify_id_token_rejects_missing_exp() -> None:
    claims = _claims()
    claims.pop("exp")

    with pytest.raises(SsoTokenError, match="过期"):
        verify_id_token(_hs256_token(claims), config=make_config(), jwks={}, nonce=NONCE)


def test_verify_id_token_rejects_future_iat() -> None:
    now = int(datetime.now(UTC).timestamp())

    with pytest.raises(SsoTokenError, match="签发时间"):
        verify_id_token(
            _hs256_token(_claims(iat=now + 3600)), config=make_config(), jwks={}, nonce=NONCE
        )


def test_verify_id_token_rejects_unverified_email() -> None:
    with pytest.raises(SsoTokenError, match="未验证邮箱"):
        verify_id_token(
            _hs256_token(_claims(email_verified=False)),
            config=make_config(),
            jwks={},
            nonce=NONCE,
        )


@pytest.mark.parametrize("field", ["sub", "email"])
def test_verify_id_token_rejects_missing_identity(field: str) -> None:
    claims = _claims()
    claims.pop(field)

    with pytest.raises(SsoTokenError):
        verify_id_token(_hs256_token(claims), config=make_config(), jwks={}, nonce=NONCE)


def test_verify_id_token_rejects_malformed_token() -> None:
    with pytest.raises(SsoTokenError, match="格式无效"):
        verify_id_token("not-a-jwt", config=make_config(), jwks={}, nonce=NONCE)


def test_verify_id_token_rejects_tampered_signature() -> None:
    token = _hs256_token(_claims(), secret="wrong-secret")

    with pytest.raises(SsoTokenError, match="签名"):
        verify_id_token(token, config=make_config(), jwks={}, nonce=NONCE)


def test_complete_authorization_chains_exchange_and_verify() -> None:
    def transport(method, url, *, headers, data=None, params=None, timeout):
        if method == "POST":
            return FakeResponse(payload={"id_token": _hs256_token(_claims())})
        return FakeResponse(payload={"keys": []})

    identity = complete_authorization(
        make_config(), code="c", code_verifier="v", nonce=NONCE, transport=transport
    )

    assert identity.subject == "user-1"


# --- state 仓储 ---------------------------------------------------------------


def _state(value: str = "st-1", *, created_at: datetime | None = None) -> SsoState:
    return SsoState(
        state=value,
        nonce="n-1",
        code_verifier="v-1",
        redirect_uri=REDIRECT_URI,
        created_at=created_at or datetime.now(UTC),
    )


def test_inmemory_state_consume_is_one_time() -> None:
    store = InMemorySsoStateStore()
    store.add(_state())

    consumed = store.consume("st-1", ttl_seconds=300)

    assert consumed.code_verifier == "v-1"
    with pytest.raises(SsoStateNotFound):
        store.consume("st-1", ttl_seconds=300)


def test_inmemory_state_consume_rejects_expired_and_removes_it() -> None:
    store = InMemorySsoStateStore()
    store.add(_state(created_at=datetime.now(UTC) - timedelta(seconds=600)))

    with pytest.raises(SsoStateNotFound):
        store.consume("st-1", ttl_seconds=300)
    # 过期项已被删除：purge 不再统计到它
    assert store.purge_expired(ttl_seconds=300) == 0


def test_inmemory_state_purge_expired_returns_count() -> None:
    store = InMemorySsoStateStore()
    store.add(_state("old", created_at=datetime.now(UTC) - timedelta(seconds=600)))
    store.add(_state("fresh"))

    assert store.purge_expired(ttl_seconds=300) == 1
    assert store.consume("fresh", ttl_seconds=300).state == "fresh"


class StateRecordingCursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.statements: list[tuple[str, tuple]] = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement: str, params: tuple = ()) -> None:
        self.statements.append((statement, params))
        self.rowcount = len(self.rows) if self.rows else 0

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


class StateRecordingConnection:
    def __init__(self, rows: list[object]) -> None:
        self.cursor_instance = StateRecordingCursor(rows)

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cursor_instance


def test_postgres_state_consume_uses_single_delete_returning() -> None:
    row = ("st-1", "n-1", "v-1", REDIRECT_URI, datetime.now(UTC))
    connection = StateRecordingConnection([row])
    store = PostgresSsoStateStore(connection)

    consumed = store.consume("st-1", ttl_seconds=300)

    assert consumed.state == "st-1"
    assert len(connection.cursor_instance.statements) == 1
    statement, params = connection.cursor_instance.statements[0]
    assert statement.strip().startswith("DELETE FROM workbench_sso_states")
    assert "WHERE state = %s" in statement
    assert "RETURNING" in statement
    assert params == ("st-1",)


def test_postgres_state_consume_raises_when_missing_or_expired() -> None:
    missing = PostgresSsoStateStore(StateRecordingConnection([]))
    with pytest.raises(SsoStateNotFound):
        missing.consume("st-1", ttl_seconds=300)

    expired_row = ("st-1", "n-1", "v-1", REDIRECT_URI, datetime.now(UTC) - timedelta(seconds=600))
    expired = PostgresSsoStateStore(StateRecordingConnection([expired_row]))
    with pytest.raises(SsoStateNotFound):
        expired.consume("st-1", ttl_seconds=300)


# --- 账号仓储 SSO -------------------------------------------------------------


def test_inmemory_find_by_email_is_case_insensitive() -> None:
    repository = InMemoryAccountRepository()
    account = repository.add(
        Account(
            phone="13800000001",
            password_hash="scrypt$hash",
            position="内容运营",
            full_name="张三",
            email="User@Example.com",
        )
    )

    assert repository.find_by_email(" user@example.COM ") is account
    assert repository.find_by_email("missing@example.com") is None


def test_inmemory_set_sso_identity_writes_back() -> None:
    repository = InMemoryAccountRepository()
    account = repository.add(
        Account(phone="13800000001", password_hash="scrypt$hash", position="内容运营", full_name="张三")
    )

    updated = repository.set_sso_identity(account.account_id, provider="generic_oidc", subject="sub-1")

    assert updated.sso_provider == "generic_oidc"
    assert updated.sso_subject == "sub-1"
    assert repository.get(account.account_id).sso_subject == "sub-1"


class RepoCursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.statements: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement: str, params: tuple = ()) -> None:
        self.statements.append((statement, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


class RepoConnection:
    def __init__(self, rows: list[object]) -> None:
        self.cursor_instance = RepoCursor(rows)

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cursor_instance


def _full_row() -> tuple:
    return (
        "acct-1", "13800000001", "scrypt$hash", "内容运营", "张三", "user@example.com",
        "employee", "t-1", "approved", datetime(2026, 9, 10, tzinfo=UTC),
        datetime(2026, 9, 11, tzinfo=UTC), "acct-admin", None,
        None, None, None, "generic_oidc", "sub-1",
    )


def test_postgres_columns_include_sso_and_match_placeholder_count() -> None:
    columns = [name.strip() for name in PostgresAccountRepository._COLUMNS.split(",")]

    assert columns[-2:] == ["sso_provider", "sso_subject"]
    connection = RepoConnection([_full_row()])
    repository = PostgresAccountRepository(connection)
    repository.add(
        Account(phone="13800000001", password_hash="scrypt$hash", position="内容运营", full_name="张三")
    )
    statement, params = connection.cursor_instance.statements[0]
    assert statement.count("%s") == len(columns)
    assert len(params) == len(columns)


def test_postgres_find_by_email_normalizes_and_returns_account() -> None:
    connection = RepoConnection([_full_row()])
    repository = PostgresAccountRepository(connection)

    account = repository.find_by_email(" USER@example.COM ")

    assert account is not None and account.account_id == "acct-1"
    statement, params = connection.cursor_instance.statements[0]
    assert "lower(btrim(email)) = %s" in statement
    assert params == ("user@example.com",)


def test_postgres_find_by_email_returns_none_when_absent() -> None:
    repository = PostgresAccountRepository(RepoConnection([]))

    assert repository.find_by_email("missing@example.com") is None


def test_postgres_set_sso_identity_updates_and_returns() -> None:
    connection = RepoConnection([_full_row()])
    repository = PostgresAccountRepository(connection)

    account = repository.set_sso_identity("acct-1", provider="generic_oidc", subject="sub-1")

    assert account.sso_subject == "sub-1"
    statement, params = connection.cursor_instance.statements[0]
    assert "UPDATE workbench_accounts" in statement
    assert "sso_provider = %s" in statement and "sso_subject = %s" in statement
    assert params == ("generic_oidc", "sub-1", "acct-1")


# --- 迁移与装配 ---------------------------------------------------------------


def test_migration_017_declares_sso_identity_and_states() -> None:
    content = (
        Path(__file__).resolve().parents[1] / "migrations" / "017_sso_identity.sql"
    ).read_text(encoding="utf-8")

    assert "sso_provider TEXT" in content
    assert "sso_subject TEXT" in content
    assert "CREATE TABLE IF NOT EXISTS workbench_sso_states" in content
    assert "state TEXT PRIMARY KEY" in content
    assert "idx_workbench_sso_states_created" in content


def test_build_sso_config_returns_none_when_disabled() -> None:
    assert build_sso_config(Settings(sso_enabled=False)) is None


def test_build_sso_config_raises_when_enabled_but_incomplete() -> None:
    with pytest.raises(ValueError, match="SSO 已启用但缺少必填配置"):
        build_sso_config(Settings(sso_enabled=True))


def test_build_sso_config_builds_when_complete() -> None:
    settings = Settings(
        sso_enabled=True,
        sso_issuer=ISSUER,
        sso_authorization_endpoint="https://idp.example/authorize",
        sso_token_endpoint="https://idp.example/token",
        sso_jwks_uri="https://idp.example/jwks",
        sso_client_id=CLIENT_ID,
        sso_client_secret=CLIENT_SECRET,
        sso_redirect_uri=REDIRECT_URI,
        sso_scopes="openid email",
    )

    config = build_sso_config(settings)

    assert config is not None
    assert config.scopes == ("openid", "email")
    assert config.client_id == CLIENT_ID


def test_build_sso_state_store_memory_in_development() -> None:
    store = build_sso_state_store(Settings(env="development", storage_backend="memory"))

    assert isinstance(store, InMemorySsoStateStore)


def test_build_sso_state_store_rejects_memory_in_production() -> None:
    settings = Settings(env="production", storage_backend="memory")

    # 生产环境的内存仓储一律被运行时校验拦截（fail-closed）。
    with pytest.raises(ValueError):
        build_sso_state_store(settings)


def test_build_sso_state_store_uses_injected_postgres_connection() -> None:
    settings = Settings(
        env="production",
        storage_backend="postgres",
        database_url="postgresql://workbench:pw@pg.internal:5432/workbench",
        auth_secret="a" * 32,
        backup_encryption_key="b" * 32,
        content_store_backend="sqlite",
    )

    store = build_sso_state_store(settings, connection=object(), migrate=False)

    assert isinstance(store, PostgresSsoStateStore)
