"""容器执行器：用 **Docker SDK for Python** 真实执行，并逐条装配 §3.3 加固口径。

加固口径（§3.3，逐条落地，**不得做成配置可关**）：
    - 根**只读**（`read_only=True`）；
    - **非 root**（`user=65534:65534`）；
    - `cap_drop=["ALL"]`；
    - `security_opt=["no-new-privileges"]`；
    - `pids_limit` / `mem_limit` / `nano_cpus`（= `docker --cpus`）/ 单次执行硬上限；
    - **超时 = 拒绝并终止容器**（fail-closed）；
    - 网络面**仅内网桥**（`internal=True`，**无外网出口**）；
    - 工作卷 `/workspace` **生成即空、运行结束销毁**，挂载选项 `noexec,nosuid,nodev`；
    - 镜像**必须用 digest**（`@sha256:`），不得用 tag。

工作卷形态说明（如实登记）：Docker **不支持**在 bind / volume 挂载上传 `noexec,nosuid,nodev`
（实测 `docker run -v vol:/w:noexec → invalid mode: noexec,nosuid,nodev`），唯一能同时满足
「`noexec,nosuid,nodev` + 与容器根不同设备 + 生成即空 + 随容器销毁」的是容器内 **tmpfs**。
故 `/workspace` 采用 tmpfs；宿主侧 `WORKBENCH_EXEC_WORKSPACE_ROOT` 仍由 ③ 路径闸门消费。

孤儿容器（§3.3 生命周期）：按 `workbench.exec.managed` 标签清扫（启动时 + 周期，见
`cleanup.py`）；**孤儿数超 `WORKBENCH_EXEC_ORPHAN_LIMIT` → 拒绝新执行并记 error（fail-closed，
不打挂进程）**（§8 U17 ⑥）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .errors import ToolExecutionConfigError, WorkspaceError
from .log import get_logger

# 容器内挂载点与固定加固常量（§3.3）。
WORKSPACE_MOUNT = "/workspace"
TMP_MOUNT = "/tmp"
DEV_SHM_MOUNT = "/dev/shm"
EXEC_USER = "65534:65534"
INTERNAL_NETWORK_NAME = "workbench-exec-internal"
MANAGED_LABEL = "workbench.exec.managed"
RUN_LABEL = "workbench.exec.run"
FALLBACK_SCRATCH_SIZE_MB = 64
DEFAULT_ORPHAN_LIMIT = 8

TMPFS_OPTIONS = "rw,noexec,nosuid,nodev"


def _digest_pinned(image: str) -> bool:
    """镜像必须按 digest 钉死（`repo@sha256:…`）；tag 一律拒绝。"""
    return "@sha256:" in image


def _command_for(tool_key: str, params: Mapping[str, Any]) -> list[str]:
    """把一次工具调用映射为容器内的**结构化命令**（不经过 shell 解释）。

    段二-3 只交付容器边界本身；需要在容器内落地的自建工具（`fs.*` / `artifact.export`）
    由后续适配器段实现（规格 §F）。此处对未实现的工具** fail-closed **，绝不静默返回成功。
    """
    if tool_key == "cmd.run":
        executable = params.get("executable")
        args = params.get("args") or []
        if not isinstance(executable, str) or not executable:
            raise ToolExecutionConfigError("cmd.run 缺少 executable，拒绝执行")
        if not isinstance(args, (list, tuple)) or not all(
            isinstance(item, str) for item in args
        ):
            raise ToolExecutionConfigError("cmd.run 的 args 必须为字符串数组，拒绝执行")
        return [executable, *args]
    raise ToolExecutionConfigError(f"工具 {tool_key} 在容器内的执行入口尚未实现，拒绝执行")


def _run_id_from(workspace_path: str) -> str:
    """工作卷路径形如 `<root>/<tenant>/<run>`：取末段作为 run 标签（仅用于标签/清扫）。"""
    cleaned = str(workspace_path).replace("\\", "/").rstrip("/")
    return cleaned.rsplit("/", 1)[-1] if cleaned else ""


@dataclass(frozen=True)
class ContainerSpec:
    """一次容器执行的参数装配结果（供 ⑧ 使用）。"""

    image: str
    pids_limit: int
    memory_mb: int
    cpus: float
    timeout_seconds: int
    workspace_mount: str = WORKSPACE_MOUNT
    scratch_size_mb: int = FALLBACK_SCRATCH_SIZE_MB
    network_name: str = INTERNAL_NETWORK_NAME

    def docker_args(self, workspace_path: str) -> list[str]:
        """加固口径的 CLI 等价 argv（工作卷为 tmpfs，故无 `-v` 宿主绑定）。"""
        return [
            "run",
            "--rm",
            "--read-only",
            "--user",
            EXEC_USER,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(self.pids_limit),
            "--memory",
            f"{self.memory_mb}m",
            "--cpus",
            str(self.cpus),
            "--network",
            self.network_name,
            "--tmpfs",
            f"{self.workspace_mount}:{TMPFS_OPTIONS},size={self.scratch_size_mb}m",
            "--tmpfs",
            f"{TMP_MOUNT}:{TMPFS_OPTIONS},size={self.scratch_size_mb}m",
            "--tmpfs",
            f"{DEV_SHM_MOUNT}:{TMPFS_OPTIONS},size={self.scratch_size_mb}m",
            self.image,
        ]

    def create_kwargs(
        self, *, labels: Mapping[str, str], command: list[str]
    ) -> dict[str, object]:
        """Docker SDK 的 `containers.run(..., **kwargs)` 参数（加固口径唯一来源）。"""
        return {
            "image": self.image,
            "command": command,
            "detach": True,
            "labels": dict(labels),
            "network": self.network_name,
            "read_only": True,
            "user": EXEC_USER,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges"],
            "privileged": False,
            "pids_limit": self.pids_limit,
            "mem_limit": f"{self.memory_mb}m",
            "nano_cpus": int(self.cpus * 1_000_000_000),
            "tmpfs": {
                self.workspace_mount: f"{TMPFS_OPTIONS},size={self.scratch_size_mb}m",
                TMP_MOUNT: f"{TMPFS_OPTIONS},size={self.scratch_size_mb}m",
                DEV_SHM_MOUNT: f"{TMPFS_OPTIONS},size={self.scratch_size_mb}m",
            },
        }


@dataclass(frozen=True)
class ExecutionOutcome:
    """一次执行的**确定性**结果摘要（供 ⑨ 落摘要 / 用例断言；不含正文与宿主路径）。"""

    ok: bool
    summary: dict[str, object]
    timed_out: bool = False


class OrphanLimitExceeded(ToolExecutionConfigError):
    """孤儿容器数超 `WORKBENCH_EXEC_ORPHAN_LIMIT`：**拒绝新执行**（fail-closed，不打挂进程）。"""


def _default_client_factory():
    try:
        import docker  # noqa: PLC0415 - 新依赖，仅在真实执行路径导入
    except ModuleNotFoundError as exc:  # pragma: no cover - 依赖缺失时的 fail-closed
        raise ToolExecutionConfigError(
            "未安装 Docker SDK（包名 docker），拒绝启用真实容器执行"
        ) from exc
    return docker.from_env()


class ContainerExecutor:
    """容器执行器：§3.3 加固装配 + 真实执行 + 孤儿治理。"""

    def __init__(
        self,
        *,
        image_digest: str,
        pids_limit: int,
        memory_mb: int,
        cpu_quota: float,
        timeout_seconds: int,
        workspace_mount: str = WORKSPACE_MOUNT,
        scratch_size_mb: int = FALLBACK_SCRATCH_SIZE_MB,
        orphan_limit: int = DEFAULT_ORPHAN_LIMIT,
        network_name: str = INTERNAL_NETWORK_NAME,
        client_factory: Callable[[], Any] | None = None,
        token_revoker: Callable[[str], None] | None = None,
    ) -> None:
        if not isinstance(image_digest, str) or not image_digest.strip():
            raise ToolExecutionConfigError(
                "未配置执行镜像 digest WORKBENCH_EXEC_IMAGE_DIGEST，拒绝启用真实执行"
            )
        if not _digest_pinned(image_digest):
            raise ToolExecutionConfigError(
                "执行镜像必须按 digest 钉死（repo@sha256:…），禁止使用浮动 tag"
            )
        if pids_limit < 1 or memory_mb < 1 or cpu_quota <= 0 or timeout_seconds < 1:
            raise ToolExecutionConfigError("容器资源参数非法")
        if orphan_limit < 0:
            raise ToolExecutionConfigError("孤儿上限必须为非负整数")
        self.image_digest = image_digest
        self.pids_limit = pids_limit
        self.memory_mb = memory_mb
        self.cpu_quota = cpu_quota
        self.timeout_seconds = timeout_seconds
        self.workspace_mount = workspace_mount
        self.scratch_size_mb = scratch_size_mb
        self.orphan_limit = orphan_limit
        self.network_name = network_name
        self._client_factory = client_factory or _default_client_factory
        self._client: Any | None = None
        # 本进程内**当前在跑**的容器 id；不在此集合、却带托管标签的容器即「孤儿」。
        self._live: set[str] = set()
        # 终态同步吊销（§3.5 P1 第 3 条 ⑤）：容器到达终态后触发（可为 None）。
        self.token_revoker = token_revoker

    @classmethod
    def from_settings(cls, settings) -> "ContainerExecutor":
        return cls(
            image_digest=settings.exec_image_digest,
            pids_limit=settings.exec_pids_limit,
            memory_mb=settings.exec_memory_mb,
            cpu_quota=settings.exec_cpu_quota,
            timeout_seconds=settings.exec_timeout_seconds,
            orphan_limit=settings.exec_orphan_limit,
        )

    # ------------------------------------------------------------------ 装配

    def build_spec(self) -> ContainerSpec:
        return ContainerSpec(
            image=self.image_digest,
            pids_limit=self.pids_limit,
            memory_mb=self.memory_mb,
            cpus=self.cpu_quota,
            timeout_seconds=self.timeout_seconds,
            workspace_mount=self.workspace_mount,
            scratch_size_mb=self.scratch_size_mb,
            network_name=self.network_name,
        )

    def client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    # ------------------------------------------------------------------ 孤儿治理

    def managed_containers(self) -> list[Any]:
        """带托管标签的全部容器（含已退出、未被回收的残留）。"""
        try:
            return list(
                self.client().containers.list(
                    all=True, filters={"label": f"{MANAGED_LABEL}=1"}
                )
            )
        except ToolExecutionConfigError:
            raise
        except Exception as exc:  # noqa: BLE001 - Docker 不可用时不静默放行
            raise ToolExecutionConfigError(f"Docker 守护进程不可用：{exc}") from exc

    def orphan_containers(self) -> list[Any]:
        """孤儿 = 带托管标签、但本进程未在跟踪的容器。"""
        return [c for c in self.managed_containers() if c.id not in self._live]

    def enforce_orphan_limit(self) -> None:
        """超限 → 拒绝新执行并告警（fail-closed）。"""
        orphans = self.orphan_containers()
        if len(orphans) > self.orphan_limit:
            get_logger().error(
                "孤儿容器数 %d 超上限 %d，拒绝新执行（§8 U17 ⑥）",
                len(orphans),
                self.orphan_limit,
            )
            raise OrphanLimitExceeded(
                f"孤儿容器数 {len(orphans)} 超上限 {self.orphan_limit}，拒绝新执行"
            )

    def cleanup_orphans(self) -> int:
        """回收孤儿容器（启动时 + 周期）；回收失败**告警并登记**，不抛出。"""
        removed = 0
        for container in self.orphan_containers():
            try:
                container.remove(force=True)
                removed += 1
            except Exception as exc:  # noqa: BLE001 - 清扫失败只告警，不影响读路径
                get_logger().error(
                    "孤儿容器回收失败，需人工清理：%s（%s）", container.id, exc
                )
        if removed:
            get_logger().error("已回收 %d 个孤儿容器（§3.3 生命周期）", removed)
        return removed

    # ------------------------------------------------------------------ 执行

    def create(self, *, tool_key: str, params: Mapping[str, Any], workspace_path: str) -> Any:
        """创建并启动一个加固容器（**工作卷 = 容器内 tmpfs**）；调用方负责销毁。"""
        command = _command_for(tool_key, params)
        self._ensure_internal_network()
        spec = self.build_spec()
        kwargs = spec.create_kwargs(
            labels={MANAGED_LABEL: "1", RUN_LABEL: _run_id_from(workspace_path)},
            command=command,
        )
        try:
            container = self.client().containers.run(**kwargs)
        except Exception as exc:  # noqa: BLE001 - 起容器失败一律受控
            raise WorkspaceError(f"容器创建失败：{exc}") from exc
        self._live.add(container.id)
        return container

    def remove_container(self, container: Any) -> None:
        """强制移除容器；失败**告警并登记**（孤儿回收兜底由 `cleanup_orphans` 承担）。"""
        self._live.discard(container.id)
        try:
            container.remove(force=True)
        except Exception as exc:  # noqa: BLE001 - 销毁失败只告警
            get_logger().error("容器销毁失败，需人工清理残留：%s（%s）", container.id, exc)

    def execute(
        self,
        *,
        tool_key: str,
        params: Mapping[str, Any],
        workspace_path: str,
        spec: ContainerSpec | None = None,
    ) -> ExecutionOutcome:
        """真实执行一次工具调用：超时 → **拒绝并终止容器**（fail-closed）。"""
        self.enforce_orphan_limit()
        container = self.create(tool_key=tool_key, params=params, workspace_path=workspace_path)
        timed_out = False
        status_code: int | None = None
        try:
            try:
                result = container.wait(timeout=self.timeout_seconds)
                status_code = int((result or {}).get("StatusCode", 0))
            except Exception as exc:  # noqa: BLE001
                if not _is_timeout(exc):
                    raise
                timed_out = True
                self._kill(container)
        finally:
            self.remove_container(container)
            self._revoke_on_terminal(_run_id_from(workspace_path))

        summary: dict[str, object] = {
            "tool_key": tool_key,
            "status": "timeout" if timed_out else ("ok" if status_code == 0 else "failed"),
        }
        if not timed_out:
            summary["exit_code"] = status_code
        return ExecutionOutcome(
            ok=not timed_out and status_code == 0,
            timed_out=timed_out,
            summary=summary,
        )

    # ------------------------------------------------------------------ 内部

    def _kill(self, container: Any) -> None:
        try:
            container.kill()
        except Exception as exc:  # noqa: BLE001 - 超时终止失败必须留痕
            get_logger().error("超时终止容器失败，需人工介入：%s（%s）", container.id, exc)

    def _revoke_on_terminal(self, run_id: str) -> None:
        """终态同步吊销（§3.5 P1 ⑤）：失败只告警，**不得**影响执行结果返回。"""
        if self.token_revoker is None or not run_id:
            return
        try:
            self.token_revoker(run_id)
        except Exception as exc:  # noqa: BLE001 - 吊销失败不影响既有结果
            get_logger().error("终态同步吊销失败，需人工介入（§3.5 P1 ⑤）：%s", exc)

    def _ensure_internal_network(self) -> None:
        """确保内网桥存在且 **`internal=True`（无外网出口）**（§3.3 网络）。"""
        client = self.client()
        try:
            existing = client.networks.list(names=[self.network_name])
            for network in existing:
                if network.name == self.network_name:
                    attrs = getattr(network, "attrs", {}) or {}
                    if not attrs.get("Internal", False):
                        raise ToolExecutionConfigError(
                            f"网络 {self.network_name} 非内网桥（internal=False），拒绝执行"
                        )
                    return
            client.networks.create(self.network_name, driver="bridge", internal=True)
        except ToolExecutionConfigError:
            raise
        except Exception as exc:  # noqa: BLE001 - 网络装配失败一律 fail-closed
            raise ToolExecutionConfigError(f"内网桥装配失败：{exc}") from exc


def _is_timeout(exc: Exception) -> bool:
    """识别 `container.wait(timeout=…)` 的超时异常（requests 的 ReadTimeout）。"""
    names = {type(exc).__name__}
    names.update(base.__name__ for base in type(exc).__mro__)
    if names & {"ReadTimeout", "Timeout", "ConnectionTimeout"}:
        return True
    return "timed out" in str(exc).lower() or "timeout" in str(exc).lower()


class DeterministicFakeExecutor:
    """⑧ 的**一次性假执行器**（段二-2 离线验收用，§1.4）。

    - **确定性**：同一入参恒返回同一结果（不使用时间 / 随机 / 网络 / 容器）；
    - 只返回**摘要**（工具键 + 结果计数），**不回传参数原文与宿主路径**；
    - 真实容器执行见 `ContainerExecutor.execute`。
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
