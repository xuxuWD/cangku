# P4 技能层（技能包 + 注册表 + 白名单审计） 立项规格

> **性质**：**阶段规格（唯一真源）**。本文定义「P4 技能层」做什么、怎么做、怎么验收。
> **上位真源**：[`2026-09-12-conversational-agent-platform-design.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md) §14.1 P4（`SKILL.md` + 注册表 + MCP 客户端 + 白名单审计 + 沙箱加固）、§2.2（SKILL.md 事实标准 / MCP 不含量）、§15 #3（技能包投毒攻击面）、§6（dsh 用法边界）；[`capability-ownership-map.md`](file:///d:/徐徐AI学习/公司工作台/docs/capability-ownership-map.md) #17（技能层 = A 自研，`SKILL.md` 为开放标准、可遵循不搬实现）；[`moat-boundaries.md`](file:///d:/徐徐AI学习/公司工作台/docs/moat-boundaries.md) §2（M2 沉淀层 = 「越用越强」唯一载体）。
> **依据**：[`iteration-research-2026-09-15.md`](file:///d:/徐徐AI学习/公司工作台/docs/iteration-research-2026-09-15.md) §4.1（DeerFlow SKILL.md 包格式 / eino 工具白名单两端 / OpenViking 只借模型）、§6.5（知识×工作流闭环）；P3 记忆层已交付（本层消费记忆的「技能引用」能力，非前置依赖）。
> **日期**：2026-09-15
> **状态**：**已实现（2026-09-15）**——迁移 030/031、`app/skills/`（models/validator/store/service）、路由、审计扩 5 动作码、env 模板、api-contract 均已落地；**M5 裁决已落地（技能包正文库内落库，`031_skills_content` + 体积上限 + 指纹一致性）**；全量回归 **1842 passed / 45 skipped**（新增 20 个技能层用例 + 4 个真库用例含 M5 正文用例）。实现与本期规格口径一致；既有已交付组件未改动（除 `audit/models.py` 扩 5 动作码、`admin-web` 审计标签同步、`settings/env` 加配置外）。
> **前置**：P3 记忆层已交付（`029` + `app/memory/`，CI 全绿）；P2a 段二（dsh 接入 + 隔离容器 + `ToolSpecCatalog` 闸门）已交付——**本层挂在既有执行闸门之后**，不为技能另建执行通道。

---

## 0. 真库回归记录（2026-09-15，本机一次性容器）

> **环境**：Docker `pgvector/pgvector:pg16`，端口 55435，容器 `workbench-pg-030`，**跑完即删**（同 023 §16 / 029 §3.5 口径）。

- **从零应用迁移**：31 条（`001` → `031_skills_content`），含两条新表与 JSONB `allowed_tools` 列 + `content_body` 正文列（M5 裁决，追加迁移）。
- **真库用例 `tests/test_skills_postgres.py`：4 条全绿**：① `workbench_skills` 持久化 + JSONB 读回 + `content_body` 落库读回一致 + `content_sha256` 由正文派生；② 状态机 submitted→approved→enabled→disabled 真库写回（`reviewed_by` 落库）；③ 同 key 多版本并存 + 只 `enabled` 版本参与 `expanded_tools_for_agent` 交集；④ 生命周期 `list_all_for_tenant`/`delete_all_for_tenant`（N2 对称）。
- **未发现需修复的 PG 缺陷**（吸取 P3 教训：任务 prompt 内置 psycopg 参数顺序纪律 + `RETURNING` 下标对照）。
- **未验证（如实登记）**：~~CI `postgres` job 在真实 GitHub Actions 跑 `test_skills_postgres.py` 尚未发生~~ ——**已销账（2026-09-15）**：push `168840a`（P4 初交付）触发 run `34951486037`、push `88ffd44`（M5 落库）触发 run `34952989393`，**两轮均 6/6 job conclusion=success**（后端 pytest+compileall / 三端构建 / 后端真库 5 模块 skipped=0 / 沙箱真容器回归，含 M5 后的 content_body 用例）；技能脚本在隔离容器内的真实执行（沙箱只读挂载 `/mnt/skills/`）属 P2a 段二联动，未在本层跑真容器（仍待验证）。

---

## 1. 范围

### 1.1 什么是「技能层」（P4 的边界定义）

技能层让数字员工能把「可复用的操作能力」声明为**版本化技能包**，经**审核-登记-启用**后才能被对话/任务路径调用。它不是新执行引擎——**执行仍走既有九步闸门 + `ToolSpecCatalog`**；技能层提供的是「包的声明、校验、注册、白名单、来源与审计」。

### 1.2 做什么（六项）

| # | 事项 | 一句话 |
| --- | --- | --- |
| A | **技能包格式（遵循 `SKILL.md` 开放标准）** | 元数据 frontmatter（`name` / `description` / `license` / **`allowed-tools`**）+ 内容（`scripts` / `references` / `assets`）；**不搬 DeerFlow 实现，只遵循标准格式** |
| B | **技能注册表**（迁移 + 仓储） | `workbench_skills` 表（租户语义 + 版本 + 状态 + 来源 + owner）+ 内存/PG 双实现 |
| C | **准入闸门（人工在环）** | 技能包提交 → **人工审核（`super_admin`）** → 通过后登记；**来源白名单**：只允许受控来源（部署注入的来源 key），**不允许用户自传技能包直接生效** |
| D | **白名单 / 权限 / 审计** | 技能与数字员工 `tool_allowlist` 联动；调用审计动作码；`allowed-tools` 与既有 `ToolSpecCatalog` 交集校验（**取交集、fail-closed**） |
| E | **执行接线（只挂在既有闸门后）** | 已启用技能 → 其 `allowed-tools` 展开进会话工具面（复用 027 待批动作 + 九步闸门 + `agent_key` 校验收紧）；**不新增第二条执行通道** |
| F | **沙箱加固（联动）** | 技能包内容（scripts）在**既有隔离容器**内**只读挂载**（`/mnt/skills/`，DeerFlow 同款机制），不可写；包内文件 hash 校验防篡改 |

### 1.3 不做什么（明确排除）

1. **不做 MCP 客户端拉起**（立项 §14.1 P4 原文含「MCP 客户端」，但：调研 §4.4 取向 3「MCP 已是事实标准、不含治理」，dsh 原生 `dsh-mcp-client` 已归类「能用的」——**本层不实现 MCP 协议客户端**，对外部 MCP server 的连接走 dsh/既有适配器；MCP 客户端**单独立项**（§4 未决 M1），不在本规格实现）。
2. **不做技能执行引擎**：技能不写代码执行器；其脚本运行统一在既有隔离容器 + 九步闸门内，**绝不绕过**。
3. **不做自进化**（P6 是独立里程碑）：技能准入靠**人类审核**，不由 LLM 自评/自批（生成者 ≠ 评审者硬约束先行）。
4. **不建技能市场 / 公开技能源下载**：来源白名单是**部署注入的受控 key**，不从公开仓库拉包。
5. **不改数字员工 `tool_allowlist` 既有语义**（`023`，只存不用；本层把「已启用技能」并入其可见面，但不动 023 表结构）。
6. **不引入 EvoFlow / OpenViking / DeerFlow 代码**（许可或只读学口径，capability-map #17/#28 红线不变）。

### 1.4 影响什么（改动面）

| 层 | 影响 |
| --- | --- |
| 数据库 | 新迁移 `030_skills.sql`：`workbench_skills`（技能包元数据+版本+状态+来源+owner）+ `workbench_skill_bindings`（数字员工↔技能 中间表，租户隔离写进约束） |
| 后端 | 新模块 `app/skills/`（模型 / 仓储 / 服务 / 校验器）；`app/main.py` 增管理路由；审计扩动作码（`skill.submitted` / `skill.approved` / `skill.rejected` / `skill.enabled` / `skill.disabled` / `skill.invoked`）；`ToolSpecCatalog` 增加「按技能展开 allowed-tools 交集」组合接口（**不改既有默认集**） |
| 配置 | `.env.example` / `.env.staging.example`：`WORKBENCH_SKILL_SOURCE_ALLOWLIST`（来源白名单，逗号分隔；空 = 关闭技能层，fail-closed） |
| 契约 | `docs/api-contract.md` 新增「技能（P4）本章节」 |
| 既有行为 | 未启用任何技能时**行为与今天完全一致**（零默认技能）；技能启用是显式管理动作 |

---

## 2. 设计

### 2.1 事项 A：技能包格式（遵循 `SKILL.md` 开放标准）

> 依据：立项 §2.2「`SKILL.md` 已被 30+ 产品采纳（Copilot / Cursor / Codex CLI / OpenHands / Letta…），渐进式披露、token 效率显著优于把整个 REST API 镜像成工具」；迭代调研 §4.1 DeerFlow 项②。

**包结构**（遵循标准，不搬实现）：

```
SKILL.md                  # frontmatter + 渐进式披露正文（描述 / 用法 / 边界）
scripts/                  # 可执行脚本（沙箱只读挂载）
references/               # 引用文档（只读）
assets/                   # 静态资源（只读）
```

**frontmatter 必填字段**：

| 字段 | 要求 | 校验 |
| --- | --- | --- |
| `name` | 小写标识（同 `rule_key` 风格） | 白名单格式 |
| `description` | ≤ 800 字符 | 长度上限 |
| `license` | **必须是受支持的许可**（白名单：Apache-2.0/MIT/BSD-3；其它一律拒） | 许可清单 fail-closed |
| `allowed-tools` | **工具键数组** ∈ 既有 `ToolSpecCatalog` 键集 | 逐键校验，未知键即拒 |
| `version` | 语义版本 `major.minor.patch` | 正则 + 递增校验 |

**校验器 `SkillPackageValidator`**：解析 frontmatter + 校验必填/格式/许可/`allowed-tools` 交集 → 任一不通过即 `422`（`InvalidSkillPackage`），**不登记**。包内容 hash 在登记时计算存表（`content_sha256`），供沙箱挂载前复核（防文件被替换）。

### 2.2 事项 B：技能注册表（迁移 030）

`workbench_skills`（租户语义 + 状态机）：

```sql
CREATE TABLE IF NOT EXISTS workbench_skills (
    tenant_id       TEXT NOT NULL,
    skill_key       TEXT NOT NULL,
    version         TEXT NOT NULL,           -- 语义版本号
    name            TEXT NOT NULL,
    description     TEXT NOT NULL,
    license         TEXT NOT NULL,           -- 白名单校验后的许可标识
    allowed_tools   JSONB NOT NULL,          -- allowed-tools 数组（服务端校验后落库）
    status          TEXT NOT NULL DEFAULT 'submitted'
        CHECK (status IN ('submitted','approved','rejected','enabled','disabled')),
    source_key      TEXT NOT NULL,           -- 来源 key（须 ∈ 部署注入白名单）
    content_sha256  TEXT NOT NULL,           -- 包内容指纹（防篡改）
    owner_id        TEXT NOT NULL,           -- 提交人
    reviewed_by     TEXT,                    -- 审核人（super_admin）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, skill_key, version)   -- 版本多行，同 key 多版本并存
);
```

`workbench_skill_bindings`（数字员工 ↔ 技能 中间表，租户隔离复合外键同 022 手法）：

```sql
CREATE TABLE IF NOT EXISTS workbench_skill_bindings (
    tenant_id   TEXT NOT NULL,
    agent_key   TEXT NOT NULL,
    skill_key   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
    created_by  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, agent_key, skill_key)
);
```

**状态机**：`submitted → approved → enabled → disabled`（可回退：`enabled ⇄ disabled`；`approved ⇄ submitted` 允许退回修改；`rejected` 终态）。同 `skill_key` 多版本并存：只 `enabled` 版本参与工具面展开。

### 2.3 事项 C：准入闸门（人工在环，技能包投毒防御）

- **来源白名单（部署注入）**：`WORKBENCH_SKILL_SOURCE_ALLOWLIST=src1,src2`；提交时 `source_key` 必须在该集合内，否则 `403`。**空白名单 = 技能层关闭**（fail-closed：能登记、不能启用）。
- **人工审核**：`approved` / `rejected` 仅 `super_admin`；提交人不能审核自己提交的包（生成者 ≠ 评审者，立项 §2.2 实证 LLM 自评仅 46.4%，此处人力同规则）。
- **不允许用户自传技能包直接生效**（立项 §15 #3 原文）——登记只是申报，**启用**是独立管理动作。
- **D11 类防护**：`description` 写入阶段扫描「自我授权 / 绕过权限」指令，命中 `422`（复用对话层 D11 同款扫描思路，不复制实现）。

### 2.4 事项 D：白名单 / 权限 / 审计

- **`allowed-tools` 与 `ToolSpecCatalog` 的交集校验**：登记时逐键校验 ∈ 目录；**启用时再取目录交集**（目录可升级，技能允许集随目录收窄——**取交集、fail-closed**）。
- **数字员工侧**：`enabled` 技能经 `workbench_skill_bindings` 绑定到特定 `agent_key` 后才进入该员工的会话工具面；未绑定不展开。
- **审计动作码**：`skill.submitted` / `skill.approved` / `skill.rejected` / `skill.enabled` / `skill.disabled` / `skill.invoked`（`invoked` 在技能首次被会话调用时记一次，明细 = `skill_key`/`version`/`agent_key`，不记正文）。明细键进 `ALLOWED_DETAIL_KEYS` 白名单。

### 2.5 事项 E：执行接线（只挂既有闸门后）

```
技能 enabled + 绑定 agent_key
   → 会话启动时：展开 allowed_tools（与 ToolSpecCatalog 交集）
   → 工具调用仍走 027 待批动作 + 九步闸门 + agent_key 校验收紧（全复用，不新增路径）
   → 技能脚本在既有隔离容器运行（见 2.6）
