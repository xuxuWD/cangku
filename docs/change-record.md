# 变更记录（影响地基的变更）

> **性质**：本文件是宪法 1.4「**变更留痕**：影响地基的变更必须写进变更记录（**时间、原因、影响面、回退方式**）」所要求的**记录载体**。**只登记影响地基的变更**（技术栈、目录结构、**数据模型**、权限模型、支付逻辑）；日常功能变更不在此登记。
> **建立日期**：2026-09-13（第四轮独立复核 P6 指出：本仓库此前**没有独立变更记录载体**，对既有表的结构变更只写在规格正文里）。
> **维护规则**：① 地基变更**先登记、后动手**；② 登记项在落地后须补「执行日期 / 执行人 / 演练结果」；③ 回退方式必须写清，且**未经确认不得执行回滚**。

---

## 记录

### 2026-09-13 · ⑥ 失败的零残留语义：字面「同一事务」→ **显式补偿回滚**（段二-4）

| 项 | 内容 |
| --- | --- |
| **时间** | 2026-09-13（**用户裁决**，随段二-4 缺口收口登记） |
| **变更** | §4.1.3「⑥ 落库失败（`503`）与本行属**同一事务**」落地为「**显式补偿回滚**」：按创建顺序**逆序撤销**（运行记录 → 进程内运行状态 → 承载任务）；幂等行本就不写、消息在 ⑥ 成功后才追加 ⇒ 二者天然为 0。 |
| **原因** | 四类对象（承载任务 / 运行记录 / 会话消息 / 幂等行）分属**四个各自持有连接的独立仓储**，**不存在可挂靠的 Unit-of-Work / 共享连接层**；要真做 DB 事务需大幅改造四个仓储的连接管理（超出本缺口范围）。 |
| **影响面** | ① **可观测结果与"同一事务"一致** —— 请求结束后四类对象均查不到，已由用例断言（`test_persist_failure_503_leaves_zero_residue_and_replays_gates`）；② **非字面 DB 事务** ⇒ 中间态在补偿完成前**短暂可见**（同进程内）；③ 为支持补偿，**四个仓储各新增** `delete` / `remove` / `set_pending_approval`（**纯新增，既有方法语义未改**，`git diff --numstat` 删除行数全为 0）；④ **Postgres 分支的补偿路径未经真实库验证**（登记为未验证）。 |
| **回退方式** | 若要回到字面事务，须引入 Unit-of-Work（共享连接 / 事务上下文）并改造四个仓储 —— **属结构性改动，回退前必须重新评审**。 |
| **依据** | 规格 [`2026-09-12-dsh-integration-design.md`](superpowers/specs/2026-09-12-dsh-integration-design.md) §4.1.3（2026-09-13 裁决注）；实现 `app/conversation/execution.py` 的 `_compensate` |

### 2026-09-13 · 执行工作卷落点：宿主 bind → **容器内 tmpfs**（段二-3）

| 项 | 内容 |
| --- | --- |
| **时间** | 2026-09-13（**用户裁决**，随段二-3 实现登记） |
| **变更** | 容器执行的**工作卷落点**由「宿主目录 bind 到 `/workspace`」改为「**容器内 tmpfs**」（挂载选项 `rw,noexec,nosuid,nodev`），容器销毁即随之消失。宿主侧 `WORKBENCH_EXEC_WORKSPACE_ROOT` **保留**，语义收窄为「③ 路径闸门的宿主锚点」。 |
| **原因** | **Docker 不支持在 bind / volume 上设置 `nosuid,nodev,noexec`**（实测 `docker run -v vol:/w:noexec,nosuid,nodev` → `invalid mode: noexec,nosuid,nodev`）。而规格 §3.3 的三条要求必须**同时**满足：① 挂载选项 `nosuid,nodev,noexec`；② **工作卷与容器根不同设备**；③ 生成即空 + 运行结束销毁。**tmpfs 是同时满足三者的唯一原生手段。** |
| **影响面** | ① 工作卷**不再落在宿主目录** ⇒ 宿主侧不能直接查看/留存执行产物（**产物导出**走 `artifact.export`，不受影响）；② §3.3「与容器根不同设备」由 tmpfs 天然满足；③ `WORKBENCH_EXEC_WORKSPACE_ROOT` 语义收窄，**不再**是 bind 源；④ 宿主残留风险**下降**（容器销毁即清，⑥ 孤儿治理只需管容器）。 |
| **回退方式** | 改回宿主 bind 需**同时放弃** `noexec,nosuid,nodev` 三项（或改用其它隔离手段）⇒ **属安全性下降**，**回退前必须重新评审**，不得静默切换。 |
| **依据** | 规格 [`2026-09-12-dsh-integration-design.md`](superpowers/specs/2026-09-12-dsh-integration-design.md) §3.3 文件系统 / 工作目录两行（2026-09-13 裁决注）；段二-3 实现 `app/tool_execution/executor.py` |

