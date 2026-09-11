"""桌面端自动更新链路演练（客户端发布链「旧版 → 新版」验收前置）。

用途
    把「自动更新能装上新版」拆成**可机械验证的搬运层**与**必须人工完成的安装层**：

    - 机械部分（本脚本）：更新源可达、元数据形状正确、版本递增、安装包完整（sha512 与大小一致）。
    - 人工部分（脚本只列清单、不代跑）：在**干净 Windows 机器**上装旧版 → 启动 → 触发更新检查
      → 下载新版 → 重启完成升级 → 确认版本号变化；以及更新失败时的回滚表现。

    electron-updater 的真实安装步骤无法在无 GUI / 无签名安装包的机器上执行，因此脚本对这部分
    一律输出 ``skipped`` 并写明「人工执行」，**不得**把它计为通过（宪法 2.5）。

更新源约定（与 ``desktop/`` 保持一致）
    - 运行时与构建时共用 ``WORKBENCH_DESKTOP_UPDATE_URL``（必须是 HTTPS）。
    - 频道白名单 ``latest`` / ``beta`` / ``alpha``，元数据文件名即 ``<频道>.yml``。
    - 元数据形状取 electron-builder 生成的 ``latest.yml``：``version`` / ``path`` / ``sha512``
      与 ``files[]``（``url`` / ``sha512`` / ``size``）。**不引入 YAML 依赖**，只解析这一种已知形状；
      形状不符一律 fail-closed。

安全护栏（fail-closed，先于任何请求）
    - ``--update-url`` 非 ``https``（未加 ``--allow-insecure``）→ 拒绝；
    - 指向 localhost / 127.0.0.1 / ::1 / 0.0.0.0（未加 ``--allow-local``）→ 拒绝；
    - 报告只含主机名、频道、版本与判定文案，**不打印完整 URL 查询串**。

退出码
    ``2`` 参数/配置错误；``0`` ``pass``（或该阶段 ``skipped``）；``1`` ``fail``。
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

import httpx

DEFAULT_CHANNEL = "latest"
RUN_CHANNELS = ("latest", "beta", "alpha")

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_FLOATING_REFS = {"latest", "main", "master", "head", "trunk"}
_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")

METADATA_MAX_BYTES = 1_000_000
DEFAULT_MAX_BYTES = 500 * 1024 * 1024

Transport = Callable[..., object]


class DrillConfigError(ValueError):
    """演练配置或元数据形状错误；配置错误必须在发起任何请求前抛出。"""


class ArtifactTooLarge(RuntimeError):
    """安装包下载体积超过上限，按 fail-closed 处理。"""


@dataclass(frozen=True)
class DrillCheck:
    name: str
    status: str
    message: str


@dataclass(frozen=True)
class DrillReport:
    status: str
    checks: tuple[DrillCheck, ...]
    update_host: str = ""
    channel: str = ""
    version: str = ""

    def to_text(self) -> str:
        lines = [f"自动更新链路演练结果：{self.status}"]
        if self.update_host:
            lines.append(f"更新源主机：{self.update_host}")
        if self.channel:
            lines.append(f"频道：{self.channel}")
        if self.version:
            lines.append(f"目标版本：{self.version}")
        lines.extend(f"[{check.status}] {check.name}：{check.message}" for check in self.checks)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "update_host": self.update_host,
            "channel": self.channel,
            "version": self.version,
            "checks": [
                {"name": check.name, "status": check.status, "message": check.message}
                for check in self.checks
            ],
        }


def resolve_update_url(
    update_url: str, *, allow_insecure: bool = False, allow_local: bool = False
) -> str:
    """解析并校验更新源地址；越界立即 fail-closed。"""
    if not isinstance(update_url, str) or not update_url.strip():
        raise DrillConfigError("必须提供更新源地址")
    candidate = update_url.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme != "https" and not allow_insecure:
        raise DrillConfigError("更新源必须使用 HTTPS")
    hostname = (parsed.hostname or "").lower()
    if hostname in _LOCAL_HOSTS and not allow_local:
        raise DrillConfigError("更新源必须指向独立主机，不能回落本地")
    return candidate.rstrip("/")


def metadata_name(channel: str) -> str:
    """按频道给出元数据文件名；频道不在白名单内即拒绝。"""
    normalized = (channel or "").strip()
    if normalized not in RUN_CHANNELS:
        raise DrillConfigError(
            f"更新频道必须是 {'/'.join(RUN_CHANNELS)} 之一，当前为 {normalized or '（空）'}"
        )
    return f"{normalized}.yml"


def parse_version(text: str) -> tuple[int, int, int] | None:
    """解析语义化版本；浮动引用（latest/main/head 等）一律返回 None。"""
    if not isinstance(text, str):
        return None
    candidate = text.strip()
    if not candidate or candidate.lower() in _FLOATING_REFS:
        return None
    matched = _SEMVER_RE.match(candidate)
    if matched is None:
        return None
    return int(matched.group(1)), int(matched.group(2)), int(matched.group(3))


def sha512_base64(data: bytes) -> str:
    return base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")


def decode_sha512(value: str) -> bytes:
    """解码 base64 形式的 sha512 摘要；非法 base64 或长度不是 64 字节即拒绝。"""
    candidate = (value or "").strip()
    if not candidate:
        raise DrillConfigError("元数据缺少 sha512")
    try:
        digest = base64.b64decode(candidate, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DrillConfigError("元数据 sha512 不是合法 base64") from exc
    if len(digest) != 64:
        raise DrillConfigError("元数据 sha512 长度不是 64 字节")
    return digest


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _coerce(value: str) -> object:
    return int(value) if value.isdigit() else value


def parse_update_metadata(text: str) -> dict[str, object]:
    """解析 electron-builder 生成的更新元数据（仅支持这一种已知形状）。"""
    result: dict[str, object] = {}
    in_files = False
    current_item: dict[str, object] | None = None

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        stripped = raw_line.strip()
        indented = raw_line[:1] in {" ", "\t"}

        if indented:
            if not in_files:
                raise DrillConfigError(f"元数据缩进异常：{stripped}")
            if stripped.startswith("- "):
                current_item = {}
                files = result.setdefault("files", [])
                if not isinstance(files, list):
                    raise DrillConfigError("元数据 files 形状异常")
                files.append(current_item)
                stripped = stripped[2:].strip()
                if not stripped:
                    raise DrillConfigError("元数据 files 列表项为空")
            if current_item is None:
                raise DrillConfigError(f"元数据缩进异常：{stripped}")
            key, separator, value = stripped.partition(":")
            if not separator or not key.strip():
                raise DrillConfigError(f"元数据存在无法解析的行：{stripped}")
            current_item[key.strip()] = _coerce(_unquote(value.strip()))
            continue

        in_files = False
        current_item = None
        key, separator, value = stripped.partition(":")
        if not separator or not key.strip():
            raise DrillConfigError(f"元数据存在无法解析的行：{stripped}")
        key = key.strip()
        if key == "files":
            in_files = True
            result["files"] = []
            continue
        result[key] = _coerce(_unquote(value.strip()))

    _validate_metadata(result)
    return result


def _validate_metadata(parsed: dict[str, object]) -> None:
    if parse_version(str(parsed.get("version", ""))) is None:
        raise DrillConfigError("元数据缺少可解析的 version（不接受 latest/main/head 之类浮动值）")
    if not isinstance(parsed.get("path"), str) or not str(parsed["path"]).strip():
        raise DrillConfigError("元数据缺少 path")
    decode_sha512(str(parsed.get("sha512", "")))

    files = parsed.get("files")
    if not isinstance(files, list) or not files:
        raise DrillConfigError("元数据缺少非空 files 列表")
    for item in files:
        if not isinstance(item, dict):
            raise DrillConfigError("元数据 files 形状异常")
        if not isinstance(item.get("url"), str) or not str(item["url"]).strip():
            raise DrillConfigError("元数据 files 项缺少 url")
        decode_sha512(str(item.get("sha512", "")))


def _fetch(
    transport: Transport | None, url: str, *, timeout: float, max_bytes: int
) -> tuple[int, bytes]:
    """取回资源；超限抛 ArtifactTooLarge（fail-closed）。"""
    headers = {"Accept": "*/*"}
    if transport is not None:
        response = transport("GET", url, headers=headers, data=None, params=None, timeout=timeout)
        code = int(getattr(response, "status_code", 0))
        content = getattr(response, "content", b"") or b""
        if len(content) > max_bytes:
            raise ArtifactTooLarge(f"下载体积超过上限 {max_bytes} 字节")
        return code, content

    with httpx.stream("GET", url, headers=headers, timeout=timeout, follow_redirects=True) as response:
        code = int(response.status_code)
        if code != 200:
            return code, b""
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise ArtifactTooLarge(f"下载体积超过上限 {max_bytes} 字节")
            chunks.append(chunk)
        return code, b"".join(chunks)


def _host(update_url: str) -> str:
    try:
        return (urlsplit(update_url).hostname or "").lower()
    except ValueError:
        return ""


MANUAL_STEPS: tuple[tuple[str, str], ...] = (
    (
        "旧版 → 新版实装更新",
        "人工执行（脚本不代跑）：干净 Windows 机器安装旧版 → 启动 → 确认更新检查被触发 → "
        "下载新版 → 重启完成升级 → 核对版本号确已变化。",
    ),
    (
        "更新失败回滚表现",
        "人工执行：断网或篡改更新源时应不安装且应用仍可用；恢复后重试能装上新版。",
    ),
)


def run_drill(
    update_url: str,
    *,
    channel: str = DEFAULT_CHANNEL,
    current_version: str = "",
    phase: str = "full",
    transport: Transport | None = None,
    timeout: float = 10.0,
    max_bytes: int = DEFAULT_MAX_BYTES,
    allow_insecure: bool = False,
    allow_local: bool = False,
) -> DrillReport:
    """执行自动更新链路演练；``phase="metadata"`` 时只校验元数据、不下载安装包。"""
    base_url = resolve_update_url(
        update_url, allow_insecure=allow_insecure, allow_local=allow_local
    )
    name = metadata_name(channel)
    host = _host(base_url)

    def report(status: str, checks: list[DrillCheck], version: str = "") -> DrillReport:
        return DrillReport(status, tuple(checks), update_host=host, channel=channel, version=version)

    metadata_url = urljoin(f"{base_url}/", name)
    try:
        status_code, body = _fetch(
            transport, metadata_url, timeout=timeout, max_bytes=METADATA_MAX_BYTES
        )
    except Exception as exc:  # noqa: BLE001 传输失败按不可达处理
        return report(
            "fail",
            [DrillCheck("更新元数据可达", "fail", f"请求失败（{type(exc).__name__}）")],
        )
    if status_code != 200:
        return report(
            "fail",
            [DrillCheck("更新元数据可达", "fail", f"HTTP {status_code}，期望 200")],
        )

    try:
        parsed = parse_update_metadata(body.decode("utf-8"))
    except (DrillConfigError, UnicodeDecodeError) as exc:
        return report(
            "fail",
            [
                DrillCheck("更新元数据可达", "pass", "已获取元数据"),
                DrillCheck("元数据形状", "fail", str(exc)),
            ],
        )

    version = str(parsed["version"])
    checks: list[DrillCheck] = [
        DrillCheck("更新元数据可达", "pass", "已获取元数据"),
        DrillCheck("元数据形状", "pass", f"version={version}，files 项数={len(parsed['files'])}"),
    ]

    if current_version.strip():
        current = parse_version(current_version)
        if current is None:
            return report(
                "fail",
                checks + [DrillCheck("版本递增", "fail", f"--current-version 无法解析：{current_version}")],
                version,
            )
        if parse_version(version) > current:  # type: ignore[operator]
            checks.append(
                DrillCheck("版本递增", "pass", f"更新源版本 {version} 高于当前版本 {current_version}")
            )
        else:
            checks.append(
                DrillCheck("版本递增", "fail", f"更新源版本 {version} 未高于当前版本 {current_version}")
            )
    else:
        checks.append(
            DrillCheck("版本递增", "skipped", "未提供 --current-version，无法判定版本是否递增")
        )

    if phase == "metadata":
        checks.append(DrillCheck("安装包可下载", "skipped", "metadata 阶段不下载安装包"))
        checks.append(DrillCheck("安装包完整性（sha512）", "skipped", "metadata 阶段不下载安装包"))
        checks.append(DrillCheck("安装包大小一致", "skipped", "metadata 阶段不下载安装包"))
        checks.extend(DrillCheck(step, "skipped", message) for step, message in MANUAL_STEPS)
        return report(_status(checks), checks, version)

    artifact_path = str(parsed["path"])
    artifact_url = urljoin(f"{base_url}/", artifact_path)
    try:
        artifact_status, content = _fetch(
            transport, artifact_url, timeout=timeout, max_bytes=max_bytes
        )
    except ArtifactTooLarge as exc:
        checks.append(DrillCheck("安装包体积上限", "fail", str(exc)))
        checks.append(DrillCheck("安装包完整性（sha512）", "skipped", "未取得安装包"))
        checks.append(DrillCheck("安装包大小一致", "skipped", "未取得安装包"))
        checks.extend(DrillCheck(step, "skipped", message) for step, message in MANUAL_STEPS)
        return report("fail", checks, version)
    except Exception as exc:  # noqa: BLE001 传输失败按不可达处理
        checks.append(
            DrillCheck("安装包可下载", "fail", f"请求失败（{type(exc).__name__}）")
        )
        checks.append(DrillCheck("安装包完整性（sha512）", "skipped", "未取得安装包"))
        checks.append(DrillCheck("安装包大小一致", "skipped", "未取得安装包"))
        checks.extend(DrillCheck(step, "skipped", message) for step, message in MANUAL_STEPS)
        return report("fail", checks, version)

    if artifact_status != 200:
        checks.append(
            DrillCheck("安装包可下载", "fail", f"HTTP {artifact_status}，期望 200")
        )
        checks.append(DrillCheck("安装包完整性（sha512）", "skipped", "未取得安装包"))
        checks.append(DrillCheck("安装包大小一致", "skipped", "未取得安装包"))
        checks.extend(DrillCheck(step, "skipped", message) for step, message in MANUAL_STEPS)
        return report("fail", checks, version)

    checks.append(DrillCheck("安装包可下载", "pass", f"已取得 {len(content)} 字节"))

    expected_digest = base64.b64encode(decode_sha512(str(parsed["sha512"]))).decode("ascii")
    actual_digest = sha512_base64(content)
    if expected_digest == actual_digest:
        checks.append(DrillCheck("安装包完整性（sha512）", "pass", "摘要与元数据一致"))
    else:
        checks.append(
            DrillCheck("安装包完整性（sha512）", "fail", "摘要与元数据不一致（安装包可能损坏或被替换）")
        )

    declared_size = _declared_size(parsed, artifact_path)
    if declared_size is None:
        checks.append(DrillCheck("安装包大小一致", "skipped", "元数据未登记该文件大小"))
    elif declared_size == len(content):
        checks.append(DrillCheck("安装包大小一致", "pass", f"{declared_size} 字节"))
    else:
        checks.append(
            DrillCheck(
                "安装包大小一致",
                "fail",
                f"元数据登记 {declared_size} 字节，实际 {len(content)} 字节",
            )
        )

    checks.extend(DrillCheck(step, "skipped", message) for step, message in MANUAL_STEPS)
    return report(_status(checks), checks, version)


def _declared_size(parsed: dict[str, object], artifact_path: str) -> int | None:
    basename = artifact_path.rsplit("/", 1)[-1]
    for item in parsed.get("files", []):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", ""))
        if url in {artifact_path, basename} and isinstance(item.get("size"), int):
            return int(item["size"])
    return None


def _status(checks: list[DrillCheck]) -> str:
    return "fail" if any(check.status == "fail" for check in checks) else "pass"


def _run_example() -> int:
    """离线演示 fail-closed 护栏：不发起任何网络请求。"""
    print("示例：演示自动更新链路演练的 fail-closed 护栏（不发起任何网络请求）")
    for candidate in ("http://updates.example.com/workbench", "https://localhost:8000/workbench"):
        try:
            resolve_update_url(candidate)
        except DrillConfigError as exc:
            print(f"[fail] 护栏 {candidate}：{exc}")
    for channel in ("nightly", "HEAD"):
        try:
            metadata_name(channel)
        except DrillConfigError as exc:
            print(f"[fail] 护栏 频道 {channel}：{exc}")
    print("[skipped] 演练：示例模式不访问任何更新源")
    return 2


def main(argv: list[str] | None = None, *, transport: Transport | None = None) -> int:
    parser = argparse.ArgumentParser(description="公司工作台桌面端自动更新链路演练")
    parser.add_argument("--update-url", default="", help="更新源地址（须 HTTPS、非本地）")
    parser.add_argument(
        "--channel", default=DEFAULT_CHANNEL, help="更新频道：latest / beta / alpha"
    )
    parser.add_argument("--current-version", default="", help="当前已安装版本，用于判定版本递增")
    parser.add_argument(
        "--phase", choices=("metadata", "full"), default="full", help="metadata 只校验元数据"
    )
    parser.add_argument("--output", default="", help="报告 JSON 落盘路径（可选）")
    parser.add_argument("--timeout", type=float, default=10.0, help="单请求超时秒数（默认 10）")
    parser.add_argument(
        "--max-bytes", type=int, default=DEFAULT_MAX_BYTES, help="安装包体积上限（字节）"
    )
    parser.add_argument("--allow-insecure", action="store_true", help="允许 http://（仅限内网联调）")
    parser.add_argument("--allow-local", action="store_true", help="允许本地主机（仅限自测）")
    parser.add_argument("--example", action="store_true", help="演示 fail-closed 护栏")
    args = parser.parse_args(argv)

    if args.example:
        return _run_example()

    if not args.update_url:
        print("配置错误：缺少 --update-url")
        return 2
    if args.timeout <= 0:
        print("配置错误：--timeout 必须为正数")
        return 2
    if args.max_bytes <= 0:
        print("配置错误：--max-bytes 必须为正数")
        return 2
    try:
        metadata_name(args.channel)
        base_url = resolve_update_url(
            args.update_url, allow_insecure=args.allow_insecure, allow_local=args.allow_local
        )
    except DrillConfigError as exc:
        print(f"配置错误：{exc}")
        return 2

    report = run_drill(
        base_url,
        channel=args.channel,
        current_version=args.current_version,
        phase=args.phase,
        transport=transport,
        timeout=args.timeout,
        max_bytes=args.max_bytes,
        allow_insecure=args.allow_insecure,
        allow_local=args.allow_local,
    )
    print(report.to_text())
    if args.output:
        try:
            Path(args.output).write_text(
                json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"报告已写入 {args.output}")
        except OSError as exc:
            print(f"配置错误：报告写入失败（{type(exc).__name__}）")
            return 2
    return 0 if report.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
