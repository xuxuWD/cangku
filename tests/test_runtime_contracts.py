import hashlib
import json
from datetime import UTC, datetime, timedelta

from app.runtime.contracts import (
    AgentPlan,
    AgentRuntimeAdapter,
    KnowledgeCitation,
    RuntimeContext,
    RuntimeEvent,
    RuntimeEventType,
    redact_payload,
)


def test_knowledge_citation_requires_the_public_reference_fields() -> None:
    citation = KnowledgeCitation(
        document_id="doc-1",
        knowledge_base_id="kb-1",
        title="设备维护手册",
        snippet="检查电源和散热。",
        score=0.92,
    )

    assert citation.document_id == "doc-1"
    assert citation.knowledge_base_id == "kb-1"
    assert citation.score == 0.92


def test_runtime_context_requires_scope_and_expiry() -> None:
    expires_at = datetime.now(UTC) + timedelta(minutes=5)
    context = RuntimeContext(
        tenant_id="tenant-1",
        user_id="user-1",
        role_key="ai-product-delivery",
        mode="product_manager",
        project_id="project-1",
        task_id="task-1",
        device_id="device-1",
        knowledge_scope=("kb-product",),
        file_scope=("D:/staging/project-1",),
        budget_cents=5000,
        risk_level="low",
        policy_version="policy-1",
        expires_at=expires_at,
    )
    assert context.is_valid_at(datetime.now(UTC))
    assert not context.is_valid_at(expires_at + timedelta(seconds=1))


def test_plan_marks_side_effects_as_approval_required() -> None:
    plan = AgentPlan.from_steps(
        [
            {"step_id": "s1", "kind": "read", "tool": "knowledge.search"},
            {"step_id": "s2", "kind": "write", "tool": "file.write"},
        ]
    )
    assert plan.steps[1].requires_approval is True
    assert plan.steps[0].requires_approval is False


def test_event_serialization_keeps_cursor_and_redacts_secrets() -> None:
    event = RuntimeEvent(
        run_id="run-1",
        sequence=3,
        event_type=RuntimeEventType.TOOL_RESULT,
        payload={"text": "ok", "api_key": "secret", "cookie": "session"},
    )
    data = event.to_public_dict()
    assert data["cursor"] == "run-1:3"
    assert data["payload"]["api_key"] == "[已隐藏]"
    assert data["payload"]["cookie"] == "[已隐藏]"


def test_event_serialization_redacts_common_credentials_case_insensitively_and_recursively() -> None:
    event = RuntimeEvent(
        run_id="run-1",
        sequence=4,
        event_type=RuntimeEventType.TOOL_RESULT,
        payload={
            "Authorization": "Bearer secret",
            "nested": {
                "ACCESS_TOKEN": "access-secret",
                "refresh_token": "refresh-secret",
                "Session": {"value": "session-secret"},
                "safe": "ok",
            },
        },
    )

    payload = event.to_public_dict()["payload"]
    assert payload["Authorization"] == "[已隐藏]"
    assert payload["nested"]["ACCESS_TOKEN"] == "[已隐藏]"
    assert payload["nested"]["refresh_token"] == "[已隐藏]"
    assert payload["nested"]["Session"] == "[已隐藏]"
    assert payload["nested"]["safe"] == "ok"


def test_adapter_protocol_exposes_lifecycle_methods() -> None:
    methods = {name for name in dir(AgentRuntimeAdapter) if not name.startswith("_")}
    assert {
        "start_run",
        "stream_events",
        "pause_run",
        "resume_run",
        "cancel_run",
        "request_approval",
        "get_checkpoint",
        "replay_run",
        "get_usage",
        "health",
    } <= methods


# ---------------------------------------------------------------------------
# 10.4 自查（2026-09-16）：redact_payload 的形态覆盖与掩码幂等
# 判据① 值的形态（不只看键名：工具标题 / 命令摘要 / 回复正文里可能带 key）；
# 判据② 掩码幂等（重复脱敏不改变 payload hash）。
# ---------------------------------------------------------------------------


