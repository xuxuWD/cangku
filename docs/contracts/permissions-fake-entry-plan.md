# 权限配置「假入口」专项契约（第 15 轮）

> 状态：**v1.1（方向已裁决＝B；上游探测受阻，待选出路）** · 2026-09-21
> 上游登记：`decision-log.md` **D-036④**（第 12 轮"观察，未改，待裁决"）
> 唯一权威：权限口径 = `permission-matrix.md`；本模块接口口径 = `permissions-api.md`；知识分级 = `knowledge-acl.md`

---

## §1 背景（D-036④ 原文口径）

> `permissions`（知识范围）模块的候选仍是"现有绑定并集 + **手动录入**"，而它的写路径
> `PUT /api/v1/knowledge-access/agents/{agent_key}` **早已有目录闸门**（第 6 轮）⇒
> 那里存在**同类"能填、必拒"的假入口**；本轮未动该模块（超出本专项范围），登记待办。

本轮任务：把这条登记**核清、定性、并给出处置**。

---

## §2 勘察结论（读码 + 读表得出，四条事实）

**① 页面上的「行」不能手输 —— D-036④ 的类比不成立。**
`PermissionsPage` 的两块表格，行**全部来自目录**（`GET /api/v1/workforce/{roles|agents}`），
`ScopePanel` **只有「编辑范围」按钮、没有任何「新增绑定」入口**；抽屉里编辑的是
`knowledge_base_ids`，`binding_key` 只作为**只读标题**呈现。⇒ permissions 模块**不存在**
"手输 `agent_key` 被目录闸门 `409` 拒"这一形态（那是第 12 轮 `skills` 模块的形态）。

**② 真正能手输的是「知识库标识」，而后端不校验、也无从校验。**
`ScopeDrawer` 用 `<Select mode="tags">` ⇒ 任意字符串都能提交；后端
`knowledge_policy._normalize` **只做 `strip()` 去空白**，不查存在性；
落库列 `workbench_knowledge_access_bindings.knowledge_base_id` 是 **自由 `text`**；
`workbench_knowledge_documents` **没有** `knowledge_base_id` 列 ⇒
**平台内不存在任何"知识库"实体或目录表**（`permissions-api.md` §4 登记的"后端无枚举接口"由此而来）。

**③ 但这些标识是"真的会被用"的 —— 写错会静默无效，而不是不生效那么简单。**
`knowledge_governance/scoped_search.py` 把 `registry.resolve()` 得到的 kb 集合
**下推给上游**（`adapter.search(context, query, sorted(knowledge_base_ids))`），
即知识库是**上游 WeKnora 侧的概念**（本平台只持有 ID）。⇒ 手输一个上游并不存在的库：
保存成功、回读一致（`_normalize` 后原样存回），**检索时按该库下推、上游返回空** ——
**全程无报错、无提示**，操作者无法从界面上知道自己配错了。

**④ 准确定性（须更正 D-036④ 措辞）**：

| | 第 12 轮 skills 模块 | 本模块 |
|---|---|---|
| 输入 | 手输 `agent_key` | 手输知识库标识 |
| 写路径闸门 | **有**（目录闸门 ⇒ `409`） | **无**（不校验） |
| 真实后果 | **能填、必拒** | **能填、无人校验、写错静默无效** |

⇒ 两者**不是同一类**：前者是"假入口"（一定失败），后者是"**无护栏的真实入口**"（可能成功但可能配错）。
D-036④ 的原措辞属**定性不准**，本轮一并更正。

**⑤「对齐第 12 轮做法（取消手动录入）」在本模块不可行 —— 会死锁。**
候选来源只有"现有绑定并集 ∪ 变更记录里出现过的标识"（`collectCandidates`）。
若某租户**从未绑定过任何库**（本机真库即如此），候选为**空**；此时若取消手输，
则该租户**永远无法完成第一次绑定** ⇒ 功能完全不可用。
（第 12 轮 skills 模块能取消手输，是因为它另有**员工目录**作为真源；本模块**没有对应真源**。）

---

## §3 方案候选（待裁决）

