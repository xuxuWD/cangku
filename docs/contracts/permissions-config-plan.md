# 第 6 轮「权限配置」模块 · 实施方案（**待确认后再写代码**）

> 状态：**方案 v1 · 2026-09-19**。
> **唯一权威不在本文件**：权限口径见 [`permission-matrix.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/permission-matrix.md)、
> 知识分级见 [`knowledge-acl.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/knowledge-acl.md)；
> 本文件只写"**这一轮做什么、怎么做、怎么验**"，不复制口径、不改口径，冲突时以那两份为准。
> **事实来源**：后端源码只读核对 + **2026-09-19 真机实测**（本机工作树 `uvicorn` + 真库 `workbench_test`，非生产）。

## 1. 目标（一句话）

把「权限配置」从占位页变成**可用的知识范围授权面**：超级管理员在本页完成「角色 / 数字员工 ↔ 知识库范围」的查看与绑定，
越权与未纳管一律被拒，并给出**可懂的原因**（不是"操作失败"四个字）。

## 2. 范围

**做什么**
1. 「角色知识范围」块：岗位目录里的角色 + 当前绑定，可编辑（写入走 `PUT knowledge-access/roles/{role_key}`）。
2. 「数字员工知识范围」块：同上（`PUT knowledge-access/agents/{agent_key}`）。
3. 「最近变更」块：只读读 `GET /api/v1/knowledge-access/audits`（含 old/new 绑定 id、操作者、时间）。
4. 四态（加载 / 空 / 错误 / 无权限）与越权呈现；失败**不静默**。
5. 契约文件（新增）：`docs/contracts/permissions-api.md`（**契约先行**：写码前先落接口清单与实测形状）。

**不做什么（禁止事项）**
- **不做**角色 / 数字员工的**创建、改名、启停** —— 那是「数字员工管理 / 设置」（目录面）的职责；
  本页只**消费**目录状态（未纳管的 key 写入会被服务端 `409` 拒绝，界面据此提示"请先在数字员工设置中纳管"）。
- **不做**只读权限矩阵页签 —— 矩阵的唯一权威是 `permission-matrix.md`，界面另绘一份**必然漂移**。
- **不做**文档级四级 ACL 字段 —— `knowledge-acl.md` 的四级字段尚未落库（属 Schema 线），本轮不碰。
- **不新增后端接口、不改后端一行**；不动第 1~5 轮与接线批 1 已交付的文件行为。

**影响什么**：`workbench-web/src/features/permissions/**`、新增 `docs/contracts/permissions-api.md`、
回写 `permission-matrix.md` §7 差距表的"归属"列（把本轮落地项标掉）。

## 3. 接口清单（**真机实测，逐键点名**）

| 方法 | 路径 | 实测结果 |
| --- | --- | --- |
| GET | `/api/v1/knowledge-access/roles/{role_key}` | `200` `{"binding_type":"role","binding_key":"content-ops","knowledge_base_ids":[]}`（**读不要求 key 已纳管**） |
| PUT | 同上 | 请求体 `{"knowledge_base_ids":[...]}`（`extra="forbid"`、`max_length=100`）；成功返回**同 GET 形状** |
| GET | `/api/v1/knowledge-access/agents/{agent_key}` | `200` 同形状（`binding_type="agent"`） |
| PUT | 同上 | 同上 |
| GET | `/api/v1/knowledge-access/audits?limit=` | `200` **数组**（本租户当前为空） |
| GET | `/api/v1/workforce/roles?limit=&offset=` | `200` `{"items":[],"total":0,"limit":50,"offset":0}`；每项键 = `role_key / name / description / status / created_by / created_at / updated_at` |

**写路径两道闸门（实测，顺序 = 先权限、后目录）**

| 场景 | 实测 | 原文 |
| --- | --- | --- |
| 员工令牌 PUT | **`403`** | `{"detail":"只有超级管理员可以调整知识库范围"}` |
| 超管 PUT 未纳管 key | **`409`** | `{"detail":"该标识尚未纳入目录，请先在「数字员工设置」中纳管"}`（**未产生任何写入**） |
| 请求体多字段 | **`422`** | `detail` 是**数组**（`extra_forbidden`）⇒ 前端 `safeDetail` 拒绝非字符串 ⇒ 落回**本地固定文案**，不渲染原始校验 JSON |

## 4. 关键缺口与处置（**需要裁决**）

**缺口：后端没有"知识库候选列表"接口。** 全仓 grep 无 KB 枚举端点；`knowledge_base_ids` 是 WeKnora 侧的库标识
⇒ 界面**取不到**"可选项"。

- **A（推荐）**：候选 = **现有绑定的并集** + **手动录入新 id**（前端只做非空 / 去重 / ≤100 项校验，
  **服务端仍是唯一权威**）；界面明确写"候选来自现有绑定；新库标识需手动录入（后端暂无枚举接口，已登记）"。
- **B**：先请后端补枚举接口（须先确认 WeKnora 侧是否提供可枚举面）⇒ **阻塞本模块**，本轮改做别的模块。
- **C**：本模块只读（只看不绑）⇒ 价值与体验最低，但风险最小。

## 5. 交付物与验收标准（可检查）

1. `src/features/permissions/` 四件套（components / services / types / tests）+ 契约 `docs/contracts/permissions-api.md`。
2. **四态齐备**：员工打开本页 ⇒ **无权限态 + 原因**，且**不渲染任何编辑控件**（不是"藏起来"）。
3. 403 / 409 / 422 三种失败各有**可懂文案**（优先服务端 `detail`；非字符串则落回本地文案）；失败不静默。
4. **先红后绿** + **≥2 组反假**（例：改坏 403 呈现、改坏"未纳管"提示 ⇒ 指定用例必须变红）。
5. **真机取证（本机工作树 + 真库）**：① 员工 PUT ⇒ `403`；② 超管 PUT 未纳管 key ⇒ `409` 且**查库零新增**；
   ③ 先经目录纳管一个角色 → 超管 PUT ⇒ `200` → GET 回读一致 → **查库核对该绑定落库**；④ 变更记录块能读到该条审计。
   ⚠️ ③ 会在**测试库**产生数据 ⇒ 按你确认过的清理清单**用完即清**（并登记成绩）。
6. 门禁：`tsc` / `vitest`（既有全量 + 新增）/ `build`；产物 grep 无样例字样。
7. 交付报告五问：做完哪些 / 没做哪些、改了哪些文件、怎么验证、**哪些未验证**、下一步。

## 6. 已登记"做不到 / 未验证"（不得读成已验）

- **检索侧效果验不了**：`POST /api/v1/knowledge/search` 需要 WeKnora 配置（未配 ⇒ `503`）⇒
  "绑定后检索真的只返回该范围"**本机无法验证**；只能验到**绑定读写与闸门行为**。
- 文档级四级 ACL（`knowledge-acl.md`）**未落库**，本轮不涉及。
- 本机拓扑为 Windows + 单进程 uvicorn + 本机测试库，**非 staging / 生产**。

## 7. 依赖与顺序

- 依赖：接线轮**批 2** 完成（它接 `/workforce/roles`、`/roster` 等目录面）；本模块**复用**其登录会话与统一请求层，
  但**不跨模块 import**（角色 / 员工清单在本模块自己的 service 里重新取，避免耦合）。
- 顺序：本方案确认 → 写契约文件 → 先红后绿 → 真机取证 → 验收清单与报告。