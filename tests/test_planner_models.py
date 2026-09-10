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


def test_catalog_rejects_unknown_or_miscased_kind() -> None:
    for bad_kind in ("publsh", "READ", "readonly", "admin", "execute"):
        with pytest.raises(ValueError, match="kind"):
            ToolCatalog((Tool(name="content.publish", kind=bad_kind),))


def test_tool_rejects_unknown_kind_when_constructed_directly() -> None:
    with pytest.raises(ValueError, match="kind"):
        Tool(name="content.publish", kind="publsh")
    with pytest.raises(ValueError, match="工具名"):
        Tool(name="   ", kind="read")


def test_catalog_rejects_duplicate_tool_names() -> None:
    with pytest.raises(ValueError, match="重复"):
        ToolCatalog(
            (
                Tool(name="content.publish", kind="publish"),
                Tool(name="content.publish", kind="read"),
            )
        )


def test_normalize_rejects_compound_and_nested_sensitive_keys() -> None:
    for sensitive in (
        {"client_secret": "x"},
        {"secret_key": "x"},
        {"private_key": "x"},
        {"passwd": "x"},
        {"pwd": "x"},
        {"x-api-key": "x"},
        {"bearer": "x"},
        {"credential": "x"},
        {"headers": {"Authorization": "SECRET"}},
    ):
        with pytest.raises(PlanGenerationError, match="敏感"):
            normalize_steps(
                [{"step_id": "s1", "tool": "knowledge.search", "args": sensitive}],
                catalog(),
                max_steps=5,
            )


def test_normalize_allows_benign_keys_containing_key_substring() -> None:
    steps = normalize_steps(
        [{"step_id": "s1", "tool": "knowledge.search", "args": {"keyword": "选题", "topic": "内容"}}],
        catalog(),
        max_steps=5,
    )

    assert steps[0].args == {"keyword": "选题", "topic": "内容"}


def test_normalize_rejects_camel_case_sensitive_keys() -> None:
    for sensitive in (
        {"apiKey": "x"},
        {"myToken": "x"},
        {"accessToken": "x"},
        {"clientSecret": "x"},
        {"api_keyValue": "x"},
        {"userToken": "x"},
        {"nested": {"accessToken": "x"}},
    ):
        with pytest.raises(PlanGenerationError, match="敏感"):
            normalize_steps(
                [{"step_id": "s1", "tool": "knowledge.search", "args": sensitive}],
                catalog(),
                max_steps=5,
            )


def test_normalize_allows_benign_camel_case_keys() -> None:
    steps = normalize_steps(
        [{"step_id": "s1", "tool": "knowledge.search", "args": {"keyword": "a", "topicName": "b"}}],
        catalog(),
        max_steps=5,
    )

    assert steps[0].args == {"keyword": "a", "topicName": "b"}
