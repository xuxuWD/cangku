"""④ 危险命令闸门（规格 §3.2 ④ / §3.2.1）。

三个子判定**顺序固定**，任一命中即拒（不允许"审批后放行"豁免）：

* **④-0 可执行文件来源**：解析自「受信任且不可写的固定根」（`settings.exec_trusted_roots`，
  默认 `/usr/bin`；**不使用 PATH 解析**）；realpath 落在该根内、属主 root、
  **非 group/world-writable**；**拒 shebang 脚本与非 ELF**；工作卷不得在该根内。
* **④-1 可执行名白名单**（§3.2.1 Q2 最小只读集，**fail-closed**，无失败语义豁免）。
* **④-2 危险命令黑名单**：A 可执行名 / B 参数级 / C 路径（C 见 `paths.path_blacklist_hit`）。

判定口径 R1–R4（§3.2.1）逐条落实在本模块。
"""

from __future__ import annotations

import os
import re
from typing import Iterable, Sequence

from .paths import path_blacklist_hit

_EXTENSIONS = (".exe", ".cmd", ".bat", ".ps1")
_ELF_MAGIC = b"\x7fELF"
_SHEBANG_MAGIC = b"#!"


class CommandDenied(ValueError):
    """④ 任一子判定命中（→ 403 `blacklisted`；重跑路径置 `027` 行 `rejected`）。"""

    def __init__(self, message: str, *, sub_step: str) -> None:
        super().__init__(message)
        self.sub_step = sub_step


# ---- ④-1 可执行名白名单（§3.2.1 Q2 最小只读集） ----
READ_ONLY_WHITELIST = frozenset({"ls", "cat", "head", "tail", "wc", "stat", "file"})

# ---- ④-2 A 可执行名黑名单（§3.2.1 A1–A12） ----
_A_EXACT = frozenset(
    # A1 文件系统破坏
    "rm rmdir shred dd truncate mke2fs wipefs fdisk parted sgdisk mkswap swapon swapoff chattr setfattr "
    # A2 提权与身份
    "sudo su doas pkexec runuser setcap usermod useradd groupadd passwd chsh visudo newgrp chown chgrp "
    # A3 进程/服务控制
    "kill killall pkill systemctl service crontab at batch nohup screen tmux shutdown reboot halt poweroff init telinit "
    # A4 网络与外联
    "curl wget nc ncat netcat socat telnet ssh scp sftp ftp tftp ping traceroute dig nslookup host ntpdate "
    "iptables nft ip ifconfig route tcpdump "
    # A5 逃逸原语
    "docker podman nerdctl ctr crictl kubectl nsenter unshare chroot mount umount losetup pivot_root "
    "modprobe insmod rmmod sysctl systemd-nspawn machinectl "
    # A6 包管理
    "apt apt-get dpkg yum dnf rpm apk pacman zypper pip pip3 npm yarn pnpm cargo gem composer conda brew "
    # A7 shell 解释
    "sh bash zsh dash ksh pwsh powershell cmd wsl "
    # A8 解释器内联代码（作为独立命令名亦被 A12 覆盖）
    "gdb lldb dlv strace ltrace ptrace valgrind "
    # A9/A10
    "yes "
    # A11 包装器
    "env busybox toybox timeout setsid nice ionice stdbuf xargs find "
    # A12 裸解释器
    "python python3 node perl ruby php lua tclsh Rscript".split()
)

# A8：解释器 + 内联代码选项（如 `python -c`、`node -e`）。
_INLINE_CODE_OPTIONS = {
    "python": {"-c"},
    "python3": {"-c"},
    "node": {"-e", "-p"},
    "perl": {"-e"},
    "ruby": {"-e"},
    "php": {"-r"},
    "lua": {"-e"},
}

# B 层：归档工具 + 危险参数。
_ARCHIVE_TOOLS = frozenset({"tar", "unzip", "7z", "cpio", "bsdtar"})
_ARCHIVE_DENY_FLAGS = frozenset({"-p", "--absolute-names"})
# B 层：`chmod` 放宽权限的数值 / 等价形态。
_CHMOD_DENY_VALUES = frozenset({"777", "0777", "666", "a+rwx", "+s"})


def strip_executable_extension(name: str) -> str:
    lowered = name.lower()
    for extension in _EXTENSIONS:
        if lowered.endswith(extension):
            return lowered[: -len(extension)]
    return lowered


