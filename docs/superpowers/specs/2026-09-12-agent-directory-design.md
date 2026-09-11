# 岗位与数字员工目录（「数字员工设置」）立项文档 · 口径

> **状态**：**口径已确认**（§4 四项决策已定，依据 §2 事实核查）。**立项阶段 —— 本文件不包含任何已写代码**；§12 落地清单须经评审通过后才可动手（宪法：立项阶段禁止写代码，地基改动必须专项评审）。
> **日期**：2026-09-12　**基线**：`main`（`bfc7584`，后端全量 `pytest` 退出码 0，CI run `34626240061` 四个 job 全绿）
> **前序**：本文件关闭 [`2026-09-11-workforce-roster-design.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-11-workforce-roster-design.md) §7 登记的缺口 1「不是目录管理」与缺口 3「`employee_key` 是自由文本」；该页（`GET /api/v1/workforce/roster`）继续保留为目录的「总览 / 未纳管」数据来源。

## 1. 背景与目标

管理台侧栏的「数字员工设置」至今是**占位项**：没有页面、没有实体、没有接口。而它背后的事实是——**岗位与数字员工都只是自由文本标识**，没有中文名、没有归属关系、没有启用状态，甚至前端下拉里的选项是**写死的假数据**。

**目标**：为租户建立**岗位**与**数字员工**的最小目录实体，让「数字员工设置」成为真实页面，并把它作为知识范围的**唯一候选来源**（替代前端写死清单）。

**非目标（明确不做）**：

| 不做 | 原因 |
| --- | --- |
| 组织 / 部门树、岗位层级、汇报线 | 组织架构是独立的领域建模（部门从哪来？与租户/工作区什么关系？），须单独立项 |
| 数字员工的模型 / Runtime / 技能 / 提示词 / 预算与自治上限绑定 | 涉及 `ModelGateway` 与 Runtime 注册表两处运行层接线，改动面与风险等级都不同，按 §12 留到下一期 |
| 账号（`role`: `employee`/`ceo`/…）与岗位的映射 | 账号角色是**系统权限角色**，岗位是**业务职能**，两者不是同一种东西；混用会同时污染权限模型与业务模型 |
| 删除（物理）岗位或数字员工 | 历史任务、运行记录、知识绑定都引用了标识；删除会让历史记录无法解析（§4 D4） |
| 把「模型与费用」占位项接上 | 模型清单来自配置注入的 `ModelGateway`，不是数据库实体，属另一条线 |

## 2. 事实核查（实际读码确认，非印象）

| # | 事实 | 位置 |
| --- | --- | --- |
| 1 | 任务上的数字员工只是必填 1–100 字符的自由文本，无白名单、无外键 | [main.py](file:///d:/徐徐AI学习/公司工作台/app/main.py#L157)、[domain.py](file:///d:/徐徐AI学习/公司工作台/app/domain.py#L47) |
| 2 | 知识范围绑定按 `(tenant_id, binding_type, binding_key)` 存放，`binding_key` 仅校验「不能为空」，**没有指向任何岗位/员工表的外键** | [004_knowledge_access_bindings.sql](file:///d:/徐徐AI学习/公司工作台/migrations/004_knowledge_access_bindings.sql)、[knowledge_policy.py](file:///d:/徐徐AI学习/公司工作台/app/knowledge_policy.py#L75-L79) |
| 3 | **岗位与数字员工在运行时是同一个命名空间**：任务的 `employee_key` 被直接当作 `role_key` 传给运行时上下文 | [service.py](file:///d:/徐徐AI学习/公司工作台/app/runtime/service.py#L60-L69) |
| 4 | 知识范围解析**没有继承**：传入 `agent_key` 就只看 agent 绑定，否则只看 role 绑定 | [knowledge_policy.py](file:///d:/徐徐AI学习/公司工作台/app/knowledge_policy.py#L48-L52) |
| 5 | 账号角色是独立一套：`employee / department_lead / ceo / super_admin / customer_admin`，与岗位无映射 | [service.py](file:///d:/徐徐AI学习/公司工作台/app/accounts/service.py#L45) |
| 6 | 知识范围读写**仅 `super_admin`**（仓储层与接口层各拦一次） | [knowledge_policy.py](file:///d:/徐徐AI学习/公司工作台/app/knowledge_policy.py#L81-L84)、[main.py](file:///d:/徐徐AI学习/公司工作台/app/main.py#L764-L766) |
| 7 | 管理台「知识权限管理」页的岗位/数字员工下拉是**写死的**（3 个岗位 + 2 个数字员工 + 中文名），并写死「内容中心 · 6 名员工」 | [KnowledgeAccessPage.tsx](file:///d:/徐徐AI学习/公司工作台/admin-web/src/features/knowledgeAccess/KnowledgeAccessPage.tsx#L17-L20)（L131 同页） |
| 8 | 知识库清单同样写死在前端（6 个 id + 中文名） | [types.ts](file:///d:/徐徐AI学习/公司工作台/admin-web/src/features/knowledgeAccess/types.ts#L8-L15) |
| 9 | 数据库里**没有**岗位 / 数字员工 / 组织 / 部门 / 技能 / 模型表：迁移仅 `001`–`021`（目录已逐一核对） | [migrations/](file:///d:/徐徐AI学习/公司工作台/migrations) |
| 10 | 但**已有可复用的「租户管理员」概念与判定模式**：`workbench_customer_admins` + `super_admin or (customer_admin 且本租户已登记)` | [006_commercial_g0.sql](file:///d:/徐徐AI学习/公司工作台/migrations/006_commercial_g0.sql#L18-L23)、[main.py](file:///d:/徐徐AI学习/公司工作台/app/main.py#L391-L393)、[tenant.py](file:///d:/徐徐AI学习/公司工作台/app/commercial/tenant.py#L54) |
| 11 | `super_admin` 登录**已强制 TOTP**，因此 super_admin 身份本身已含二次验证 | [service.py](file:///d:/徐徐AI学习/公司工作台/app/accounts/service.py#L47) |
| 12 | 审计明细是**严格白名单**：新增动作若带 `role_key` / `agent_key` 这类键，必须同步扩白名单，否则写审计直接抛错 | [models.py](file:///d:/徐徐AI学习/公司工作台/app/audit/models.py#L11-L76) |
| 13 | 目标态领域对象在架构文档里已声明（含岗位、数字员工、组织、部门、技能、模型、路由策略），但**代码中多数尚不存在** | [architecture.md](file:///d:/徐徐AI学习/公司工作台/docs/architecture.md#L42-L44) |
| 14 | 迁移清单必须同步登记，否则 staging 预检永久 `blocked`（曾有漂移事故） | [.env.staging.example](file:///d:/徐徐AI学习/公司工作台/.env.staging.example#L30) |

**结论**：事实 3 与事实 4 说明「岗位 / 数字员工」的**语义边界今天是不成立的**（同一个字符串既当岗位又当员工）。因此本立项的第一价值不是「加一张表」，而是**把两个概念拆开**，这也决定了 §4 D2 必须定归属关系。

## 3. 目标态一句话

> 管理员在「数字员工设置」里维护**岗位**（标识 + 中文名 + 启用状态）与**数字员工**（标识 + 中文名 + **所属岗位** + 启用状态）；知识范围的候选对象来自这份目录（不再写死）；历史遗留的自由文本标识被实时标注为**未纳管**，可一键纳管，且**不阻断任何现有任务与检索**。

## 4. 决策记录（已确认）

| # | 决策点 | 结论 | 影响 |
| --- | --- | --- | --- |
| D1 | 本期范围 | **目录 + 知识范围联动**（不做模型 / Runtime / 技能） | 只动 `knowledge_policy` 的候选来源与新增目录域；不碰运行层 |
| D2 | 归属关系 | **数字员工归属一个岗位**（`agent.role_key` 必填） | 岗位成为范围的载体，员工级可单独绑定（语义与既有「知识权限管理」页说明一致） |
| D3 | 编辑权限 | **仅 `super_admin` 读写**（`ceo` / `customer_admin` 均不可见） | 与知识范围管理完全一致，不新增权限面；私有部署客户管理员需求出现时再单独立项 |
| D4 | 存量自由文本标识 | **自动登记为「未纳管」**（可一键纳管，不阻断现有流程） | 采用**实时计算**而非落库，避免制造第二份真相 |
| D5 | 知识范围绑定键（`binding_key`）的大小写归一（阶段 2 前置，2026-09-12 评审后新增） | **归一**：绑定键与目录标识一样做 `strip().lower()` | 写入时归一化绑定键；存量大小写不一致的行在下一次保存时被改写；`roster` / `candidates` 的精确匹配口径随之变化，实现时**必须同步 `docs/api-contract.md`** |

## 5. 数据模型

### 5.1 实体与字段（迁移 `022_workforce_directory.sql`）

```sql
CREATE TABLE IF NOT EXISTS workbench_job_roles (
    tenant_id TEXT NOT NULL,
    role_key TEXT NOT NULL,              -- 机器标识，创建后不可改（对齐既有 binding_key 口径）
    name TEXT NOT NULL,                  -- 中文显示名
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, role_key)
);