### 2026-09-13 · 执行容器 tmpfs 追加 `mode=1777`（段 F 复跑发现）

| 项 | 内容 |
| --- | --- |
| **时间** | 2026-09-13（随段 F 真实 turn 复跑登记） |
| **变更** | 执行容器的**工作卷 tmpfs** 挂载选项追加 **`mode=1777`**（非 root 进程需可写）。 |
| **原因** | 容器以**非 root（65534）**运行，而 tmpfs 默认属主为 root ⇒ 工作卷对执行进程**不可写**。段 F 的真实 turn 复跑暴露该偏差。 |
| **影响面** | 仅影响**容器内工作卷的权限位**；**不改变** §3.3 的其余加固项，**不改变**「生成即空、随容器销毁」语义（容器销毁即清，且 `noexec,nosuid,nodev` 三项仍在）。 |
| **回退方式** | 收紧 `mode` 前必须先确认非 root 执行仍可写工作卷，否则执行会失败；**不得**为收紧权限而把容器改回 root 运行（那是更大的安全性下降）。 |
| **依据** | 段 F 实现 `app/tool_execution/executor.py`；规格 [`2026-09-12-dsh-integration-design.md`](superpowers/specs/2026-09-12-dsh-integration-design.md) §3.3 文件系统行 |

### 2026-09-13 · 对既有表 `workbench_run_records` 增补唯一约束（随迁移 `027`）

| 项 | 内容 |
| --- | --- |
| **时间** | 2026-09-13（设计登记）→ **同日已落地并完成真库演练**（见下「执行与演练」行） |
| **变更** | `ALTER TABLE workbench_run_records ADD CONSTRAINT workbench_run_records_run_tenant_unique UNIQUE (run_id, tenant_id)`；**可重复执行写法（已更正）**：**DO 块按 `pg_constraint` 判定后增补**——原写「`DROP CONSTRAINT IF EXISTS …` 后 `ADD CONSTRAINT …`」在真库演练中**证明不可用**（两张新表持有指向该约束的复合外键，重跑时 DROP 报 *other objects depend on it*） |
| **执行与演练** | **执行日期**：2026-09-13；**执行人**：AI 助手（用户裁决「过闸，落 027」后执行）；**落地物**：`migrations/027_dsh_tool_execution.sql`。**真实库演练**（独立 `pgvector/pgvector:0.8.0-pg16@sha256:a132765…` 容器，**非生产**）：① 27 个迁移**整组连跑 3 遍全部 OK**（可重复执行）；② **回退演练**：`DROP` 两表 + `DROP` 约束 → 对象数归 0 → **重跑 `027` 前滚成功**（31 列；`run_tenant_unique` + 两张表的 `pkey`/`fkey`/4 个 `CHECK` 全部就位）；③ 回归 **1445 passed**、`compileall` exit 0。**演练发现并修正 1 处实现缺陷**（即本行「变更」列所记写法问题），**未使用 `CASCADE`**；规格 §4.1.2 / §4.1.5 已回改 |
| **原因** | 迁移 `027` 的两张新表需用**复合外键 `(tenant_id, run_id)`** 把租户隔离「写进约束」（与 `migrations/023` 同思路）；而 `migrations/013` 只建了 `PRIMARY KEY (run_id)`，**父表侧缺唯一约束** → 复合外键无法成立；若退化为单列外键则**丢失租户维度**（跨租户可达） |
| **影响面** | ① 仅**新增一个唯一约束**，不改列、不改既有查询语义；② `run_id` 本就是主键 → 既有数据在 `(run_id, tenant_id)` 上必然唯一，**无需回填**；③ 同文件内**必须先执行本条、再建 `workbench_tool_actions` / `workbench_execution_idempotency`**（否则 PostgreSQL 建外键时报 *there is no unique constraint matching given keys for referenced table*） |
| **回退方式** | 先停真实执行（`WORKBENCH_AGENT_RUNTIME_BACKEND=mock`）→ `DROP TABLE workbench_tool_actions` → `DROP TABLE workbench_execution_idempotency` → `DROP CONSTRAINT workbench_run_records_run_tenant_unique` → 删除 `workbench_schema_migrations` 中 `027` 的记账行 |
| **评审状态** | **未通过**：随段二规格 §4.1 一并送审。**第四轮**独立复核判「不予放行」（阻断项 R4-1 即本条的**语句顺序**）→ 修订 → **第五/第六轮**独立复核仍判「不予放行」（第六轮为 R6-1/R6-2/R6-3，见评审记录 §12）→ **已按 J7 = 丙案 + J8/J9 定死完成第六轮修订**（规格 §9.5）→ **第七轮定点复核未通过**（R6-1/R6-2 表面闭合等）→ 已按 **P1–P11** 打补丁（规格 §9.6）→ **补丁确认未通过 → Q1–Q3 → 再次确认「部分真闭合」→ R1–R3 → 最后一次补丁确认：R1/R2/R3 全部真闭合** → **规格已评审通过（附记录）· 2026-09-13** |
| **依据** | 规格 [`2026-09-12-dsh-integration-design.md`](superpowers/specs/2026-09-12-dsh-integration-design.md) §4.1.2 / §4.1.5；评审记录 [`dsh-integration-review-record.md`](dsh-integration-review-record.md) §9 |