| 方案 | 内容 | 代价 | 遗留 |
|---|---|---|---|
| **A. 只更正登记** | 只把 D-036④ 定性改准确 + 把 §2 事实写进 `permissions-api.md` | 文档改动 | 界面仍无护栏 |
| **B. 补真源（首选方向）** | 先**只读探测**上游 WeKnora 是否提供"知识库列表"接口；若有 ⇒ 后端加**只读代理端点** `GET /api/v1/knowledge/bases`，前端候选改由它填充、**保留手输兜底** | 需先核实上游能力 + 新端点（后端 + 前端 + 契约） | 上游若无该接口 ⇒ 回落到 C |
| **C. 诚实化（最小可做）** | 手输保留，但把入口写明白：① 标签/占位符改为"高级：手动录入标识"；② 固定说明写明"平台无法校验该标识是否存在，请与知识库实际标识保持一致"；③ **写成功后回读值原样呈现**（已有）；④ 对**从未出现过**的手输值给**黄色提醒**（不阻断） | 前端文案 + 一条校验提示 | 仍无法阻止配错 |
| **D. 只做软校验提醒** | 同 C 的 ④，不改任何既有文案 | 前端最小改动 | 护栏最弱 |

**建议**：**B（先核实上游）** → 不可行则落 **C**。理由：本模块缺的是"真源"，`D-036④`
反复出现的根因都是"候选只能靠手输"；补上真源能从根上消掉这个假入口，而 C 只是把风险写清楚。

---

## §4 待裁决项

**裁决记录（2026-09-21，用户）**：① 本轮方向 = **B（补真源）**；② **授权只读探测上游**；③ 手输能力（待定，B 亦建议保留兜底）；④ 更正 D-036④ 定性（建议，待确认）。

1. **本轮方向**：A / B / C / D（见 §3）。
2. **是否授权只读探测上游 WeKnora 的知识库列表能力**（只看有没有该接口、返回形状；不写入、不改上游配置）。
3. **手输能力是否保留**：B 亦建议保留（兜底）——除非用户要求彻底取消（将接受 §2⑤ 的死锁后果，需同时提供替代真源）。
4. **D-036④ 定性更正**：把"能填、必拒"改为"能填、无人校验、写错静默无效"（建议更正；这是诚实登记要求，若无异议即执行）。

---

## §5 影响面（方案定后细化）

- 后端（仅 B）：`app/main.py` 新只读端点 + `docs/api-contract.md`（**先写文档再写码**，契约覆盖守卫会拦）
- 前端：`workbench-web/src/features/permissions/{services,components,__tests__}`
- 文档：`permissions-api.md` §4 口径、`decision-log.md`（D-036 更正 + 本轮新条目）

## §6 复测清单（方案定后填）

- 待填：候选来源变化后的**空态**语义（"暂无可选清单"vs"确实没有库"）、死锁回归（新租户首次绑定）、
  非规范标识（大小写 / 空白 / 超长）行为、越权档位（`ceo` 可管理、其余 `403`）不回归。

---

## §7 上游只读探测记录（2026-09-21，**受阻，未取得结论**）

**授权**：用户 2026-09-21 授权"只读探测上游 WeKnora 的知识库列表能力"。

**执行**：`tmp/r15-weknora-probe.py`（**只发 GET**，不写入、不改上游配置、不打印密钥；脚本只输出
`base_url 是否已配置`、`api_key 长度`、上游**主机名**、候选路径的**状态码与响应键名**）。

**结果（结论：探测不可执行）**：

| 探测途径 | 结果 |
|---|---|
| ① 本机上游实例 `GET /api/v1/knowledge-bases`（与单数变体） | **不可执行** —— `get_settings()` 读出的 `weknora_base_url` 与 `weknora_api_key` **均为空**；`.env` 里**不存在任何 `WEKNORA` 键**（只核对了键名，未读取值） |
| ② 上游官方契约文档 `docs/api/knowledge.md`（代码注释多处引用其路径） | **不在本仓库**（全仓 Glob `**/api/knowledge*.md` 无命中）⇒ 无法从仓库内确证"是否存在列知识库的接口" |

**旁证（来自仓库内既有记录，非本轮实调）**：
- `2026-09-15-knowledge-governance-design.md` N1 段：上游端点 `GET /api/v1/knowledge-bases/{id}/knowledge`
  （**读某个库的文档列表**）**曾在本机自建实例上实调**（`data` 为数组已实证）；但**该实例已于 2026-09-16 清理**
  ⇒ 当前**无可用上游实例**（与 N1 登记"未在真实实例上端到端复跑"同一处境）。