CREATE TABLE IF NOT EXISTS workbench_digital_employees (
    tenant_id TEXT NOT NULL,
    agent_key TEXT NOT NULL,             -- 等于任务上的 employee_key
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    role_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, agent_key),
    FOREIGN KEY (tenant_id, role_key) REFERENCES workbench_job_roles (tenant_id, role_key)
);
```

- 索引沿用 `idx_workbench_*` 命名：`(tenant_id, status)`、`(tenant_id, role_key)`（员工按岗位归组）。
- **复合外键** `(tenant_id, role_key)` 是刻意的：租户隔离写进约束，而不是只靠 `WHERE`（与 `workbench_tasks` 的 `UNIQUE (id, tenant_id)` + 复合外键同一手法）。
- **不建软删除列**：`status='disabled'` 即停用语义；历史记录继续解析得到标识，不会 404（D4 的必然要求）。
- **不建 `unmanaged_*` 表**：未纳管标识由「目录 ∪ 知识绑定 ∪ 任务里出现过的标识」实时求差集得到，复用现有 `workforce/roster` 的三源并集逻辑（[main.py](file:///d:/徐徐AI学习/公司工作台/app/main.py#L790-L803)）。

### 5.2 标识规范

| 规则 | 取值 | 理由 |
| --- | --- | --- |
| 允许字符 | `^[a-z0-9][a-z0-9._-]{0,63}$` | 与既有 `content-operator` / `content-writer` / `geo-analyst` 兼容；与运行时 / 日志 / URL 路径安全 |
| 大小写 | **必须小写**（提交前 `strip()` + 转小写后再校验） | 消除「大小写不同即两个标识」的隐患（roster 页已登记的精确匹配限制） |
| 唯一性 | 租户内唯一（主键保证） | 幂等与冲突判定交给数据库，不靠应用层查重 |
| 可修改 | **`role_key` / `agent_key` 创建后不可改** | 任务、知识绑定、运行记录都引用了标识；改名等于静默切断历史 |
| 命名不对齐（已登记） | 目录用 `agent_key`，任务用 `employee_key` | 本期**不重命名任务字段**（破坏性变更）；实现时在仓储与契约里写明「两者同值」 |

### 5.3 与知识范围的联动（口径）

| 动作 | 规则 | 影响面 |
| --- | --- | --- |
| **读 / 检索解析** | **不变**：`resolve()` 不校验目录，存量绑定与既有任务照旧可用 | 零回归风险（事实 4：本来就无继承，本期也**不引入**继承，见 §11 Q1） |
| **写（配置知识范围）** | **已实施（阶段 2，2026-09-12）**：`PUT /knowledge-access/roles/{role_key}`、`.../agents/{agent_key}` 要求该标识**已在目录且 `status='active'`**；未纳管、已停用、格式非法或跨租户一律 `409`「该标识尚未纳入目录，请先在「数字员工设置」中纳管」。绑定键同时按 D5 归一（去空白 + 小写）。**判定顺序：先 `403` 后 `409`** | 实测破坏面只有 2 个 `PUT` 分支 + 1 个测试文件的 2 个用例（见 §14.1）；**无迁移、无表结构变更** |
| **候选来源** | 前端下拉改为目录数据（替代写死清单，事实 7） | 管理台行为变更，非破坏性 |

阶段划分的理由：**读路径是生产运行链路，写路径是管理配置链路**。把校验放在写路径，既能消灭「配置里出现不存在的人」这一类脏数据，又不会让历史运行记录或检索立刻失效。

## 6. 权限模型

| 动作 | `super_admin` | `ceo` | `department_lead` | `employee` | `customer_admin` |
| --- | --- | --- | --- | --- | --- |
| 查看岗位/员工目录 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 新建 / 编辑 / 停用 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 查看「未纳管」标识 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 配置知识范围（既有） | ✅ | ❌ | ❌ | ❌ | ❌ |

**强制约束（每条都要有对应用例）**：

1. **严格本租户**：所有查询带 `tenant_id`，跨租户数据不可见（不依赖前端传参）。
2. **不可改标识**：`PATCH` 请求体出现 `role_key` / `agent_key` 一律 `422`（模型层就不暴露这两个字段）。
3. **停用不删除**：停用后不出现在「可指派」候选里，但历史任务、历史绑定、历史运行记录仍可解析。
4. **岗位必须存在且启用**：新建/编辑员工时校验 `role_key` 属于本租户且 `active`，否则 `409`。
5. **不做二次审批**：目录变更不进审批闸门（它不是架构文档所述「岗位提示词修改」那类高风险动作）；但 `super_admin` 本身已强制 TOTP（事实 11），且每次变更**必须写审计**。
6. **不提供批量导入/导出**（避免绕过逐条校验；如确有需要另立项）。

**审计（宪法要求「关键操作预埋日志」）**：新增 6 个动作，33 → 39，并同步扩 `ALLOWED_DETAIL_KEYS`（事实 12，否则写审计直接抛错）：

| 动作 | 明细键（需新增） |
| --- | --- |
| `workforce.role.created` / `workforce.role.updated` / `workforce.role.disabled` | `role_key`、`changed_fields` |
| `workforce.agent.created` / `workforce.agent.updated` / `workforce.agent.disabled` | `agent_key`、`role_key`、`changed_fields` |

前端中文标签表（`features/auditLog/types.ts`）与 `tests/test_frontend_audit_labels.py` 必须同步，否则标签漂移守护测试会红。

## 7. 接口契约草案（实现时写入 `docs/api-contract.md`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/workforce/roles` | 列表，`limit` 1–200 + `offset` + `total`（宪法：列表必须分页）；`status` 可选过滤 |
| `POST` | `/api/v1/workforce/roles` | 新建；标识重复 `409`；非法标识 `422` |
| `PATCH` | `/api/v1/workforce/roles/{role_key}` | 改中文名 / 描述 / 状态；**不含标识字段**；幂等 |
| `GET` | `/api/v1/workforce/agents` | 同上（含 `role_key`、可按 `role_key` 过滤） |
| `POST` | `/api/v1/workforce/agents` | 同上；岗位不存在或已停用 `409` |
| `PATCH` | `/api/v1/workforce/agents/{agent_key}` | 同上 |
| `GET` | `/api/v1/workforce/candidates` | **未纳管标识**（三源并集减去目录），供「一键纳管」 |

