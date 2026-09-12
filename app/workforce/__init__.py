"""岗位与数字员工目录（「数字员工设置」的领域层）。

口径见 `docs/superpowers/specs/2026-09-12-agent-directory-design.md`。
"""

from .config import AgentConfigService, scan_system_prompt, validate_agent_config
from .models import (
    AUTONOMY_LEVELS,
    MAX_SYSTEM_PROMPT_LENGTH,
    RISK_THRESHOLDS,
    DigitalEmployee,
    DirectoryConflict,
    DirectoryError,
    DirectoryNotFound,
    DirectoryNotManaged,
    DirectoryStatus,
    InvalidAgentConfig,
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
    "AUTONOMY_LEVELS",
    "AgentConfigService",
    "DigitalEmployee",
    "DirectoryConflict",
    "DirectoryError",
    "DirectoryNotFound",
    "DirectoryNotManaged",
    "DirectoryStatus",
    "InMemoryWorkforceDirectoryStore",
    "InvalidAgentConfig",
    "InvalidDirectoryKey",
    "InvalidDirectoryName",
    "JobRole",
    "MAX_SYSTEM_PROMPT_LENGTH",
    "PostgresWorkforceDirectoryStore",
    "RISK_THRESHOLDS",
    "RoleNotAvailable",
    "WorkforceDirectoryService",
    "WorkforceDirectoryStore",
    "scan_system_prompt",
    "validate_agent_config",
]
