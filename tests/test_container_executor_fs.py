"""P2c-3 `fs.*` 的**真容器**回归（在加固容器内落地；工作卷 tmpfs 即毁）。

与 `tests/test_fs_tools.py`（宿主侧脚本语义）分工：
  - 本文件验证**装配到真容器**后的端到端行为：命令能跑、变更记录出得来、标记行不进摘录、
    容器内自身的路径闸门（③ 的纵深防御）仍拒越界路径、**文件不跨执行留存**（事实 11）；
  - 加固口径本身（只读根 / 非 root / 无外网 / tmpfs 选项）由 `tests/test_container_executor.py`
    **原样重跑**覆盖（规格 §4「P2c-3 真库用例」⑤ 容器回归不变）。

真容器验证：需要本机 Docker 与钉死镜像；两者缺一时整组跳过（skipped 计入基线，属预期）。
"""

from __future__ import annotations

import hashlib
import uuid

import pytest

from app.tool_execution.executor import ContainerExecutor
from app.tool_execution.file_ops import MARKER

# 与 `tests/test_container_executor.py` / `Dockerfile` 同源的钉死镜像（tag 可变、digest 不可变）。
IMAGE_DIGEST = (
    "python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea"
)
PIDS_LIMIT = 256
MEMORY_MB = 256
CPU_QUOTA = 1.0
TIMEOUT_SECONDS = 60


def _docker_client():
    docker = pytest.importorskip("docker")
    try:
        client = docker.from_env()
        client.ping()
    except Exception:  # noqa: BLE001 - 无守护进程 → 整组跳过
        pytest.skip("Docker 守护进程不可用，跳过真容器验收")
    try:
        client.images.get(IMAGE_DIGEST)
    except Exception:  # noqa: BLE001 - 钉死镜像缺失 → 整组跳过（不联网拉取）
        pytest.skip("钉死镜像不在本机，跳过真实容器验收")
    return client


@pytest.fixture(scope="module")
def client():
    return _docker_client()


@pytest.fixture()
def executor(client):
    """真容器执行器：**变更通道与回传都开启**（与生产默认口径一致）。"""
    return ContainerExecutor(
        image_digest=IMAGE_DIGEST,
        pids_limit=PIDS_LIMIT,
        memory_mb=MEMORY_MB,
        cpu_quota=CPU_QUOTA,
        timeout_seconds=TIMEOUT_SECONDS,
        client_factory=lambda: client,
        output_excerpt_max_bytes=16384,
        file_diff_excerpt_max_bytes=8192,
        file_changes_max=50,
    )


def workspace() -> str:
    return f"/srv/exec-ws/t-fs/{uuid.uuid4().hex[:8]}"


def test_fs_write_reports_change_and_strips_marker(executor) -> None:
    content = "你好，工作台\n"
    outcome = executor.execute(
        tool_key="fs.write",
        params={"path": "/workspace/a.txt", "content": content},
        workspace_path=workspace(),
    )

    assert outcome.ok is True, outcome.summary
    assert len(outcome.file_changes) == 1
    change = outcome.file_changes[0]
    raw = content.encode("utf-8")
    assert change.virtual_path == "/workspace/a.txt"
    assert change.change_kind == "created"
    assert change.bytes == len(raw)
    assert change.sha256 == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert change.diff_excerpt == content
    assert outcome.output is not None
    assert MARKER not in (outcome.output.excerpt or "")  # 标记行面向本进程，不进摘录
    assert "已写入 /workspace/a.txt" in (outcome.output.excerpt or "")


def test_files_do_not_survive_across_executions(executor) -> None:
    """事实 11（**如实登记**）：工作卷是容器内 tmpfs、随容器销毁 ⇒ 文件**不跨执行留存**。"""
    written = executor.execute(
        tool_key="fs.write",
        params={"path": "/workspace/persist.txt", "content": "x"},
        workspace_path=workspace(),
    )
    assert written.ok is True

    read_back = executor.execute(
        tool_key="fs.read",
        params={"path": "/workspace/persist.txt", "max_bytes": 64},
        workspace_path=workspace(),
    )
    assert read_back.ok is False  # 新容器的工作卷是空的 ⇒ 读不到
    assert read_back.file_changes == ()


def test_fs_list_on_empty_workspace_and_missing_stat(executor) -> None:
    listed = executor.execute(
        tool_key="fs.list", params={"path": "/workspace"}, workspace_path=workspace()
    )
    assert listed.ok is True
    assert "（0 项）" in (listed.output.excerpt or "")

    missing = executor.execute(
        tool_key="fs.stat", params={"path": "/workspace/none.txt"}, workspace_path=workspace()
    )
    assert missing.ok is False


def test_in_container_path_gate_denies_escape(executor) -> None:
    """③ 的**纵深防御**：即使绕过服务层闸门直连执行器，容器内脚本仍拒绝工作卷之外的路径。"""
    for path in ("/etc/passwd", "/workspace/../etc/passwd"):
        outcome = executor.execute(
            tool_key="fs.read", params={"path": path, "max_bytes": 16}, workspace_path=workspace()
        )
        assert outcome.ok is False, path


def test_fs_delete_on_empty_workspace_succeeds_without_change_record(executor) -> None:
    """空工作卷下的常态：删除不存在 ⇒ **成功且不产出变更记录**（不伪造变更）。"""
    outcome = executor.execute(
        tool_key="fs.delete", params={"path": "/workspace/none.txt"}, workspace_path=workspace()
    )
    assert outcome.ok is True
    assert outcome.file_changes == ()
    assert "无变更" in (outcome.output.excerpt or "")