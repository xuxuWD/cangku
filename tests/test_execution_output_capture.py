"""执行输出的**有界读取**（P2c-2 §2.6 / 契约「内容级回传」）——单元级回归。

口径（**不是**真容器验收，真容器见 `tests/test_container_executor.py`）：
  - 用**假容器 / 假客户端**验证 `ContainerExecutor` 的捕获语义，无需 Docker；
  - 重点：① 有界（超限截断 + 显式告知 + 读取有硬上限）；② `0` = 关闭回传（**不读日志**）；
    ③ 非 UTF-8 / 二进制**只留**字节数 + sha256；④ 读取发生在 `remove_container()` **之前**；
    ⑤ 读取失败不影响执行结果（fail-open 只影响回传，不影响执行）。

对应规格 §4「P2c-2 真库用例」的 ①②③ 三则在单元层的可判定版本；链路段（帧 payload / 脱敏 / 审计）
另见 `tests/test_conversation_stream_api.py` 与 `tests/test_conversation_stream_postgres.py`。
"""

from __future__ import annotations

import hashlib
import json

from app.tool_execution.executor import ContainerExecutor

IMAGE_DIGEST = "python:3.12-slim@sha256:" + "0" * 64
PARAMS = {"executable": "echo", "args": ["hi"]}
WORKSPACE = "/srv/exec-ws/t-capture/run-1"


class FakeContainer:
    """假容器：模拟 `wait` / `logs(stream=True)` / `remove` 与**读取先于销毁**的顺序约束。"""

    def __init__(self, *, chunks=(), status_code=0, logs_error: Exception | None = None) -> None:
        self.id = "fake-container-1"
        self._chunks = [bytes(chunk) for chunk in chunks]
        self._status_code = status_code
        self._logs_error = logs_error
        self.removed = False
        self.logs_calls = 0

    def wait(self, timeout=None):  # noqa: ANN001 - 与 docker SDK 同签名
        return {"StatusCode": self._status_code}

    def logs(self, **kwargs):  # noqa: ANN003
        self.logs_calls += 1
        assert kwargs.get("stream") is True, "有界读取必须走流式（避免一次性载入全部日志）"
        assert not self.removed, "读取必须在容器销毁之前完成（P2c-2 §2.6 实现注意）"
        if self._logs_error is not None:
            raise self._logs_error
        return iter(list(self._chunks))

    def remove(self, force=False):  # noqa: ANN001
        self.removed = True

    def kill(self):  # pragma: no cover - 本文件不覆盖超时分支
        return None


class _FakeContainers:
    def __init__(self, container: FakeContainer) -> None:
        self._container = container

    def run(self, **kwargs):  # noqa: ANN003
        return self._container

    def list(self, all=False, filters=None):  # noqa: ANN001
        return []


class _FakeNetworks:
    def list(self, names=None):  # noqa: ANN001
        return []

    def create(self, name, driver=None, internal=None):  # noqa: ANN001, ARG002
        return None


class _FakeClient:
    def __init__(self, container: FakeContainer) -> None:
        self.containers = _FakeContainers(container)
        self.networks = _FakeNetworks()


def make_executor(container: FakeContainer, **overrides) -> ContainerExecutor:
    kwargs = {
        "image_digest": IMAGE_DIGEST,
        "pids_limit": 256,
        "memory_mb": 256,
        "cpu_quota": 1.0,
        "timeout_seconds": 30,
    }
    kwargs.update(overrides)
    return ContainerExecutor(client_factory=lambda: _FakeClient(container), **kwargs)


def run(container: FakeContainer, **overrides):
    return make_executor(container, **overrides).execute(
        tool_key="cmd.run", params=PARAMS, workspace_path=WORKSPACE
    )


# ------------------------------------------------------------ ① 有界（截断 + 告知）


