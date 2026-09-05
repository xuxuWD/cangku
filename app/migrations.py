from __future__ import annotations

from contextlib import contextmanager, nullcontext
from pathlib import Path


@contextmanager
def _connection(connection_or_pool):
    if hasattr(connection_or_pool, "connection") and callable(connection_or_pool.connection):
        with connection_or_pool.connection() as connection:
            yield connection
    else:
        with nullcontext(connection_or_pool) as connection:
            yield connection


def apply_migrations(connection, directory: Path) -> list[str]:
    """Apply ordered SQL files once under a PostgreSQL transaction advisory lock."""
    migration_files = sorted(directory.glob("*.sql"))
    if not migration_files:
        return []

    newly_applied: list[str] = []
    with _connection(connection) as leased:
        with leased.transaction():
            with leased.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext('company-workbench:migrations'))", ())
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workbench_schema_migrations (
                        version TEXT PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """,
                    (),
                )
                cursor.execute("SELECT version FROM workbench_schema_migrations", ())
                applied = {str(row[0]) for row in cursor.fetchall()}
                for migration_file in migration_files:
                    version = migration_file.stem
                    if version in applied:
                        continue
                    cursor.execute(migration_file.read_text(encoding="utf-8"))
                    cursor.execute(
                        "INSERT INTO workbench_schema_migrations (version) VALUES (%s)",
                        (version,),
                    )
                    newly_applied.append(version)
    return newly_applied
