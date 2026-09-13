"""容器执行器：**只做接口 + 参数装配**。

把配置映射为容器参数（`exec_pids_limit` → `--pids-limit`、`exec_memory_mb` → `--memory`、
`exec_cpu_quota` → `--cpus`、`exec_image_digest` → 镜像引用、`exec_timeout_seconds` → 执行侧硬上限）。

**真实 docker 调用不在本步骤范围**——属 §4.1.6-4 的 ⑧（段二-3）；`execute()` 显式抛
`NotImplementedError`，避免被误当作"已能执行"。容器的其余加固项（只读根、`nosuid,nodev,noexec`、
`--cap-drop ALL`、`--network internal` 等，§3.3）一并留待该步骤。
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ToolExecutionConfigError


@dataclass(frozen=True)
class ContainerSpec:
    """一次容器执行的参数装配结果（供后续 ⑧ 使用；本步骤不调用 docker）。"""

    image: str
    pids_limit: int
    memory_mb: int
    cpus: float
    timeout_seconds: int
    workspace_mount: str = "/workspace"

    def docker_args(self, workspace_path: str) -> list[str]:
        return [
            "run",
            "--rm",
            "--pids-limit",
            str(self.pids_limit),
            "--memory",
            f"{self.memory_mb}m",
            "--cpus",
            str(self.cpus),
            "-v",
            f"{workspace_path}:{self.workspace_mount}",
            self.image,
        ]


class ContainerExecutor:
    """容器执行器接口 + 参数装配；真实执行留待后续步骤。"""

    def __init__(
        self,
        *,
        image_digest: str,
        pids_limit: int,
        memory_mb: int,
        cpu_quota: float,
        timeout_seconds: int,
        workspace_mount: str = "/workspace",
    ) -> None:
        if not isinstance(image_digest, str) or not image_digest.strip():
            raise ToolExecutionConfigError(
                "未配置执行镜像 digest WORKBENCH_EXEC_IMAGE_DIGEST，拒绝启用真实执行"
            )
        if pids_limit < 1 or memory_mb < 1 or cpu_quota <= 0 or timeout_seconds < 1:
            raise ToolExecutionConfigError("容器资源参数非法")
        self.image_digest = image_digest
        self.pids_limit = pids_limit
        self.memory_mb = memory_mb
        self.cpu_quota = cpu_quota
        self.timeout_seconds = timeout_seconds
        self.workspace_mount = workspace_mount

    @classmethod
    def from_settings(cls, settings) -> "ContainerExecutor":
        return cls(
            image_digest=settings.exec_image_digest,
            pids_limit=settings.exec_pids_limit,
            memory_mb=settings.exec_memory_mb,
            cpu_quota=settings.exec_cpu_quota,
            timeout_seconds=settings.exec_timeout_seconds,
        )

    def build_spec(self) -> ContainerSpec:
        return ContainerSpec(
            image=self.image_digest,
            pids_limit=self.pids_limit,
            memory_mb=self.memory_mb,
            cpus=self.cpu_quota,
            timeout_seconds=self.timeout_seconds,
            workspace_mount=self.workspace_mount,
        )

    def execute(self, spec: ContainerSpec, *, workspace_path: str):
        raise NotImplementedError(
            "真实容器执行属后续步骤（§4.1.6-4 的 ⑧，段二-3）；本步骤只交付参数装配"
        )


@dataclass(frozen=True)
class ExecutionOutcome:
    """一次执行的**确定性**结果摘要（供 ⑨ 落摘要 / 用例断言；不含正文与宿主路径）。"""

    ok: bool
    summary: dict[str, object]
    timed_out: bool = False


class DeterministicFakeExecutor:
    """⑧ 的**一次性假执行器**（段二-2 离线验收用，§1.4）。

    - **确定性**：同一入参恒返回同一结果（不使用时间 / 随机 / 网络 / 容器）；
    - 只返回**摘要**（工具键 + 结果计数），**不回传参数原文与宿主路径**；
    - 真实容器执行属段二-3（`ContainerExecutor.execute`）。
    按 §6「清理纪律」，本类属需在用户确认后删除的一次性测试桩。

    另暴露**只读**调用计数与调用记录（`call_count` / `calls`），仅用于 §5 用例 29①「打桩断言
    执行器被调用一次」的可判定性；**不改执行语义**。
    """

    def __init__(self, *, ok: bool = True, timed_out: bool = False) -> None:
        self.ok = ok
        self.timed_out = timed_out
        self._calls: list[dict[str, object]] = []

    @property
    def call_count(self) -> int:
        """本桩被调用次数（只读）。"""
        return len(self._calls)

    @property
    def calls(self) -> tuple[dict[str, object], ...]:
        """本桩的调用记录（只读快照；仅含工具键、工作卷路径与参数个数，不含参数原文）。"""
        return tuple(self._calls)

    def execute(
        self, *, tool_key: str, params, workspace_path: str, spec: ContainerSpec | None = None
    ) -> ExecutionOutcome:
        self._calls.append(
            {
                "tool_key": tool_key,
                "workspace_path": workspace_path,
                "param_count": len(params) if params is not None else 0,
            }
        )
        summary: dict[str, object] = {
            "tool_key": tool_key,
            "status": "ok" if (self.ok and not self.timed_out) else "failed",
            "param_count": len(params) if params is not None else 0,
        }
        return ExecutionOutcome(ok=self.ok, timed_out=self.timed_out, summary=summary)
