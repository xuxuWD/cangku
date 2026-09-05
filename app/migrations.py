from __future__ import annotations

from pathlib import Path


def apply_migrations(connection, directory: Path) -> list[str]:
    """Apply ordered SQL files exactly once inside independent transactions."""
    migration_files = sorted(directory.glob("*.sql"))
    if not migration_files:
        return []

    with connection.transaction():
        with connection.cursor() as cursor:
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

    newly_applied: list[str] = []
    for migration_file in migration_files:
        version = migration_file.stem
        if version in applied:
            continue
        sql = migration_file.read_text(encoding="utf-8")
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(sql)
                cursor.execute(
                    "INSERT INTO workbench_schema_migrations (version) VALUES (%s)",
                    (version,),
                )
        newly_applied.append(version)
    return newly_applied