全部接口：未认证 `401`；非 `super_admin` `403`；只返回本租户数据；响应不含账号 PII。既有 `GET /api/v1/workforce/roster` 保持不变（向后兼容，仍是总览入口）。

## 8. 前端

- 新增 `admin-web/src/features/workforceSettings/`（`types.ts` / `api.ts` / `state.ts` / `WorkforceSettingsPage.tsx` + 测试），侧栏「数字员工设置」接上 `view: 'workforceSettings'`（URL `?view=workforceSettings`）。
- 页面结构：分段切换「岗位 / 数字员工」→ 列表（标识、中文名、所属岗位、状态）→ 新建 / 编辑（弹层或行内表单）→「未纳管」区块（列出并一键纳管，纳管时补中文名与所属岗位）。
- 四态齐备：加载 / 空 / 错误（含「重新尝试」）/ 无权限（403 显示「当前账号没有管理岗位与数字员工的权限」）。
- **副作用（必须一并做，否则仍是假数据）**：`KnowledgeAccessPage.tsx` 的写死 `subjects`（事实 7）改为从目录加载，其「内容中心 · 6 名员工」文案改为真实计数或删除。
- 与 roster 页的关系：目录页承载「未纳管」，roster 页保留为只读总览（不删除接口，避免破坏契约与既有测试）。

