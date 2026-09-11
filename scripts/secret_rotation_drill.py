"""生产密钥轮换演练（门禁项 3.2「生产密钥轮换」验收前置）。

用途
    把「轮换 ``WORKBENCH_AUTH_SECRET`` 后旧会话必须失效」拆成可机械验证的两阶段演练：

    - ``--phase before``：用给定凭据登录取得访问令牌，写入 ``--output`` 指定的**证据文件**，
      并打印令牌**指纹**（SHA-256 前 8 位）而非原文。该文件含令牌，用完即删。
    - ``--phase after``：读取 before 产出的令牌，断言三件事：
        ① 旧令牌访问受保护接口 → ``401``（轮换后必须失效）；
        ② 用凭据重新登录 → 成功；
        ③ 新令牌访问同一受保护接口 → ``200``。
      任意一条不符即 ``fail``。

约定（与既有脚本一致）
    - 认证一律走 ``Authorization: Bearer <token>``；登录接口为 ``POST /api/v1/auth/sessions``
      （请求体 ``{"phone","password"}``，可选 ``totp_code``），受保护探针默认
      ``GET /api/v1/approvals/pending``（登录后对任意角色均返回 200）。
    - 可通过 ``transport`` 注入 HTTP 传输层，形如
      ``transport(method, url, *, headers, data=None, params=None, timeout)``，便于离线测试。

安全护栏（fail-closed，先于任何请求）
    - ``--base-url`` 非 ``https``（未加 ``--allow-insecure``）→ 拒绝；
    - 指向 localhost / 127.0.0.1 / ::1 / 0.0.0.0（未加 ``--allow-local``）→ 拒绝；
    - **绝不打印令牌原文**，报告与证据文件提示里只出现指纹。

退出码
    ``2`` 参数/配置错误；``0`` 该阶段 ``pass``（或 ``skipped``）；``1`` ``fail``。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import httpx

DEFAULT_PROBE_PATH = "/api/v1/approvals/pending"
LOGIN_PATH = "/api/v1/auth/sessions"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

Transport = Callable[..., object]

_EXPECTED_OLD_STATUS = 401
_EXPECTED_NEW_STATUS = 200


class DrillConfigError(ValueError):
    """演练配置错误；必须在发起任何请求前抛出。"""


@dataclass(frozen=True)
class DrillCheck:
    name: str
    status: str
    message: str


@dataclass(frozen=True)
class DrillReport:
    status: str
    checks: tuple[DrillCheck, ...]
    token_fingerprint: str = ""

    def to_text(self) -> str:
        lines = [f"密钥轮换演练结果：{self.status}"]
        if self.token_fingerprint:
            lines.append(f"令牌指纹：sha256:{self.token_fingerprint}")
        lines.extend(f"[{check.status}] {check.name}：{check.message}" for check in self.checks)
        return "\n".join(lines)


def resolve_base_url(
    base_url: str, *, allow_insecure: bool = False, allow_local: bool = False
) -> str:
    """解析并校验 staging 基础地址；越界立即 fail-closed。"""
    if not isinstance(base_url, str) or not base_url.strip():
        raise DrillConfigError("必须提供 staging 基础地址")
    candidate = base_url.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme != "https" and not allow_insecure:
        raise DrillConfigError("演练必须使用 HTTPS")
    hostname = (parsed.hostname or "").lower()
    if hostname in _LOCAL_HOSTS and not allow_local:
        raise DrillConfigError("演练必须指向独立 staging 主机，不能回落本地")
    return candidate.rstrip("/")


def fingerprint(token: str) -> str:
    """返回令牌指纹（SHA-256 前 8 位），用于在不暴露原文的前提下标识令牌。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]


def _host(base_url: str) -> str:
    try:
        return (urlsplit(base_url).hostname or "").lower()
    except ValueError:
        return ""


def _code_text(code: int) -> str:
    return "无响应（传输异常）" if code == 0 else f"HTTP {code}"


def _request(
    transport: Transport | None,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    data: bytes | None = None,
    params: dict[str, str] | None = None,
    timeout: float,
) -> object:
    if transport is None:
        return httpx.request(
            method, url, headers=headers, content=data, params=params, timeout=timeout
        )
    return transport(method, url, headers=headers, data=data, params=params, timeout=timeout)