def test_excerpt_is_bounded_and_truncation_is_declared() -> None:
    container = FakeContainer(chunks=[b"x" * 3000, b"y" * 1000])
    outcome = run(container, output_excerpt_max_bytes=1024)

    assert outcome.ok is True
    assert container.removed is True  # 容器仍被销毁（读取不改变执行语义）
    assert outcome.output is not None
    assert outcome.output.truncated is True  # 超限**显式告知**
    assert outcome.output.bytes_read == 4000  # 读取到的字节数（有界读取）
    assert outcome.output.excerpt == "x" * 1024  # 摘录按**上限**裁剪
    assert outcome.output.sha256 is None  # 文本不回传摘要（既有 sha256 仍指摘要摘要）


def test_not_truncated_when_output_within_limit() -> None:
    container = FakeContainer(chunks=[b"hello\n", b"world\n"])
    outcome = run(container, output_excerpt_max_bytes=1024)

    assert outcome.output is not None
    assert outcome.output.truncated is False
    assert outcome.output.bytes_read == 12
    assert outcome.output.excerpt == "hello\nworld\n"


def test_read_is_hard_bounded_by_hard_limit() -> None:
    """读取有**硬上限**：超长输出不会把内存 / 时间拖垮（只读到上限即停）。"""
    container = FakeContainer(chunks=[b"z" * 500 for _ in range(20)])  # 10000 字节
    outcome = run(container, output_excerpt_max_bytes=1024, output_capture_hard_limit_bytes=2048)

    assert outcome.output is not None
    assert outcome.output.bytes_read == 2048  # 到硬上限即停（不继续 drain）
    assert outcome.output.truncated is True
    assert outcome.output.excerpt == "z" * 1024


# ------------------------------------------------------------ ② 配置 0 = 关闭回传


def test_zero_limit_disables_capture_without_reading_logs() -> None:
    container = FakeContainer(chunks=[b"should-not-be-read"])
    outcome = run(container, output_excerpt_max_bytes=0)

    assert outcome.ok is True
    assert outcome.output is None  # 关闭回传 ⇒ 不出现任何回传字段
    assert container.logs_calls == 0  # 连日志都不读（省开销）


def test_default_construction_keeps_capture_off() -> None:
    """未显式装配（默认值）⇒ 关闭：既有调用方与既有行为**零变化**。"""
    container = FakeContainer(chunks=[b"payload"])
    outcome = run(container)

    assert outcome.output is None
    assert container.logs_calls == 0


# ------------------------------------------------------------ ③ 非 UTF-8 / 二进制


def test_non_utf8_output_keeps_only_bytes_and_sha256() -> None:
    raw = b"\xff\xfe\x00abc"
    container = FakeContainer(chunks=[raw])
    outcome = run(container, output_excerpt_max_bytes=1024)

    assert outcome.output is not None
    assert outcome.output.excerpt is None  # **不落内容**
    assert outcome.output.bytes_read == len(raw)
    assert outcome.output.sha256 == "sha256:" + hashlib.sha256(raw).hexdigest()


def test_truncated_excerpt_never_splits_multibyte_character() -> None:
    raw = "中" * 10  # 30 字节
    container = FakeContainer(chunks=[raw.encode("utf-8")])
    outcome = run(container, output_excerpt_max_bytes=10)

    assert outcome.output is not None
    assert outcome.output.truncated is True
    assert outcome.output.excerpt == "中中中"  # 9 字节 ≤ 10，且不切裂字符
    assert len(outcome.output.excerpt.encode("utf-8")) <= 10


# ------------------------------------------------------------ ④ 读取失败不影响执行


def test_capture_failure_does_not_change_execution_result() -> None:
    container = FakeContainer(chunks=[b"x"], logs_error=RuntimeError("日志不可用"))
    outcome = run(container, output_excerpt_max_bytes=1024)

    assert outcome.ok is True  # 执行结果不变
    assert outcome.summary["status"] == "ok"
    assert outcome.output is None  # 回传降级为「无」（流是视图）
    assert container.removed is True


# ------------------------------------------------------------ ⑤ P2c-3 文件变更记录


FS_PARAMS = {"path": "/workspace/a.txt", "content": "x"}
MARKER = "__WORKBENCH_FS_RESULT__"


def change_line(*changes: dict) -> bytes:
    return (MARKER + " " + json.dumps({"changes": list(changes)}, ensure_ascii=False) + "\n").encode("utf-8")