## 9. 迁移与兼容

| 项 | 处理 |
| --- | --- |
| 迁移编号 | `022_workforce_directory.sql`；`CREATE TABLE IF NOT EXISTS` |
| 迁移清单 | 同步 `.env.staging.example` 的 `WORKBENCH_APPLIED_MIGRATIONS`（事实 14，`tests/test_staging_assets.py` 守护） |
| 存量数据 | **不回填、不改写**既有绑定与任务；存量标识以「未纳管」呈现，纳管动作只新增目录行 |
| 双实现 | 内存 + PostgreSQL 双实现（沿用 `_COLUMNS` / `_hydrate` / `_connection` 既有模式），memory 仅限 `development` |
| 回滚 | 目录是**新增表**，回滚 = 停止使用该页面 + 保留表（不需要删数据）；`022` 属新增迁移，无既有表结构变更 |
| 破坏性变更 | 仅「写知识范围要求标识已在目录」（§5.3），**单列为阶段 2**，收敛条件见 §11 Q2 |

## 10. 测试计划（先写失败测试，后写实现）

| 层次 | 覆盖 |
| --- | --- |
| 仓储（内存 / PG 假连接） | 新建、重名 `409`、停用、只列本租户、分页、按状态与岗位过滤；PG 的 SQL 与参数断言 |
| 接口 | `401` / `403`（`ceo` 与 `customer_admin` 也必须 403）/ 创建 `201` / 重名与非法标识 `409`、`422` / `PATCH` 传标识字段 `422` / 列表分页 / 跨租户不可见 / 响应无 PII |
| 联动 | 「未纳管」三源并集正确；纳管后从 candidates 消失；阶段 2 后写知识范围对未纳管标识返回 `409` |
| 审计 | 6 个新动作写入成功；未在白名单的明细键被拒；`test_frontend_audit_labels.py` 覆盖新动作 |
| 前端 | 目录页四态、新建/编辑/停用、纳管动作；`KnowledgeAccessPage` 下拉来自目录（不再出现写死清单） |
| 契约守护 | 全部新路由必须出现在 `docs/api-contract.md`（`tests/test_api_contract_coverage.py`） |
| 反假测试（必做） | ① 去掉仓储的 `tenant_id` 过滤 → 跨租户用例必须变红；② 让 `PATCH` 接受标识字段 → 「不可改标识」用例必须变红；③ 关闭审计白名单扩展 → 审计用例必须变红 |

