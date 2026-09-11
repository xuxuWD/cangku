"""接口契约覆盖的静态守护：每个对外路由都必须写进 `docs/api-contract.md`。

背景：`delivery-gates.md` 的「每次提交必须满足」第 4 条要求「新接口同步更新
`docs/api-contract.md`」，但此前没有守护，导致 `GET /api/v1/content-tasks` 与两个运行指标
接口已实现却未登记。本测试用真实路由表核对契约文本。

约定：契约中必须写出接口的**完整路径**（例如续作动作要分别写成
`POST /api/v1/runs/{run_id}/resume`，不能只写 `/pause、resume、cancel`），
否则该测试无法识别；这是刻意的严格口径。
"""

from pathlib import Path

from fastapi.routing import APIRoute

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "api-contract.md"


def api_route_paths() -> set[str]:
    """收集对外 JSON 接口路径（只取 /api/ 前缀，排除 openapi/docs 等内置路由）。"""
    return {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/")
    }


def test_every_api_route_is_documented_in_contract() -> None:
    content = CONTRACT.read_text(encoding="utf-8")
    missing = sorted(path for path in api_route_paths() if path not in content)

    # 判定依据：契约未登记的接口等于没有对外承诺，客户端无从得知状态码与错误语义。
    assert missing == [], f"以下接口未写入 docs/api-contract.md：{missing}"


def test_contract_covers_jwt_revocation_and_metrics_endpoints() -> None:
    content = CONTRACT.read_text(encoding="utf-8")

    # 判定依据：本轮新增/补齐的能力必须在契约里可查（登出与运行指标）。
    for path in (
        "/api/v1/auth/logout",
        "/api/v1/runs/{run_id}/metrics",
        "/api/v1/metrics/summary",
    ):
        assert path in content, f"契约缺少 {path}"
