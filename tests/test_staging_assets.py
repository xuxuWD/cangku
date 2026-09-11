"""staging 部署模板与验收证据约定的静态契约。

`WORKBENCH_APPLIED_MIGRATIONS` 是预检脚本判定「迁移状态」的唯一依据：只要模板落后于
`migrations/` 目录，`scripts/staging_preflight.py` 与 `scripts/commercial_g0_preflight.py`
就会判 `blocked`，导致 staging 验收的总闸门永远无法 `pass`。本测试用迁移文件的真实
文件名守护该登记值，防止再次漂移。

同时守护证据约定：外部依赖验收的原始证据必须留在仓库外（`.acceptance/`），
仓库只提交结论，避免把脱敏后的请求/响应误提交进版本库。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
STAGING_TEMPLATE = ROOT / ".env.staging.example"
ACCEPTANCE_PLAN = ROOT / "docs" / "external-dependency-acceptance-plan.md"
EXECUTION_PLAN = ROOT / "docs" / "external-dependency-execution-plan.md"


def read_template_entries() -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in STAGING_TEMPLATE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        entries[key.strip()] = value.strip()
    return entries


def test_applied_migrations_match_repository_migrations() -> None:
    expected = sorted(path.stem for path in MIGRATIONS.glob("*.sql"))
    registered = [
        item
        for item in read_template_entries()["WORKBENCH_APPLIED_MIGRATIONS"].split(",")
        if item
    ]

    # 判定依据：模板登记值必须与 migrations/*.sql 的完整清单逐一相等（含顺序），
    # 否则预检的「迁移状态」会判 blocked。
    assert registered == expected


def test_staging_template_registers_runtime_capability_whitelists() -> None:
    entries = read_template_entries()

    # 判定依据：外部 Runtime 已接入应用装配并启用 fail-closed，
    # 模板必须登记非空能力白名单，否则预检 pass 但应用启动期即抛 RuntimeConfigError。
    for key in ("RAGFLOW_CAPABILITIES", "AGENTSCOPE_CAPABILITIES"):
        value = entries.get(key, "")
        assert any(item.strip() for item in value.split(",")), f"模板缺少非空 {key}"


def test_staging_template_never_registers_token_values() -> None:
    entries = read_template_entries()

    # 判定依据：凭据值只经部署密钥系统注入；模板若登记 *_AUTH_TOKEN，
    # 其值必须为空或明显占位，绝不能出现真实令牌值。
    offenders = {
        key: value
        for key, value in entries.items()
        if key.endswith("_AUTH_TOKEN") and value and "REPLACE" not in value.upper()
    }
    assert offenders == {}


def test_evidence_directory_is_not_tracked() -> None:
    entries = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    # 判定依据：验收原始证据目录必须被忽略，仓库只提交结论。
    assert ".acceptance/" in entries


def test_acceptance_plan_covers_nine_gates() -> None:
    content = ACCEPTANCE_PLAN.read_text(encoding="utf-8")

    # 判定依据：计划必须逐项覆盖 9 个未勾选门禁，并如实标注哪些项存在代码缺口。
    for number in range(1, 10):
        assert f"### 项 {number} ·" in content, f"计划缺少项 {number}"
    assert "需先补的代码" in content


def test_execution_plan_covers_nine_cards_and_definition_of_done() -> None:
    content = EXECUTION_PLAN.read_text(encoding="utf-8")

    # 判定依据：执行计划必须逐项给出执行卡，且必须定义完成条件与口径确认点，
    # 否则「开始验收」缺少统一入口，容易各做各的。
    for number in range(1, 10):
        assert f"### 项 {number} ·" in content, f"执行计划缺少项 {number} 的执行卡"
    assert "## 0. 开工前必须先定的两个口径" in content
    assert "## 8. 完成定义（DoD）" in content
    assert "五步法" in content
