"""受评对象（subject）与离线评测运行器（P6a 规格 §2.3 / §3 V2）。

- **受评对象**是可插拔的评测目标：v1 内置 `runtime-safety-probe`（**复用**既有
  `app/runtime/evaluation.py` 的最小断言，确定性判定、零模型费用）；P6b 的「候选技能」将
  以 subject 值的形式接入（如 `skill:<key>@<version>`），**不改变本运行器的接口**。
- **运行器**按套件执行已发布用例：记录 `suite_digest`（当次考了什么）、最差一次计入（repeats）、
  费用上限 fail-closed（超限中止但**留痕**：aborted 运行 + 审计）。
- 明细只落判定与计数（`detail`），**不落正文**。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..audit.models import AuditAction
from ..domain import UserContext
from .models import (
    EvalCase,
    EvalCaseResult,
    EvalCaseStatus,
    EvalCostExceeded,
    EvalDisabled,
    EvalRun,
    EvalRunStatus,
    EvalSuiteEmpty,
    EvalSuiteTooLarge,
    InvalidEvalCase,
    UnknownEvalSubject,
    compute_suite_digest,
    ensure_can_manage,
    new_eval_run_id,
    normalize_suite_key,
)
from .store import EvalStore

# 单次运行的用例数上限（自设上界，防跑飞；超出即显式失败，不静默截断）。
MAX_EVAL_CASES_PER_RUN = 200
# 重复次数上限（抑制抖动用；1 = 单次判定）。
MAX_REPEATS = 10
# 评测费用默认上限（整数分；v1 内置探针为 0，接入模型类受评对象后由配置收紧）。
DEFAULT_MAX_COST_CENTS = 500


@dataclass(frozen=True)
class SubjectOutcome:
    """受评对象对单个用例的判定结果；`detail` 只放受控短值（判定与计数）。"""

    ok: bool
    detail: dict


class EvalSubject(Protocol):
    """受评对象契约：注册名 + 单例费用 + 输入校验 + 判定。"""

    name: str
    cost_cents_per_case: int

    def validate_input(self, snapshot: dict) -> None: ...

    def evaluate(self, case: EvalCase) -> SubjectOutcome: ...


class RuntimeSafetyProbeSubject:
    """运行时安全探针：复用既有 `EvaluationRunner`（注入 / 密钥两类筛查 + 良性对照）。

    期望取值：`pass`（未命中任何风险判定）或 `blocked`（命中 ⇒ 应拦）。判定完全确定性，
    因此费用恒为 0，且同一用例重复运行结果稳定（抖动只可能来自未来的模型类受评对象）。
    """

    name = "runtime-safety-probe"
    cost_cents_per_case = 0

    def __init__(self) -> None:
        from ..runtime.evaluation import EvaluationRunner

        self._probe = EvaluationRunner()

    def validate_input(self, snapshot: dict) -> None:
        if not isinstance(snapshot, dict):
            raise InvalidEvalCase("runtime-safety 用例的快照必须是对象")
        prompt = snapshot.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise InvalidEvalCase("runtime-safety 用例必须提供非空 prompt")
        logs = snapshot.get("logs", [])
        if not isinstance(logs, list) or any(not isinstance(item, str) for item in logs):
            raise InvalidEvalCase("runtime-safety 用例的 logs 必须是字符串数组")

    def evaluate(self, case: EvalCase) -> SubjectOutcome:
        snapshot = case.input_snapshot
        result = self._probe.evaluate(
            {
                "prompt": str(snapshot.get("prompt", "")),
                "logs": [str(item) for item in (snapshot.get("logs") or [])],
            }
        )
        status = str(result.get("status"))
        expected = str(case.expectation.get("expect"))
        return SubjectOutcome(ok=status == expected, detail={"status": status, "expect": expected})


def build_builtin_subjects() -> dict[str, EvalSubject]:
    """内置受评对象注册表（v1 仅运行时安全探针）。"""
    subject = RuntimeSafetyProbeSubject()
    return {subject.name: subject}


class EvalRunner:
    """离线评测运行器（**不在请求链路内执行**；由 CLI / 管理动作触发）。"""

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
        self.max_cost_cents = max_cost_cents

    def run(
        self,
        context: UserContext,
        *,
        subject_name: str,
        suite_key: str,
        repeats: int = 1,
    ) -> EvalRun:
        """执行一个套件：逐例判定 → 运行与逐例结果落库 → 审计。"""
        ensure_can_manage(context)
        if not self.enabled:
            raise EvalDisabled("自进化评测组件未启用（WORKBENCH_EVOLUTION_ENABLED）")
        if isinstance(repeats, bool) or not isinstance(repeats, int) or not 1 <= repeats <= MAX_REPEATS:
            raise InvalidEvalCase(f"repeats 必须是 1–{MAX_REPEATS} 的整数")
        suite = normalize_suite_key(suite_key)
        subject = self.subjects.get(subject_name)
        if subject is None:
            raise UnknownEvalSubject(
                f"受评对象未注册：{subject_name}（当前：{sorted(self.subjects)}）"
            )

        cases, total = self.store.list_cases(
            context, suite_key=suite, status=EvalCaseStatus.PUBLISHED, limit=MAX_EVAL_CASES_PER_RUN + 1
        )
        if total == 0 or not cases:
            raise EvalSuiteEmpty(
                f"套件 {suite} 没有已发布的评测用例——fail-closed 拒绝执行（不得默认为通过）"
            )
        if total > MAX_EVAL_CASES_PER_RUN:
            raise EvalSuiteTooLarge(
                f"套件 {suite} 有 {total} 条已发布用例，超过单次运行上限 {MAX_EVAL_CASES_PER_RUN}——"
                "为避免只评一部分已中止（请拆分套件）"
            )

        digest = compute_suite_digest(cases)
        planned_cost = int(getattr(subject, "cost_cents_per_case", 0)) * len(cases) * repeats
        if planned_cost > self.max_cost_cents:
            aborted = self.store.create_run(
                context,
                EvalRun(
                    tenant_id=context.tenant_id,
                    eval_run_id=new_eval_run_id(),
                    subject=subject_name,
                    suite_key=suite,
                    suite_digest=digest,
                    case_count=0,
                    pass_count=0,
                    cost_cents=0,
                    status=EvalRunStatus.ABORTED,
                    created_by=context.user_id,
                ),
            )
            self._record(context, aborted, reason="cost_exceeded")
            raise EvalCostExceeded(
                f"评测费用预计 {planned_cost} 分，超过上限 {self.max_cost_cents} 分——已中止（fail-closed）"
            )

        evaluated: list[tuple[EvalCase, bool, dict]] = []
        for case in cases:
            outcomes = [subject.evaluate(case) for _ in range(repeats)]
            failures = [item for item in outcomes if not item.ok]
            detail = dict(outcomes[-1].detail)
            detail["repeats"] = repeats
            detail["failed_repeats"] = len(failures)
            evaluated.append((case, not failures, detail))

        run = self.store.create_run(
            context,
            EvalRun(
                tenant_id=context.tenant_id,
                eval_run_id=new_eval_run_id(),
                subject=subject_name,
                suite_key=suite,
                suite_digest=digest,
                case_count=len(cases),
                pass_count=sum(1 for _case, passed, _detail in evaluated if passed),
                cost_cents=planned_cost,
                status=EvalRunStatus.COMPLETED,
                created_by=context.user_id,
            ),
        )
        for case, passed, detail in evaluated:
            self.store.record_result(
                context,
                EvalCaseResult(
                    tenant_id=context.tenant_id,
                    eval_run_id=run.eval_run_id,
                    case_id=case.case_id,
                    passed=passed,
                    detail=detail,
                ),
            )
        self._record(context, run, reason=None)
        return run

    def _record(self, context: UserContext, run: EvalRun, *, reason: str | None) -> None:
        if self.audit is None:
            return
        detail: dict[str, object] = {
            "eval_run_id": run.eval_run_id,
            "status": run.status.value,
            "case_count": run.case_count,
            "pass_count": run.pass_count,
            "suite_digest": run.suite_digest,
        }
        if reason:
            detail["reason"] = reason
        self.audit.record(
            AuditAction.EVOLUTION_EVAL_COMPLETED,
            tenant_id=context.tenant_id,
            actor_id=context.user_id,
            target_type="eval_run",
            target_id=run.eval_run_id,
            detail=detail,
        )