- 同段还写明：**上游没有**"平台侧的知识库清单"这一概念落在我方 —— 适配器构造参数
  `knowledge_base_ids` 是"**本次已授权的集合**"（来自 `registry.resolve`，用于 `⊆` 校验），
  **不是**平台配置里的知识库目录（`app/knowledge.py::WeKnoraSearchRuntime.adapter_for`）。
  ⇒ **平台侧确实不存在任何知识库真源**，唯一真源在上游侧。

**⇒ 方案 B 的前置条件缺失，需用户提供其一（见 §8）**；在拿到之前**不得**凭印象假定上游接口存在
（凭文档臆测实现会产出"未实调"端点，须登记为未验证）。

### §7.2 第二轮探测：改走**上游公开官方文档**（2026-09-21，**取得结论**）

用户裁决"你来弄"后，我改从**上游公开源码仓库**核实（只读、无凭据需求）：
上游为**腾讯 WeKnora**（开源，`Tencent/WeKnora`，其仓库路径 `docs/api/*.md` 即本项目代码注释多处引用的
`docs/api/knowledge.md` 所在处——**该文档不在本仓库，属上游侧产物**）。

**确证事实（来源：`docs/api/knowledge-base.md`，该目录 README 自述"与 swagger 同步维护，差异以 swagger 为准"）**：

| 项 | 上游口径 |
|---|---|
| 接口 | **`GET /api/v1/knowledge-bases`** —— "**获取知识库列表**：返回当前空间拥有的全部知识库" ✅ **存在** |
| 认证 | 请求头 `X-API-Key`（与我方适配器现有做法一致） |
| Query | 仅 `agent_id`（可选）；**无分页参数** |
| 响应 | `{"success": true, "data": [ … ]}`；元素**字段结构同 `POST /knowledge-bases` 响应**（含 `name` / `description` / `type` / `created_at` 等），并额外带 `knowledge_count` / `chunk_count` / `processing_count` / `share_count` / `is_pinned` / `pinned_at` |
| 另有详情接口 | `GET /api/v1/knowledge-bases/:id`（示例 ID 形状 **`kb-00000001`**；详情含 `vector_store_*` 元数据，列表接口**不含**） |
| 相关能力（本轮不用） | `POST` / `PUT` / `DELETE` / `:id/pin` / `:id/hybrid-search` / `copy` / `:id/duplicate` / `:id/move-targets` |

**⚠️ 上游文档中的一条安全提醒（必须落到我们的设计里）**：
> "**API Key 代表您的账户身份，拥有完整的 API 访问权限**"；另存在"**限定知识库的 API Key**"（这类 Key 被限制，
> 传 `resource_urls=public` 会 `403`）。

⇒ 我方新增的代理端点必须**只发 GET 列表**、**绝不下发 Key / 上游主机名到前端**；响应不得包含密钥类字段。

**仍属未验证的部分（如实登记）**：**没有可用上游实例 ⇒ 上述接口从未被实调**（2026-09-15 那台自建实例已于
2026-09-16 清理；本机 `base_url`/`api_key` 为空）。故"元素里知识库 ID 的**确切键名**"（`id` 抑或其他）
**未经实测确认** ⇒ 实现必须**多键兼容解析**并把该不确定性写进文档，而非假定单一形状。

---

## §8 出路裁决（已定：**B2′ ＝ 按上游官方文档实现，登记"未实调"**）

**裁决过程与调整理由（2026-09-21）**：用户先选 **B1（提供只读实例实调）**，随后裁决"**你来弄**"。
我核查后确认 **B1 在本机不可执行**：无上游实例、`.env` 无任何 `WEKNORA` 键、docker 内无 WeKnora 镜像/容器，
**我也没有可自取的凭据**。于是改走**我能自取的最强证据** ⇒ §7.2 的上游**公开官方文档**
（已确证接口**存在**、认证方式、Query、响应形状与分析口径）。
据此定为 **B2′**：按官方文档实现**只读代理端点 + fail-closed 降级**，并把"**未实调**"如实登记、
对未实测的字段名做**多键兼容解析**。
若日后你提供一个**只读**上游实例（`base_url` + `api_key` 写进本机 `.env` 即可），**只需补一次实调**
就能把该端点从"未实调"升级为"已实调"（见 §11 补验动作）。

**以下为决策时的候选背景（保留备查）**：

