# 只读核验清单 · 岗位/数字员工目录与阶段 2 闸门

> **用途**：在 **staging**（或经授权的真实库）上核验「数字员工设置 / 知识范围写路径闸门」的落地状态与**存量风险**。**全部命令只读**：不改数据、不改配置、不跑迁移。
> **执行方式**：AI **不连** staging/生产。由你在服务器上执行本清单，把输出回传后由我判读。
> **验证状态**：本清单的 **9 条 SQL、只读包装、只读角色建法、令牌获取三种情形，以及 §3 API 组与 §4 跨租户探测脚本，均已于 2026-09-12 在本机验证**（样例输出见 §7）：SQL 与只读角色跑在一次性真实 PostgreSQL 16 上（只读角色以**真实 DSN（TCP + 密码）**跑通并确认写操作被拒）；**§3/§4 跑在真实 HTTP 服务（`uvicorn`）上并造了两个租户**；令牌三种情形以 FastAPI `TestClient`（进程内，走同一套中间件与路由）跑通。**本清单本身尚未在 staging 执行过**——staging 未就绪（阻塞项 1）。

## 0. 安全边界（先读）

1. **会话级只读包装**：所有 SQL 都用 `-c "SET default_transaction_read_only = on"` 执行。本机已验证：同一会话内 `SELECT` 正常，而 `CREATE TABLE` 被直接拒绝（`ERROR: cannot execute CREATE TABLE in a read-only transaction`）。
2. 建议再用**只读库账号**（仅 `GRANT SELECT`）执行，双保险。
3. **不要**把 DSN、口令或令牌贴进聊天；回传时用 `***` 替换。
4. **不要**在这一轮顺手执行 §5 列出的写命令（含直接启动应用服务——启动即跑迁移）。

## 1. 前置

| 项 | 说明 |
| --- | --- |
| `WORKBENCH_PSQL_DSN` | `postgresql://<只读账号>:<口令>@<主机>:5432/<库名>`。**注意**：应用侧配置用 `postgresql+psycopg://` 前缀，`psql` 用**不带** `+psycopg` 的写法 |
| `BASE` | 应用入口，例如 `https://staging.example.internal` |
| `TOKEN` | 超管令牌（只有 §3 需要）。获取方式见 §1.3 |
| 工具 | `psql`、`curl`、`jq`（`psql` 需安装 `postgresql-client`，与 §5 排掉的 `migration_backup_drill.py` 所需 `pg_dump` / `pg_restore` 是同一套客户端） |

### 1.1 怎么拿到「只读连接串」（DBA 执行）

在目标库上以**管理员**身份执行下面三步（**2026-09-12 已在本机一次性真实 PostgreSQL 16 上验证**：建角色 → 授权 → 用该 DSN 跑 §2 的 9 条查询全部通过、写操作被拒）：

```sql
-- ① 建只读账号（不要给 SUPERUSER / CREATEDB / CREATEROLE）
CREATE ROLE workbench_ro LOGIN PASSWORD '<强口令>';

-- ② 允许连接 + 读取（pg_read_all_data 是 PG14+ 内置角色）
GRANT CONNECT ON DATABASE <库名> TO workbench_ro;
GRANT pg_read_all_data TO workbench_ro;

-- ③ 核对属性：应得到 workbench_ro|f|f|t（非超管、不能建库、可登录）
SELECT rolname, rolsuper, rolcreatedb, rolcanlogin FROM pg_roles WHERE rolname = 'workbench_ro';
```

- **为什么用 `pg_read_all_data`**：它**自动覆盖未来迁移新建的表**。本机实测：管理员新建一张表后，只读账号**无需再授权**即可 `SELECT`。若改用显式授权，必须额外写
  `ALTER DEFAULT PRIVILEGES FOR ROLE <应用库账号> IN SCHEMA public GRANT SELECT ON TABLES TO workbench_ro;`
  否则**迁移 023 之后的新表该账号读不到**，核验会在未来静默失败。
