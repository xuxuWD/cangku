"""评测集服务层：用例治理（申领/补全期望/发布/归档/替代）+ 运行转发 + 审计。

口径见 `docs/superpowers/specs/2026-09-16-self-evolution-p6-design.md` §2.3/§2.5：
- 用例状态机 `draft → published → archived`；**已发布用例的变更走 supersede**（软链到新条目，不原地改）；
- **发布闸门 fail-closed**：期望必须可执行（受评对象已注册 + 输入形状可消费），空期望一律拒绝；
- 权限仅 `super_admin`；审计动作码 `evolution.case.changed` / `evolution.eval.completed`，**不记正文**。
"""

from __future__ import annotations

from typing import Sequence

from ..audit.models import AuditAction
from ..domain import UserContext
from .models import (
    CaseSpec,
    EvalCase,
    EvalCaseNotFound,
    EvalCaseResult,
    EvalCaseSource,
    EvalCaseStateConflict,
    EvalCaseStatus,
    EvalDisabled,
    EvalRun,
    InvalidEvalCase,
    compute_input_digest,
    ensure_can_manage,
    new_case_id,
    normalize_case_id,
    normalize_expectation,
    normalize_snapshot,
    normalize_source,
    normalize_suite_key,
)
from .runner import DEFAULT_MAX_COST_CENTS, EvalRunner, EvalSubject, build_builtin_subjects
from .store import EvalStore

# 已发布状态（替代链上允许被软链的源状态）。
_OPEN_STATUSES = (EvalCaseStatus.DRAFT, EvalCaseStatus.PUBLISHED)


