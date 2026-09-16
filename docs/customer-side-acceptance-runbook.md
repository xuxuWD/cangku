# 客户侧交付验收运行手册（人机协作 · 只读）

> **用途**：在**客户侧**（私有部署环境）对「交付验收」这条垂直面做一次**只读**核验：容器起栈产物可追溯、日志有界、健康与排程、连接账目与容量、监控告警**是否真的接入**、运行事件与审计留存口径。
> **执行方式**：**AI 不连客户 / 生产环境**。本手册的命令由**人在客户侧服务器上执行**，把输出回传（凭据一律用 `***` 替换）后由 AI 判读。
> **只读承诺**：本手册**全部核验命令只读**——不改数据、不改配置、不跑迁移、不重启/停止容器、不推镜像、不发写请求。会写数据或改配置的动作（迁移、回滚演练、密钥轮换、压测写入、首次起栈等）一律列入 [§5 明确排除](#5-明确排除会写数据--改配置另行授权后再跑)，**另行授权后再跑**。
> **验证状态（如实登记）**：本手册**尚未在客户侧 / 生产执行过**（客户环境未就绪）。文中引用的阈值与实测数据来自 `docs/private-deployment-runbook.md` 的**本机容器演练**（2026-09-16），**本机数据不替代客户侧压测**；监控告警渠道**当前未接入任何环境**。因此本手册任何一项在客户侧回传前，一律视为**未验证**。

## 0. 与 `docs/readonly-verification-runbook.md` 的分工与衔接

两份清单**范围不重叠**，合起来是一次完整的客户侧只读轮次：

| | `docs/readonly-verification-runbook.md` | 本手册 |
| --- | --- | --- |
| **垂直面** | **岗位 / 数字员工目录与阶段 2 闸门**：知识访问绑定归一、目录收敛条件、停用标识影响面 | **交付验收**：镜像与产物可追溯、日志有界、健康与排程、连接账目与容量、监控告警接入、运行事件与审计留存 |
| **典型产物** | 9 条目录/绑定类 SQL、`/api/v1/workforce/*` 只读 GET、跨租户探测 | 容器/镜像 `docker inspect` 核对、连接与事件类 SQL、`scripts/customer_acceptance_probe.py` |

**衔接（本手册不重述对方内容，只引用）**：

1. **只读账号、只读包装、令牌获取**：`psql` 的 `SET default_transaction_read_only = on` 包装、只读账号建法与 `pg_read_all_data` 口径、超管令牌三种情形，**全部见对方 §0 / §1.1 / §1.3**，本手册直接沿用，不重复。
2. **脱敏回传口径**同对方 §0 第 3 条：DSN / 口令 / 令牌不贴进聊天，回传用 `***` 替换。
3. **两章的「明确排除」互为补充**：合并执行一个轮次时，以**两份排除项的并集**为准。
4. **判读与真源回写**：回传由 AI 判读（[§4 回传模板](#4-回传模板)）；状态真相只在 `docs/delivery-readiness-checklist.md` 维护，本手册不另立状态。

---

## 1. 前置

| 项 | 说明 |
| --- | --- |
| `WORKBENCH_APP_IMAGE` | 起栈所用镜像引用（**必须带版本标签**，例：`workbench-app:v1.2.3`） |
| `BASE` | 应用入口（例：`https://workbench.customer.internal`） |
| `WORKBENCH_PROBE_PSQL_DSN` | **只读**连接串：`postgresql://<只读账号>:<口令>@<主机>:5432/<库名>`。**注意**：应用侧配置是 `postgresql+psycopg://`，`psql` / 探针用**不带** `+psycopg` 的写法 |
| 容器名 | 探针默认 `workbench-app-1` / `workbench-worker-1` / `workbench-beat-1`；**项目名不同时必须显式传入**。实际名字用 `docker compose -f docker-compose.yml -f docker-compose.app.yml ps --format '{{.Name}}'` 查（只读） |
| 工具 | `docker`（含 compose 插件）、`psql`、`curl` |
| 不进本轮 | 任何 `up` / `build` / `restart` / `exec` / `pull` / `push`（见 §5） |

---

## 2. 验收面（逐项命令 + 判据）

> 除特别说明外，命令均为**只读**。每项的结论只允许三种取值：`pass` / `fail` / `skipped`（探针输出形如 `[pass] 检查项：…`）。
> `skipped` **不等于通过**——核对不到的环境必须显式记 `skipped` 并写明原因，回传时登记为「未验证」。

### 2.1 容器起栈与产物可追溯

**A. 部署侧前置动作（另行授权：会创建镜像与容器，不属于本轮只读核验）**

首次起栈或版本更新由运维在维护窗口执行，命令与 `Dockerfile` / `docker-compose.app.yml` 头注释一致：

```bash
# 带版本号与构建编号构建（宪法 §6.3 产物可追溯）
docker build \
  --build-arg WORKBENCH_IMAGE_VERSION=$(git describe --tags --always) \
  --build-arg WORKBENCH_IMAGE_REVISION=$(git rev-parse HEAD) \
  -t workbench-app:$(git describe --tags --always) .

# 用同一标签起栈；不显式给 WORKBENCH_APP_IMAGE 时编排回落到 `workbench-app`（即 :latest）——正式交付禁止
WORKBENCH_APP_IMAGE=workbench-app:<版本> \
  docker compose -f docker-compose.yml -f docker-compose.app.yml up -d --no-build
```

**B. 只读核对（本轮执行）**

```bash
# ① 运行中的三个服务分别用了哪个镜像标签（应为同一带版本标签，不得是 latest）
docker inspect <app容器> <worker容器> <beat容器> \
  --format '{{.Name}} -> {{.Config.Image}}'

# ② 镜像引用（禁 latest / 禁无标签）
echo "$WORKBENCH_APP_IMAGE"

# ③ 5 个 OCI 标签
docker image inspect "$WORKBENCH_APP_IMAGE" --format '{{json .Config.Labels}}'
```

- **判据**：① 三服务镜像引用**逐字相同**且带版本标签；② 引用**不得**为 `:latest`、**不得**无标签（无标签即回落 `:latest`）；③ 标签须同时含 `org.opencontainers.image.title` / `description` / `version` / `revision` / `source`，且 **`version` ≠ `dev`、`revision` ≠ `unknown`**（`dev` / `unknown` 是未注入 `--build-arg` 的默认值，**不算正式版本** ⇒ 「假可追溯」）。
- **`fail` 的典型形态**：`version=dev`、`revision=unknown`、镜像引用是 `workbench-app`（无标签）或 `workbench-app:latest`。
- 一并登记**版本号与构建编号原文**（回传后用于查回对应提交）。

### 2.2 日志有界（三服务）

```bash
for c in <app容器> <worker容器> <beat容器>; do
  echo "== $c"; docker inspect "$c" --format '{{json .HostConfig.LogConfig}}'
done
```

- **判据**：三个服务的 `LogConfig` 均为 `driver=json-file`、`max-size=10m`、`max-file=5`。
- **为什么必须核**：应用日志只写 stdout，审计为单行 JSON；未设上限时容器日志无界增长，会**先于「磁盘容量告警」把人写爆盘**。
- **依据**：`docker-compose.app.yml`（2026-09-16 本机演练 `docker inspect` 实查生效；`tests/test_compose_worker_assets.py::test_app_services_bound_container_log_growth` 守护）。

### 2.3 健康与排程

```bash
# ① 应用健康
curl -sS -o - -w '\nHTTP %{http_code}\n' "$BASE/api/v1/health"

# ② worker healthcheck 状态（编排内置：celery inspect ping，interval 30s / retries 3）
docker inspect <worker容器> --format '{{json .State.Health}}'

# ③ beat 是否在派发（调度停 ⇒ Outbox 不发布、生命周期作业与到期扫描全停）
docker compose -f docker-compose.yml -f docker-compose.app.yml logs beat --tail 200 \
  | grep "Sending due task" | tail -5

# ③' 顺带看保留期清理任务是否被派发（迁移 034 起新增排程）
docker compose -f docker-compose.yml -f docker-compose.app.yml logs beat --tail 500 \
  | grep "runtime-events-purge" | tail -5
```

- **判据**：① HTTP 2xx 且响应体 `{"status":"ok"}`；② `State.Health.Status=healthy`（`starting` / `unhealthy` / 无 healthcheck 块均判 `fail`）；③ 最近日志中**出现 ≥1 条** `Sending due task`；③' 见得到 `runtime-events-purge` 的派发记录（看不到 ⇒ 保留期清理未在跑，见 §2.6）。
- **注意**：`beat` 容器**故意关闭**了镜像级 HTTP healthcheck（beat 不开端口，继承会让容器永远 `unhealthy`）⇒ **beat 的存活性只能看「是否在派发」**，不要用 `State.Health` 判 beat。

### 2.4 连接账目与容量复测

统一包装（与只读核验清单 §2 同口径：会话级只读 + `ON_ERROR_STOP`）：

```bash
psql "$WORKBENCH_PROBE_PSQL_DSN" -v ON_ERROR_STOP=1 \
  -c "SET default_transaction_read_only = on" \
  -c "<下面的 SQL>"
```

```sql
-- ① 连接总数与上限
SELECT count(*) AS used,
       (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') AS max_connections
  FROM pg_stat_activity;

-- ② 连接按状态/来源分摊（看清是谁占的）
SELECT coalesce(state, '(null)') AS state, count(*) FROM pg_stat_activity GROUP BY 1 ORDER BY 2 DESC;
SELECT coalesce(application_name, '(null)') AS app, count(*) FROM pg_stat_activity GROUP BY 1 ORDER BY 2 DESC;

-- ③ 账目核对用：本库自身连接数与各库分布（多租户共实例时避免误判）
SELECT datname, count(*) FROM pg_stat_activity GROUP BY 1 ORDER BY 2 DESC;
```

- **判据**（runbook「容量与并发」「监控与告警」同口径）：
  1. `max_connections` **≥ 100**（默认值即可满足）——低于 100 判 `fail`；
  2. 使用率 `used / max_connections` **≤ 80%**——超过即命中告警线，判 `fail`（先处置再放行）；
  3. **账目对照**：稳态连接数 = **38（`app` 启动即持有，各组件各自建池、`min_size=1` 累加）+ 2×并发（`worker` 每个任务子进程 2 个池：共享池 + 审计池）+ 1（运维 / 探针）**。以 `WORKBENCH_WORKER_CONCURRENCY`（默认 2）代入 ⇒ 预算 **43**；实测高于预算属**可能的瞬态扩容**（各池 `max_size=10`），须在回传里说明当时是否有压测/批处理在跑。
- **并发压测不属于本轮**：真实压测（`scripts/staging_concurrency_probe.py`）会发 `POST`，列入 §5。本节只做**连接账目复测**。
- **⚠️ 本机数据不替代客户侧压测**：仓库里 2026-09-16 的容量数据（扫描 400 篇 ≈2.0–2.1s、600 事件排空、RSS 123–206MiB 等）出自本机 Docker Desktop + Windows 宿主，**Linux 宿主、客户数据规模、PG 参数与网络时延均不同**。本节的结论只能来自**客户侧实测**。

### 2.5 监控告警「接入」核对（规则成文 ≠ 告警生效）

> **分工**：9 条规则的**信号采样**由 `scripts/monitoring_probe.py` 负责（它会逐条给出 `ok` / `alert` / `skipped`，阈值与 runbook 表逐条一致）。**本节只做探针做不到的那一半**：**是否真的接入了渠道** + **触发一次真实告警作为证据**。

**A. 逐条核对渠道接入**（每条都要填「渠道 / 接收人 / 触发方式 / 证据」）：

| # | 信号 | 是否已接入渠道 | 渠道（Prometheus / Zabbix / 云监控 / 邮件 / webhook…） | 触发一次真实告警的证据（时间戳 + 截图/日志/告警 ID） |
| --- | --- | --- | --- | --- |
| 1 | beat 是否在派发（`Sending due task` 断档 ≥5 分钟） | ☐ 是 ☐ 否 | | |
| 2 | worker 容器健康（healthcheck 转 `unhealthy`） | ☐ 是 ☐ 否 | | |
| 3 | app 健康（`/api/v1/health` 非 200 或超时） | ☐ 是 ☐ 否 | | |
| 4 | Outbox 积压（`published_at IS NULL` 连续 2 个周期不下降） | ☐ 是 ☐ 否 | | |
| 5 | 死信新增（`replayed_at IS NULL` 新行） | ☐ 是 ☐ 否 | | |
| 6 | 审计是否在落（`max(occurred_at)` 长时间不推进） | ☐ 是 ☐ 否 | | |
| 7 | 宿主磁盘（≥80% 预警 / ≥90% 严重） | ☐ 是 ☐ 否 | | |
| 8 | PostgreSQL 连接数（使用率 >80%） | ☐ 是 ☐ 否 | | |
| 9 | worker 资源（单容器 RSS 持续 >512MiB） | ☐ 是 ☐ 否 | | |

**B. 触发一次真实告警（必做，作为「已生效」的唯一证据）**

**严禁**用会改数据、停服务、塞爆磁盘、改系统时钟的方式触发。可用的三种安全方式（任选其一，规则 3 必须验到）：

1. **监控平台自带的「测试告警 / 发送测试通知」**：在客户既有监控平台（Prometheus Alertmanager / Zabbix / 云监控）上对已接入的规则发一次测试通知，确认到达接收人。
2. **宿主侧轻量采集 + webhook（对应 runbook 接入方式 ②）**：用 `scripts/monitoring_probe.py` 采样一次并确认渠道收到（人执行）：

```bash
WORKBENCH_MONITOR_APP_URL="$BASE" \
WORKBENCH_ALERT_WEBHOOK_URL="<渠道地址>" \
  python scripts/monitoring_probe.py --notify
# 再跑一次不带 --notify，把 9 条规则的 ok / alert / skipped 原文一并回传
```

3. **规则 3（app 健康）**：把**监控平台侧**的探测目标临时指向一个必然非 200 的地址（改的是监控平台配置，**不碰被监控系统**），确认收到告警后改回，并在回传里写明「已改回」。

- **判据**：**渠道侧收到告警**（贴出告警 ID / 邮件标题 / webhook 接收日志的**时间戳**）。**只跑采样、渠道没收到 ⇒ 该项记 `fail`**，不得读成「监控已接入」。
- **依据声明**：`docs/private-deployment-runbook.md`「监控与告警」章已明示——**规则成文、渠道未接入任何环境 ⇒ 本项按「未验收」处理**。本节通过后，才允许去改 `docs/delivery-readiness-checklist.md` 的对应口径。

### 2.6 运行事件与审计留存

**口径（先明确）**：

- **运行事件**：独立 append-only 表 **`workbench_runtime_events`**（迁移 `034_runtime_events.sql`；主键 `(run_id, sequence)`，`occurred_at` 为清理判定列），状态行 `workbench_runtime_states` 只保留**事件计数** `event_count`（清理后不回退）。
- **保留期**：`WORKBENCH_RUNTIME_EVENTS_RETENTION_DAYS`（**默认 30 天**，合法区间 1–3650），由 worker 周期任务 `app.worker.purge_runtime_events` 按 `occurred_at` 清理（beat 排程 `runtime-events-purge`）。**只清理运行事件**。
- **审计**：`workbench_audit_log` **不轮转、不删除**（合规证据链；迁移 034 注释与本条同口径）。

```sql
-- ① 迁移 034 是否落地（表 + 状态行的 event_count 列）
SELECT table_name FROM information_schema.tables
 WHERE table_schema = 'public' AND table_name = 'workbench_runtime_events';
SELECT column_name, data_type FROM information_schema.columns
 WHERE table_name = 'workbench_runtime_states' AND column_name = 'event_count';

-- ② 事件表体量与最早/最晚事件时间（保留期判定的实测值）
SELECT count(*) AS events, min(occurred_at) AS earliest, max(occurred_at) AS latest
  FROM workbench_runtime_events;

-- ③ 状态行声明的事件计数（与 ② 的量级对照，可看出清理是否让状态行与表脱节）
SELECT count(*) AS runs, sum(event_count) AS declared_events FROM workbench_runtime_states;

-- ④ 审计表可读性与最新时间（不删除口径）
SELECT count(*) AS rows, max(occurred_at) AS latest FROM workbench_audit_log;
```

- **判据**：
  1. ① 两行都有返回 ⇒ 迁移 034 已落地；**缺表 / 缺列** ⇒ `fail`（保留期没有载体）；
  2. ② `earliest` **不得早于**「当前时间 − 保留期天数」——存在超期事件 ⇒ 保留期清理未生效，判 `fail`；`count = 0` 属正常（无运行事件）；
  3. ③ `declared_events` 与 ② 的 `events` **不必相等**（清理会删行、计数不回退，这是设计口径），但**差值持续扩大**说明清理长期未跑，须结合 §2.3 ③' 判断；
  4. ④ 审计表**必须可读**（不可读 ⇒ `fail`：合规证据链不成立）。本项只能证明「可读 + 最新时间」；**删除路径**由代码与权限守护，不在本项覆盖范围。
- **回传时务必贴出**：事件表 `count / earliest / latest` 三个值 + 保留期配置的**实际取值**（由运维从容器环境读出后告知）。**不要整段回传 `docker compose config`**——它会把编排里展开后的全部密钥（数据库口令、`WORKBENCH_*` 密钥）一并打出来。

---

## 3. 一键探针：`scripts/customer_acceptance_probe.py`

把 §2.1（B）、§2.2、§2.3、§2.4、§2.6 里**能机械核对**的项做成一次只读检查，输出可直接回传的文本（每项：**检查项 / 结论 / 实测值 / 判据**）。

```bash
# 人在客户侧服务器上执行（只读：docker inspect/logs + GET + SELECT）
export WORKBENCH_APP_IMAGE="workbench-app:<版本>"
export WORKBENCH_ACCEPTANCE_BASE_URL="https://workbench.customer.internal"
export WORKBENCH_PROBE_PSQL_DSN="postgresql://<只读账号>:<口令>@<主机>:5432/<库名>"
export WORKBENCH_PROBE_APP_CONTAINER="<app容器名>"
export WORKBENCH_PROBE_WORKER_CONTAINER="<worker容器名>"
export WORKBENCH_PROBE_BEAT_CONTAINER="<beat容器名>"

python scripts/customer_acceptance_probe.py | tee acceptance-probe.txt
# 回传：acceptance-probe.txt 的内容（凭据已由脚本遮蔽为 scheme://***@host）
```

| 参数 | 作用 |
| --- | --- |
| `--image` / `WORKBENCH_APP_IMAGE` | 受检镜像引用（判 `latest` / 无标签 / 5 个 OCI 标签） |
| `--base-url` / `WORKBENCH_ACCEPTANCE_BASE_URL` | 应用入口；**必须 https 且非本地**（仅联调可加 `--allow-insecure` / `--allow-local`） |
| `--app-container` / `--worker-container` / `--beat-container`（或 `WORKBENCH_PROBE_*_CONTAINER`） | 容器名 |
| `--psql-dsn` / `WORKBENCH_PROBE_PSQL_DSN` | **只读**连接串（不写入报告） |
| `--runtime-events-table` / `WORKBENCH_PROBE_RUNTIME_EVENTS_TABLE` | 运行事件表名（默认 `workbench_runtime_events`） |
| `--retention-days` / `WORKBENCH_RUNTIME_EVENTS_RETENTION_DAYS` | 保留期天数（默认 30） |
| `--concurrency` / `WORKBENCH_WORKER_CONCURRENCY` | worker 并发（默认 2，用于算连接账目预算） |
| `--timeout` | 单请求超时秒数（默认 10） |

- **退出码**：`0` = 全部通过或跳过；`1` = 存在不通过；`2` = 参数或配置错误（护栏 fail-closed：http / 本地目标在未显式放行时直接拒绝执行）。
- **口径**：核对不到的环境（无 docker 守护进程、无只读 DSN、容器不存在、表不存在）一律显式 `skipped` **并写明原因**，**绝不静默通过**；`skipped` 项必须在回传里登记为「未验证」。
- **不做**：本脚本不覆盖 §2.5（渠道接入与真实触发——必须人工取得渠道侧证据），也不做任何写操作。

---

## 4. 回传模板

把下面模板填好（**凭据用 `***` 替换**）连同命令输出原文一起回传：

```
# 客户侧交付验收回传
- 客户 / 环境：<客户名 / staging / 生产>
- 执行人：<姓名 + 角色>        执行时间：<YYYY-MM-DD HH:MM TZ>
- 执行主机：<主机名 + 系统 + 架构（如 Ubuntu 22.04 x86_64）>
- 产物版本：<WORKBENCH_APP_IMAGE 标签>        镜像构建编号（revision）：<git rev-parse HEAD>
- 探针报告：<粘贴 python scripts/customer_acceptance_probe.py 的完整输出>

## 逐项结论（结论只允许 pass / fail / skipped）

| # | 检查项 | 结论 | 证据原文（命令 + 关键输出） | 未通过项说明 |
| --- | --- | --- | --- | --- |
| 1 | 镜像引用与 5 个 OCI 标签（version/revision 非 dev/unknown，禁 latest） | | `docker image inspect ...` 输出 | |
| 2 | 三服务容器日志上限（json-file / 10m / 5） | | `docker inspect ... LogConfig` 输出 | |
| 3 | 应用健康（/api/v1/health） | | HTTP 码 + 响应体 | |
| 4 | worker healthcheck | | State.Health 原文 | |
| 5 | beat 是否在派发 | | grep 到的派发行原文 | |
| 6 | PostgreSQL 连接数与上限（≥100、使用率 ≤80%、账目 38+2×并发+1） | | SQL 输出 | |
| 7 | 监控告警 9 条是否接入渠道 | | 上表（§2.5 A）逐条填写 | |
| 8 | 真实告警触发一次（渠道确已收到） | | 告警 ID / 时间戳 | |
| 9 | 运行事件表体量与最早/最晚时间 + 保留期实际取值 | | SQL 三列 + 保留期配置值 | |
| 10 | 审计表可读性与最新时间（不删除口径） | | SQL 输出 | |

## 跳过项（必须登记为「未验证」，不得读成通过）
- <检查项>：<为什么核对不到>

## 未执行 / 未验证
- 并发压测（会写数据）：未执行 / 已授权执行（贴口径与结果）
- 迁移与回滚演练、密钥轮换：未执行（另行授权）
- 其它：
```

**判读规则（AI 侧同口径）**：① 只有 `pass` 能进「通过」列；② `skipped` 与「未执行」一律进「未验证」；③ 任一项 `fail` 先定位再往下，**不得**用「先上线、回头再看」带过；④ 判读结论回写 `docs/delivery-readiness-checklist.md`，本手册不另立状态。

---

## 5. 明确排除（会写数据 / 改配置，另行授权后再跑）

| 动作 | 为什么不能放进只读轮次 |
| --- | --- |
| **首次起栈 / 版本更新**（`docker build`、`docker compose up -d`、`--force-recreate`） | 会创建镜像与容器；`app` 启动即 `apply_migrations`，**会改库结构** |
| **`docker restart` / `stop` / `exec` / `rm`** | 会改变运行态或进程内状态 |
| **`docker push` / `docker pull`** | 推镜像出本机 / 覆盖本地镜像引用 |
| **执行迁移**（`psql -f migrations/*.sql`、启动应用触发迁移） | 改库结构 |
| **回滚 / 恢复演练**（`scripts/migration_backup_drill.py` 等） | 会创建恢复库并执行迁移 |
| **密钥轮换**（`scripts/secret_rotation_drill.py` 等） | 会轮换密钥；轮换备份加密密钥还会使既有 TOTP 种子不可解 |
| **并发 / 幂等压测**（`scripts/staging_concurrency_probe.py`） | 三个场景都会发 `POST` |
| **桌面端更新演练**（`scripts/desktop_update_drill.py`） | 会触发更新演练 |
| **任何 `POST` / `PUT` / `PATCH` / `DELETE` 接口**（含死信重放、审批、导出/删除申请） | 写操作 |
| **为凑数据改系统时钟 / 塞满磁盘 / 停服务来触发告警** | 破坏性触发；告警验证只允许用安全方式（见 §2.5 B） |

---

## 6. 未验证登记（本手册自身）

1. **客户侧 / 生产拓扑未验收**：本手册尚未在客户环境执行；仓库内的实测数据来自本机容器演练（Windows 宿主 + Docker Desktop），**不替代客户侧压测**。
2. **监控告警渠道未接入任何环境**：9 条规则已成文，**无真实触发证据** ⇒ 本项按「未验收」处理。
3. **运行事件保留期未在客户侧验证**：迁移 `034_runtime_events.sql` 与保留期任务属本轮新落地资产；**保留期清理是否在客户侧真实按周期运行**，须以 §2.3 ③' 与 §2.6 的实测值为准。
4. **镜像标签的客户侧取值未验证**：仓库侧的标签守护只覆盖 `Dockerfile` 静态契约与一次本机构建取证；**未推任何镜像仓库、未在客户环境按版本标签起栈**。
5. **CI 不覆盖容器编排路径**：`ci.yml` 无 compose job ⇒ 镜像标签 / 日志上限 / 连接账目**仍只有本机演练与本手册的客户侧回传作证据**。
