"""迁移 `027_dsh_tool_execution.sql` 的静态契约。

口径沿用 `tests/test_persistence_contract.py` 与 `tests/test_orchestration_models.py`：
直接读迁移文本、**点名断言**关键结构，防止"改了 DDL 却没人发现"。

规格 §6 / §C3 要求本测试"点名断言两张新表的全部列与 3 个 CHECK"
（含 `args_json` / `body_ciphertext` / `body_expires_at` / `http_status` / `approval_id`
与 `body_check` / `result_check`）；§4.1.5 另要求可重复执行与语句顺序。
"""

from pathlib import Path

MIGRATION = Path("migrations/027_dsh_tool_execution.sql").read_text(encoding="utf-8")
STAGING_TEMPLATE = Path(".env.staging.example").read_text(encoding="utf-8")


def test_parent_unique_constraint_comes_before_new_tables() -> None:
    """R4-1：必须先补父表唯一约束，再建两张新表（否则复合外键引用不到唯一约束）。

    实现注意（2026-09-13 真库演练发现）：**不用** 024/025/026 的「DROP IF EXISTS + ADD」——
    027 的两张新表持有指向该唯一约束的复合外键，重跑时 DROP 会因依赖对象而失败。
    改用 DO 块按 `pg_constraint` 判定后增补（PostgreSQL 无 `ADD CONSTRAINT IF NOT EXISTS`），
    且**不使用 CASCADE**（否则会连带删掉两张表的复合外键）。
    """
    assert "ALTER TABLE workbench_run_records" in MIGRATION
    assert "ADD CONSTRAINT workbench_run_records_run_tenant_unique UNIQUE (run_id, tenant_id);" in MIGRATION
    assert "DROP CONSTRAINT IF EXISTS workbench_run_records_run_tenant_unique" not in MIGRATION
    assert "SELECT 1 FROM pg_constraint" in MIGRATION
    assert "AND conrelid = 'workbench_run_records'::regclass" in MIGRATION
    # 不使用 CASCADE（否则连带删掉两张表的复合外键）。注意本文件注释里出现过该词作说明，
    # 故断言"任一条 DROP 语句都不带 CASCADE"，而非"全文无 CASCADE"。
    for line in MIGRATION.splitlines():
        if "DROP" in line.upper():
            assert "CASCADE" not in line.upper(), f"DROP 语句不得使用 CASCADE：{line.strip()}"

    parent = MIGRATION.index("workbench_run_records_run_tenant_unique")
    first_table = MIGRATION.index("CREATE TABLE IF NOT EXISTS workbench_tool_actions")
    second_table = MIGRATION.index("CREATE TABLE IF NOT EXISTS workbench_execution_idempotency")
    assert parent < first_table < second_table


def test_tool_actions_table_declares_every_column() -> None:
    assert "CREATE TABLE IF NOT EXISTS workbench_tool_actions (" in MIGRATION
    for column in (
        "tenant_id",
        "action_id",
        "approval_id",
        "run_id",
        "task_id",
        "step_id",
        "tool_key",
        "args_digest",
        "args_json",
        "body_ciphertext",
        "body_expires_at",
        "plan_digest",
        "risk_level",
        "requires_approval",
        "status",
        "requested_by",
        "requested_at",
        "decided_by",
        "decided_at",
        "decision_source",
        "reason_code",
    ):
        assert column in MIGRATION, f"workbench_tool_actions 缺少列 {column}"

    assert "PRIMARY KEY (tenant_id, action_id)," in MIGRATION
    # 租户隔离写进约束（与 migrations/023 同思路），不只靠 WHERE。
    assert "FOREIGN KEY (tenant_id, run_id) REFERENCES workbench_run_records (tenant_id, run_id)," in MIGRATION


def test_tool_actions_declares_two_named_checks_and_enums() -> None:
    assert "CONSTRAINT workbench_tool_actions_decision_check CHECK (" in MIGRATION
    assert "CONSTRAINT workbench_tool_actions_body_check CHECK (" in MIGRATION
    # body_check：密文与到期时刻同有同无（J7 = 丙案）
    assert "(body_ciphertext IS NULL AND body_expires_at IS NULL)" in MIGRATION
    assert "(body_ciphertext IS NOT NULL AND body_expires_at IS NOT NULL)" in MIGRATION
    # 状态与风险档由 CHECK 显式枚举
    assert "CHECK (risk_level IN ('low','medium','high','critical'))" in MIGRATION
    assert "CHECK (status IN ('pending','approved','rejected','expired'))" in MIGRATION


