# Schema 级多租户改造专项方案

> 状态：**方案 · 待签字（2026-09-19）**。依据：用户 2026-09-19 裁决「ADR-0002 改为 **Schema 级隔离**」（推翻原"保留行级"提议）
> 与《开发设计规则》"地基不随手翻"（地基级变更必须专项评审后再动工）。
> **签字前不得写任何实现代码**；签字后按 §5 分期执行，每期独立验收。
> 关联：`adr.md` ADR-0002（方向与 7 个必答问题）、`permission-matrix.md`（权限口径）、`decision-log.md`。

## 1. 目标 / 范围 / 不做

**目标**：`public` 单 schema 行级隔离 → **每租户一套 schema**；租户上下文由后端强制注入并与 schema 路由**同一处解析**；租户间"无交叉访问可能"由 schema 边界 + 行级双保险共同保证。

**范围**：迁移执行器、连接/事务路由、建租户流程、全部 PG 仓储的连接获取方式、既有批量任务（保留清理 / 生命周期 / CRM / 导出读取器）、测试与演练。

**不做（本期明确排除）**：
- ❌ 双写期迁移（应用层同时写两份，成本远高于收益，且对账复杂）；
- ❌ 按租户独立连接池（池数量随租户线性增长）；
- ❌ 高敏感租户**独立数据库**（= 本模型的自然延伸，另开 ADR/专项）；
- ❌ 对象存储 / 向量库 / 缓存的租户级隔离（另一专项）。

## 2. 现状事实（实测，2026-09-19 测试库）

| 口径 | 数值 | 证据 |
| --- | --- | --- |
| 本项目**租户级表**（含 `tenant_id`，`workbench_` 前缀） | **55 张** | `information_schema` 实测（例：`workbench_accounts` / `workbench_tasks` / `workbench_conversations` / `workbench_crm_*` …） |
| 本项目**平台级表**（不含 `tenant_id`） | **6 张** | `workbench_tenants` / `workbench_schema_migrations` / `workbench_event_consumers` / `workbench_login_attempts` / `workbench_session_revocations` / `workbench_sso_states` |
| 迁移执行器 | 扁平形：`sorted(migrations/*.sql)` 逐个执行，记在 `workbench_schema_migrations(version)` | `app/migrations.py:17-45` |
| 连接获取 | 各 PG 仓储构造时接 `connection_or_pool`（单池/单连接），`_connection()` 各自实现 | `app/bootstrap.py` 及各 store |
| 既有隔离 | 行级：`tenant_id` + **复合外键**（如 `(tenant_id, conversation_id)`）在 DB 层拒跨租户写 | 迁移 001/023/027/037/040/042 等 |

> ⚠️ 测试库中还有**另一个项目**的表（`tenants` / `roles` / `approval_events` 等）：本方案只处理 `workbench_` 前缀的表，且**迁移不得触碰他表**。

## 3. 关键设计决策（逐项列选项 → 推荐 → **待签字**）

### D1 隔离模型：schema 为主 + 行级为"双保险"
- **保留** `tenant_id` 列与全部复合外键（不删列、不改约束）。
- **理由**：① 删列要动 55 表与 2600+ 用例，收益为零；② 两道防线（schema 边界 + 行级约束）对"无交叉访问"是更稳的证明；③ 平台侧联查/运维统计仍需要租户列。
- **签字**：`[ ] 采纳`  `[ ] 去掉 tenant_id 列（需追加数据层专项）`

### D2 表归属清单（55 张的拆分）
- **租户 schema**：51 张"行属某租户"的业务表（任务 / 运行 / 会话 / 消息 / 流 / 技能 / 知识治理 / 记忆 / 账号（`workbench_accounts`）/ CRM / 收件箱 / 内容 / 用量账本 / 保留策略 / 事件出箱 / 死信 / 评估 …）。
- **平台 schema（**例外，4 张从 55 里提出来**）**：
  | 表 | 为什么留在平台 |
  | --- | --- |
  | `workbench_audit_log` | 审计**永不删除**（既有裁决）；超管需**跨租户**查；放租户 schema 会随 `DROP SCHEMA` 被销毁 ⇒ 违规 |
  | `workbench_lifecycle_jobs` | 删除流程**自身**的记录（B6 建议保留；放租户 schema 会在删除当刻消失，断审计链） |
  | `workbench_export_packages` | 导出包 = 交付给客户的副本；删除后仍应可下载（B6 建议保留） |
  | `workbench_customer_admins`（若单列） | 平台侧的租户管理员名册（与 `workbench_tenants` 同类） |
