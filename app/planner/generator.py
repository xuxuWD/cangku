from __future__ import annotations

import json
from typing import Any, Callable, Protocol

import httpx

from app.runtime.contracts import READ_KIND

from .models import (
    PlanGenerationError,
    PlannerNotConfigured,
    ToolCatalog,
)


class PlanGenerator(Protocol):
    key: str
    model_name: str | None

    def generate(self, goal: str, *, catalog: ToolCatalog, max_steps: int) -> list[dict[str, Any]]: ...


class MockPlanGenerator:
    """确定性生成器：只使用白名单里的只读工具，结果可重复。"""

    key = "mock"
    model_name = None

    def generate(self, goal: str, *, catalog: ToolCatalog, max_steps: int) -> list[dict[str, Any]]:
        catalog.require_configured()
        read_tools = [name for name in catalog.names() if catalog.resolve(name).kind == READ_KIND]
        if not read_tools:
            raise PlannerNotConfigured("未配置任何只读工具")
        selected = read_tools[:max_steps]
        return [
            {"step_id": f"step-{index + 1}", "tool": name, "args": {"goal": goal.strip()}}
            for index, name in enumerate(selected)
        ]


Transport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


class OpenAICompatiblePlanGenerator:
    """OpenAI 兼容的规划后端；任何失败都抛出明确错误，不降级为 Mock。"""

    key = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        api_key: str,
        timeout_seconds: float,
        transport: Transport | None = None,
    ) -> None:
        if not base_url or not model_name or not api_key:
            raise ValueError("真实规划模型需要配置地址、模型名和 API Key")
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._transport = transport or self._http_transport

    @property
    def url(self) -> str:
        """与内容模型同一套语义：地址带不带 `/v1` 都请求 `/v1/chat/completions`。"""
        return f"{self.base_url}/chat/completions" if self.base_url.endswith("/v1") else f"{self.base_url}/v1/chat/completions"

    def generate(self, goal: str, *, catalog: ToolCatalog, max_steps: int) -> list[dict[str, Any]]:
        catalog.require_configured()
        allowed = ", ".join(catalog.names())
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是执行计划生成器。只能使用这些工具："
                        f"{allowed}。只返回 JSON，形如 "
                        '{"steps": [{"step_id": "s1", "tool": "工具名", "args": {}}]}，'
                        f"步骤数不超过 {max_steps}。不要输出 kind、权限或审批字段。"
                    ),
                },
                {"role": "user", "content": goal},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            response = self._transport(
                self.url,
                {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                payload,
                self.timeout_seconds,
            )
        except Exception as exc:  # 网络、超时、HTTP 状态异常统一收敛
            raise PlanGenerationError("模型调用失败") from exc
        return self._parse(response)[:max_steps]

    @staticmethod
    def _http_transport(
        url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _parse(response: Any) -> list[dict[str, Any]]:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise PlanGenerationError("模型响应缺少可解析内容") from exc
        if not isinstance(content, str):
            raise PlanGenerationError("模型响应缺少可解析内容")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise PlanGenerationError("模型响应不是合法 JSON") from exc
        steps = parsed.get("steps") if isinstance(parsed, dict) else None
        if not isinstance(steps, list):
            raise PlanGenerationError("模型响应缺少步骤列表")
        cleaned: list[dict[str, Any]] = []
        for item in steps:
            if not isinstance(item, dict):
                raise PlanGenerationError("模型响应中的步骤必须是对象")
            step: dict[str, Any] = {
                "step_id": item.get("step_id"),
                "tool": item.get("tool"),
            }
            if "args" in item:
                step["args"] = item["args"]
            cleaned.append(step)
        return cleaned