> **口径**：本条为**设计登记**，**不代表已执行**；`migrations/027_*.sql` 落地前不得视为生效。**〔2026-09-13 更新：已按第 1 条的「执行与演练」行补齐——执行日期、执行人、真实库升级与回退演练结果均已登记；`027` 已落地生效。〕**

### 2026-09-13 · 新增表 `workbench_tool_actions`（随迁移 `027`）

> **补登说明**：第五轮独立复核阻断项 **R5-5** 指出——本文件建立时**只登记了对既有表的约束增补**，而 `027` 实际引入**三项**数据模型变更，两张**新表**未登记（新表同为「数据模型变更」，宪法 1.4 要求留痕）。本条与下条即为此补登，**内容与规格 §4.1.1 / §4.1.3 同源，未新增任何设计**。

| 项 | 内容 |
| --- | --- |
| **时间** | 2026-09-13（设计登记）→ **同日已落地并完成真库演练**（执行与演练记录见第 1 条） |
| **变更** | 新建表 `workbench_tool_actions`（待批动作 = 授权项，同行同表；`PRIMARY KEY (tenant_id, action_id)`；含 `approval_id` / `args_digest` / **`args_json`** / **`body_ciphertext` + `body_expires_at`**（**J7 = 丙案的受控正文密文列**）/ `plan_digest` / `risk_level` / `status` / 决议四列；**2 个 CHECK**——`decision_check`「决议字段全有或全无」与 `body_check`「密文与到期时刻同有同无」；2 个部分唯一索引 + 1 个普通索引）。完整 DDL 见规格 §4.1.1 |
| **原因** | 段一「逐项授权」只有**单一摘要列**（`026`），无法表达逐项；③ 需要「**待批动作与授权项是同一行的两个状态**」以从结构上消除「批准 A、执行 B」；`026` 为运行级快照，**不得单独放行工具执行**（裁决 R7） |
| **影响面** | ① **纯新增表**，不改既有表、不改既有查询；② **必须排在 §4.1.2 的 `ALTER` 之后**（复合外键依赖父表唯一约束）；③ 与 `workbench_execution_idempotency` 有先后无依赖（各自引用既有父表）；④ **正文边界（J7 = 丙案）**：`args_json` **只落控制参数**；`body` 原文**默认不落库**，**唯一例外** = 本表 **`body_ciphertext`**（**AEAD 密文、密钥不落库、TTL 与审批同寿、审批落定即清、不导出、审计不落**，规格 §3.4 / §4.1.5） |
| **回退方式** | 先停真实执行（`WORKBENCH_AGENT_RUNTIME_BACKEND=mock`）→ `DROP TABLE workbench_tool_actions` → 再按上一条回退（幂等表 → 约束 → 记账行） |
| **评审状态** | **未通过**：随段二规格 §4.1 一并送审；第四轮判「不予放行」，**第五轮**再判「不予放行」（阻断项 R5-1 `args_json` 落点缺失、R5-5 本条漏登）→ 修订 → **第六轮**判「不予放行」（R6-1/R6-2/R6-3）→ **已按 J7 = 丙案 + J8/J9 定死完成第六轮修订**（本条补 `body_ciphertext` / `body_expires_at` + `body_check`）→ **第七轮定点复核未通过** → 已按 **P1–P11** 打补丁（补充 `BodyCipher` 组件落点、密钥与清理周期配置、加解密失败语义、密钥轮换窗口、`expired` 执行方；规格 §9.6）→ **补丁确认未通过 → Q1–Q3 → R1–R3** → **规格已评审通过（附记录）· 2026-09-13** |
| **依据** | 规格 [`2026-09-12-dsh-integration-design.md`](superpowers/specs/2026-09-12-dsh-integration-design.md) §4.1.1 / §4.1.5；评审记录 §10 |