def resolved_basename(executable: str) -> str:
    """R2：basename 先 realpath 归一，再剥离可执行扩展名，最后大小写归一小写。"""
    resolved = os.path.realpath(executable)
    return strip_executable_extension(os.path.basename(resolved))


def executable_blacklist_hit(executable: str, args: Sequence[str] = ()) -> bool:
    """A 层（可执行名黑名单）：按 R2 归一后判定，含 A8 内联代码形态。"""
    name = resolved_basename(executable)
    if name in _A_EXACT or name.startswith("mkfs"):
        return True
    options = _INLINE_CODE_OPTIONS.get(name)
    if options and any(token in options for token in normalize_args(args)):
        return True
    return False


def normalize_args(args: Iterable[str]) -> list[str]:
    """R1：结构化参数的规范化（去引号 / 短选项粘连 / 长选项 `=` 形态 / `--` 终止符 / 大小写归一）。"""
    normalized: list[str] = []
    for raw in args:
        if not isinstance(raw, str):
            normalized.append(str(raw))
            continue
        token = raw
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
            token = token[1:-1]
        lowered = token.lower()
        if lowered.startswith("--") and "=" in lowered:
            option, value = lowered.split("=", 1)
            normalized.extend([option, value])
        elif re.fullmatch(r"-[a-z]{2,3}", lowered):
            normalized.extend(f"-{char}" for char in lowered[1:])
        else:
            normalized.append(lowered)
    return normalized


def _has_parent_segment(token: str) -> bool:
    return ".." in token.split("/")


def param_blacklist_hit(
    executable: str,
    args: Sequence[str],
    *,
    workspace_path: str | None = None,
    virtual_root: str = "/workspace",
) -> bool:
    """B 层（参数级黑名单）。"""
    name = resolved_basename(executable)
    tokens = normalize_args(args)
    token_set = set(tokens)

    if name == "find" and token_set & {"-delete", "-exec", "-execdir"}:
        return True
    if name == "sed" and (token_set & {"-i", "--in-place"}):
        return True
    if name in _ARCHIVE_TOOLS:
        if token_set & _ARCHIVE_DENY_FLAGS:
            return True
        for index, token in enumerate(tokens[:-1]):
            if token == "-c" and tokens[index + 1].replace("\\", "/") == "/":
                return True
        if any(_has_parent_segment(token) for token in tokens):
            return True
    if name == "git":
        if "config" in tokens and "--global" in token_set:
            return True
        if "remote" in tokens and token_set & {"add", "set-url", "remove", "rename"}:
            return True
        if "alias" in tokens and any(token.startswith("!") for token in tokens):
            return True
    if name == "chmod":
        for token in tokens:
            if token in _CHMOD_DENY_VALUES or token.startswith("--reference="):
                return True
    # 任意命令 + 重定向 / tee 写入允许目录之外。
    if any(token in {">", ">>", "tee"} for token in tokens):
        return True
    # 任意参数命中 C 类路径黑名单，或 realpath 后落在允许目录外。
    for token in tokens:
        if not (token.startswith("/") or token.startswith("~") or _has_parent_segment(token)):
            continue
        normalized = token.replace("\\", "/")
        if path_blacklist_hit(normalized):
            return True
        if _has_parent_segment(normalized) and not _inside_workspace(normalized, workspace_path, virtual_root):
            return True
        if normalized.startswith("/") and not _inside_workspace(normalized, workspace_path, virtual_root):
            return True
    return False


def _inside_workspace(candidate: str, workspace_path: str | None, virtual_root: str) -> bool:
    normalized = os.path.normpath(candidate).replace("\\", "/")
    root = virtual_root.replace("\\", "/").rstrip("/")
    if normalized == root or normalized.startswith(root + "/"):
        return True
    if workspace_path is None:
        return True
    base = workspace_path.replace("\\", "/").rstrip("/")
    return normalized == base or normalized.startswith(base + "/")