三类用例齐全：正常流程（**查库验证写入正确，不只看 200**）、临界值（空标识、超长、非法字符、分页边界、同一标识并发创建）、异常与非法输入（跨租户、越权角色、传标识字段、不存在/停用的岗位）。

## 11. 开放问题（未定，需在阶段 1 实现前答复）

| # | 问题 | 建议与理由 |
| --- | --- | --- |
| Q1 | 是否引入「员工继承岗位知识范围」？今日解析**无继承**（事实 4），且运行时把 `employee_key` 当 `role_key` 用（事实 3） | **本期不做**。若要做，需同时改运行时传参（传 `agent_key` + 所属 `role_key`），属**检索行为变更**，必须单独评审；本期只把归属关系落在目录里备用 |
| Q2 | 阶段 2（写知识范围强制目录校验）的收敛条件 | 收敛条件取**「绑定侧未纳管为空」**，并作为阶段 2 的开工前提；**不按时间**排期。**依据（2026-09-12 本地带数据实测，见 §13.6）**：`candidates` 的员工候选把**任务中的 `employee_key`** 也算进去，而建同名**岗位**并不会让它消失；若按字面的「candidates 全空」判定，只要历史任务里存在 `employee_key` 就**永远不空**（条件不可达）。阶段 2 实际校验的对象只是知识范围写接口的 `binding_key`（`role` / `agent` 绑定），任务 `employee_key` 不参与绑定写入。故判据按绑定侧取：① `GET /api/v1/workforce/candidates` 的 `roles` 为空；② `GET /api/v1/workforce/roster` 中 `agent_knowledge_base_ids` 非空、且该 key 不在员工目录里的项为空（**用现有两个只读接口即可判定，不需要新接口**）。任务侧的历史标识另立处置（逐个纳管为员工，或明确豁免），**不阻塞阶段 2** |
| Q3 | 停用员工的后果 | 建议：**停用只禁止「新任务指派」**，不撤销知识绑定、不影响历史与进行中的运行；已停用员工的既有绑定仍按原样解析 |

