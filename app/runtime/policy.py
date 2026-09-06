from __future__ import annotations

from dataclasses import dataclass
from pathlib import PureWindowsPath

from .contracts import RuntimeContext


class PolicyDenied(ValueError):
    pass


class ApprovalRequired(PolicyDenied):
    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__(f"动作需要人工审批: {action}")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    approval_required: bool
    reason: str
    policy_version: str


class RuntimePolicy:
    def __init__(self, policy_version: str) -> None:
        self.policy_version = policy_version

    @staticmethod
    def _inside(path: str, roots: tuple[str, ...]) -> bool:
        try:
            candidate = PureWindowsPath(path)
            return any(candidate == root or root in candidate.parents for root in (PureWindowsPath(item) for item in roots))
        except (TypeError, ValueError):
            return False

    def check(self, context: RuntimeContext, action: str, *, path: str | None = None, cost_cents: int = 0) -> Decision:
        if not context.is_valid_at(__import__('datetime').datetime.now(__import__('datetime').UTC)):
            raise PolicyDenied("运行授权已过期")
        if context.policy_version != self.policy_version:
            raise PolicyDenied("策略版本不匹配")
        if cost_cents < 0 or cost_cents > context.budget_cents:
            raise PolicyDenied("动作超出本次任务预算")
        if context.mode == "product_manager":
            allowed = {"knowledge.search", "plan.create", "plan.read"}
            if action not in allowed:
                raise PolicyDenied(f"产品经理模式不允许动作: {action}")
        elif context.mode == "fde":
            if action in {"file.read", "workspace.check"}:
                if not path or not self._inside(path, context.file_scope):
                    raise PolicyDenied("文件不在本次任务授权范围内")
            elif action in {"file.write", "external.send", "external.publish", "delete", "permission.change", "production.workflow.update"}:
                raise ApprovalRequired(action)
            else:
                raise PolicyDenied(f"FDE 模式未登记动作: {action}")
        else:
            raise PolicyDenied("未知工作模式")
        return Decision(True, False, "动作符合岗位与任务策略", self.policy_version)
