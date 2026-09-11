# 通用审计查询与管理台审计页设计 · 口径（已确认）

> **状态**：**口径已确认**（§9 四项均已定），进入实现（先写失败测试，再写实现）。
> **日期**：2026-09-11　**基线**：`main`（后端 1142 项测试通过，CI 实跑通过）

## 1. 目标与非目标

**目标**：审计已经在写（33 类动作、内存 / `workbench_audit_log` 双仓储、写入即白名单校验），但**只有「知识范围审计」有一个局部查询接口**，其余审计只能进数据库看。本设计补一个**通用只读查询接口**与管理台页面，把已落库的审计变成可查证据。

**非目标（明确不做）**：

| 不做 | 原因 |
| --- | --- |
| 导出 CSV / 归档 | 属另一条链路（导出要另行设计脱敏与体积上限），本轮只做查询 |
| 全文搜索 / 模糊匹配 `detail` | `detail` 是白名单键值，模糊搜索会引入未定义语义与性能风险 |
| 审计写入链路改造 | 写入侧已是白名单 + 递归敏感键校验，本轮不动 |
| 删除 / 清理审计 | 保留策略由 `WORKBENCH_RETENTION_POLICY`（audit 730 天）管辖，不在此接口 |

## 2. 事实核查（实际读码确认）

| # | 事实 | 位置 |
| --- | --- | --- |
| 1 | 审计写入已落库且明细经白名单 + 递归敏感键校验 | `app/audit/models.py`、`app/audit/service.py` |
| 2 | 仓储只有 `list_recent(tenant_id=None, limit)`；`tenant_id=None` 表示「全部租户」 | `app/audit/store.py:32-38,101-122` |
| 3 | `workbench_audit_log` 有 `id BIGSERIAL` 与三个索引（租户+时间、动作+时间、target_id） | `migrations/010_audit_log.sql` |
| 4 | 管理台只有一个局部审计入口（知识范围审计），无通用审计页；侧栏无审计项 | `admin-web/src/features/knowledgeAccess/`、`AppShell.tsx` |
| 5 | 既有权限口径参考：运行指标 summary 与编排提案为 `ceo`/`super_admin` | `app/main.py` |

## 3. 存储层（新增查询，无迁移）

两个仓储同时新增（接口一致）：

```python
def query(
    self,
    tenant_id: str,                      # 必填：强制租户隔离，不提供 None
    *,
    actions: Sequence[str] | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    actor_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AuditRecord], int]:      # (按时间倒序的本页记录, 命中总数)
```

- 内存实现：过滤 → 按 `occurred_at` 倒序 → 切片；`total` 为过滤后条数。
- PostgreSQL 实现：同一套 `WHERE` 条件（租户必填 + 可选动作/目标/操作者/时间范围）配 `ORDER BY id DESC LIMIT/OFFSET`，另发一条 `COUNT(*)` 求 `total`。
- **`tenant_id` 必填**：把「严格本租户」落在存储层，避免调用方误传 `None` 拿到全部租户数据。
- 既有 `list_recent` 保持不变（其它调用方与测试继续可用）。

## 4. 服务层

`AuditService.query(...)` 作为只读入口，转发到仓储（与 `record` 对称，让路由不直接摸 `.store`）。

## 5. 接口契约（须同步 `docs/api-contract.md`）

`GET /api/v1/audits`

| 参数 | 说明 |
| --- | --- |
| `action` | 可重复（`?action=a&action=b`）；每个值必须属于 `AuditAction`，否则 `422` |
| `target_type` / `target_id` / `actor_id` | 精确匹配，可选 |
| `since` / `until` | ISO 8601，**必须带时区**，否则 `422`；`until` 为闭区间上界 |
| `limit` | 默认 `50`，范围 `1`~`200`，越界 `422` |
| `offset` | 默认 `0`，`>= 0`，越界 `422` |

- **权限**：仅 `ceo` / `super_admin`；其他角色 `403`「只有 CEO 或超级管理员可以查看审计日志」；未认证 `401`。
- **租户隔离**：只返回 `tenant_id == 当前租户` 的记录；`tenant_id` 为空的全局记录**不返回**（避免把系统级上下文混进租户视图）。
- **响应**：`{"items": [...], "total": <命中总数>, "limit": <本次 limit>, "offset": <本次 offset>}`，`items` 按时间倒序。
- **条目字段**：`record_id`、`action`、`actor_id`、`target_type`、`target_id`、`phone_masked`、`detail`、`occurred_at`。**不含 `tenant_id`**（恒等于调用者租户，返回属噪音）。
- 只读：不接受任何写动作；`detail` 直接返回落库内容（写入侧已白名单化，无需二次加工）。

