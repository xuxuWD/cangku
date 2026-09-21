# 「审计导出」专项方案（第 13 轮）

> 状态：**v2 · 2026-09-21 · 已交付（用户裁决 A/A/A/A；见 §9 交付记录）**。
> **唯一权威在别处**：权限口径 = [`permission-matrix.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/permission-matrix.md)（§3「审计：导出」行 = **仅 `super_admin` ✅**）；
> 审计面契约 = [`audit-log-api.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/audit-log-api.md)（§1 清单 / §4 不做 / §7-#4 裁决"只登记"）；
> 后端接口真源 = `docs/api-contract.md`（**改接口先改它**）。
>
> **证据级别**：源码判定 + 第 10 轮真机证据（`GET /api/v1/audits` 四档、`/audits/actions` 94 项）。

## 1. 背景：矩阵要求 vs 实现的唯一缺口

第 10 轮交付了「审计：查询」四档（`employee` 仅本人 / `department_lead`、`ceo`、`super_admin` 本租户），
但同一节 §3 的**「审计：导出」= 仅 `super_admin` ✅ 至今零实现**（`grep` 全仓无 audit export 端点）：
界面当时按"不给假入口"处理 —— 超管视图只显示一句「审计导出尚未接入…不提供导出按钮，也不会伪造下载入口」。
本轮把这个缺口补实。

## 2. 目标与非目标

**目标**：`super_admin` 能按**当前筛选条件**导出本租户审计记录（CSV / JSON 二选一），
**脱敏口径与查询一致**，**导出动作本身留审计**，超限不静默截断。

**非目标（本轮不做）**：
- **异步导出**（任务队列 + 生成包 + 过期清理 + 下载令牌）—— 属新运行域，另立；
- **导出历史 / 导出任务列表**页面（本轮只在审计里留一条痕，不做管理页）；
- **平台运营后台**（`admin-web`）的导出——它是早期原型（用环境变量注入身份，生产禁用，见 D-027），不在本轮；
- **跨租户 / 全平台导出**（属商业化生命周期导出，另有 `commercial/export_readers.py` 通道）；
- 员工档「仅本人相关」的**口径扩展**（`actor_id == 自己 OR target_id == 自己`）——属**口径选择**，见 §7-#4。

## 3. 接口设计（新增端点）

| 项 | 设计 |
| --- | --- |
| 路径 | `GET /api/v1/audits/export` |
| 权限 | **仅 `super_admin`**（矩阵 §3「审计：导出」）；其余四角色 ⇒ `403`「只有超级管理员可以导出审计日志」；匿名 ⇒ `401` |
| 筛选参数 | 与查询**同名同义**：`action`（**可重复**）/ `target_type` / `target_id` / `actor_id` / `since` / `until`（时间**必须带时区**，与查询同口径） |
| 新增参数 | `format`：`csv`（默认）/ `json`；`limit`：默认 **1000**、上限 **5000**（越界 ⇒ `422`） |
| 响应 | 文件流：CSV ⇒ `text/csv; charset=utf-8`（**带 UTF-8 BOM**，Excel 中文兼容）；JSON ⇒ `application/json`（`{"items":[…],"total":N,"exported_at":…}`） |
| 响应头 | `Content-Disposition: attachment; filename="audit-<tenant>-<UTC时间戳>.<csv\|json>"`；`X-Exported-Rows: <N>`（前端据此提示"已导出 N 条"，同源部署下可读） |
| 超限 | **`422`** + 如实文案（含**命中数**与**上限**："命中 5821 条，超过单次导出上限 5000 条；请缩小时间范围后重试"）——**不静默截断**（§7-#3 待你裁决） |
| 错误语义 | 与查询一致：动作码未知 ⇒ `422`；时间不带时区 ⇒ `422`；跨租户数据**不可能出现**（`tenant_id` 由服务端注入） |

**字段口径**：与 `GET /api/v1/audits` **逐字一致**（`record_id` / `action` / `actor_id` / `target_type` / `target_id` /
`phone_masked` / `detail` / `occurred_at`）；`phone_masked` 已是掩码列；`detail` 入库即受
`ALLOWED_DETAIL_KEYS` 白名单约束（不含口令 / 令牌），导出**再过一遍统一脱敏器**
（复用 `app/commercial/export_readers.py::audit_export_reader` 的同一口径，避免两套脱敏）。

