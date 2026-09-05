from pathlib import Path

import pytest

from app.settings import Settings, validate_runtime_settings


def test_production_requires_postgres_and_a_real_auth_secret() -> None:
    with pytest.raises(ValueError, match="生产环境必须使用 PostgreSQL"):
        validate_runtime_settings(
            Settings(env="production", storage_backend="memory", auth_secret="long-enough-secret")
        )

    with pytest.raises(ValueError, match="认证密钥至少需要 32 个字符"):
        validate_runtime_settings(
            Settings(
                env="production",
                storage_backend="postgres",
                database_url="postgresql://localhost/workbench",
                auth_secret="short",
            )
        )


def test_initial_migration_has_tenant_scoped_idempotency_and_atomic_approval_constraint() -> None:
    migration = Path("migrations/001_initial.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS workbench_tasks" in migration
    assert "UNIQUE (tenant_id, created_by, idempotency_key)" in migration
    assert "CHECK (status IN ('queued', 'pending_approval', 'cancelled'))" in migration
    assert "UPDATE workbench_tasks" in migration
    assert "WHERE id = $1 AND tenant_id = $2 AND status = 'pending_approval'" in migration