### 2026-09-13 · 新增表 `workbench_execution_idempotency`（随迁移 `027`）

| 项 | 内容 |
| --- | --- |
| **时间** | 2026-09-13（设计登记）→ **同日已落地并完成真库演练**（执行与演练记录见第 1 条） |
| **变更** | 新建表 `workbench_execution_idempotency`（执行幂等；`PRIMARY KEY (tenant_id, actor_id, conversation_id, idempotency_key)`；含 `message_id`（**可空**）、`run_id`（可空）、**`approval_id`**（J-4：重建 `202` 响应体所需）、`outcome`（4 值 CHECK）、**`http_status`**（R5-2 新增）、**`result_check`**（J-5：`outcome` ↔ `http_status` 合法组合约束）；3 个复合外键 + 1 个部分索引）。完整 DDL 见规格 §4.1.3 |
| **原因** | 执行幂等键已定为请求头 `Idempotency-Key`（裁决 R2），需**持久化首次结果**以保证重放「不新增消息 / 不新增承载任务 / 不新增运行 / 不二次执行」；`message_id` 由 `append_message` 每次新建，**不能**承担幂等键 |
| **影响面** | ① **纯新增表**；② 三外键分别引用 `workbench_conversations` / `workbench_conversation_messages`（`migrations/023` 复合主键）与 `workbench_run_records`（**依赖 §4.1.2 的 `ALTER`**）；③ `message_id` / `run_id` 可空 → 被拒与首次失败场景亦能写行；④ **`body` 原文不落本表**（同 §4.1.1 边界） |
| **回退方式** | 先停真实执行 → `DROP TABLE workbench_execution_idempotency` → `DROP TABLE workbench_tool_actions` → `DROP CONSTRAINT workbench_run_records_run_tenant_unique` → 删除记账行 |
| **评审状态** | **未通过**：第五轮独立复核阻断项 **R5-2**（缺 `http_status` → 「响应重建」不可兑现）；**第六轮**判「不予放行」（**R6-3** ① 步结果码冲突牵动本表 `http_status` 的唯一性）→ **已修订**（补 **`approval_id`** + **`result_check`** + 「⑥ 失败不写本表」例外）→ **第七轮定点复核未通过**（用例 32② 不可判定等）→ 已按 **P7/P8** 打补丁（用例 32② 改可执行口径 + 双向引用；规格 §9.6）→ **再次补丁确认「部分真闭合」→ R1/R2/R3 修订 → 最后一次补丁确认：全部真闭合** → **规格已评审通过（附记录）· 2026-09-13** |
| **依据** | 规格 §4.1.3 / §4.1.5；契约「工具执行（P2a 段二）」变更点 5 |

> **口径（对以上三条同样适用）**：均为**设计登记**，**不代表已执行**；`migrations/027_*.sql` 落地前不得视为生效。落地时须补：执行日期、执行人、真实库上的升级与回退演练结果。

### 2026-09-13 · 后端依赖基线锁定（新增 `requirements.lock`；`Dockerfile` 改为消费它）

> **补登说明（自我登记）**：本条属**事后补登**。按本文件口径应"**先登记、后动手**"；本次为"**先动手、后补登**"——我最初判断"补一个锁文件"**不属**地基变更（未动技术栈/目录结构/数据模型/权限/支付），故未登记；但**改动 `Dockerfile` 之后**，它已构成**"装哪些依赖版本"的基线变更**（可回退、且影响交付物可复现性），**应留痕**，故补登。**该判断偏差由我承担，供后续复核。**

