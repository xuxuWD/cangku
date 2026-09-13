"""③ 路径校验 + ④-2 C 类路径黑名单（规格 §3.2 ③ / §3.2.1 C）。

③ 口径：工具参数使用**虚拟化路径**（默认前缀 `/workspace`），映射到该 run 的工作卷后，
**realpath 必须落在工作卷内** —— 防 `../` 逃逸与**符号链接逃逸**（realpath 会解析链接）。
C 类口径：对 realpath 绝对路径做「前缀匹配」+「基名 glob 匹配」，任一命中即拒。

⚠️ 本模块的路径黑名单**按 Linux 语义判定**（执行环境限定 Linux 容器，§3.2.1 R4）：
不调用 `os.path.realpath`（宿主是 Windows 时会把 `/etc/shadow` 解析成盘符路径），
只做分隔符归一 + `~` 展开 + 前缀/基名匹配。
"""

from __future__ import annotations

import fnmatch
import os

VIRTUAL_ROOT = "/workspace"

# 前缀黑名单（命中即拒）。
_PREFIX_DENY = (
    "/etc/shadow",
    "/etc/sudoers",
    "/root",
    "/proc/sys",
    "/sys",
    "/dev",
    "/var/run/secrets",
)
_EXACT_DENY = ("/proc/self/environ", "/proc/self/maps", "/proc/self/mem")
# 基名 glob 黑名单（大小写不敏感）。
_BASENAME_DENY = (".env", ".npmrc", ".pypirc", "*.pem", "*.key", "id_rsa*")


class PathDenied(ValueError):
    """路径不在允许范围内（③ → 403 `path_denied`）。"""


class BlacklistedPath(PathDenied):
    """命中 C 类路径黑名单（④-2 → 403 `blacklisted`）。"""


def _posix(value: str) -> str:
    return os.path.expanduser(value).replace("\\", "/")


def path_blacklist_hit(path: str) -> bool:
    """C 类路径黑名单判定：前缀匹配 + 基名 glob 匹配，任一命中即 True。"""
    if not isinstance(path, str) or not path:
        return False
    candidate = _posix(path)
    for prefix in _PREFIX_DENY:
        if candidate == prefix or candidate.startswith(prefix + "/"):
            return True
    if candidate in _EXACT_DENY:
        return True
    # `/proc/*/environ`：进程环境变量窥探。
    if candidate.startswith("/proc/") and candidate.rsplit("/", 1)[-1] == "environ":
        return True
    home = _posix("~").rstrip("/")
    for sensitive in (".ssh", ".aws", ".config/gcloud"):
        if candidate == f"{home}/{sensitive}" or candidate.startswith(f"{home}/{sensitive}/"):
            return True
    if candidate == f"{home}/.docker/config.json":
        return True
    basename = candidate.rsplit("/", 1)[-1].lower()
    return any(fnmatch.fnmatch(basename, pattern) for pattern in _BASENAME_DENY)


class PathGuard:
    """③ 的落点：虚拟路径 → realpath → 必须落在本 run 工作卷内。"""

    def __init__(self, *, virtual_root: str = VIRTUAL_ROOT) -> None:
        self._virtual_root = virtual_root.rstrip("/") or "/"

    def resolve(self, virtual_path: str, *, workspace_path: str) -> str:
        """把虚拟路径映射到工作卷并 realpath；越界（含符号链接）一律 `PathDenied`。"""
        if not isinstance(virtual_path, str) or virtual_path == "":
            raise PathDenied("路径为空")
        root = self._virtual_root
        if virtual_path == root:
            relative = ""
        elif virtual_path.startswith(root + "/"):
            relative = virtual_path[len(root) + 1 :]
        else:
            raise PathDenied("路径不在工作卷虚拟根内")
        base = os.path.realpath(workspace_path)
        candidate = os.path.realpath(os.path.join(base, relative))
        if not _within(candidate, base):
            raise PathDenied("路径 realpath 后落在允许目录之外")
        return candidate


def _within(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
    except ValueError:
        return False