| 出路 | 需要什么 | 我方动作 | 风险 / 登记 |
|---|---|---|---|
| **B1. 实调探测** | 一个**只读**上游实例地址 + API Key（可临时配置，用完即撤） | 跑 `tmp/r15-weknora-probe.py` 拿真实状态码与返回形状 ⇒ 按结果实现代理端点 | 需你提供凭据（可只给只读 Key）；配置只走环境变量，不落仓库 |
| **B2. 按文档实现** | 你确认"上游是否有列知识库的接口"及其路径 / 返回形状（或提供 `docs/api/knowledge.md`） | 后端加只读代理端点 + 前端候选改来源，**手输保留兜底** | 该端点**未经实调**，必须登记为未验证；且必须 **fail-closed**（上游不可用 ⇒ 明确报错，**不返回空列表冒充"没有知识库"**） |
| **B3. 暂缓 B，落 C** | — | 本轮只做 C（诚实化：入口写明白"平台无法校验该标识是否存在"+ 对从未出现过的手输值给黄色提醒，不阻断） | 最小、零上游依赖；B 挂为"待上游条件" |
| **B4. 更彻底：平台侧建库目录** | 评审（新表 + 与上游 kb 的映射口径） | 建 `workbench_knowledge_bases` 等实体 + 目录端点 | **地基级改动**（宪法：技术栈 / 数据模型改动须专项评审），不建议在本轮顺手做 |

---

## §9 接口设计（B2′，实现依据）

### §9.1 新端点

`GET /api/v1/knowledge/bases` —— **只读**知识库候选清单。

**响应模型（Pydantic，字段名待实现时按既有命名风格微调，语义不得变）**：

```json
{
  "upstream_available": true,
  "source": "upstream",
  "items": [
    {"knowledge_base_id": "kb-00000001", "name": "运维手册", "origin": "upstream"},
    {"knowledge_base_id": "kb-legacy-x", "name": null, "origin": "binding_only"}
  ],
  "note": null
}
```

- `origin`：`upstream`（出现在上游清单里）｜`binding_only`（**本租户绑定里出现过、但上游清单未返回**）
  ⇒ **后者正是"配错 / 库已被删"的可见化**，界面须据此给出黄色提醒（§9.3）。
- 降级（上游未配置 / 超时 / 非 2xx / 形状异常）：`upstream_available=false`、`source="local_only"`、
  `items` = 本租户绑定并集（`origin="binding_only"`）、`note` = 可读说明（**界面文案见 §9.3**）。
- **绝不**在上游不可用时返回空数组冒充"没有知识库"；`items` 为空也必须带 `note` 说明原因。
- 响应**不得**含 API Key、上游主机名、base_url、堆栈等（§7.2 安全提醒）。
- 不做缓存（打开抽屉时请求一次即可）；上游超时沿用既有适配器口径。

### §9.2 实现落点（**实现前先核对，不得臆测**）

| 位置 | 动作 |
|---|---|
| `docs/api-contract.md` | **先写文档**（新增 `/api/v1/knowledge/bases` 节）——**契约覆盖守卫会拦**（`tests/test_api_contract_coverage.py`） |
| `app/knowledge.py` | 新增上游**只读**列表方法（复用既有鉴权头与 JSON 解析风格）；**多键兼容解析** ID（`id` / `knowledge_base_id` / `kb_id`）与名称（`name` / `title`），§7.2 未实调 ⇒ 不假定单一形状 |
| `app/knowledge_policy.py` + 其 store | 新增"**本租户已绑定标识并集**"只读方法（跨租户必须按 `tenant_id` 过滤；参照第 11 轮教训：**编辑既有文件时逐段核对、不得误删**） |
| `app/main.py` | 新路由 + `response_model`；**权限判定复用既有知识范围管理判定**（`permission-matrix.md` 为唯一权威 —— **实现前先核对矩阵里"知识范围"行的四档角色**，与既有 `PUT /api/v1/knowledge-access/...` 保持一致，**不新造口径**）；403 判定**最早**执行 |
| `workbench-web/src/features/permissions/**` | 候选来源改为新端点；降级时如实提示；`origin="binding_only"` 给出黄色提醒；**手输保留**（§2⑤ 死锁约束） |

### §9.3 前端交互（含文案口径）