| 项 | 内容 |
| --- | --- |
| **时间** | 2026-09-13（**已实施**：锁文件已生成入库、`Dockerfile` 已改、构建与验证均已完成） |
| **变更** | ① **新增** [`requirements.lock`](../requirements.lock)（`pip-compile --generate-hashes` 生成：**49 个包全部 `==` 锁定**、**835 条 `--hash=sha256:`**、74,690 字节）；② **`Dockerfile` 依赖安装两行改写**：`COPY requirements.txt` + `pip install -r requirements.txt` → **`COPY requirements.lock` + `pip install --no-cache-dir --require-hashes -r requirements.lock`**。**`requirements.txt` 保留未改**（不再被构建使用） |
| **原因** | 后端原只有**范围约束**（`>=x,<y`）且**无任何锁定文件** ⇒ 同一份清单在不同时间装出不同版本，**§3 第 0 层的"可离线复现构建"对后端不成立**（缺口①，见自主可控方案 §11.2） |
| **影响面** | ① **改变"装哪些版本"的基线** —— 锁定值 = 2026-09-13 时各范围约束内的**最新版**（如 `cryptography==48.0.1`、`fastapi==0.141.1`、`pydantic==2.13.5`、`celery==5.6.3`）；② 构建变为 **fail-closed**（哈希不符即失败）；③ **不动**：应用代码、`migrations/`、运行时配置、权限模型、数据模型；④ 镜像内**不再包含** `requirements.txt` |
| **回退方式** | ① 把 `Dockerfile` 那两行还原为 `COPY requirements.txt` + `pip install -r requirements.txt`；② 删除 `requirements.lock`；③ 重新构建镜像。**均为文件级操作、无数据迁移、可即时回退** |
| **验证（已补完）** | ✅ 构建通过；✅ 镜像内 **49/49 版本与锁文件逐条一致**（`MISSING=0` / `VERSION_MISMATCH=0`）；✅ import 冒烟全 OK；✅ **反假测试**：改坏全部 835 条哈希 ⇒ `--require-hashes` **失败（EXIT=1）**，原文件 ⇒ **EXIT=0**；✅ `--network none` 纯离线安装通过；✅ **测试套件（按 CI 原命令 `python -m pytest -o addopts=""`，锁定依赖）⇒ `1434 passed, 0 failed`（29.6s）+ `compileall` 通过 ⇒ 与文档基线"后端 1434"逐数一致**；✅ **仓库未被测试改动**（`git status` 仅本轮变更；测试写入的 `tmp/relative.db` 落在只读挂载之外） |
| **✅ 先前标注的未验证项已闭合** | ~~未跑项目测试套件~~ → **已跑（2026-09-13，选项 F）：`1434 passed, 0 failed` + `compileall` 通过，与文档基线逐数一致**。**仍存在的一般性边界**：测试跑在**容器**（`python:3.12-slim`）而非 CI 的 `ubuntu-latest`；**未跑前端/桌面三个 job**（本变更只影响后端依赖） |
| **依据** | 自主可控方案 §11.2 缺口① / §11.5 / §11.6 / §11.7；门禁 §B16 |

### 2026-09-13 · 构建输入钉死（基础镜像改 digest；三端声明 Node 版本）

> **补登说明（自我登记）**：与上条同口径，本条亦为**事后补登**（先动手、后补登）。判断依据：它改变**交付物构建输入的不可变性**，属**可回退、且影响交付物可复现性**的变更，应留痕。

| 项 | 内容 |
| --- | --- |
| **时间** | 2026-09-13（**已实施并验证**） |
| **变更** | ① [`Dockerfile`](../Dockerfile)：`FROM python:3.12-slim` → **`FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea`**；② [`admin-web/package.json`](../admin-web/package.json)、[`companion-pwa/package.json`](../companion-pwa/package.json)、[`desktop/package.json`](../desktop/package.json) 各新增 **`"engines": {"node": ">=22"}`** |
| **原因** | 缺口③（自主可控方案 §11.2）：基础镜像按 **tag** 引用 ⇒ tag 可变、**归档与生产可能不是同一镜像**；且三端**未声明 Node 版本**（CI 靠 `node-version: "22"` 隐式约束） |
| **影响面** | ① 基础镜像**不再随 tag 漂移**（升级须显式改 digest）；② 前端/桌面**显式要求 Node ≥22**（与 CI 注释「vite 8 / vitest 5 要求 Node 22+」一致；`engine-strict` 未开启 ⇒ `npm ci` 不因之失败）；③ **不动**：应用代码、依赖版本、`requirements.lock`、`migrations/`、运行时配置、权限与数据模型 |
| **回退方式** | ① `Dockerfile` 还原为 `FROM python:3.12-slim`；② 删除三处 `engines` 字段。**均为文件级操作、可即时回退** |
| **验证** | ✅ 重建成功（构建日志显示按 `@sha256:78387bc3…` 解析）；✅ **反假测试**：`FROM …@sha256:0000…` ⇒ **构建失败（exit=1，`not found`）** ⇒ digest 钉死**承重**；✅ 三份 `package.json` 仍为**合法 JSON** 且 `engines.node=">=22"`；✅ 镜像内依赖仍与锁文件 **49/49 一致** |
| **未验证 / 未做** | **未跑前端/桌面三个 CI job**（本变更只加声明、未改依赖，风险低但**未实测**）；**`docker-compose.yml` 的基础设施镜像仍按 tag**（未改）；**MinIO 镜像已不可获取**（独立阻塞项，见自主可控方案 §11.8，**不属本变更**） |
| **依据** | 自主可控方案 §11.2 缺口③ / §11.8 / §11.9；门禁 §B16 |