## 12. 落地清单（评审通过后才动手）

**阶段 1（目录基础设施，非破坏性）**

1. `migrations/022_workforce_directory.sql` + `.env.staging.example` 清单登记。
2. `app/workforce/`（新模块：模型 + 内存仓储 + PG 仓储 + 服务层，权限在仓储层与接口层各拦一次）。
3. `app/main.py`：`roles` / `agents` / `candidates` 共 7 个路由；`app/audit/models.py` 扩 6 个动作 + 3 个明细键。
4. 前端 `features/workforceSettings/`；`KnowledgeAccessPage.tsx` 下拉改为目录数据、删除写死文案。
5. `docs/api-contract.md` 新章节；`docs/delivery-gates.md`、`docs/delivery-readiness-checklist.md`、`docs/architecture.md`（把「核心领域对象」中岗位/员工标注为已落地）同步。
6. 全量回归（`pytest` + `compileall` + 两端 vitest/build + 桌面 `node --test`）+ CI 实跑。

**阶段 2（写路径收敛，破坏性 —— 需 Q2 满足且再次评审）**

7. 知识范围写接口强制目录校验；清点并修正受影响的既有测试与开发期数据；补 `409` 用例。

## 13. 已知风险（如实登记）

1. **命名不统一**：目录 `agent_key` vs 任务 `employee_key`（同值不同名），本期只做文档说明，不改字段。
2. **标识一旦写错就永久留存**：不可改标识换来的是历史可追溯，代价是错标识只能停用 + 新建。
3. **阶段 1 到阶段 2 之间的双轨已结束**（阶段 2 于 2026-09-12 落地）：目录是唯一候选来源，知识范围**写**路径强制先纳管；**读/检索**仍按归一键解析历史绑定。任务侧 `employee_key` 依旧是自由文本（不受写闸门约束），属已登记限制。
4. **知识库清单仍写死在前端**（事实 8）：本期只改岗位/员工候选来源；知识库实体化属另一条线（需与 WeKnora 的库清单对齐后才能定真源）。
5. **本文件不构成任何实现完成的声明**：阶段 1 已于 2026-09-12 落地（提交 `8f23ee6`…`4e6fff3`，CI run `34628395663` 四个 job 全绿）；**阶段 2 亦已完成**（见 §14.5）。

### 13.6 阶段 1 落地后的实测记录（2026-09-12，本地进程内带数据）

在 `env=development` + `storage_backend=memory` 下（`X-*` 头身份仅在 development 生效，见 `app/main.py:376-391`），手工造 2 条知识范围绑定 + 2 条任务后实测：

| 步骤 | 结果 |
| --- | --- |
| 初始 `candidates` | `{"roles": ["content-operator"], "agents": ["content-operator", "content-writer", "geo-analyst"]}` |
| 建岗位 `content-operator` / `geo-operator` | `201` / `201` |
| 建岗位 `CONTENT-OPERATOR` | `409`（大小写折叠为同一标识） |
| 建员工 `content-writer` → `content-operator` | `201` |
| 纳管后 `candidates` | `{"roles": [], "agents": ["content-operator", "geo-analyst"]}` |
| `PATCH` 传 `role_key` | `422`（标识不可改） |
| 停用岗位后挂员工 | `409` |
| `ceo` 读 `candidates` | `403` |
| 审计动作 | 4 条：`workforce.role.created` ×2、`workforce.agent.created`、`workforce.role.disabled` |

**结论**：① 三源并集与「按类型分开」的语义成立；② **建同名岗位不会让该标识从员工候选里消失**（它仍作为任务的 `employee_key` 存在），这正是 Q2 收敛条件必须取「绑定侧」的原因；③ 内存存储进程结束即消失、无落盘（`git status` 干净、无 `.db` 文件），**本次结果不代表任何真实环境的未纳管情况**，真实判定仍需 staging 与超管令牌（阻塞项 1）。

