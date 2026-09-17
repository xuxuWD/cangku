"""CRM 敏感字段密级（§2.2）：掩码 / 剥离两套出口 + 单一来源常量。

- **人类接口**（列表 / 详情响应）：`mask_record` 返回**掩码值**（`138****1234` / `a***@domain`），
  明文只能经专用 reveal 端点获取（服务端在接口层判定 + 审计）。
- **AI 输入 / 工具输出**：`to_safe_dict` 返回**剥离敏感字段**的 dict（字段值不出现在结果里）。

`phone` 复用既有 `app.audit.redaction.mask_phone`（单一来源，不复制实现）；
`mask_email` 在本模块实现（本地部分保留首字符 + `***`，域名保留）。
两函数均为纯函数（先写单测再实现，见 `tests/test_crm_masking.py`）。
"""

from __future__ import annotations

from .models import SENSITIVE_FIELDS, Account, Activity, Contact, Contract, Lead, Opportunity, Quote

# 掩码后的占位（剥离口径下敏感字段直接不出现在结果里）。
_MASK_SUFFIX = "***"


def mask_email(email: str) -> str:
    """邮箱脱敏：本地部分保留首字符 + `***`，域名保留；异常格式全量遮蔽。

    空串返回空串（不造占位）。非 ASCII / 缺 `@` 的输入一律全遮蔽，避免短值泄露。
    """
    text = (email or "").strip()
    if not text:
        return ""
    if "@" not in text:
        return "*" * len(text)
    local, _, domain = text.partition("@")
    if not local or not domain:
        return "*" * len(text)
    return f"{local[0]}{_MASK_SUFFIX}@{domain}"


def mask_phone_value(phone: str) -> str:
    """薄封装：保持单一来源（委托 `app.audit.redaction.mask_phone`）。"""
    from ..audit.redaction import mask_phone

    return mask_phone((phone or "").strip())


_MASKERS = {
    "phone": mask_phone_value,
    "email": mask_email,
}


def mask_sensitive_fields(object_key: str, payload: dict) -> dict:
    """对 dict 中的敏感字段做掩码（人类接口口径）；未登记对象 / 字段原样返回。"""
    fields = SENSITIVE_FIELDS.get(object_key)
    if not fields:
        return dict(payload)
    result = dict(payload)
    for name in fields:
        if name in result and isinstance(result[name], str):
            result[name] = _MASKERS[name](result[name])
    return result


def _record_to_dict(record: object) -> dict:
    return dict(vars(record))


def mask_record(record: object) -> dict:
    """把联系人 / 线索记录转为掩码版 dict（人类接口默认出口）。"""
    payload = _record_to_dict(record)
    object_key = _object_key_of(record)
    if object_key is None:
        return payload
    return mask_sensitive_fields(object_key, payload)


def to_safe_dict(record: object) -> dict:
    """把记录转为**剥离敏感字段**的 dict（AI 输入 / 工具输出唯一出口，§2.2 / §2.8）。

    敏感字段**整键移除**（不是掩码）——确保任何下游（模型网关 / 工具序列化器 / 帧）
    都不可能拿到字段值，哪怕是掩码形态。
    """
    payload = _record_to_dict(record)
    object_key = _object_key_of(record)
    if object_key is None:
        return payload
    for name in SENSITIVE_FIELDS.get(object_key, frozenset()):
        payload.pop(name, None)
    return payload


def _object_key_of(record: object) -> str | None:
    if isinstance(record, Contact):
        return "contact"
    if isinstance(record, Lead):
        return "lead"
    return None


# 可在智能层（LLM 输入 / 工具输出）出现的对象类型（用于类型标注与自检）。
SAFE_RECORD_TYPES = (Account, Contact, Lead, Opportunity, Activity, Quote, Contract)