### 2026-09-13 · 基础设施镜像换源（MinIO：Docker Hub → quay.io，并按 digest 钉死）

> **补登说明（自我登记）**：与上两条同口径，本条亦为**事后补登**（先动手、后补登）。判断依据：它改变**运行环境依赖的来源与不可变性**，属**可回退、且影响交付物可复现性**的变更，应留痕。

| 项 | 内容 |
| --- | --- |
| **时间** | 2026-09-13（**已实施并验证**） |
| **变更** | [`docker-compose.yml`](../docker-compose.yml) `minio` 服务：`image: minio/minio:RELEASE.2025-04-22T22-12-26Z` → **`image: quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z@sha256:a1ea29fa28355559ef137d71fc570e508a214ec84ff8083e39bc5428980b015e`**（**tag + digest 并存**） |
| **原因** | **上游源失效**（2026-09-13 实测）：`minio/minio` 在 Docker Hub 的**钉死 tag 与 `latest` 均返回 `pull access denied`** ⇒ 新环境按原 compose **起不来 MinIO**，且 §3 第 0 层拿不到归档输入（详见自主可控方案 §11.8） |
| **影响面** | ① **只换源与钉死方式，版本不变**（quay 上为**同一 release**，Created `2025-04-22T22:35:01Z`）；② 镜像引用变为**不可变**（digest 生效）；③ **不动**：其它服务、端口、卷、环境变量、应用代码、依赖版本、`migrations/` |
| **回退方式** | ⚠️ **本条已被同日的「对象存储由 MinIO 换成 SeaweedFS」条目取代（见下方两条）** —— 对象存储**当前为 SeaweedFS**，如需回退请参照那一条。~~原回退方式：还原为 `image: minio/minio:RELEASE.2025-04-22T22-12-26Z`~~（且回退后在本机/新环境将拉不到该镜像）。**文件级操作、无数据迁移** |
| **验证** | ✅ `docker compose -p workbench -f docker-compose.yml config --images` ⇒ MinIO 行解析为**新的 quay+digest 引用**；✅ `docker run --rm <ref> --version` ⇒ `RELEASE.2025-04-22T22-12-26Z (commit-id=0d7408fc…)`；✅ **临时容器起服务**（宿主 `19000`、`--tmpfs /data`）⇒ `/minio/health/live` **返回 `200`**，随后**已删除该临时容器**；✅ 全程**未占用**被其它项目占用的 `9000/9001` |
| **未做 / 未验证** | **`docker-compose.yml` 另两个镜像仍按 tag**（`pgvector/pgvector:0.8.0-pg16`、`redis:7.4-alpine`）—— 本轮只批准 MinIO 换源；**未做 `docker save` 归档**（无目的地，P0-2 挂起）；**未在真实 compose 全栈下验证**（本机 `9000/9001` 被占） |
| **连带发现（非本变更引入）** | MinIO 镜像自述 **`GNU AGPLv3`**，而项目许可清单 [`poc-license-checklist.md`](superpowers/poc-license-checklist.md) **从未覆盖基础设施组件** ⇒ **需合规判断**（见自主可控方案 §11.8 末），**本条只登记事实、未改许可结论** |
| **依据** | 自主可控方案 §8 第 6/7 项、§11.2 缺口② / §11.8；门禁 §B16 |

### 2026-09-13 · 基础设施镜像补钉 digest（`postgres` / `redis`）

> **补登说明（自我登记）**：与上三条同口径，本条亦为**事后补登**（先动手、后补登）。

