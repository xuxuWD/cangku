# 知识治理层（知识生命周期 + 检索谓词守卫） 立项规格

> **性质**：**阶段规格（唯一真源）**。本文定义「知识治理层」做什么、怎么做、怎么验收。
> **上位真源**：[`2026-09-12-conversational-agent-platform-design.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md)（对话层 / 知识范围绑定 P1 已交付）；[`capability-ownership-map.md`](file:///d:/徐徐AI学习/公司工作台/docs/capability-ownership-map.md) #12（**D1 已裁决：WeKnora 唯一主源**，RAGFlow 对照/实验）；[`multi-adapter-coexistence-spec.md`](file:///d:/徐徐AI学习/公司工作台/docs/multi-adapter-coexistence-spec.md)（企业知识检索归口）。
> **依据**：[`iteration-research-2026-09-15.md`](file:///d:/徐徐AI学习/公司工作台/docs/iteration-research-2026-09-15.md) §6.3（知识治理最小集：强制 owner/status、生命周期、事件触发复核、**过期从检索谓词下线**、Freshness Index）、§6.4（**pre-filter 必须进检索谓词**、clearance 从已校验身份取、忽略客户端传入）、§6.5（知识×工作流是护城河唯一自证价值闭环）、§6.6 坑 2（知识库无治理：owner/复核/归档仍可搜）；P3 记忆层 / P4 技能层已交付（本层与其并列，形成 M2 完整闭环）。
> **日期**：2026-09-15
> **状态**：**实施中**（2026-09-15 按 §2 落地，迁移 `032_knowledge_governance` 已建）。
> **前置**：D1 已裁决（WeKnora 唯一主源）；P1 知识范围绑定（`004`/`005`）已交付；P3 记忆层/P4 技能层已交付（本层不依赖其存储，但与其共用审计/权限设施）。

---

## 0. 真库回归记录（2026-09-15，本机 wb-test-postgres）

> **环境**：Docker `wb-test-postgres-1`（postgres 16，端口 55433），库 `workbench_test`；沿用 030/031 既有容器口径，未新增容器。

- **从零应用迁移**：32 条（`001` → `032_knowledge_governance`），含新表 `workbench_knowledge_documents`（复合主键 `(tenant_id, document_id)` + 状态 CHECK 约束 + 两个索引，`IF NOT EXISTS` 幂等）。
- **真库用例 `tests/test_knowledge_governance_postgres.py`：7 条全绿**：① 登记 + 状态流（draft→published→needs_review→published）真库持久化 + 复核时间戳落库；② **`draft` 可直接归档**（any→archived，§2.2 裁定）真库持久化；③ **N3 跨租户到期扫描**（两个租户各一篇到期 → 一次扫描全置位、未到期不动，写回逐条带租户）；④ 状态 CHECK 约束拦截非法状态值；⑤ 谓词守卫真库语义（仅 published 且未过 `review_due_at` 进白名单；过期即下线）；⑥ `mark_review_due` / 到期扫描真库可用且幂等；⑦ 生命周期 `list_all_for_tenant`/`delete_all_for_tenant`（N2 对称）。
- **反假口径**：draft 不进白名单（只发布可检索）、needs_review 被谓词排除、状态机 25 条边逐边锁定（§2.2 裁定，`test_transition_matrix_locks_section_2_2_ruling`）——真库与内存双端覆盖。
- **未验证（如实登记）**：`scoped_search` 与真实 WeKnora 的端到端检索（N2 落点：WeKnora 检索为知识库级、无文档级过滤参数，本期实现为「检索后按白名单收敛」的接口面兜底，标注见 `app/knowledge_governance/scoped_search.py`）；CI 侧取证见下。
- **CI 侧（2026-09-15）**：run `34960179880`（知识治理层初交付 push）与 run `34960954584`（口径裁定 push）**6/6 job 全绿**（含 backend 全量 pytest 在本仓库 Linux 环境通过）。⚠️ 上述两轮的 **postgres job 清单尚未包含本模块**（`ci.yml` 当时硬编码五个模块）⇒ 那时**不得读成「真库回归已被 CI 守护」**；本轮已补齐（`ci.yml` 加入 `test_knowledge_governance_postgres.py`，并在 `tests/test_ci_assets.py` 把 job 清单六条逐字钉死）。
- ✅ **CI 销账（2026-09-15）**：run **`34974145326`**（CI 纳入补齐 push）**6/6 job conclusion=success**；postgres job 原始日志取证：`newly applied` 列表含 **`032_knowledge_governance`**、`tests/test_knowledge_governance_postgres.py ...... [100%]`、**`真库用例：tests=51 skipped=0 failed=0`** ⇒ 知识治理真库回归**已由 CI 真实守护**（不再是 DSN 门控下的 skip）。

---

## 1. 范围

### 1.1 什么是「知识治理层」（边界定义）

让「进入企业知识检索的知识文档」有**生命周期**（谁拥有 / 什么状态 / 何时复核 / 过期即从检索下线），并在检索时由**服务端谓词**强制过滤（**pre-filter**，不是生成后过滤）。它**不是检索引擎**（检索仍是 WeKnora 唯一主源，D1），**不是范围绑定**（岗位/数字员工↔知识库绑定已由 `004`/`005` 交付）——治理层**在绑定之上**加一层「文档级」生命周期与新鲜度守卫。

### 1.2 做什么（六项）

| # | 事项 | 一句话 |
| --- | --- | --- |
| A | **知识文档注册表**（迁移 + 仓储） | `workbench_knowledge_documents` 表：租户语义 + 文档标识 + **owner + status + 版本 + 来源**；文档由治理层**登记**（WeKnora 侧索引仍是事实源，治理层是元数据守卫） |
| B | **生命周期状态机** | `draft → published → under_review → stale/needs_review → archived`（§6.3）；**事件触发复核**（非日历） |
| C | **发布闸门** | **发布强制 owner 与 status**（§6.3「最能防孤儿页」）；未登记文档一律不进检索 |
| D | **检索谓词守卫（pre-filter）** | 检索时服务端 SQL/谓词**只放行 `status='published'` 且未过期**的文档；`stale/archived` 从检索**下线**（§6.3「只归档没用，必须从谓词下线」）；**clearance 从已校验身份断言取，忽略客户端传入**（§6.4） |
| E | **Freshness Index** | 按期复核率作一等运营指标（`GET /api/v1/knowledge/metrics` 只读；供管理台预警） |
| F | **过期文档提示** | 检索命中已过期/待复核文档时，Quota 中提示「该文档已进入复核周期，结论可能过期」（服务端附加，不改引用内容） |

### 1.3 不做什么（明确排除）

1. **不做检索引擎**：检索仍走 WeKnora（D1 唯一主源）；治理层**不物化向量、不替代 RAGFlow 对照位**。
2. **不改知识库范围绑定**（`004`/`005` 语义与表不动）；治理层是**文档级**元数据，与绑定并列、不覆盖。
3. **不做文档全文入库**：只登记元数据（id/title/owner/status/版本/来源/时间戳补齐），正文仍在 WeKnora 侧。
4. **不做自动复核裁决**：复核是**人工事件**（§6.3「复核由事件触发」）；「到期待复核」只改状态进 `needs_review`，不自动归档/自动下线正文（除非状态机如此定义，见 §2.2）。
5. **不做 RBAC 重造**：权限沿用既有 `UserContext`/角色体系；本层只在检索谓词做**过滤**，不新建授权表。
6. **不引入新外部依赖**（许可证纪律延续）。

### 1.4 影响什么（改动面）

| 层 | 影响 |
| --- | --- |
| 数据库 | 新迁移 `032_knowledge_governance.sql`：`workbench_knowledge_documents`（含 `status` CHECK、`owner_id`、`last_reviewed_at`、`review_due_at`、`source_key`）+ 状态图审计列 |
| 后端 | 新模块 `app/knowledge_governance/`（模型/仓储/服务/状态机）；`app/knowledge.py` 的检索入口**加谓词守卫**（或封装成 `scoped_search` 组合件）；审计扩动作码 |
| 路由 | `/api/v1/knowledge/*` 增治理端点（登记/改状态/标记复核/指标），检索端点消费谓词守卫 |
| 契约 | `docs/api-contract.md` 增「知识治理（P5 前置）」章节 |
| 既有行为 | **检索默认行为不变**（未启用治理登记时，检索照常走 WeKnora）；治理端点启用后未发布文档从检索隐去。**旧文档（无登记）处理见 §5 N1** |

---

## 2. 设计

### 2.1 事项 A：知识文档注册表（迁移 032）

```sql
CREATE TABLE IF NOT EXISTS workbench_knowledge_documents (
    tenant_id        TEXT NOT NULL,
    document_id      TEXT NOT NULL,             -- WeKnora 侧文档 id（唯一事实源引用）
    title            TEXT NOT NULL,
    owner_id         TEXT NOT NULL,             -- 负责人（账号 id；发布时必填，§6.3）
    status           TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','published','under_review','needs_review','archived')),
    version          TEXT NOT NULL DEFAULT '1', -- WeKnora 侧版本或治理层登记版本
    source_key       TEXT NOT NULL DEFAULT 'manual',  -- 登记来源（manual / migration / api）
    last_reviewed_at TIMESTAMPTZ,
    review_due_at    TIMESTAMPTZ,               -- 复核到期（事件触发或显式设定）
    registered_by    TEXT NOT NULL,             -- 登记人
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, document_id)
);
CREATE INDEX IF NOT EXISTS idx_knowledge_docs_status ON workbench_knowledge_documents (tenant_id, status);
```

- **不做软删除**（文档「归档」= `status='archived'`，物理保留；重要数据软删除口径延续）。
- 与 `004` 绑定表**不建外键**（文档可能尚未绑定到任何岗位/员工，iliated 解耦，同 022 手法：目录可停用、历史可解析）。

### 2.2 事项 B：状态机（§6.3 生命周期）

| 现状 | 触发 | 迁移 | 约束 |
| --- | --- | --- | --- |
| `draft` | 登记 | 登记即 draft | owner 必填 |
| `draft` | 发布（人工） | → `published` | **发布闸门**：owner 非空 + status 合法（§1.2 C） |
| `published` | 到期 / 事件 | → `needs_review` | 事件触发（`PUT .../review-due` 或到期扫描 worker），**不自动归档** |
| `needs_review` | 复核完成 | → `published`（重新发布）或 → `archived`（判废） | 人工事件 |
| `published`/`needs_review` | 复核中 | → `under_review`（可选中间态） | 人工 |
| any | 归档（人工/复核判废） | → `archived` | 终态（不自动回 published） |

- **复核规则**：`needs_review`/`stale` 进入检索谓词**排除集**（§2.3）；人工复核后可回 `published`（刷新 `last_reviewed_at`/`review_due_at`）或 `archived`。
- **口径裁定（2026-09-15，用户拍板）**：末行「any → 归档」为**准确口径**——**`draft` 可直接归档**（登记后即判废，无需先发布）；§3.2 旧表曾把「draft→archived 直跳」列为 409，属**笔误**，已更正。`archived` 为终态（不回 `published`），`published→draft` / `needs_review→draft` 回退与 `draft→under_review` 一律非法。
- **事件触发而非日历**（§6.3）：到期入 `needs_review` 由**到期扫描 worker**（beat）批量置位 + 可配置 `WORKBENCH_KNOWLEDGE_REVIEW_GRACE_DAYS`；**不**由检索时顺手改状态（避免读路径写库）。
  - **落地（§4 N3，2026-09-15）**：beat 任务 `app.worker.scan_knowledge_review_due`（排程键 `knowledge-review-scan`，间隔 `WORKBENCH_KNOWLEDGE_REVIEW_SCAN_INTERVAL_SECONDS`）；跨租户取候选（`store.list_due_across_tenants`，**唯一跨租户查询**）→ 逐条以租户作用域置位 → 审计 actor 固定 `system:worker`、**按租户逐条**写。手动端点 `POST /api/v1/knowledge/review-scan` 保留（人工触发/排障）。

### 2.3 事项 D：检索谓词守卫（pre-filter，§6.4 硬要求）

检索入口（`WeKnoraKnowledgeAdapter.search` 的封装 `scoped_search`）**在请求 WeKnora 前**：

1. 由 `KnowledgeAccessRegistry.resolve` 得到 **knowledge_base_ids**（既有，租户内岗位/员工绑定）；
2. 由治理服务查该租户 **`status='published'` 且未过 `review_due_at`** 的文档集（**pre-filter**）→ 得到文档级白名单；
3. 白名单空 → 直接返回空结果（**fail-closed**，不请求 WeKnora）；
4. 否则把白名单传给 WeKnora（或按文档集合聚合成其查询参数——WeKnora 检索是知识库级，文档级过滤在返回后再收敛，见 §5 N2 的开项）。

**clearance 要求（§6.4）**：一切范围/权限从**服务端已校验身份断言**（`UserContext.tenant_id`/role）推导；客户端传入的设置一律忽略。语义缓存（如有）key 须含租户 + 角色 + **治理策略版本**。

### 2.4 事项 E：Freshness Index（一等运营指标）

```sql
-- 只读指标（可由查询推导，不建表）
SELECT
  COUNT(*) FILTER (WHERE status = 'published') AS published,
  COUNT(*) FILTER (WHERE status = 'needs_review') AS needs_review,
  COUNT(*) FILTER (WHERE status = 'archived') AS archived,
  COUNT(*) AS total
FROM workbench_knowledge_documents WHERE tenant_id = %s;
```
Freshness = `published / total`（按期复核率）。`GET /api/v1/knowledge/metrics` 返回以上字段 + `freshness_ratio`；仅 `super_admin` 可读。

### 2.5 事项 F：过期提示

检索命中**已进入复核周期（`needs_review`/`under_review`）的文档**时，响应为每条引用附加 `review_status`（服务端从谓词阶段的元数据显示映射追加，**不改引用正文**）：`{"...", "review_status": "needs_review", "review_hint": "该文档已进入复核周期，结论可能过期"}`。

### 2.6 配置项（外置）

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `WORKBENCH_KNOWLEDGE_REVIEW_GRACE_DAYS` | 30 | 到期扫描前置宽限（天）；`review_due_at` 未设的 published 文档不计入到期 |
| `WORKBENCH_KNOWLEDGE_REVIEW_SCAN_INTERVAL_SECONDS` | 3600 | 到期扫描 beat 间隔（秒；范围 30–604800）。worker 的 `knowledge-review-scan` 任务按此周期执行（§4 N3，2026-09-15 落地） |
| `WORKBENCH_KNOWLEDGE_GOVERNANCE_ENABLED` | false | 治理层总开关（fail-closed：关闭时**不**做文档级过滤，保持既有检索行为） |

### 2.7 审计

新动作码：`knowledge.doc.registered` / `knowledge.doc.published` / `knowledge.doc.archived` / `knowledge.doc.reviewed` / `knowledge.doc.review_due`；明细键最小集（`document_id` / `title` / `status` / `owner_id` / `version` / `source_key`，**不落正文**），入 `ALLOWED_DETAIL_KEYS`。

---

## 3. 验收

### 3.1 正常流程（查库验证）

1. 登记文档（`POST /api/v1/knowledge/documents`，owner 必填）→ 表内 `status='draft'`，`owner_id`/`source_key` 正确。
2. 发布（`POST .../{document_id}/publish`）→ `status='published'`。
3. 检索命中该文档且谓词放行（治理开启 + 未过期）→ 返回引用含服务端附加的元数据。
4. 到期扫描置 `needs_review` → 检索**不再命中**（谓词排除）→ Freshness 指标反映。
5. 复核回 published → 重新可检索，`last_reviewed_at` 刷新。

### 3.2 临界 / 异常与非法输入

| 用例 | 期望 |
| --- | --- |
| 未登录 / 过期 Token | 401 |
| 普通员工登记 / 发布 / 改状态 / 读指标 | 403（管理动作） |
| 发布无 owner | 422（发布闸门强制 owner） |
| 非法 status 迁移（published→draft 回退 / archived 终态出发 / draft→under_review） | 409（状态机校验）；**`draft`→`archived` 合法**（§2.2「any → archived」，2026-09-15 裁定） |
| 治理开关开启但文档集为空 | 检索返回空（fail-closed，不请求 WeKnora） |
| 治理开关关闭 | 检索行为与今天完全一致（不过滤） |
| 过期文档 | 检索不命中 + 指标 needs_review 计数 +1 |
| 未知 document_id | 404 |
| 传客户端伪造 scope/clearance | 忽略（服务端断言为准） |

### 3.3 反假测试

- 故意把 `status != published` 的文档留在预过滤白名单 → 「只发布可检索」用例必须变红。
- 故意删掉谓词守卫只留生成后过滤 → 「检索前不可见」用例必须变红（防安全回归）。
- 故意放开 `archived` 终态（允许 archived→published）→ 「终态不可回发布 / 不可复核」用例必须变红。
- 故意把 `draft→archived` 判为非法 → 「draft 可直接归档」用例必须变红（防口径回退，2026-09-15 裁定）。
- 故意拿未复核的 needs_review 文档做查询 → 「谓词排除」必须变红。

### 3.4 一键回归

`pytest` 全量（含新 `tests/test_knowledge_governance*.py`）+ CI 真库 job 纳入 `test_knowledge_governance_postgres.py`（同 DSN 门控模式；**2026-09-15 已纳入** `ci.yml` postgres job，并由 `tests/test_ci_assets.py` 的「模块清单逐条钉死」断言守护——取证见 §0「CI 侧」）。

---

## 4. 未决项 / 不在本期

| # | 项 | 状态 |
| --- | --- | --- |
| N1 | **存量文档（无登记）**：治理开启后，WeKnora 中已存在但未登记进治理表的文档如何处理 | **默认：不检索**（fail-closed，未登记视为不受控）；提供一次性「导入登记」迁移脚本（读 WeKnora 文档列表 → 批量登记为 draft，owner 待人工补）——需用户确认是否本期做导入脚本 |
| N2 | **文档级过滤的落点**：WeKnora 检索是知识库级，文档级白名单如何下传 | 两个方案：① 检索后按文档白名单**收敛结果**（简单，但「文本已被检索」——违反 §6.4 的 pre-filter 精神，仅当 WeKnora 无文档级过滤时兜底）；② 要求 WeKnora 支持文档级过滤参数（需上游接口面）。**裁决后定**——若上游不支持，选 ① 并明确记录「是接口面限制的兜底，不是设计偏好」 |
| N3 | 复核**到期扫描 worker**（beat 任务） | ✅ **已落地（2026-09-15）**：`app.worker.scan_knowledge_review_due`（排程键 `knowledge-review-scan`，间隔可外置 `WORKBENCH_KNOWLEDGE_REVIEW_SCAN_INTERVAL_SECONDS`，默认 1h）；候选跨租户、写回带租户、审计 actor=`system:worker`；手动端点 `POST /api/v1/knowledge/review-scan` 保留。**未验证**：worker 进程在真实部署拓扑下的 beat 联调（本机与 CI 均未起 Celery beat）。 |
| N6 | **首轮复核对齐**：`publish_document` 目前**不设** `review_due_at`（保持为空）⇒ 未被人工复核过的已发布文档**永不进入到期周期**（beat 只能捞到「复核过一次」的文档） | **待裁决**：A) 发布时置 `review_due_at = now + grace`（让首轮到期闭环，与 §2.6「到期扫描前置宽限」措辞一致）；B) 维持现状（首轮到期须人工设位）。**未擅自改**（属已交付行为，超出 N3 范围）。 |
| N4 | 文档级权限（某些文档仅部分岗位可见） | **不做**：文档级可见性收敛到知识库绑定粒度（`004`）；文档级 RBAC 属重造授权，明示排除 |
| N5 | 语义缓存 | 本期不建缓存；预留「key 含租户+角色+治理版本」口径，实现缓存时遵守 |

---

## 5. 风险与红线

1. **检索谓词守卫是安全门**（§6.4）：pre-filter 必须在**请求 WeKnora 前**完成；「检索后裁剪 = 已读到机密内容」是安全回归，反假必测。
2. **只归档不够，必须从谓词下线**（§6.3）：`archived`/`needs_review` 文档绝不能进检索结果（即使 WeKnora 侧仍可查）。
3. **治理层不是第二个真源**：WeKnora 索引仍是检索事实源；治理层只守卫「哪些可检索/何时复核」，不复制正文或重建索引。
4. **人工在环**：复核与发布是人工事件；到期自动进 `needs_review` 但不自动归档/自动下线（除非 2.2 状态机明文如此）。
5. **D1 不变**：治理层不改变 WeKnora 唯一主源；RAGFlow 仍对照/实验。
6. **许可纪律**：不引入新外部依赖。