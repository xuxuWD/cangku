"""参数规范化与摘要（`args_digest`，规格 §4.1.4）。

原则：**只做表示层归一**，不做任何"看起来一样就折叠"的模糊处理。

八条规则（逐条照抄 §4.1.4）：
1. 输入为 schema 校验通过后的 JSON 值；
2. 对象：键按 Unicode 码点升序排序；保留 `null` 值；「缺键」与「键=null」不同（不省略键）；
3. 数组：保持原顺序（不排序）；
4. 字符串：先做 NFC 归一；**仅对 schema 声明为「路径」的参数**再做 `/` 分隔归一、折叠 `.`/`..`、
   去尾部 `/`（根除外）、**不做大小写折叠**（执行环境为 Linux，大小写敏感）；
5. 数字：按类型分别序列化（整数 `1` 与浮点 `1.0` 摘要不同）；浮点不保留字面量差异；
6. 布尔：输出 `true` / `false`（小写）；
7. 序列化：`json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))`；
8. 摘要：`"sha256:" + sha256(utf8(序列化结果)).hexdigest()`。

⚠️ 本摘要按**完整参数（含 `body` 原文）**一次算定；`args_json` 只落控制参数（正文以占位常量替代），
**严禁**据 `args_json` 反算 `args_digest`（§4.1.1 边界第 2 条）。
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any, Iterable, Mapping


class ArgCanonicalizationError(ValueError):
    """参数值不是可规范化的 JSON 类型（fail-closed，不静默跳过）。"""


def _normalize_path_string(value: str) -> str:
    """路径参数的表示层归一（§4.1.4 规则 4）：分隔归一 / 折叠 `.`/`..` / 去尾部 `/`。"""
    value = unicodedata.normalize("NFC", value)
    absolute = value.startswith("/")
    out: list[str] = []
    for segment in value.split("/"):
        if segment == "" or segment == ".":
            continue
        if segment == "..":
            if out:
                out.pop()
            continue
        out.append(segment)
    normalized = "/".join(out)
    if absolute:
        return "/" + normalized
    return normalized


def _canonicalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, int):  # bool 已在上方拦截
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _canonicalize(value[key]) for key in sorted(value, key=str)}
    raise ArgCanonicalizationError(f"不支持的参数类型：{type(value).__name__}")


def canonicalize_params(
    params: Mapping[str, Any], *, path_params: Iterable[str] = ()
) -> dict[str, Any]:
    """规范化参数；`path_params` 内的顶层参数按路径规则归一。"""
    path_names = set(path_params)
    canonical: dict[str, Any] = {}
    for key in sorted(params, key=str):
        value = params[key]
        if key in path_names and isinstance(value, str):
            canonical[key] = _normalize_path_string(value)
        else:
            canonical[key] = _canonicalize(value)
    return canonical


def serialize_params(params: Mapping[str, Any], *, path_params: Iterable[str] = ()) -> str:
    canonical = canonicalize_params(params, path_params=path_params)
    return json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))


def args_digest(params: Mapping[str, Any], *, path_params: Iterable[str] = ()) -> str:
    """按 §4.1.4 产出 `args_digest`（`"sha256:" + hex`）。"""
    serialized = serialize_params(params, path_params=path_params)
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