- **多租户共用实例**时，`pg_read_all_data` 会读到该库内所有租户的表；若不能接受，改用显式 `GRANT SELECT ON ALL TABLES`（此时必须同时写上面那条 `ALTER DEFAULT PRIVILEGES`）。
- 只读账号**不需要**写权限；本清单每条 SQL 仍会再套一层会话级只读（§0 第 1 条），形成双保险。
- 传参方式：口令与 DSN 走**密钥系统/临时环境变量**，不要写进仓库、不要贴进聊天（回传时用 `***` 替换）。

### 1.2 怎么拿到「目标库的已应用迁移清单」

应用在 `postgres` 模式下启动时会**自动应用未执行的迁移**，并把结果记在 `workbench_schema_migrations`。因此从目标库读取的准确方式是：

```sql
SELECT version, applied_at FROM workbench_schema_migrations ORDER BY version;
```

把逗号拼接的结果填入环境变量 `WORKBENCH_APPLIED_MIGRATIONS`（`staging_preflight.py` 与 `migration_backup_drill.py --phase list` 都据此比对）。
**若该表不存在**，说明该库的迁移**不是**由应用执行的（例如人工 `psql` 跑 `.sql`），此时清单只能由运维按实际执行记录登记——这种情况请回传给我，不要凭猜填写。

### 1.3 怎么拿到「超管令牌」

接口：`POST /api/v1/auth/sessions`，请求体 `{phone, password, totp_code?}`；返回含 `access_token` 与 `scope`。

**情形 A：已有超管账号**（最常见）

```bash
TOKEN=$(curl -sS -X POST "$BASE/api/v1/auth/sessions" \
  -H 'Content-Type: application/json' \
  -d '{"phone":"<超管手机号>","password":"<口令>","totp_code":"<6 位动态码>"}' | jq -r .access_token)
```

**情形 B：还没有任何超管账号**（首次部署）
调 `POST /api/v1/auth/registrations`（201 即成功）。**`bootstrap_token` 是请求体字段，不是请求头**；且必须声明 `tenant_id`，否则 `403`「首个管理员申请必须声明有效租户」：

```bash
curl -sS -X POST "$BASE/api/v1/auth/registrations" \
  -H 'Content-Type: application/json' \
  -d '{"phone":"<超管手机号>","password":"<≥10 位口令>","position":"<岗位>","full_name":"<姓名>",
       "tenant_id":"<租户标识>","bootstrap_token":"<部署注入的 WORKBENCH_BOOTSTRAP_TOKEN>"}'
```

- 该口令与 `WORKBENCH_BOOTSTRAP_TOKEN` 用**恒定时间比较**；不正确 → `403`「首个管理员需要正确的初始化口令」。**注意：这条校验只在「尚无任何已批准管理员」时生效**——本机实测：一旦已有超管，同样的请求（哪怕口令错、或没带 `tenant_id`）会返回 **201 且状态 `pending`**，即变成一条普通待审批申请。**可用这一点判断目标环境是否已有超管**（`403`＝还没有；`201 pending`＝已经有了）。
- 走通后账号**直接是 `super_admin` 且状态为已批准**（`reviewed_by=bootstrap`，**不需要他人审批**），同时写入两条审计（申请 + 批准）。
- 一旦**已有**已批准管理员，再调此接口就是**普通申请**（进入待审批，`tenant_id` 会被忽略、角色由审批人指定）——所以这个引导口令**只在首个超管**上有效。

**情形 C：返回的 `scope` 不是 `full`**
`WORKBENCH_REQUIRE_ADMIN_TOTP` 默认为 **真**。超管尚未绑定动态口令时，登录签发的是受限会话 `totp_enrollment`（有效期取 `min(session_ttl, totp_enrollment_ttl)`，默认 300 秒），用它访问 §3 接口会 `403`「账号需要先完成动态口令绑定」。此时按顺序做：

```bash
# ① 确认确实不是 full（是 totp_enrollment 才继续）
curl -sS -X POST "$BASE/api/v1/auth/sessions" -H 'Content-Type: application/json' \
  -d '{"phone":"<超管手机号>","password":"<口令>"}' | jq '{scope, expires_in}'

# ② 用受限令牌开始绑定（返回 secret / otpauth_uri，用验证器扫码）
curl -sS -X POST "$BASE/api/v1/auth/me/totp" -H "Authorization: Bearer $TOKEN" | jq

# ③ 用验证器当前 6 位码确认启用
curl -sS -X POST "$BASE/api/v1/auth/me/totp/confirmation" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"totp_code":"<6 位动态码>"}'

# ④ 重新登录（此时须带 totp_code），并确认 scope=full
```

