"""存量文档导入登记脚本测试（规格 §4 N1）。

覆盖：清单解析（JSON/CSV）、**默认 dry-run 不写库**、apply 写入语义（draft + source_key
= 'migration' + owner 待补）、幂等跳过、非法行逐行拒绝、反假（dry-run 若写库必须变红）。
真库路径见 `tests/test_knowledge_governance_postgres.py`。
"""

from __future__ import annotations

import json

import pytest

from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import UserContext
from app.knowledge_governance.models import KnowledgeDocNotFound, KnowledgeDocStatus
from app.knowledge_governance.service import KnowledgeGovernanceService
from app.knowledge_governance.store import InMemoryKnowledgeGovStore
from scripts.knowledge_import_register import (
    IMPORT_SOURCE_KEY,
    ImportEntry,
    fetch_entries_from_weknora,
    main,
    parse_manifest,
    run_import,
)

TENANT = "t-1"
ADMIN = "acct-admin"


@pytest.fixture()
def service() -> KnowledgeGovernanceService:
    return KnowledgeGovernanceService(
        InMemoryKnowledgeGovStore(), audit=AuditService(InMemoryAuditStore()), review_grace_days=30
    )


def _admin() -> UserContext:
    return UserContext(TENANT, ADMIN, "super_admin")


# ------------------------------------------------------------ 清单解析

def test_parse_json_manifest_and_ignores_unknown_fields() -> None:
    text = json.dumps(
        {
            "documents": [
                {"document_id": "doc-1", "title": "差旅制度", "version": "2", "extra": "忽略"},
                {"document_id": "doc-2"},
            ],
            "generated_at": "2026-09-15",
        }
    )
    entries, rejected = parse_manifest(text, fmt="json")
    assert rejected == []
    assert [(e.document_id, e.title, e.version) for e in entries] == [
        ("doc-1", "差旅制度", "2"),
        ("doc-2", "", "1"),
    ]


def test_parse_json_rejects_structurally_wrong_manifest() -> None:
    with pytest.raises(ValueError):
        parse_manifest("[]", fmt="json")  # 必须是对象
    with pytest.raises(ValueError):
        parse_manifest('{"items": []}', fmt="json")  # 缺 documents
    with pytest.raises(ValueError):
        parse_manifest("not-json", fmt="json")


def test_parse_csv_manifest_and_missing_header() -> None:
    text = "document_id,title,version\ndoc-1,差旅制度,2\ndoc-2,,\n"
    entries, rejected = parse_manifest(text, fmt="csv")
    assert rejected == []
    assert [(e.document_id, e.version) for e in entries] == [("doc-1", "2"), ("doc-2", "1")]

    with pytest.raises(ValueError):
        parse_manifest("title,version\n差旅,2\n", fmt="csv")


def test_parse_rejects_rows_without_document_id() -> None:
    text = json.dumps({"documents": [{"document_id": ""}, {"title": "缺 id"}, {"document_id": "doc-ok"}]})
    entries, rejected = parse_manifest(text, fmt="json")
    assert [e.document_id for e in entries] == ["doc-ok"]
    assert len(rejected) == 2
    assert all("document_id" in reason for _doc_id, reason in rejected)


# ------------------------------------------------------------ 导入（dry-run / apply / 幂等）

def test_dry_run_never_writes(service: KnowledgeGovernanceService) -> None:
    """**默认 dry-run 绝不写库**（反假锚点：若 dry-run 分支被去掉/写库，本用例必须变红）。"""
    entries = [ImportEntry("doc-a"), ImportEntry("doc-b")]

    report = run_import(service, _admin(), entries, apply=False)

    assert report.applied is False
    assert report.created == ("doc-a", "doc-b")
    assert report.skipped == () and report.rejected == ()
    # 查库：两条都不存在
    for document_id in ("doc-a", "doc-b"):
        with pytest.raises(KnowledgeDocNotFound):
            service.store.get_document(_admin(), document_id)


def test_apply_registers_drafts_with_migration_source_and_empty_owner(service: KnowledgeGovernanceService) -> None:
    """apply：写入 draft + `source_key='migration'` + **owner 留空待补**；审计 actor 为操作人。"""
    entries = [ImportEntry("doc-a", title="差旅制度", version="2"), ImportEntry("doc-b")]

    report = run_import(service, _admin(), entries, apply=True)

    assert report.applied is True
    assert report.created == ("doc-a", "doc-b")
    stored = service.store.get_document(_admin(), "doc-a")
    assert stored.status is KnowledgeDocStatus.DRAFT
    assert stored.source_key == IMPORT_SOURCE_KEY
    assert stored.owner_id == ""
    assert stored.version == "2"
    assert stored.registered_by == ADMIN

    actions = {item.action.value for item in service.audit.store.list_recent(TENANT)}
    assert AuditAction.KNOWLEDGE_DOC_REGISTERED.value in actions


def test_repeat_import_is_idempotent(service: KnowledgeGovernanceService) -> None:
    """幂等：重复导入已登记的文档一律 skipped，不重复登记、不报错。"""
    entries = [ImportEntry("doc-a"), ImportEntry("doc-b")]
    run_import(service, _admin(), entries, apply=True)

    second = run_import(service, _admin(), entries, apply=True)

    assert second.created == ()
    assert second.skipped == ("doc-a", "doc-b")
    assert second.rejected == ()


