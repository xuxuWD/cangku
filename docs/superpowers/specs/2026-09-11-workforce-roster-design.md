# 岗位与数字员工清单页设计 · 口径（已确认）

> **状态**：**口径已确认**（§9 四项均已定），进入实现（先写失败测试，再写实现）。
> **日期**：2026-09-11　**基线**：`main`（后端 1159 项测试通过，CI 实跑通过）

## 1. 目标与非目标

**目标**：把管理台侧栏的占位项「员工与岗位」做成**只读**的真实页面——列出本租户**已知的岗位 / 数字员工标识**、各自绑定的知识库与关联任务数；同时**删掉侧栏写死的假数据**（「已配置 18 个岗位 / 42 个数字员工」）。

**非目标（明确不做）**：

| 不做 | 原因 |
| --- | --- |
| 新建岗位 / 数字员工**目录实体**（建表、增删改、归属关系） | 这是地基层面的领域建模（岗位从哪来？管理员手建还是内置枚举？数字员工与岗位的关系？），必须先立项定口径（宪法铁律四） |
| 展示**系统角色**（账号 `role`）人数分布 | 需要另加按角色聚合账户的查询，属独立范围 |
| 编辑岗位/员工与知识库的绑定 | 已有专门的「知识权限管理」页与接口，避免两处入口 |
| 「数字员工设置」与「模型与费用」两个占位项 | 同样缺数据源（`employee_key` 只是任务上的字符串；模型清单来自配置而非实体），本轮不动 |

## 2. 事实核查（实际读码确认）

| # | 事实 | 位置 |
| --- | --- | --- |
| 1 | 岗位 / 数字员工都只是**自由文本标识**，没有目录实体 | `app/domain.py:47`（`employee_key`）、`app/knowledge_policy.py:27-28` |
| 2 | 知识范围绑定按 `(tenant_id, binding_type='role'\|'agent', binding_key)` 存放，**没有列出全部绑定的方法** | `app/knowledge_policy.py`、`migrations/004` |
| 3 | 任务表有 `tenant_id` / `employee_key`，可做按标识计数；但任务仓储**没有聚合查询** | `migrations/001_initial.sql:3-19`、`app/domain.py:74-102` |
| 4 | 知识范围管理的权限是**仅 `super_admin`** | `app/main.py:764-766` |
| 5 | 侧栏底部「已配置 18 个岗位 / 42 个数字员工」是**写死的假数据** | `admin-web/src/app/AppShell.tsx` |

## 3. 后端：两个只读查询（无迁移）

### 3.1 知识范围绑定清单

两个实现同时新增：

```python
def list_bindings(self, context: UserContext) -> dict[str, dict[str, list[str]]]:
    """返回 {"role": {key: [kb_id, ...]}, "agent": {key: [...]}}；仅 super_admin 可调用。"""
```

- 内存实现：遍历两张 scopes 表，按租户过滤并排序。
- PostgreSQL 实现：`SELECT binding_type, binding_key, knowledge_base_id FROM workbench_knowledge_access_bindings WHERE tenant_id = %s ORDER BY binding_type, binding_key, knowledge_base_id` 后分组。
- **权限在仓储层同样强制**（复用 `_ensure_admin`），避免调用方绕过。

### 3.2 任务数按标识聚合

`TaskStore` 与 `PostgresTaskRepository` 同时新增：

```python
def count_by_employee(self, tenant_id: str) -> dict[str, int]:
    """本租户内按 employee_key 统计任务数。"""
```

- 内存：遍历 `_tasks` 过滤租户后计数。
- PostgreSQL：`SELECT employee_key, COUNT(*) FROM workbench_tasks WHERE tenant_id = %s GROUP BY employee_key`。

## 4. 接口契约（须同步 `docs/api-contract.md`）

`GET /api/v1/workforce/roster`

- **权限**：仅 `super_admin`；其他角色 `403`「只有超级管理员可以查看岗位与数字员工清单」；未认证 `401`。
- **租户隔离**：只统计与列出当前租户的数据。
- **数据来源（三个事实源的并集）**：知识范围里的 `role` 绑定、`agent` 绑定、以及任务中出现过的 `employee_key`。
- 响应：`{"items": [{"key", "role_knowledge_base_ids": [...], "agent_knowledge_base_ids": [...], "task_count": n}], "total": <条数>}`

