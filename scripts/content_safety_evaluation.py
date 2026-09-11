"""内容安全评估入口：对内容链路跑一遍安全用例并输出可存档的报告。

用途
    - 项 9「内容安全评估」的**证据产出工具**：把带 canary 的恶意素材喂进内容链路，
      产出逐用例的 pass/fail 结论（JSON 可存入 `.acceptance/<日期>-9-.../`）。
    - 离线运行（默认 Mock 生成器）只证明**仪器可判定、不误报**；
      **真实模型结论必须在配置了真实内容模型后重跑**（`WORKBENCH_CONTENT_GENERATION_BACKEND=openai_compatible`）。

前置
    - 使用专用评估租户与用户（默认 `safety-tenant` / `safety-evaluator`），不要用真实人员账号。
    - 仓储与生成后端取自部署配置（`Settings`）。离线跑可先设
      `WORKBENCH_CONTENT_STORE_BACKEND=memory` 避免落盘。

退出码
    `0` 全部用例通过；`1` 存在失败用例；`2` 配置/环境错误。

注意
    本报告的结论**不构成生产验收**：通过 ≠ 模型安全，只说明本套用例未发现标记外泄与状态被改。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bootstrap import build_content_generator, build_content_store
from app.content.safety import ContentSafetyEvaluator
from app.domain import UserContext
from app.settings import Settings, validate_runtime_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="公司工作台内容安全评估")
    parser.add_argument("--tenant-id", default="safety-tenant", help="评估专用租户（勿用真实租户）")
    parser.add_argument("--user-id", default="safety-evaluator", help="评估专用用户")
    parser.add_argument("--role", default="employee", help="评估身份角色，默认 employee")
    parser.add_argument("--output", default=None, help="将 JSON 报告写入指定文件")
    parser.add_argument("--json", action="store_true", help="以 JSON 打印报告（默认打印文本）")
    args = parser.parse_args(argv)

    try:
        settings = Settings()
        validate_runtime_settings(settings)
        content_store = build_content_store(settings)
        content_generator = build_content_generator(settings)
    except Exception as exc:  # noqa: BLE001 配置错误必须显式失败，不静默降级
        print(f"配置错误：{exc}")
        return 2

    from app.content.service import ContentService
    from app.runtime.service import RuntimeService
    from app.domain import TaskStore

    task_store = TaskStore()
    content_service = ContentService(
        task_store,
        RuntimeService(task_store),
        content_store,
        content_generator=content_generator,
    )
    actor = UserContext(tenant_id=args.tenant_id, user_id=args.user_id, role=args.role)
    report = ContentSafetyEvaluator(content_service, content_store).run(actor)

    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) if args.json else report.to_text())
    if args.output:
        Path(args.output).write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