**顺序语义**：与查询一致，**新 → 旧**（服务端固定顺序，导出不做排序参数）。

## 4. 安全要件（红线）

1. **越权优先**：`403` 先于任何参数校验（`ceo` 传非法 `format` 也拿 `403`，不泄露校验细节）；
2. **数据归属**：`tenant_id` **只从鉴权上下文取**，请求里没有该参数（也不接受）⇒ 跨租户导出**不可能**；
3. **不落敏感物**：CSV / JSON 里不得出现堆栈、SQL、内部路径、他人手机号原文（只有 `phone_masked`）、密钥；
4. **导出动作本身留审计**：新增 `AuditAction.AUDIT_EXPORTED = "audit.exported"`，
   明细 `{format, rows, filters}`（`filters` 为**字符串**，如 `action=skill.enabled&since=2026-09-01T00:00:00Z`）——
   这三个键**当前都不在** `ALLOWED_DETAIL_KEYS`（已核对：只有 `truncated` 在位）⇒ 需新增 **3 个白名单键**
   （`format` / `rows` / `filters`）；**被拒的导出（403 / 422）不写审计**（与既有 4xx 口径一致）；
5. **文件不落服务器**：同步生成、直接回给调用方，**不在服务端留临时文件**（避免"导出包遗留"）。

## 5. 前端交互（`workbench-web` 审计页）

| 档位 | 交互 |
| --- | --- |
| `super_admin` | 表单右侧新增「导出」按钮（次要按钮）：点击后用**当前筛选条件**（含 `action` 多选）请求导出 ⇒ 浏览器下载（Blob + `a[download]`）⇒ 成功提示「已导出 N 条」（`N` 取 `X-Exported-Rows`，缺失时回落为按行数统计）；**导出中**按钮 `loading` 且禁止重复点击 |
| `ceo` / `department_lead`（能查不能导） | **不渲染导出按钮**，但在页内说明里补一句「导出仅超级管理员可用」（**给原因，不静默隐藏**） |
| `employee` | 同上（且该档本就不含导出能力） |
| `customer_admin` | 整页无权限态（不变） |

**五态**：加载（按钮 loading）/ 成功（条数）/ **超限（422 原文，含命中数与上限）** / 无权限（403 原文）/ 失败（可重试）。
**文案下线**：`AUDIT_EXPORT_NOT_CONNECTED_NOTE`（"尚未接入"）在超管视图**撤下**，改为真按钮 + 说明
（「导出当前筛选条件下的记录；单次上限 5000 条」）；非超管视图的「仅超级管理员可用」为新增说明。

## 6. 影响面与兼容性

| 影响面 | 说明 |
| --- | --- |
| **契约覆盖守卫** | 新增路由 ⇒ 必须先写进 `docs/api-contract.md`（`tests/test_api_contract_coverage.py` 会拦） |
| **动作码** | `AuditAction` 94 → **95** 项 ⇒ `tests/test_audit_models.py` 的 `len(set(AuditAction)) == 94` 断言需改为 95 + 新增值断言；`/audits/actions` 端点返回 95 项（**前端自动跟随**，不复制枚举） |
| **前端用例** | 第 10 轮的「导出：超管只看到「尚未接入」说明，**没有任何导出按钮**」用例**翻转为**"有按钮 + 点击触发下载 + 条数提示"；新增超限 422 / 403 / 失败可重试三例 |
| **矩阵** | §3「审计：导出」由"零实现"改标 **已实现（仅 `super_admin`）**；§7 对应登记行关闭（§14 已预留该行） |
| **不做破坏** | 查询四档（第 10 轮）**零改动**；`GET /audits` 与 `/audits/actions` 响应形状不变 |

## 7. 待裁决（四项）