- 受限会话**只允许**这 3 个接口（两个 TOTP 接口 + 登出/健康检查），其它接口一律 403（本机实测：受限令牌访问 `/api/v1/workforce/roster` → `403`「账号需要先完成动态口令绑定」）。
- **⚠️ 实操坑（本机实测踩到）**：第 ③ 步确认绑定用的那个动态码**已被消费**。若紧接着用**同一个码**登录，会得到 `401`「手机号或密码不正确」——**这不是账号或口令错了**，而是该步长的码已用过。等验证器翻到**下一个**码（≤30 秒）再登录即可（实测：用下一个步长的码 → `200`、`scope=full`）。服务端对「用了旧码」与「口令错」返回**同一个提示语**，这是刻意不泄露失败因素的安全设计。
- 非 `development` 环境**忽略** `X-Tenant-Id` / `X-User-Id` / `X-User-Role` 请求头，必须用真实令牌。
- 令牌有时效（`WORKBENCH_SESSION_TTL_SECONDS` 默认 900 秒），§3 请在拿到后尽快执行。

## 2. SQL 组（只读；逐条独立执行）

统一包装（把所有 `-c "SELECT ..."` 接在后面即可）：

```bash
psql "$WORKBENCH_PSQL_DSN" -v ON_ERROR_STOP=1 \
  -c "SET default_transaction_read_only = on" \
  -c "<下面的 SQL>"
```

### A. 数据库版本与 pgvector

```sql
SELECT version();
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
```

- **预期**：第二行返回一行（本机样例 `vector | 0.8.6`）。
- **判读**：**无返回行 = 迁移 001 的 `CREATE EXTENSION vector` 没成功**，必须先在目标库装 pgvector（官方 `postgres` 镜像不带；用 `pgvector/pgvector:pg16` 或等价发行版）。

### B. 迁移 022 是否落地（表 + 复合外键）

```sql
SELECT table_name FROM information_schema.tables
 WHERE table_schema = 'public'
   AND table_name IN ('workbench_job_roles','workbench_digital_employees')
 ORDER BY 1;
```

```sql
SELECT conname, pg_get_constraintdef(oid)
  FROM pg_constraint
 WHERE conrelid = 'workbench_digital_employees'::regclass AND contype = 'f';
```

- **预期**：第一条约 2 行；第二条 1 行，内容含 `FOREIGN KEY (tenant_id, role_key) REFERENCES workbench_job_roles(tenant_id, role_key)`。
- **判读**：缺表 = 迁移未跑到 022；有表但**没有复合外键** = 迁移被手工改过或用了旧脚本，必须停下来查。

### C. 存量「归一风险」盘点（**最重要**）

```sql
SELECT DISTINCT binding_type, binding_key, lower(btrim(binding_key)) AS normalized_key
  FROM workbench_knowledge_access_bindings
 WHERE binding_key <> lower(btrim(binding_key))
 ORDER BY 1, 2;
```

- **含义**：这些绑定键含大写或首尾空白，与目录标识口径不一致（D5）。**它们仍是「未纳管」**，且**下一次保存该绑定的范围时会被自动改写为归一键**（这是已确认的预期行为，不是故障）。
- **判读**：
  - **0 行** → 无风险，可直接推进。
  - **>0 行** → 先决定这些行是「人工纳管」还是「接受改写」，**再**让管理员在界面上动它们；避免在不知情的情况下被批量改写。
  - 本机样例（故意造的大小写不一致）返回：`role | Content-Operator | content-operator`。

### D. 规模快照