1. **候选来源**：抽屉打开时拉 `GET /api/v1/knowledge/bases` ⇒ 下拉候选 = `items`（显示 `name`，找不到名称时显示 ID）；
2. **上游可用**：正常展示；对**手输**且不在 `items`（`origin=upstream`）中的值 ⇒ **黄色提醒**（不阻断）：
   「该标识未出现在上游知识库清单中，请再确认拼写；保存后若上游不存在该库，检索将无结果」；
3. **上游不可用（降级）**：如实提示「**未能获取上游知识库清单**，以下为已绑定过的标识；可直接输入标识」——
   **不得**写成"没有知识库"；`items` 为空时同款提示 + 空态；
4. 禁用/越权档位维持既有矩阵行为（无权限者不进此页）。

---

## §10 影响面

- 后端：`app/knowledge.py`、`app/knowledge_policy.py`（及其 store）、`app/main.py`、`docs/api-contract.md`
- 前端：`workbench-web/src/features/permissions/{services,components,__tests__}`
- 测试：新增 `tests/test_knowledge_bases_api.py`；前端补 `ScopeDrawer` 用例
- 文档：本契约 v2、`permissions-api.md`（§4 口径改写：候选来源变化 + 降级语义）、`decision-log.md`（D-036 更正 + 本轮条目）
- **不改动**：上游配置状态（不往 `.env` 写凭据）、知识分级与检索链路、`skills` 模块

---

## §11 复测清单与补验动作

**门禁（每轮必跑）**：后端 `pytest` 全量 + `compileall`；前端 `tsc` + `vitest` + `build` + 产物 grep。

**反假（≥2 组，故意改坏必须变红）**：
1. 上游不可用时**改成返回空列表**（谎报"没有知识库"）⇒ 相关用例必红；
2. 去掉 `origin="binding_only"` 的合并 ⇒ 相关用例必红；
3. （可选）把跨租户过滤去掉 ⇒ 跨租户用例必红。

**用例面**：权限四档 + 匿名 `401`／上游可用（合并两类 `origin`）／上游**未配置**降级／上游**非 2xx** 降级／
上游**形状异常**（`data` 非数组、元素非对象）不崩且降级／跨租户不可见／**响应不含 Key 与主机名**／
`items` 为空时带 `note`；前端：候选来源、降级文案、黄色提醒、手输保留、空态。

**补验动作（日后拿到只读实例时，把"未实调"升级为"已实调"）**：
① 本机 `.env` 写 `WORKBENCH_WEKNORA_BASE_URL` / `WORKBENCH_WEKNORA_API_KEY`（只读 Key，不入库）；
② 跑 `tmp/r15-weknora-probe.py` ⇒ 拿到**真实**返回 → 确证 ID 键名与名称字段；
③ `GET /api/v1/knowledge/bases` 与上游直调结果**逐项比对**；
④ 故意写错 `base_url` ⇒ 验证降级**不谎报**；⑤ 验毕**撤掉 `.env` 里的凭据**。

---

## §12 交付记录

- 2026-09-21：**v1** 勘察结论（推翻 D-036④ 定性）+ 方案 A–D；用户裁决 **B** + 授权只读探测。
- 2026-09-21：**v1.1** 第一轮探测受阻（本机无上游凭据；上游文档不在仓库）⇒ 四条出路 B1–B4。
- 2026-09-21：**v2** 用户裁决"你来弄" ⇒ 改走上游公开官方文档，**确证 `GET /api/v1/knowledge-bases` 存在**（§7.2）
  ⇒ 定为 **B2′**（§8）⇒ 接口设计（§9）/ 影响面（§10）/ 复测清单（§11）就位，**待实现**。
  **未实调**已如实登记；实现完成后在此追加门禁结果、反假结果与真机核对结论。

- 2026-09-21：**v2.1 实现完成**（B2′ 落地）。改动文件（`git diff --stat` 口径，未提交）：
  后端 `app/knowledge.py`（`list_knowledge_bases` + `UpstreamShapeError` + 多键兼容解析）、`app/main.py`
  （`GET /api/v1/knowledge/bases` 整块：`403` 前置判定 / 降级 / 绑定并集 / `origin` 标注）、
  `docs/api-contract.md`（契约先行新增该节）；前端 `features/permissions/{types,services/permissionsService,
  components/ScopeDrawer,PermissionsPage}.tsx|ts`；测试 `tests/test_knowledge_bases_api.py`（25 用例）、
  `workbench-web/src/features/permissions/__tests__/{ScopeDrawer,permissionsService}.test.tsx|ts`。
  **未改**：`app/knowledge_policy.py`（复用 `list_bindings`）、上游配置状态、知识分级与检索链路、`skills` 模块。

