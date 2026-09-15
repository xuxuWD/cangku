"""P6a 自进化·评测集基础设施（规格 docs/superpowers/specs/2026-09-16-self-evolution-p6-design.md）。

边界：**P6a = 评测集基础设施与采集器**（用例库 + 离线评测运行器 + 回归锁定基线 + 采集器）。
候选生成 / 准入闸门 / 指针灰度 / 回滚属 **P6b**（须 D13 判据达标后开工），不在本包内。
"""

from .collector import collect_blocked_case_specs
from .models import (
    CaseSpec,
    EvalCase,
    EvalCaseNotFound,
    EvalCaseResult,
    EvalCaseSource,
    EvalCaseStateConflict,
    EvalCaseStatus,
    EvalCostExceeded,
    EvalDisabled,
    EvalError,
    EvalRun,
    EvalRunStatus,
    EvalSuiteEmpty,
    EvalSuiteTooLarge,
    InvalidEvalCase,
    UnknownEvalSubject,
    compute_input_digest,
    compute_suite_digest,
)
from .regression import REGRESSION_SUITE, regression_case_specs
from .runner import (
    DEFAULT_MAX_COST_CENTS,
    MAX_EVAL_CASES_PER_RUN,
    EvalRunner,
    EvalSubject,
    RuntimeSafetyProbeSubject,
    SubjectOutcome,
    build_builtin_subjects,
)
from .service import EvolutionService
from .store import EvalStore, InMemoryEvalStore, PostgresEvalStore

__all__ = [
    "CaseSpec",
    "DEFAULT_MAX_COST_CENTS",
    "EvalCase",
    "EvalCaseNotFound",
    "EvalCaseResult",
    "EvalCaseSource",
    "EvalCaseStateConflict",
    "EvalCaseStatus",
    "EvalCostExceeded",
    "EvalDisabled",
    "EvalError",
    "EvalRun",
    "EvalRunStatus",
    "EvalRunner",
    "EvalStore",
    "EvalSubject",
    "EvalSuiteEmpty",
    "EvalSuiteTooLarge",
    "EvolutionService",
    "InMemoryEvalStore",
    "InvalidEvalCase",
    "MAX_EVAL_CASES_PER_RUN",
    "PostgresEvalStore",
    "REGRESSION_SUITE",
    "RuntimeSafetyProbeSubject",
    "SubjectOutcome",
    "UnknownEvalSubject",
    "build_builtin_subjects",
    "collect_blocked_case_specs",
    "compute_input_digest",
    "compute_suite_digest",
    "regression_case_specs",
]