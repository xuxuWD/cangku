"""P2c-3：`fs.*` 的**容器内落地**（自建内联脚本）+ 文件变更记录的解析与有界折算。

口径来源（真源）：
    - 规格 [`2026-09-17-frontend-interaction-p2c-design.md`] §2.6 / §2.7 及「实现期裁定 1–5」；
    - 契约 `docs/api-contract.md`「内容级回传」硬边界第 7 条（`fs.*` 语义 + 工作卷随容器即毁）。

三条**不可协商**的口径：
  1. **容器内执行**：`fs.*` 在加固容器内由一个**自建内联脚本**完成（`python3 -c <脚本> --op …`，
     结构化 argv、不经 shell）；**不依赖 coreutils 命令集**（执行镜像 `python:3.12-slim` 中
     `file` 等命令并不保证存在，`_command_for` 段二-3 的 `ls/cat/*` 只用于 `cmd.run` 白名单）。
  2. **内容传递**：`fs.write` / `fs.overwrite` 的 `content`（body 类参数）以 **base64 经 argv** 传入
     （不经 env、不经卷）；超出 `CONTENT_ARG_MAX_BYTES`（64 KiB）一律 **fail-closed 拒绝**——
     不截断内容、不静默降级（唯一入口的消息上限 8000 字符 ⇒ 正常运行远低于该阈值）。
  3. **空工作卷语义**（事实 11：工作卷是容器内 tmpfs，随容器销毁、**文件不跨执行留存**）：
     `fs.write` = 新建（目标已存在 ⇒ 拒绝）；`fs.overwrite` = 覆盖语义写入（存在 ⇒ `overwritten`，
     不存在 ⇒ `created`）；`fs.delete` = 幂等删除（存在 ⇒ `deleted`，不存在 ⇒ 成功且**不产出变更记录**）。

变更记录（契约冻结字段）：`{virtual_path, change_kind, bytes, sha256, diff_excerpt?}`——
**只用虚拟路径**（宿主真实路径不得出现）、`diff_excerpt` 为**有界**文本摘录（非文本不产出该键）。
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .errors import ToolExecutionConfigError
from .log import get_logger
from .paths import VIRTUAL_ROOT

# 容器内解释器：执行镜像（`python:3.12-slim`，digest 钉死）保证存在。
FS_INTERPRETER = "python3"

# 变更标记行前缀（脚本 stdout 的**最后一行**）；解析后该行**不进摘录**。
MARKER = "__WORKBENCH_FS_RESULT__"

CHANGE_CREATED = "created"
CHANGE_OVERWRITTEN = "overwritten"
CHANGE_DELETED = "deleted"
CHANGE_KINDS = frozenset({CHANGE_CREATED, CHANGE_OVERWRITTEN, CHANGE_DELETED})

# `content` 的**argv 安全上限**（base64 后约 85 KiB，远低于 Linux `MAX_ARG_STRLEN` 128 KiB）。
CONTENT_ARG_MAX_BYTES = 64 * 1024

# 脚本侧单次读取硬上限（1 MiB）：回传始终有界；超过即**不读内容**（只如实告知字节数）。
READ_HARD_CAP_BYTES = 1 << 20

_FS_OPS: Mapping[str, str] = {
    "fs.read": "read",
    "fs.list": "list",
    "fs.stat": "stat",
    "fs.write": "write",
    "fs.overwrite": "overwrite",
    "fs.delete": "delete",
}

FS_TOOLS = frozenset(_FS_OPS)


@dataclass(frozen=True)
class FileChange:
    """一次文件变更的**有界**登记（无内容原文；`diff_excerpt` 为有界文本摘录）。"""

    virtual_path: str
    change_kind: str
    bytes: int
    sha256: str
    diff_excerpt: str | None = None

    def to_payload(self) -> dict[str, object]:
        """折算为契约字段（**白名单键**；无摘录时不出现该键）。"""
        payload: dict[str, object] = {
            "virtual_path": self.virtual_path,
            "change_kind": self.change_kind,
            "bytes": int(self.bytes),
            "sha256": self.sha256,
        }
        if self.diff_excerpt:
            payload["diff_excerpt"] = self.diff_excerpt
        return payload


# ---------------------------------------------------------------------------- 命令装配


def build_fs_command(
    tool_key: str,
    params: Mapping[str, Any],
    *,
    workspace_mount: str,
    virtual_root: str = VIRTUAL_ROOT,
    interpreter: str = FS_INTERPRETER,
    diff_excerpt_max_bytes: int = 0,
) -> list[str]:
    """把一次 `fs.*` 调用映射为容器内的**结构化命令**（不经 shell 解释）。"""
    op = _FS_OPS.get(tool_key)
    if op is None:
        raise ToolExecutionConfigError(f"工具 {tool_key} 不是可执行的 fs.* 工具，拒绝执行")
    path = params.get("path")
    if not isinstance(path, str) or not path:
        raise ToolExecutionConfigError(f"{tool_key} 缺少 path，拒绝执行")
    command = [
        interpreter,
        "-c",
        FS_SCRIPT,
        "--op",
        op,
        "--root",
        str(workspace_mount),
        "--virtual-root",
        str(virtual_root or VIRTUAL_ROOT),
        "--path",
        path,
        "--diff-max",
        str(max(0, int(diff_excerpt_max_bytes))),
    ]
    if op == "read":
        max_bytes = params.get("max_bytes")
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
            raise ToolExecutionConfigError("fs.read 缺少合法的 max_bytes，拒绝执行")
        command += ["--max-bytes", str(int(max_bytes))]
    if op in {"write", "overwrite"}:
        content = params.get("content")
        if not isinstance(content, str):
            raise ToolExecutionConfigError(f"{tool_key} 缺少 content（字符串），拒绝执行")
        raw = content.encode("utf-8")
        if len(raw) > CONTENT_ARG_MAX_BYTES:
            raise ToolExecutionConfigError(
                f"{tool_key} 的 content 超过单次上限 {CONTENT_ARG_MAX_BYTES} 字节，拒绝执行（不截断内容）"
            )
        command += ["--content-b64", base64.b64encode(raw).decode("ascii")]
    return command


# ---------------------------------------------------------------------------- 解析与折算


def parse_marker(text: str) -> tuple[tuple[FileChange, ...], str]:
    """从容器输出中提取变更记录，并返回**去掉标记行**的摘录文本。

    - 只认**首条**标记行（脚本恰好写一行；坏 JSON ⇒ 按无变更处理，绝不因此改变执行结果）；
    - 所有标记行都不进摘录（摘录面向用户，标记面向本进程）。
    """
    if not text:
        return (), ""
    changes: tuple[FileChange, ...] = ()
    kept: list[str] = []
    for line in text.splitlines():
        if line.startswith(MARKER):
            if not changes:
                changes = _decode_marker(line[len(MARKER) :])
            continue
        kept.append(line)
    return changes, "\n".join(kept)


def bounded_changes(
    changes: Iterable[FileChange], max_changes: int
) -> tuple[tuple[FileChange, ...], bool]:
    """按 `WORKBENCH_FILE_CHANGES_MAX` 截断；返回 `(保留项, 是否被截断)`。

    `0` = 关闭变更通道（不产出任何记录，且**如实标记为截断**）；上限内原样返回。
    """
    items = tuple(changes)
    limit = max(0, int(max_changes))
    if limit == 0:
        return (), bool(items)
    if len(items) <= limit:
        return items, False
    return items[:limit], True


def changes_payload(changes: Iterable[FileChange]) -> list[dict[str, object]]:
    return [change.to_payload() for change in changes]


def _decode_marker(raw: str) -> tuple[FileChange, ...]:
    try:
        payload = json.loads(raw.strip() or "{}")
    except json.JSONDecodeError:
        get_logger().error("文件变更标记解析失败（按无变更处理，不影响执行结果）")
        return ()
    items = payload.get("changes") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return ()
    changes: list[FileChange] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        virtual_path = item.get("virtual_path")
        change_kind = item.get("change_kind")
        size = item.get("bytes")
        sha256 = item.get("sha256")
        if not isinstance(virtual_path, str) or not virtual_path:
            continue
        if change_kind not in CHANGE_KINDS:
            continue
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            continue
        if not isinstance(sha256, str) or not sha256.startswith("sha256:"):
            continue
        excerpt = item.get("diff_excerpt")
        changes.append(
            FileChange(
                virtual_path=virtual_path,
                change_kind=change_kind,
                bytes=int(size),
                sha256=sha256,
                diff_excerpt=excerpt if isinstance(excerpt, str) and excerpt else None,
            )
        )
    return tuple(changes)


# ---------------------------------------------------------------------------- 容器内脚本


FS_SCRIPT = r'''
import argparse
import base64
import hashlib
import json
import os
import sys

MARKER = "__WORKBENCH_FS_RESULT__"
READ_HARD_CAP = 1 << 20
CHUNK = 64 * 1024


def fail(reason):
    sys.stderr.write("fs 操作被拒绝：" + reason + "\n")
    raise SystemExit(2)


def norm(path):
    # POSIX 语义（执行环境是 Linux 容器）；分隔符归一只为让脚本在开发机（Windows）上可判定。
    return os.path.realpath(path).replace("\\", "/")


def resolve(root, virtual_root, virtual_path):
    virtual_root = (virtual_root or "/workspace").rstrip("/") or "/"
    if not isinstance(virtual_path, str) or not virtual_path.startswith("/"):
        fail("路径必须是绝对路径")
    if virtual_path == virtual_root:
        relative = ""
    elif virtual_path.startswith(virtual_root + "/"):
        relative = virtual_path[len(virtual_root) + 1:]
    else:
        fail("路径不在工作卷虚拟根内")
    if any(segment == ".." for segment in relative.split("/")):
        fail("路径包含上级跳转")
    base = norm(root).rstrip("/") or "/"
    candidate = norm(os.path.join(base, relative))
    if candidate != base and not candidate.startswith(base + "/"):
        fail("路径 realpath 后落在工作卷之外")
    return candidate


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def digest_file(path):
    hasher = hashlib.sha256()
    total = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            hasher.update(chunk)
            total += len(chunk)
    return total, "sha256:" + hasher.hexdigest()


def text_excerpt(raw, limit):
    if limit <= 0:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore")


def emit(changes):
    sys.stdout.write(MARKER + " " + json.dumps({"changes": changes}, ensure_ascii=False) + "\n")


def op_read(path, virtual_path, max_bytes):
    if not os.path.isfile(path):
        fail("目标文件不存在")
    size = os.path.getsize(path)
    if size > READ_HARD_CAP:
        sys.stdout.write("内容超过读取硬上限（bytes=%d > %d），未回传内容。\n" % (size, READ_HARD_CAP))
        return
    with open(path, "rb") as handle:
        raw = handle.read()
    if size > max_bytes:
        sys.stdout.write(
            "内容超过单次回传上限（bytes=%d > max_bytes=%d），未回传内容；%s\n"
            % (size, max_bytes, digest(raw))
        )
        return
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        sys.stdout.write("非文本内容未回传：bytes=%d %s\n" % (size, digest(raw)))
        return
    sys.stdout.write(text)


def op_list(path, virtual_path):
    if not os.path.isdir(path):
        fail("目标目录不存在")
    names = sorted(os.listdir(path))
    lines = ["清单：%s（%d 项）" % (virtual_path, len(names))]
    for name in names:
        full = os.path.join(path, name)
        if os.path.isdir(full):
            lines.append("%s\tdir\t0" % name)
        elif os.path.isfile(full):
            lines.append("%s\tfile\t%d" % (name, os.path.getsize(full)))
        else:
            lines.append("%s\tother\t0" % name)
    sys.stdout.write("\n".join(lines) + "\n")


def op_stat(path, virtual_path):
    if not os.path.isfile(path):
        fail("目标文件不存在")
    info = os.stat(path)
    sys.stdout.write(
        "路径：%s type=file size=%d mode=0o%o\n" % (virtual_path, info.st_size, info.st_mode & 0o777)
    )


def op_write(mode, path, virtual_path, raw, diff_max):
    exists = os.path.exists(path)
    if exists:
        if not os.path.isfile(path):
            fail("目标是目录，拒绝写入")
        if mode == "create":
            fail("目标已存在，fs.write 不覆盖（如需覆盖请用 fs.overwrite）")
        change_kind = "overwritten"
    else:
        change_kind = "created"
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(raw)
    record = {
        "virtual_path": virtual_path,
        "change_kind": change_kind,
        "bytes": len(raw),
        "sha256": digest(raw),
    }
    excerpt = text_excerpt(raw, diff_max)
    if excerpt is not None:
        record["diff_excerpt"] = excerpt
    sys.stdout.write("%s %s（%d 字节）\n" % ("已覆盖" if change_kind == "overwritten" else "已写入", virtual_path, len(raw)))
    emit([record])


def op_delete(path, virtual_path):
    if not os.path.exists(path):
        sys.stdout.write("目标不存在（无变更）：%s\n" % virtual_path)
        return
    if not os.path.isfile(path):
        fail("仅支持删除文件")
    total, sha = digest_file(path)
    os.remove(path)
    sys.stdout.write("已删除 %s\n" % virtual_path)
    emit([{"virtual_path": virtual_path, "change_kind": "deleted", "bytes": total, "sha256": sha}])


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--op", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--virtual-root", default="/workspace")
    parser.add_argument("--path", required=True)
    parser.add_argument("--content-b64", default=None)
    parser.add_argument("--max-bytes", type=int, default=0)
    parser.add_argument("--diff-max", type=int, default=0)
    args = parser.parse_args()

    path = resolve(args.root, args.virtual_root, args.path)
    if args.op == "read":
        op_read(path, args.path, max(0, args.max_bytes))
    elif args.op == "list":
        op_list(path, args.path)
    elif args.op == "stat":
        op_stat(path, args.path)
    elif args.op in ("write", "overwrite"):
        if args.content_b64 is None:
            fail("缺少内容")
        try:
            raw = base64.b64decode(args.content_b64, validate=True)
        except Exception:
            fail("内容编码非法")
        op_write("create" if args.op == "write" else "overwrite", path, args.path, raw, max(0, args.diff_max))
    elif args.op == "delete":
        op_delete(path, args.path)
    else:
        fail("不支持的操作")


main()
'''