| 字段 | 说明 |
| --- | --- |
| `key` | 岗位 / 数字员工标识（去重后的并集，同一标识只出现一次） |
| `role_knowledge_base_ids` | 该标识作为**岗位**绑定的知识库 id（未绑定时为空数组） |
| `agent_knowledge_base_ids` | 该标识作为**数字员工**绑定的知识库 id（未绑定时为空数组） |
| `task_count` | 本租户内 `employee_key == key` 的任务数（无任务时为 `0`） |

- 排序：`task_count` 倒序，其次 `key` 升序（用得多的在前，结果稳定）。
- 只读：不接受任何写动作；不返回账号、手机号或任何 PII。

## 5. 管理台页面

- 侧栏把占位项「员工与岗位」**接上真实页面**（`view: 'workforce'`，URL `?view=workforce`）。
- **删除** `AppShell` 里写死的 `side-summary` 装饰块（18/42 假数据）。
- 页面（`admin-web/src/features/workforce/`，沿用既有 feature 结构与外壳类名）：
  - 表格/列表列：标识、岗位知识范围（id 芯片，未绑定显示「未绑定」）、数字员工知识范围（同上）、任务数
  - 加载 / 空 / 错误（含「重新尝试」）三态；403 显示「当前账号没有查看岗位与数字员工的权限」
  - 顶部说明：这是**只读**视图、数据来自知识范围绑定与任务记录；不做增删改（编辑走「知识权限管理」）

## 6. 测试计划（先写测试，后写实现）

| 层次 | 覆盖 |
| --- | --- |
| 仓储（内存 / PG 假连接） | `list_bindings` 只返回本租户、按类型与 key 分组排序；**非 super_admin 抛 `PolicyError`**；PG 的 SQL 与参数正确 |
| 任务聚合 | 内存与 PG（假连接）的 `count_by_employee` 正确分组、只统计本租户 |
| 接口 | 401 / 403（ceo 也 403）/ 200；**三个事实源并集**去重；`task_count` 正确；未绑定的标识也出现；排序稳定；跨租户数据不可见；响应不含 PII |
| 前端 | api 错误映射；页面渲染三源合并结果、空态、错误态重试；侧栏假数据已消失（页面不含「18 个岗位」这类文案断言） |
| 契约守护 | 新路由必须出现在 `docs/api-contract.md`（`test_api_contract_coverage.py`） |

## 7. 已知限制（实现后需如实登记）

1. **不是目录管理**：没有新增/编辑/停用岗位或数字员工的能力，页面只反映"已经出现过的标识"；真正的目录实体需单独立项。
2. **系统角色（账号 `role`）不在本页**：需要另加账户聚合查询。
3. **`task_count` 为精确匹配**：`employee_key` 是自由文本，写法不同（大小写、空格）会被视作不同标识；不做归一化（归一化会掩盖数据问题）。
4. 「数字员工设置」与「模型与费用」仍是占位项（无数据源）。

## 8. 决策记录（已确认）

| # | 决策 | 结论 |
| --- | --- | --- |
| D1 | 查看权限 | **仅 `super_admin`**（与知识范围管理一致） |
| D2 | 是否含系统角色分布 | **不纳入**（另需账户聚合查询） |
| D3 | 侧栏写死假数据 | **删除装饰块**（不改为实时请求） |
| D4 | 是否展示任务数 | **展示**（按 `employee_key` 精确匹配） |

## 9. 落地清单

1. `app/knowledge_policy.py`：两个实现新增 `list_bindings(context)`。
2. `app/domain.py`（`TaskStore`）与 `app/repository.py`（`PostgresTaskRepository`）：新增 `count_by_employee(tenant_id)`。
3. `app/main.py`：`GET /api/v1/workforce/roster` + 视图模型。
4. `admin-web/src/features/workforce/`：types / api / state / `WorkforcePage.tsx` + 测试。
5. `admin-web/src/app/AppShell.tsx`（接上 `view: 'workforce'`、删除假数据块）、`App.tsx`（路由）、`global.css`（追加样式）。
6. `docs/api-contract.md`（新章节）、`docs/delivery-gates.md`、`docs/delivery-readiness-checklist.md` 同步。
7. 全量回归（`pytest` + `compileall` + 两端 vitest/build + desktop `node --test`），CI 实跑确认。
