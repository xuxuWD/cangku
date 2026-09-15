"""知识治理层「存量文档导入登记」脚本（规格 §4 N1）。

用途
    治理层开启后，**未登记**的文档在检索谓词处 fail-closed（不可检索，规格 §2.3）。本脚本把
    存量文档批量登记为 `draft`（`source_key='migration'`，**owner 留空待人工补**——发布闸门
    仍要求 owner），使运维能把既有文档纳入治理表，再逐篇补负责人并发布。

数据来源（两种，缺省 file）
    ① **清单文件**（缺省）：JSON
       ``{"documents": [{"document_id": "doc-1", "title": "差旅制度", "version": "1"}]}``
       或 CSV：首行表头必须含 ``document_id`` 列（``title`` / ``version`` 可选）。
    ② **WeKnora 直拉**（``--source weknora``）：调上游文档列表
       ``GET /api/v1/knowledge-bases/{id}/knowledge``（官方契约 + 2026-09-15 真实实例实调），
       逐页拉到 ``total``；**N1 缺口已收口**（此前该接口面未核实，故只能人工导出清单喂入）。

安全
    - **默认 dry-run**：不加 ``--apply`` **绝不写库**；只报告「将登记 / 已存在 / 拒绝」。
    - **校验复用服务层闸门**：逐条走 ``KnowledgeGovernanceService.register_document``（内部
      ``normalize_*``），与 API 完全同口径——脚本**不自造**第二套校验。
    - **逐行拒绝、不静默丢弃**：非法行（空/超长 document_id、非法 version 等）计入
      ``rejected`` 并打印原因；有 rejected 时退出码 1（让调用方看见）。
    - **幂等**：已登记的 ``(tenant, document_id)`` 一律 ``skipped``（服务层登记本身幂等），
      重复导入安全。
    - **翻页上限 fail-closed**：WeKnora 直拉超出 ``--max-pages`` 即**报错退出**，绝不只导入一部分。
    - 只打印 DSN **主机与库名**、以及 WeKnora **主机名**（二者都不含凭据）；API Key 从不回显；
      不打印标题等文档内容。

退出码：成功（含 dry-run）→ 0；有 rejected / 配置或运行失败 → 1；参数错误 → 2（argparse 默认）。

用法
    py scripts/knowledge_import_register.py --file docs.json --tenant-id t-1 --actor-id admin-1
    py scripts/knowledge_import_register.py --file docs.csv --tenant-id t-1 --actor-id admin-1 --apply
    py scripts/knowledge_import_register.py --source weknora --knowledge-base-id kb-1 \\
        --tenant-id 10000 --actor-id admin-1 \\
        --weknora-base-url https://weknora.internal --weknora-api-key "$WORKBENCH_WEKNORA_API_KEY"
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain import PolicyError, UserContext
from app.knowledge import WeKnoraKnowledgeAdapter
from app.knowledge_governance.models import (
    InvalidKnowledgeDoc,
    KnowledgeDocNotFound,
    KnowledgeGovernanceError,
)

# 导入来源：路由登记用 manual、接口注册用 api、**存量导入用 migration**（规格 §2.1 候选值）。
IMPORT_SOURCE_KEY = "migration"
MANIFEST_FORMATS = ("json", "csv")
SOURCES = ("file", "weknora")


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


def fetch_entries_from_weknora(
    adapter,
    context: UserContext,
    *,
    knowledge_base_id: str,
    parse_status: str | None = None,
    page_size: int = 50,
    max_pages: int = 50,
) -> tuple[list[ImportEntry], list[tuple[str, str]]]:
    """从 WeKnora 文档列表构造导入条目（逐页拉取，N1 缺口收口）。

    - 逐页拉到 ``total``（或某页为空即止）；**超出 ``max_pages`` 直接抛 ``ValueError``**——
      绝不静默只导入一部分存量文档。
    - 条目 ``title`` 取上游 ``title``（适配器已在空标题时回退 ``file_name``）；``version``
      上游列表不含版本概念，统一取默认 ``"1"``（登记为 draft，待人工复核时校正）。
    - 上游条目缺 id ⇒ 计入 rejected（逐条不静默丢弃）。
    """
    entries: list[ImportEntry] = []
    rejected: list[tuple[str, str]] = []
    collected = 0
    total = 0

    for page in range(1, max_pages + 1):
        result = adapter.list_documents(
            context, knowledge_base_id, page=page, page_size=page_size, parse_status=parse_status
        )
        total = result.total
        for index, item in enumerate(result.items, start=1):
            document_id = str(getattr(item, "document_id", "") or "").strip()
            if not document_id:
                rejected.append((f"<第 {page} 页第 {index} 条>", "文档 id 不能为空"))
                continue
            entries.append(ImportEntry(document_id=document_id, title=str(getattr(item, "title", "") or "")))
        collected += len(result.items)
        if not result.items:
            break
        if collected >= total:
            break
    else:
        raise ValueError(
            f"WeKnora 文档列表超过翻页上限（{max_pages} 页 × {page_size} 条）——"
            "为避免只导入一部分存量文档已中止；请调大 --max-pages 或分批处理"
        )
    return entries, rejected


def _build_weknora_adapter(*, base_url: str, api_key: str, tenant_id: str, knowledge_base_id: str):
    """装配只读适配器：知识库白名单只有这一个库，租户取 ``--tenant-id``（WeKnora 空间标识）。"""
    return WeKnoraKnowledgeAdapter(
        tenant_id=tenant_id,
        api_key=api_key,
        knowledge_base_ids={knowledge_base_id},
        base_url=base_url,
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
    parser.add_argument(
        "--source",
        choices=SOURCES,
        default="file",
        help="数据来源：file＝清单文件（缺省）；weknora＝直拉上游文档列表",
    )
    parser.add_argument("--file", help="清单文件路径（JSON 或 CSV；--source file 时必填）")
    parser.add_argument("--tenant-id", required=True, help="目标租户（weknora 直拉时必须是上游空间标识）")
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
    # ---- WeKnora 数据源（--source weknora）----
    parser.add_argument("--knowledge-base-id", help="WeKnora 知识库 id（--source weknora 时必填）")
    parser.add_argument(
        "--weknora-base-url",
        default=os.environ.get("WORKBENCH_WEKNORA_BASE_URL", ""),
        help="WeKnora 基址（默认取环境变量 WORKBENCH_WEKNORA_BASE_URL）",
    )
    parser.add_argument(
        "--weknora-api-key",
        default=os.environ.get("WORKBENCH_WEKNORA_API_KEY", ""),
        help="WeKnora API Key（默认取环境变量 WORKBENCH_WEKNORA_API_KEY；**从不回显**）",
    )
    parser.add_argument(
        "--parse-status",
        default=None,
        choices=("pending", "processing", "completed", "failed"),
        help="只拉指定解析状态的文档（缺省不过滤，拉全库）",
    )
    parser.add_argument("--page-size", type=int, default=50, help="每页条数（默认 50）")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=50,
        help="翻页上限（默认 50）；超出即报错退出，绝不只导入一部分",
    )
    return parser


def _load_weknora_entries(args, context: UserContext) -> tuple[list[ImportEntry], list[tuple[str, str]]]:
    """装配只读适配器并拉取条目；失败抛 ``ValueError``（不含凭据）。"""
    if not args.knowledge_base_id:
        raise ValueError("--source weknora 必须提供 --knowledge-base-id")
    if not args.weknora_base_url or not args.weknora_api_key:
        raise ValueError(
            "WeKnora 凭据缺失：--source weknora 需要 --weknora-base-url 与 --weknora-api-key"
            "（或环境变量 WORKBENCH_WEKNORA_BASE_URL / WORKBENCH_WEKNORA_API_KEY）"
        )
    adapter = _build_weknora_adapter(
        base_url=args.weknora_base_url,
        api_key=args.weknora_api_key,
        tenant_id=args.tenant_id,
        knowledge_base_id=args.knowledge_base_id,
    )
    return fetch_entries_from_weknora(
        adapter,
        context,
        knowledge_base_id=args.knowledge_base_id,
        parse_status=args.parse_status,
        page_size=args.page_size,
        max_pages=args.max_pages,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    context = UserContext(args.tenant_id, args.actor_id, "super_admin")

    if args.source == "weknora":
        try:
            entries, struct_rejected = _load_weknora_entries(args, context)
        except (ValueError, PolicyError, RuntimeError, httpx.HTTPError) as exc:
            print(f"WeKnora 文档列表读取失败：{exc}", file=sys.stderr)
            return 1
        print(f"来源：WeKnora {urlsplit(args.weknora_base_url).hostname or '(未配置主机)'} / 知识库 {args.knowledge_base_id}")
    else:
        if not args.file:
            print("装配失败：--source file 必须提供 --file（清单文件路径）", file=sys.stderr)
            return 1
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
        print(f"来源：清单文件（{fmt}）")

    try:
        service = _build_service()
    except (ValueError, ImportError) as exc:
        print(f"装配失败：{exc}", file=sys.stderr)
        return 1

    print(f"目标库：{_target_hint()}；租户：{args.tenant_id}；操作人：{args.actor_id}")
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