## 14. 阶段 2 影响清点（评审材料，2026-09-12）

> 结论先说：**破坏面远小于 §5.3 初稿的估计**，但开工前必须先定 §14.2 的三条口径，其中第 3 条（大小写归一）不解决会形成死结。

### 14.1 事实清点

| 面 | 结论 | 依据 |
| --- | --- | --- |
| 写接口实现点 | **只有 2 处** | `app/main.py:1085-1097`（`PUT .../roles/{role_key}`）与 `app/main.py:1109-1121`（`PUT .../agents/{agent_key}`） |
| 当前写流程 | 先 `_ensure_knowledge_admin`（`PolicyError` → `403`）→ `bind_*` → `resolve` | 同上 |
| 打 HTTP 写接口的测试 | **仅 1 个文件 2 个用例** | `tests/test_control_plane.py:345`（超管写 role，键 `content-operator`）、`:367`（ceo 写 agent，断言 `403`） |
| 直接调 store `bind_role`/`bind_agent` 的测试 | 5 个文件 14 处，**只测注册表本身** | `test_knowledge_policy.py`(5)、`test_workforce_roster_store.py`(4)、`test_workforce_roster_api.py`(2)、`test_workforce_directory_api.py`(2)、`test_knowledge.py`(1) |
| 前端调用方 | 只有 `saveKnowledgeAccess`；且候选已改为读目录（阶段 1 只拉 `status=active`），正常操作提交不了未纳管标识 | `admin-web/src/features/knowledgeAccess/api.ts`、`KnowledgeAccessPage.tsx` |
| 存量数据影响 | 既有绑定行**读 / 检索不受影响**（`resolve` 不改），只有「重新保存该绑定的范围」才需要先纳管 → 影响的是**管理动作**，不是运行链路 | `app/knowledge_policy.py:48-52`、`:146-160` |

**推论**：只要校验放在**接口层**，要动的只有「2 个 PUT 分支 + 1 个测试文件的 2 个用例 + 契约文案」，仓储层原语、注册表单测与检索链路全部不动，且**不涉及任何迁移**。

### 14.2 必须先定的三条口径

1. **校验层次 = 接口层**，不进 `KnowledgeAccessRegistry.bind_*`。理由：① 两个 store 方法被 14 处单测直接调用，放进仓储层等于让注册表单测被迫先建目录，并把注册表从「绑定原语」耦合上「目录」；② `app/` 内除这两个 PUT 外**没有其它写绑定的调用点**（已全仓核对），接口层足够覆盖。
2. **顺序：先 `403`，后 `409`**。现有 `except PolicyError → 403` 包住整个 try。**实测修正（2026-09-12）**：把闸门提到鉴权之前**不会改变状态码**（目录仓储层的 `_ensure_admin` 同样抛 `PolicyError` → 仍映射为 `403`），但**会把 `detail` 泄露成「只有超级管理员可以管理岗位与数字员工目录」**，即暴露请求已经打到目录层；用**文案断言**才守得住这一点（`test_permission_check_wins_over_directory_gate`）。因此仍要求 `DirectoryNotManaged` **不继承** `PolicyError`、且鉴权排在闸门之前。
3. **绑定键的大小写归一陷阱（不解决会死结）**：目录侧写入会 `strip().lower()`，但知识范围绑定的 `binding_key` **今天完全不归一**——`_normalize` 只拒绝空白、不规范化键本身（`app/knowledge_policy.py:75-79`），PG 的 `_bind` 原样写入（`:108-132`）。若阶段 2 要求「绑定键必须等于目录里的标识」，库里既有的 `Content-Operator` 这类绑定会**两头堵**：既不算已纳管（≠ 目录里的 `content-operator`），重写又被 `409` 拒绝。**已定（见 §4 D5）：绑定键也做 `strip().lower()` 归一**；实现时须同步改写 `roster` / `candidates` 的精确匹配口径与 `docs/api-contract.md`。

### 14.3 实现要点与回退

