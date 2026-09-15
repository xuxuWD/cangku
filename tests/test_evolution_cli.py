"""P6a 评测集运维命令（`scripts/evolution_eval.py`）的口径测试：fail-closed 与参数面。

不覆盖真库写路径（那属 `tests/test_evolution_postgres.py` 与运维执行）；这里钉死的是
「关闭即拒绝」「内存后端即拒绝」两条 fail-closed 行为与子命令面。
"""

from __future__ import annotations

import pytest

from app.settings import Settings
from scripts import evolution_eval


def _patch_settings(monkeypatch, settings: Settings) -> None:
    monkeypatch.setattr("app.settings.get_settings", lambda: settings)


def test_parser_exposes_expected_subcommands() -> None:
    parser = evolution_eval.build_parser()
    with pytest.raises(SystemExit):  # 缺子命令 ⇒ argparse 退出（退出码 2）
        parser.parse_args([])
    args = parser.parse_args(["run", "--tenant-id", "t-1", "--actor-id", "a-1", "--subject", "s", "--suite", "x"])
    assert args.repeats == 1


def test_disabled_component_refuses_execution(monkeypatch, capsys) -> None:
    """反假锚点：去掉开关检查 ⇒ 本用例会因尝试连库而换错误（不再命中「未启用」文案）。"""
    _patch_settings(monkeypatch, Settings(evolution_enabled=False))

    assert evolution_eval.main(["collect", "--tenant-id", "t-1", "--actor-id", "a-1"]) == 1
    assert "未启用" in capsys.readouterr().out


def test_memory_backend_refuses_execution(monkeypatch, capsys) -> None:
    _patch_settings(
        monkeypatch, Settings(evolution_enabled=True, storage_backend="memory", env="development")
    )

    assert (
        evolution_eval.main(["import-regression", "--tenant-id", "t-1", "--actor-id", "a-1"])
        == 1
    )
    assert "PostgreSQL" in capsys.readouterr().out


def test_collect_requires_subcommand(monkeypatch) -> None:
    parser = evolution_eval.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["collect", "--tenant-id", "t-1"])  # 缺 --actor-id