| 项 | 内容 |
| --- | --- |
| **时间** | 2026-09-13（**已实施并验证**） |
| **变更** | [`docker-compose.yml`](../docker-compose.yml)：`postgres` 的 `image` → `pgvector/pgvector:0.8.0-pg16@sha256:a132765ec351c65111b5b675928a3a0515a466a40f97277329db8b8209ad8bc9`；`redis` 的 `image` → `redis:7.4-alpine@sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf`（各加一行说明注释） |
| **原因** | 缺口③的收尾：这两个镜像仍按 **tag** 引用 ⇒ tag 可变、**归档与运行可能不是同一镜像**；`minio` 在上一条已钉死，本条补齐至**三个服务口径一致** |
| **影响面** | ① 两个镜像引用**变为不可变**；② **镜像版本不变**（digest 取自本机已拉取的同一 tag）；③ **不动**：服务定义、端口、卷、环境变量、应用代码、依赖版本、`migrations/` |
| **回退方式** | 删除两处 `@sha256:…` 后缀即可（回到 tag 引用）。**文件级操作、无数据迁移** |
| **验证** | ✅ `docker compose -p workbench -f docker-compose.yml config --images` ⇒ **三条全为 `tag@sha256:…`**；✅ **Redis 真起服务**（宿主 `16379`）⇒ **`PING = PONG`**、`redis_version:7.4.11`；✅ **PG 真起服务**（宿主 `15432`、`--tmpfs`）⇒ `pg_isready` accepting、`PostgreSQL 16.10`；✅ **`CREATE EXTENSION vector` 成功** ⇒ `pg_extension` 含 **`vector 0.8.0`**；✅ 两个临时容器**均已删除** |
| **验证方式说明** | 本机 `5432/6379/9000/9001` **被其它项目容器占用**（`infra-postgres-1`/`infra-redis-1`/`infra-minio-1`），故**改用 `15432/16379` + `--tmpfs`**，**未用项目命名卷、未触碰其它项目** |
| **未做 / 未验证** | **未跑 `docker compose up` 全栈**（端口被占，且会创建命名卷）；**未做 compose 级"错 digest 必失败"反假测试**（机制已在 `Dockerfile` 侧证过） |
| **依据** | 自主可控方案 §11.2 缺口③ / §11.9 / **§11.10**；门禁 §B16 |

### 2026-09-13 · 缓存/事件总线服务端由 Redis 换为 Valkey（许可驱动）

> **补登说明（自我登记）**：与上四条同口径，本条亦为**事后补登**（先动手、后补登）。

| 项 | 内容 |
| --- | --- |
| **时间** | 2026-09-13（**已实施并验证**） |
| **变更** | [`docker-compose.yml`](../docker-compose.yml) `redis` 服务 image：`redis:7.4-alpine@sha256:ff02b58f…eadf` → **`valkey/valkey:8-alpine@sha256:d2e18f3410b6f616de1417f570fa55261af2898b9c5b2cfb6781ce2373ea43d1`**（**Valkey 8.1.10**）；**服务名保持 `redis` 不变** |
| **原因** | Redis 自 **7.4** 起为 **RSALv2 / SSPLv1**（source-available，**非 OSI 开源**）：RSALv2 明文**禁止把其功能作为服务提供给第三方**，SSPLv1 含**服务化即须开源对应源码**义务。按用户裁决"**不引入 copyleft**"＋交付形态"**现在内部、将来可能对外**" ⇒ 换成 **Valkey（BSD 3-Clause）**（见自主可控方案 §8 第 8 项 / §11.11） |
| **影响面** | ① **服务端实现替换**（协议与 URI 沿用 ⇒ **应用代码零改动**）；② 镜像引用**不可变**（digest）；③ **不动**：服务名、端口、卷、环境变量、`WORKBENCH_REDIS_URL`、应用代码、依赖版本（`redis` Python 客户端不变）、`migrations/` |
| **回退方式** | 该行还原为 `redis:7.4-alpine@sha256:ff02b58f…` 即可（**文件级、无数据迁移**；⚠️ **回退即回到 source-available 许可**） |
| **验证** | ✅ **许可取证 @tag `8.1.10`**（两份 BSD 3-Clause，blob SHA `2254cb05…`）；✅ **用项目自身 `RedisStreamEventBus` 真连 Valkey ⇒ 10/10**（`XADD`/`XGROUP`+BUSYGROUP/`XREADGROUP`/`XPENDING`/`XAUTOCLAIM`/`XACK`/`XREVRANGE`/`XINFO`）；✅ **反假测试：坏地址 ⇒ exit 1**；✅ **对照组：同一套对 Redis 7.4.11 亦 10/10**；✅ **compose 级真起服务**（`up -d redis` ⇒ `Up`、`valkey-cli ping` = `PONG`、对该服务再跑兼容套件 10/10）；✅ 回归 **`1434 passed` + `compileall` 通过**；✅ 临时容器/网络/新建卷**已清理** |
| **未验证** | ⚠️ **`1434` 不覆盖 Streams**（CI 后端 job 无服务容器 ⇒ **不得作为兼容性证据**）；**未验证持久化（RDB/AOF）与主从/集群形态**；**未压测** |
| **依据** | 自主可控方案 §8 第 8 项 / **§11.11**；许可清单【决策留痕】；门禁 §B16 |

