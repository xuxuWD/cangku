"""§5 用例 35：短期令牌的绑定强制与恒时比对（规格 §3.5 P1 第 3 条 ②④）。

校验点 ＝ **工作台控制面**（执行侧回调工作台时）。
六条：① 令牌与当前执行不匹配 → 拒；② 跨租户 → 拒；③ 旧代次 → 拒；④ 完全匹配 → 放行；
⑤ 容器侧伪造绑定声明无效果（服务端只以自己的权威记录为准）；⑥ 网关数据面不做绑定。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.audit.models import AuditAction
from app.tool_execution import token_binding
from app.tool_execution.gateway_token import GatewayTokenClient
from app.tool_execution.token_binding import (
    BindingDenied,
    ControlPlaneBindingVerifier,
    TokenBinding,
    TokenBindingStore,
    constant_time_equal,
)

ROOT = Path(__file__).resolve().parents[1]


class RecordingAudit:
    def __init__(self) -> None:
        self.calls: list[tuple[AuditAction, dict]] = []

    def record(self, action: AuditAction, **kwargs) -> None:
        self.calls.append((action, kwargs))


def make() -> tuple[ControlPlaneBindingVerifier, TokenBindingStore, RecordingAudit]:
    store = TokenBindingStore()
    audit = RecordingAudit()
    return ControlPlaneBindingVerifier(store=store, audit=audit), store, audit


def test_case_35_1_token_does_not_match_current_execution_is_denied() -> None:
    verifier, store, audit = make()
    # 为 run-A 的会话 / 代次签发并落绑定。
    store.record(token="tok-A", binding=TokenBinding("t-1", "sess-A", 1))
    # 却用于 run-B 的回调（当前执行 = 另一会话）。
    with pytest.raises(BindingDenied) as excinfo:
        verifier.verify(token="tok-A", expected=TokenBinding("t-1", "sess-B", 1), run_id="run-B")
    assert excinfo.value.http_status == 403
    # 不泄露存在性：文案固定，不含会话 / 代次 / 运行标识。
    assert "sess-B" not in str(excinfo.value)
    assert "run-B" not in str(excinfo.value)
    # 记审计（复用既有动作码，不新增）。
    assert [action for action, _ in audit.calls] == [AuditAction.TOOL_BLOCKED]


def test_case_35_2_cross_tenant_is_denied() -> None:
    verifier, store, audit = make()
    store.record(token="tok-1", binding=TokenBinding("t-1", "sess-A", 1))
    with pytest.raises(BindingDenied):
        verifier.verify(token="tok-1", expected=TokenBinding("t-2", "sess-A", 1))
    assert audit.calls  # 记审计


def test_case_35_3_stale_generation_is_denied() -> None:
    verifier, store, _audit = make()
    store.record(token="tok-old", binding=TokenBinding("t-1", "sess-A", 1))
    # 当前执行已是第 2 代（上一 turn 的令牌 = 旧代次）。
    with pytest.raises(BindingDenied):
        verifier.verify(token="tok-old", expected=TokenBinding("t-1", "sess-A", 2))


def test_case_35_4_exact_match_is_allowed_and_uses_constant_time_primitive(monkeypatch) -> None:
    verifier, store, audit = make()
    binding = TokenBinding("t-1", "sess-A", 3)
    store.record(token="tok-1", binding=binding)

    calls: list[tuple[str, str]] = []
    real = token_binding.hmac.compare_digest

    def spy(left, right):
        calls.append((str(left), str(right)))
        return real(left, right)

    monkeypatch.setattr(token_binding.hmac, "compare_digest", spy)

    result = verifier.verify(token="tok-1", expected=binding)

    assert result == binding
    # ④ 以「调用 constant-time 原语」为判据（不以计时为判据）。
    assert calls, "绑定比对必须调用 constant-time 原语"
    assert not audit.calls  # 放行不记拒绝审计


def test_case_35_5_forged_container_declaration_has_no_effect() -> None:
    """服务端只以自持记录为准：容器声明的绑定**被忽略**。"""
    verifier, store, _audit = make()
    store.record(token="tok-1", binding=TokenBinding("t-1", "sess-A", 1))

    # 情形一：当前执行与「服务端绑定」一致，但容器**谎报**成别的 → 仍放行（声明被忽略）。
    server_binding = TokenBinding("t-1", "sess-A", 1)
    assert verifier.verify(
        token="tok-1",
        expected=server_binding,
        claimed_binding=TokenBinding("t-9", "sess-Z", 99),
    ) == server_binding

    # 情形二：当前执行与服务端绑定不一致，容器**谎报**成一致 → 仍拒绝（伪造无效）。
    with pytest.raises(BindingDenied):
        verifier.verify(
            token="tok-1",
            expected=TokenBinding("t-1", "sess-B", 2),
            claimed_binding=TokenBinding("t-1", "sess-A", 1),
        )


def test_case_35_6_gateway_data_plane_does_not_do_binding() -> None:
    """网关数据面不得加绑定校验：绑定逻辑只存在于控制面模块。"""
    source = (ROOT / "app" / "tool_execution" / "gateway_token.py").read_text(encoding="utf-8")
    for forbidden in ("compare_digest", "TokenBinding", "verify_binding", "ControlPlaneBindingVerifier"):
        assert forbidden not in source, f"网关模块不得出现绑定校验：{forbidden}"
    # 网关控制面客户端只做铸造 / 吊销，不承担绑定强制。
    assert not hasattr(GatewayTokenClient, "verify_binding")
    assert not hasattr(GatewayTokenClient, "verify")
    # 绑定校验的落点是控制面模块（`token_binding`）。
    assert hasattr(token_binding, "ControlPlaneBindingVerifier")


def test_token_binding_store_revoke_clears_own_copy() -> None:
    store = TokenBindingStore()
    binding = TokenBinding("t-1", "sess-A", 1)
    store.record(token="tok-1", binding=binding)
    assert store.lookup("tok-1") == binding
    assert store.revoke("tok-1") is True
    assert store.lookup("tok-1") is None
    # 按绑定吊销（清多个副本）。
    store.record(token="tok-1", binding=binding)
    store.record(token="tok-2", binding=binding)
    assert store.revoke_binding(binding) == 2


def test_unknown_token_is_denied_without_leaking_existence() -> None:
    verifier, _store, audit = make()
    with pytest.raises(BindingDenied) as excinfo:
        verifier.verify(token="never-issued", expected=TokenBinding("t-1", "sess-A", 1))
    assert excinfo.value.http_status == 403
    assert audit.calls


def test_constant_time_equal_is_component_wise() -> None:
    assert constant_time_equal(TokenBinding("t-1", "s", 1), TokenBinding("t-1", "s", 1))
    assert not constant_time_equal(TokenBinding("t-1", "s", 1), TokenBinding("t-1", "s", 2))
    assert not constant_time_equal(TokenBinding("t-1", "s", 1), TokenBinding("t-1", "x", 1))
    assert not constant_time_equal(TokenBinding("t-1", "s", 1), TokenBinding("t-2", "s", 1))