```

**零默认技能**：未启用任何技能时，工具面 = 既有默认集（`fs.*`/`cmd.run`/`artifact.export`），**行为与今天的 P2a 段二完全一致**。

### 2.6 事项 F：沙箱加固联动

- 技能包 `scripts/` 在容器内**只读挂载**（`/mnt/skills/`，DeerFlow §4.1 同款），容器侧无写权限。
- 挂载前按 `content_sha256` **复核包文件 hash**，不匹配拒绝启动执行（防托管侧篡改）。
- 技能脚本执行仍受容器 `--network none` + 只读根 + 无长寿命凭据约束（**不降低**既有沙箱基线）。

### 2.7 配置项（外置，fail-closed）

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `WORKBENCH_SKILL_SOURCE_ALLOWLIST` | 空 | 逗号分隔来源 key；空 = 技能层关闭（可登记不可启用） |
| `WORKBENCH_SKILLS_SANDBOX_MOUNT` | `/mnt/skills` | 容器内只读挂载点（服务端常量，不进前端） |

### 2.8 与 P3 记忆层的关系（非依赖）

- P4 不消费 P3 存储；但「技能引用」可作为事实类记忆（`POST /api/v1/memory/facts` 的 content = 技能键），打通 M2 沉淀层（迭代调研 §6.5 知识×工作流闭环的后半段）。
- **M3 打通已实现（2026-09-15）**：`POST /api/v1/skills/{key}/versions/{v}/memories` 技能经验 → 事实类记忆（正文带 `[skill:key@version]` 前缀、幂等、归属操作者，记忆层未接线 503）。

---

## 3. 验收

### 3.1 正常流程（查库验证）

1. `POST /api/v1/skills`（source_key ∈ 白名单）提交合法包 → 表内出现 `status='submitted'`，`content_sha256` 非空。
2. `super_admin` 审核通过 → `status='approved'`；再启用 → `status='enabled'`。
3. 绑定技能到某 `agent_key` → 该员工会话工具面含其 `allowed-tools` 交集；未绑定员工无。
4. 技能脚本在容器只读挂载（`/mnt/skills/`）且 hash 复核通过 → 执行成功 + 写 `skill.invoked` 审计。

### 3.2 临界 / 异常与非法输入

| 用例 | 期望 |
| --- | --- |
| 未登录 / 过期 Token | 401 |
| 普通员工提交 / 审核技能 | 403 |
| 提交人审核自己的提交 | 403（生成者 ≠ 评审者） |
| `source_key` 不在白名单 | 403 |
| `license` 非白名单许可 | 422（许可白名单 fail-closed） |
| `allowed-tools` 含非目录键 | 422（逐键校验，未知键拒） |
| `description` 含绕过权限指令 | 422（D11 类扫描） |
| 版本号不递增 / 非法格式 | 422 |
| 白名单为空时启用技能 | 403（技能层关闭） |
| 技能包文件被篡改（hash 不符） | 挂载前拒绝，不启动执行 |
| 与朋友幂等 | 同 `(tenant, skill_key, version)` 重复提交幂等（返回既有记录） |

### 3.3 反假测试

- 故意给 `allowed-tools` 塞一个目录外工具键 → 「逐键校验」用例必须变红。
- 故意放行 `license=GPL-3.0` → 「许可白名单」用例必须变红。
- 故意让技能包在沙箱内可写 → 「只读挂载」用例必须变红。
- 故意删掉交集校验 → 启用时工具面含目录外工具 → 用例必须变红。

### 3.4 一键回归

`pytest` 全量（含新 `tests/test_skills_*.py`）+ CI 真库 job 纳入 `test_skills_postgres.py`（同 DSN 门控模式）。

---

## 4. 未决项 / 不在本期

| # | 项 | 状态 |
| --- | --- | --- |
| M1 | **MCP 客户端**（立项 §14.1 P4 原文含，本规格**砍出**） | 单独立项：连接外部 MCP server 需先过出网/凭据/资源三关评审（capability-map §4 D3 同款流程）；本层交付前 npm/pypi MCP SDK 不引入 |
| M2 | 技能**市场 / 公开源下载** | 不做（来源白名单为部署注入受控 key） |
| M3 | 技能 ↔ 记忆打通（技能引用入事实类记忆） | ✅ **已实现（2026-09-15）**：`POST /api/v1/skills/{key}/versions/{v}/memories` 把技能经验沉淀为**事实类记忆**（正文带 `[skill:key@version]` 前缀可检索；幂等键由 `skill_key@version+content` 派生；归属操作者；记忆层未接线 → 503 fail-closed）。`app/main.py` 装配时注入 P3 `memory_service` 实例；审计复用 `memory.fact.created`。`tests/test_skills_layer.py` 5 用例 + 契约「技能（P4）」已同步 |
| M4 | 技能**灰度 / 回滚**（版本切换自动回滚） | 属 P6（自进化）范围；本层只做「enabled ⇄ disabled」人工回退 |
| M5 | 技能包**内容托管**（对象存储 vs 库内） | **已裁决（2026-09-15）：库内落库**——新增迁移 `031_skills_content.sql` 为 `workbench_skills` 加 `content_body` 列（技能包正文，TEXT），服务端校验体积上限（`WORKBENCH_SKILL_CONTENT_MAX_BYTES`，默认 64 KiB）+ 复用 `content_sha256` 指纹验证正文一致；对象存储路径留作后续（大文件技能再评审），本期**不接**对象存储 |

---

## 5. 风险与红线

1. **技能包投毒是真实攻击面**（立项 §15 #3）：来源白名单 + 人工审核 + hash 复核 + 沙箱只读，四层缺一不可；**不允许用户自传技能包直接生效**。
2. **不新增执行通道**：执行永远走九步闸门；技能只是「包声明」，不是第二个执行器。
3. **许可纪律**：`license` 白名单 fail-closed；不引入 EvoFlow/OpenViking/DeerFlow 代码（只读学/许可红线）。
4. **生成者 ≠ 评审者**：审核是独立人类动作，不由提交者/LLM 代审。
5. **零默认技能**：上线不动默认行为；未启用 = 与今天完全一致。