- **附带 6 张平台级表**保持平台：见 §2。
- **签字**：`[ ] 采纳（4 张留平台）`  `[ ] 改为全 table 进租户 schema（审计与删除链断裂，需你确认接受）`

### D3 迁移策略：一次性切换 + "双链"模板化
- **形态**：新增**租户模板链** `migrations/tenant_template/*.sql`（把现有 44 个迁移中**属于租户表**的 DDL 抽取合并，保持既有幂等风格 `IF NOT EXISTS`），平台链沿用现有 `migrations/*.sql`。
  - **不改写 44 个历史文件**（它们仍是 `public` 阶段的历史事实与回滚依据）；
  - 今后任何结构变更：**属于租户表的必须同时更新租户模板链**（规则写入 CI 守护：两链的表集合必须等于 §2 的分类清单）。
- **台账**：平台 schema 新增 `workbench_tenant_schema_versions(tenant_id, version, applied_at)`（每个租户 schema 的模板版本），**不改** `workbench_schema_migrations` 的既有语义。
- **执行**：`apply_migrations(connection)` 增加 `scope`（`platform` / `tenant:<id>`），租户侧在执行前 `SET LOCAL search_path TO <schema>`。
- **首迁**：为现有全部租户建 schema → 应用模板 → **按表搬迁**（`INSERT ... SELECT`）→ **逐表校验**（行数 + 关键聚合 `SUM` 相等）→ 切路由 → 保留 `public` 旧表**只读冻结一个观察期**（不删）。
- **签字**：`[ ] 采纳（双链 + 一次性搬迁 + 观察期冻结）`  `[ ] 改用双写期`  `[ ] 其他`

### D4 新租户建 schema：注册即建（事务性原子）
- 在"创建租户"的**同一事务**内：`CREATE SCHEMA` + 应用租户模板 + 插入 `workbench_tenants` ⇒ **PostgreSQL DDL 可事务**，不会出现"有租户无 schema"的半状态。
- **幂等**：`ensure_tenant_schema(tenant_id)`（模板全 `IF NOT EXISTS`）供运维与自愈复用；失败补偿 = 重跑该函数（不删租户）。
- **签字**：`[ ] 采纳（注册即建 + 幂等 ensure）`  `[ ] 首次使用懒建`

### D5 连接与事务路由：统一封装 + `SET LOCAL search_path` + fail-closed
- 新增**唯一入口**（示意名 `tenant_connection(tenant_id)`，落点待实现期定）：事务内执行 `SET LOCAL search_path TO <tenant_schema>, platform`。
  - **为什么用 `SET LOCAL`**：事务结束自动失效 ⇒ 连接复用**不会串租户**（session 级 `SET` 存在池化串租户风险）；
  - **平台表可解析**：`platform` 作为第二解析路径（`workbench_tenants` 等仍可直接引用）；**禁止**同一事务出现两个租户 schema；
  - **fail-closed**：租户上下文存在但 schema 名解析/校验失败 ⇒ **拒绝执行**（绝不回落到 `public`）；无租户上下文（平台运维）⇒ 显式 `search_path = platform`。
- 改造面：所有 PG 仓储的 `_connection()` 统一走该入口（**一处定义、全仓收敛**）；注入点与租户解析同一处（ADR-0002 锁定要求）。
- **签字**：`[ ] 采纳（SET LOCAL + 统一入口 + 不回落到 public）`  `[ ] 其他`

### D6 schema 命名与注入防护（安全，逐行审核类）
- 命名**由服务端生成**：`t_<净化后的 tenant_id 前 40 字符>_<sha1(tenant_id)[:8]>`（`a-b` 与 `a_b` 不会被折叠成同名）。
- **白名单校验**：只允许 `^[a-z0-9_]{1,63}$`；**任何来自请求的字符串都不得直接进入 schema 名**（DDL 无法参数化 ⇒ 必须"生成 + 校验"两条都做）。
- **签字**：`[ ] 采纳`