- 需要新增**只读判定**：现有 `known_keys`（`app/workforce/store.py:174` 内存版、`:387` PG 版）**刻意包含停用项**（那是「未纳管」用的口径），**不能**直接拿来判断 `active`；应新增 `is_active(context, kind, key)`，或在服务层用 `list_roles/list_employees(status='active')` 组装。
- 契约改动：`docs/api-contract.md`「知识范围」章节补 `409` 语义；「岗位与数字员工目录」章节删掉「阶段 1 不强制绑定前置」那段限制。
- 测试改动：`tests/test_control_plane.py` 两个用例补前置目录数据（或把断言从 `403` 保持不动、只给超管那条建目录）。
- **回退**：只改接口层分支，回退＝还原那两个 `PUT` 的校验行；无迁移、无表结构变更、无需数据修复。
- ~~**开工前提**仍是 §11 Q2 的「绑定侧未纳管为空」。~~ **2026-09-12 变更**：用户明确决定**不等真实数据验证、直接实施**阶段 2，并接受由此带来的风险——存量库中大小写/空白不一致的绑定会在**下一次保存时被归一改写**（这是 D5 的预期行为，但未经真实数据演练，已登记在 §14.5「未验证」）。

### 14.4 评审结论与实施结果

三条口径已定并**全部实施完成（2026-09-12）**：① 校验放接口层；② 顺序先 `403` 后 `409`（独立异常类型 `DirectoryNotManaged`，**不继承** `PolicyError`）；③ 绑定键归一到 `strip().lower()`，并与目录**共用同一个** `normalize_key`（避免两套标识规范）。

已执行的顺序：改那 2 个 `PUT` 分支（含绑定键归一）→ 同步 `docs/api-contract.md`（`409` 语义 + 归一/精确匹配口径）→ 补 `tests/test_control_plane.py` 的前置目录数据 → 全量回归（见 §14.5）。

### 14.5 阶段 2 实施与验证记录（2026-09-12）

**改动**

| 文件 | 改动 |
| --- | --- |
| `app/workforce/models.py` | 新增 `DirectoryNotManaged`（**不继承** `PolicyError`，否则会被 `except PolicyError → 403` 截走） |
| `app/knowledge_policy.py` | 新增 `normalize_binding_key`（与目录共用 `normalize_key`）与容错的 `_lookup_key`；内存与 PG 的 `bind_*` / `_bind` 落库与审计均用归一键；`resolve` 按归一键查找 |
| `app/workforce/store.py` | 新增 `role_is_active` / `agent_is_active`（内存 + PG；非法/空标识按「不可用」处理，**不抛异常**） |
| `app/workforce/service.py` | 新增闸门 `ensure_role_binding_available` / `ensure_agent_binding_available`（返回归一键；未纳管抛 `DirectoryNotManaged`） |
| `app/main.py` | 两个 `PUT` 分支接入闸门（鉴权 → 闸门 → 绑定），新增 `except DirectoryNotManaged → 409` |

**测试**：新增 `tests/test_knowledge_access_directory_gate.py`（8 项）；`tests/test_knowledge_policy.py` 补归一与格式收紧用例（含 PG 参数断言）；`tests/test_workforce_directory_store.py` 补 2 项可用性用例（含 PG SQL/参数）；`tests/test_control_plane.py` 补前置目录数据。

**反假测试（两次，均已还原）**

| 故意制造的错误 | 结果 |
| --- | --- |
| 把闸门提到鉴权之前 | `test_permission_check_wins_over_directory_gate` 变红（`detail` 泄露成目录层文案）→ 证实「先 `403` 后 `409`」与**文案断言**有效 |
| 去掉角色写路径的闸门 | 5 项变红（未纳管 / 已停用 / 格式非法 / 跨租户 / 归一写入）→ 证实闸门本身有效 |

**回归**：后端 `pytest` exit=0、`compileall` exit=0；`admin-web` 94 passed、`companion-pwa` 37 passed、`desktop` 19 pass / 0 fail。

**未验证（如实登记）**：真实 PostgreSQL 下的闸门行为（PG 的 `role_is_active` 只用假连接做了 SQL/参数断言）；未做浏览器人工闭环；存量库里若存在大小写/空白不一致的绑定，其**下一次保存**会被归一改写（口径 D5 的预期行为，未经真实数据演练）。