```sql
SELECT 'job_roles' AS item, count(*) AS n FROM workbench_job_roles
UNION ALL SELECT 'digital_employees', count(*) FROM workbench_digital_employees
UNION ALL SELECT 'role_bindings', count(*) FROM workbench_knowledge_access_bindings WHERE binding_type = 'role'
UNION ALL SELECT 'agent_bindings', count(*) FROM workbench_knowledge_access_bindings WHERE binding_type = 'agent'
UNION ALL SELECT 'tasks', count(*) FROM workbench_tasks
ORDER BY 1;
```

- **判读**：用于估算后续纳管工作量（本机样例：`agent_bindings 2 / digital_employees 2 / job_roles 2 / role_bindings 3 / tasks 1`）。

### E. 收敛条件①：仍被绑定、但不在目录里的**岗位**

```sql
SELECT DISTINCT b.binding_key
  FROM workbench_knowledge_access_bindings AS b
  LEFT JOIN workbench_job_roles AS r
    ON r.tenant_id = b.tenant_id AND r.role_key = b.binding_key
 WHERE b.binding_type = 'role' AND r.role_key IS NULL
 ORDER BY 1;
```

- **判读**：这就是设计文档 §11 Q2 的**「绑定侧未纳管为空」的岗位部分**。**为空 → 收敛条件① 满足**。
- 注意：大小写不一致的键（如 `Content-Operator`）会**出现在这里**（目录里是小写），这正是 §C 要一起看的原因。

### F. 收敛条件②：仍被绑定、但不在目录里的**数字员工**

```sql
SELECT DISTINCT b.binding_key
  FROM workbench_knowledge_access_bindings AS b
  LEFT JOIN workbench_digital_employees AS e
    ON e.tenant_id = b.tenant_id AND e.agent_key = b.binding_key
 WHERE b.binding_type = 'agent' AND e.agent_key IS NULL
 ORDER BY 1;
```

- **判读**：**为空 → 收敛条件② 满足**。
- 该查询**只看绑定来源**，不把任务里的 `employee_key` 算进来（那部分按已确认口径**不阻塞**阶段 2）。

### G. 已停用、但仍有绑定的标识（写路径会被闸门拦，属预期）

```sql
SELECT 'role' AS kind, b.binding_key
  FROM workbench_knowledge_access_bindings AS b
  JOIN workbench_job_roles AS r
    ON r.tenant_id = b.tenant_id AND r.role_key = b.binding_key
 WHERE b.binding_type = 'role' AND r.status = 'disabled'
UNION ALL
SELECT 'agent', b.binding_key
  FROM workbench_knowledge_access_bindings AS b
  JOIN workbench_digital_employees AS e
    ON e.tenant_id = b.tenant_id AND e.agent_key = b.binding_key
 WHERE b.binding_type = 'agent' AND e.status = 'disabled'
 ORDER BY 1, 2;
```

- **判读**：这些标识的范围**现在改不了**（会返回 `409`，需先启用）。**读/检索不受影响**，历史绑定照旧生效。属于需要你知情的现状，不一定是问题。

### H. 员工挂在「非启用」岗位下的影响面（收严口径）

```sql
SELECT e.tenant_id, e.agent_key, e.role_key, r.status AS role_status
  FROM workbench_digital_employees AS e
  LEFT JOIN workbench_job_roles AS r
    ON r.tenant_id = e.tenant_id AND r.role_key = e.role_key
 WHERE e.status = 'active' AND (r.role_key IS NULL OR r.status <> 'active')
 ORDER BY 1, 2;
```

- **含义**：2026-09-12 收严后，**员工可用 = 员工 `active` 且所属岗位 `active`**，所以这些员工的范围也改不了（`409`）。
- **判读**：`role_status = NULL` 表示**员工挂在一个已不存在的岗位上**（数据异常，需人工核查）；`disabled` 表示岗位被停用（按需启用即可）。

## 3. API 组（只读 GET）

```bash
curl -sS "$BASE/api/v1/workforce/candidates" -H "Authorization: Bearer $TOKEN" | jq
curl -sS "$BASE/api/v1/workforce/roster"    -H "Authorization: Bearer $TOKEN" | jq '.total'
```

