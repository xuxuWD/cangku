"""技能绑定修复脚本（`scripts/repair_dangling_skill_bindings.py`）的**纯函数**口径测试。

为什么只测纯函数：脚本的写路径要连真库（`--apply`），而**风险最高的不是 SQL，而是"判哪些行该修"**——
判错就会把合规的绑定误置为已解除。故把判定抽成纯函数，逐类钉死；DB 层保持"薄 + 只改状态"。

安全约定也在本文件里被钉住：**默认干跑**（`--apply` 才写）、**必须指定租户**、**DSN 只从环境变量取**。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "repair_dangling_skill_bindings.py"

DSN_ENV_FOR_TEST = "WORKBENCH_DSN_NOT_SET_FOR_TEST"


def _run(args: list[str], child_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """以**固定 UTF-8** 跑脚本（Windows 默认管道编码是 cp936，脚本输出是 UTF-8）。"""
    env = dict(os.environ) if child_env is None else child_env
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import repair_dangling_skill_bindings as repair  # noqa: E402


def _row(agent: str, skill: str, status: str = "active") -> repair.BindingRow:
    return repair.BindingRow(agent_key=agent, skill_key=skill, status=status)


def test_violation_reason_classifies_three_cases() -> None:
    """三类判定：技能不存在 / 有版本但无 enabled / 合规。"""
    statuses = {"ok-skill": {"enabled"}, "draft-skill": {"submitted"}, "mixed": {"submitted", "enabled"}}

    assert repair.violation_reason(_row("a", "ghost-skill"), statuses) == repair.REASON_SKILL_MISSING
    assert repair.violation_reason(_row("a", "draft-skill"), statuses) == repair.REASON_SKILL_NOT_ENABLED
    assert repair.violation_reason(_row("a", "ok-skill"), statuses) is None
    # 多版本：只要有一个 enabled 版本即合规
    assert repair.violation_reason(_row("a", "mixed"), statuses) is None


def test_find_violations_splits_pending_and_report_only() -> None:
    """只有**生效中**的违规行才待修；已解除的违规行只报告（不生效，不动它）。"""
    statuses = {"ok-skill": {"enabled"}, "draft-skill": {"submitted"}}
    rows = [
        _row("a", "ok-skill"),                      # 合规
        _row("b", "draft-skill"),                   # 待修（生效中 + 未启用）
        _row("c", "ghost-skill"),                   # 待修（生效中 + 技能不存在）
        _row("d", "ghost-skill", status="disabled"),  # 仅报告（已解除）
    ]

    pending, report_only = repair.find_violations(rows, statuses)

    assert [(r.agent_key, r.skill_key) for r in pending] == [("b", "draft-skill"), ("c", "ghost-skill")]
    assert [(r.agent_key, r.skill_key) for r in report_only] == [("d", "ghost-skill")]


def test_find_violations_is_idempotent_for_disabled_rows() -> None:
    """幂等：把待修行置为 disabled 后再跑，待修列表为空（不会反复报同一批）。"""
    statuses = {"draft-skill": {"submitted"}}
    rows = [_row("b", "draft-skill")]

    pending, _ = repair.find_violations(rows, statuses)
    assert len(pending) == 1

    rows_after = [_row("b", "draft-skill", status="disabled")]
    pending_after, report_after = repair.find_violations(rows_after, statuses)
    assert pending_after == []
    assert len(report_after) == 1


def test_script_requires_tenant_argument() -> None:
    """**必须指定租户**（不做全库一把改）：缺 `--tenant` ⇒ argparse 报错（退出码 2）。"""
    result = _run([])

    assert result.returncode == 2
    assert "--tenant" in result.stderr


def test_script_refuses_without_dsn_and_never_contains_credentials() -> None:
    """DSN 只从环境变量取（脚本内**不得**出现连接串 / 凭据字面量）。"""
    child_env = {k: v for k, v in os.environ.items() if k != DSN_ENV_FOR_TEST}
    result = _run(["--tenant", "t-none", "--dsn-env", DSN_ENV_FOR_TEST], child_env=child_env)

    assert result.returncode == 2
    assert "未设置" in result.stderr

    text = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("postgresql://", "postgresql+psycopg://", "password=", "REPLACE_ME"):
        assert forbidden not in text, f"脚本内不得出现连接串 / 凭据形态的字面量：{forbidden}"


def test_script_defaults_to_dry_run_and_never_deletes() -> None:
    """默认干跑（`--apply` 才写）；且脚本**不含任何 DELETE**（只改状态、不删数据）。"""
    text = SCRIPT.read_text(encoding="utf-8")

    assert '"--apply"' in text and "action=" in text and "store_true" in text
    assert "DELETE" not in text.upper()
    assert "SET status = 'disabled'" in text


@pytest.mark.parametrize("marker", ["--apply", "--tenant", "--dsn-env"])
def test_script_help_lists_safety_flags(marker: str) -> None:
    """三个安全相关参数必须在 `--help` 里可见（操作者据此知道如何安全使用）。"""
    result = _run(["--help"])

    assert result.returncode == 0
    assert marker in result.stdout