def test_tool_actions_indexes() -> None:
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_workbench_tool_actions_pending_unique" in MIGRATION
    assert "WHERE status = 'pending';" in MIGRATION
    assert "CREATE INDEX IF NOT EXISTS idx_workbench_tool_actions_run" in MIGRATION
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_workbench_tool_actions_approval" in MIGRATION
    assert "WHERE approval_id IS NOT NULL;" in MIGRATION


def test_idempotency_table_declares_every_column() -> None:
    assert "CREATE TABLE IF NOT EXISTS workbench_execution_idempotency (" in MIGRATION
    for column in (
        "tenant_id",
        "actor_id",
        "conversation_id",
        "idempotency_key",
        "message_id",
        "run_id",
        "approval_id",
        "outcome",
        "http_status",
        "created_at",
    ):
        assert column in MIGRATION, f"workbench_execution_idempotency 缺少列 {column}"

    assert "PRIMARY KEY (tenant_id, actor_id, conversation_id, idempotency_key)," in MIGRATION
    assert "REFERENCES workbench_conversations (tenant_id, conversation_id)," in MIGRATION
    assert "REFERENCES workbench_conversation_messages (tenant_id, message_id)," in MIGRATION
    assert "REFERENCES workbench_run_records (tenant_id, run_id)," in MIGRATION
    assert "CHECK (outcome IN ('executed','pending_approval','rejected','failed'))" in MIGRATION


def test_idempotency_result_check_pins_status_codes() -> None:
    assert "CONSTRAINT workbench_execution_idempotency_result_check CHECK (" in MIGRATION
    assert "(outcome = 'executed'            AND http_status = 201)" in MIGRATION
    assert "OR (outcome = 'pending_approval' AND http_status = 202)" in MIGRATION
    assert "OR (outcome = 'rejected'         AND http_status IN (403, 404, 409, 422))" in MIGRATION
    assert "OR (outcome = 'failed'           AND http_status IN (502, 504))" in MIGRATION
    assert "CREATE INDEX IF NOT EXISTS idx_workbench_execution_idempotency_run" in MIGRATION


def test_migration_is_repeatable_and_non_destructive() -> None:
    """§4.1.5：DDL 一律 IF NOT EXISTS / DROP ... IF EXISTS + ADD；无自动回滚故必须可重复执行。"""
    assert MIGRATION.count("CREATE TABLE ") == 2
    assert MIGRATION.count("CREATE TABLE IF NOT EXISTS") == 2
    assert MIGRATION.count("CREATE UNIQUE INDEX IF NOT EXISTS") == 2
    assert MIGRATION.count("CREATE INDEX IF NOT EXISTS") == 2
    # 破坏性语句一律不得出现
    for forbidden in ("DROP TABLE", "DELETE FROM", "TRUNCATE", "ALTER COLUMN", "DROP COLUMN"):
        assert forbidden not in MIGRATION, f"迁移不应包含 {forbidden}"


def test_staging_template_registers_migration_027() -> None:
    """漏登则 staging 预检永久 blocked（tests/test_staging_assets.py 会逐条相等断言）。

    末项断言只校验「登记行以 `migrations/` 的最新编号结尾」——`027` 曾是写入时的最新编号，
    现由 `028_workbench_export_packages` 接续；故改用动态最新编号，避免每次新增迁移都需手改常量，
    同时保留「登记行没有尾部漂移」这一原始覆盖。
    """
    assert "027_dsh_tool_execution" in STAGING_TEMPLATE
    line = next(
        item for item in STAGING_TEMPLATE.splitlines() if item.startswith("WORKBENCH_APPLIED_MIGRATIONS=")
    )
    newest = sorted(path.stem for path in Path("migrations").glob("*.sql"))[-1]
    assert line.rstrip().endswith(newest)