def run_fs(container: FakeContainer, *, tool_key: str = "fs.write", **overrides):
    return make_executor(container, **overrides).execute(
        tool_key=tool_key, params=FS_PARAMS, workspace_path=WORKSPACE
    )


def test_file_changes_are_parsed_and_marker_is_stripped_from_excerpt() -> None:
    container = FakeContainer(
        chunks=[
            "已写入 /workspace/a.txt（5 字节）\n".encode("utf-8"),
            change_line(
                {
                    "virtual_path": "/workspace/a.txt",
                    "change_kind": "created",
                    "bytes": 5,
                    "sha256": "sha256:abc",
                    "diff_excerpt": "hello",
                }
            ),
        ]
    )
    outcome = run_fs(container, output_excerpt_max_bytes=1024, file_changes_max=50)

    assert outcome.ok is True
    assert len(outcome.file_changes) == 1
    change = outcome.file_changes[0]
    assert change.virtual_path == "/workspace/a.txt"
    assert change.change_kind == "created" and change.diff_excerpt == "hello"
    assert outcome.file_changes_truncated is False
    assert outcome.output is not None
    assert MARKER not in outcome.output.excerpt  # 标记行面向本进程，不进摘录
    assert "已写入 /workspace/a.txt（5 字节）" in outcome.output.excerpt


def test_file_changes_are_truncated_and_declared() -> None:
    container = FakeContainer(
        chunks=[
            change_line(
                *[
                    {
                        "virtual_path": f"/workspace/{index}.txt",
                        "change_kind": "created",
                        "bytes": index,
                        "sha256": f"sha256:{index}",
                    }
                    for index in range(3)
                ]
            )
        ]
    )
    outcome = run_fs(container, output_excerpt_max_bytes=1024, file_changes_max=2)

    assert [change.bytes for change in outcome.file_changes] == [0, 1]
    assert outcome.file_changes_truncated is True  # 截断**显式告知**


def test_file_changes_channel_is_off_by_default() -> None:
    """默认（未注入配置）⇒ 关闭：既有调用方零变化（不解析、不产出）。"""
    container = FakeContainer(
        chunks=[change_line({"virtual_path": "/workspace/a.txt", "change_kind": "created", "bytes": 1, "sha256": "sha256:x"})]
    )
    outcome = run_fs(container, output_excerpt_max_bytes=1024)

    assert outcome.file_changes == () and outcome.file_changes_truncated is False


def test_cmd_run_output_marker_is_never_parsed() -> None:
    """防伪造：`cmd.run` 的 stdout 是**用户可控内容**，其中的标记行不得产出变更记录。"""
    container = FakeContainer(
        chunks=[change_line({"virtual_path": "/workspace/a.txt", "change_kind": "created", "bytes": 1, "sha256": "sha256:x"})]
    )
    outcome = make_executor(container, output_excerpt_max_bytes=1024, file_changes_max=50).execute(
        tool_key="cmd.run", params=PARAMS, workspace_path=WORKSPACE
    )

    assert outcome.file_changes == ()


def test_file_changes_reads_logs_even_when_excerpt_is_disabled() -> None:
    container = FakeContainer(
        chunks=[change_line({"virtual_path": "/workspace/a.txt", "change_kind": "created", "bytes": 1, "sha256": "sha256:x"})]
    )
    outcome = run_fs(container, output_excerpt_max_bytes=0, file_changes_max=50)

    assert container.logs_calls == 1  # 输出回传关闭，但变更通道开启 ⇒ 仍需读日志
    assert outcome.output is None  # 输出回传确实关闭
    assert len(outcome.file_changes) == 1


def test_malformed_change_marker_does_not_break_execution() -> None:
    container = FakeContainer(chunks=[(MARKER + " not-json\n").encode("utf-8")])
    outcome = run_fs(container, output_excerpt_max_bytes=1024, file_changes_max=50)

    assert outcome.ok is True  # 回传是视图：坏标记只影响回传
    assert outcome.file_changes == ()
    assert outcome.output is not None
    assert MARKER not in outcome.output.excerpt