class ExecutableTrust:
    """④-0：可执行文件来源校验。

    `trusted_uid` / `write_mask` 是**可注入的判定口径**，默认值即生产语义：
    * `trusted_uid`（默认 `0` = root）：期望属主 uid。POSIX 上 `st_uid` 反映真实属主；
      Windows 无 POSIX 属主语义、`os.stat().st_uid` 恒为 `0`，故该判定在本平台**退化为恒真**
      （无法判定为「假」）。
    * `write_mask`（默认 `0o022` = group/world 任一位可写即拒）：`st_mode & write_mask != 0` 即拒。
    """

    def __init__(
        self,
        *,
        trusted_roots: Iterable[str],
        workspace_root: str = "",
        trusted_uid: int = 0,
        write_mask: int = 0o022,
    ) -> None:
        roots = tuple(self._normalize_root(root) for root in trusted_roots if root)
        if not roots:
            raise ValueError("未配置受信任可执行根 WORKBENCH_EXEC_TRUSTED_ROOTS")
        self._roots = roots
        self._workspace_root = os.path.realpath(workspace_root) if workspace_root else ""
        self._trusted_uid = trusted_uid
        self._write_mask = write_mask

    @staticmethod
    def _normalize_root(root: str) -> str:
        return os.path.realpath(root)

    @property
    def roots(self) -> tuple[str, ...]:
        return self._roots

    @property
    def trusted_uid(self) -> int:
        return self._trusted_uid

    @property
    def write_mask(self) -> int:
        return self._write_mask

    def _in_trusted_root(self, resolved: str) -> bool:
        for root in self._roots:
            if resolved == root:
                return True
            if resolved.startswith(root.rstrip(os.sep) + os.sep):
                return True
        return False

    def verify(self, executable: str) -> str:
        """返回 realpath；任一不满足即 `CommandDenied(sub_step="④-0")`。"""
        if not isinstance(executable, str) or not executable:
            raise CommandDenied("可执行文件为空", sub_step="④-0")
        # 不使用 PATH 解析：必须是绝对路径（含分隔符即视为路径）。
        if os.path.basename(executable) == executable:
            raise CommandDenied("可执行文件必须给出绝对路径（不得经 PATH 解析）", sub_step="④-0")
        resolved = os.path.realpath(executable)
        if not self._in_trusted_root(resolved):
            raise CommandDenied("可执行文件不在受信任根内", sub_step="④-0")
        if self._workspace_root and (
            self._workspace_root == resolved or self._workspace_root.startswith(resolved + os.sep)
        ):
            raise CommandDenied("工作卷不得位于受信任可执行根内", sub_step="④-0")
        try:
            info = os.stat(resolved)
        except OSError as exc:
            raise CommandDenied("可执行文件不可读取", sub_step="④-0") from exc
        if not os.path.isfile(resolved):
            raise CommandDenied("可执行文件不是常规文件", sub_step="④-0")
        if info.st_uid != self._trusted_uid:
            raise CommandDenied("可执行文件属主不是受信任属主", sub_step="④-0")
        if info.st_mode & self._write_mask:
            raise CommandDenied("可执行文件对 group/world 可写", sub_step="④-0")
        try:
            with open(resolved, "rb") as handle:
                head = handle.read(4)
        except OSError as exc:
            raise CommandDenied("可执行文件不可读取", sub_step="④-0") from exc
        if head.startswith(_SHEBANG_MAGIC):
            raise CommandDenied("拒绝 shebang 脚本", sub_step="④-0")
        if not head.startswith(_ELF_MAGIC):
            raise CommandDenied("拒绝非 ELF 可执行文件", sub_step="④-0")
        return resolved


class CommandGate:
    """④ 的落点：④-0 → ④-1 → ④-2 顺序固定，任一命中即 `CommandDenied`。"""

    def __init__(
        self,
        *,
        trusted_roots: Iterable[str],
        workspace_root: str = "",
        trusted_uid: int = 0,
        write_mask: int = 0o022,
    ) -> None:
        self._trust = ExecutableTrust(
            trusted_roots=trusted_roots,
            workspace_root=workspace_root,
            trusted_uid=trusted_uid,
            write_mask=write_mask,
        )

    def verify_source(self, executable: str) -> str:
        return self._trust.verify(executable)

    @staticmethod
    def verify_name(resolved_executable: str) -> str:
        name = resolved_basename(resolved_executable)
        if name not in READ_ONLY_WHITELIST:
            raise CommandDenied("可执行名不在最小只读白名单内", sub_step="④-1")
        return name

    @staticmethod
    def verify_blacklist(
        resolved_executable: str, args: Sequence[str], *, workspace_path: str | None = None
    ) -> None:
        if executable_blacklist_hit(resolved_executable, args):
            raise CommandDenied("命中可执行名黑名单", sub_step="④-2")
        if param_blacklist_hit(resolved_executable, args, workspace_path=workspace_path):
            raise CommandDenied("命中参数级黑名单", sub_step="④-2")