- **`candidates.roles` 为空** ⇔ 与 §2E 的 SQL 结果一致（两种方式应互相印证）。
- **绑定侧未纳管为空** 的完整判据：`candidates.roles == []` **且** `roster` 中 `agent_knowledge_base_ids` 非空而该 `key` 不在员工目录里的项为空（等价于 §2F）。
- 两者不一致时以 **SQL 结果为准**（API 走的是同一份数据，但可能存在调用方租户不同、或权限 403 的情况）。
- **本机实测预期**（真实 HTTP 服务 + 真实令牌）：无数据时 `candidates` 返回 `{"roles": [], "agents": []}`、`roster` 返回 `total=0`；**非超管**访问 → `403`；**不带令牌** → `401`。若你在 staging 上看到 403，先按 §1.3 确认该令牌的 `scope` 是否为 `full`。

## 4. 可选：只读的既有脚本

以下脚本**已核对为只读**（`scripts/` 下无 `psycopg` 依赖；这些脚本只读环境变量与仓内文件，或只发 `GET`）：

```bash
python scripts/staging_preflight.py
python scripts/runtime_staging_preflight.py
python scripts/commercial_g0_preflight.py
python scripts/worker_preflight.py
python scripts/sso_preflight.py
```

跨租户只读探测（全部为 `GET`）——**注意：必须带 `--resource`，否则直接 `exit=2` 报「至少需要一个 --resource KIND:A_ID:B_ID」**：

```bash
python scripts/cross_tenant_probe.py --base-url "$BASE" \
  --token-a "$TOKEN_A" --token-b "$TOKEN_B" \
  --resource "task:$TASK_ID_A:$TASK_ID_B"
```

- `--resource` 可重复传多条；**可选 KIND 共 6 种**：`task`、`plan_proposal`、`content_task`、`run_metrics`、`orchestration_proposal`、`commercial_lifecycle`。
- `A_ID` 必须属于令牌 A 的租户、`B_ID` 属于令牌 B 的租户，**且两者不同**（相同会被拒绝）。**每类资源都要在两个租户里各有一个真实存在的 ID**，否则探测无法构成对照——这是最容易白跑的一点。
- **造对照组数据时的权限坑（本机实测踩到）**：`customer_admin` **不能创建任务**（`403`「当前岗位不能创建任务」）；可用角色为 `employee` / `department_lead` / `ceo` / `super_admin`。
- **本机实测结果**（真实 HTTP + 两个租户各一个真实 task）：`exit=0`，报告为
  `[pass] 隔离 task：A→A=200 B→B=200 A→B=404 B→A=404`——正向对照通过且双向都不是 200，隔离成立。

## 5. 明确排除（会写数据 / 改配置，另行授权后再跑）

| 命令 | 为什么不能放进只读轮次 |
| --- | --- |
| 直接启动应用服务（`uvicorn app.main:app`） | 启动即执行 `apply_migrations`，**会改库结构** |
| `scripts/migration_backup_drill.py` | 会创建恢复库并执行迁移 |
| `scripts/staging_concurrency_probe.py` | 三个场景都会发 `POST`（登录限流 / 任务幂等 / 审批原子性） |
| `scripts/secret_rotation_drill.py` | 会轮换密钥 |
| `scripts/desktop_update_drill.py` | 会触发更新演练 |
| 任何 `PUT/POST/PATCH/DELETE` 接口 | 写操作 |

## 6. 回传格式

把每条命令的输出原样贴回（DSN / 令牌用 `***` 替换），并附 4 条判定：

```
A pgvector:          有/无
B 迁移 022:          已落地 / 缺表 / 缺复合外键
C 归一风险行数:      0 / N（若是 N，贴出 normalized_key 列表）
E+F 绑定侧未纳管:    为空 / 非空（非空则贴出 key 列表）
G 停用但仍有绑定:    N 条（贴出列表）
H 员工挂非启用岗位:  N 条（贴出列表；注意 role_status=NULL 的行）
```

## 7. 本地验证样例输出（证明这些命令确实可执行）

2026-09-12 在本机一次性 `pgvector/pgvector:pg16`（端口 55432，跑完即删）+ 手工造数（1 启用岗位 / 1 停用岗位 / 2 员工 / 3 岗位绑定 / 2 员工绑定 / 1 任务）上的实测结果：

