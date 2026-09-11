"""岗位与数字员工目录（「数字员工设置」的领域层）。

口径见 `docs/superpowers/specs/2026-09-12-agent-directory-design.md`。
"""

from .models import (
    DigitalEmployee,
    DirectoryConflict,
    DirectoryError,
    DirectoryNotFound,
    DirectoryStatus,
    InvalidDirectoryKey,
    InvalidDirectoryName,
    JobRole,
    RoleNotAvailable,
)
from .service import WorkforceDirectoryService
from .store import (
    InMemoryWorkforceDirectoryStore,
    PostgresWorkforceDirectoryStore,
    WorkforceDirectoryStore,
)

__all__ = [
    "DigitalEmployee",
    "DirectoryConflict",
    "DirectoryError",
    "DirectoryNotFound",
    "DirectoryStatus",
    "InMemoryWorkforceDirectoryStore",
    "InvalidDirectoryKey",
    "InvalidDirectoryName",
    "JobRole",
    "PostgresWorkforceDirectoryStore",
    "RoleNotAvailable",
    "WorkforceDirectoryService",
    "WorkforceDirectoryStore",
]
