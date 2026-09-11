"""跨租户隔离实测探针（门禁项 8「RAGFlow/AgentScope 跨租户实测」验收前置）。

用途
    用两个租户的访问令牌做**双向交叉访问**，验证租户隔离（水平越权防线）在真实 staging 上成立：

    - 用租户 A 的令牌访问**属于租户 B 的**资源，断言返回 ``403`` 或 ``404``；
    - 用租户 B 的令牌访问**属于租户 A 的**资源，再验一次；
    - 逐资源输出结果行。

    任何 ``200``（或其它非 ``403``/``404`` 的响应，含 ``5xx`` 与传输异常）都判 ``fail``——
    因为 ``200`` 意味着跨租户读取成功或拿到了对方实体数据。

正向对照（positive control，避免空转通过）
    每个资源在交叉访问之外，还必须**用所有者自己的令牌读取该资源**：``A→A`` 与 ``B→B``
    都必须返回 ``200``。只有当两个正向对照都通过时，交叉拒绝的结论才有效。
    若任一正向对照不是 ``200``（例如 ``404``），说明资源 id 写错、资源已删除或所有者不可读，
    该用例**无效**，一律判 ``fail``——因为「两端都 404」既可能是隔离成立，也可能是资源根本不存在，
    无效用例不能当作隔离成立的证据。

资源类型（按真实存在的接口核对，均按当前令牌的 ``tenant_id`` 做归属过滤）
    - ``task`` → ``GET /api/v1/tasks/{id}``（跨租户 / 无权 → ``404``）
    - ``plan_proposal`` → ``GET /api/v1/plan-proposals/{id}``（跨租户 → ``404``）
    - ``content_task`` → ``GET /api/v1/content-tasks/{id}``（跨租户 → ``404``）
    - ``run_metrics`` → ``GET /api/v1/runs/{id}/metrics``（跨租户 → ``404``）
    - ``orchestration_proposal`` → ``GET /api/v1/orchestration-proposals/{id}``
      （非 CEO/超管 → ``403``；管理员跨租户 → ``404``）
    - ``commercial_lifecycle`` → ``GET /api/v1/commercial/lifecycle/{id}``（同上）

前置条件（缺一即停）
    - 一个**独立 staging 主机**（HTTPS，非 localhost / 127.0.0.1 / ::1 / 0.0.0.0）。
    - **两个不同租户**各自的访问令牌（``Authorization: Bearer <token>``）。
    - 每类资源都要提供**真实存在、分属两个租户的两个资源标识**：``--resource KIND:A_ID:B_ID``，
      其中 ``A_ID`` 属于令牌 A 的租户、``B_ID`` 属于令牌 B 的租户；两者必须不同。

安全护栏（fail-closed，先于任何请求）
    - ``--base-url`` 非 ``https``（未加 ``--allow-insecure``）→ 拒绝；
    - 指向 localhost / 127.0.0.1 / ::1 / 0.0.0.0（未加 ``--allow-local``）→ 拒绝；
    - 缺少任一租户令牌 / 缺少资源规格 / 资源规格非法 → 参数错误（退出码 ``2``）。

脱敏要求
    - 报告**只输出资源类型与响应码**，以及判定文案；**绝不打印令牌，也不打印响应正文里的业务数据**。

已知缺口（本轮如实登记，未臆造接口）
    - ``knowledge-access`` 的角色/数字员工绑定与审计接口按调用方 ``tenant_id`` 直接返回**本租户**数据，
      没有可指向「他租户」的资源标识，无法构造跨租户对照，故未纳入探测。
    - 若某类资源当前无法提供属于另一租户的标识（例如需要 ``pending`` 状态的提案），请如实跳过该资源，
      不要伪造 id。

退出码
    ``2`` 参数/配置错误；``0`` 全部资源 ``pass``；``1`` 任一资源 ``fail``。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Iterable, Sequence
from urllib.parse import urlsplit

import httpx

RESOURCE_PATHS: dict[str, str] = {
    "task": "/api/v1/tasks/{resource_id}",
    "plan_proposal": "/api/v1/plan-proposals/{resource_id}",
    "content_task": "/api/v1/content-tasks/{resource_id}",
    "run_metrics": "/api/v1/runs/{resource_id}/metrics",
    "orchestration_proposal": "/api/v1/orchestration-proposals/{resource_id}",
    "commercial_lifecycle": "/api/v1/commercial/lifecycle/{resource_id}",
}

_BLOCKED_STATUSES = frozenset({403, 404})
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

Transport = Callable[..., object]

ResourceSpec = tuple[str, str, str]


class CrossTenantConfigError(ValueError):
    """探针配置错误；必须在发起任何请求前抛出。"""


@dataclass(frozen=True)
class ResourceProbe:
    kind: str
    status: str
    code_ab: int
    code_ba: int
    message: str
    # 正向对照状态码（新增字段必须置于末尾并给默认值，保持既有位置构造兼容）
    code_aa: int | None = None
    code_bb: int | None = None


@dataclass(frozen=True)
class CrossTenantReport:
    base_url_host: str
    probes: tuple[ResourceProbe, ...]
    generated_at: str

    @property
    def passed(self) -> bool:
        return not any(probe.status == "fail" for probe in self.probes)

    def to_text(self) -> str:
        lines = [
            f"跨租户探针结果：{'pass' if self.passed else 'fail'}",
            f"目标主机：{self.base_url_host}",
            f"生成时间：{self.generated_at}",
        ]
        for probe in self.probes:
            lines.append(
                f"[{probe.status}] 隔离 {probe.kind}："
                f"A→A={_code_text(probe.code_aa)} B→B={_code_text(probe.code_bb)} "
                f"A→B={_code_text(probe.code_ab)} B→A={_code_text(probe.code_ba)}：{probe.message}"
            )
        return "\n".join(lines)


def resolve_base_url(
    base_url: str, *, allow_insecure: bool = False, allow_local: bool = False
) -> str:
    """解析并校验 staging 基础地址；越界立即 fail-closed。"""
    if not isinstance(base_url, str) or not base_url.strip():
        raise CrossTenantConfigError("必须提供 staging 基础地址")
    candidate = base_url.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme != "https" and not allow_insecure:
        raise CrossTenantConfigError("跨租户探针必须使用 HTTPS")
    hostname = (parsed.hostname or "").lower()
    if hostname in _LOCAL_HOSTS and not allow_local:
        raise CrossTenantConfigError("必须指向独立 staging 主机，不能回落本地")
    return candidate.rstrip("/")


def parse_resource(spec: str) -> ResourceSpec:
    """解析 ``KIND:A_ID:B_ID``；非法规格 fail-closed。"""
    parts = spec.split(":")
    if len(parts) != 3:
        raise CrossTenantConfigError(f"资源规格必须为 KIND:A_ID:B_ID，收到：{spec}")
    kind, a_id, b_id = (part.strip() for part in parts)
    if kind not in RESOURCE_PATHS:
        raise CrossTenantConfigError(f"未知资源类型：{kind or '(空)'}")
    if not a_id or not b_id:
        raise CrossTenantConfigError("资源标识不能为空")
    if a_id == b_id:
        raise CrossTenantConfigError("A/B 两侧资源标识必须不同，否则无法构成跨租户对照")
    return kind, a_id, b_id


def _host(base_url: str) -> str:
    try:
        return (urlsplit(base_url).hostname or "").lower()
    except ValueError:
        return ""


def _code_text(code: int | None) -> str:
    return "-" if not code else str(code)


def _path(kind: str, resource_id: str) -> str:
    return RESOURCE_PATHS[kind].format(resource_id=resource_id)


def _request(
    transport: Transport | None,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
) -> object:
    if transport is None:
        return httpx.request(method, url, headers=headers, timeout=timeout)
    return transport(method, url, headers=headers, data=None, params=None, timeout=timeout)


def _safe_status(
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


def evaluate_isolation(code_ab: int, code_ba: int) -> tuple[str, str]:
    """双向响应码判定：仅 ``403``/``404`` 视为通过。"""
    problems: list[str] = []
    if code_ab == 0:
        problems.append("A→B 请求无响应（传输异常）")
    elif code_ab not in _BLOCKED_STATUSES:
        problems.append(f"A→B 返回 {code_ab}，租户隔离失效（期望 403/404）")
    if code_ba == 0:
        problems.append("B→A 请求无响应（传输异常）")
    elif code_ba not in _BLOCKED_STATUSES:
        problems.append(f"B→A 返回 {code_ba}，租户隔离失效（期望 403/404）")
    if problems:
        return "fail", "；".join(problems)
    return "pass", "双向均返回 403/404，租户隔离成立"


def _control_problem(role: str, code: int) -> str:
    if code == 0:
        return f"正向对照未通过：{role} 对自己的资源请求无响应（传输异常），本用例无效"
    return (
        f"正向对照未通过：{role} 对自己的资源返回 {code}，"
        "该资源不存在或所有者不可读，本用例无效"
    )


def evaluate_isolation_with_controls(
    code_aa: int, code_bb: int, code_ab: int, code_ba: int
) -> tuple[str, str]:
    """先判正向对照（``A→A`` / ``B→B`` 必须 ``200``），再委托双向交叉判定。

    正向对照不通过意味着该资源根本不存在或所有者不可读：此时「跨租户返回 403/404」毫无意义，
    必须判 ``fail`` 并明确标注该用例无效，避免空转通过。
    """
    problems: list[str] = []
    if code_aa != 200:
        problems.append(_control_problem("A", code_aa))
    if code_bb != 200:
        problems.append(_control_problem("B", code_bb))
    if problems:
        return "fail", "；".join(problems)
    status, message = evaluate_isolation(code_ab, code_ba)
    if status == "pass":
        return "pass", f"正向对照通过（A→A=200 B→B=200）且{message}"
    return status, message


def _probe_resource(
    base_url: str,
    kind: str,
    a_id: str,
    b_id: str,
    *,
    token_a: str,
    token_b: str,
    transport: Transport | None,
    timeout: float,
) -> ResourceProbe:
    # 正向对照：所有者读自己的资源，必须 200
    code_aa = _safe_status(
        base_url, _path(kind, a_id), token_a, transport=transport, timeout=timeout
    )
    code_bb = _safe_status(
        base_url, _path(kind, b_id), token_b, transport=transport, timeout=timeout
    )
    # 双向交叉访问：用对方令牌读本资源
    code_ab = _safe_status(
        base_url, _path(kind, b_id), token_a, transport=transport, timeout=timeout
    )
    code_ba = _safe_status(
        base_url, _path(kind, a_id), token_b, transport=transport, timeout=timeout
    )
    status, message = evaluate_isolation_with_controls(code_aa, code_bb, code_ab, code_ba)
    return ResourceProbe(kind, status, code_ab, code_ba, message, code_aa, code_bb)


def run_probe(
    base_url: str,
    *,
    token_a: str,
    token_b: str,
    resources: Iterable[ResourceSpec],
    transport: Transport | None = None,
    timeout: float = 10.0,
) -> CrossTenantReport:
    probes = tuple(
        _probe_resource(
            base_url,
            kind,
            a_id,
            b_id,
            token_a=token_a,
            token_b=token_b,
            transport=transport,
            timeout=timeout,
        )
        for kind, a_id, b_id in resources
    )
    return CrossTenantReport(
        base_url_host=_host(base_url),
        probes=probes,
        generated_at=datetime.now(UTC).isoformat(),
    )


def _run_example() -> int:
    """离线演示 fail-closed 参数校验：不发起任何网络请求。"""
    print("示例：演示跨租户探针的 fail-closed 参数校验（不发起任何网络请求）")
    print("配置错误：缺少租户 A 令牌（--token-a）")
    return 2


def main(argv: list[str] | None = None, *, transport: Transport | None = None) -> int:
    parser = argparse.ArgumentParser(description="公司工作台跨租户隔离实测探针")
    parser.add_argument("--base-url", default="", help="staging 基础地址（须 HTTPS、非本地）")
    parser.add_argument("--token-a", default="", help="租户 A 访问令牌（不会写入报告）")
    parser.add_argument("--token-b", default="", help="租户 B 访问令牌（不会写入报告）")
    parser.add_argument(
        "--resource",
        action="append",
        default=None,
        help="KIND:A_ID:B_ID，A_ID 属租户 A、B_ID 属租户 B；可重复",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="单请求超时秒数（默认 10）")
    parser.add_argument("--allow-insecure", action="store_true", help="允许 http://（仅限内网联调）")
    parser.add_argument("--allow-local", action="store_true", help="允许本地主机（仅限自测）")
    parser.add_argument("--example", action="store_true", help="演示 fail-closed 参数校验")
    args = parser.parse_args(argv)

    if args.example:
        return _run_example()

    if not args.base_url:
        print("配置错误：缺少 --base-url")
        return 2
    if not args.token_a:
        print("配置错误：缺少租户 A 令牌（--token-a）")
        return 2
    if not args.token_b:
        print("配置错误：缺少租户 B 令牌（--token-b）")
        return 2
    if not args.resource:
        print("配置错误：至少需要一个 --resource KIND:A_ID:B_ID")
        return 2

    try:
        base_url = resolve_base_url(
            args.base_url, allow_insecure=args.allow_insecure, allow_local=args.allow_local
        )
    except CrossTenantConfigError as exc:
        print(f"配置错误：{exc}")
        return 2
    if args.timeout <= 0:
        print("配置错误：--timeout 必须为正数")
        return 2

    try:
        resources: Sequence[ResourceSpec] = [parse_resource(spec) for spec in args.resource]
    except CrossTenantConfigError as exc:
        print(f"配置错误：{exc}")
        return 2

    report = run_probe(
        base_url,
        token_a=args.token_a,
        token_b=args.token_b,
        resources=resources,
        transport=transport,
        timeout=args.timeout,
    )
    print(report.to_text())
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