def test_invalid_rows_are_rejected_not_silently_dropped(service: KnowledgeGovernanceService) -> None:
    """非法行（超长 document_id / 非法 version）逐行拒绝并给原因，合法行照常导入。"""
    entries = [
        ImportEntry("x" * 200),  # 超长 → 服务层闸门拒绝
        ImportEntry("doc-bad-version", version="v" * 64),  # version 超长 → 拒绝
        ImportEntry("doc-ok"),
    ]

    report = run_import(service, _admin(), entries, apply=True)

    assert report.created == ("doc-ok",)
    assert {doc_id for doc_id, _reason in report.rejected} == {"x" * 200, "doc-bad-version"}
    assert service.store.get_document(_admin(), "doc-ok").status is KnowledgeDocStatus.DRAFT


# ------------------------------------------------------------ WeKnora 数据源（N1 缺口收口）

class _FakeDocument:
    def __init__(self, document_id: str, title: str = "", parse_status: str = "completed"):
        self.document_id = document_id
        self.title = title
        self.parse_status = parse_status


class _FakePage:
    def __init__(self, items, *, page: int, page_size: int, total: int):
        self.items = tuple(items)
        self.page = page
        self.page_size = page_size
        self.total = total


class _FakeWeKnoraAdapter:
    """按页返回的假适配器；记录每次调用的参数。"""

    def __init__(self, pages: dict[int, _FakePage]):
        self.pages = pages
        self.calls: list[dict] = []

    def list_documents(self, context, knowledge_base_id, *, page=1, page_size=20, parse_status=None):
        self.calls.append(
            {"tenant": context.tenant_id, "kb": knowledge_base_id, "page": page,
             "page_size": page_size, "parse_status": parse_status}
        )
        return self.pages.get(page, _FakePage([], page=page, page_size=page_size, total=0))


def test_weknora_source_paginates_and_builds_entries() -> None:
    """翻页直到取满 total；条目字段对齐（空标题回退文件名）；**空 id 计入拒绝**而非静默丢弃。"""
    adapter = _FakeWeKnoraAdapter(
        {
            1: _FakePage(
                [_FakeDocument("doc-1", "差旅制度"), _FakeDocument("", "无 id 条目")],
                page=1, page_size=2, total=3,
            ),
            2: _FakePage([_FakeDocument("doc-2", "报销制度")], page=2, page_size=2, total=3),
        }
    )

    entries, rejected = fetch_entries_from_weknora(
        adapter, _admin(), knowledge_base_id="kb-1", page_size=2
    )

    assert [e.document_id for e in entries] == ["doc-1", "doc-2"]
    assert entries[0].title == "差旅制度"
    assert len(rejected) == 1 and "id" in rejected[0][1]
    assert [call["page"] for call in adapter.calls] == [1, 2]  # 取满即停，不多请求
    assert all(call["kb"] == "kb-1" for call in adapter.calls)


def test_weknora_source_fails_closed_when_list_exceeds_page_cap() -> None:
    """列表超出翻页上限 ⇒ **显式失败**（不得静默只导入一部分存量文档）。"""
    always_full = _FakePage([_FakeDocument(f"doc-{i}") for i in range(2)], page=1, page_size=2, total=999)
    adapter = _FakeWeKnoraAdapter({page: always_full for page in range(1, 10)})

    with pytest.raises(ValueError) as excinfo:
        fetch_entries_from_weknora(adapter, _admin(), knowledge_base_id="kb-1", page_size=2, max_pages=3)

    assert "上限" in str(excinfo.value)
    assert len(adapter.calls) == 3  # 到上限即停，不会无限翻页


def test_cli_weknora_source_requires_credentials(capsys) -> None:
    """weknora 数据源缺凭据/缺知识库 id ⇒ 退出码 1（fail-closed）；且**不回显密钥**。"""
    code = main(["--source", "weknora", "--tenant-id", TENANT, "--actor-id", ADMIN, "--knowledge-base-id", "kb-1"])
    assert code == 1
    err = capsys.readouterr().err
    assert "WeKnora" in err or "凭据" in err

    code = main(
        [
            "--source", "weknora", "--tenant-id", TENANT, "--actor-id", ADMIN,
            "--weknora-base-url", "https://weknora.internal", "--weknora-api-key", "sk-secret-value",
        ]
    )
    assert code == 1
    out = capsys.readouterr()
    assert "knowledge-base-id" in out.err
    assert "sk-secret-value" not in out.err and "sk-secret-value" not in out.out  # 密钥不得回显


# ------------------------------------------------------------ CLI（失败路径 fail-closed）

def test_cli_fails_on_missing_file(tmp_path, capsys) -> None:
    code = main(["--file", str(tmp_path / "nope.json"), "--tenant-id", TENANT, "--actor-id", ADMIN])
    assert code == 1
    assert "读取清单失败" in capsys.readouterr().err


def test_cli_fails_on_bad_manifest(tmp_path, capsys) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    code = main(["--file", str(bad), "--tenant-id", TENANT, "--actor-id", ADMIN])
    assert code == 1
    assert "清单解析失败" in capsys.readouterr().err


def test_cli_requires_tenant_and_actor() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--file", "x.json"])
    assert excinfo.value.code == 2  # argparse 参数错误