| # | 问题 | 选项 | 我的建议 |
| --- | --- | --- | --- |
| 1 | 本轮范围 | **A** 只做审计导出；**B** 导出 + 员工档自限口径扩展（`actor_id == 自己 OR target_id == 自己`，需改仓储 AND→OR 组合）；**C** 只做口径扩展 | **A**（导出的缺口是矩阵明确要求；口径扩展是"要不要包含别人对我账号的操作"，属产品口径选择，宜单独定夺） |
| 2 | 导出格式 | **A** CSV（默认，带 BOM）+ 可选 `format=json`；**B** 只 CSV；**C** 只 JSON | **A**（审计台账最常见是 Excel / CSV；JSON 便于程序消费，成本仅是同一份数据换序列化） |
| 3 | 超限行为 | **A** `422` 拒绝 + 告知命中数与上限（**不静默截断**）；**B** 截断到上限并在响应头/审计里标 `truncated=true`；**C** 加 `on_overflow=reject\|truncate` 让调用方选 | **A**（宪法"不得静默"：截断会让使用者以为"导全了"；真要全量应缩范围或走异步导出） |
| 4 | 导出是否留审计 | **A** 留（新增 `audit.exported` + 明细 `{format, rows, filters}`，需加 **3 个**白名单键）；**B** 不留 | **A**（导出审计记录本身是敏感动作：谁、何时、导了什么范围，必须可追溯；与 D-023 的"关键操作预埋日志"一致） |

## 8. 复测清单（裁决后按此执行）

1. 单元：`super_admin` 导出 ⇒ `200` + `Content-Disposition` + **`X-Exported-Rows` 与命中数一致**；CSV 首行是表头 + **BOM**；
2. 单元：`ceo` / `department_lead` / `employee` / `customer_admin` ⇒ **一律 `403`**；匿名 ⇒ `401`；`ceo` 传非法 `format` ⇒ **仍 `403`**（越权优先）；
3. 单元：`limit=5001` ⇒ `422`；命中数 > `limit` ⇒ `422` 且文案含命中数与上限；未知动作码 ⇒ `422`；naive 时间 ⇒ `422`；
4. 单元：筛选生效（`action` 多选 / `target_type` / `actor_id` / 时间窗口）⇒ 导出内容只含命中行；`employee` 的**自限不适用**（本就 403）；
5. 单元：成功后**恰好 1 条** `audit.exported`，明细含 `format` / `rows` / `filters`；被拒（403 / 422）**不写审计**；
6. 单元：导出文件里**不含**堆栈 / SQL / 路径 / 明文手机号（`phone_masked` 才是手机号列）；`detail` 过统一脱敏器；
7. 前端：超管点导出 ⇒ 触发下载 + 条数提示；超限 ⇒ 呈现 422 原文；非超管 ⇒ **无按钮但有"仅超级管理员"说明**；
8. 真机（只读为主 + 一次真实导出）：`super_admin` 导出本租户 ⇒ 行数与 `GET /audits` 的 `total` 一致、抽查脱敏；
   `ceo` ⇒ `403`；导出后 `GET /audits?action=audit.exported` 能查到那一条痕。

## 9. 交付记录（v2，2026-09-21）

**已落地**（用户按 §7 裁决 **A/A/A/A**：只做导出 / CSV 默认 + 可选 JSON / 超限 422 / 导出留痕）：

| 项 | 落地 |
| --- | --- |
| 后端端点 | `GET /api/v1/audits/export`（`app/main.py`）：权限 `ensure_can_export_audits` ⇒ `403`（**先于任何参数校验**）→ `format` / 动作码 / 时区 / `limit` 校验 ⇒ `422` → **命中数 > limit ⇒ `422`（不静默截断）** → 生成 CSV（**带 BOM**）/ JSON（形状与列表逐字一致）→ 写 `audit.exported` → 返回文件流 |
| 角色与常量 | `app/audit/models.py`：`AUDIT_EXPORT_ROLES = {super_admin}`、`AUDIT_EXPORT_MAX_ROWS = 5000`、`AUDIT_EXPORT_DEFAULT_ROWS = 1000`、`AUDIT_EXPORT_FORMATS = {csv, json}`、`can_export_audits` / `ensure_can_export_audits`（文案「只有超级管理员可以导出审计日志」） |
| 动作码与白名单 | 新增 `AuditAction.AUDIT_EXPORTED = "audit.exported"`（**94 → 95 项**）+ 3 个明细白名单键（`format` / `rows` / `filters`） |
| 前端 | `client.ts` 抽 `performRequest` + 新增 `requestRaw`（**仍只有这一处发 HTTP**）；`auditService.ts` 新增 `exportAudits` / `triggerDownload` / `AUDIT_EXPORT_HINT` / `AUDIT_EXPORT_ONLY_ADMIN_NOTE` / `AUDIT_EXPORT_MAX_ROWS` / `MOCK_EXPORT_NOTE`（旧「尚未接入」文案**下线**）；`AuditLogPage.tsx` 超管渲染「导出」按钮 + 五态（导出中 / 成功条数 / 超限 422 原文 / 无权限 / 失败可重试），非超管**无按钮但给"仅超级管理员可用"说明**；能力 `audit.export` 仅 `super_admin`（`session.tsx`） |
| 契约真源 | `docs/api-contract.md` 新增 `GET /api/v1/audits/export` 节（契约覆盖守卫要求先写文档） |

