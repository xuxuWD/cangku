# 攻击面八类检查 · 真实环境复测手册（1.12）

> **用途**：在 **staging** 上把本机已完成的安全攻击面八类检查（[`docs/security-attack-surface-report.md`](file:///d:/徐徐AI学习/公司工作台/docs/security-attack-surface-report.md) §2）**严格重放**并留档证据，产出 1.12 判据（[`docs/delivery-remaining-checklist.md`](file:///d:/徐徐AI学习/公司工作台/docs/delivery-remaining-checklist.md) 组 1 → 1.12）。
> **上位真源**：立项规格 [`docs/superpowers/specs/2026-09-16-attack-surface-retest-design.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-16-attack-surface-retest-design.md)（范围 / 裁决 / 红线）；判据口径以**报告 §2 原文**为准，与其冲突时以报告为准并回改本手册。
> **执行方式**：AI **不连** staging / 生产。由你在服务器上执行本手册命令，把**脱敏后**的输出回传后由我判读（宪法 §六；输入索取表红线 4）。
> **状态**：**待执行（未在 staging 运行过）**。本手册为 V1 产出（2026-09-16）；V2 执行需 I1–I14 到位 + **单独写授权**；V1/V2/V3 分期与待裁决点见立项规格 §1.3 / §4。
> **日期**：2026-09-16

## 0. 安全边界（先读）

1. **写操作须单独授权**：本手册第 1 / 4 / 5 / 8 类及第 3 类的 `logout` 含写操作（造数、建任务 / 提案、注销会话、锁定探针账号）——未获授权**不得执行**（口径同 [`docs/readonly-verification-runbook.md`](file:///d:/徐徐AI学习/公司工作台/docs/readonly-verification-runbook.md) §0 第 4 条）。
2. **绝不使用真人账号**：第 8 类会锁定账号（默认 5 次失败 / 300 秒窗口 ⇒ 锁定 900 秒）；只用 I12 **专用探针账号**与演练账号。
3. **敏感值不回传**：令牌、口令、DSN、密钥一律用 `***` 替换后再回传；证据不得含明文手机号、口令 / 哈希、密钥、令牌值。
4. **不得为「让复测通过」改配置 / 改代码**：期望不符 ⇒ 停手、原文登记、按立项规格 §2.4 处理。
5. **不复测开发态约定**：第 6 类只复测 `401` 面（development 态 `200` 属设计约定，报告 §4 已知限制 8）。

### 0.1 占位符约定

| 占位符 | 含义 |
| --- | --- |
| `$BASE` | staging 入口，如 `https://staging.example.internal`（须 HTTPS、非本地，两个探针脚本均强制校验） |
| `$TOKEN_ADMIN` | 超管令牌（I10；获取见 §1.2） |
| `$TOKEN_EMP_A` / `$TOKEN_EMP_B` | 同租户两个 employee 令牌（不同自然人；均已绑 TOTP） |
| `$TOKEN_A` / `$TOKEN_B` | 租户 A / 租户 B 令牌（第 1 类；见 §2） |
| `$DSN_RO` | 只读库账号连接串（I5；`psql` 用不带 `+psycopg` 的写法） |
| `$PROBE_PHONE` / `$PROBE_PASSWORD` | **I12 专用探针账号**（会被锁定） |
| `$TASK_ID` / `$PROPOSAL_ID` / `$ACCOUNT_ID` / `$EVENT_ID` / `$ROLE_KEY` | 演练租户内的真实资源标识（造数见 §2.2） |

## 1. 前置

### 1.1 账号与角色矩阵

| 用途 | 账号 | 来源 | 备注 |
| --- | --- | --- | --- |
| 审批 / 管理面 | 超管 × 1 | I10（或引导注册，见 §1.2 情形 B） | 第 2 / 4 / 5 / 7 类 |
| 垂直越权（第 2 类） | employee × 1（已绑 TOTP） | 演练租户自建（注册 + 审批） | 受限会话 `scope=totp_enrollment` 不算（会 `403`「需要先完成动态口令绑定」，属另一口径） |
| 同租户非发起人（第 1 类） | employee × 2（**不同自然人**） | 同上 | 其中 1 人为任务发起人 |
| 跨租户（第 1 类） | 租户 A / 租户 B 各一枚令牌 | I10 只含一个租户 ⇒ **第二租户由超管走「注册 + 审批」自建**（本机已验证路径，需额外手机号） | 每 KIND 在两租户各造 1 个真实资源 |
| 资源滥用（第 8 类） | **I12 专用探针账号** × 1 | I12 | 会被短时锁定；**禁真人账号** |

### 1.2 取令牌

按 [`docs/readonly-verification-runbook.md`](file:///d:/徐徐AI学习/公司工作台/docs/readonly-verification-runbook.md) **§1.3 三种情形**执行（情形 A 已有超管 / 情形 B 首次部署引导 / 情形 C `scope` 非 `full` 时先绑 TOTP）。接口 `POST /api/v1/auth/sessions`（`app/main.py:3572`）。

### 1.3 执行前核对（三项）

1. `WORKBENCH_ENV ≠ development`（第 6 类判据前提；I14 / 1.2 口径）；
2. 演练租户内已配置**启用中的数字员工**（`employee_key`）——`POST /api/v1/tasks` 必填（`app/main.py:335`）；
3. `WORKBENCH_PLANNER_TOOLS` 非空——建计划提案前置（默认空时 `422`「未配置任何可用工具」），且第 4 / 5 类的提案项依赖它。

### 1.4 建议执行顺序

**`2 → 3 → 6 → 7 → 4 → 5 → 1 → 8`**：先只读类，再写类；第 8 类会锁定探针账号，放最后（避免影响其他项）；第 1 类需要先造对照组数据（§2.2）。

---

## 2. 第 1 类 水平越权（跨租户）【探测只读；对照组造数为写】

### 2.1 探针（复用资产，不新写代码）

```bash
python scripts/cross_tenant_probe.py --base-url "$BASE" \
  --token-a "$TOKEN_A" --token-b "$TOKEN_B" \
  --resource "task:<A_ID>:<B_ID>"
```

- 参数 `scripts/cross_tenant_probe.py:309-320`；**6 类 KIND**（`task` / `plan_proposal` / `content_task` / `run_metrics` / `orchestration_proposal` / `commercial_lifecycle`，`:63-70`）每类一行 `--resource`；**漏 `--resource` ⇒ `exit=2`**（`:335-337`）。
- **判据**：`exit=0` 且报告 `A→A=200 B→B=200 A→B=404 B→A=404`（本机 2026-09-16 已实测 task 一种全绿）。

### 2.2 对照组造数（写；逐 KIND 在两租户各造 1 个真实资源）

造数路径逐 KIND 见 [`docs/delivery-remaining-checklist.md`](file:///d:/徐徐AI学习/公司工作台/docs/delivery-remaining-checklist.md) 1.7 子项（`POST /api/v1/tasks` `:2985`、`POST /api/v1/content-tasks` `:679`、`POST /api/v1/tasks/{task_id}/plan-proposals` `:3834`、建 run `:3103`/`:3905`、`POST /api/v1/orchestration-proposals` `:3966`、`POST /api/v1/commercial/exports`/`deletion-requests` `:934`/`:976`）。

### 2.3 补充（同租户非发起人，报告第 1 类第 3 行）

用 `$TOKEN_EMP_B` 读 `$TOKEN_EMP_A` 发起的任务 ⇒ 期望 `404`：

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/api/v1/tasks/<A 发起的 TASK_ID>" \
  -H "Authorization: Bearer $TOKEN_EMP_B"
```

### 2.4 对照（合法访问）

发起人本人读自己的任务 ⇒ `200`（证明不是全盘拒绝）。

---

## 3. 第 2 类 垂直越权（普通用户调管理员接口）【读】

以 **employee 令牌**逐接口调用（`$TOKEN_EMP_A`），**8 个接口全部期望 `403`**（权限中间件在业务处理前拦截）：

| # | 接口 | 方法 + 路径（行号） | 期望 |
| --- | --- | --- | --- |
| 1 | 任务审批 | `POST /api/v1/tasks/{task_id}/approve`（`:3036`） | 403 |
| 2 | 注册申请列表 | `GET /api/v1/auth/registrations`（`:3437`） | 403 |
| 3 | 改他人口令 | `POST /api/v1/auth/accounts/{account_id}/password`（`:3772`） | 403 |
| 4 | 重置他人 TOTP | `POST /api/v1/auth/accounts/{account_id}/totp-reset`（`:3746`） | 403 |
| 5 | 死信列表 | `GET /api/v1/dead-letters`（`:1021`） | 403 |
| 6 | 死信重投 | `POST /api/v1/dead-letters/{event_id}/replay`（`:1044`） | 403 |
| 7 | Runtime 健康 | `GET /api/v1/runtimes/health`（`:1014`） | 403 |
| 8 | 知识范围角色读取 | `GET /api/v1/knowledge-access/roles/{role_key}`（`:2180`） | 403 |

- **id 取值**：`403` 在业务前拦截，id 可用**演练租户真实值**（推荐）或占位值；`{account_id}` 一律用**演练账号**，避免误伤。
- **红线**：接口 3 / 4 即使返回非 `403`（即权限失效），**立即停手登记**，绝不在真实账号上完成后续操作。
- 本机口径：报告第 2 类 8 接口均 `403`；§1.2 若用受限会话会得 `403`「需要先完成动态口令绑定」——文案不同，属**前置不满足**，不算本条通过。

---

## 4. 第 3 类 身份伪造【读；`logout` 一处为写】

对受保护接口（默认探针 `GET /api/v1/approvals/pending`，`app/main.py:3504`）：

| # | 场景 | 构造方式 | 期望 |
| --- | --- | --- | --- |
| 3.1 | 不带任何凭证 | 仅访问路径，无 `Authorization` 头 | 401 |
| 3.2 | 伪造签名令牌 | `Authorization: Bearer aGVsbG8.forgedsignature` | 401 |
| 3.3 | 篡改 payload 保留原签名 | 取一枚 `$TOKEN_EMP_A`：payload 段 base64 解码 → 把角色字段改为 `super_admin` → 拼回（**签名段原样不动**） | 401（签名不匹配） |
| 3.4 | 已过期令牌 | **不可造**（staging 无法签发过期令牌）⇒ 替代：先 `POST /api/v1/auth/logout`（`:3605`）再用**同一令牌**请求 | 401（服务端撤销生效） |
| 3.5 | 对照：有效令牌 | 正常 `$TOKEN_EMP_A` 访问 | 非 401（证明令牌被接受、非全盘拒绝） |

- **3.3 备注**：若 payload 解码后无法识别角色字段（令牌结构以实现为准），改为改动 payload 段任一字符（签名段不动），并注明与报告口径的差异。
- **3.4 结论口径**：如实标注「**过期路径未复测（本机已覆盖）**」；撤销路径与过期路径同属「令牌失效 → 401」，但不互相替代。
- 本机输出样例：`no_credentials=401` / `forged_signature=401` / `expired_token=401` / `tampered_role_keep_signature=401`。

---

## 5. 第 4 类 字段提权【写（演练租户内）】

| # | 场景 | 请求 | 期望 |
| --- | --- | --- | --- |
| 4.1 | 注册塞 `"role":"super_admin"`、`"status":"approved"` | `POST /api/v1/auth/registrations`（`:3412`），体在 §5.1 基础上加多余字段 | 422（`extra=forbid`，`RegistrationCreate:3318`） |
| 4.2 | 审批塞额外字段 | `POST /api/v1/auth/registrations/{account_id}/approval`（`:3453`）加 `"is_admin":true` | 422（可并测任务审批 `:3036` 同款） |
| 4.3 | 注册传 `"tenant_id":"t-hacker"`（非首管理员） | 同 4.1 路径，不带多余字段；前置＝**已有超管** | 响应 `tenant_id=null`、`status=pending`（客户端租户被忽略） |
| 4.4 | 计划步骤 `kind` 服务端推导 | `POST /api/v1/tasks/{task_id}/plan-proposals`（`:3834`），体 `{"goal":"…","idempotency_key":"…"}` | 响应步骤 `kind` / `requires_approval` 与工具白名单一致（**观察式**；生成器伪造面不可造，见立项规格 §2.3） |
| 4.5 | 弱口令 × 3 | 同 4.1 路径，口令分别 `1234567890` / `aaaaaaaaaa` / `password123` | 均 422（纯数字 / 重复单一字符 / 常见弱口令） |

请求体基线（`phone` 必须是**未被占用**的演练手机号）：

```json
{"phone":"<演练手机号>","password":"<≥10 位强口令>","position":"<岗位>","full_name":"<姓名>"}
```

---

## 6. 第 5 类 注入【写（演练租户内）】

### 6.1 建任务注入（`POST /api/v1/tasks` `:2985`；体必填 `title` / `employee_key` / `idempotency_key`，`app/main.py:331-339`）

标题分别用三种载荷：

```
'; DROP TABLE users;--
<script>alert(1)</script>
; rm -rf / | cat /etc/passwd
```

**期望**：均 `201`，响应中标题与输入**逐字相等**（字面存储、原样回显）；**全程无任何 500**。

### 6.2 计划目标注入（`POST /api/v1/tasks/{task_id}/plan-proposals` `:3834`）

`goal` 用 `'; DROP TABLE users;-- <script>alert(1)</script>` ⇒ 期望 `201`，响应 `goal` 与输入逐字相等。

### 6.3 驳回原因注入（`POST /api/v1/plan-proposals/{proposal_id}/rejection` `:3881`、`POST /api/v1/auth/registrations/{account_id}/rejection` `:3476`）

`rejection_reason` 用 `'; DROP TABLE users;--` / `<script>alert(1)</script>` ⇒ 期望 `200`，原因字段逐字相等。

### 6.4 强格式字段注入（注册路径）

手机号用 `' OR 1=1 --` 与 `1<script>alert1` ⇒ 期望均 `422`（格式校验拒绝）。

**判据小结**：文本字段字面存储；本项目响应为 `application/json`、不渲染 HTML、不在请求路径执行 shell ⇒ 无注入语义改变、**无 500**。

---

## 7. 第 6 类 绕过前端【读】

仅带身份请求头、**不带任何凭证**访问受保护接口 ⇒ 期望 `401`（staging 不信任客户端自填角色）：

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/api/v1/approvals/pending" \
  -H 'X-Tenant-Id: t-x' -H 'X-User-Id: u-x' -H 'X-User-Role: super_admin'
```

- 前置：`WORKBENCH_ENV ≠ development`（§1.3 第 1 项）——否则该行为是**设计内开发态约定**，属前置不满足、不算本条通过。
- development 态 `200` 面**不复测**（立项规格 §1.5 第 5 条）。

---

## 8. 第 7 类 信息泄露【读】

### 8.1 响应穷举比对

采集四类响应：注册响应（§5 基线）、账号视图 `GET /api/v1/auth/registrations`（`:3437`）、计划提案视图 `GET /api/v1/plan-proposals/{proposal_id}`（`:3853`）、登录响应 `POST /api/v1/auth/sessions`（`:3572`）。

穷举串：明文手机号、`password`、`password_hash`、`scrypt$`、`access_token`、`totp_secret`、bootstrap 令牌的值、`WORKBENCH_AUTH_SECRET` 的值。

**期望**：除登录响应含 `access_token`（设计内、登录接口正常返回体）外，其余全部**无命中**；注册响应手机号应为 `138****0001` 式脱敏。

### 8.2 审计面

```bash
python scripts/customer_acceptance_probe.py --base-url "$BASE" --token "$TOKEN_ADMIN" \
  …（参数按 scripts/customer_acceptance_probe.py:659-683）
```

- `_check_audit_log:521` 同口径判定；另用只读账号抽查：

```bash
psql "$DSN_RO" -c "SET default_transaction_read_only = on" \
  -c "SELECT action, detail FROM workbench_audit_log ORDER BY id DESC LIMIT 20;"
```

- **期望**：顶层明细键全部在 `ALLOWED_DETAIL_KEYS` 内；手机号仅以 `phone_masked` 出现；**无** `password_hash`。
- **红线**：`WORKBENCH_AUTH_SECRET` 字面比对由**部署侧**执行（在服务端进程内比对本机值），**只回「命中 / 未命中」，密钥值不回传**。

### 8.3 错误响应

`404` 文案（如「任务不存在」）、`422` 结构（Pydantic `type/loc/msg/input`）⇒ **不得**含 `Traceback`、`site-packages`、`C:\`、`SELECT ` 等内部信息。

---

## 9. 第 8 类 资源滥用【写（锁定探针账号；放最后执行）】

### 9.1 顺序限流（错口令 × 5 ⇒ 第 6 次 429）

| 场景 | 期望 |
| --- | --- |
| 存在手机号（演练账号）连续 5 次错误口令 | `401×5`，第 6 次 `429` |
| 不存在手机号连续 5 次错误口令 | 同上 |
| 两次第 1 次的失败文案 | 完全一致（不泄露账号是否存在） |
| 已绑 TOTP 账号连续 5 次错误动态码 | 失败计数 `1→2→3→4→5`，第 6 次 `429` |
| 单次 scrypt 耗时 | 记录实测值（本机 53.3 ms） |

- **注意（同一步长重复用码会计入失败计数）**：不得在同一 TOTP 步长内反复重试；等**步长号真正推进**（验证器翻到下一个码，`≤30` 秒）再登录（口径见 [`docs/readonly-verification-runbook.md`](file:///d:/徐徐AI学习/公司工作台/docs/readonly-verification-runbook.md) §1.3 实操坑）。
- 默认参数：`5` 次 / `300` 秒窗口 / 锁定 `900` 秒（`app/settings.py:166-183`）。

### 9.2 并发版（复用资产）

```bash
python scripts/staging_concurrency_probe.py --base-url "$BASE" \
  --token "$TOKEN_ADMIN" --phone "$PROBE_PHONE" --password "$PROBE_PASSWORD" \
  --scene login_throttle --concurrency 8
```

- **第一次跑必然 `{401:8}`（已知并发窗口，不是缺陷）——紧接着再跑一次即 `{429:8}`（判 pass）**；**不得因此改代码 / 调配置**（口径同 1.8 子项）。
- 只用 I12 专用探针账号；口令不会写入报告。

---

## 10. 证据记录模板（回传用）

| 类别 | 检查项 | 方法 / 路径 | 身份 | 期望 | 实测（脱敏） | 判读（通过 / 差异 / 未复测） |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 探针 6 KIND | `cross_tenant_probe.py` | 租户 A / B | `exit=0` 且四象限 200/200/404/404 | | |
| 1 | 同租户非发起人 | `GET /tasks/{id}` | employee B | 404 | | |
| 2 | 8 接口逐一 | §3 表 | employee | 全部 403 | | |
| 3 | 无凭证 / 伪造签名 / 篡改 / 撤销后复用 / 对照 | §4 表 | — / employee | 401×4 + 非 401 | | |
| 4 | 5 项 | §5 表 | 超管 / 匿名注册 | 422 / 忽略 / 服务端推导 | | |
| 5 | 4 项 | §6 | 员工 / 超管 | 逐字相等、无 500、422 | | |
| 6 | 请求头身份 | §7 | 无凭证 | 401 | | |
| 7 | 响应 / 审计 / 错误体 | §8 | 超管 / 只读账号 | 无敏感命中 | | |
| 8 | 顺序 / 并发 / TOTP / scrypt | §9 | I12 探针账号 | 第 6 次 429；文案一致 | | |
| 3 / 4 | **不可造场景**（过期令牌、生成器伪造 kind） | 替代口径（立项规格 §2.3） | — | 如实标注「未复测」 | | |

**回传要求**：逐行填「实测」列（令牌 / 口令 / DSN 一律 `***`）；未执行的行填「未复测」并注明原因——**不得留空、不得以 `skipped` 读成 `pass`**。

---

## 11. 执行后收尾

1. **结论回写（V3）**：报告补 staging 结论节（含未复测项）；`delivery-remaining-checklist.md` 1.12 **勾选仅当八类证据齐备**（不可造项按立项规格 §4 已裁决口径计入结论）；`change-record.md` 留痕。
2. **造数清理**：演练租户内任务 / 提案 / pending 账号按约定清理或登记残留；探针账号锁定状态确认（自动到期）。
3. **差异处理**：任何不符预期项**只登记不现场修**（立项规格 §2.4）；修复另行立项。
4. **纪律**：回传前检查证据中无令牌 / 口令 / 密钥；本手册不含任何写命令的「预跑」。

---

## 12. 本手册局限

1. 本手册**未在 staging 执行过**；判据口径全部来自报告 §2 的本机实测，命令行号来自当前提交（执行前如代码已前移，以 `git log` 核对）。
2. 本机 dev 态相关面（报告第 6 类 development `200`、直接调用 `normalize_steps` 等非 HTTP 面）**不在复测范围**（立项规格 §1.5）。
3. 手册与立项规格冲突时**以立项规格的裁决为准**；与报告 §2 冲突时**以报告为准**并回改本手册。