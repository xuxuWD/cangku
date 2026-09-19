"""租户导出包的**读取通道**（B-2 接线）：把各模块「按租户读元数据」的能力翻译成统一的
`(rows, total)`，供 `CommercialLifecycleService.build_export_payload` 使用。

口径（三条，同时写入 `docs/api-contract.md`「私有部署商业化 G0」导出段）：

1. **字段只取既有读模型 / 对外视图已存在的字段**，并对**凭据类列按类别硬排除**
   （用户口令哈希与 TOTP 种子、数字员工的系统提示词 / 模型键 / 工具白名单 / 记忆策略、
   任务的幂等键与请求指纹、运行的执行授权位）——不臆造字段、不把内部凭据带出。
2. **每类有行数上限**（`limit` 由调用方给出，默认见 `lifecycle.EXPORT_CATEGORY_MAX_ROWS`）：
   读者返回 `(本页行, 该类总数)`，`总数 > 行数` 时**由服务层在 `truncated_categories` 里如实声明**，
   绝不静默截断。
3. 读到的行**统一过 `redact_payload`**（既有脱敏器：敏感键名 + 值内凭据形态），
   因此即便某条文本里写了密钥，也不会原样进包。

读者是**无状态适配器**：不做鉴权（权限由服务层 `_ensure_admin` 负责）、不跨租户（每个方法都带
`tenant_id`）、不改上游数据；上游能力不足（无 offset / 无计数）时由适配器自己分页或计数，
**不谎报总数**（拿不到总数就不接该类，见 `build_export_readers` 的注释）。

**已知字段级缺口（如实登记，不假装有数据）**：数字员工只导出目录字段——两套实现里
`list_employees` 在 PG 侧**不返回配置列**（回落 dataclass 默认值，见 `app/workforce/store.py` 的
`_hydrate_employee`），从列表值导出自治档 / 预算等会**导出默认值而不是真值**；真配置只能逐条
`read_agent_config`（N+1）。本批不猜值 ⇒ 配置明细留待后续（见交付清单 10.7 的残留项）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Protocol

from ..audit.redaction import mask_phone
from ..domain import UserContext
from ..runtime.contracts import redact_payload

ExportRow = dict[str, object]

# 平台身份：导出由 worker 代表平台执行（与 `CommercialLifecycleService.execute_delete` 用
# super_admin 走状态机、`_ensure_admin` 只认 super_admin / 客户管理员同一先例）。
# 这里只为通过上游仓储的 `_ensure_admin`（如 `app/workforce/store.py`），不冒充具体客户用户。
EXPORT_ACTOR_USER_ID = "system:export"
EXPORT_ACTOR_ROLE = "super_admin"

# 分页循环的页大小：不得超过上游 `MAX_LIMIT`（workforce 为 200，`app/workforce/store.py`）。
_PAGE_SIZE = 200


class ExportReader(Protocol):
    """单类别读取器：返回 `(行, 该类总数)`；行数不得超过 `limit`。"""

    def __call__(self, tenant_id: str, *, limit: int) -> tuple[list[ExportRow], int]: ...


def _system_context(tenant_id: str) -> UserContext:
    return UserContext(tenant_id=tenant_id, user_id=EXPORT_ACTOR_USER_ID, role=EXPORT_ACTOR_ROLE)


def _as_text(value: object) -> str:
    """枚举取 `.value`，其余转字符串（读模型里状态多为 StrEnum）。"""
    inner = getattr(value, "value", None)
    return str(inner if inner is not None else value)


def _iso(value: object) -> str | None:
    """时间统一 ISO 字符串；空值保持 None（不伪造时间）。"""
    if isinstance(value, datetime):
        return value.isoformat()
    return None if value is None else str(value)


def _paged(fetch: Callable[[int, int], tuple[list[ExportRow], int]], *, limit: int) -> tuple[list[ExportRow], int]:
    """通用分页循环：`fetch(offset, page_size) -> (rows, total)`，最多取 `limit` 行。

    `total` 由上游给出（**不拿页数推算**）；上游返回空页即停，避免无 offset 语义的上游死循环。
    """
    rows: list[ExportRow] = []
    total = 0
    offset = 0
    while len(rows) < limit:
        page_size = min(_PAGE_SIZE, limit - len(rows))
        page, total = fetch(offset, page_size)
        if not page:
            break
        rows.extend(page)
        offset += len(page)
        if offset >= total:
            break
    return rows, total


# ---------------------------------------------------------------------------
# 记忆（P3）——**整层三类**（2026-09-19 起），事实类字段与 2026-09-16 接线时逐字一致
# ---------------------------------------------------------------------------


def memory_export_reader(memory_store) -> ExportReader:
    """`memories` 读**记忆层整层**：事实 / 规则 / 身份类画像三类，行内以 `kind` 判别。

    为什么整层（2026-09-19）：真源 §6.1 的导出项「记忆」= 记忆层，而 `029` 迁移自述记忆层是
    「三类记忆（身份 / 规则 / 事实）」⇒ 只出事实类会让导出包少两类；删除面已按整层三张表清场，
    两面口径必须一致。**事实类字段不变**（既有字段 + 新增的 `kind` 判别），规则类 = 事实字段 +
    `rule_key` / `version`，画像类 = 自身 KV 字段（无状态列）。
    """

    def read(tenant_id: str, *, limit: int) -> tuple[list[ExportRow], int]:
        facts = memory_store.list_all_for_tenant(tenant_id)
        rules = memory_store.list_rules_for_tenant(tenant_id)
        profiles = memory_store.list_profiles_for_tenant(tenant_id)
        rows: list[ExportRow] = []
        for fact in facts:
            rows.append(
                {
                    "kind": "fact",
                    "memory_id": fact.memory_id,
                    "scope": _as_text(fact.scope),
                    "status": _as_text(fact.status),
                    "content": fact.content,
                    "created_at": _iso(fact.created_at),
                }
            )
        for rule in rules:
            rows.append(
                {
                    "kind": "rule",
                    "memory_id": rule.memory_id,
                    "scope": _as_text(rule.scope),
                    "status": _as_text(rule.status),
                    "content": rule.content,
                    "created_at": _iso(rule.created_at),
                    "rule_key": rule.rule_key,
                    "version": rule.version,
                }
            )
        for profile in profiles:
            rows.append(
                {
                    "kind": "profile",
                    "owner_kind": _as_text(profile.owner_kind),
                    "owner_id": profile.owner_id,
                    "profile_key": profile.profile_key,
                    "value": profile.value,
                    "updated_at": _iso(profile.updated_at),
                }
            )
        # 总数 = 三类之和（**不拿返回条数冒充总数**）；上限按合并后的整层列表切片。
        total = len(rows)
        return rows[:limit], total

    return read


# ---------------------------------------------------------------------------
# 岗位 / 数字员工（workforce 目录）
# ---------------------------------------------------------------------------


def workforce_role_export_reader(store) -> ExportReader:
    """岗位配置：字段同 `JobRoleView`（`app/main.py`），不含租户列。"""

    def read(tenant_id: str, *, limit: int) -> tuple[list[ExportRow], int]:
        context = _system_context(tenant_id)

        def bound(offset: int, page_size: int) -> tuple[list[ExportRow], int]:
            roles, total = store.list_roles(context, limit=page_size, offset=offset)
            return [
                {
                    "role_key": role.role_key,
                    "name": role.name,
                    "description": role.description,
                    "status": _as_text(role.status),
                    "created_by": role.created_by,
                    "created_at": _iso(role.created_at),
                    "updated_at": _iso(role.updated_at),
                }
                for role in roles
            ], total

        return _paged(bound, limit=limit)

    return read


def workforce_agent_export_reader(store) -> ExportReader:
    """数字员工**目录**字段（同 `DigitalEmployeeView`）。

    **不含配置明细**（系统提示词 / 模型键 / 工具白名单 / 记忆策略 / 自治档 / 预算）：
    PG 侧列表读模型不返回配置列（会回落默认值）⇒ 从列表导出等于导出默认值，属「假装有数据」；
    真配置需逐条 `read_agent_config`，本批不做（缺口已登记）。
    """

    def read(tenant_id: str, *, limit: int) -> tuple[list[ExportRow], int]:
        context = _system_context(tenant_id)

        def bound(offset: int, page_size: int) -> tuple[list[ExportRow], int]:
            employees, total = store.list_employees(context, limit=page_size, offset=offset)
            return [
                {
                    "agent_key": employee.agent_key,
                    "role_key": employee.role_key,
                    "name": employee.name,
                    "description": employee.description,
                    "status": _as_text(employee.status),
                    "created_by": employee.created_by,
                    "created_at": _iso(employee.created_at),
                    "updated_at": _iso(employee.updated_at),
                }
                for employee in employees
            ], total

        return _paged(bound, limit=limit)

    return read


# ---------------------------------------------------------------------------
# 知识文档（知识治理层）
# ---------------------------------------------------------------------------


def knowledge_document_export_reader(store) -> ExportReader:
    """知识文档元数据：字段同 `KnowledgeDocView`（不含租户列、不含正文）。

    上游 `list_all_for_tenant` 是**全量无分页**读取 ⇒ 本适配器自行切片，总数取读取结果长度。
    """

    def read(tenant_id: str, *, limit: int) -> tuple[list[ExportRow], int]:
        documents = store.list_all_for_tenant(tenant_id)
        rows = [
            {
                "document_id": document.document_id,
                "title": document.title,
                "owner_id": document.owner_id,
                "status": _as_text(document.status),
                "version": document.version,
                "source_key": document.source_key,
                "registered_by": document.registered_by,
                "last_reviewed_at": _iso(document.last_reviewed_at),
                "review_due_at": _iso(document.review_due_at),
                "created_at": _iso(document.created_at),
                "updated_at": _iso(document.updated_at),
            }
            for document in documents[:limit]
        ]
        return rows, len(documents)

    return read


# ---------------------------------------------------------------------------
# 审计记录（通用审计表）
# ---------------------------------------------------------------------------


def audit_export_reader(audit) -> ExportReader:
    """审计记录：字段同 `AuditRecordView`（手机号列已是掩码列 `phone_masked`）。

    `detail` 受 `ALLOWED_DETAIL_KEYS` 白名单约束（不含口令 / 令牌），仍会被统一脱敏器再扫一遍
    （值内凭据形态）；`action` 是枚举，导出取值而非枚举名。
    """

    def read(tenant_id: str, *, limit: int) -> tuple[list[ExportRow], int]:
        def bound(offset: int, page_size: int) -> tuple[list[ExportRow], int]:
            records, total = audit.query(tenant_id, limit=page_size, offset=offset)
            return [
                {
                    "record_id": record.record_id,
                    "action": _as_text(record.action),
                    "actor_id": record.actor_id,
                    "target_type": record.target_type,
                    "target_id": record.target_id,
                    "phone_masked": record.phone_masked,
                    "detail": record.detail,
                    "occurred_at": _iso(record.occurred_at),
                }
                for record in records
            ], total

        return _paged(bound, limit=limit)

    return read


# ---------------------------------------------------------------------------
# 运行记录（含步骤与工具计数的元数据）
# ---------------------------------------------------------------------------


def run_export_reader(records) -> ExportReader:
    """运行元数据：字段同 `RunMetricsView`（**不含**执行授权位 `execution_authorization`）。

    上游只有「最近 N 条」+ 计数两条通道 ⇒ `total` 取计数（**不拿返回条数冒充总数**），
    行取 `list_recent`（按 `started_at` 倒序）。
    """

    def read(tenant_id: str, *, limit: int) -> tuple[list[ExportRow], int]:
        recent = records.list_recent(tenant_id, limit=limit)
        rows = [
            {
                "run_id": record.run_id,
                "task_id": record.task_id,
                "proposal_id": record.proposal_id,
                "runtime_key": record.runtime_key,
                "status": _as_text(record.status),
                "step_count": record.step_count,
                "completed_step_count": record.completed_step_count,
                "tool_calls": record.tool_calls,
                "successful_tools": record.successful_tools,
                "knowledge_hits": record.knowledge_hits,
                "latency_ms": record.latency_ms,
                "started_at": _iso(record.started_at),
                "finished_at": _iso(record.finished_at),
                "finish_reason": record.finish_reason,
            }
            for record in recent
        ]
        return rows, records.count_for_tenant(tenant_id)

    return read


# ---------------------------------------------------------------------------
# 任务 / 用户（账号）/ 用量账本
# ---------------------------------------------------------------------------


def task_export_reader(repository) -> ExportReader:
    """任务元数据：字段取 `TaskView`（`app/main.py`）的业务列。

    **不含** `idempotency_key`（幂等去重键）与 `request_fingerprint`（请求内容指纹）：
    两者都是内部实现痕迹，不是业务元数据，也不该进导出包。
    """

    def read(tenant_id: str, *, limit: int) -> tuple[list[ExportRow], int]:
        def bound(offset: int, page_size: int) -> tuple[list[ExportRow], int]:
            tasks, total = repository.list_for_tenant(tenant_id, limit=page_size, offset=offset)
            return [
                {
                    "task_id": task.id,
                    "project_id": task.project_id,
                    "created_by": task.created_by,
                    "employee_key": task.employee_key,
                    "title": task.title,
                    "risk_level": _as_text(task.risk_level),
                    "budget": task.budget,
                    "status": _as_text(task.status),
                }
                for task in tasks
            ], total

        return _paged(bound, limit=limit)

    return read


def account_export_reader(repository) -> ExportReader:
    """用户（账号）元数据：字段取 `AccountView`（`app/main.py`）对外可见的那一份。

    **不含**：`password_hash` / `totp_secret` / `totp_last_step` / `sso_provider` / `sso_subject`
    / `rejection_reason`（自由文本）与**原始手机号**（只出掩码列 `phone_masked`，口径同管理台）。
    未审批（无租户）的申请账号不属于任何租户 ⇒ 上游 `list_for_tenant` 天然不返回。
    """

    def read(tenant_id: str, *, limit: int) -> tuple[list[ExportRow], int]:
        def bound(offset: int, page_size: int) -> tuple[list[ExportRow], int]:
            accounts, total = repository.list_for_tenant(tenant_id, limit=page_size, offset=offset)
            return [
                {
                    "account_id": account.account_id,
                    "phone_masked": mask_phone(account.phone),
                    "position": account.position,
                    "full_name": account.full_name,
                    "email": account.email,
                    "role": account.role,
                    "status": _as_text(account.status),
                    "requested_at": _iso(account.requested_at),
                    "reviewed_at": _iso(account.reviewed_at),
                    "reviewed_by": account.reviewed_by,
                }
                for account in accounts
            ], total

        return _paged(bound, limit=limit)

    return read


def usage_export_reader(ledger) -> ExportReader:
    """用量账本明细：**不含** `idempotency_key`（内部去重键）与 `tenant_id`。

    冲正以 `reversal_of` 指向原条目、`units` / `cost_cents` 为负值 ⇒ 累计口径与
    `GET /api/v1/commercial/usage` 一致（含冲正，客户端可自行汇总核对）。
    """

    def read(tenant_id: str, *, limit: int) -> tuple[list[ExportRow], int]:
        def bound(offset: int, page_size: int) -> tuple[list[ExportRow], int]:
            entries, total = ledger.list_for_tenant(tenant_id, limit=page_size, offset=offset)
            return [
                {
                    "id": entry.id,
                    "units": entry.units,
                    "cost_cents": entry.cost_cents,
                    "reversal_of": entry.reversal_of,
                    "occurred_at": _iso(entry.occurred_at),
                }
                for entry in entries
            ], total

        return _paged(bound, limit=limit)

    return read


def artifact_export_reader(store) -> ExportReader:
    """产物元数据：字段在 `RunArtifact.to_view()` 之上**补 `run_id`**。

    为什么补：`to_view()` 是**运行级**端点视图（运行号已在 URL 里，故不含），而导出是**租户级**
    快照 —— 不给运行号就无法判断产物属于哪次运行（真源要求的是「产物元数据」）。
    **不含** `tenant_id`（顶层已给）与宿主真实路径（`virtual_path` 本就是虚拟路径）。
    过期口径与运行产物端点一致（保留期外的登记不返回）。
    """

    def read(tenant_id: str, *, limit: int) -> tuple[list[ExportRow], int]:
        def bound(offset: int, page_size: int) -> tuple[list[ExportRow], int]:
            rows, total = store.list_for_tenant(tenant_id, limit=page_size, offset=offset)
            return [
                {
                    "run_id": row.run_id,
                    "artifact_id": row.artifact_id,
                    "virtual_path": row.virtual_path,
                    "change_kind": row.change_kind,
                    "bytes": int(row.bytes),
                    "sha256": row.sha256,
                    "created_at": _iso(row.created_at),
                    "expires_at": _iso(row.expires_at),
                }
                for row in rows
            ], total

        return _paged(bound, limit=limit)

    return read


def step_export_reader(state_store) -> ExportReader:
    """步骤元数据：**每个计划步骤一行**（把运行状态的计划展开成扁平行）。

    字段：`run_id` / `step_id` / `kind` / `tool` / `requires_approval` / `completed`
    （`completed` 由运行状态的 `completed_steps` 判定）。
    **不含**步骤的正文与执行输出（那些在运行事件里，属内部明细；本类是「元数据」）。

    **已知局限（如实登记）**：上游 `list_for_tenant` 无分页 ⇒ 适配器一次取全量后自行切片与计数；
    内存存储模式下运行时状态是**进程内状态**（重启 / 多进程看到的不完整），PG 模式读的是持久化
    状态行（`workbench_runtime_states`）——走查与真库用例均以 PG 口径为准。
    """

    def read(tenant_id: str, *, limit: int) -> tuple[list[ExportRow], int]:
        states = state_store.list_for_tenant(tenant_id)
        rows: list[ExportRow] = []
        total = 0
        for state in states:
            completed = set(state.completed_steps)
            for step in state.plan.steps:
                total += 1
                if len(rows) >= limit:
                    continue  # 仍要数完整总数（截断由服务层如实声明）
                rows.append(
                    {
                        "run_id": state.run_id,
                        "step_id": step.step_id,
                        "kind": step.kind,
                        "tool": step.tool,
                        "requires_approval": bool(step.requires_approval),
                        "completed": step.step_id in completed,
                    }
                )
        return rows, total

    return read


# ---------------------------------------------------------------------------
# 装配
# ---------------------------------------------------------------------------


def build_export_readers(
    *,
    memory_store=None,
    workforce=None,
    knowledge=None,
    audits=None,
    runs=None,
    accounts=None,
    tasks=None,
    usage=None,
    artifacts=None,
    steps=None,
) -> dict[str, ExportReader]:
    """按可用上游装配读取器；**缺哪个上游就不接哪一类**（该类仍留在 `unimplemented_categories`）。

    上游只提供「最近 N 条」而没有计数能力的（如运行记录缺 `count_for_tenant`）**不接**：
    宁可不接并在包内如实标注「未实现」，也不导出**无法声明完整性的**残缺列表。
    """
    readers: dict[str, ExportReader] = {}
    if memory_store is not None:
        readers["memories"] = memory_export_reader(memory_store)
    if workforce is not None:
        readers["roles"] = workforce_role_export_reader(workforce)
        readers["agents"] = workforce_agent_export_reader(workforce)
    if knowledge is not None:
        readers["knowledge_documents"] = knowledge_document_export_reader(knowledge)
    if audits is not None:
        readers["audits"] = audit_export_reader(audits)
    if runs is not None and hasattr(runs, "count_for_tenant"):
        readers["runs"] = run_export_reader(runs)
    if accounts is not None:
        readers["users"] = account_export_reader(accounts)
    if tasks is not None:
        readers["tasks"] = task_export_reader(tasks)
    if usage is not None:
        readers["usage"] = usage_export_reader(usage)
    if artifacts is not None:
        readers["artifacts"] = artifact_export_reader(artifacts)
    if steps is not None:
        readers["steps"] = step_export_reader(steps)
    return readers


__all__ = [
    "EXPORT_ACTOR_ROLE",
    "EXPORT_ACTOR_USER_ID",
    "ExportReader",
    "ExportRow",
    "account_export_reader",
    "artifact_export_reader",
    "audit_export_reader",
    "build_export_readers",
    "knowledge_document_export_reader",
    "memory_export_reader",
    "redact_payload",
    "run_export_reader",
    "step_export_reader",
    "task_export_reader",
    "usage_export_reader",
    "workforce_agent_export_reader",
    "workforce_role_export_reader",
]