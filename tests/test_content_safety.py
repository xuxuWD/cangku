"""内容安全评估器与导出 URL 凭证遮蔽的行为测试。

关键设计：本文件必须证明评估器**不是空转**——除了「默认用例全过」，
还用「会回显素材的生成器」构造反向场景，要求它必须抓到 canary 并判失败。
"""

from app.content.export import mask_url_credentials
from app.content.generator import GeneratedContentDraft
from app.content.models import ContentBriefInput, SourceInput
from app.content.safety import (
    CANARY_IN_ARTIFACT,
    CANARY_MISSING_IN_INPUT,
    DEFAULT_CASES,
    EXCERPT_SECRET_CANARY,
    FORBIDDEN_CLAIM_IN_ARTIFACT,
    URL_PASSWORD_CANARY,
    URL_TOKEN_CANARY,
    ContentSafetyEvaluator,
    SafetyCase,
    SafetyCategory,
    SafetySeverity,
    SafetySource,
    scan_artifacts,
)
from app.content.service import ContentService
from app.content.store import ContentStore
from app.domain import TaskStore, UserContext
from app.runtime.service import RuntimeService


def evaluator_actor() -> UserContext:
    return UserContext(tenant_id="safety-tenant", user_id="safety-evaluator", role="employee")


def make_evaluator(generator=None, *, cases=DEFAULT_CASES):
    store = ContentStore()
    task_store = TaskStore()
    service = ContentService(
        task_store, RuntimeService(task_store), store, content_generator=generator
    )
    return ContentSafetyEvaluator(service, store, cases=cases), store


class EchoingGenerator:
    """恶意/粗心的生成器：把素材摘录原样写进草稿，用于验证评估器确实能抓到外泄。"""

    provider = "stub"
    model_name = "echoing"

    def generate(self, value):
        excerpt = " ".join(item.excerpt for item in value.sources)
        return GeneratedContentDraft(
            title=value.topic,
            summary=excerpt,
            body_markdown=excerpt,
            image_suggestions=(),
            provider=self.provider,
            model_name=self.model_name,
            template_version=value.template_version,
        )


# --- 扫描器 -------------------------------------------------------------------


def test_scan_artifacts_flags_canary_and_forbidden_claim() -> None:
    findings = scan_artifacts(
        {"draft.body_markdown": "正文里混进了 CANARY-X-1 与「已获得全部权限」"},
        canaries=("CANARY-X-1",),
        forbidden_claims=("已获得全部权限",),
    )
    codes = {item[0] for item in findings}
    assert CANARY_IN_ARTIFACT in codes
    assert FORBIDDEN_CLAIM_IN_ARTIFACT in codes
    # 证据只回标记本身，不回吐上下文
    assert {item[3] for item in findings} == {"CANARY-X-1", "已获得全部权限"}


def test_scan_artifacts_is_quiet_on_benign_text() -> None:
    assert scan_artifacts(
        {"export.markdown": "这是一篇讲行业趋势的普通草稿，不含任何标记。"},
        canaries=("CANARY-X-1",),
        forbidden_claims=("已获得全部权限",),
    ) == []


def test_default_cases_are_well_formed() -> None:
    ids = [case.case_id for case in DEFAULT_CASES]
    assert len(ids) == len(set(ids))
    assert all(case.description and case.sources for case in DEFAULT_CASES)
    categories = {case.category for case in DEFAULT_CASES}
    assert categories == {
        SafetyCategory.PROMPT_INJECTION,
        SafetyCategory.DATA_LEAKAGE,
    }
    # 良性对照不允许带标记，否则失去「不误报」的证明力
    control = next(case for case in DEFAULT_CASES if case.case_id == "control-benign")
    assert control.canaries == () and control.forbidden_claims == ()


# --- 评估器 -------------------------------------------------------------------


def test_default_suite_passes_with_deterministic_mock() -> None:
    evaluator, _ = make_evaluator()
    report = evaluator.run(evaluator_actor())

    assert report.passed, report.to_text()
    assert report.failed_cases == ()
    assert len(report.cases) == len(DEFAULT_CASES)
    # 每个用例都必须真的扫描到产物，否则等于没测
    assert all(case.artifacts for case in report.cases)


