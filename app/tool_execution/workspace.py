"""per-run 工作卷管理（规格 §3.3「工作目录：per-run 唯一、生成即空；运行结束销毁」）。

目录标识来自租户 / 运行 id（属**不可信输入**）：一律做白名单字符校验后再拼路径，
防止 `../` 逃逸出工作卷根。销毁失败必须告警（§3.3 残留清理）。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .errors import ToolExecutionConfigError, WorkspaceError
from .log import get_logger

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")


class WorkspaceManager:
    """工作卷的创建 / 销毁；**生成即空**——已存在的目录拒绝复用。"""

    def __init__(self, root: str) -> None:
        if not isinstance(root, str) or not root.strip():
            raise ToolExecutionConfigError(
                "未配置执行工作卷根 WORKBENCH_EXEC_WORKSPACE_ROOT，拒绝启用真实执行"
            )
        self._root = Path(root)

    def _path(self, tenant_id: str, run_id: str) -> Path:
        for segment in (tenant_id, run_id):
            if not isinstance(segment, str) or not _SAFE_SEGMENT.match(segment):
                raise WorkspaceError("工作目录标识非法（只允许字母、数字、下划线与连字符）")
        return self._root / tenant_id / run_id

    def create(self, tenant_id: str, run_id: str) -> str:
        path = self._path(tenant_id, run_id)
        try:
            path.mkdir(parents=True)
        except FileExistsError as exc:
            raise WorkspaceError("工作目录已存在，拒绝复用") from exc
        except OSError as exc:
            raise WorkspaceError("工作目录创建失败") from exc
        return str(path)

    def destroy(self, tenant_id: str, run_id: str) -> None:
        path = self._path(tenant_id, run_id)
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            return
        except OSError as exc:
            get_logger().error("工作目录销毁失败，需人工清理残留：%s", exc)
            raise WorkspaceError("工作目录销毁失败") from exc
