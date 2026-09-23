"""租户 schema 模板链的构建与校验脚本（Schema 级多租户改造 · S0 准备阶段）。

背景
    方案见 ``docs/contracts/schema-per-tenant-plan.md``：``public`` 单 schema 行级隔离
    改造为「每租户一套 schema」。本脚本只服务 S0：产出并校验**租户模板链**，
    不写任何业务实现。

子命令
    build-template
        在测试容器内跑 ``pg_dump --schema-only``，按语句解析 -> 只保留
        ``migrations/tenant_template/classification.json`` 中 ``tenant_schema``（A 组 53 张）的
        ``CREATE TABLE`` / ``CREATE [UNIQUE] INDEX`` / ``ALTER TABLE ... ADD CONSTRAINT`` /
        ``CREATE SEQUENCE`` / ``ALTER SEQUENCE ... OWNED BY`` /
        ``ALTER TABLE ... ALTER COLUMN ... SET DEFAULT nextval(...)``（后三类仅当序列**由 A 组表拥有**）；
        去掉 ``public.`` schema 限定（改裸名，靠 search_path 解析）；把指向 B/C 组平台表的
        ``REFERENCES`` 改写为 ``${PLATFORM_SCHEMA}.<表名>``；输出
        ``migrations/tenant_template/0001_tenant_baseline.sql``（纯 DDL，不做 IF NOT EXISTS 幂等化）。
    verify
        ① 分类与实测一致：含 tenant_id 的 workbench_ 表集合 == A∪B；不含 tenant_id 的 == C；
        ② 模板覆盖：模板里的 CREATE TABLE 集合 == A；
        ③ ``--apply``：建临时 schema -> 应用模板（${PLATFORM_SCHEMA} 替换为 public）-> 与 public
           逐表比对「表/列（含 column_default）/索引/约束」集合 -> 无论成败都清理临时 schema。
           退出码 0 通过 / 1 失败 / 2 参数错误。
    inventory
        列出当前库所有 schema 及其表数；对本项目 schema（``t_%`` 与 ``platform``）再打印逐表行数。

S0 期决策（来自用户裁决，勿在本脚本内改口径）
    模板保持**纯 DDL**，不加 ``IF NOT EXISTS`` 幂等包装；幂等性由 S1 的
    「单事务应用 + 版本台账（workbench_tenant_schema_versions）」保证。

覆盖范围与归一化口径
    - **序列随表入租户 schema**：属于 A 组表的序列（`CREATE SEQUENCE` / `OWNED BY` /
      列的 `nextval` 默认值）一并进模板并去掉 schema 限定，保证新租户 schema 的自增行为与 public 一致。
    - 结构比对**含 column_default**；跨 schema 比较前统一做前缀归一化，否则 `nextval` 的
      regclass 文本会因 schema 不同而虚假不等 —— 规则见 `canonicalize()` 的输出说明。
    - 扩展类型与其 opclass（如 ``public.vector`` / ``public.vector_cosine_ops``）按方案只对
      ``REFERENCES`` 做占位符改写，故 DDL 中仍保留 ``public.`` 限定（扩展装在 public）。

未覆盖的结构差异类别（如实登记，勿读成已覆盖）
    - 触发器 / 规则、函数与存储过程、视图与物化视图、自定义类型与域、扩展对象本身（`CREATE EXTENSION`）、
      表与列的 COMMENT、GRANT / 所有者 / 表空间 / 存储参数、行级安全策略（RLS）、分区与继承。
      本项目当前 `public` 中 A 组表不涉及上述对象，故未纳入模板；一旦出现须扩展本脚本。

依赖：仅标准库 + psycopg。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "migrations" / "tenant_template"
CLASSIFICATION_PATH = TEMPLATE_DIR / "classification.json"
TEMPLATE_SQL_PATH = TEMPLATE_DIR / "0001_tenant_baseline.sql"

GENERATOR_VERSION = "tenant_schema.py/1.1.0"

CONTAINER_NAME = "wb-test-postgres-1"
DB_NAME = "workbench_test"
DB_USER = "workbench_test"
DB_HOST = "127.0.0.1"
DB_PORT = 55433

#: 平台 schema 占位符：模板中指向平台表的 REFERENCES 一律写成它，S1 执行时替换为真实 schema 名。
PLATFORM_SCHEMA = "${PLATFORM_SCHEMA}"

#: 测试库口令：优先读环境变量，其次向容器索取（容器内为 socket trust，TCP 需口令）。
PASSWORD_ENV = "WORKBENCH_TEST_POSTGRES_PASSWORD"

DUMP_COMMAND = (
    "docker exec {container} pg_dump -U {user} --schema-only --no-owner --no-privileges "
    "--dbname={db}"
).format(container=CONTAINER_NAME, user=DB_USER, db=DB_NAME)

_CREATE_TABLE_RE = re.compile(r"^CREATE TABLE ([^\s(]+)\s*\(")
_CREATE_INDEX_RE = re.compile(r"^CREATE (?:UNIQUE )?INDEX ([^\s]+) ON ([^\s(]+)")
_ALTER_TABLE_CONSTRAINT_RE = re.compile(r"^ALTER TABLE (?:ONLY )?([^\s]+)\s+ADD CONSTRAINT\s")
_CREATE_SEQUENCE_RE = re.compile(r"^CREATE SEQUENCE ([^\s;]+)")
_ALTER_SEQUENCE_OWNED_RE = re.compile(r"^ALTER SEQUENCE ([^\s]+)\s+OWNED BY\s+([^\s;]+)\s*;", re.S)
_ALTER_TABLE_SET_DEFAULT_RE = re.compile(
    r"^ALTER TABLE (?:ONLY )?([^\s]+)\s+ALTER COLUMN\s+(\S+)\s+SET DEFAULT\s+(.+?);\s*$", re.S
)
_NEXTVAL_RE = re.compile(r"nextval\('([^']+)'::regclass\)")
_QUALIFIED_NAME_RE = re.compile(r"([A-Za-z_][A-Za-z_0-9]*)\.([A-Za-z_][A-Za-z_0-9]*)")

#: 归一化标记：本 schema 内自有对象 / 平台 schema 上的 B/C 组对象。
SELF_MARK = "<SELF>"
PLATFORM_MARK = "<PLATFORM>"

#: 归一化规则的人类可读说明（会打印在 verify 输出里，避免"静默比对"）。
CANONICALIZE_RULE = (
    f"比对前归一化 schema 前缀：<本 schema>.<自有对象> -> {SELF_MARK}.<名>；"
    f"平台 schema 上的 B/C 组对象 -> {PLATFORM_MARK}.<名>；其余前缀原样保留"
)


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def load_classification() -> dict:
    """读取分类清单，并硬校验三个数组的元素个数（防清单被误改后静默通过）。"""
    if not CLASSIFICATION_PATH.exists():
        raise SystemExit(f"缺少分类清单：{CLASSIFICATION_PATH}")
    data = json.loads(CLASSIFICATION_PATH.read_text(encoding="utf-8"))
    # ⚠️ 这三个数是**硬校验**（防清单被误改后静默通过）⇒ 结构变更导致表数合法变化时，
    #    **必须同步改这里**，否则 build-template / verify 会直接 SystemExit。
    #    2026-09-24：迁移 045 新增 2 张 A 组表 ⇒ tenant_schema 51 → 53。
    for key, expected in (
        ("tenant_schema", 53),
        ("platform_tenant_scoped", 4),
        ("platform_core", 6),
    ):
        values = data.get(key)
        if not isinstance(values, list):
            raise SystemExit(f"classification.json 缺少数组字段：{key}")
        if len(values) != expected:
            raise SystemExit(f"classification.json 的 {key} 有 {len(values)} 项，期望 {expected} 项")
        if len(set(values)) != len(values):
            raise SystemExit(f"classification.json 的 {key} 存在重复项")
    return data


def tenant_set(classification: dict) -> set[str]:
    return set(classification["tenant_schema"])


def platform_set(classification: dict) -> set[str]:
    """B 组（平台上的租户级表）∪ C 组（平台核心表）。"""
    return set(classification["platform_tenant_scoped"]) | set(classification["platform_core"])


def split_qualified(name: str) -> tuple[str, str]:
    """拆分 ``public.workbench_tasks`` -> (``public``, ``workbench_tasks``)。"""
    if "." in name:
        schema, _, bare = name.rpartition(".")
        return schema.strip('"'), bare.strip('"')
    return "", name.strip('"')


def _paren_delta(line: str, in_quote: bool) -> tuple[int, bool]:
    """统计一行中括号的净增数（跳过单引号字符串内的括号，处理 ``''`` 转义）。"""
    delta = 0
    index = 0
    while index < len(line):
        char = line[index]
        if in_quote:
            if char == "'":
                if index + 1 < len(line) and line[index + 1] == "'":
                    index += 2
                    continue
                in_quote = False
        elif char == "'":
            in_quote = True
        elif char == "(":
            delta += 1
        elif char == ")":
            delta -= 1
        index += 1
    return delta, in_quote


def split_statements(text: str) -> list[str]:
    """按语句解析 pg_dump 文本。

    不能在顶格行上切分：``CREATE TABLE`` 的收尾 ``);`` 本身就顶格。改为「括号配平 +
    以 ``;`` 收尾」判定语句结束，即可稳定处理多行的 ``CREATE TABLE``（体内含内联 CHECK）
    与 ``ALTER TABLE ... ADD CONSTRAINT``；空行与 ``--`` 注释块在语句之间被忽略。
    """
    statements: list[str] = []
    current: list[str] = []
    depth = 0
    in_quote = False

    def flush() -> None:
        if current:
            statements.append("\n".join(current))
            current.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        delta, in_quote = _paren_delta(line, in_quote)
        depth += delta
        if depth <= 0 and line.rstrip().endswith(";"):
            flush()
            depth = 0
            in_quote = False
    flush()
    return statements


def rewrite_public_refs(text: str, local: set[str], platform: set[str]) -> str:
    """改写语句中的 ``public.<对象>`` 限定。

    - ``public.<local 里的对象>``（A 组表、以及由 A 组表拥有的序列）-> 去掉 schema 限定
      （裸名，靠 search_path 解析）；
    - ``public.<B/C 组表>`` -> ``${PLATFORM_SCHEMA}.<表名>``（与部署环境无关的占位符）；
    - 其他（如扩展类型 ``public.vector``）保持原样。
    """

    def replace(match: re.Match[str]) -> str:
        schema, name = match.group(1), match.group(2)
        if schema != "public":
            return match.group(0)
        if name in platform:
            return f"{PLATFORM_SCHEMA}.{name}"
        if name in local:
            return name
        return match.group(0)

    return _QUALIFIED_NAME_RE.sub(replace, text)


def canonicalize(text: str, self_schema: str, local: set[str], platform: set[str]) -> str:
    """把对象定义里的 schema 限定归一化，便于跨 schema 比对（规则见 ``CANONICALIZE_RULE``）。

    - ``<self_schema>.<local 里的对象>`` -> ``<SELF>.<名>``（如 ``nextval`` 的 regclass 文本）
    - B/C 组平台表（无论写成 ``public.`` 还是 ``<self_schema>.``）-> ``<PLATFORM>.<名>``
    - 其余前缀原样保留（如扩展类型 ``public.vector`` 在两个 schema 下同为 ``public.vector``）
    """

    def replace(match: re.Match[str]) -> str:
        schema, name = match.group(1), match.group(2)
        if schema == self_schema:
            if name in local:
                return f"{SELF_MARK}.{name}"
            if name in platform:
                return f"{PLATFORM_MARK}.{name}"
        if schema == "public" and name in platform:
            return f"{PLATFORM_MARK}.{name}"
        return match.group(0)

    return _QUALIFIED_NAME_RE.sub(replace, text)


def discover_owned_sequences(statements: list[str], tenant: set[str]) -> dict[str, str]:
    """从 dump 里找出**由 A 组表拥有**的序列。

    依据 ``ALTER SEQUENCE <seq> OWNED BY <table>.<col>;``：只有 OWNED BY 指向 A 组表的
    序列才纳入模板（B/C 组表与他项目对象的序列一律跳过）。返回 ``{序列名: 所属表名}``。
    """
    owned: dict[str, str] = {}
    for statement in statements:
        match = _ALTER_SEQUENCE_OWNED_RE.match(statement)
        if not match:
            continue
        _, sequence = split_qualified(match.group(1))
        table_ref = match.group(2).rsplit(".", 1)[0]
        _, table = split_qualified(table_ref)
        if table in tenant:
            owned[sequence] = table
    return owned


def fetch_template_sequences() -> set[str]:
    """从模板里读出 ``CREATE SEQUENCE`` 的序列名集合（不要求模板先存在之外的其它前置）。"""
    if not TEMPLATE_SQL_PATH.exists():
        raise SystemExit(f"缺少租户模板：{TEMPLATE_SQL_PATH}（先跑 build-template）")
    sequences: set[str] = set()
    for statement in split_statements(TEMPLATE_SQL_PATH.read_text(encoding="utf-8")):
        match = _CREATE_SEQUENCE_RE.match(statement)
        if match:
            _, name = split_qualified(match.group(1))
            sequences.add(name)
    return sequences


# --------------------------------------------------------------------------- #
# 数据库连接 / dump
# --------------------------------------------------------------------------- #
def resolve_password() -> str:
    password = os.environ.get(PASSWORD_ENV)
    if password:
        return password
    result = subprocess.run(
        ["docker", "exec", CONTAINER_NAME, "printenv", "POSTGRES_PASSWORD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    password = (result.stdout or "").strip()
    if result.returncode != 0 or not password:
        raise SystemExit(
            f"无法获取测试库口令：请设置 {PASSWORD_ENV}，或确认容器 {CONTAINER_NAME} 正在运行"
        )
    return password


def connect_db(autocommit: bool = True) -> psycopg.Connection:
    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=resolve_password(),
        autocommit=autocommit,
    )


def run_dump() -> str:
    result = subprocess.run(
        ["docker", "exec", CONTAINER_NAME, "pg_dump", "-U", DB_USER, "--schema-only",
         "--no-owner", "--no-privileges", "--dbname", DB_NAME],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise SystemExit(f"pg_dump 失败（退出码 {result.returncode}）：\n{result.stderr}")
    return result.stdout


# --------------------------------------------------------------------------- #
# build-template
# --------------------------------------------------------------------------- #
def cmd_build_template(_args: argparse.Namespace) -> int:
    classification = load_classification()
    tenant = tenant_set(classification)
    platform = platform_set(classification)

    dump = run_dump()
    statements = split_statements(dump)

    # 仅纳入「由 A 组表拥有」的序列；这些序列名也参与去 schema 限定（与 A 组表同等对待）。
    owned_sequences = discover_owned_sequences(statements, tenant)
    local = tenant | set(owned_sequences)

    rendered: list[str] = []
    counters = {"table": 0, "index": 0, "constraint": 0, "sequence": 0, "set_default": 0}
    for statement in statements:
        match = _CREATE_TABLE_RE.match(statement)
        if match:
            _, name = split_qualified(match.group(1))
            if name in tenant:
                rendered.append(rewrite_public_refs(statement, local, platform))
                counters["table"] += 1
            continue

        match = _CREATE_INDEX_RE.match(statement)
        if match:
            _, table = split_qualified(match.group(2))
            if table in tenant:
                rendered.append(rewrite_public_refs(statement, local, platform))
                counters["index"] += 1
            continue

        match = _ALTER_TABLE_CONSTRAINT_RE.match(statement)
        if match:
            _, table = split_qualified(match.group(1))
            if table in tenant:
                rendered.append(rewrite_public_refs(statement, local, platform))
                counters["constraint"] += 1
            continue

        match = _CREATE_SEQUENCE_RE.match(statement)
        if match:
            _, sequence = split_qualified(match.group(1))
            if sequence in owned_sequences:
                rendered.append(rewrite_public_refs(statement, local, platform))
                counters["sequence"] += 1
            continue

        match = _ALTER_SEQUENCE_OWNED_RE.match(statement)
        if match:
            _, sequence = split_qualified(match.group(1))
            if sequence in owned_sequences:
                rendered.append(rewrite_public_refs(statement, local, platform))
            continue

        match = _ALTER_TABLE_SET_DEFAULT_RE.match(statement)
        if match:
            _, table = split_qualified(match.group(1))
            nextval = _NEXTVAL_RE.search(statement)
            sequence = split_qualified(nextval.group(1))[1] if nextval else None
            if table in tenant and sequence in owned_sequences:
                rendered.append(rewrite_public_refs(statement, local, platform))
                counters["set_default"] += 1
            continue
        # 其余（CREATE EXTENSION / COMMENT / SET / GRANT / OWNER TO / 他项目对象、
        # 以及不属于 A 组表拥有的序列）一律跳过。

    placeholder_count = sum(text.count(PLATFORM_SCHEMA) for text in rendered)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    header = "\n".join(
        [
            "-- =========================================================================",
            "-- 租户 schema 基线 DDL（S0 生成物 · 自动生成，请勿手工编辑）",
            f"-- 生成器：{GENERATOR_VERSION}（scripts/tenant_schema.py build-template）",
            f"-- 生成日期：{date}（UTC）",
            f"-- 生成命令：py scripts/tenant_schema.py build-template",
            f"--           -> {DUMP_COMMAND}",
            f"-- 源库：容器 {CONTAINER_NAME} / 库 {DB_NAME} / schema public（PostgreSQL 16.15）",
            f"-- 表数：{counters['table']}（= classification.json 的 tenant_schema 集合）",
            f"-- 索引数：{counters['index']}",
            f"-- 约束数：{counters['constraint']}",
            f"-- 序列数（CREATE SEQUENCE，均由 A 组表拥有）：{counters['sequence']}",
            f"-- SET DEFAULT nextval 条数：{counters['set_default']}",
            f"-- {PLATFORM_SCHEMA} 改写：{placeholder_count} 处（指向 B/C 组平台表的外键）",
            "-- 说明：纯 DDL，不做 IF NOT EXISTS 幂等化；幂等由「单事务应用 + 版本台账」保证（S1 实现）。",
            "-- 说明：属于 A 组表的序列随表入租户 schema（去 public 限定），保证自增行为与 public 一致。",
            "-- 说明：语句内的 public.vector / public.vector_cosine_ops 等扩展对象按方案不做占位符改写。",
            "-- =========================================================================",
            "",
        ]
    )

    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATE_SQL_PATH.write_text(header + "\n\n".join(rendered) + "\n", encoding="utf-8", newline="\n")

    print(f"已生成：{TEMPLATE_SQL_PATH}")
    print(f"  表数（CREATE TABLE）：{counters['table']}")
    print(f"  索引数（CREATE [UNIQUE] INDEX）：{counters['index']}")
    print(f"  约束数（ALTER TABLE ... ADD CONSTRAINT）：{counters['constraint']}")
    print(f"  序列数（CREATE SEQUENCE，A 组表自有）：{counters['sequence']}")
    print(f"  SET DEFAULT nextval 条数：{counters['set_default']}")
    print(f"  {PLATFORM_SCHEMA} 改写处数：{placeholder_count}")
    if counters["table"] != len(tenant):
        print(
            f"  [失败] 模板表数 {counters['table']} 与 classification.json 的 {len(tenant)} 不一致",
            file=sys.stderr,
        )
        return 1
    return 0


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #
def fetch_db_classification(conn: psycopg.Connection) -> tuple[set[str], set[str]]:
    """返回（含 tenant_id 的 workbench_ 表, 不含 tenant_id 的 workbench_ 表）。"""
    rows = conn.execute(
        """
        SELECT t.table_name,
               EXISTS (
                   SELECT 1 FROM information_schema.columns c
                   WHERE c.table_schema = t.table_schema
                     AND c.table_name = t.table_name
                     AND c.column_name = 'tenant_id'
               ) AS has_tenant_id
        FROM information_schema.tables t
        WHERE t.table_schema = 'public'
          AND t.table_type = 'BASE TABLE'
          AND left(t.table_name, 10) = 'workbench_'
        """
    ).fetchall()
    with_tenant = {name for name, has in rows if has}
    without_tenant = {name for name, has in rows if not has}
    return with_tenant, without_tenant


def fetch_template_tables() -> set[str]:
    if not TEMPLATE_SQL_PATH.exists():
        raise SystemExit(f"缺少租户模板：{TEMPLATE_SQL_PATH}（先跑 build-template）")
    tables: set[str] = set()
    for statement in split_statements(TEMPLATE_SQL_PATH.read_text(encoding="utf-8")):
        match = _CREATE_TABLE_RE.match(statement)
        if match:
            _, name = split_qualified(match.group(1))
            tables.add(name)
    return tables


def collect_schema_objects(
    conn: psycopg.Connection,
    schema: str,
    local: set[str],
    platform: set[str],
) -> dict[str, dict[str, set]]:
    """采集某 schema 的表/列（含默认值）/索引/约束集合，键为表名。

    ``column_default`` 一并采集且按 ``canonicalize`` 归一化 —— 这样「缺序列 / 缺 nextval 默认值」
    这类保真度缺口不可能被比对漏过。采集前调用方须把 ``search_path`` 置空，保证定义文本全带 schema 限定。
    """
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
            (schema,),
        )
    }
    columns: dict[str, set] = {}
    for table, column, data_type, udt, nullable, default in conn.execute(
        "SELECT table_name, column_name, data_type, udt_name, is_nullable, column_default "
        "FROM information_schema.columns WHERE table_schema = %s",
        (schema,),
    ):
        columns.setdefault(table, set()).add(
            (
                column,
                data_type,
                udt,
                nullable,
                canonicalize(default or "", schema, local, platform),
            )
        )

    indexes: dict[str, set] = {}
    for table, index, definition in conn.execute(
        "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = %s",
        (schema,),
    ):
        indexes.setdefault(table, set()).add(
            (index, canonicalize(definition, schema, local, platform))
        )

    constraints: dict[str, set] = {}
    for table, name, contype, definition in conn.execute(
        "SELECT cl.relname, c.conname, c.contype, pg_get_constraintdef(c.oid) "
        "FROM pg_constraint c "
        "JOIN pg_class cl ON cl.oid = c.conrelid "
        "JOIN pg_namespace n ON n.oid = cl.relnamespace "
        "WHERE n.nspname = %s",
        (schema,),
    ):
        constraints.setdefault(table, set()).add(
            (name, contype, canonicalize(definition, schema, local, platform))
        )

    return {
        "tables": tables,
        "columns": columns,
        "indexes": indexes,
        "constraints": constraints,
    }


def compare_with_public(
    reference: dict[str, dict[str, set]],
    candidate: dict[str, dict[str, set]],
    tenant: set[str],
) -> list[str]:
    problems: list[str] = []

    ref_tables = reference["tables"] & tenant
    cand_tables = candidate["tables"] & tenant
    if ref_tables != cand_tables:
        missing = sorted(ref_tables - cand_tables)
        extra = sorted(cand_tables - ref_tables)
        problems.append(f"表集合不一致：临时 schema 缺少 {missing[:5]}；多出 {extra[:5]}")

    for table in sorted(tenant):
        for label, key in (
            ("列（含默认值）", "columns"),
            ("索引", "indexes"),
            ("约束", "constraints"),
        ):
            ref_values = reference[key].get(table, set())
            cand_values = candidate[key].get(table, set())
            if ref_values != cand_values:
                only_ref = sorted(ref_values - cand_values, key=str)[:3]
                only_cand = sorted(cand_values - ref_values, key=str)[:3]
                problems.append(
                    f"{table} 的{label}集合不一致：仅 public 有 {only_ref}；仅临时 schema 有 {only_cand}"
                )
    return problems


def apply_template_to_temp_schema(
    conn: psycopg.Connection,
    temp_schema: str,
    tenant: set[str],
    local: set[str],
    platform: set[str],
) -> list[str]:
    """在临时 schema 内应用模板，并与 public 的 A 组表逐项比对；返回差异列表。"""
    body = TEMPLATE_SQL_PATH.read_text(encoding="utf-8").replace(PLATFORM_SCHEMA, "public")
    # search_path 只放临时 schema：裸名建表/建序列落在临时 schema；跨 schema 引用已在模板中显式限定。
    conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(temp_schema)))
    count = 0
    for statement in split_statements(body):
        conn.execute(statement)
        count += 1
    print(f"  [apply] 临时 schema {temp_schema} 内执行 {count} 条语句成功")

    # 清空 search_path，让对象定义全部带 schema 限定，便于精确比对。
    conn.execute("SET search_path TO ''")
    temp_objects = collect_schema_objects(conn, temp_schema, local, platform)
    public_objects = collect_schema_objects(conn, "public", local, platform)
    return compare_with_public(public_objects, temp_objects, tenant)


def cmd_verify(args: argparse.Namespace) -> int:
    classification = load_classification()
    tenant = tenant_set(classification)
    platform = platform_set(classification)
    failures: list[str] = []

    conn = connect_db(autocommit=True)
    try:
        # ① 分类与实测一致
        print("[1/3] 分类清单 vs 实测库")
        with_tenant, without_tenant = fetch_db_classification(conn)
        # 含 tenant_id 的应 == A ∪ B（B 组虽留在平台 schema，但仍是「行属某租户」的表）
        expected_with = tenant | set(classification["platform_tenant_scoped"])
        expected_without = set(classification["platform_core"])
        ok1 = True
        if with_tenant != expected_with:
            ok1 = False
            print("  [失败] 含 tenant_id 的表集合不一致")
            print(f"         实测有清单无：{sorted(with_tenant - expected_with)}")
            print(f"         清单有实测无：{sorted(expected_with - with_tenant)}")
        if without_tenant != expected_without:
            ok1 = False
            print(f"  [失败] 不含 tenant_id 的表集合不一致")
            print(f"         实测有清单无：{sorted(without_tenant - expected_without)}")
            print(f"         清单有实测无：{sorted(expected_without - without_tenant)}")
        if ok1:
            print(
                f"  [通过] 含 tenant_id {len(with_tenant)} 张（A {len(tenant)} + B {len(classification['platform_tenant_scoped'])}）"
                f"；不含 tenant_id {len(without_tenant)} 张"
            )
        else:
            failures.append("分类清单与实测库不一致")

        # ② 模板覆盖
        print("[2/3] 模板 CREATE TABLE 集合 vs classification.json 的 tenant_schema")
        template_tables = fetch_template_tables()
        if template_tables == tenant:
            print(f"  [通过] 模板覆盖 {len(template_tables)} 张表，与 A 组一致")
        else:
            failures.append("模板表集合与 A 组不一致")
            print(f"  [失败] 模板有清单无：{sorted(template_tables - tenant)}")
            print(f"  [失败] 清单有模板无：{sorted(tenant - template_tables)}")

        # 归一化需知道「本 schema 自有对象」= A 组表 + 模板里由 A 组表拥有的序列。
        template_sequences = fetch_template_sequences()
        local = tenant | template_sequences
        print(
            f"  [信息] 模板含序列 {len(template_sequences)} 个：{sorted(template_sequences)}；"
            f"归一化规则：{CANONICALIZE_RULE}"
        )

        # ③ --apply 空库跑通
        if args.apply:
            print("[3/3] 空库试跑（临时 schema 应用模板，比对 public）")
            temp_schema = "t_verify_" + secrets.token_hex(4)
            created = False
            try:
                conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(temp_schema)))
                created = True
                differences = apply_template_to_temp_schema(
                    conn, temp_schema, tenant, local, platform
                )
                if differences:
                    failures.append("临时 schema 与 public 的 A 组表结构不一致")
                    print(f"  [失败] 发现 {len(differences)} 处差异：")
                    for line in differences[:10]:
                        print(f"         - {line}")
                else:
                    print(
                        "  [通过] 临时 schema 与 public 的 A 组表：表/列（含 column_default）/索引/约束集合完全一致"
                    )
            except Exception as exc:  # noqa: BLE001 - 失败也要走清理
                failures.append(f"空库试跑异常：{exc}")
                print(f"  [失败] 空库试跑异常：{type(exc).__name__}: {exc}")
            finally:
                try:
                    if created:
                        conn.execute(
                            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                                sql.Identifier(temp_schema)
                            )
                        )
                        left = conn.execute(
                            "SELECT count(*) FROM pg_namespace WHERE nspname = %s", (temp_schema,)
                        ).fetchone()[0]
                        print(f"  [清理] 临时 schema {temp_schema} 已删除（残留 {left}）")
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"临时 schema 清理失败：{exc}")
                    print(f"  [清理] 删除临时 schema {temp_schema} 失败：{exc}", file=sys.stderr)
            print(f"  [提示] 列比对已含 column_default；{CANONICALIZE_RULE}（故 nextval 的 regclass 文本可跨 schema 比较）")

        print("")
        if failures:
            print("结论：校验未通过")
            for line in failures:
                print(f"  - {line}")
            return 1
        print("结论：校验通过")
        return 0
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# inventory
# --------------------------------------------------------------------------- #
def cmd_inventory(_args: argparse.Namespace) -> int:
    conn = connect_db(autocommit=True)
    try:
        print("当前库 schema 一览（表数）：")
        rows = conn.execute(
            """
            SELECT n.nspname, count(c.oid)
            FROM pg_namespace n
            LEFT JOIN pg_class c ON c.relnamespace = n.oid AND c.relkind = 'r'
            WHERE n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema'
            GROUP BY n.nspname
            ORDER BY n.nspname
            """
        ).fetchall()
        for name, count in rows:
            print(f"  {name}: {count}")

        print("")
        print("本项目 schema（t_% / platform）逐表行数：")
        project = [
            name
            for name, _ in rows
            if name == "platform" or (name.startswith("t_") and name != "public")
        ]
        if not project:
            print("  （无：当前库还没有租户 schema）")
        for name in project:
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY table_name",
                (name,),
            ).fetchall()
            print(f"  {name}: {len(tables)} 张表")
            for (table,) in tables:
                count = conn.execute(
                    sql.SQL("SELECT count(*) FROM {}.{}").format(
                        sql.Identifier(name), sql.Identifier(table)
                    )
                ).fetchone()[0]
                print(f"    {table}: {count} 行")
        return 0
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tenant_schema.py",
        description="租户 schema 模板链的构建与校验（Schema 级多租户改造 · S0）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build-template", help="从测试库抽取 A 组 53 张表，生成租户模板 DDL")
    build.set_defaults(func=cmd_build_template)

    verify = subparsers.add_parser("verify", help="校验分类清单 / 模板覆盖，可选空库试跑")
    verify.add_argument("--apply", action="store_true", help="建临时 schema 应用模板并与 public 比对，跑完即清理")
    verify.set_defaults(func=cmd_verify)

    inventory = subparsers.add_parser("inventory", help="列出各 schema 表数与本项目 schema 的逐表行数")
    inventory.set_defaults(func=cmd_inventory)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())