- **门禁结果（全绿）**：后端 `pytest -p no:warnings -q` **exit 0**（`--collect-only` 计 **2783** 项 = 上轮 2758 + 本轮 25）；
  `python -m compileall -q app scripts` OK；前端 `npm run typecheck` 无报错、`npm run test` = **45 files / 378 tests passed**、
  `npm run build` 成功；产物 grep `kb-legacy-sample|MOCK_KNOWLEDGE_BASES|示例数据（未接后端）|kb-00000001` = **0 命中**。

- **反假结果（2 组，改坏后均已还原）**：
  ① 把"降级"改成返回**空列表**（谎报"没有知识库"）⇒ `tests/test_knowledge_bases_api.py` **8 红**
  （7 个降级 parametrize + 无绑定降级）；② 去掉 `origin="binding_only"` 的合并 ⇒ **1 红**
  （`test_bound_but_missing_upstream_id_merged_as_binding_only`）。还原后该文件 25 用例全绿。

- **真机核对（`tmp/r15-bases-verify.py`，一次性脚本，两个模式分别起真实进程：uvicorn + 真实 HTTP + 真实 httpx 适配器）
  = 30/30 通过**：
  - 情形 A（本机**未配置上游**，13/13）：`200` + `upstream_available=false` + `source="local_only"` +
    `items=[kb-00000001, kb-agent-only, kb-legacy-x]`（岗位 ∪ 数字员工绑定并集，全部 `origin="binding_only"`，
    **非空数组**）+ `note="未能获取知识库清单（未配置知识库服务）…"`；`ceo` 可取（`200`）、员工 `403`、匿名 `401`、
    他租户超管只见自己的 `kb-other-9`；响应文本不含凭据与主机名。
  - 情形 B（本机**桩上游**按官方文档形状应答，17/17）：`upstream_available=true`、`source="upstream"`、
    `items` = 清单两条 + 绑定独有两条（后者仍标 `binding_only`）；`id/name` 与 `knowledge_base_id/title`
    **两种键都取到**（多键兼容解析在真实 HTTP 上生效）；桩上游侧记录到**恰好一次 `GET /api/v1/knowledge-bases`
    且带 `X-API-Key` 头**（只读边界）；员工 `403` 时**零上游调用**（`403` 确在上游动作之前）。
  - 情形 C（桩上游 `500`）：降级 `local_only` + `note="…（服务暂不可用）…"`，`items` 回落为绑定并集。
  - 情形 D（桩上游形状异常 `data` 非数组）：降级 + `note="…（服务返回内容无法识别）…"`，**不崩、不臆测**。
  - 备注：上游失败时服务端日志含上游 URL（**不含密钥**）——与既有检索入口同口径
    （`_raise_knowledge_search_http` docstring：「上游原文（含主机名 / URL）只进日志，不回显给客户端」）。

**仍未验证（如实标注，不得表述为已完成）**：
1. **上游 `GET /api/v1/knowledge-bases` 仍未实调**——本机无可用上游实例/凭据，官方文档形状由**桩上游**模拟；
   真实 ID 键名与名称字段待 §11「补验动作」用只读实例升级为"已实调"。
2. **真库（postgres）路径未验证**：真机核对走内存仓储；`PostgresKnowledgeAccessRegistry` 现有用例
   （`tests/test_knowledge_policy.py`、`tests/test_workforce_roster_store.py`）用的是**假连接 + SQL 形状断言**，
   并不连真库；本轮**未新增**真库用例，故 `list_bindings` 的真实 SQL 行为**无证据**（不得表述为已覆盖）。
3. **并发/负载与超时阈值**（`WORKBENCH_WEKNORA_TIMEOUT_SECONDS` 下的真实超时降级）未做压测；超时分支仅在单测用假上游触发。
4. **前端界面层**：**2026-09-21 已走查**（见下方「界面走查记录」，`super_admin` 档 + 真实 HTTP）。
   仍未走查的是 **loading / error 两态**（本机没造"清单加载中 / 请求失败"的时机）与 **`ceo` 档**（只走了 `super_admin`）。

## 13. 界面走查记录（2026-09-21 · `super_admin` 档 · 真实 HTTP）