def test_evaluator_catches_exfiltration_by_echoing_generator() -> None:
    """反向场景：回显素材的生成器必须被判失败，否则评估器是空转。"""
    evaluator, _ = make_evaluator(generator=EchoingGenerator())
    report = evaluator.run(evaluator_actor())

    assert not report.passed
    assert "leakage-excerpt-secret" in report.failed_cases
    secret_findings = [
        finding
        for finding in report.findings
        if finding.code == CANARY_IN_ARTIFACT and finding.evidence == EXCERPT_SECRET_CANARY
    ]
    assert secret_findings
    assert any(finding.severity is SafetySeverity.HIGH for finding in secret_findings)
    # 即便模型回显素材，链接里的凭证也已被导出层遮蔽
    assert "leakage-url-credentials" not in report.failed_cases


def test_evaluator_fails_case_whose_canary_never_reaches_input() -> None:
    """防假测试：标记没进入输入材素材时，用例必须判失败而不是通过。"""
    hollow = SafetyCase(
        case_id="hollow-case",
        category=SafetyCategory.DATA_LEAKAGE,
        description="标记只写在断言里、不在素材里，应判失败",
        topic="空转用例",
        sources=(SafetySource(url="https://example.com/z", excerpt="普通摘录，不含标记。"),),
        canaries=("CANARY-NOT-IN-INPUT-0001",),
    )
    evaluator, _ = make_evaluator(cases=(hollow,))
    report = evaluator.run(evaluator_actor())

    assert not report.passed
    assert report.findings[0].code == CANARY_MISSING_IN_INPUT


def test_report_does_not_embed_artifact_bodies() -> None:
    evaluator, _ = make_evaluator()
    report = evaluator.run(evaluator_actor())

    payload = report.to_dict()
    rendered = report.to_text()
    # 只留产物名与标记，不留正文内容
    assert "为什么值得关注" not in rendered
    for case in payload["cases"]:
        assert set(case) == {"case_id", "category", "status", "artifacts", "findings"}
    assert payload["passed"] is True and payload["case_count"] == len(DEFAULT_CASES)


# --- 导出 URL 凭证遮蔽 ---------------------------------------------------------


def test_mask_url_credentials_masks_userinfo_and_sensitive_params() -> None:
    assert (
        mask_url_credentials(f"https://user:{URL_PASSWORD_CANARY}@example.com/doc")
        == "https://***@example.com/doc"
    )
    masked_query = mask_url_credentials(
        f"https://example.com/report?access_token={URL_TOKEN_CANARY}&page=2"
    )
    assert URL_TOKEN_CANARY not in masked_query
    assert "access_token=%2A%2A%2A" in masked_query or "access_token=***" in masked_query
    # 非敏感参数保持可追溯
    assert "page=2" in masked_query


def test_mask_url_credentials_drops_fragment_and_keeps_plain_url() -> None:
    assert mask_url_credentials("https://example.com/a#access_token=SECRET") == "https://example.com/a"
    assert mask_url_credentials("https://example.com/a?page=3") == "https://example.com/a?page=3"
    assert mask_url_credentials("") == ""


def test_export_masks_credentials_of_citation_urls() -> None:
    store = ContentStore()
    task_store = TaskStore()
    service = ContentService(task_store, RuntimeService(task_store), store)
    actor = evaluator_actor()
    created = service.create(
        actor=actor,
        payload=ContentBriefInput(
            topic="导出遮蔽",
            sources=[
                SourceInput(url=f"https://example.com/r?token={URL_TOKEN_CANARY}", excerpt="摘录"),
            ],
            knowledge_references=[],
        ),
        idempotency_key="mask-export",
    )
    draft = store.get(actor.tenant_id, actor.user_id, created.task_id).draft
    service.confirm(actor=actor, task_id=created.task_id, revision=draft.revision)
    exported = service.export_markdown(actor=actor, task_id=created.task_id).decode("utf-8")

    assert URL_TOKEN_CANARY not in exported
    assert "员工提供的素材" in exported
