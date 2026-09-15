"""技能包校验器：解析 / 校验 frontmatter + D11 注入防护 + 内容指纹派生。

口径见 `docs/superpowers/specs/2026-09-15-skill-layer-p4-design.md` §2.1 / §2.3。

`SkillPackageValidator` **不接触存储**——纯校验 + 派生不可变 spec；登记由服务层做（服务层调
`store.submit`）。任一校验不通过抛 `InvalidSkillPackage`（422）或 `SkillSourceDenied`（403），
不登记（fail-closed）。

D11 类防护（§2.3）：`description` 写入阶段扫描「自我授权 / 绕过权限」指令，命中即 422。
这里自实现一版小型扫描（不复制对话层 D11 实现）：对文本做全半角归一 + 去分隔符归一后，
匹配「规避词 × 管控词」共现或强自授权短语。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .models import (
    MAX_DESCRIPTION_LENGTH,
    InvalidSkillPackage,
    SkillSourceDenied,
    normalize_content_body,
    normalize_license,
    normalize_skill_key,
    normalize_version,
)

# 全半角映射（0xFF01..0xFF5E → 0x21..0x7E），归一英文标点/空格为半角，便于去分隔。
_FULLWIDTH_TO_HALF = {0xFF01 + i: 0x21 + i for i in range(0x5E)}
# 去分隔符（空白、常见标点、下划线、点、短横线、斜杠、反斜杠、引号等）与统一小写。
_SEP_RE = re.compile(r"[\s.,;:!?()[\]{}_'\"`~\-—_/|\\+=*#@$%^&<>]+")

# 强自授权短语（命中即拒，无需共现对）。
_STRONG_PATTERNS = (
    "自我授权", "授权给自己", "给自己添加权限", "给自己加权限",
    "让自己成为管理员", "提升我的权限", "授予自己管理员",
    "grantyourself", "makeyourselfadmin", "becomeadmin",
    "giveyourselfpermission", "selfauthorize", "grantmyself",
)
# 规避词（表示「绕过 / 跳过 / 忽略」类动作）。
_EVASION_WORDS = (
    "绕过", "跳过", "忽略", "规避", "蒙混", "擅自", "私自", "骗过", "越权", "逃过",
    "解除", "绕过校验", "绕过审核", "绕过审批", "免审", "免批",
    "bypass", "bypassing", "skip", "ignore", "circumvent", "workaround",
    "escalate", "elevate", "override", "waive", "grant", "disablecheck", "bypassthe",
)
# 管控词（权限 / 审批 / 审核 / 限制等被规避的目标）。
_CONTROL_WORDS = (
    "权限", "审批", "审核", "限制", "白名单", "许可", "审查", "校验", "管理员", "策略", "验证", "检查",
    "authorization", "approval", "approve", "permission", "restriction",
    "policy", "allowlist", "whitelist", "review", "admin", "validation", "access", "chek", "check",
)


@dataclass(frozen=True)
class SkillPackageSpec:
    """校验通过后的不可变技能包声明（供服务层登记落库）。"""

    skill_key: str
    version: str
    name: str
    description: str
    license: str
    allowed_tools: tuple[str, ...]
    source_key: str
    content_body: str = ""


def _normalize_scan_target(text: str) -> str:
    """归一扫描目标：全半角小写 + 去分隔符，使「解.除.限.制 / By-pas-set 审.核」等变体统一。"""
    half = text.translate(_FULLWIDTH_TO_HALF).lower()
    return _SEP_RE.sub("", half)


class SkillPackageValidator:
    """技能包准入校验（来源白名单 + 字段归一 + 工具键逐键 + D11 描述扫描）。"""

    def validate_package(
        self,
        *,
        skill_key: str,
        version: str,
        name: str,
        description: str,
        license: str,
        allowed_tools,
        source_key: str,
        allowed_sources: frozenset[str],
        catalog_tool_keys: frozenset[str],
        content_body: str = "",
        max_content_bytes: int = 64 * 1024,
    ) -> SkillPackageSpec:
        """全校验后返回不可变 spec；任一不通过抛 422 / 403，不登记。

        步骤（§2.1 / §2.3 / M5 裁决）：
        1. 来源 ∈ 部署注入白名单（否则 403，fail-closed）；
        2. 逐字段归一（skill_key / version / license / description 长度）；
        3. `allowed_tools` 每个键 ∈ 既有目录键集（逐键校验，未知键即 422）；
        4. D11 类描述灌注扫描（命中即 422）；
        5. `content_body` 体积上限（M5：库内落库；UTF-8 字节 ≤ max，默认 64 KiB）+ D11 扫描。
        """
        # 1. 来源白名单。
        if source_key not in allowed_sources:
            raise SkillSourceDenied("来源 key 不在部署注入白名单内")

        # 2. 逐字段归一（非法 / 超长抛 422）。
        clean_key = normalize_skill_key(skill_key)
        clean_version = normalize_version(version)
        clean_license = normalize_license(license)
        if not isinstance(name, str):
            raise InvalidSkillPackage("name 必须是字符串")
        clean_name = name.strip()
        if not clean_name:
            raise InvalidSkillPackage("name 不能为空")
        if not isinstance(description, str):
            raise InvalidSkillPackage("description 必须是字符串")
        clean_description = description.strip()
        if not clean_description:
            raise InvalidSkillPackage("description 不能为空")
        if len(clean_description) > MAX_DESCRIPTION_LENGTH:
            raise InvalidSkillPackage(f"description 最长 {MAX_DESCRIPTION_LENGTH} 个字符")

        # 3. allowed-tools 逐键校验（fail-closed）。
        tools = []
        for tool in (allowed_tools or ()):
            if not isinstance(tool, str):
                raise InvalidSkillPackage("allowed-tools 必须为工具键字符串数组")
            key = tool.strip()
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", key):
                raise InvalidSkillPackage(f"allowed-tools 含非法工具键：{key!r}")
            if key not in catalog_tool_keys:
                raise InvalidSkillPackage(f"allowed-tool 不在工具目录内：{key}")
            if key in tools:
                raise InvalidSkillPackage(f"allowed-tools 含重复工具键：{key}")
            tools.append(key)

        # 4. D11 类描述灌注防护（§2.3）。
        if self._scan_d11(clean_description):
            raise InvalidSkillPackage("description 包含自授权 / 绕过权限类指令，拒绝登记")

        # 5. 正文（M5 裁决：库内落库，体积上限 + D11 扫描）。
        clean_body = normalize_content_body(content_body, max_bytes=max_content_bytes) if content_body else ""
        if clean_body and self._scan_d11(clean_body):
            raise InvalidSkillPackage("content_body 包含自授权 / 绕过权限类指令，拒绝登记")

        return SkillPackageSpec(
            skill_key=clean_key,
            version=clean_version,
            name=clean_name,
            description=clean_description,
            license=clean_license,
            allowed_tools=tuple(tools),
            source_key=source_key,
            content_body=clean_body,
        )

    def _scan_d11(self, description: str) -> bool:
        """D11 类扫描：命中「自我授权 / 绕过权限」指令则返回 True（fail-closed，宁可误拒不放过）。

        归一后匹配两类信号：① 强自授权短语；② 规避词与管控词同现。
        """
        canonical = _normalize_scan_target(description)
        if any(p in canonical for p in _STRONG_PATTERNS):
            return True
        # 分段/独立信号更贴近真实意图，但仍保持 fail-closed：规避 + 管控 各命中即拒。
        has_evasion = any(w in canonical for w in _EVASION_WORDS)
        has_control = any(w in canonical for w in _CONTROL_WORDS)
        return has_evasion and has_control

    @staticmethod
    def compute_sha256(content_bytes: bytes) -> str:
        """`content_sha256`：包内容指纹（登记时计算，沙箱挂载前复核防篡改，§2.6）。"""
        return hashlib.sha256(content_bytes).hexdigest()

    @staticmethod
    def compute_sha256_from_text(text: str) -> str:
        """由技能包正文文本计算指纹（M5：content_body 的 UTF-8 字节指纹，须与 content_sha256 一致）。"""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()