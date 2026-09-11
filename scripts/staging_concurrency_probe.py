"""Staging 并发探针：验证登录限流跨进程一致性、任务幂等与审批原子性。

用途
    - 对**真实 staging** 环境发起受控并发请求，产出**并发行为统计**（响应码分布、
      P95 延迟、场景判定），用于验收计划项 1「真实并发压测」。
    - 三个场景：
      ① ``login_throttle``：同一专用探针手机号并发**错误口令**登录，期望出现 ``429``；
      ② ``task_idempotency``：同一幂等键并发创建任务，期望只产生 1 条记录；
      ③ ``plan_approval``：同一计划提案并发审批，期望恰好 1 个 ``200``、其余 ``409``。

前置条件（缺一即停）
    - 一个**独立 staging 主机**（HTTPS，非 localhost / 127.0.0.1 / ::1 / 0.0.0.0）。
    - 一个**专用探针账号**及其手机号/口令（登录场景会故意失败并**锁定该账号一段时间**，
      请勿使用任何真实人员账号）；一个具备相应权限的会话令牌。
    - ``plan_approval`` 场景还需要一个处于 ``pending_review`` 且**发起人 ≠ 令牌用户**
      的计划提案 id（自审会被规则拒绝）。

安全护栏
    - 默认强制 HTTPS 与独立主机，越界即 ``ProbeConfigError``（fail-closed，先于任何请求）。
    - 报告只输出主机、路径、响应码分布与耗时；**绝不写入口令明文、令牌或完整 URL 查询串**。
    - 本脚本**不发起任何写入以外的副作用重放**，也**不构成验收证据**——它只产出并发行为
      统计，是否通过验收须由人工按通过判据判定。

退出码
    - ``2`` 配置错误（地址越界 / 参数非法）；``0`` 全部非 skipped 场景 pass；其余 ``1``。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

SCENES = ("login_throttle", "task_idempotency", "plan_approval")

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

# 与 app.settings 默认值一致的登录最大失败次数，仅用于报告文案说明。
DEFAULT_EXPECTED_MAX_FAILURES = 5

_PROBE_WRONG_SUFFIX = "-probe-invalid"


class ProbeConfigError(ValueError):
    """探针配置错误；必须在发起任何请求前抛出。"""


def resolve_base_url(base_url: str, *, allow_insecure: bool = False, allow_local: bool = False) -> str:
    """解析并校验 staging 基础地址；越界立即 fail-closed。"""
    if not isinstance(base_url, str) or not base_url.strip():
        raise ProbeConfigError("必须提供 staging 基础地址")
    candidate = base_url.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme != "https" and not allow_insecure:
        raise ProbeConfigError("staging 探针必须使用 HTTPS")
    hostname = (parsed.hostname or "").lower()
    if hostname in _LOCAL_HOSTS and not allow_local:
        raise ProbeConfigError("必须指向独立 staging 主机，不能回落本地")
    return candidate.rstrip("/")


@dataclass(frozen=True)
class SceneResult:
    name: str
    status: str
    requests: int
    codes: dict[int, int]
    p95_ms: int
    detail: str


@dataclass(frozen=True)
class ProbeResponse:
    status_code: int
    payload: object = None

    def json(self) -> object:
        return self.payload


class ProbeClient(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        json: dict | None = None,
        headers: dict | None = None,
        timeout: float = 10.0,
    ) -> ProbeResponse: ...


class HttpProbeClient:
    """默认基于 httpx 的实现；允许注入 transport 以便离线测试。"""

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(transport=transport)

    def request(
        self,
        method: str,
        url: str,
        *,
        json: dict | None = None,
        headers: dict | None = None,
        timeout: float = 10.0,
    ) -> ProbeResponse:
        response = self._client.request(method, url, json=json, headers=headers, timeout=timeout)
        try:
            payload: object = response.json()
        except ValueError:
            payload = None
        return ProbeResponse(status_code=response.status_code, payload=payload)


@dataclass(frozen=True)
class ProbeTarget:
    base_url: str
    token: str
    phone: str
    password: str
    tenant_id: str = ""
    user_id: str = ""
    role: str = ""


@dataclass(frozen=True)
class _Call:
    code: int
    elapsed_ms: float
    payload: object


def _host(base_url: str) -> str:
    try:
        return (urlsplit(base_url).hostname or "").lower()
    except ValueError:
        return ""


def _headers(target: ProbeTarget) -> dict[str, str]:
    """认证一律走 Bearer；下面三个身份头只在开发态约定下才被后端采信，staging 环境会被忽略。"""
    headers = {"Authorization": f"Bearer {target.token}"}
    if target.tenant_id:
        headers["X-Tenant-Id"] = target.tenant_id
    if target.user_id:
        headers["X-User-Id"] = target.user_id
    if target.role:
        headers["X-User-Role"] = target.role
    return headers


def _wrong_password(password: str) -> str:
    """构造一个与真实口令必定不同、且满足长度约束的探针口令。"""
    candidate = (password + _PROBE_WRONG_SUFFIX)[:128]
    if candidate == password:
        candidate = (_PROBE_WRONG_SUFFIX + password)[:128]
    if candidate == password:
        candidate = _PROBE_WRONG_SUFFIX.strip("-")[:128]
    return candidate


def _response_payload(response: ProbeResponse) -> object:
    try:
        return response.json()
    except Exception:  # noqa: BLE001 响应体不可解析时视作无内容
        return None


def _gather(count: int, call) -> list[_Call]:
    """用 Barrier 对齐启动时刻，最大化并发；传输失败显式记为 code=0（后续判 fail）。"""
    if count <= 0:
        return []
    barrier = Barrier(count)

    def worker(index: int) -> _Call:
        barrier.wait()
        start = time.perf_counter()
        try:
            response = call(index)
        except Exception:  # noqa: BLE001 传输失败必须显式计为失败，不得伪装成功
            return _Call(0, (time.perf_counter() - start) * 1000.0, None)
        return _Call(
            response.status_code,
            (time.perf_counter() - start) * 1000.0,
            _response_payload(response),
        )

    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(worker, range(count)))


def _count_codes(calls: list[_Call]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for call in calls:
        counts[call.code] = counts.get(call.code, 0) + 1
    return counts


def _p95(calls: list[_Call]) -> int:
    if not calls:
        return 0
    ordered = sorted(call.elapsed_ms for call in calls)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return int(round(ordered[index]))


def evaluate_login_throttle(codes: dict[int, int], expected_max_failures: int) -> tuple[str, str]:
    if any(500 <= code < 600 for code in codes):
        return "fail", "出现 5xx，限流实现异常"
    if codes.get(429, 0) >= 1:
        return "pass", f"出现 429，登录限流跨进程生效（部署最大失败次数约为 {expected_max_failures}）"
    return "fail", "未出现 429，登录限流未跨进程生效"


def evaluate_task_idempotency(codes: dict[int, int], task_ids: list[str]) -> tuple[str, str]:
    if any(500 <= code < 600 for code in codes):
        return "fail", "出现 5xx，幂等创建实现异常"
    unique = {task_id for task_id in task_ids if task_id}
    if len(unique) == 1:
        return "pass", f"同一幂等键并发只产生 1 条记录（{next(iter(unique))}）"
    if not unique:
        return "fail", "并发创建未返回任何任务 id（可能全部被拒）"
    return "fail", f"同一幂等键并发产生了 {len(unique)} 条记录"


def evaluate_plan_approval(codes: dict[int, int]) -> tuple[str, str]:
    if any(500 <= code < 600 for code in codes):
        return "fail", "出现 5xx，审批实现异常"
    approved = codes.get(200, 0)
    total = sum(codes.values())
    if approved > 1:
        return "fail", f"出现 {approved} 个 200，审批原子性被破坏"
    if approved == 1 and codes.get(409, 0) == total - 1:
        return "pass", "恰好 1 个 200、其余 409，审批保持原子"
    return "fail", f"响应码分布不符合预期（200={approved}，总数={total}）"


def _run_login_throttle(
    target: ProbeTarget, client: ProbeClient, concurrency: int, timeout: float
) -> SceneResult:
    url = f"{target.base_url}/api/v1/auth/sessions"
    body = {"phone": target.phone, "password": _wrong_password(target.password)}
    calls = _gather(
        concurrency,
        lambda index: client.request("POST", url, json=body, headers={}, timeout=timeout),
    )
    codes = _count_codes(calls)
    status, verdict = evaluate_login_throttle(codes, DEFAULT_EXPECTED_MAX_FAILURES)
    detail = (
        f"并发发送 {concurrency} 次错误口令登录；本场景会锁定该探针账号一段时间；{verdict}"
    )
    return SceneResult("login_throttle", status, concurrency, codes, _p95(calls), detail)


def _run_task_idempotency(
    target: ProbeTarget, client: ProbeClient, concurrency: int, timeout: float
) -> SceneResult:
    url = f"{target.base_url}/api/v1/tasks"
    idempotency_key = f"probe-idempotency-{uuid4().hex}"
    body = {
        "title": "并发探针幂等任务",
        "employee_key": "probe-employee",
        "risk_level": "low",
        "budget": 0,
        "idempotency_key": idempotency_key,
    }
    headers = _headers(target)
    calls = _gather(
        concurrency,
        lambda index: client.request("POST", url, json=body, headers=headers, timeout=timeout),
    )
    codes = _count_codes(calls)
    task_ids = [
        str(call.payload["id"])
        for call in calls
        if isinstance(call.payload, dict) and call.payload.get("id")
    ]
    status, verdict = evaluate_task_idempotency(codes, task_ids)
    detail = f"并发提交同一幂等键 {idempotency_key} 创建任务；{verdict}"
    return SceneResult("task_idempotency", status, concurrency, codes, _p95(calls), detail)


def _run_plan_approval(
    target: ProbeTarget, client: ProbeClient, concurrency: int, timeout: float, proposal_id: str | None
) -> SceneResult:
    if not proposal_id:
        return SceneResult(
            "plan_approval",
            "skipped",
            0,
            {},
            0,
            "需要 --proposal-id：一个处于 pending_review 且发起人 ≠ 令牌用户的计划提案；未提供则跳过",
        )
    url = f"{target.base_url}/api/v1/plan-proposals/{proposal_id}/approval"
    headers = _headers(target)
    calls = _gather(
        concurrency,
        lambda index: client.request("POST", url, json=None, headers=headers, timeout=timeout),
    )
    codes = _count_codes(calls)
    status, verdict = evaluate_plan_approval(codes)
    detail = f"并发审批计划提案 {proposal_id}；{verdict}"
    return SceneResult("plan_approval", status, concurrency, codes, _p95(calls), detail)


def _execute_scene(
    name: str,
    target: ProbeTarget,
    client: ProbeClient,
    concurrency: int,
    timeout: float,
    proposal_id: str | None,
) -> SceneResult:
    if name == "login_throttle":
        return _run_login_throttle(target, client, concurrency, timeout)
    if name == "task_idempotency":
        return _run_task_idempotency(target, client, concurrency, timeout)
    if name == "plan_approval":
        return _run_plan_approval(target, client, concurrency, timeout, proposal_id)
    raise ProbeConfigError(f"未知场景：{name}")


@dataclass(frozen=True)
class ProbeReport:
    base_url_host: str
    scenes: tuple[SceneResult, ...]
    generated_at: str

    @property
    def passed(self) -> bool:
        return not any(scene.status == "fail" for scene in self.scenes)

    def to_dict(self) -> dict[str, object]:
        return {
            "base_url": self.base_url_host,
            "base_url_host": self.base_url_host,
            "generated_at": self.generated_at,
            "passed": self.passed,
            "scenes": [
                {
                    "name": scene.name,
                    "status": scene.status,
                    "requests": scene.requests,
                    "codes": dict(scene.codes),
                    "p95_ms": scene.p95_ms,
                    "detail": scene.detail,
                }
                for scene in self.scenes
            ],
        }

    def to_text(self) -> str:
        lines = [
            f"Staging 并发探针结果：{'pass' if self.passed else 'fail'}",
            f"目标主机：{self.base_url_host}",
            f"生成时间：{self.generated_at}",
        ]
        for scene in self.scenes:
            codes = ",".join(f"{code}:{count}" for code, count in sorted(scene.codes.items())) or "-"
            lines.append(
                f"[{scene.status}] {scene.name}：requests={scene.requests} "
                f"codes={{{codes}}} p95={scene.p95_ms}ms"
            )
            lines.append(f"    {scene.detail}")
        return "\n".join(lines)


def run_probe(
    target: ProbeTarget,
    client: ProbeClient,
    *,
    scenes,
    concurrency: int,
    timeout: float,
    proposal_id: str | None = None,
) -> ProbeReport:
    names = [scenes] if isinstance(scenes, str) else list(scenes)
    results = tuple(
        _execute_scene(name, target, client, concurrency, timeout, proposal_id) for name in names
    )
    return ProbeReport(
        base_url_host=_host(target.base_url),
        scenes=results,
        generated_at=datetime.now(UTC).isoformat(),
    )


def _resolve_scenes(scenes: list[str] | None) -> list[str]:
    if not scenes or "all" in scenes:
        return list(SCENES)
    ordered: list[str] = []
    for scene in scenes:
        if scene not in ordered:
            ordered.append(scene)
    return ordered


def _default_client_factory() -> ProbeClient:
    return HttpProbeClient()


def main(argv: list[str] | None = None, *, client_factory=None) -> int:
    parser = argparse.ArgumentParser(description="公司工作台 staging 并发探针")
    parser.add_argument("--base-url", required=True, help="staging 基础地址（须 HTTPS、非本地）")
    parser.add_argument("--token", required=True, help="探针账号会话令牌（不会写入报告）")
    parser.add_argument("--tenant-id", default="", help="可选：租户标识（作为请求头）")
    parser.add_argument("--user-id", default="", help="可选：用户标识（作为请求头）")
    parser.add_argument("--role", default="", help="可选：角色（作为 X-User-Role 头，仅开发态约定生效）")
    parser.add_argument("--phone", required=True, help="专用探针账号手机号（会被锁定）")
    parser.add_argument("--password", required=True, help="专用探针账号口令（不会写入报告）")
    parser.add_argument(
        "--scene", action="append", default=None, help="all 或场景名，可重复；默认 all"
    )
    parser.add_argument("--concurrency", type=int, default=8, help="并发数（1–64，默认 8）")
    parser.add_argument("--timeout", type=float, default=10.0, help="单请求超时秒数（默认 10）")
    parser.add_argument("--proposal-id", default=None, help="plan_approval 场景所需的提案 id")
    parser.add_argument("--output", default=None, help="将脱敏 JSON 统计写入指定文件")
    parser.add_argument("--allow-insecure", action="store_true", help="允许 http://（仅限内网联调）")
    parser.add_argument("--allow-local", action="store_true", help="允许本地主机（仅限自测）")
    args = parser.parse_args(argv)

    try:
        base_url = resolve_base_url(
            args.base_url, allow_insecure=args.allow_insecure, allow_local=args.allow_local
        )
    except ProbeConfigError as exc:
        print(f"配置错误：{exc}")
        return 2

    if not 1 <= args.concurrency <= 64:
        print("配置错误：--concurrency 必须在 1–64 之间")
        return 2
    if args.timeout <= 0:
        print("配置错误：--timeout 必须为正数")
        return 2

    scenes = _resolve_scenes(args.scene)
    unknown = [scene for scene in scenes if scene not in SCENES]
    if unknown:
        print(f"配置错误：未知场景 {', '.join(unknown)}")
        return 2

    target = ProbeTarget(
        base_url=base_url,
        token=args.token,
        phone=args.phone,
        password=args.password,
        tenant_id=args.tenant_id,
        user_id=args.user_id,
        role=args.role,
    )
    factory = client_factory or _default_client_factory
    report = run_probe(
        target,
        factory(),
        scenes=scenes,
        concurrency=args.concurrency,
        timeout=args.timeout,
        proposal_id=args.proposal_id,
    )
    print(report.to_text())
    if args.output:
        Path(args.output).write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
