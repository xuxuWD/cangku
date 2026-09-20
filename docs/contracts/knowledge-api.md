# 「知识库」界面接口契约（第 7 轮）

> 状态：**v1 · 2026-09-19**（第 7 轮交付物；**契约先行**——本文件确认后才写码）。实施方案见
> [`knowledge-module-plan.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/knowledge-module-plan.md)。
> **唯一权威在别处**：权限口径 = [`permission-matrix.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/permission-matrix.md)；
> 知识分级 = [`knowledge-acl.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/knowledge-acl.md)；
> 治理语义 = `docs/superpowers/specs/2026-09-15-knowledge-governance-design.md`。本文件只声明**界面所需的最小接口集**，
> 与 `docs/api-contract.md`（后端契约真源）的关系是**只引用、不修改**。字段名与 `src/features/knowledge/types.ts` **逐字一致**。
> **所有形状与状态码均为 2026-09-19 真机实测**（本机工作树 `uvicorn` + 真库 + 本地 WeKnora 实例，`governance=true`；非生产）。

## 1. 接口清单与**角色门禁**（2026-09-19 按矩阵 §3 对齐，见 §11）

| 方法 | 路径 | 用途 | 角色门禁（`permission-matrix.md` §3） |
| --- | --- | --- | --- |
| GET | `/api/v1/knowledge/documents` | 文档列表（`status` 可选、`limit` 1–200、`offset`） | **治理读**：`ceo` / `super_admin` |
| POST | `/api/v1/knowledge/documents` | 登记（`document_id`/`title`/`owner_id?`/`version?`/`source_key?`；**幂等**） | **登记行**：`employee` / `department_lead` / `ceo` / `super_admin` |
| POST | `/api/v1/knowledge/documents/{id}/publish` | 发布（`draft` → `published`） | **管理行**：`ceo` / `super_admin` |
| POST | `/api/v1/knowledge/documents/{id}/archive` | 归档（→ `archived`，**终态，不物理删**） | `ceo` / `super_admin` |
| POST | `/api/v1/knowledge/documents/{id}/review?approved=<bool>` | 复核（人工事件；**`approved` 是必填 query**） | `ceo` / `super_admin` |
| POST | `/api/v1/knowledge/review-scan` | 触发到期扫描（`published` 且过期 ⇒ `needs_review`） | `ceo` / `super_admin` |
| GET | `/api/v1/knowledge/metrics` | 治理指标（Freshness Index） | `ceo` / `super_admin` |
| GET | `/api/v1/knowledge/governance/eligible` | 可检索（已发布）清单 | `ceo` / `super_admin` |
| POST | `/api/v1/knowledge/search` | 检索（**需 WeKnora 配置 + 治理开关**；未配置 ⇒ `503`） | **检索行**：`employee` / `department_lead` / `ceo` / `super_admin`（⚠️ 非管理角色**自限于自身角色**）；`customer_admin` ❌ |

**登记 ≠ 发布**：登记行对四个角色开放，但发布 / 归档 / 复核仍是管理行（`ceo` / `super_admin`）
⇒ 低权角色登记出的文档只停在 `draft`，**不进入可检索白名单**。

**检索行的自限（P0 安全要件，2026-09-19）**：`KnowledgeAccessRegistry.resolve` **不校验调用者身份**
（只按租户取绑定）⇒ 非管理角色强制 `role_key == 自身角色`、**不开放** `agent_key` 通道；
无绑定 ⇒ `200 items=[] reason="no_binding"`（fail-closed，**不请求上游**）。
管理角色不受限（治理台需按任意岗位 / 数字员工核查检索效果）。

**响应形状（实测，逐键点名）**
- 列表 / eligible：`{ items: KnowledgeDoc[], total, limit, offset }`
- `KnowledgeDoc`：`document_id / title / owner_id / status / version / source_key / last_reviewed_at / review_due_at / registered_by / created_at / updated_at`（**无正文**）
- `metrics`：`{ published, needs_review, archived, total, freshness_ratio }`（实测 `{"published":1,"needs_review":0,"archived":1,"total":3,"freshness_ratio":0.333…}`；`freshness_ratio` = `published / total`，**分母含 draft 与 archived**）
- `review-scan`：`{ reviewed_due: <int> }`（幂等）
- 检索：`{ items: Citation[], truncated, reason }`；`Citation` = `citation_id / content / source_title / knowledge_id / score`；
  `reason` 实测取值之一 `empty_whitelist`（见 §4）

## 2. 状态机（**实测**：动作 × 前置状态 × 结果）

| 当前状态 | publish | archive | review?approved=true | review?approved=false |
| --- | --- | --- | --- | --- |
| `draft` | ✅ → `published`（并置 `review_due_at = 发布时刻 + 宽限天数`，默认 30d） | ✅ → `archived` | ❌ `409`「当前状态不能进入该复核结果」 | ❌ `409` |
| `published` | ❌ `409`「当前状态不能发布（仅 draft 可发布）」 | ✅ → `archived` | ❌ `409`（复核只针对 `needs_review`） | ❌ `409` |
| `needs_review` | ❌ `409` | ✅ → `archived` | ✅ → `published` + **刷新** `last_reviewed_at` 与 `review_due_at`（**owner 空 ⇒ `422`**，见 §2.1） | ✅ → `archived` |
| `archived` | ❌ **`409`（实测）** | ❌ `409` | ❌ **`409`（实测）** | ❌ `409` |

- **到期扫描实测**：把某一篇 `review_due_at` 置为过去 ⇒ `POST /review-scan` 返回 `{"reviewed_due":1}` 且该篇 `published → needs_review`；复跑不再置位（幂等）。
- **`approved` 缺省即 `422`**（实测：不带该 query 参数调用 ⇒ `422`，属请求校验失败，**不是**状态冲突）。
- 发布还要求**已指定负责人**（`owner`）；未指定 ⇒ `InvalidKnowledgeDoc`（服务端文案「发布必须指定负责人（owner）」）。

### 2.1 P1 缺口与修复（2026-09-19 · **已修复，本表恢复成立**）

**原缺口（第 7 轮实测登记）**：`draft` + `review?approved=true` ⇒ **`200` → `published`**，且 `owner_id` 可为空。
根因：状态机 `transition_allowed` 允许 `draft → published`（该边本为「发布」而设），
而 `review_document` 只查状态边、**不查 owner 闸门** ⇒ **复核通道可代替发布并跳过「发布必须指定负责人」**。
（另实测：`review?approved=false` 在任意非终态也 ⇒ `200 → archived`，即复核退回等价于归档。）

**修复（用户 2026-09-19 裁决「双管」）**，两处均在 `app/knowledge_governance/service.py::review_document`：

1. **前置状态收窄**：只有 `needs_review` / `under_review` 可复核（`REVIEWABLE_STATES`）；
   其它状态（含 `draft` / `published`）⇒ **`409`**「只有待复核（needs_review）或复核中（under_review）的文档可以复核」。
2. **owner 闸门**：`approved=True` 进 `published` 的**任何路径**都要求 owner 非空；
   为空 ⇒ **`422`**「复核通过必须指定负责人（owner）」（与发布闸门同口径，纵深兜底历史 / 迁移数据）。

⇒ 本表 §2 的 `draft` / `published` 两行「复核」列的 `409` **重新成立**（此前曾实测为 `200`，见下方沿革）；
`needs_review` + 通过仍需 owner 非空（来自 published 的文档必有 owner，故正常路径不受影响）。
**回归证据**：`tests/test_knowledge_role_matrix.py` 的三条 P1 用例（收窄 / owner 闸门 / 合法路径不受影响）。

> **沿革（不删旧记录）**：2026-09-19 第 7 轮交付时曾按实测登记「补正一」（`draft` + 复核通过 ⇒ `200 → published`）
> 与「补正二」（复核退回任意非终态 ⇒ `200 → archived`）；两者描述的**修复前**行为，
> 修复后由本节的收窄闸门取代 —— 旧结论**不再成立**，保留于此仅供追溯。

## 2.2 状态机 → 界面按钮规则（实现口径，逐条可查）

| 动作 | 启用条件 | 禁用时的原因（`title`，原生提示，**不隐藏按钮**） |
| --- | --- | --- |
| 发布 | `draft` | `published` ⇒「只有草稿状态的文档可以发布；该文档已发布。」；`needs_review` ⇒「请先完成复核」；`archived` ⇒「终态，不能再发布」 |
| 归档 | `draft` / `published` / `needs_review` | `archived` ⇒「文档已归档（终态，不可恢复），不能再发布、归档或复核。」 |
| 复核通过 / 复核退回 | `needs_review` | 其它状态 ⇒「只有到期待复核的文档才需要复核。」；`archived` ⇒ 终态原因 |
| 任意状态 = 未定义取值 | — | 「该文档的状态未在界面定义，暂不能执行任何管理操作。」（**不误标**成已知状态） |

归档走 `DangerConfirm`（终态、不可恢复）；发布 / 复核直接提交。

## 3. 页面契约（一页四块）

| 块 | 数据源 | 交互 | 空态口径 |
| --- | --- | --- | --- |
| **文档列表** | `GET /knowledge/documents` | 行内「发布 / 归档 / 复核」按 §2 的合法前置状态**启用**，不合法一律**禁用 + 给原因**（不静默隐藏） | 「本租户还没有登记任何文档；登记并发布后才可被检索」（解释为什么空） |
| **登记** | `POST /knowledge/documents` | 抽屉：`document_id` + 标题（+ 可选负责人/版本/来源）⇒ 成功用**服务端回读值**提示，失败就地呈现、**不关抽屉** | — |
| **治理指标** | `GET /knowledge/metrics` | 只读四数 + `freshness_ratio`（**如实显示真实分母口径**） | 指标全 0 时照实显示 0（这是真实值），但不显示"没有数据"式含糊文案 |
| **待复核 / 可检索** | `GET /knowledge/governance/eligible` | 只读列表（`document_id` + 标题 + 复核到期） | 「当前没有可检索文档（需先发布）」 |
| （检索入口） | `POST /knowledge/search` | 见 §4；未配置 ⇒ 「服务未接入」说明（**不是空结果**） | — |

**四态**：加载 / 空 / 错误（可重试）/ 无权限；**无权限**整页 `PermissionGuard` 呈现（原因：见 §5），**不渲染任何编辑控件**。

## 4. 检索口径（**前端必须知道的三条**）

1. **范围由服务端解析**，客户端**不得**自带租户 / 知识库 id；请求体只有 `{ query, role_key | agent_key（二者恰一）, limit(1–50) }`。
2. **fail-closed 真机验证**：白名单为空（未登记 / 未发布）时**不请求上游**，返回 `200 items=[] reason="empty_whitelist"`；
   界面必须把 `empty_whitelist` 与「真的没查到」**分开呈现**（前者给"先登记并发布"的指引）。
3. **上游 fail-open 必须被下游收敛兜住**：实测 `knowledge_base_ids + knowledge_ids=[A]` ⇒ 上游**返回整库两条**（忽略文档白名单）
   ⇒ 客户端**不得**依赖上游过滤；真实防线是服务端 `scoped_search` 的返回后收敛（前端只呈现服务端最终结果，不做二次裁剪）。

## 5. 与已签矩阵的**实测偏差**（本轮登记，不改后端）

`permission-matrix.md` §3 写「知识：上传/登记 = 员工 ✅」，但**实测 6 个知识端点对 `employee` 一律 `403`**（含登记）。
⇒ 本模块按**实际门禁**实现：非超管进入 ⇒ **整页无权限态 + 原因**（引用服务端原文「只有超级管理员可以调整知识库范围 / 查看岗位与数字员工清单」同族文案），
并把该偏差登记进 `permission-matrix.md` 的交付记录（**P0 缺口：知识库对普通员工不可达，KB-02 不达标**）。

## 6. 未定义 / 未接入（本模块**不做**）

| 事项 | 原因 |
| --- | --- |
| 文档**正文**上传 / 下载 / 预览 | 本模块只登记元数据；正文在 WeKnora 侧（工作台视图不含正文） |
| 知识库**枚举**接口 | 后端无此端点（第 6 轮已登记同类缺口） |
| 文档级**四级 ACL** | `knowledge-acl.md` 字段未落库（属 Schema 线） |
| 批量登记 / 批量操作 | 后端无批量端点（`review-scan` 是唯一的批量动作） |
| 取消归档 / 复活 | `archived` 为终态（实测 `publish` 返回 `409`） |
| ~~**复核通道绕过 owner 闸门（P1 缺口）**~~ | ✅ **已修复（2026-09-19）**：复核前置状态收窄为 `needs_review` / `under_review` + 通过路径补 owner 闸门（见 §2.1）。原缺口：`draft` + `review?approved=true` 实测 `200 → published`（`owner_id` 可为空） |

## 7. 未验证（不得读成已验）

- **检索链路**：本机 WeKnora 为**外部自建实例**，非生产 / 客户侧；`top_k` 语义未核实（本轮 `limit` 只做服务端截断）。
- ~~本模块的**界面渲染层**尚无真机走查（写码后由收口人统一做）~~ ⇒ **已补：2026-09-19 收口验收 33/33 通过（见 §10）**。
- **检索冷启动首次可能 `504`**（收口验收观察，真机 1 次）：长时间空闲后首次检索，上游 `wk-app` 耗时 12.7s，
  超过适配层超时 ⇒ 服务端 `504`「知识检索服务超时，请稍后重试」；复测 0.2–0.7s 正常。属本机 CPU 推理环境特性，
  界面按错误态如实呈现（可重试），**不影响**「未配置 ⇒ `503`」口径。
- `draft` 状态的文档在**检索**中的行为（理论上不进白名单）未单独取证；`source_key` 的合法取值集合未穷举。
- 未测并发、未压测；未验证 LLM 摘要 / 问答链路（本机无 LLM）。
- **第 7 轮新增未验证**：`no_binding` / `no_hits` 两种空结果归因**未在真机单独构造**（仅验证了 `empty_whitelist` 与"有命中"两端）；
  文档列表**分页翻页**未走查（界面按单页上限 200 取数，超出仅给截断说明）；归档确认弹层未真机走查。

## 8. 变更留痕

- 2026-09-19：v1 建立（第 7 轮方案确认后、写码前落盘）；形状、状态码、状态机、fail-open / fail-closed 均为真机实测。
- 2026-09-19：**第 7 轮交付回写**——新增 §2.1（`draft`+复核的实测补正）/ §2.2（按钮规则）/ §9（实施落地口径）；
  §7 增补"本轮未验证"；实现与契约的差异逐条见 §9。
- 2026-09-19：**收口验收回写**——§2.1 追加「补正二」（`review?approved=false` 非终态 ⇒ `200 → archived`，探针 B 实测）；
  §7 更新（走查已补 + 新增冷启动 `504` 观察）；新增 §10（收口验收证据清单）。
- 2026-09-19：**两个缺口修复回写**——§1 换为「按矩阵 §3 的角色门禁」+ 自限口径；§2 表 `needs_review` 行补 owner 闸门；
  §2.1 由「实测补正」改写为「P1 缺口与修复（已修复）」并保留旧结论作沿革；§6 标记 P1 已修复；新增 §11。
  **注**：`permission-matrix.md` §3 是权限口径唯一权威，本次是**实现向矩阵对齐**（非改矩阵口径），
  仅同步了该表两处「现状描述」（检索行不再标注"现为唯一可用角色"、登记行去掉 🆕）。

## 9. 实施落地口径（第 7 轮交付 · 逐条可查）

**模块位置**：`workbench-web/src/features/knowledge/**`（替换占位页 `KnowledgePage.tsx`）。
`types.ts`（字段名与本节 §1 **逐字一致**） / `services/knowledgeService.ts`（唯一接线点） /
`components/{MetricsPanel,DocumentPanel,EligiblePanel,RegisterDrawer,SearchPanel}.tsx` / `__tests__/**`。

| 项 | 落地口径 |
| --- | --- |
| 页面结构 | 一页四块：`治理指标` / `文档列表`（含登记入口）/ `可检索文档`（含到期扫描）/ `知识检索` |
| 数据源 | 列表 `GET /documents`（`limit=200, offset=0`）；指标 `GET /metrics`；清单 `GET /governance/eligible`（**只读**）；写路径见 §1 |
| 状态标签 | 受控枚举 `draft/published/needs_review/archived`；**未知取值**渲染中性标签「未定义状态」并禁用全部动作（**不误标**） |
| 复核到期 | `review_due_at` 有值按 `YYYY-MM-DD HH:mm` 展示；为空写「未设置」（**不编造时间**） |
| 治理指标 | 四数 + `freshness_ratio`（`formatPercent`）；界面**必须**显示分母口径「分母为全部已登记文档，含草稿与已归档」；全 0 时照实显示 0 并说明原因 |
| 按钮规则 | 见 §2.2；不合法一律 `disabled` + `title` 原因（**不静默隐藏**）；归档走 `DangerConfirm`（终态） |
| 写成功提示 | **只用服务端回读值**（标题 + 状态取自响应）；样例模式（无服务端）明确「没有写入任何数据」，不伪造回读值 |
| 写失败 | 就地呈现：`409` 保留**服务端原文**（如「当前状态不能发布（仅 draft 可发布）」）；`422` 的 `detail` 为数组时由请求层丢弃 ⇒ 落本地固定文案「请求参数不合法，已拒绝。」；每条失败都附「本次没有写入任何数据」；抽屉**不关闭**、不假装成功 |
| 空态口径 | 列表：本租户还没有登记任何文档；登记并发布后才可被检索。清单：当前没有可检索文档（需先发布）（**解释为什么空**，不写"0 条"） |
| 检索请求体 | `{ query, role_key \| agent_key, limit }`（**恰一**；`agent_key` 由界面「数字员工」身份选择产生）；范围由服务端解析，客户端**不带**租户 / 知识库 id |
| 检索空结果 | 按 `reason` **分开呈现**：`empty_whitelist` ⇒ 给"先登记并发布"指引；`no_binding` ⇒ 提示先配置知识范围；`no_hits` ⇒ 只提示更换关键词（**不给**"先发布"指引）；`reason` 缺失 ⇒ 中性文案（不臆测） |
| 检索未配置 | `503` ⇒ 分类 `not_configured` ⇒ 呈现「服务未接入」说明（**不是空结果**、不是"没查到"） |
| 检索结果 | 只呈现服务端最终结果（`truncated` 时提示已截断），**不做二次裁剪**（数据归属由服务端 `scoped_search` 收敛保证） |
| 四态 · 无权限 | 整页 `PermissionGuard capability="knowledge.manage"`（**新增能力，仅 `super_admin`**）；非超管 ⇒ 无权限态 + 原因，**不请求任何数据、不渲染编辑控件** |
| 四态 · 其余 | 加载 = 骨架屏（不出现"暂无"）；空 = 上表文案；错误 = 可重试（点了会重新取数） |
| 状态保真 | 形状不符（缺 `items` / 缺指标必需键）**抛错**，绝不用 0 或空数组兜底（0 会被读成"真的是 0"） |
| 样例数据 | 仅 `import.meta.env.DEV` 存在；样例说明文案同样只在开发期存在 ⇒ 生产产物中样例标识 **0 命中** |
| 一致性 | 请求只走 `src/api/client.ts`；模式用 `serviceKit.resolveServiceMode()`；颜色 / 间距只取 `theme/tokens.ts`；组件只用 AntD + 既有自研组件 |

## 10. 收口验收记录（2026-09-19 · 收口人独立复核，非交付自验）

**门禁（收口人重跑）**：`tsc --noEmit` 退出码 0；`vitest run` **262/262**（38 文件）；`build` 成功。
**独立反假（2 组）**：① 状态机 `publish` 闸门改坏（`published` 行返回可发布）⇒ `KnowledgePage ②` + 服务纯函数**共 2 条红** ⇒ 还原复绿；
② `toReason` 恒 `null` ⇒ 「`empty_whitelist`」**红** ⇒ 还原复绿（knowledge 用例 30/30）。

**真机交叉验证**（`127.0.0.1:18112` 工作树后端 + 真库 + 本机知识服务；超管 `13600000001` / 员工 `13600000002` 双账号）：

| # | 操作 | 接口实测 | 查库核对 |
| --- | --- | --- | --- |
| 1 | 超管读 `documents` / `metrics` / `eligible` | `200` ×3；metrics `{"published":2,"needs_review":0,"archived":2,"total":5,"freshness_ratio":0.4}` | 与库逐行一致 |
| 2 | 超管检索（`{query, role_key=evidence-ops, limit}`） | `200`，`items=1`（取证文档A 真实引用）、`reason=null` | — |
| 3 | 员工 `metrics` / `documents`（POST，**带完整请求体**）/ `search` | **`403` ×3**（抽查；其余端点由交付自验 9/9 `403` + 服务端日志佐证） | — |
| 4 | 登记（**逐字复刻界面载荷**：`owner_id=""` / `version="1"` / `source_key="manual"`） | `201`，回读 `draft` + `owner_id=""` | ✅ 行与原值逐字段一致 |
| 5 | 登记 B（带 owner）→ 发布 → 复核退回 | `201` → `200`（`review_due_at` 恰为 +30d）→ **`200 → archived`** | ✅ 与接口回读一致 |
| 6 | 界面登记（幂等：同 `document_id` 同值重登记） | 抽屉正常关闭 + 「已登记：…（当前状态：草稿）」服务端回读提示 | ✅ 行未被改动（`updated_at` 不变） |

**浏览器走查**（`npx vite preview --port 4180`；脚本 [`tmp/r7-knowledge-walkthrough.mjs`](file:///d:/徐徐AI学习/公司工作台/tmp/r7-knowledge-walkthrough.mjs)）：
**33/33 通过**，0 控制台错误、0 页面异常、0 个 `4xx/5xx`；截图 `docs/screenshots/ui-v2-r7-knowledge/`（00–04）。
覆盖：四块齐备 + 「已接入真实数据」标识（无示例字样）；指标 `40.0%` 与分母口径；草稿行「发布」可用 / 已发布行禁用 + 原因 /
终态行四按钮全禁用 + 终态原因；到期扫描返回 `0 篇`；检索 1 条真引用；登记幂等成功；**员工侧整页无权限 + 0 次知识端点请求**。

**产物核检（ripgrep，UTF-8）**：本轮样例字样 `0` 命中（`示例文档` / `sample-*` / `「知识库」尚未接入` / 本轮样例说明句）；
`console.log` `0`；`Evidence-Pass` / `136xxxxxxxx` `0`（`password` 的命中全部来自 AntD 库内部实现）。
**遗留（非本轮引入）**：第 6 轮 `permissions.SAMPLE_DESCRIPTION` 与 `myWorkbench` 的「标记已读…」说明未做 DEV 门控
⇒ 字符串留在生产产物中（`http` 模式界面不渲染，属惰性残留）——登记待后续整改，**不在本轮范围内**。

**⚠️ 验收新增数据（待清）**：`r7-reviewer-a`（`draft`）/ `r7-reviewer-b`（`archived`，`owner=acct-reviewer-probe`）；
连同交付期 `probe-admin-1`（被复核探针置为 `published`）一并见 [`decision-log.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/decision-log.md) 清理清单。

> **时效说明**：以上走查（§10）执行于 **P0 修复之前**（当时"员工 ⇒ 整页无权限"是事实）。
> P0 修复后员工侧改为「登记 + 自限检索 + 治理三块给原因」视图，**该条走查结论已被 §11 取代**，
> 保留于此仅供追溯；P0 之后的新走查证据见 §11。

## 11. 两个已登记缺口的修复记录（2026-09-19 · 用户裁决后实施）

**背景**：第 7 轮登记两项须修缺口（`permission-matrix.md` §11 缺口表 / `decision-log.md` D-022）。
用户 2026-09-19 裁决：P0 **全量对齐矩阵**、P1 **双管（owner 闸门 + 收窄前置状态）**、**界面同轮对齐**、
非管理角色检索**自身角色自限**；顺序 = **先修缺口、再开第 8 轮模块**。

### 11.1 P0：知识端点角色门禁对齐矩阵 §3

| 项 | 内容 |
| --- | --- |
| 角色档位（单一来源） | `app/knowledge_governance/models.py`：`SEARCH_ROLES` / `REGISTER_ROLES`（四个角色）、`GOVERNANCE_ROLES`（`ceo` + `super_admin`）；`MANAGE_ROLES` 保留为 `GOVERNANCE_ROLES` 别名 |
| 闸门拆分 | 新增 `ensure_can_search` / `ensure_can_register`；`ensure_can_manage` / `ensure_can_read_metrics` 改为 `GOVERNANCE_ROLES`；`register_document` 改走登记闸门 |
| 绑定面 | `app/knowledge_policy.py::_ensure_admin` 与 `app/main.py::_ensure_knowledge_admin` 委派同一角色集合（`ceo` 亦允许） |
| **安全要件（自限）** | `app/main.py::_ensure_search_scope_self_limited`：非管理角色强制 `role_key == 自身角色`、**不开放** `agent_key`；否则填任意岗位键即可读到他人知识范围 |
| 报文变化 | 403 文案：管理面 →「只有企业负责人或超级管理员可以管理知识文档治理」；检索 →「当前角色不能检索知识文档」；登记 →「当前角色不能登记知识文档」；绑定 →「只有企业负责人或超级管理员可以调整知识库范围」 |

### 11.2 P1：复核通道不再绕过 owner 闸门

见 §2.1：前置状态收窄（`REVIEWABLE_STATES`）+ 通过路径 owner 非空（422）。

### 11.3 界面同轮对齐

- `src/app/session.tsx`：新增能力 `knowledge.search` / `knowledge.register`（四个角色）与 `knowledge.manage`（`ceo` + `super_admin`）；
  **未**把 `permission.manage` 开给 `ceo`（其依赖的岗位目录接口仍仅超管，见 11.4）。
- `src/features/knowledge/KnowledgePage.tsx`：按能力分三视图 —— 治理台（四块齐备）/ 员工视图（登记 + 自限检索 + 治理三块**只给原因、不请求数据**）/ 无能力（整页无权限 + 原因）。
- `SearchPanel`：新增 `fixedRoleKey`，非管理角色**不渲染身份选择**，请求体只带本人角色。

### 11.4 残留缺口（本轮**登记**，待专项裁决）

| 缺口 | 事实 | 影响 |
| --- | --- | --- |
| 矩阵 §3「知识：授权绑定」对 `ceo` 标注 ✅，但 `ceo` 实际**不可写**绑定 | 知识域闸门已放开，但写路径还要过**岗位目录**闸门（`app/workforce/store.py::_ensure_admin`，仍仅 `super_admin`） | 该行对 `ceo` 仅有"读"可达；处置（放开目录 / 修订该行 / 维持）待裁决 |
| 无 user→岗位 / 数字员工 归属链 | 平台无该映射（ADR-0004 未落部门 / 岗位实体） | 非管理角色的检索只能"按自身角色键"命中绑定；真正"按岗位"需等 Schema / 岗位实体线 |

### 11.5 验证

| 验证 | 结果 |
| --- | --- |
| 新增门禁锚点 | `tests/test_knowledge_role_matrix.py`（逐行钉矩阵 §3 + P1 三例 + fail-closed 自限）——**先红后绿**（修复前 14 条红） |
| 旧用例修正 | `test_knowledge_governance.py`（登记行改 ✅）、`test_knowledge_search_api.py`（改名与口径：他人 `role_key` ⇒ 403）、`test_workforce_roster_store.py`（`ceo` 可读绑定）、`test_knowledge_access_directory_gate.py`（ceo 被目录闸门拦 = 残留缺口事实钉住） |
| 后端全量 | `pytest -q`：**2503 passed / 0 failed / 140 skipped（既有跳过）**，退出码 `0`；`compileall` 退出码 `0` |
| 前端 | `tsc --noEmit` 退出码 0；`vitest run` **265/265**（原 262 + 新增 3：员工视图 / 自限检索请求体 / ceo 治理台）；`build` 成功；产物样例字样 / `console.log` `0` 命中 |
| **真机交叉验证**（工作树后端 + 真库 `workbench_test`；超管 `13600000001` / 员工 `13600000002`；**本机未配 WeKnora**，故检索落到 `503`） | ① 员工：治理读 `403` / **登记 `201`** / 发布 `403` / 指标 `403` —— 与矩阵 §3 逐行一致；② 员工填**他人** `role_key` ⇒ `403`「非管理角色只能检索与自身角色对应的知识范围」；填 `agent_key` ⇒ `403`「非管理角色不能按数字员工检索知识…」；**填本人 `role_key` ⇒ `503`**（越过闸门，仅因未配检索服务）✓ 自限生效；③ 超管填任意 `role_key` ⇒ `503`（管理角色不受限）✓；④ **P1**：`draft` + `review?approved=true` ⇒ **`409`**（原为 `200 → published`）；`published` + `review?approved=false` ⇒ **`409`**（原为 `200 → archived`）；**查库核对：两次被拒后该行状态未被改写** ✓ |
| 反假（3 组，均"改坏 → 必红 → 还原"） | ① `SEARCH_ROLES` 收回仅 `super_admin` ⇒ 检索行 5 条红；② 停用 `_ensure_search_scope_self_limited` ⇒ 3 条红（**且响应为 `200` 并真的读到他人范围**——正是要防的洞）；③ 停用复核前置状态收窄 ⇒ `test_review_rejected_for_non_reviewable_state` 红。三处还原后复绿，源码无探针残留（`grep 反假探针` = 0） |