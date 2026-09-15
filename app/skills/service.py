"""技能服务层：技能包申报 / 审核 / 启用 / 绑定业务逻辑 + 工具面交集 + 审计。

口径见 `docs/superpowers/specs/2026-09-15-skill-layer-p4-design.md` §2。
职责边界：来源白名单与字段校验（`SkillPackageValidator`）、内容指纹派生、状态机流转、
`allowed-tools` 与既有 `ToolSpecCatalog` 键集取交集（§2.4，fail-closed）、审计落点。
仓储层的归属 / 角色校验同样保留（双保险，与记忆层一致）。

⚠️ 动作码（"skill.submitted" / "skill.approved" / "skill.rejected" / "skill.enabled" /
"skill.disabled"）与明细键（skill_key / version / agent_key / source_key / content_sha256 /
approved）已由主代理加入 `app/audit/models.py` 的 `AuditAction` 与 `ALLOWED_DETAIL_KEYS`；
本模块经 `AuditAction` 枚举引用（与记忆层 service 同口径）。
"""

from __future__ import annotations

from typing import Sequence

from ..audit.models import AuditAction
from ..domain import PolicyError, UserContext
from .models import (
    Skill,
    SkillBinding,
    SkillStatus,
    ensure_can_review,
    ensure_can_submit,
    normalize_status,
)
from .store import SkillStore
from .validator import SkillPackageValidator

# 审计动作码（已加入 AuditAction；经枚举引用，emit_audit_line 需要 .value）。
_ACTION_SUBMITTED = AuditAction.SKILL_SUBMITTED
_ACTION_APPROVED = AuditAction.SKILL_APPROVED
_ACTION_REJECTED = AuditAction.SKILL_REJECTED
_ACTION_ENABLED = AuditAction.SKILL_ENABLED
_ACTION_DISABLED = AuditAction.SKILL_DISABLED