def _payload_digest(payload: object) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_payload_redaction_covers_credentials_inside_free_text_values() -> None:
    """判据①值形态：键名不敏感时，值正文里的凭据也必须脱敏。"""
    payload = {
        "title": "curl -H 'Authorization: Bearer sk-live-abc123' https://api.example.com",
        "command": "export API_KEY=abc123 && ./run.sh",
        "reply": "你的 API key 是 sk-test-99887766，请保密",
        "text": '{"token": "user-token-xyz"}',
        "headers": "X-Api-Key: 12345",
    }

    out = redact_payload(json.loads(json.dumps(payload)))

    for leaked in ("sk-live-abc123", "abc123", "sk-test-99887766", "user-token-xyz", "12345"):
        assert leaked not in str(out), leaked
    assert out["title"].endswith("https://api.example.com")
    assert "Bearer [已隐藏]" in out["title"]
    assert "API_KEY=[已隐藏]" in out["command"]
    assert '"token": "[已隐藏]"' in out["text"]


def test_payload_redaction_normalizes_key_shapes() -> None:
    """判据①键名侧：camelCase / 连字符 / 头部风格键名与下划线小写同口径。"""
    payload = {
        "apiKey": "k-1",
        "X-Api-Key": "k-2",
        "authToken": "t-1",
        "api-key": "k-3",
        "clientSecret": "s-1",
    }

    out = redact_payload(json.loads(json.dumps(payload)))

    assert all(value == "[已隐藏]" for value in out.values())


def test_payload_redaction_does_not_touch_non_credential_key_shapes() -> None:
    """反误伤：`publicKey` / `sortKey` / `keyword` / 裸 `key` 不是凭据键（裸 key 单列不纳入判定）。"""
    payload = {
        "publicKey": "not-a-secret",
        "sortKey": "asc",
        "keyword": "search",
        "key": "plan-42",
    }

    assert redact_payload(json.loads(json.dumps(payload))) == payload


def test_payload_redaction_leaves_non_credential_text_untouched() -> None:
    """反误伤：正常文本（含 `risk-` / `maxfail=` / 路径 / 中文）不得被替换。"""
    payload = {
        "text": "检查电源和散热。",
        "path": "D:/staging/project-1/report.md",
        "command": "pytest -q --maxfail=1",
        "note": "risk-based keyword search",
        "budget_cents": 5000,
    }

    assert redact_payload(json.loads(json.dumps(payload))) == payload


def test_payload_redaction_is_idempotent_across_all_shapes() -> None:
    """判据②：重复脱敏逐字节一致且 payload hash 不变（键名 + 值形态混合样本）。"""
    payload = {
        "apiKey": "k-1",
        "Authorization": "Bearer sk-live-abc123",
        "nested": {"list": [{"token": "t"}, "command: export API_KEY=abc123"]},
        "title": "run with X-Api-Key: 12345",
    }

    once = redact_payload(json.loads(json.dumps(payload)))
    twice = redact_payload(json.loads(json.dumps(once)))

    assert twice == once
    assert _payload_digest(twice) == _payload_digest(once)


def test_payload_redaction_is_idempotent_on_already_masked_values() -> None:
    """判据②：已掩码内容（含从库里读出的旧事件）再脱敏不得改变。"""
    payload = {
        "Authorization": "[已隐藏]",
        "title": "Bearer [已隐藏]",
        "text": "token: [已隐藏]",
    }

    assert redact_payload(json.loads(json.dumps(payload))) == payload


def test_payload_redaction_documented_boundary_shell_short_option_not_covered() -> None:
    """已登记边界（10.4）：`-p<password>` 短选项形态不覆盖。

    覆盖它必然要匹配 `-p` 后跟任意串，会误伤 `-production` 之类正常参数 ⇒ 明确不做，
    此断言钉住该边界（若将来覆盖，此测试变红以提醒同步更新 10.4 结论）。
    """
    payload = {"command": "mysql -u root -ppassword123 -h db"}

    assert redact_payload(json.loads(json.dumps(payload))) == payload


def test_event_public_dict_redacts_value_shapes_end_to_end() -> None:
    """端到端：读取路径（`to_public_dict`）与持久化写入共用同一脱敏入口。"""
    event = RuntimeEvent(
        run_id="run-1",
        sequence=9,
        event_type=RuntimeEventType.TOOL_RESULT,
        payload={"title": "call with Authorization: Bearer sk-live-abc123"},
    )

    payload = event.to_public_dict()["payload"]

    assert "sk-live-abc123" not in str(payload)
    assert payload["title"].endswith("[已隐藏]")
