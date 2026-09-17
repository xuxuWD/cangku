"""P2c-3 `fs.*` 容器内落地：命令装配 + 内联脚本语义（**宿主侧**执行，无需 Docker）。

定位与边界（如实登记）：
  - 本文件验证①`_command_for` 的 `fs.*` 映射（结构化 argv、base64 内容、超限 fail-closed、
    `artifact.export` 仍不装配）与②**内联脚本自身的语义**（写 / 覆盖 / 删除 / 读 / 列 / 元信息、
    工作卷内 realpath 约束、空工作卷下的三态变更记录）；
  - 脚本以 `sys.executable` 在**宿主临时目录**执行（容器内保证 `python3`，见规格 §2.7 实现期裁定 1）；
    脚本按 POSIX 语义判定，但分隔符归一（`\\` → `/`）⇒ 宿主 Windows 上同样可判定；
  - **真容器**装配（加固口径不变 + 端到端变更记录）见 `tests/test_container_executor_fs.py`；
    帧 / 产物链路见 `tests/test_conversation_stream_api.py` 的 P2c-3 段与 `tests/test_run_artifacts_postgres.py`。
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.tool_execution.errors import ToolExecutionConfigError
from app.tool_execution.executor import _command_for
from app.tool_execution.file_ops import (
    CHANGE_CREATED,
    CHANGE_DELETED,
    CHANGE_OVERWRITTEN,
    CONTENT_ARG_MAX_BYTES,
    MARKER,
    FileChange,
    bounded_changes,
    build_fs_command,
    parse_marker,
)

WORKSPACE = "/workspace"


# ------------------------------------------------------------ ① 命令装配


def test_fs_write_command_is_structured_and_base64_encoded() -> None:
    command = _command_for("fs.write", {"path": "/workspace/a.txt", "content": "机密正文"})

    # 结构化 argv（不经 shell）：首个参数是解释器，第二个是 `-c`，脚本自带 `--op` 等选项。
    assert command[0] == "python3" and command[1] == "-c"
    assert "--op" in command and command[command.index("--op") + 1] == "write"
    assert command[command.index("--path") + 1] == "/workspace/a.txt"
    # 内容以 base64 传入（argv 安全，不经 env / 不经卷）；**原文不出现在 argv**。
    encoded = command[command.index("--content-b64") + 1]
    assert base64.b64decode(encoded).decode("utf-8") == "机密正文"
    assert "机密正文" not in " ".join(command)


def test_fs_overwrite_and_delete_commands_are_distinct() -> None:
    overwrite = _command_for("fs.overwrite", {"path": "/workspace/a.txt", "content": "x"})
    delete = _command_for("fs.delete", {"path": "/workspace/a.txt"})

    assert overwrite[overwrite.index("--op") + 1] == "overwrite"
    assert "--content-b64" in overwrite
    assert delete[delete.index("--op") + 1] == "delete"
    assert "--content-b64" not in delete


def test_fs_read_carries_max_bytes() -> None:
    command = _command_for("fs.read", {"path": "/workspace/a.txt", "max_bytes": 64})
    assert command[command.index("--op") + 1] == "read"
    assert command[command.index("--max-bytes") + 1] == "64"


def test_fs_write_rejects_missing_or_oversized_content() -> None:
    with pytest.raises(ToolExecutionConfigError):
        _command_for("fs.write", {"path": "/workspace/a.txt"})
    with pytest.raises(ToolExecutionConfigError):
        _command_for("fs.overwrite", {"path": "/workspace/a.txt", "content": 123})
    too_big = "x" * (CONTENT_ARG_MAX_BYTES + 1)
    with pytest.raises(ToolExecutionConfigError):
        _command_for("fs.write", {"path": "/workspace/a.txt", "content": too_big})


def test_artifact_export_and_unknown_tools_stay_fail_closed() -> None:
    with pytest.raises(ToolExecutionConfigError):
        _command_for("artifact.export", {"path": "/workspace/a.txt", "target": "team-a"})
    with pytest.raises(ToolExecutionConfigError):
        _command_for("fs.chmod", {"path": "/workspace/a.txt"})


def test_cmd_run_mapping_is_unchanged() -> None:
    assert _command_for("cmd.run", {"executable": "ls", "args": ["-la"]}) == ["ls", "-la"]


# ------------------------------------------------------------ ② 脚本语义（宿主侧执行）


def run_op(tool_key: str, params: dict, workspace: Path, *, diff_excerpt_max_bytes: int = 8192):
    command = build_fs_command(
        tool_key,
        params,
        workspace_mount=str(workspace),
        diff_excerpt_max_bytes=diff_excerpt_max_bytes,
    )
    completed = subprocess.run(
        [sys.executable, *command[1:]], capture_output=True, text=True, check=False
    )
    changes, excerpt = parse_marker(completed.stdout)
    return completed, changes, excerpt


def test_script_writes_new_file_and_reports_change(tmp_path: Path) -> None:
    completed, changes, excerpt = run_op(
        "fs.write", {"path": "/workspace/a.txt", "content": "你好"}, tmp_path
    )

    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "你好"
    assert len(changes) == 1
    change = changes[0]
    assert change.virtual_path == "/workspace/a.txt"  # **虚拟路径**（宿主真实路径不得出现）
    assert change.change_kind == CHANGE_CREATED
    assert change.bytes == len("你好".encode("utf-8"))
    assert change.sha256 == "sha256:" + hashlib.sha256("你好".encode("utf-8")).hexdigest()
    assert change.diff_excerpt == "你好"
    assert str(tmp_path) not in excerpt  # 摘要行只含虚拟路径
    assert MARKER not in excerpt  # 标记行不进摘录


def test_script_write_refuses_existing_target(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("旧", encoding="utf-8")
    completed, changes, _ = run_op("fs.write", {"path": "/workspace/a.txt", "content": "新"}, tmp_path)

    assert completed.returncode != 0  # fail-closed：fs.write 不覆盖
    assert changes == ()
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "旧"


def test_script_overwrite_replaces_and_reports_overwritten(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("旧", encoding="utf-8")
    completed, changes, _ = run_op(
        "fs.overwrite", {"path": "/workspace/a.txt", "content": "新"}, tmp_path
    )

    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "新"
    assert [change.change_kind for change in changes] == [CHANGE_OVERWRITTEN]


def test_script_overwrite_creates_when_absent(tmp_path: Path) -> None:
    completed, changes, _ = run_op(
        "fs.overwrite", {"path": "/workspace/sub/a.txt", "content": "新"}, tmp_path
    )

    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "sub" / "a.txt").read_text(encoding="utf-8") == "新"  # 父目录自动创建
    assert [change.change_kind for change in changes] == [CHANGE_CREATED]


def test_script_delete_removes_and_reports_deleted(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    completed, changes, _ = run_op("fs.delete", {"path": "/workspace/a.txt"}, tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert not (tmp_path / "a.txt").exists()
    assert [change.change_kind for change in changes] == [CHANGE_DELETED]


def test_script_delete_missing_is_idempotent_without_change_record(tmp_path: Path) -> None:
    """空工作卷下的常态：删除不存在 ⇒ 成功但**不产出变更记录**（不伪造变更）。"""
    completed, changes, excerpt = run_op("fs.delete", {"path": "/workspace/none.txt"}, tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert changes == ()
    assert "无变更" in excerpt


def test_script_read_returns_text_and_binary_summary(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("正文", encoding="utf-8")
    (tmp_path / "b.bin").write_bytes(b"\xff\xfe\x00")

    completed, changes, excerpt = run_op("fs.read", {"path": "/workspace/a.txt", "max_bytes": 1024}, tmp_path)
    assert completed.returncode == 0 and excerpt == "正文" and changes == ()

    binary, _, binary_excerpt = run_op(
        "fs.read", {"path": "/workspace/b.bin", "max_bytes": 1024}, tmp_path
    )
    assert binary.returncode == 0
    # 二进制**不落内容**：只给字节数与摘要（回传通道只有一行说明）。
    assert binary_excerpt.startswith("非文本内容未回传")
    assert "bytes=3" in binary_excerpt and "sha256:" in binary_excerpt
    assert "\xff" not in binary_excerpt and "\xfe" not in binary_excerpt


def test_script_read_missing_file_fails(tmp_path: Path) -> None:
    completed, changes, _ = run_op("fs.read", {"path": "/workspace/none.txt", "max_bytes": 10}, tmp_path)
    assert completed.returncode != 0
    assert changes == ()


def test_script_list_and_stat(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("abc", encoding="utf-8")
    listed, _, excerpt = run_op("fs.list", {"path": "/workspace"}, tmp_path)
    assert listed.returncode == 0 and "a.txt" in excerpt

    stat, _, stat_excerpt = run_op("fs.stat", {"path": "/workspace/a.txt"}, tmp_path)
    assert stat.returncode == 0 and "size=3" in stat_excerpt


def test_script_denies_path_outside_workspace(tmp_path: Path) -> None:
    for path in ("/etc/passwd", "/workspace/../etc/passwd", "relative/a.txt"):
        completed, changes, _ = run_op("fs.read", {"path": path, "max_bytes": 10}, tmp_path)
        assert completed.returncode != 0, path
        assert changes == ()


def test_script_denies_symlink_escape(tmp_path: Path) -> None:
    """**符号链接逃逸**：前缀与 `..` 检查都过得去，只有 **realpath 落点判定** 能拦住它。

    平台差异（如实登记）：Windows 上创建符号链接需要开发者模式 / 管理员权限，创建失败即跳过
    （CI 与本机 Linux 容器路径由 `tests/test_container_executor_fs.py` 的真容器用例覆盖）。
    """
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("外泄内容", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("当前平台不允许创建符号链接，跳过（真容器用例另行覆盖）")

    completed, changes, _ = run_op("fs.read", {"path": "/workspace/link/secret.txt", "max_bytes": 64}, tmp_path)

    assert completed.returncode != 0  # realpath 解析到工作卷之外 ⇒ 拒绝
    assert changes == ()
    assert "外泄内容" not in completed.stdout


def test_script_diff_excerpt_is_bounded(tmp_path: Path) -> None:
    command = build_fs_command(
        "fs.write",
        {"path": "/workspace/big.txt", "content": "中" * 100},
        workspace_mount=str(tmp_path),
        diff_excerpt_max_bytes=10,
    )
    completed = subprocess.run(
        [sys.executable, *command[1:]], capture_output=True, text=True, check=False
    )
    changes, _ = parse_marker(completed.stdout)
    assert completed.returncode == 0
    assert len(changes[0].diff_excerpt.encode("utf-8")) <= 10


# ------------------------------------------------------------ ③ 解析与上限（纯函数）


def test_parse_marker_extracts_last_line_and_strips_it() -> None:
    payload = {"changes": [{"virtual_path": "/workspace/a", "change_kind": "created", "bytes": 1, "sha256": "sha256:x"}]}
    text = f"已写入 /workspace/a\n{MARKER} {json.dumps(payload)}\n"

    changes, excerpt = parse_marker(text)
    assert len(changes) == 1 and changes[0].virtual_path == "/workspace/a"
    assert excerpt.strip() == "已写入 /workspace/a"
    assert MARKER not in excerpt


def test_parse_marker_rejects_malformed_payload_without_raising() -> None:
    changes, excerpt = parse_marker(f"{MARKER} not-json\nresult")
    assert changes == ()
    assert excerpt == "result"  # 坏标记只丢自己，不污染摘录、不影响执行


def test_bounded_changes_truncates_and_declares() -> None:
    changes = tuple(
        FileChange(
            virtual_path=f"/workspace/{index}.txt",
            change_kind=CHANGE_CREATED,
            bytes=index,
            sha256=f"sha256:{index}",
        )
        for index in range(5)
    )
    kept, truncated = bounded_changes(changes, 2)
    assert [change.bytes for change in kept] == [0, 1] and truncated is True

    kept_all, truncated_all = bounded_changes(changes, 5)
    assert len(kept_all) == 5 and truncated_all is False

    kept_off, truncated_off = bounded_changes(changes, 0)
    assert kept_off == () and truncated_off is True