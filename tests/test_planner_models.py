import pytest

from app.planner.models import (
    PlanGenerationError,
    PlanProposal,
    PlanStatus,
    PlannerNotConfigured,
    Tool,
    ToolCatalog,
    UnknownTool,
    normalize_steps,
)


def catalog() -> ToolCatalog:
    return ToolCatalog(
        (
            Tool(name="knowledge.search", kind="read", description="只读知识检索"),
            Tool(name="content.publish", kind="publish", description="对外发布"),
        )
    )


def test_catalog_resolves_known_tool_and_rejects_unknown() -> None:
    instance = catalog()

    resolved = instance.resolve("knowledge.search")

    assert resolved.name == "knowledge.search"
    assert resolved.requires_approval is False
    with pytest.raises(UnknownTool):
        instance.resolve("shell.exec")


def test_side_effect_kinds_require_approval() -> None:
    assert Tool(name="a", kind="read").requires_approval is False
    for kind in ("write", "external_send", "publish", "delete", "permission"):
        assert Tool(name="a", kind=kind).requires_approval is True


def test_normalize_ignores_model_declared_kind_and_approval() -> None:
    raw = [
        {
            "step_id": "s1",
            "tool": "content.publish",
            "kind": "read",
            "requires_approval": False,
            "args": {"channel": "wechat"},
        }
    ]

    steps = normalize_steps(raw, catalog(), max_steps=5)

    assert steps[0].kind == "publish"
    assert steps[0].requires_approval is True


def test_normalize_rejects_unknown_tool_entirely() -> None:
    raw = [
        {"step_id": "s1", "tool": "knowledge.search"},
        {"step_id": "s2", "tool": "shell.exec"},
    ]

    with pytest.raises(UnknownTool):
        normalize_steps(raw, catalog(), max_steps=5)


def test_normalize_rejects_empty_oversized_and_duplicate_steps() -> None:
    with pytest.raises(PlanGenerationError, match="至少一个步骤"):
        normalize_steps([], catalog(), max_steps=5)

    too_many = [{"step_id": f"s{i}", "tool": "knowledge.search"} for i in range(3)]
    with pytest.raises(PlanGenerationError, match="超过上限"):
        normalize_steps(too_many, catalog(), max_steps=2)

    duplicated = [
        {"step_id": "s1", "tool": "knowledge.search"},
        {"step_id": "s1", "tool": "knowledge.search"},
    ]
    with pytest.raises(PlanGenerationError, match="重复"):
        normalize_steps(duplicated, catalog(), max_steps=5)


def test_normalize_rejects_bad_args_and_sensitive_keys() -> None:
    with pytest.raises(PlanGenerationError, match="args"):
        normalize_steps([{"step_id": "s1", "tool": "knowledge.search", "args": "text"}], catalog(), max_steps=5)

    with pytest.raises(PlanGenerationError, match="敏感"):
        normalize_steps(
            [{"step_id": "s1", "tool": "knowledge.search", "args": {"api_key": "x"}}],
            catalog(),
            max_steps=5,
        )


def test_normalize_rejects_missing_fields() -> None:
    with pytest.raises(PlanGenerationError, match="step_id"):
        normalize_steps([{"tool": "knowledge.search"}], catalog(), max_steps=5)
    with pytest.raises(PlanGenerationError, match="tool"):
        normalize_steps([{"step_id": "s1"}], catalog(), max_steps=5)


def test_empty_catalog_is_reported() -> None:
    assert ToolCatalog().is_empty() is True
    assert catalog().is_empty() is False
    with pytest.raises(PlannerNotConfigured):
        ToolCatalog().require_configured()


def test_catalog_from_config_parses_json_list() -> None:
    parsed = ToolCatalog.from_config('[{"name": "knowledge.search", "kind": "read"}]')

    assert parsed.names() == ("knowledge.search",)


def test_catalog_from_config_rejects_bad_shapes() -> None:
    for bad in ("", "not-json", "{}", '[{"name": "x"}]', '[{"name": "x", "kind": ""}]', '[1]'):
        with pytest.raises(ValueError, match="工具白名单"):
            ToolCatalog.from_config(bad)


def test_catalog_from_config_accepts_empty_values() -> None:
    assert ToolCatalog.from_config(None).is_empty() is True
    # 空串 "" 表示非法 JSON 形状（见 rejects_bad_shapes），此处用空列表表达"已配置但为空"。
    assert ToolCatalog.from_config([]).is_empty() is True
    assert ToolCatalog.from_config("[]").is_empty() is True


def test_proposal_defaults_to_pending_review() -> None:
    proposal = PlanProposal(
        task_id="task-1",
        tenant_id="t-1",
        goal="整理本周公众号选题",
        steps=(),
        generator_key="mock",
        generator_model=None,
        created_by="u-1",
        idempotency_key="id-1",
    )

    assert proposal.status is PlanStatus.PENDING_REVIEW
    assert proposal.proposal_id.startswith("plan-")
    assert proposal.reviewed_by is None