def _login_token(
    base_url: str, phone: str, password: str, *, transport: Transport | None, timeout: float
) -> tuple[str, int]:
    """登录并返回 (访问令牌, 状态码)；失败时令牌为空字符串。"""
    body = json.dumps({"phone": phone, "password": password}).encode("utf-8")
    response = _request(
        transport,
        "POST",
        f"{base_url}{LOGIN_PATH}",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        data=body,
        timeout=timeout,
    )
    code = int(getattr(response, "status_code", 0))
    if code != 200:
        return "", code
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 响应体不可解析时按登录失败处理
        return "", code
    if not isinstance(payload, dict):
        return "", code
    token = payload.get("access_token")
    return (token if isinstance(token, str) else ""), code


def _probe_status(
    base_url: str, path: str, token: str, *, transport: Transport | None, timeout: float
) -> int:
    try:
        response = _request(
            transport,
            "GET",
            f"{base_url}{path}",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001 传输失败显式记 0，后续判 fail
        return 0
    return int(getattr(response, "status_code", 0))


def run_before(
    base_url: str,
    *,
    phone: str,
    password: str,
    output_path: str,
    transport: Transport | None = None,
    timeout: float = 10.0,
) -> DrillReport:
    """第一阶段：登录取令牌并写入证据文件；只打印指纹。"""
    try:
        token, code = _login_token(
            base_url, phone, password, transport=transport, timeout=timeout
        )
    except Exception as exc:  # noqa: BLE001 登录请求失败必须判 fail
        return DrillReport(
            "fail",
            (DrillCheck("登录并获取令牌", "fail", f"登录请求失败（{type(exc).__name__}）"),),
        )
    if not token:
        return DrillReport(
            "fail",
            (DrillCheck("登录并获取令牌", "fail", f"登录未取得访问令牌（{_code_text(code)}）"),),
        )
    value = fingerprint(token)
    try:
        Path(output_path).write_text(
            json.dumps(
                {
                    "access_token": token,
                    "base_url": base_url,
                    "generated_at": datetime.now(UTC).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        return DrillReport(
            "fail",
            (
                DrillCheck("登录并获取令牌", "pass", f"已获取访问令牌（指纹 sha256:{value}）"),
                DrillCheck("写入令牌证据文件", "fail", f"写入失败（{type(exc).__name__}）"),
            ),
        )
    return DrillReport(
        "pass",
        (
            DrillCheck("登录并获取令牌", "pass", f"已获取访问令牌（指纹 sha256:{value}）"),
            DrillCheck(
                "写入令牌证据文件",
                "pass",
                f"已写入 {output_path}；该文件含访问令牌，用完即删",
            ),
        ),
        token_fingerprint=value,
    )


def run_after(
    base_url: str,
    *,
    phone: str,
    password: str,
    token_path: str,
    probe_path: str = DEFAULT_PROBE_PATH,
    transport: Transport | None = None,
    timeout: float = 10.0,
) -> DrillReport:
    """第二阶段：断言旧令牌失效、重登成功、新令牌可用。"""
    try:
        raw = json.loads(Path(token_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return DrillReport(
            "fail",
            (DrillCheck("读取令牌文件", "fail", f"无法读取 {token_path}（{type(exc).__name__}）"),),
        )
    old_token = raw.get("access_token") if isinstance(raw, dict) else None
    if not isinstance(old_token, str) or not old_token:
        return DrillReport(
            "fail", (DrillCheck("读取令牌文件", "fail", "令牌文件缺少 access_token"),)
        )

    checks: list[DrillCheck] = []

    old_code = _probe_status(base_url, probe_path, old_token, transport=transport, timeout=timeout)
    if old_code == _EXPECTED_OLD_STATUS:
        checks.append(
            DrillCheck("旧令牌访问受保护接口", "pass", "返回 401，轮换后旧令牌已失效")
        )
    elif old_code == 200:
        checks.append(
            DrillCheck(
                "旧令牌访问受保护接口",
                "fail",
                "旧令牌仍可访问受保护接口（HTTP 200），轮换未生效",
            )
        )
    else:
        checks.append(
            DrillCheck(
                "旧令牌访问受保护接口",
                "fail",
                f"返回 {_code_text(old_code)}，期望 {_EXPECTED_OLD_STATUS}",
            )
        )

    try:
        new_token, login_code = _login_token(
            base_url, phone, password, transport=transport, timeout=timeout
        )
    except Exception:  # noqa: BLE001 传输失败按登录失败处理
        new_token, login_code = "", 0
    if new_token:
        checks.append(
            DrillCheck(
                "重新登录获取新令牌",
                "pass",
                f"重新登录成功（指纹 sha256:{fingerprint(new_token)}）",
            )
        )
    else:
        checks.append(
            DrillCheck("重新登录获取新令牌", "fail", f"重新登录失败（{_code_text(login_code)}）")
        )

    if new_token:
        new_code = _probe_status(
            base_url, probe_path, new_token, transport=transport, timeout=timeout
        )
        if new_code == _EXPECTED_NEW_STATUS:
            checks.append(
                DrillCheck("新令牌访问受保护接口", "pass", "返回 200，新令牌可用")
            )
        else:
            checks.append(
                DrillCheck(
                    "新令牌访问受保护接口",
                    "fail",
                    f"返回 {_code_text(new_code)}，期望 {_EXPECTED_NEW_STATUS}",
                )
            )
    else:
        checks.append(
            DrillCheck("新令牌访问受保护接口", "skipped", "未取得新令牌，跳过校验")
        )

    status = "fail" if any(check.status == "fail" for check in checks) else "pass"
    return DrillReport(status, tuple(checks), token_fingerprint=fingerprint(old_token))


def _run_example() -> int:
    """离线演示 fail-closed 护栏：不发起任何网络请求。"""
    print("示例：演示密钥轮换演练的 fail-closed 护栏（不发起任何网络请求）")
    for candidate in ("http://staging.example.com", "https://localhost:8000"):
        try:
            resolve_base_url(candidate)
        except DrillConfigError as exc:
            print(f"[fail] 护栏 {candidate}：{exc}")
    print("[skipped] 演练：示例模式不执行真实登录与令牌轮换")
    return 2


def main(argv: list[str] | None = None, *, transport: Transport | None = None) -> int:
    parser = argparse.ArgumentParser(description="公司工作台生产密钥轮换演练")
    parser.add_argument("--phase", choices=("before", "after"), default=None, help="before 或 after")
    parser.add_argument("--base-url", default="", help="staging 基础地址（须 HTTPS、非本地）")
    parser.add_argument("--phone", default="", help="登录手机号（不会写入报告）")
    parser.add_argument("--password", default="", help="登录口令（不会写入报告）")
    parser.add_argument(
        "--output", default="", help="令牌证据文件：before 写入、after 读取；含令牌，用完即删"
    )
    parser.add_argument("--probe-path", default=DEFAULT_PROBE_PATH, help="受保护探针接口路径")
    parser.add_argument("--timeout", type=float, default=10.0, help="单请求超时秒数（默认 10）")
    parser.add_argument("--allow-insecure", action="store_true", help="允许 http://（仅限内网联调）")
    parser.add_argument("--allow-local", action="store_true", help="允许本地主机（仅限自测）")
    parser.add_argument("--example", action="store_true", help="演示 fail-closed 护栏")
    args = parser.parse_args(argv)

    if args.example:
        return _run_example()

    if args.phase not in {"before", "after"}:
        print("配置错误：必须指定 --phase before 或 --phase after")
        return 2
    for label, value in (
        ("--base-url", args.base_url),
        ("--phone", args.phone),
        ("--password", args.password),
        ("--output", args.output),
    ):
        if not value:
            print(f"配置错误：缺少 {label}")
            return 2
    try:
        base_url = resolve_base_url(
            args.base_url, allow_insecure=args.allow_insecure, allow_local=args.allow_local
        )
    except DrillConfigError as exc:
        print(f"配置错误：{exc}")
        return 2
    if args.timeout <= 0:
        print("配置错误：--timeout 必须为正数")
        return 2

    if args.phase == "before":
        report = run_before(
            base_url,
            phone=args.phone,
            password=args.password,
            output_path=args.output,
            transport=transport,
            timeout=args.timeout,
        )
    else:
        report = run_after(
            base_url,
            phone=args.phone,
            password=args.password,
            token_path=args.output,
            probe_path=args.probe_path,
            transport=transport,
            timeout=args.timeout,
        )
    print(report.to_text())
    return 0 if report.status in {"pass", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
