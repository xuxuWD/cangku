"""交付手册守护（真源 §7「私有部署交付包必须包含…客户管理员手册、员工手册和故障手册」）。

**为什么需要**：这三份手册是**交付包必含项**，此前**一份都不存在**（2026-09-19 审计发现：
全仓 grep 只命中真源本身）。手册属"写一次就没人再看"的文档类型 ⇒ 没有守护就会在下一次功能
变更后静默过期（同类漂移已发生过一次：运行详情页使用指南曾把**已交付**的验收能力写成「尚未交付」）。

本文件只守护**结构性事实**（存在 / 互链 / 覆盖真源要求的主题 / 如实声明边界），
**不**校验逐条文案是否与实现一致——那需要人读，属已登记的未验证项。
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HANDBOOKS = REPO_ROOT / "docs" / "handbooks"

EMPLOYEE = HANDBOOKS / "employee-handbook.md"
ADMIN = HANDBOOKS / "customer-admin-handbook.md"
TROUBLESHOOTING = HANDBOOKS / "troubleshooting-handbook.md"


def _text(path: Path) -> str:
    assert path.is_file(), f"缺少交付手册：{path.relative_to(REPO_ROOT)}（真源 §7 要求交付包必含）"
    body = path.read_text(encoding="utf-8")
    assert len(body) > 1500, f"{path.name} 内容过短（{len(body)} 字），疑似占位"
    return body


@pytest.mark.parametrize("path", [EMPLOYEE, ADMIN, TROUBLESHOOTING])
def test_handbook_starts_with_h1_title(path: Path) -> None:
    body = _text(path)
    assert body.lstrip().startswith("# "), f"{path.name} 缺少一级标题"
    assert "适用范围" in body, f"{path.name} 未写明适用范围（受众口径）"


def test_handbooks_link_to_each_other() -> None:
    """三份手册互为入口：读者从任一份都能找到另外两份（避免"走失"）。"""
    pairs = (
        (EMPLOYEE, ("customer-admin-handbook.md", "troubleshooting-handbook.md")),
        (ADMIN, ("employee-handbook.md", "troubleshooting-handbook.md")),
        (TROUBLESHOOTING, ("employee-handbook.md", "customer-admin-handbook.md")),
    )
    for path, targets in pairs:
        body = _text(path)
        for target in targets:
            assert target in body, f"{path.name} 未链接到 {target}"


@pytest.mark.parametrize("path", [EMPLOYEE, ADMIN, TROUBLESHOOTING])
def test_handbooks_declare_undelivered_boundaries(path: Path) -> None:
    """宪法 §9：不承诺未被证实的接入 / 效果 ⇒ 每份手册必须有如实边界声明。"""
    body = _text(path)
    assert "未交付" in body or "未验收" in body, f"{path.name} 没有如实声明未交付 / 未验收边界"


def test_admin_handbook_covers_the_required_topics() -> None:
    """覆盖真源 §6（导出 / 删除 / 保留）与 §7（交付包）要求管理员必须知道的面。"""
    body = _text(ADMIN)
    for topic in (
        "账号",           # 注册审批与登录安全
        "动态口令",       # 管理员 TOTP
        "数字员工",       # 岗位与数字员工配置
        "知识权限",       # 知识范围绑定
        "用量与费用",     # 整数分口径
        "数据导出",       # 异步导出 + 7 天过期
        "租户数据删除",   # 两步流程 + 确认人
        "保留策略",       # 默认口径 + 现状
        "审计",           # 审计查询与不可篡改
    ):
        assert topic in body, f"客户管理员手册缺少「{topic}」面"


def test_employee_handbook_covers_all_three_clients() -> None:
    body = _text(EMPLOYEE)
    for client in ("网页管理台", "手机伴侣端", "桌面端"):
        assert client in body, f"员工手册未覆盖客户端：{client}"


def test_troubleshooting_handbook_points_to_operational_entries() -> None:
    """故障手册必须指向**可执行 / 可读**的运维入口，而不是只讲道理。"""
    body = _text(TROUBLESHOOTING)
    assert "private-deployment-runbook.md" in body, "未指向部署运行手册（监控与回滚口径的唯一来源）"
    for script in ("monitoring_probe.py", "customer_acceptance_probe.py"):
        assert script in body, f"未指向只读探针：{script}"
        assert (REPO_ROOT / "scripts" / script).is_file(), f"引用的探针不存在：{script}"


def test_troubleshooting_handbook_forbids_unsafe_fixes() -> None:
    """宪法七章：不得用「吞异常 / 删报错」的方式"修"故障 ⇒ 手册必须把这条写给客户。"""
    body = _text(TROUBLESHOOTING)
    assert "报错原文" in body
    assert "三轮" in body, "未写「同一问题连续三轮未解决就停手」的刹车纪律"
