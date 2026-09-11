"""会话令牌服务端撤销的测试：内存/PostgreSQL 存储 + 登出接口端到端。

覆盖：撤销名单的过期语义与幂等、PostgreSQL 条件查询形状、
令牌暴露 `jti`/`exp`、登出后同一令牌立即失效而**其他令牌不受影响**、
无令牌登出与撤销存储故障时的 fail-closed。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import create_access_token, verify_access_token
from app.domain import UserContext
from app.sessions import InMemorySessionRevocationStore, PostgresSessionRevocationStore

SECRET = "s" * 40
PROBE_PATH = "/api/v1/approvals/pending"
LOGOUT_PATH = "/api/v1/auth/logout"


def future(seconds: int = 900) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=seconds)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- 存储层


def test_memory_store_revokes_idempotently_and_ignores_expired_entries() -> None:
    store = InMemorySessionRevocationStore()

    assert store.is_revoked("jti-1") is False
    store.revoke("jti-1", expires_at=future())
    store.revoke("jti-1", expires_at=future())  # 幂等：重复撤销不报错
    assert store.is_revoked("jti-1") is True

    # 判定依据：令牌本身过期后，撤销条目不再参与判定（也无需人工清理）。
    store.revoke("jti-2", expires_at=future(-1))
    assert store.is_revoked("jti-2") is False


class RecordingCursor:
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


class RecordingTransaction:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class RecordingConnection:
    def __init__(self, rows: list[object]) -> None:
        self.cursor_instance = RecordingCursor(rows)

    def transaction(self):
        return RecordingTransaction()

    def cursor(self):
        return self.cursor_instance


def test_postgres_store_upserts_and_checks_expiry_window() -> None:
    connection = RecordingConnection([(1,)])
    store = PostgresSessionRevocationStore(connection)

    store.revoke("jti-1", expires_at=future())
    statements = [statement for statement, _params in connection.cursor_instance.statements]
    insert_params = [params for statement, params in connection.cursor_instance.statements if "INSERT" in statement][0]
    assert any("INSERT INTO workbench_session_revocations" in statement for statement in statements)
    assert any("ON CONFLICT (token_id) DO UPDATE" in statement for statement in statements)
    # 顺带清理已过期条目，避免表无限增长。
    assert any("DELETE FROM workbench_session_revocations" in statement for statement in statements)
    assert insert_params[0] == "jti-1"

    assert store.is_revoked("jti-1") is True
    statement, params = connection.cursor_instance.statements[-1]
    assert "SELECT 1 FROM workbench_session_revocations" in statement
    assert "expires_at > now()" in statement
    assert params == ("jti-1",)


def test_postgres_store_reports_not_revoked_when_row_absent() -> None:
    connection = RecordingConnection([None])
    store = PostgresSessionRevocationStore(connection)

    assert store.is_revoked("jti-missing") is False


# ---------------------------------------------------------------- 令牌载荷


def test_verify_access_token_exposes_token_id_and_expiry() -> None:
    token = create_access_token(UserContext("t-1", "acct-1", "employee"), SECRET, ttl_seconds=900)

    context = verify_access_token(token, SECRET)

    # 判定依据：没有 jti 与过期时间就无法做服务端撤销。
    assert context.token_id
    assert context.expires_at is not None
    assert context.expires_at > datetime.now(UTC)


# ---------------------------------------------------------------- 接口


@pytest.fixture
def api(monkeypatch) -> tuple[TestClient, InMemorySessionRevocationStore]:
    store = InMemorySessionRevocationStore()
    monkeypatch.setattr(main.settings, "auth_secret", SECRET)
    monkeypatch.setattr(main, "session_revocation_store", store)
    return TestClient(main.app), store


def employee_token(user_id: str = "acct-a") -> str:
    return create_access_token(UserContext("t-1", user_id, "employee"), SECRET, ttl_seconds=900)


def test_logout_revokes_only_the_token_that_was_used(api) -> None:
    client, store = api
    token_a = employee_token("acct-a")
    token_b = employee_token("acct-b")

    assert client.get(PROBE_PATH, headers=bearer(token_a)).status_code == 200

    assert client.post(LOGOUT_PATH, headers=bearer(token_a)).status_code == 204

    # 判定依据：登出必须让**该令牌**立即失效，且不影响其他已签发令牌。
    assert client.get(PROBE_PATH, headers=bearer(token_a)).status_code == 401
    assert client.get(PROBE_PATH, headers=bearer(token_b)).status_code == 200
    assert store.is_revoked(verify_access_token(token_a, SECRET).token_id) is True
    assert store.is_revoked(verify_access_token(token_b, SECRET).token_id) is False


def test_logout_rejects_missing_or_header_identity(api) -> None:
    client, _store = api

    # 判定依据：无令牌时无法定位会话，必须 401（不能静默成功）。
    assert client.post(LOGOUT_PATH).status_code == 401
    header_only = client.post(
        LOGOUT_PATH, headers={"X-Tenant-Id": "t-1", "X-User-Id": "u-1", "X-User-Role": "employee"}
    )
    assert header_only.status_code == 401


def test_revocation_lookup_failure_fails_closed(api, monkeypatch) -> None:
    client, _store = api

    class Broken:
        def revoke(self, token_id, *, expires_at):  # pragma: no cover - 本用例不触发
            raise RuntimeError("db down")

        def is_revoked(self, token_id: str) -> bool:
            raise RuntimeError("db down")

    monkeypatch.setattr(main, "session_revocation_store", Broken())

    response = client.get(PROBE_PATH, headers=bearer(employee_token()))

    assert response.status_code == 503


def test_header_identity_sessions_do_not_consult_revocation_store(monkeypatch) -> None:
    class Broken:
        def revoke(self, token_id, *, expires_at):  # pragma: no cover - 本用例不触发
            raise RuntimeError("db down")

        def is_revoked(self, token_id: str) -> bool:
            raise RuntimeError("db down")

    monkeypatch.setattr(main.settings, "auth_secret", "")
    monkeypatch.setattr(main, "session_revocation_store", Broken())
    client = TestClient(main.app)

    response = client.get(
        PROBE_PATH,
        headers={"X-Tenant-Id": "t-1", "X-User-Id": "u-1", "X-User-Role": "employee"},
    )

    assert response.status_code == 200