## 6. 管理台页面（admin-web）

- 侧栏新增「安全与审计」（`view: 'audit'`），URL `?view=audit`，与既有页面同一套外壳与样式约定。
- 筛选区：动作（多选，取值来自前端标签表）、操作者、目标 ID、起止时间（`datetime-local`）、每页条数。
- 列表：时间、动作（中文标签 + 原始动作码）、操作者、目标、脱敏手机号、明细（键值对逐条渲染，**只渲染一层标量**，不 dump 嵌套）。
- 分页：`上一页 / 下一页` + 「共 N 条（第 x–y 条）」；筛选变化时 offset 归零。
- 空态 / 加载态 / 错误态 + 「重新尝试」；403 显示「当前账号没有查看审计日志的权限」。
- **标签漂移守护**：新增 `tests/test_frontend_audit_labels.py`，比对 TS 标签表的键与 `AuditAction` 取值，**后端每个动作都必须有标签**（沿用收件箱 kind 漂移的守护思路）。

## 7. 测试计划（先写测试，后写实现）

| 层次 | 覆盖 |
| --- | --- |
| 存储（内存） | 租户必填隔离；动作多选、目标、操作者、时间范围过滤；倒序；`limit`/`offset` 与 `total` 正确 |
| 存储（PG 假连接） | `WHERE` 条件与参数齐全（含 `ANY` 与时间条件）、`COUNT(*)` 语句、`LIMIT/OFFSET` 参数 |
| 服务 | `query` 转发与返回值形状 |
| 接口 | 权限矩阵（401 / 403 / 200）；未知 `action` 422；无时区时间 422；`limit`/`offset` 越界 422；跨租户数据不可见（两个租户各写一条，只看到自己的）；响应含 `total`/`limit`/`offset`；只读（不存在写方法） |
| 前端 | api 参数拼装与错误映射；筛选/分页交互；空态与错误态；标签漂移守护 |
| 契约守护 | 新路由必须出现在 `docs/api-contract.md`（`test_api_contract_coverage.py`） |

## 8. 已知限制（实现后需如实登记）

1. **offset 分页的错位**：审计是只追加的，翻页期间若有新写入，`offset` 可能跳过/重复个别记录；用筛选（时间范围、动作）可规避。需要严格一致性时应改为游标分页。
2. **`total` 为额外 COUNT 查询**：大表 + 宽时间范围下有一次额外开销（现有索引覆盖租户+时间）。
3. **不支持导出与模糊搜索**（见 §1）。
4. **只返回租户维度审计**：`tenant_id` 为空的全局记录不可见（如需排查系统级问题要走数据库或后续再加专门入口）。

## 9. 决策记录（已确认）

| # | 决策 | 结论 |
| --- | --- | --- |
| D1 | 查看权限 | **`ceo` + `super_admin`** |
| D2 | 租户隔离 | **严格本租户，不含全局记录** |
| D3 | 分页 | **`limit` + `offset` + `total`** |
| D4 | 前端入口 | **侧栏新增「安全与审计」页** |

## 10. 落地清单

1. `app/audit/store.py`：内存 + PG 两侧 `query(...)`。
2. `app/audit/service.py`：`AuditService.query(...)`。
3. `app/main.py`：`GET /api/v1/audits` + 权限/参数校验与视图模型。
4. `admin-web/src/features/auditLog/`：types / api / state / `AuditLogPage.tsx` + 测试。
5. `admin-web/src/app/AppShell.tsx`、`App.tsx`：`view: 'audit'` 与路由。
6. `admin-web/src/styles/global.css`：审计页样式（追加，不打乱既有内容）。
7. `tests/test_frontend_audit_labels.py`：标签漂移守护。
8. `docs/api-contract.md`（新接口章节）、`docs/delivery-gates.md`、`docs/delivery-readiness-checklist.md` 同步。
9. 全量回归（`pytest` + `compileall` + 两端 vitest/build + desktop `node --test`），CI 实跑确认。