### D7 既有批量任务与运维改造
| 任务 / 路径 | 改造 |
| --- | --- |
| 保留清理（`purge_expired_tenant_data`） | 已**逐租户**执行 ⇒ 每租户进入前设置 search_path；`runtime_events` 等查询随 schema 走 |
| 生命周期（`run_pending_jobs` / `execute_delete`） | 同上；**租户删除**最后一步可改为 `DROP SCHEMA CASCADE`（审计/生命周期/导出包在平台 schema ⇒ 天然不受影响） |
| CRM / 导出读取器 / 状态清理 | 逐租户遍历时设置 search_path（读取器已按 `reader(tenant_id, ...)` 形态设计，改造面小） |
| 巡检 / 备份 | 新增巡检脚本（逐 schema 表数 / 模板版本 / 行数）；备份策略改为"全库 + 逐 schema 校验" |
| 测试 | 真库用例改为"建临时租户 schema → 执行 → 清理"；**跨租户用例逐域至少一条**（A 的 schema 读不到 B） |
- **签字**：`[ ] 采纳`

### D8 回退方案与演练（对齐既有"迁移 + 回退演练"口径）
- **开关**：配置 `WORKBENCH_TENANT_ISOLATION=row|schema`（默认 `row`，**切换后才为 `schema`**）；回退 = 切回 `row` + 反向搬迁（schema → public）。
- **演练三段闭合**（在**副本库**上，禁止在生产演练）：`前滚 → 回退 → 再前滚`，留脚本与日志；对齐 044 迁移演练先例。
- **不可逆点**：`DROP SCHEMA`。⇒ ① 观察期内**不删** `public` 旧表；② 生产执行删除前先审计 + 备份。
- **签字**：`[ ] 采纳（含开关与三段演练）`

### D9 性能影响与测量口径
| 项 | 预期 | 必须实测 |
| --- | --- | --- |
| 权限校验 | `SET LOCAL` 每事务 1 条语句（微秒级） | 仍须满足"P95 ≤ 5ms"（`permission-matrix.md` §6 口径） |
| 检索 | 无额外跳数 | 仍 ≤ 2s（含上游） |
| 迁移/建租户 | 现库近空 ⇒ 秒级 | **真实规模未测**（大租户逐表搬迁耗时与锁影响） |
| schema 数量增长 | — | 连接与巡检耗时随 schema 数增长的曲线未测 |
- **签字**：`[ ] 认可该口径（未测项按 §6 登记为未验证）`

## 4. 与第一期（ADR-0005）的排期关系（**必须一起拍**）

第一期并入项有 3 项要**写新表/新写入路径**（岗位模板、共享载体、角色/技能配置）。若先做这些、后做 Schema 改造 ⇒ 同一批要写两次。
**建议**：① 本方案**先签字**（把"新表属于哪条链"钉死）；② 前端第 1 轮"应用壳"**并行开工**（不触碰数据层）；③ 涉及写库的新功能**待 S2 路由改造完成**后落地。
**签字**：`[ ] 采纳该排期`  `[ ] 先集中做完 Schema 改造再开第一期功能`  `[ ] 其他`

## 5. 分期与每期验收（签字后执行）

| 期 | 内容 | 验收（可验证） |
| --- | --- | --- |
| **S0 准备（不写实现）** | 55+6 表分类清单落地为文件；租户模板链抽取；巡检/校验脚本 | 两链表集合与 §2 实测完全一致；脚本对空库可跑通 |
| **S1 迁移执行器** | `scope` 化 + `workbench_tenant_schema_versions`；建 `ensure_tenant_schema` | 测试库建 3 个租户 schema，逐表存在；重跑幂等 |
| **S2 路由改造** | `tenant_connection` 统一入口 + fail-closed + 各仓储收敛 | **跨租户用例逐域至少一条**（含 A/B 双向）；去掉 SET ⇒ **必红**（反假） |
| **S3 搬迁** | 现有租户数据搬迁 + 逐表校验 + 观察期冻结 | 55 表行数与关键聚合**搬迁前后相等**（逐表留痕） |
| **S4 回退演练** | 副本库三段闭合 | 前滚/回退/再前滚 都成功，且回退后旧用例全绿 |
| **S5 切换** | 测试 → 预发 → 生产（按七步更新） | 每环境按真实流程 + 歪路验证；生产切换前打 tag |

