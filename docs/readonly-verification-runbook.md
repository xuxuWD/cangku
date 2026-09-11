# 只读核验清单 · 岗位/数字员工目录与阶段 2 闸门

> **用途**：在 **staging**（或经授权的真实库）上核验「数字员工设置 / 知识范围写路径闸门」的落地状态与**存量风险**。**全部命令只读**：不改数据、不改配置、不跑迁移。
> **执行方式**：AI **不连** staging/生产。由你在服务器上执行本清单，把输出回传后由我判读。
> **验证状态**：本清单的 **9 条 SQL、只读包装与判读标准已于 2026-09-12 在本机一次性真实 PostgreSQL 16 上逐条验证**（样例输出见 §7）。**本清单本身尚未在 staging 执行过**——staging 未就绪（阻塞项 1）。

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
| `TOKEN` | 超管令牌（只有 §3 需要）。获取方式见下 |
| 工具 | `psql`、`curl`、`jq` |

**令牌获取**（`POST /api/v1/auth/sessions`，请求体 `{phone, password, totp_code?}`）：

```bash
TOKEN=$(curl -sS -X POST "$BASE/api/v1/auth/sessions" \
  -H 'Content-Type: application/json' \
  -d '{"phone":"<超管手机号>","password":"<口令>","totp_code":"<6 位动态码>"}' | jq -r .access_token)
```

- **必须确认返回的 `scope` 是 `full`**。若超管尚未绑定动态口令，服务端签发的是受限会话 `totp_enrollment`，此时访问本清单的接口会返回 `403`「账号需要先完成动态口令绑定」——这时先完成 `POST /api/v1/auth/me/totp` + `.../totp/confirmation` 再回来。
- 非 `development` 环境**忽略** `X-Tenant-Id` / `X-User-Id` / `X-User-Role` 请求头，必须用真实令牌。

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

## 4. 可选：只读的既有脚本

以下脚本**已核对为只读**（`scripts/` 下无 `psycopg` 依赖；这些脚本只读环境变量与仓内文件，或只发 `GET`）：

```bash
python scripts/staging_preflight.py
python scripts/runtime_staging_preflight.py
python scripts/commercial_g0_preflight.py
python scripts/worker_preflight.py
python scripts/sso_preflight.py
```

跨租户只读探测（需要两个不同租户的令牌；全部为 `GET`）：

```bash
python scripts/cross_tenant_probe.py --base-url "$BASE" --token-a "$TOKEN_A" --token-b "$TOKEN_B"
```

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
