"""P2c-4 两个**只读候选端点**：`GET /api/v1/workforce/model-candidates` 与 `GET /api/v1/tools/catalog`。

口径（真源）：`docs/superpowers/specs/2026-09-17-frontend-interaction-p2c-design.md` §2.10（含实现期裁定，
**推翻契约 Y1**）与 `docs/api-contract.md`「模型 / 工具候选端点」。

关键断言（规格 §4「P2c-4 真库用例」⑤ 的接口层部分）：
  * 权限：仅 `super_admin`（`ceo` / `department_lead` / `employee` / `customer_admin` 一律 `403`；未认证 `401`）；
  * `model-candidates` 与员工配置的**保存闸门同源**（`registered_model_keys(settings)`）；候选为空时如实返回空列表；
  * `tools/catalog` 的 `items` = 执行工具目录（含风险档 / 是否需审批 / 参数与角色），
    `allowlist` = `tool_allowlist` 的**保存闸门集合**（`WORKBENCH_PLANNER_TOOLS`）——两者**如实分开**；
  * 响应**不含任何凭据 / 内部地址 / 提示词**（grep 断言）。
"""

from __future__ import annotations

import json
import types

import pytest
from fastapi.testclient import TestClient

from app import main
from app.bootstrap import registered_model_keys
from app.main import app

client = TestClient(app)
TENANT = "t-catalog"
PLANNER_TOOLS = '[{"name":"knowledge.search","kind":"read"},{"name":"content.publish","kind":"publish"}]'


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    fake = types.SimpleNamespace(
        # 认证依赖会读 `env`（非 development 时强制令牌校验），这里保持开发期头部身份语义。
        env="development",
        planner_backend="openai_compatible",
        planner_model_name="deepseek-chat",
        planner_tools=PLANNER_TOOLS,
    )
    monkeypatch.setattr(main, "settings", fake)
    return fake


def headers(role: str = "super_admin", user_id: str = "admin-1") -> dict[str, str]:
    return {"X-Tenant-Id": TENANT, "X-User-Id": user_id, "X-User-Role": role}


# ------------------------------------------------------------ 权限


def test_candidate_endpoints_require_authentication() -> None:
    for path in ("/api/v1/workforce/model-candidates", "/api/v1/tools/catalog"):
        assert client.get(path).status_code == 401


def test_candidate_endpoints_require_super_admin() -> None:
    for path in ("/api/v1/workforce/model-candidates", "/api/v1/tools/catalog"):
        for role in ("ceo", "department_lead", "employee", "customer_admin"):
            assert client.get(path, headers=headers(role)).status_code == 403, (path, role)


# ------------------------------------------------------------ 模型候选


def test_model_candidates_share_the_save_gate_source(_settings) -> None:
    response = client.get("/api/v1/workforce/model-candidates", headers=headers())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {"items": sorted(registered_model_keys(_settings)), "total": 1}
    assert body["items"] == ["deepseek-chat"]
    # 只读、无凭据 / 内部地址 / 提示词。
    text = json.dumps(body)
    assert "api_key" not in text and "base_url" not in text and "http" not in text


def test_model_candidates_report_empty_honestly(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "settings",
        types.SimpleNamespace(
            env="development", planner_backend="mock", planner_model_name="", planner_tools="[]"
        ),
    )
    body = client.get("/api/v1/workforce/model-candidates", headers=headers()).json()
    assert body == {"items": [], "total": 0}  # 本部署未注册模型键 ⇒ 如实为空，不摆假候选


# ------------------------------------------------------------ 工具目录


def test_tool_catalog_lists_execution_directory_and_save_gate(_settings) -> None:
    response = client.get("/api/v1/tools/catalog", headers=headers())
    assert response.status_code == 200, response.text
    body = response.json()
    items = {item["tool_key"]: item for item in body["items"]}
    # 执行目录实测 13 键（2026-09-17 P2c-4 实测：规格 §0 事实 8 起草期记的「16」为笔误，已回改）。
    assert body["total"] == len(items) == 13
    # 执行目录字段（来自 `ToolSpecCatalog`）：风险档 / 是否需审批 / 参数与角色。
    assert items["fs.read"]["risk_level"] == "low"
    assert items["fs.read"]["requires_approval"] is False
    assert items["fs.read"]["has_side_effect"] is False
    assert {"name": "path", "role": "control"} in items["fs.read"]["params"]
    assert items["cmd.run"]["risk_level"] == "medium" and items["cmd.run"]["requires_approval"] is False
    assert items["fs.write"]["requires_approval"] is True and items["fs.write"]["has_side_effect"] is True
    assert items["artifact.export"]["risk_level"] == "critical"
    # 保存闸门集合 = `WORKBENCH_PLANNER_TOOLS` 声明的键（与执行目录**不是同一批名字**）。
    assert body["allowlist"] == ["content.publish", "knowledge.search"]
    text = json.dumps(body)
    assert "api_key" not in text and "http" not in text and "system_prompt" not in text