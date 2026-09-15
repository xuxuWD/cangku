"""P6a 评测集管理接口的接口级测试（规格 §2.2/§2.3/§3.2）。

口径：
- 正常流程：登记（草稿）→ 补全期望 → 发布 → 替代（supersede）；运行结果只读查询。
- 异常与非法输入：未启用 503 / 非管理员 403 / 未知字段 422 / 非法来源 422 /
  无期望发布 422 / 敏感键快照 422 / 不存在 404。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.evolution.regression import regression_case_specs
from app.evolution.service import EvolutionService
from app.evolution.store import InMemoryEvalStore

client = TestClient(main.app)

TENANT = "t-evo"
ADMIN = "acct-admin"


def headers(role: str = "super_admin", user_id: str = ADMIN, tenant_id: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def _service(*, enabled: bool = True) -> EvolutionService:
    return EvolutionService(
        InMemoryEvalStore(), audit=AuditService(InMemoryAuditStore()), enabled=enabled
    )


def _wire(monkeypatch, service: EvolutionService | None) -> EvolutionService | None:
    """按既有 `_isolate` 范式替换模块级装配（端点每次请求重新读取全局）。"""
    monkeypatch.setattr(main, "evolution_service", service)
    return service


def _snapshot(prompt: str = "帮我总结本周销售数据") -> dict:
    return {"prompt": prompt, "logs": []}


def _expectation(expect: str = "pass") -> dict:
    return {"probe": "runtime-safety-probe", "expect": expect}


def _create(payload: dict | None = None):
    body = {
        "suite_key": "runtime-safety",
        "input_snapshot": _snapshot(),
        "expectation": _expectation(),
    }
    if payload:
        body.update(payload)
    return client.post("/api/v1/evolution/cases", json=body, headers=headers())


# ------------------------------------------------------------ 正常流程

def test_case_lifecycle_via_api(monkeypatch) -> None:
    service = _wire(monkeypatch, _service())

    created = _create({"expectation": None})
    assert created.status_code == 201
    case_id = created.json()["case_id"]
    assert created.json()["status"] == "draft"
    assert created.json()["source"] == "manual"

    # 查库：登记只落草稿（未发布不进评测）。
    assert service.get_case(main.UserContext(TENANT, ADMIN, "super_admin"), case_id).status.value == "draft"

    listed = client.get("/api/v1/evolution/cases", headers=headers(), params={"status": "draft"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1 and listed.json()["limit"] == 50

    fetched = client.get(f"/api/v1/evolution/cases/{case_id}", headers=headers())
    assert fetched.status_code == 200 and fetched.json()["case_id"] == case_id

    # 补全期望 → 发布（发布闸门：期望可执行）。
    filled = client.post(
        f"/api/v1/evolution/cases/{case_id}/expectation", json={"expectation": _expectation("blocked")}, headers=headers()
    )
    assert filled.status_code == 200
    published = client.post(f"/api/v1/evolution/cases/{case_id}/publish", headers=headers())
    assert published.status_code == 200 and published.json()["status"] == "published"

    # 替代：新条目为草稿，旧条目 archived 且链到新条目。
    superseded = client.post(
        f"/api/v1/evolution/cases/{case_id}/supersede",
        json={"input_snapshot": _snapshot("修订后的输入")},
        headers=headers(),
    )
    assert superseded.status_code == 200
    new_case = superseded.json()
    assert new_case["status"] == "draft" and new_case["case_id"] != case_id
    old = client.get(f"/api/v1/evolution/cases/{case_id}", headers=headers()).json()
    assert old["status"] == "archived" and old["superseded_by"] == new_case["case_id"]


def test_run_endpoints_are_read_only(monkeypatch) -> None:
    service = _wire(monkeypatch, _service())
    admin = main.UserContext(TENANT, ADMIN, "super_admin")
    service.import_cases(admin, regression_case_specs())
    run = service.run_eval(admin, subject_name="runtime-safety-probe", suite_key="runtime-safety")

    listed = client.get("/api/v1/evolution/eval-runs", headers=headers())
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1 and body["items"][0]["pass_count"] == 4

    detail = client.get(f"/api/v1/evolution/eval-runs/{run.eval_run_id}", headers=headers())
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["status"] == "completed"
    assert len(payload["results"]) == 4
    assert all(item["passed"] for item in payload["results"])
    assert set(payload["results"][0]["detail"]) <= {"status", "expect", "repeats", "failed_repeats"}


# ------------------------------------------------------------ 临界 / 异常与非法输入

def test_disabled_component_returns_503(monkeypatch) -> None:
    _wire(monkeypatch, None)
    assert client.get("/api/v1/evolution/cases", headers=headers()).status_code == 503
    assert _create().status_code == 503
    assert client.get("/api/v1/evolution/eval-runs", headers=headers()).status_code == 503


def test_non_admin_forbidden(monkeypatch) -> None:
    _wire(monkeypatch, _service())
    assert client.get("/api/v1/evolution/cases", headers=headers("employee", "acct-alice")).status_code == 403
    assert (
        client.post(
            "/api/v1/evolution/cases",
            json={"suite_key": "runtime-safety", "input_snapshot": _snapshot()},
            headers=headers("employee", "acct-alice"),
        ).status_code
        == 403
    )


def test_invalid_payloads_rejected(monkeypatch) -> None:
    _wire(monkeypatch, _service())
    # 未知字段（extra=forbid）
    assert _create({"unknown_field": 1}).status_code == 422
    # 非法来源
    assert _create({"source": "from_nowhere"}).status_code == 422
    # 快照含敏感键
    assert _create({"input_snapshot": {"prompt": "x", "api_key": "sk-x"}}).status_code == 422
    # 快照非对象
    assert _create({"input_snapshot": "not-a-dict"}).status_code == 422
    # 无期望发布 → 422（发布闸门）
    case_id = _create({"expectation": None, "input_snapshot": _snapshot("另一条")}).json()["case_id"]
    assert client.post(f"/api/v1/evolution/cases/{case_id}/publish", headers=headers()).status_code == 422
    # 分页参数边界
    assert client.get("/api/v1/evolution/cases", headers=headers(), params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/evolution/cases", headers=headers(), params={"limit": 500}).status_code == 422


def test_missing_case_returns_404(monkeypatch) -> None:
    _wire(monkeypatch, _service())
    assert client.get("/api/v1/evolution/cases/case-not-exists", headers=headers()).status_code == 404
    assert client.get("/api/v1/evolution/eval-runs/eval-not-exists", headers=headers()).status_code == 404


def test_archived_case_publish_conflict_409(monkeypatch) -> None:
    _wire(monkeypatch, _service())
    case_id = _create().json()["case_id"]
    assert client.post(f"/api/v1/evolution/cases/{case_id}/archive", headers=headers()).status_code == 200
    assert client.post(f"/api/v1/evolution/cases/{case_id}/publish", headers=headers()).status_code == 409