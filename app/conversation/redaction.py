"""对话消息正文脱敏（规格 §8 U23 裁决，2026-09-14）。

对话入口**不再把用户原始调用 JSON（或自由文本）逐字落**
`workbench_conversation_messages.content`，改落**脱敏引用 / 摘要**：

    调用 JSON ⇒ `tool_key` + 参数**键名清单** + 摘要指纹（sha256 前 8 位）
    其余输入 ⇒ 长度 + 摘要指纹

**所有参数值一律不落**（含 `body` 类与 `control` 类）。理由见 §8 U23「脱敏粒度」条：
① 与 §5 用例 33② 天然一致 —— `control` 的 `path` / `target` 若原样保留，会经
`GET /api/v1/conversations/{id}` 的 `messages[].content` **外泄**；② **fail-closed**
（默认不显示值，而非默认显示）；③ **不引入**「哪些 `control` 参数可显示」的**白名单**
（白名单一漏即泄漏）。

本模块是**三个写入点**（`execution.py` 的 `201` / `202` 两条，`service.py` 桩路径一条）的
**唯一**脱敏入口 —— 收敛为单一函数，防「改两处漏一处」。**不得**把任何参数值 / 自由文本原文
塞回 `content`，也**不得**把原文写进日志 / 审计明细 / 响应体。

⚠️ 指纹是**展示用**的短摘要（§4.1.4 序列化后 sha256 取前 8 位，**未做路径参数归一**），
**不等于**授权用的 `workbench_tool_actions.args_digest`（后者按完整参数 + `path_params` 算定）；
不得据此处指纹反推参数或与授权位做等价比对。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from ..tool_execution.args_digest import args_digest
from .models import MAX_MESSAGE_LENGTH

# 调用 JSON 的结构化字段（与 `execution.py` 的 `parse_tool_invocation` 同口径，此处不导入以避免环）。
_TOOL_KEY_FIELD = "tool_key"
_PARAMS_FIELD = "params"

INVOCATION_SUMMARY_PREFIX = "[工具调用·脱敏]"
FREETEXT_SUMMARY_PREFIX = "[消息·脱敏]"


def _fingerprint(params: Mapping[str, Any]) -> str:
    """参数摘要指纹：§4.1.4 序列化后 sha256 取前 8 位（**不含任何参数值**）。"""
    return args_digest(params).removeprefix("sha256:")[:8]


def _parse_invocation(content: str) -> tuple[str, Mapping[str, Any]] | None:
    """宽松解析「结构化工具调用」；非该形态返回 `None`（交给自由文本分支，绝不透传原文）。"""
    text = content.strip()
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    tool_key = payload.get(_TOOL_KEY_FIELD)
    params = payload.get(_PARAMS_FIELD, {})
    if not isinstance(tool_key, str) or not tool_key.strip():
        return None
    if not isinstance(params, dict):
        return None
    return tool_key.strip(), params


def redact_message_content(content: str) -> str:
    """把用户消息 `content` 收敛为**脱敏摘要**；**不落任何正文原文 / 参数值**（fail-closed）。

    `content` 可能是调用 JSON，也可能是自由文本 —— 两者都有安全处理：未知形态一律退化为
    「长度 + 指纹」，**绝不**把原文直接透传。
    """
    parsed = _parse_invocation(content)
    if parsed is not None:
        tool_key, params = parsed
        keys = "[" + ",".join(sorted(params, key=str)) + "]"
        summary = (
            f"{INVOCATION_SUMMARY_PREFIX} tool_key={tool_key} "
            f"params={keys} digest={_fingerprint(params)}"
        )
    else:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]
        summary = f"{FREETEXT_SUMMARY_PREFIX} chars={len(content)} digest={digest}"
    # 摘要只能比原文更短；仍防御性地兜住 `MAX_MESSAGE_LENGTH`，避免把合法请求打成 422。
    return summary[:MAX_MESSAGE_LENGTH]