class SkillService:
    """技能层领域核心的编排入口；审计缺省跳过（audit=None）。"""

    def __init__(
        self,
        store: SkillStore,
        validator: SkillPackageValidator,
        *,
        allowed_sources: frozenset[str],
        catalog_tool_keys: frozenset[str],
        audit=None,
        max_content_bytes: int = 64 * 1024,
    ) -> None:
        self.store = store
        self.validator = validator
        self.allowed_sources = allowed_sources
        self.catalog_tool_keys = catalog_tool_keys
        self.audit = audit
        # M5 裁决（2026-09-15）：技能包正文体积上限（库内落库，服务端校验；配置注入）。
        self.max_content_bytes = max_content_bytes

    # ------------------------------------------------------------ 技能包

    def submit_skill(
        self,
        context: UserContext,
        *,
        skill_key: str,
        version: str,
        name: str,
        description: str,
        license: str,
        allowed_tools: Sequence[str],
        source_key: str,
        package_bytes: bytes | None = None,
        content_sha256: str | None = None,
        content_body: str = "",
    ) -> Skill:
        """申报技能包：来源/字段/工具键校验 → 内容指纹派生 → 登记 → 审计。

        指纹三选一（M5 裁决：库内落库 content_body）：
        - 提供了 `content_body` ⇒ 以其 UTF-8 字节计算指纹，且与调用方 `content_sha256`（若给）必须一致；
        - 否则提供 `package_bytes` ⇒ 用其计算指纹；
        - 否则用调用方给的 `content_sha256`；
        三者都缺 → 422（fail-closed，登记必须可溯源）。
        """
        ensure_can_submit(context)
        spec = self.validator.validate_package(
            skill_key=skill_key,
            version=version,
            name=name,
            description=description,
            license=license,
            allowed_tools=allowed_tools,
            source_key=source_key,
            allowed_sources=self.allowed_sources,
            catalog_tool_keys=self.catalog_tool_keys,
            content_body=content_body,
            max_content_bytes=self.max_content_bytes,
        )
        # 指纹派生（优先正文文本 → 其次 package_bytes → 其次调用方声明）。
        if spec.content_body:
            sha256 = self.validator.compute_sha256_from_text(spec.content_body)
            if content_sha256 and content_sha256.strip() != sha256:
                from .models import InvalidSkillPackage

                raise InvalidSkillPackage("content_sha256 与技能包正文指纹不一致")
        elif package_bytes is not None:
            sha256 = self.validator.compute_sha256(package_bytes)
        elif content_sha256:
            sha256 = content_sha256.strip()
        else:
            from .models import InvalidSkillPackage

            raise InvalidSkillPackage("必须提供 content_body / package_bytes / content_sha256 之一")
        skill = Skill(
            tenant_id=context.tenant_id,
            skill_key=spec.skill_key,
            version=spec.version,
            name=spec.name,
            description=spec.description,
            license=spec.license,
            allowed_tools=spec.allowed_tools,
            status=SkillStatus.SUBMITTED,
            source_key=spec.source_key,
            content_sha256=sha256,
            owner_id=context.user_id,
            content_body=spec.content_body,
        )
        saved = self.store.submit(context, skill=skill, package_sha256=sha256)
        self._record(
            context,
            _ACTION_SUBMITTED,
            f"{saved.skill_key}@{saved.version}",
            {
                "skill_key": saved.skill_key,
                "version": saved.version,
                "source_key": saved.source_key,
                "content_sha256": saved.content_sha256,
            },
        )
        return saved

    def review_skill(self, context: UserContext, skill_key: str, version: str, *, approved: bool) -> Skill:
        """人工审核（仅 super_admin）：提交人不能审核自己提交的包（生成者 ≠ 评审者，§2.3）。"""
        ensure_can_review(context)
        skill = self.store.get(context, skill_key, version)
        if skill.owner_id == context.user_id:
            raise PolicyError("不能审核自己提交的技能包")
        reviewed = self.store.review(context, skill_key, version, approved=approved)
        self._record(
            context,
            _ACTION_APPROVED if approved else _ACTION_REJECTED,
            f"{reviewed.skill_key}@{reviewed.version}",
            {"skill_key": reviewed.skill_key, "version": reviewed.version, "approved": bool(approved)},
        )
        return reviewed

    def enable_skill(self, context: UserContext, skill_key: str, version: str) -> Skill:
        """启用技能（管理动作，仅 super_admin）；`enabled ⇄ disabled` 可回退。"""
        ensure_can_review(context)
        saved = self.store.enable(context, skill_key, version)
        self._record(
            context,
            _ACTION_ENABLED,
            f"{saved.skill_key}@{saved.version}",
            {"skill_key": saved.skill_key, "version": saved.version},
        )
        return saved

    def disable_skill(self, context: UserContext, skill_key: str, version: str) -> Skill:
        """停用技能（管理动作，仅 super_admin）。"""
        ensure_can_review(context)
        saved = self.store.disable(context, skill_key, version)
        self._record(
            context,
            _ACTION_DISABLED,
            f"{saved.skill_key}@{saved.version}",
            {"skill_key": saved.skill_key, "version": saved.version},
        )
        return saved

    def bind_skill(self, context: UserContext, agent_key: str, skill_key: str, *, created_by: str | None = None) -> SkillBinding:
        """把已登记技能绑定到某数字员工（UPSERT active）。"""
        ensure_can_review(context)
        binding = self.store.bind_skill(
            context, agent_key, skill_key, created_by=created_by or context.user_id
        )
        self._record(
            context,
            _ACTION_ENABLED,  # 绑定 = 放行进入该员工工具面，复用 enabled 动作码（明细区分）。
            f"{skill_key}@{agent_key}",
            {"skill_key": skill_key, "agent_key": agent_key},
        )
        return binding

    def unbind_skill(self, context: UserContext, agent_key: str, skill_key: str) -> SkillBinding:
        """解除某员工对该技能的绑定（active → disabled）。"""
        ensure_can_review(context)
        binding = self.store.unbind_skill(context, agent_key, skill_key)
        self._record(
            context,
            _ACTION_DISABLED,  # 解绑 = 移出该员工工具面，复用 disabled 动作码（明细区分）。
            f"{skill_key}@{agent_key}",
            {"skill_key": skill_key, "agent_key": agent_key},
        )
        return binding

    # ------------------------------------------------------------ 查询转发

    def get_skill(self, context: UserContext, skill_key: str, version: str) -> Skill:
        return self.store.get(context, skill_key, version)

    def list_skills(self, context: UserContext, *, status=None, limit: int = 50, offset: int = 0) -> tuple[list[Skill], int]:
        if status is not None:
            status = normalize_status(status)  # 非法值 422
        return self.store.list(context, status=status, limit=limit, offset=offset)

    def list_bindings(
        self, context: UserContext, *, agent_key: str | None = None, skill_key: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[SkillBinding], int]:
        return self.store.list_bindings(context, agent_key=agent_key, skill_key=skill_key, limit=limit, offset=offset)

    def list_enabled_for_agent(self, context: UserContext, agent_key: str) -> list[Skill]:
        return self.store.list_enabled_for_agent(context, agent_key)

    def expanded_tools_for_agent(self, context: UserContext, agent_key: str) -> tuple[str, ...]:
        """该数字员工实际可见的工具键 = 已启用技能 allowed-tools 并集 ∩ ToolSpecCatalog 键集。

        §2.4 / §1.2 D：**取交集、fail-closed**——目录可升级，技能允许集随目录收窄；
        目录外的键一律不展开。返回排序元组。
        """
        skills = self.store.list_enabled_for_agent(context, agent_key)
        union: set[str] = set()
        for skill in skills:
            union.update(skill.allowed_tools)
        return tuple(sorted(union & set(self.catalog_tool_keys)))

    # ------------------------------------------------------------ 内部

    def _record(self, context: UserContext, action: AuditAction, target_id: str, detail: dict[str, object]) -> None:
        if self.audit is None:
            return
        self.audit.record(
            action,
            tenant_id=context.tenant_id,
            actor_id=context.user_id,
            target_type="skill",
            target_id=target_id,
            detail=detail,
        )