```
[A vector]  -> [('vector', '0.8.6')]
[B1 tables] -> [('workbench_digital_employees',), ('workbench_job_roles',)]
[B2 fk]     -> FOREIGN KEY (tenant_id, role_key) REFERENCES workbench_job_roles(tenant_id, role_key)
[C normalize risk] -> [('role', 'Content-Operator', 'content-operator')]
[D scale]   -> agent_bindings 2 / digital_employees 2 / job_roles 2 / role_bindings 3 / tasks 1
[E unmanaged bound roles]  -> [('Content-Operator',), ('legacy-role',)]
[F unmanaged bound agents] -> []
[G bound but disabled]     -> [('role', 'geo-operator')]
[H employees under non-active role] -> [('t-1', 'geo-analyst', 'geo-operator', 'disabled')]
```

只读包装实测：

```
只读会话 + SELECT        -> 正常返回结果（exit 0）
只读会话 + CREATE TABLE  -> ERROR: cannot execute CREATE TABLE in a read-only transaction（exit 1）
```

只读角色（§1.1 的建法）实测——以 `workbench_ro` 通过**真实 DSN**（`postgresql://workbench_ro:***@127.0.0.1:55432/workbench`）连接：

```
CREATE ROLE / GRANT CONNECT / GRANT pg_read_all_data -> 全部成功
属性核对 -> workbench_ro|f|f|t（非超管、不能建库、可登录）
9 条只读查询（pgvector / 目录两表 / 复合外键 / 知识绑定 / 归一风险 / 任务聚合 / 运行状态 / 索引）-> 全部 PASS
SET default_transaction_read_only = on 后再 SELECT -> PASS
CREATE TABLE（应被拒）-> PASS（InsufficientPrivilege）
关键性质：管理员新建一张表后，workbench_ro 无需再授权即可 SELECT -> 返回 0（证明覆盖未来迁移的新表）
```

超管令牌三种情形（§1.3）实测——FastAPI `TestClient`，`WORKBENCH_REQUIRE_ADMIN_TOTP=true`：

```
情形B  引导注册（带 bootstrap_token + tenant_id）         -> 201  role=super_admin  status=approved（另写 2 条审计）
情形B  边界：已有超管后再提交（口令错 / 缺 tenant_id）      -> 201  status=pending（不再 403，已变成普通待审批）
情形C  未绑 TOTP 登录（不带码）                            -> 200  scope=totp_enrollment  expires_in=300
情形C  受限令牌访问 /api/v1/workforce/roster               -> 403 「账号需要先完成动态口令绑定」
情形C  POST /auth/me/totp                                  -> 200  返回 secret / otpauth_uri / digest=SHA1 / digits=6 / period=30
情形C  POST /auth/me/totp/confirmation（当前步长码）        -> 200  {"status":"confirmed"}
情形A  用【已消费】的同一个码登录                           -> 401 「手机号或密码不正确」（该步长已用过）
情形A  用【下一个】步长的码登录                             -> 200  scope=full
情形A  full 令牌访问 /api/v1/workforce/roster               -> 200
情形A  已绑 TOTP 但不带码                                   -> 401 「需要动态验证码」
```

§3 API 组 与 §4 跨租户探测实测——本机**真实 HTTP 服务**（`uvicorn` 端口 18765，跑完即停）+ 两个真实租户：

```
租户A 引导注册 -> 201 ；租户B 申请 -> 201，由 A 审批（role=ceo, tenant=t-b）-> 200
§3  candidates（超管令牌）        -> 200  {"roles": [], "agents": []}
§3  roster（超管令牌）            -> 200  total=0
§3  非超管令牌 / 不带令牌          -> 403 / 401
§4  A 令牌读 B 租户任务 / B 令牌读 A 租户任务 -> 404 / 404
§4  cross_tenant_probe.py --resource "task:<A_ID>:<B_ID>" -> exit=0
    [pass] 隔离 task：A→A=200 B→B=200 A→B=404 B→A=404：正向对照通过且双向均返回 403/404，租户隔离成立
造数踩坑：customer_admin 建任务 -> 403「当前岗位不能创建任务」（换成 ceo 后 201）——对照组数据要用允许建任务的角色
```
