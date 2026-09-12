# 外部 Runtime Staging 前置预检 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增加一个 fail-closed 的 staging 前置预检，覆盖 RAGFlow/AgentScope（外部云服务）与 DeerFlow/Codex Worker/Hermes（本地独立进程），并把部署变量、验收证据和未完成边界写入现有文档。

**Architecture:** 预检脚本只读取部署环境中的非敏感元数据和密钥是否存在，不读取或打印密钥值；它检查环境、五类 Runtime 的固定版本、endpoint、能力白名单、认证注入标记（仅外部云服务必填）和独立 staging 标识。脚本不发起网络请求，不替代真实联调。现有 FakeTransport 与本地冒烟检查继续只承担开发期契约验证。

**Tech Stack:** Python 3.11+、标准库 `os`/数据类、pytest、现有 Markdown runbook。

---

### Task 1: Runtime staging preflight

**Files:**
- Create: `scripts/runtime_staging_preflight.py`
- Test: `tests/test_runtime_staging_preflight.py`

- [ ] **Step 1: Write failing tests** for missing configuration, insecure endpoints, unpinned versions, missing auth injection markers, and a valid non-secret configuration.
- [ ] **Step 2: Run the focused tests** and confirm the module is missing.
- [ ] **Step 3: Implement** `run_preflight(config=None)` and `PreflightReport`; accept an injected mapping for tests, otherwise read:
  - `WORKBENCH_ENV`
  - `WORKBENCH_STAGING_ID`
  - `WORKBENCH_RUNTIME_NETWORK`
  - 外部云服务（HTTPS + 认证必填）：`RAGFLOW_ENDPOINT` / `RAGFLOW_VERSION` / `RAGFLOW_CAPABILITIES` / `RAGFLOW_AUTH_INJECTED`；`AGENTSCOPE_*` 同形
  - 本地独立进程（http 亦可、认证可选）：`DEERFLOW_ENDPOINT` / `DEERFLOW_VERSION` / `DEERFLOW_CAPABILITIES`；`CODEX_WORKER_*`、`HERMES_*` 同形
  - 上列 Runtime 变量同时接受裸名与 `WORKBENCH_` 前缀名（与 `Settings` 的 `AliasChoices` 顺序一致：裸名优先，先命中者生效，即使为空串也不回退）
  The report must be `pass` only when environment is non-development, staging id is non-empty, external endpoints use HTTPS, local-process endpoints are `http(s)`, versions are fixed and not `latest/main/head`, every capability whitelist is non-empty, both external auth markers are truthy（大小写不敏感的 `true`/`1`/`yes`/`on`/`t`，与 pydantic 的 bool 解析同口径）, and network policy is non-empty. Never include endpoint query strings, auth values, or secret values in output.
- [ ] **Step 4: Run focused tests** and verify all pass.
- [ ] **Step 5: Commit** with `feat: 增加外部 Runtime staging 预检`.

### Task 2: Documentation and verification

**Files:**
- Modify: `.env.staging.example`
- Modify: `docs/superpowers/poc-runtime-config.example.yaml`
- Modify: `docs/superpowers/poc-staging-runbook.md`
- Modify: `docs/staging-acceptance-checklist.md`
- Modify: `docs/delivery-gates.md`
- Test: `tests/test_runtime_staging_preflight.py`

- [ ] **Step 1: Add example entries for all five runtimes**（RAGFlow/AgentScope 外部云服务，DeerFlow/Codex Worker/Hermes 本地独立进程）using placeholders only, with comments that endpoints and auth are injected by deployment; the staging template must also register every runtime's endpoint/version/capability whitelist so the preflight has a field shape to copy.
- [ ] **Step 2: Add the preflight command and explicit external-runtime acceptance steps**: health, RAGFlow scoped search/cross-tenant rejection, AgentScope lifecycle/unknown-event rejection, timeout/cancel/replay, and evidence retention.
- [ ] **Step 3: Preserve unchecked real staging gates** and explicitly state that the preflight is metadata-only and does not prove external service availability.
- [ ] **Step 4: Run `python scripts/runtime_staging_preflight.py --example`, focused tests, full pytest, compileall, and `git diff --check`.
- [ ] **Step 5: Commit** with `docs: 补充外部 Runtime staging 验收前置`.

### Task 3: Final review

- [ ] Review the diff from the current HEAD, verify no secret values or network calls were added, and record the result in the SDD progress ledger.