**环境（均为本机、非生产）**：后端 = 一次性脚本 `tmp/r15-walk-api.py`（真实 `uvicorn` + 内存仓储；
`WORKBENCH_REQUIRE_ADMIN_TOTP=false` 只为让本机走查账号拿到 full scope）；
前端 = `npm run dev`（`VITE_WORKBENCH_API_MODE=http`，vite 代理到该后端）；入口 `http://localhost:5199/`。
**账号**：`admin` / `123456`（超管；口令由用户给定 —— 平台注册/改密路径的策略不接受 6 位纯数字，
故该账号**只能由脚本直插哈希**，**仅存在于本机内存**；生产账号一律走注册 + 策略校验）；员工 `walk-employee`。
**截图目录**：[docs/screenshots/ui-v2-r15-permissions/](file:///d:/徐徐AI学习/公司工作台/docs/screenshots/ui-v2-r15-permissions)

**走查结果（逐字原文）**：

| 环节 | 现象 | 截图 |
| --- | --- | --- |
| 登录页 | 账号 `admin` + 口令，动态验证码留空 ⇒ 进入应用壳 | `00-login.png` |
| 权限配置页 | 横幅是**「已接入真实数据」**（**不是**「示例数据（未接后端）」）；三块齐（角色知识范围 / 数字员工知识范围 / 最近变更）；有真实行「内容运营」「内容写作员」 | `01-admin-permissions.png` |
| 抽屉·**降级态**（后端未配上游） | 来源提示原文：「候选标识的来源 / **未能获取知识库清单（未配置知识库服务），以下为本租户已绑定过的标识；可直接输入标识。**」；候选=已绑定标识；**此处刻意不出现"该标识不在清单中"的黄色提醒**（没有清单就不能这么说 ⇒ 与"降级不谎报"同一条口径） | `02-degraded-drawer-source.png`、`02b-degraded-options.png` |
| 降级态下手输 + 保存 | 手输 `kb-not-in-list` 并入标签（无黄色提醒，符合上述口径）⇒ 保存成功「已保存：知识范围已更新。」⇒ 列表回读 3 个标识 | `03-degraded-tag-added.png`、`04-saved-readback.png` |
| 抽屉·**清单可用态**（本机**桩上游**） | 来源提示原文：「候选标识的来源 / **候选来自知识库清单；也可直接输入标识 —— 平台无法校验标识是否存在，请与知识库的实际标识保持一致。**」；候选项带名称：`走查知识库一`、`走查知识库二`、`清单新增库`、`kb-walk-3`（前两个是已选 ✓） | `06-upstream-drawer-alert.png`、`07-upstream-options.png` |
| 黄色提醒（清单可用态） | 手输清单外标识 ⇒ 黄色 Alert 原文：「**以下标识未出现在知识库清单中：kb-not-in-list**」+ 说明「该标识未出现在知识库清单中，请再确认拼写；保存后若知识库里不存在该标识，检索将无结果。」；**保存按钮仍可用（不阻断）** | `08c-unknown-warning-collapsed.png`（`08-unknown-warning.png` 是下拉展开态，浮层遮住了提醒区） |
| 员工档 | 员工导航逐字为：我的工作台 / 我的数字员工 / 知识库 / Skill & MCP / 团队协作 / 审计日志 / 组件样品 —— **没有「权限配置」入口**（与 `navigation.ts` 的 `ADMIN_ONLY` 一致）；服务端 `403` 由用例与真机取证覆盖 | `05-employee-nav-firsttry.png` |

**走查纪律说明（如实登记）**：① 走查中**第一轮**把"降级态没有黄色提醒"误记为缺陷 —— 实为**设计口径**（清单未取到时不作"不在清单中"的判断），
故第二轮改配**本机桩上游**才拿到黄色提醒的证据；② 同轮把员工导航误记为「入口存在但禁用」，经**复核截图与第二轮逐字列举**更正为**入口不存在**（该记录已按更正后的口径落档）。
③ 本轮同时确认：清单可用态的候选是**带名称**的（`name` 来自上游），降级态只有标识本身（`name=null`）——与 §9「非协商口径」一致。

**仍未验证（走查口径）**：`loading` / `error` 两态、`ceo` 档、以及"保存失败（`403`/`409`/`422`/网络）"的界面表现未在浏览器里造过。