class EvolutionService:
    """评测集治理入口；审计缺省跳过（audit=None），但生产装配必须注入（与记忆层同口径）。"""

    def __init__(
        self,
        store: EvalStore,
        *,
        subjects: dict[str, EvalSubject] | None = None,
        audit=None,
        enabled: bool = True,
        max_cost_cents: int = DEFAULT_MAX_COST_CENTS,
    ) -> None:
        self.store = store
        self.subjects = dict(subjects or build_builtin_subjects())
        self.audit = audit
        self.enabled = enabled
        self.runner = EvalRunner(
            store,
            subjects=self.subjects,
            audit=audit,
            enabled=enabled,
            max_cost_cents=max_cost_cents,
        )

    # ------------------------------------------------------------ 用例治理

    def create_case(
        self,
        context: UserContext,
        *,
        suite_key: str,
        input_snapshot: dict,
        source: str | EvalCaseSource = EvalCaseSource.MANUAL,
        expectation: dict | None = None,
    ) -> EvalCase:
        """登记用例（缺省为草稿；期望可后续用 `set_expectation` 补全）。"""
        self._guard(context)
        case, _created = self._create_one(
            context,
            suite_key=suite_key,
            source=source,
            input_snapshot=input_snapshot,
            expectation=expectation,
            case_id=None,
        )
        return case

    def set_expectation(self, context: UserContext, case_id: str, expectation: dict) -> EvalCase:
        """草稿用例原地补全期望（未发布即未生效）；已发布/已归档一律拒绝。"""
        self._guard(context)
        case = self.store.get_case(context, normalize_case_id(case_id))
        if case.status is not EvalCaseStatus.DRAFT:
            raise EvalCaseStateConflict("仅草稿用例可补全期望；已发布用例的变更请走替代（supersede）")
        clean = self._validate_expectation(expectation, case.input_snapshot)
        updated = self.store.set_case_expectation(
            context, case.case_id, expectation=clean, allowed_if=(EvalCaseStatus.DRAFT,)
        )
        if updated is None:
            raise EvalCaseStateConflict("用例状态已变化，补全期望未生效")
        self._audit_case(context, updated, reason=None)
        return updated

    def publish_case(self, context: UserContext, case_id: str) -> EvalCase:
        """发布用例（发布闸门：期望必须可执行）；重复发布幂等。"""
        self._guard(context)
        case = self.store.get_case(context, normalize_case_id(case_id))
        if case.status is EvalCaseStatus.PUBLISHED:
            return case  # 幂等
        if case.status is EvalCaseStatus.ARCHIVED:
            raise EvalCaseStateConflict("已归档用例不可发布")
        if not case.expectation:
            raise InvalidEvalCase("评测用例尚未标注期望，不可发布（fail-closed，不得默认为通过）")
        self._validate_expectation(case.expectation, case.input_snapshot)
        updated = self.store.set_case_status(
            context, case.case_id, new_status=EvalCaseStatus.PUBLISHED, allowed_if=(EvalCaseStatus.DRAFT,)
        )
        if updated is None:
            raise EvalCaseStateConflict("用例状态已变化，发布未生效")
        self._audit_case(context, updated, reason=None)
        return updated

    def archive_case(self, context: UserContext, case_id: str) -> EvalCase:
        """归档用例（软删，不物理删）；重复归档幂等。"""
        self._guard(context)
        case = self.store.get_case(context, normalize_case_id(case_id))
        if case.status is EvalCaseStatus.ARCHIVED:
            return case  # 幂等
        updated = self.store.set_case_status(
            context, case.case_id, new_status=EvalCaseStatus.ARCHIVED, allowed_if=_OPEN_STATUSES
        )
        if updated is None:
            raise EvalCaseStateConflict("用例状态已变化，归档未生效")
        self._audit_case(context, updated, reason=None)
        return updated

    def supersede_case(
        self,
        context: UserContext,
        case_id: str,
        *,
        input_snapshot: dict | None = None,
        expectation: dict | None = None,
    ) -> EvalCase:
        """用新用例替代旧用例：新条目为草稿（继承未变更的部分），旧条目 `archived + superseded_by`。"""
        self._guard(context)
        if input_snapshot is None and expectation is None:
            raise InvalidEvalCase("替代必须提供至少一项变更（input_snapshot 或 expectation）")
        old = self.store.get_case(context, normalize_case_id(case_id))
        if old.status is EvalCaseStatus.ARCHIVED:
            raise EvalCaseStateConflict("已归档用例不可再被替代")

        new_case, _created = self._create_one(
            context,
            suite_key=old.suite_key,
            source=old.source,
            input_snapshot=old.input_snapshot if input_snapshot is None else input_snapshot,
            expectation=old.expectation if expectation is None else expectation,
            case_id=None,
        )
        archived = self.store.set_case_status(
            context,
            old.case_id,
            new_status=EvalCaseStatus.ARCHIVED,
            allowed_if=_OPEN_STATUSES,
            superseded_by=new_case.case_id,
        )
        if archived is None:
            raise EvalCaseStateConflict("原用例状态已变化，替代未生效")
        self._audit_case(context, archived, reason="superseded")
        return new_case

    # ------------------------------------------------------------ 批量导入 / 采集落库

    def import_cases(
        self,
        context: UserContext,
        specs: Sequence[CaseSpec],
        *,
        publish: bool = True,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """批量登记（导入回归基线 / 采集落库），返回 (created, skipped)。

        幂等口径：显式 `case_id` 已存在 ⇒ 跳过；同套件**同名快照指纹**已存在 ⇒ 跳过
        （重复采集同一条运行轨迹不产生第二条用例）。**不覆盖既有用例的任何内容**。
        """
        self._guard(context)
        created: list[str] = []
        skipped: list[str] = []
        for spec in specs:
            normalized_suite = normalize_suite_key(spec.suite_key)
            snapshot = normalize_snapshot(spec.input_snapshot)
            digest = compute_input_digest(snapshot)
            if spec.case_id is not None:
                wanted_id = normalize_case_id(spec.case_id)
                try:
                    self.store.get_case(context, wanted_id)
                except EvalCaseNotFound:
                    pass
                else:
                    skipped.append(wanted_id)
                    continue
            else:
                wanted_id = None
            if self.store.find_case_by_digest(
                context, suite_key=normalized_suite, input_digest=digest
            ) is not None:
                skipped.append(wanted_id or f"digest:{digest[:12]}")
                continue
            case, was_created = self._create_one(
                context,
                suite_key=normalized_suite,
                source=spec.source,
                input_snapshot=snapshot,
                expectation=spec.expectation,
                case_id=wanted_id,
            )
            if not was_created:
                skipped.append(case.case_id)
                continue
            if publish:
                self.publish_case(context, case.case_id)
            created.append(case.case_id)
        return tuple(created), tuple(skipped)

    # ------------------------------------------------------------ 查询与运行转发

    def get_case(self, context: UserContext, case_id: str) -> EvalCase:
        self._guard(context)
        return self.store.get_case(context, normalize_case_id(case_id))

    def list_cases(self, context: UserContext, *, suite_key=None, status=None, source=None, limit: int = 50, offset: int = 0):
        self._guard(context)
        normalized_suite = normalize_suite_key(suite_key) if suite_key is not None else None
        return self.store.list_cases(
            context, suite_key=normalized_suite, status=status, source=source, limit=limit, offset=offset
        )

    def get_run(self, context: UserContext, eval_run_id: str) -> EvalRun:
        self._guard(context)
        return self.store.get_run(context, eval_run_id)

    def list_runs(self, context: UserContext, *, suite_key=None, limit: int = 50, offset: int = 0):
        self._guard(context)
        normalized_suite = normalize_suite_key(suite_key) if suite_key is not None else None
        return self.store.list_runs(context, suite_key=normalized_suite, limit=limit, offset=offset)

    def list_results(self, context: UserContext, eval_run_id: str) -> list[EvalCaseResult]:
        self._guard(context)
        return self.store.list_results(context, eval_run_id)

    def run_eval(self, context: UserContext, *, subject_name: str, suite_key: str, repeats: int = 1) -> EvalRun:
        """执行评测（转发运行器；离线语义——不在请求链路内自动触发）。"""
        return self.runner.run(
            context, subject_name=subject_name, suite_key=suite_key, repeats=repeats
        )

    # ------------------------------------------------------------ 内部

    def _guard(self, context: UserContext) -> None:
        ensure_can_manage(context)
        if not self.enabled:
            raise EvalDisabled("自进化评测组件未启用（WORKBENCH_EVOLUTION_ENABLED）")

    def _validate_expectation(self, value: object, snapshot: dict) -> dict:
        """期望校验 = 结构（键集/取值/对象已注册）+ 输入形状可被该受评对象消费（fail-closed）。"""
        clean = normalize_expectation(value, supported_probes=frozenset(self.subjects))
        subject = self.subjects[clean["probe"]]
        subject.validate_input(snapshot)
        return clean

    def _create_one(
        self,
        context: UserContext,
        *,
        suite_key: str,
        source: str | EvalCaseSource,
        input_snapshot: dict,
        expectation: dict | None,
        case_id: str | None,
    ) -> tuple[EvalCase, bool]:
        suite = normalize_suite_key(suite_key)
        src = normalize_source(source)
        snapshot = normalize_snapshot(input_snapshot)
        clean_expectation = (
            self._validate_expectation(expectation, snapshot) if expectation else {}
        )
        case = EvalCase(
            tenant_id=context.tenant_id,
            case_id=normalize_case_id(case_id) if case_id is not None else new_case_id(),
            suite_key=suite,
            source=src,
            status=EvalCaseStatus.DRAFT,
            input_snapshot=snapshot,
            input_digest=compute_input_digest(snapshot),
            expectation=clean_expectation,
            created_by=context.user_id,
        )
        saved, created = self.store.create_case(context, case)
        if created:
            self._audit_case(context, saved, reason=None)
        return saved, created

    def _audit_case(self, context: UserContext, case: EvalCase, *, reason: str | None) -> None:
        if self.audit is None:
            return
        detail: dict[str, object] = {
            "case_id": case.case_id,
            "status": case.status.value,
            "source_key": case.source.value,
        }
        if reason:
            detail["reason"] = reason
        self.audit.record(
            AuditAction.EVOLUTION_CASE_CHANGED,
            tenant_id=context.tenant_id,
            actor_id=context.user_id,
            target_type="eval_case",
            target_id=case.case_id,
            detail=detail,
        )