### S0 完成记录（2026-09-19，已交付）

| 产物 | 路径 | 实测 |
| --- | --- | --- |
| 表分类清单（权威、机器可读） | `migrations/tenant_template/classification.json` | tenant_schema 51 / platform_tenant_scoped 4 / platform_core 6，与实测库逐字一致 |
| 租户模板链（生成物） | `migrations/tenant_template/0001_tenant_baseline.sql` | **1247 行**：51 表 / 53 索引 / 98 约束 / **2 序列**（含 `OWNED BY` 与 `nextval` 默认值）/ **4 处 `${PLATFORM_SCHEMA}` 外键改写** |
| 工具链 | `scripts/tenant_schema.py`（`build-template` / `verify` / `inventory`）+ `migrations/tenant_template/README.md` | 纯标准库 + psycopg；可重复执行（产物逐字节稳定） |

**S0 验收（逐条）**：
1. ✅ 分类与实测一致（脚本 `[1/3]` 校验：含 `tenant_id` 55 张 = A 51 + B 4；不含 6 张 = C）；
2. ✅ 模板覆盖 == 分类清单 A 组（脚本 `[2/3]`）；
3. ✅ **空库跑通**：临时 schema 内应用模板 208 条语句成功，且与 `public` 的 A 组表在**表 / 列（含 `column_default`）/ 索引 / 约束**上集合完全一致，临时 schema 已清理（`verify --apply` 退出码 0）。

**S0 期发现并已修的保真缺口（真实缺陷，不是纸面）**：首版模板**漏掉自增序列**——`workbench_audit_events` / `workbench_knowledge_access_audits` 的 `id bigint` 无 `nextval` 默认值 ⇒ 新租户 schema 下**不带 id 的插入会失败**。已补：纳入 A 组表自有的 `CREATE SEQUENCE` + `OWNED BY` + `SET DEFAULT nextval`（去 `public.` 限定，靠 search_path 落在租户 schema 内），并**把 `column_default` 纳入结构比对**（该缺口的检测判据由此具备牙齿；反假已证：注释掉序列语句 ⇒ 校验变红并指名到列，恢复 ⇒ 变绿）。

**S0 尚未覆盖（承接 §6，勿读成已验）**：触发器/规则、函数/视图/自定义类型、扩展对象本身、`COMMENT`、`GRANT`/所有者/表空间、RLS、分区与继承；序列自身属性（START/INCREMENT/CACHE）未跨 schema 比对；**未做真实"不带 id 的 INSERT"实测**（按"不写业务数据"约束留给 S1）。

## 6. 风险登记与未验证（不得读成已验）

- **资源竞争**：Schema 改造与第一期功能并行，单人主导下有排队风险（§4 已给排期建议）。
- **测试面广**：2600+ 用例中凡以"直连 public、按行级建数据"为前提的真库用例都要跟着改（工作量集中在 S2/S3）。
- **未验证**：① 大租户搬迁耗时/锁影响（本机近空库）；② schema 数增长后的巡检与迁移耗时曲线；③ 观察期冻结 `public` 期间的**双写风险**（若有人绕过路由直写 public 旧表 ⇒ 需靠"路由 fail-closed + 巡检比对"发现，**尚未演练**）；④ 高敏感独立库、对象存储/向量/缓存不在本方案。
- **不承诺**：本方案不含任何工期承诺；S0–S5 每期完成才进入下一期。

## 7. 待签字清单（一次勾完即可开工 S0）

1. D1 双保险（保留 `tenant_id` + 复合外键）`[ ]`
2. D2 表归属（4 张留平台 schema）`[ ]`
3. D3 双链模板 + 一次性搬迁 + 观察期 `[ ]`
4. D4 注册即建（事务性原子）`[ ]`
5. D5 `SET LOCAL` + 统一入口 + fail-closed `[ ]`
6. D6 schema 命名与注入防护 `[ ]`
7. D7 批量任务与运维改造面 `[ ]`
8. D8 回退开关 + 三段演练 `[ ]`
9. D9 性能测量口径 `[ ]`
10. §4 排期关系 `[ ]`

签字人：____ 日期：____