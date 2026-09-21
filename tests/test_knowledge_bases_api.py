"""知识库候选清单 `GET /api/v1/knowledge/bases` 的接口级测试（第 15 轮）。

口径源：`docs/contracts/permissions-fake-entry-plan.md` §9（方案 B2′）+ `docs/api-contract.md`
「企业知识检索」节。该端点给「权限配置」页的编辑抽屉提供候选，取代原先"候选只能是现有绑定并集"。

本文件的用例就是**门禁锚点**（`docs/delivery-gates.md`）：

- 正常流程：清单取到 ⇒ `origin="upstream"`；名称缺失回落 `null`（界面显示标识）；本租户绑定里
  出现过、清单未返回的标识 ⇒ 合并为 `origin="binding_only"`（「配错 / 库已被删」的可见化）。
- 临界值：清单为空 / 绑定为空 / 两者皆空；**空结果必须带 `note`**（不得静默空）。
- 异常与非法输入：未配置 / 超时 / 非 2xx / `success:false` / 形状异常（`data` 非数组、元素缺 ID）
  ⇒ **一律降级**（`upstream_available=false` + `source="local_only"` + 绑定并集 + `note`），
  **不崩（不 500）、不臆测**；越权（非 `ceo`/`super_admin`）`403` 且**零上游请求**；匿名 `401`；跨租户不串。
- 安全：响应**不含** API Key / 上游主机名 / base_url；只发 `GET`。
- **未实调登记**：上游 `GET /api/v1/knowledge-bases` 的元素字段名未经实测确认（本机无可用上游实例）
  ⇒ 多键兼容解析由本文件钉死；该端点的实调状态见契约 §11「补验动作」。
- 反假锚点：见各用例 docstring（改坏对应实现必须变红）。
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.domain import UserContext
from app.knowledge import WeKnoraSearchRuntime
from app.knowledge_policy import KnowledgeAccessRegistry

client = TestClient(main.app)

TENANT = "t-bases"
ADMIN = "acct-admin"
ROLE_KEY = "content-operator"
KB_UPSTREAM = "kb-00000001"
KB_BOUND_ONLY = "kb-legacy-x"

MANAGE_ROLES = ("ceo", "super_admin")
DENIED_ROLES = ("employee", "department_lead", "customer_admin")


def headers(role: str = "super_admin", user_id: str = ADMIN, tenant_id: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def _admin() -> UserContext:
    return UserContext(TENANT, ADMIN, "super_admin")


class _Upstream:
    """假 WeKnora（httpx.MockTransport）：记录 `(方法, 路径)` 与请求头，可配置清单与失败模式。"""

    def __init__(
        self,
        *,
        data: object = None,
        status: int = 200,
        success: bool = True,
        timeout: bool = False,
    ) -> None:
        self.data = [] if data is None else data
        self.status = status
        self.success = success
        self.timeout = timeout
        self.requests: list[tuple[str, str]] = []
        self.headers: list[dict[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        self.headers.append(dict(request.headers))
        if self.timeout:
            raise httpx.TimeoutException("upstream timeout", request=request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "boom"})
        return httpx.Response(200, json={"success": self.success, "data": self.data})

    def runtime(self) -> WeKnoraSearchRuntime:
        return WeKnoraSearchRuntime(
            client=httpx.Client(transport=httpx.MockTransport(self.handler)),
            base_url="https://weknora.internal",
            api_key="sk-test-key",
            timeout=5.0,
        )


@pytest.fixture()
def registry() -> KnowledgeAccessRegistry:
    return KnowledgeAccessRegistry()


def _wire(monkeypatch, *, registry: KnowledgeAccessRegistry, upstream: _Upstream | None = None) -> _Upstream:
    """按既有 `_isolate` 范式替换模块级装配（端点每次请求重新读取这些全局）。"""
    upstream = upstream or _Upstream()
    monkeypatch.setattr(main, "knowledge_access_registry", registry)
    monkeypatch.setattr(main, "weknora_search_runtime", upstream.runtime())
    return upstream


def _bind(registry: KnowledgeAccessRegistry, *ids: str, role_key: str = ROLE_KEY) -> None:
    registry.bind_role(_admin(), role_key, set(ids))


def _get(**kwargs) -> httpx.Response:
    return client.get("/api/v1/knowledge/bases", headers=kwargs.pop("headers", headers()))


# ------------------------------------------------------------ 正常流程


def test_upstream_available_returns_upstream_items(monkeypatch, registry) -> None:
    """清单取到 ⇒ `origin="upstream"`、`source="upstream"`、`note=None`，且只发 GET。

    反假锚点：把降级判定写成"永远降级"（或漏掉 `upstream_available=True`）⇒ 本用例必红。
    """
    upstream = _wire(
        monkeypatch,
        registry=registry,
        upstream=_Upstream(
            data=[
                {"id": KB_UPSTREAM, "name": "运维手册"},
                {"id": "kb-00000002", "name": "品牌素材"},
            ]
        ),
    )

    response = _get()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["upstream_available"] is True
    assert body["source"] == "upstream"
    assert body["note"] is None
    assert body["items"] == [
        {"knowledge_base_id": KB_UPSTREAM, "name": "运维手册", "origin": "upstream"},
        {"knowledge_base_id": "kb-00000002", "name": "品牌素材", "origin": "upstream"},
    ]
    assert upstream.requests == [("GET", "/api/v1/knowledge-bases")]  # 只读：只发 GET
    assert upstream.headers[0].get("x-api-key") == "sk-test-key"  # 复用既有鉴权头


def test_bound_but_missing_upstream_id_merged_as_binding_only(monkeypatch, registry) -> None:
    """本租户绑定过、但清单未返回的标识 ⇒ 合并为 `origin="binding_only"`。

    反假锚点（反假组 2）：删掉 binding_only 合并 ⇒ 本用例必红。
    这条正是「标识配错 / 库已被删」的**可见化**：不合并就等于把它藏起来。
    """
    _bind(registry, KB_UPSTREAM, KB_BOUND_ONLY)
    _wire(
        monkeypatch,
        registry=registry,
        upstream=_Upstream(data=[{"id": KB_UPSTREAM, "name": "运维手册"}]),
    )

    response = _get()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["upstream_available"] is True and body["source"] == "upstream"
    assert body["items"] == [
        {"knowledge_base_id": KB_UPSTREAM, "name": "运维手册", "origin": "upstream"},
        {"knowledge_base_id": KB_BOUND_ONLY, "name": None, "origin": "binding_only"},
    ]


def test_upstream_available_but_empty_list_is_not_silent(monkeypatch, registry) -> None:
    """清单取到但为空、且本租户无绑定 ⇒ `items` 空 **且 `note` 说明原因**（不得静默空）。"""
    _wire(monkeypatch, registry=registry, upstream=_Upstream(data=[]))

    response = _get()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["upstream_available"] is True
    assert body["items"] == []
    assert isinstance(body["note"], str) and body["note"]


# ------------------------------------------------------------ 多键兼容（未实调口径）


@pytest.mark.parametrize(
    "item",
    [
        {"id": "kb-1", "name": "用 id"},
        {"knowledge_base_id": "kb-1", "name": "用 knowledge_base_id"},
        {"kb_id": "kb-1", "name": "用 kb_id"},
        {"id": "kb-1", "title": "用 title 当名称"},
    ],
)
def test_element_key_compatibility(monkeypatch, registry, item) -> None:
    """元素标识键 `id` / `knowledge_base_id` / `kb_id`，名称键 `name` / `title` 都要认。

    依据：上游元素字段名**未经实调确认**（契约 §7.2）⇒ 不假定单一形状。
    """
    _wire(monkeypatch, registry=registry, upstream=_Upstream(data=[item]))

    response = _get()

    assert response.status_code == 200, response.text
    assert response.json()["items"] == [
        {"knowledge_base_id": "kb-1", "name": item.get("name") or item.get("title"), "origin": "upstream"}
    ]


def test_missing_name_falls_back_to_null(monkeypatch, registry) -> None:
    """清单元素没有名称 ⇒ `name=null`（**不编造**名称；界面回落显示标识）。"""
    _wire(monkeypatch, registry=registry, upstream=_Upstream(data=[{"id": "kb-1"}]))

    response = _get()

    assert response.json()["items"][0]["name"] is None


# ------------------------------------------------------------ 降级（无谎报）


@pytest.mark.parametrize(
    "upstream_factory, reason_word",
    [
        (lambda: None, "未配置"),
        (lambda: _Upstream(timeout=True), "超时"),
        (lambda: _Upstream(status=500), "暂不可用"),
        (lambda: _Upstream(success=False), "暂不可用"),
        (lambda: _Upstream(data={"items": []}), "无法识别"),
        (lambda: _Upstream(data=[{"name": "没有标识"}]), "无法识别"),
        (lambda: _Upstream(data=["不是对象"]), "无法识别"),
    ],
    ids=["unconfigured", "timeout", "http500", "success-false", "data-not-list", "item-without-id", "item-not-dict"],
)
def test_degrade_returns_bound_ids_with_note(monkeypatch, registry, upstream_factory, reason_word) -> None:
    """未配置 / 超时 / 非 2xx / `success:false` / 形状异常 ⇒ **降级**，绝不冒充「没有知识库」。

    降级的四要件（缺一即红）：`upstream_available=false` + `source="local_only"` +
    `items` = 本租户绑定并集（`origin="binding_only"`）+ `note` 含可读原因；
    且**不崩**（不返回 5xx —— 界面要的是"取不到，请手动输入"而不是"服务坏了"）。

    反假锚点（反假组 1）：把降级写成"返回空列表"⇒ 本用例必红。
    """
    _bind(registry, KB_UPSTREAM, KB_BOUND_ONLY)
    upstream = upstream_factory()
    if upstream is None:
        monkeypatch.setattr(main, "knowledge_access_registry", registry)
        monkeypatch.setattr(main, "weknora_search_runtime", None)
    else:
        _wire(monkeypatch, registry=registry, upstream=upstream)

    response = _get()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["upstream_available"] is False
    assert body["source"] == "local_only"
    assert body["items"] == [
        {"knowledge_base_id": KB_UPSTREAM, "name": None, "origin": "binding_only"},
        {"knowledge_base_id": KB_BOUND_ONLY, "name": None, "origin": "binding_only"},
    ]
    assert isinstance(body["note"], str) and reason_word in body["note"]


def test_degrade_without_binding_is_empty_but_explained(monkeypatch, registry) -> None:
    """降级 + 本租户从未绑定过 ⇒ `items` 空，但 `note` 仍在（说明"取不到"而非"没有"）。"""
    monkeypatch.setattr(main, "knowledge_access_registry", registry)
    monkeypatch.setattr(main, "weknora_search_runtime", None)

    response = _get()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["upstream_available"] is False
    assert isinstance(body["note"], str) and body["note"]


# ------------------------------------------------------------ 异常与非法输入


@pytest.mark.parametrize("role", MANAGE_ROLES)
def test_manage_roles_allowed(monkeypatch, registry, role) -> None:
    """矩阵 §3「知识：授权绑定」行：`ceo` 与 `super_admin` 均可读候选清单。"""
    upstream = _wire(monkeypatch, registry=registry, upstream=_Upstream(data=[{"id": KB_UPSTREAM, "name": "x"}]))

    response = _get(headers=headers(role=role, user_id=f"acct-{role}"))

    assert response.status_code == 200, response.text
    assert len(upstream.requests) == 1


@pytest.mark.parametrize("role", DENIED_ROLES)
def test_other_roles_forbidden_without_upstream_call(monkeypatch, registry, role) -> None:
    """其余角色 `403`，且**零上游请求**（`403` 在任何上游动作之前判定，不泄露上游存在性）。"""
    upstream = _wire(monkeypatch, registry=registry)

    response = _get(headers=headers(role=role, user_id=f"acct-{role}"))

    assert response.status_code == 403, response.text
    assert upstream.requests == []


def test_missing_identity_401(monkeypatch, registry) -> None:
    """无身份 ⇒ 401（不进入任何业务分支）。"""
    upstream = _wire(monkeypatch, registry=registry)

    assert client.get("/api/v1/knowledge/bases").status_code == 401
    assert upstream.requests == []


def test_cross_tenant_bindings_are_not_returned(monkeypatch, registry) -> None:
    """跨租户：绑定在 `t-bases` 下，换租户请求时**既不进 upstream 也不进 binding_only**。"""
    _bind(registry, KB_BOUND_ONLY)
    _wire(monkeypatch, registry=registry, upstream=_Upstream(data=[{"id": KB_UPSTREAM, "name": "x"}]))

    response = _get(headers=headers(tenant_id="t-other"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["knowledge_base_id"] for item in body["items"]] == [KB_UPSTREAM]
    assert all(item["origin"] == "upstream" for item in body["items"])


# ------------------------------------------------------------ 安全（不泄露）


def test_response_never_leaks_key_or_upstream_host(monkeypatch, registry) -> None:
    """响应体**不含** API Key、上游主机名、base_url（上游失败原文只进日志）。"""
    _bind(registry, KB_BOUND_ONLY)
    _wire(monkeypatch, registry=registry, upstream=_Upstream(status=500))

    degraded = _get()
    assert degraded.status_code == 200
    for secret in ("sk-test-key", "weknora.internal", "https://"):
        assert secret not in degraded.text

    _wire(monkeypatch, registry=registry, upstream=_Upstream(data=[{"id": KB_UPSTREAM, "name": "x"}]))
    available = _get()
    for secret in ("sk-test-key", "weknora.internal", "https://"):
        assert secret not in available.text


def test_response_shape_is_exactly_the_contract(monkeypatch, registry) -> None:
    """响应的键**恰好**是契约的四个（`upstream_available` / `source` / `items` / `note`）。"""
    _wire(monkeypatch, registry=registry, upstream=_Upstream(data=[{"id": KB_UPSTREAM, "name": "x"}]))

    body = _get().json()

    assert set(body) == {"upstream_available", "source", "items", "note"}
    assert set(body["items"][0]) == {"knowledge_base_id", "name", "origin"}