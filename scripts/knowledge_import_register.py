"""知识治理层「存量文档导入登记」脚本（规格 §4 N1）。

用途
    治理层开启后，**未登记**的文档在检索谓词处 fail-closed（不可检索，规格 §2.3）。本脚本把
    存量文档批量登记为 `draft`（`source_key='migration'`，**owner 留空待人工补**——发布闸门
    仍要求 owner），使运维能把既有文档纳入治理表，再逐篇补负责人并发布。

数据来源（本期实现：清单文件）
    JSON：``{"documents": [{"document_id": "doc-1", "title": "差旅制度", "version": "1"}]}``
    CSV ：首行表头必须含 ``document_id`` 列（``title`` / ``version`` 可选）

    已知缺口（据实登记，绝不臆造上游接口）
        **WeKnora「列出文档」接口面未核实**：D1 只定死了检索（``POST /api/v1/knowledge-search``）
        与详情（``GET /api/v1/knowledge/{id}``），**没有**文档列表接口的官方口径 ⇒ 本脚本
        **不做** WeKnora 直拉，改由运维从 WeKnora 侧导出清单后喂入；上游接口面确认后，只需
        新增一个数据源函数（导入核心已与数据源解耦：``run_import`` 只吃 ``ImportEntry``）。

安全
    - **默认 dry-run**：不加 ``--apply`` **绝不写库**；只报告「将登记 / 已存在 / 拒绝」。
    - **校验复用服务层闸门**：逐条走 ``KnowledgeGovernanceService.register_document``（内部
      ``normalize_*``），与 API 完全同口径——脚本**不自造**第二套校验。
    - **逐行拒绝、不静默丢弃**：非法行（空/超长 document_id、非法 version 等）计入
      ``rejected`` 并打印原因；有 rejected 时退出码 1（让调用方看见）。
    - **幂等**：已登记的 ``(tenant, document_id)`` 一律 ``skipped``（服务层登记本身幂等），
      重复导入安全。
    - 只打印 DSN **主机与库名**，不含凭据；不打印标题等文档内容。

退出码：成功（含 dry-run）→ 0；有 rejected / 配置或运行失败 → 1；参数错误 → 2（argparse 默认）。

用法
    py scripts/knowledge_import_register.py --file docs.json --tenant-id t-1 --actor-id admin-1
    py scripts/knowledge_import_register.py --file docs.csv --tenant-id t-1 --actor-id admin-1 --apply
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain import UserContext
from app.knowledge_governance.models import (
    InvalidKnowledgeDoc,
    KnowledgeDocNotFound,
    KnowledgeGovernanceError,
)

# 导入来源：路由登记用 manual、接口注册用 api、**存量导入用 migration**（规格 §2.1 候选值）。
IMPORT_SOURCE_KEY = "migration"
MANIFEST_FORMATS = ("json", "csv")


@dataclass(frozen=True)
class ImportEntry:
    """清单一行（已通过结构解析；字段级校验在服务层闸门完成）。"""

    document_id: str
    title: str = ""
    version: str = "1"


@dataclass(frozen=True)
class ImportReport:
    created: tuple[str, ...]  # --apply 时=真登记；dry-run 时=将登记
    skipped: tuple[str, ...]  # 已存在（幂等跳过）
    rejected: tuple[tuple[str, str], ...]  # (document_id 或 "<空>", 原因)
    applied: bool

    def to_text(self) -> str:
        mode = "已登记" if self.applied else "将登记"
        lines = [
            f"知识文档导入登记：{'已写入' if self.applied else 'dry-run（未写库）'}",
            f"  {mode} {len(self.created)} 条 / 已存在跳过 {len(self.skipped)} 条 / 拒绝 {len(self.rejected)} 条",
        ]
        if self.rejected:
            lines.append("  拒绝明细：")
            lines.extend(f"    - {doc_id}：{reason}" for doc_id, reason in self.rejected)
        return "\n".join(lines)


def parse_manifest(text: str, *, fmt: str) -> tuple[list[ImportEntry], list[tuple[str, str]]]:
    """解析清单 → (entries, rejected)。

    **结构层**非法（非 JSON/CSV、缺 `documents` 数组、CSV 缺表头）→ 抛 ``ValueError``（整批拒绝，
    因为那说明喂错了文件）；**行层**缺 ``document_id`` → 计入 rejected、其余行继续。
    未知字段一律忽略（白名单口径）。
    """
    if fmt == "json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"清单不是合法 JSON：{exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("documents"), list):
            raise ValueError("JSON 清单必须是对象且含 documents 数组")
        raw_rows: list[object] = payload["documents"]
    elif fmt == "csv":
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None or "document_id" not in reader.fieldnames:
            raise ValueError("CSV 清单必须含 document_id 表头列")
        raw_rows = list(reader)
    else:
        raise ValueError(f"不支持的清单格式：{fmt}（可选 {'/'.join(MANIFEST_FORMATS)}）")

    entries: list[ImportEntry] = []
    rejected: list[tuple[str, str]] = []
    for index, row in enumerate(raw_rows, start=1):
        if not isinstance(row, dict):
            rejected.append((f"<第 {index} 行>", "行必须是对象"))
            continue
        document_id = str(row.get("document_id") or "").strip()
        if not document_id:
            rejected.append((f"<第 {index} 行>", "document_id 不能为空"))
            continue
        title = str(row.get("title") or "")
        version = str(row.get("version") or "1").strip() or "1"
        entries.append(ImportEntry(document_id=document_id, title=title, version=version))
    return entries, rejected


def run_import(
    service,
    context: UserContext,
    entries: list[ImportEntry],
    *,
    apply: bool,
) -> ImportReport:
    """逐条导入：已存在 → skipped；dry-run → 只报告；apply → 走服务层登记（同 API 口径）。

    字段级校验交给 ``service.register_document``（``InvalidKnowledgeDoc`` ⇒ rejected），
    脚本不自造第二套规则；``register_document`` 幂等，故重复导入安全。
    """
    created: list[str] = []
    skipped: list[str] = []
    rejected: list[tuple[str, str]] = []

    for entry in entries:
        try:
            service.store.get_document(context, entry.document_id)
        except KnowledgeDocNotFound:
            pass  # 未登记 → 待导入
        else:
            skipped.append(entry.document_id)
            continue
        if not apply:
            created.append(entry.document_id)  # dry-run：只报告将登记
            continue
        try:
            service.register_document(
                context,
                document_id=entry.document_id,
                title=entry.title,
                owner_id="",  # 规格 N1：owner 待人工补（发布闸门仍强制 owner）
                version=entry.version,
                source_key=IMPORT_SOURCE_KEY,
            )
        except (InvalidKnowledgeDoc, KnowledgeGovernanceError) as exc:
            rejected.append((entry.document_id, str(exc)))
            continue
        created.append(entry.document_id)

    return ImportReport(
        created=tuple(created), skipped=tuple(skipped), rejected=tuple(rejected), applied=apply
    )


def _target_hint() -> str:
    """目标库提示：只暴露主机与库名（不含凭据）。"""
    from app.settings import get_settings

    settings = get_settings()
    parsed = urlsplit(settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    database = parsed.path.lstrip("/") or "(未配置库名)"
    return f"{parsed.hostname or '(未配置主机)'}:{parsed.port or 5432}/{database}"


def _build_service():
    """装配治理服务（**仅 postgres**；显式传 store ⇒ 复用连接且**不跑迁移**——迁移由 API 进程负责）。"""
    from app.bootstrap import build_audit_service, build_knowledge_governance_service
    from app.knowledge_governance.store import PostgresKnowledgeGovStore
    from app.settings import get_settings

    settings = get_settings()
    if settings.storage_backend != "postgres":
        raise ValueError("存量导入必须使用 PostgreSQL 后端（内存后端不承接导入）")
    from psycopg_pool import ConnectionPool

    database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    pool = ConnectionPool(database_url, min_size=1, max_size=2, open=True)
    return build_knowledge_governance_service(
        settings,
        store=PostgresKnowledgeGovStore(pool),
        # 导入是治理动作：规格 §2.7 要求登记落 `knowledge.doc.registered`（actor = --actor-id），
        # **不得静默跳过审计**（与 worker 删除执行同口径）；迁移仍由 API 进程负责（migrate=False）。
        audit=build_audit_service(settings, connection=pool, migrate=False),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="存量知识文档导入登记（默认 dry-run；--apply 才写库）"
    )
    parser.add_argument("--file", required=True, help="清单文件路径（JSON 或 CSV）")
    parser.add_argument("--tenant-id", required=True, help="目标租户")
    parser.add_argument("--actor-id", required=True, help="操作人账号 id（写入审计 actor）")
    parser.add_argument(
        "--format",
        choices=MANIFEST_FORMATS,
        default=None,
        help="清单格式；缺省按扩展名判断（.csv → csv，其余 → json）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正写库（缺省 dry-run，只报告将登记/已存在/拒绝）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fmt = args.format or ("csv" if Path(args.file).suffix.lower() == ".csv" else "json")

    try:
        text = Path(args.file).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"读取清单失败：{exc}", file=sys.stderr)
        return 1

    try:
        entries, struct_rejected = parse_manifest(text, fmt=fmt)
    except ValueError as exc:
        print(f"清单解析失败：{exc}", file=sys.stderr)
        return 1

    try:
        service = _build_service()
    except (ValueError, ImportError) as exc:
        print(f"装配失败：{exc}", file=sys.stderr)
        return 1

    context = UserContext(args.tenant_id, args.actor_id, "super_admin")
    print(f"目标库：{_target_hint()}；租户：{args.tenant_id}；操作人：{args.actor_id}；格式：{fmt}")
    report = run_import(service, context, entries, apply=args.apply)

    rejected = struct_rejected + list(report.rejected)
    merged = ImportReport(
        created=report.created, skipped=report.skipped, rejected=tuple(rejected), applied=report.applied
    )
    print(merged.to_text())
    if not args.apply:
        print("（dry-run 未写库；确认无误后加 --apply 执行）")
    return 1 if merged.rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())