### 2026-09-13 · 对象存储由 MinIO 换成 SeaweedFS（许可驱动）

> **补登说明（自我登记）**：与上五条同口径，本条亦为**事后补登**（先动手、后补登）。

| 项 | 内容 |
| --- | --- |
| **时间** | 2026-09-13（**已实施并验证**） |
| **变更** | [`docker-compose.yml`](../docker-compose.yml)：服务 `minio` → **`seaweedfs`**，镜像 → **`chrislusf/seaweedfs:4.46@sha256:08d516132314207d10c8e37cbffc1f32b147d870169688734cc61c6231625b62`**（**Apache-2.0**）；改为 `entrypoint: /bin/sh -c` + 启动脚本（**由环境变量生成 `/tmp/s3.json` 凭据**，不落仓库、不进镜像）；S3 端口对齐 **9000**；**显式关闭遥测**（`-master.telemetry=false`）与两个多余目录服务（`-s3.port.iceberg=0`、`-s3.port.lance=0`）；[`docker-compose.app.yml`](../docker-compose.app.yml)：`WORKBENCH_OBJECT_STORAGE_URL` → `http://seaweedfs:9000` |
| **原因** | MinIO 为 **GNU AGPLv3**；按用户裁决"**不引入 copyleft**"（交付形态"现在内部、将来可能对外"）换成 **Apache-2.0** 的 SeaweedFS。候选取证：**SeaweedFS=Apache-2.0 ✅ / Garage=AGPL-3.0 ❌ / Ceph RGW=LGPL-2.1·3 ⚠️**（见许可清单【MinIO 替代候选取证】） |
| **影响面** | ① **对象存储实现替换**；② 服务名变更 ⇒ 同步改 compose.app 的 URL（**全仓唯一引用，1 行**）；③ **不动**：`WORKBENCH_MINIO_*` 变量名、卷名 `workbench-minio`、宿主端口默认值（9000/9001）、app 代码、依赖、`migrations/`；④ **镜像体积上升 61 MB → 195 MB** |
| **回退方式** | 还原 compose 里的对象存储服务块（含 quay 镜像引用与 `command`）与 compose.app 那一行；**文件级、无数据迁移**（对象存储此前未真正接入，无业务数据） |
| **验证** | ✅ `compose config --images` 三条全为 `tag@sha256`；✅ **服务真起**（`Up`；日志 `Start Seaweed S3 API Server 30GB 4.46 d997fba15 at http port 9000`）；✅ **PID 1 参数含 `-master.telemetry=false` 与 `-s3.port.iceberg=0 -s3.port.lance=0`**，且日志**无 Iceberg/Lance 行**；✅ **S3 真实冒烟（boto3）**：`CREATE_BUCKET`/`PUT_OBJECT`/`GET_OBJECT`（**内容一致**）/`LIST_OBJECTS`/`DELETE_OBJECT` ⇒ **ALL_PASS**；✅ 临时容器/网络/新建卷**已清理**；✅ **回归**：后端基线 **`1434 passed, 0 failed`**（compose 文件测试会读 ⇒ 按纪律重跑） |
| **未验证** | ⚠️ **未验证**多副本/纠删码、S3 分片上传、生命周期、跨版本升级、压测（本项目当前均未使用）；⚠️ **已知限制**：凭据须为 **JSON 安全字符**（含 `"`/`\` 会启动失败，**fail-closed 不静默降级**） |
| **依据** | 自主可控方案 §8 第 7 项 / **§11.12**；许可清单【MinIO 替代候选取证】；门禁 §B16 |