**反假（3 组，均实测）**：权限档位降级为「查询档」（`ensure_can_read_audits`）⇒ **6 红**；
去掉 `total > limit` 判定 ⇒ **2 红**；去掉 `audit_service.record(AUDIT_EXPORTED…)` ⇒ **2 红**。以上均还原复绿。

**真机（2026-09-21，仅一次实质写入 = 导出留痕本身）**：`employee` ⇒ `403` 且留痕不变；`limit=1` ⇒ `422`「命中 175 条，超过单次导出上限 1 条」且留痕不变；
CSV ⇒ `Content-Disposition: attachment; filename="audit-wiring-evidence-<UTC>.csv"`、`X-Exported-Rows = 103` **等于列表 `total`**、**BOM 在**、行数 = 表头 + 103、**无明文手机号**（只有 `136****0001`）；
JSON ⇒ `200`、`total = 103`、字段集与列表一致（8 键）、`exported_at` 在；**留痕 3 → 4（每次成功 +1）**，最新明细 `{"rows":103,"format":"json","filters":"action=account.login.succeeded"}`。

**本轮边界（未做）**：异步导出（任务队列 / 生成包 / 过期管理）；导出历史页面；`admin-web`（早期原型，身份走环境变量，生产禁用）；跨租户 / 全平台导出。

**门禁（2026-09-21 复核）**：后端全量 `tests = 2758 / failures = 0 / errors = 0 / skipped = 140`（**2618 passed**）+ `compileall app scripts` 退出码 0；
前端 `tsc --noEmit` 0 / `vitest` **45 files · 371 passed**（审计模块 34）/ `build` 成功 / 产物 grep（`console.log` 0、旧「尚未接入」导出文案 0；
残留的 1 处「尚未接入」是 `notConnected` 通用文案，属其他尚未接线模块，非本轮遗留）；`admin-web`：`tsc -b` 0 + `check:ui-copy` 通过。

**门禁抓到的一条真缺口（已修）**：`tests/test_frontend_audit_labels.py` 断言「前端 `AUDIT_ACTION_LABELS` 的动作码集合 == 后端 `AuditAction` 集合」——
新增 `audit.exported` 后**该用例报红**（`admin-web/src/features/auditLog/types.ts` 缺标签 ⇒ 界面会回落显示动作码）
⇒ 补 `'audit.exported': '审计日志已导出'` ⇒ 复绿（**这正是"新动作码必须同步标签"的守卫生效实例**）。

**⚠️ 界面层未验证（如实登记，不得读成已验 —— 2026-09-21 用户裁决）**：
本轮真机核对**全部在 HTTP 层**（`tmp/r13-audit-export-verify.py` 直连 `127.0.0.1:18113`），
**「导出」按钮没有被人在浏览器里点过**。以下四项**只有前端用例（jsdom）覆盖，无实机证据**：
① 点「导出」后下载是否真的落盘（`triggerDownload` 在 jsdom 下静默跳过，浏览器行为未验）；
② 成功提示里的条数是否确实取自响应头 `X-Exported-Rows`；③ 非超管三档是否确实"无按钮、有说明"；
④ 导出失败（如超限 `422`）时错误提示是否可读、是否如实说明"本次没有生成任何文件"。

第 14 轮原计划的浏览器走查（超管 + 员工两档）**因无法自取登录口令而未执行**——口令不在仓库、也无默认口令可试，
属**正确的安全设计**（不是缺陷）；用户 2026-09-21 裁决**跳过走查、按"未验证"登记**。
若日后要补齐，最小动作＝用超管账号在审计页点一次「导出」，核对下载文件名、提示条数与列表 `total` 三者一致。
