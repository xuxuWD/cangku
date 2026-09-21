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
    SkillError,
    SkillNotFound,
    SkillStateConflict,
    SkillStatus,
    ensure_can_bind,
    ensure_can_review,
    ensure_can_submit,
    ensure_can_view_agent_tools,
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
        memory=None,
    ) -> None:
        self.store = store
        self.validator = validator
        self.allowed_sources = allowed_sources
        self.catalog_tool_keys = catalog_tool_keys
        self.audit = audit
        # M5 裁决（2026-09-15）：技能包正文体积上限（库内落库，服务端校验；配置注入）。
        self.max_content_bytes = max_content_bytes
        # M3 打通（2026-09-15）：技能经验沉淀依赖的 P3 记忆层（未注入时经验沉淀返回 503，
        # 不静默降级——见 `save_experience`）。注入方 = `app/main.py` 装配的 `memory_service`。
        self.memory = memory

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
        """人工审核（矩阵 §3 管理行：`ceo` / `super_admin`）：提交人不能审核自己提交的包（生成者 ≠ 评审者，§2.3）。"""
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
        """启用技能（管理动作，矩阵 §3：`ceo` / `super_admin`）；`enabled ⇄ disabled` 可回退。"""
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
        """停用技能（管理动作，矩阵 §3：`ceo` / `super_admin`）。"""
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
        """把已登记技能绑定到某数字员工（UPSERT active）。

        角色口径**独立于复核**：矩阵 §3 未列「绑定」行 ⇒ 仅 `super_admin`（`ensure_can_bind`），
        不随本轮 `ceo` 的复核 / 启停对齐一起放开。

        **第 11 轮闸门**（专项 `skill-binding-gate-plan.md` §3）：绑定必须指向**真实存在**且**已启用**的技能包 ——
        原先三条校验全缺（第 9 轮真机实测：技能不存在 / 未启用 / 员工键不在目录都能绑，可写入**悬空绑定**）。
        本轮落地域内两条：
        - 该 `skill_key` 在本租户**没有任何版本** ⇒ `SkillNotFound`（404）；
        - 有版本但**无 `enabled` 版本** ⇒ `SkillStateConflict`（409）「只有已启用的技能包可以绑定」。

        **闸门刻意放在幂等判定之前**：否则"已存在的绑定行"会成为绕过闸门的后门
        （技能停用后重复 `bind` 必须被拒，而不是继续返回 200 —— 这是本轮的行为变化，已登记）。
        **员工目录闸门（第 ③ 条）暂缓**：与第 9 轮「员工键可手动录入」的裁决冲突，需单独定夺。
        """
        ensure_can_bind(context)
        versions = self.store.list_versions(context, skill_key)
        if not versions:
            raise SkillNotFound(skill_key)
        if not any(item.status is SkillStatus.ENABLED for item in versions):
            raise SkillStateConflict("只有已启用的技能包可以绑定")
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
        """解除某员工对该技能的绑定（active → disabled）；角色口径同绑定（仅 `super_admin`）。"""
        ensure_can_bind(context)
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
        """绑定关系列表（**仅 `super_admin`**）。

        2026-09-20 第 9 轮：本方法原先**只转发仓储**（零角色判定，仓储仅按租户过滤）
        ⇒ 任何调用方若忘了在路由加闸门，就会把本租户全部"技能 ↔ 员工"绑定关系裸给任意登录角色。
        现按 fail-closed 口径在**服务层**也判一次（与绑定 / 解绑同一判定函数）。
        """
        ensure_can_bind(context)
        return self.store.list_bindings(context, agent_key=agent_key, skill_key=skill_key, limit=limit, offset=offset)

    def list_enabled_for_agent(self, context: UserContext, agent_key: str) -> list[Skill]:
        return self.store.list_enabled_for_agent(context, agent_key)

    def expanded_tools_for_agent(self, context: UserContext, agent_key: str) -> tuple[str, ...]:
        """该数字员工实际可见的工具键 = 已启用技能 allowed-tools 并集 ∩ ToolSpecCatalog 键集。

        §2.4 / §1.2 D：**取交集、fail-closed**——目录可升级，技能允许集随目录收窄；
        目录外的键一律不展开。返回排序元组。

        2026-09-20 第 9 轮：补岗位闸门 —— 原先只看登录（真机实测四角色全放行，含 `customer_admin`），
        与矩阵 §3 末列「技能域 `customer_admin` 一律 ❌」不符；现为四个业务角色可读、`customer_admin` ⇒ 403。
        """
        ensure_can_view_agent_tools(context)
        skills = self.store.list_enabled_for_agent(context, agent_key)
        union: set[str] = set()
        for skill in skills:
            union.update(skill.allowed_tools)
        return tuple(sorted(union & set(self.catalog_tool_keys)))

    # ------------------------------------------------------------ M3 打通：技能 ↔ 记忆（经验沉淀）

    def save_experience(self, context: UserContext, skill_key: str, version: str, *, content: str):
        """把技能使用经验沉淀为**事实类记忆**（M3 打通，规格 §2.8 / §4 M3）。

        - 前提：技能包对当前操作者可见（复用 `get_skill` 的归属 / 未审 404 语义）；
        - 记忆正文加技能引用前缀 `[skill:{skill_key}@{version}] {content}`（可检索加工技能键；
          检索时经向量/文本命中「这个技能怎么用」）；
        - 归属操作者自己（`owner_kind=user, owner_id=context.user_id`），scope 固定 user（本人语义）；
        - 幂等：`idempotency_key = skill-exp:{skill_key}:{version}:{sha256(content)[:16]}`——
          同一经验文本重复提交返回既有记录，不重复沉淀；
        - 记忆层未注入 / 不可用 → `SkillMemoryUnavailable`（503，fail-closed，不静默降级）。
        """
        skill = self.get_skill(context, skill_key, version)  # 可见性 + 404 语义
        if self.memory is None:
            from .models import SkillMemoryUnavailable

            raise SkillMemoryUnavailable("技能经验沉淀依赖的记忆层未接线")
        if not isinstance(content, str) or not content.strip():
            from .models import InvalidSkillPackage

            raise InvalidSkillPackage("经验内容不能为空")
        tagged = f"[skill:{skill.skill_key}@{skill.version}] {content.strip()}"
        idempotency_key = (
            f"skill-exp:{skill.skill_key}:{skill.version}:"
            f"{self._content_digest(content.strip())[:16]}"
        )
        try:
            fact = self.memory.create_fact(
                context,
                content=tagged,
                scope="user",
                owner_kind="user",
                owner_id=context.user_id,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:  # 记忆层业务异常（缺向量 / 预算 / 维度等）
            if isinstance(exc, SkillError):
                raise
            from .models import SkillMemoryUnavailable

            raise SkillMemoryUnavailable(f"技能经验沉淀失败：{exc}") from exc
        return {"fact": fact, "tagged_content": tagged, "idempotency_key": idempotency_key}

    @staticmethod
    def _content_digest(text: str) -> str:
        import hashlib

        return hashlib.sha256(text.encode("utf-8")).hexdigest()

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