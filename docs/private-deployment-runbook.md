# 私有部署 G0 交付运行手册

## 适用范围

本手册适用于公司内部版和客户私有部署版的首批交付。它不代表 SaaS 自动开通、在线支付或全托管生产服务已经就绪。部署前必须先通过预检；任何 `fail` 或 `blocked` 结果均不得上线。

## 部署前确认

1. 为每个客户准备独立 PostgreSQL 数据库、对象存储命名空间、Redis 逻辑库或独立实例，以及独立的认证密钥和备份加密密钥。
2. 配置 `WORKBENCH_ENV` 为非 `development`，并使用 PostgreSQL 持久化仓储；不能回退到内存模式。
3. 将 Runtime 记录为固定版本或不可变镜像摘要。禁止使用 `latest`、`main` 或未固定版本。
4. 配置数据保留策略。任务与审计保留天数必须是正整数，并写入客户交付记录。
5. 配置 `WORKBENCH_OUTBOX_MAX_ATTEMPTS`，取值为 1 到 20 的正整数，并写入交付记录。
6. 运行 `python scripts/commercial_g0_preflight.py`。预检会校验非开发环境、PostgreSQL 存储、认证密钥、备份密钥及两者隔离；输出不得包含数据库密码、备份密钥、Cookie、令牌或原始 API 密钥。
7. 隔离 staging 环境按 `.env.staging.example` 登记独立 PostgreSQL、Redis、对象存储、staging 租户和测试账号后，运行 `python scripts/staging_preflight.py`；预检会聚合基础设施隔离、商业化 G0 和外部 Runtime 元数据校验，必须为 `pass` 才能执行跨租户测试、并发压测、沙箱验证和真实外部服务联调。
8. 管理员账号必须先绑定动态口令（TOTP）才能获得完整会话：`WORKBENCH_REQUIRE_ADMIN_TOTP` 为真时，未绑定的 `super_admin` / `ceo` 登录只拿到受限会话（仅可完成绑定），绑定完成后重新登录才签发 `full` 范围令牌。用户更换设备或丢失验证器时，由超级管理员通过 `POST /api/v1/auth/accounts/{account_id}/totp-reset` 清除绑定后重新绑定。**动态口令种子在数据库中一律以密文存储**（AES-256-GCM；子密钥由 `WORKBENCH_BACKUP_ENCRYPTION_KEY` 经 HKDF-SHA256 派生，密文带 `v1:` 前缀）；因此**轮换备份加密密钥会使既有种子不可解**——轮换前须先用 `super_admin` 重置相关账号的动态口令，再完成轮换。

Staging 验收按 [`docs/staging-acceptance-checklist.md`](staging-acceptance-checklist.md) 执行；缺少任一前置条件时停止，不以本地演练替代。

## 容器化部署

1. 构建应用镜像（**带版本号与构建编号，产物可追溯**——宪法 §6.3）：`docker build --build-arg WORKBENCH_IMAGE_VERSION=$(git describe --tags --always) --build-arg WORKBENCH_IMAGE_REVISION=$(git rev-parse HEAD) -t workbench-app:$(git describe --tags --always) .`
   - 构建后核对标签：`docker image inspect <镜像> --format '{{json .Config.Labels}}'` 应含 `org.opencontainers.image.version` 与 `org.opencontainers.image.revision`（Dockerfile 的 `ARG`/`LABEL` 由 `tests/test_container_assets.py` 守护；`dev`/`unknown` 是未注入参数的默认值，**不算正式版本**）。
   - 起栈必须用同一标签：`WORKBENCH_APP_IMAGE=workbench-app:<版本> docker compose -f docker-compose.yml -f docker-compose.app.yml up -d --no-build`。**不显式给 `WORKBENCH_APP_IMAGE` 时编排回落到 `workbench-app`（即 `:latest`）——正式交付禁止**（与「部署前确认」第 3 条「禁止 `latest`」同口径）。
2. 与基础设施编排一起启动：`docker compose -f docker-compose.yml -f docker-compose.app.yml up -d`。应用容器以生产模式启动时会自动应用 `migrations/` 下的迁移。
   - 该编排起**三个服务**（同镜像、不同 command）：`app`（HTTP 入口，**唯一跑迁移**）、`worker`（Celery 执行：Outbox 发布 / 商业化生命周期作业 / **知识治理到期扫描**）、`beat`（Celery 调度，**独立进程**，见「异步链路」章）。
   - **不得把 beat 合回 worker**（`celery worker -B` 内嵌）：Windows 上 Celery 直接拒绝，生产也不推荐单点耦合；本仓库 `tests/test_compose_worker_assets.py` 会守护这一点。
   - `beat` 的排程文件落命名卷 `workbench-celerybeat`（容器重建不丢调度状态）；镜像内已预建并授权 `/var/lib/celery`，非 root 用户才写得进。
3. 密钥只允许通过环境变量注入。编排文件用 `:?` 强制要求 `WORKBENCH_AUTH_SECRET`、`WORKBENCH_BACKUP_ENCRYPTION_KEY`、`WORKBENCH_BOOTSTRAP_TOKEN`、**`WORKBENCH_EMBEDDING_BASE_URL`（P3 记忆层的本地 embedding 服务地址，生产必填——缺失即启动失败）** 和数据库口令，缺失任一项即在 compose 阶段显式报错（fail-closed，不会以「容器反复重启」的形式出现）；`.dockerignore` 排除全部环境文件，镜像内不得存在任何密钥。
4. 容器以非 root 用户运行，健康检查：`app` 走 `/api/v1/health`；`worker` 用 `celery -A app.worker inspect ping`（经 Redis broker 探活）。
5. **验收状态**：容器化资产已完成**静态校验**（`tests/test_compose_worker_assets.py`）与**一次本机容器演练**（2026-09-15）：`app` / `worker` / `beat` 三服务与基础设施（Postgres / Valkey / SeaweedFS）正常启动，`app` 健康检查 `{"status":"ok"}`、`worker` 经 broker `inspect ping` 报告 healthy、`beat` 按排程持续派发（`Sending due task knowledge-review-scan`）、到期文档被置 `needs_review` 且审计落 `system:worker`。**2026-09-16 追加本机取证**（独立 compose project + 独立端口，演练后已 `down -v` 清理）：① 镜像按上条方式**带版本标签**构建并 `docker image inspect` 核对；② 三个服务的容器日志上限（`json-file` / `max-size=10m` / `max-file=5`）经 `docker inspect` 实查生效；③ `beat` 三类排程（outbox-publisher / lifecycle-jobs / knowledge-review-scan）均派发并被 `worker` 执行；④ 扫描链路审计真实落 PostgreSQL（4 轮 × 400 篇 ⇒ `workbench_audit_log` 共 1600 行、actor=`system:worker`）；⑤ 容量测算与连接账目、监控与告警规则分别见「容量与并发」「监控与告警」两章。**仍未验收**：客户侧 / 生产拓扑（Linux 宿主、客户网络与凭据）与**监控告警渠道接入**（规则已成文，未接任何渠道）；容量数据为本机实测，**不替代客户侧压测**。因此**不得据此宣称已容器化交付**。

## 迁移与备份

1. 迁移前暂停写入任务，记录当前应用版本、数据库迁移清单和 Runtime 固定版本。
2. 对数据库执行一致性备份，对对象存储创建版本化清单；备份文件使用独立的备份加密密钥加密。
3. 在隔离数据库先执行迁移和应用启动检查，确认迁移清单与 `migrations/` 一致。商业化持久化会自动应用 `migrations/001` 至 `018`，生产模式不允许内存回退。
4. 生产迁移完成后执行健康检查、租户读取、任务创建/取消和商业化读取的冒烟测试。
5. 任何失败均停止后续迁移，不在原数据库直接试错。

本地已完成一次临时 PostgreSQL 的迁移、商业化读写、`pg_dump` 导出及恢复到新数据库的演练；该结果不替代客户 staging 数据库、恢复窗口和客户管理员验收。

## 异步链路：Worker、Outbox 与死信

1. **启动 Worker + Beat（两个进程）**：
   - **Worker**：`celery -A app.worker worker --loglevel=INFO`（容器编排即 `worker` 服务）。非 `development` 环境启动时会自动装配（`configure_runtime`）：Outbox 发布器、商业化生命周期执行层、**知识治理到期扫描器**。
     - **连接池在任务进程内装配**（fork 安全，2026-09-15 修复）：worker 主进程**不建** psycopg 连接池，池由真正执行任务的进程首次调用时建立 ⇒ Celery 默认 prefork、`threads`、`solo` 三种池都可用；旧问题（prefork 下所有周期任务抛 `PoolTimeout`，文档静默卡住）已不复现。因此**不要**为了绕过池问题而强行改 `--pool`。
     - 首次任务调用时才建池 ⇒ 启动后**第一个周期任务会稍慢**（建池），属正常。
   - **Beat**：`celery -A app.worker beat --loglevel=INFO --schedule=/var/lib/celery/beat-schedule`（容器编排即 `beat` 服务）。**必须独立进程**，不得用 `celery worker -B`（Windows 上 Celery 直接拒绝；生产也不推荐把调度与执行耦在一个进程）。排程文件必须落在**可写且持久**的路径（容器里是命名卷），否则容器重建后可能重复派发或漏发。
   - **起 beat 才会跑周期任务**：只起 worker 时，`outbox-publisher` / `lifecycle-jobs` / `knowledge-review-scan` 都**不会**被派发——这是「任务没跑」类问题首先要看的一处。
2. **Outbox 重试**：单条记录发布失败时 `attempts` 加一并写入 `last_error`，成功后才置 `published_at`；达到 `WORKBENCH_OUTBOX_MAX_ATTEMPTS`（1 至 20 的正整数）后转入死信，不再自动重试。
3. **死信登记与人工重放**：死信写入 `workbench_dead_letters`。CEO 或超级管理员可用 `GET /api/v1/dead-letters` 查看本租户死信（含 `notified_at`，用于判断是否已发出通知），用 `POST /api/v1/dead-letters/{event_id}/replay` 人工重放；重放会再次发布事件并把 `replayed_at` / `replayed_by` 落库，重复重放返回 `already_replayed`。
4. **死信通知渠道配置**：设置 `WORKBENCH_DEAD_LETTER_WEBHOOK_URL` 后，死信登记会对该事件**去重通知一次**（`notified_at` 由空变为非空时才发送），超时由 `WORKBENCH_DEAD_LETTER_WEBHOOK_TIMEOUT_SECONDS`（1 至 30 秒，默认 5）控制；以 JSON POST 发送。**未配置该地址时不发送任何通知**，行为与未接入通知渠道时一致。
5. **通知失败的处理**：Webhook 请求失败（含非 2xx）**不会向上抛出、不会重试、不会打断 Outbox 发布循环**，只在审计中记录 `dead_letter.notification_failed`；成功发送记录 `dead_letter.notified`。因此通知失败时死信本身仍完整保留，可人工排查渠道后处理。
6. **通知载荷约定**：载荷固定字段为 `kind`、`event_id`、`tenant_id`、`action`、`aggregate_type`、`aggregate_id`、`attempts`、`error`、`occurred_at`。**绝不包含事件的 `payload`**；`error` 会截断到 200 字符，并把 `scheme://user:pass@host` 形式的凭证替换为 `scheme://***@host`。Webhook 地址与超时从环境变量注入，不得写入镜像或代码。
7. **知识治理到期扫描（`knowledge-review-scan`）**：beat 按 `WORKBENCH_KNOWLEDGE_REVIEW_SCAN_INTERVAL_SECONDS`（默认 3600 秒，范围 30–604800）派发 `app.worker.scan_knowledge_review_due`，把 `published` 且已过 `review_due_at` 的文档置 `needs_review`（发布即置首轮到期 = 发布时刻 + `WORKBENCH_KNOWLEDGE_REVIEW_GRACE_DAYS`，默认 30 天）；审计按租户逐条记 `knowledge.doc.review_due`，actor 为 `system:worker`。
   - **验证（无需等真实到期）**：把某篇文档的 `review_due_at` 拨到过去（`UPDATE workbench_knowledge_documents SET review_due_at = now() - interval '1 hour' WHERE tenant_id = '<租户>' AND document_id = '<文档>'`），下一个 beat 周期后应见 `status` 变 `needs_review`、`workbench_audit_log` 出现 `system:worker` 的 `knowledge.doc.review_due` 行；再次周期 `candidates=0`（幂等）。
   - **排查顺序**：① `docker compose logs beat | grep knowledge-review-scan`（有没有派发）→ ② `docker compose logs worker | grep scan_knowledge_review_due`（有没有执行、返回的 `candidates/flipped`）→ ③ 查库看 `status` 与审计。**只起 worker 不起 beat 时不会派发**（见第 1 条）。
   - **interval 一致性**：该间隔由 **beat** 侧读取（`create_celery_app` 建排程表），worker 与 beat 两个服务必须配同一个值（编排里已对齐，`tests/test_compose_worker_assets.py` 守护）。
   - **审计缺失即失败**：装配未注入审计通道时，扫描会 fail-closed 抛错（任务显式失败、日志可见），不会静默置位而留不下审计（规格 §4 N7）——看到这类失败先检查 worker 的审计装配，不要「修」成静默跳过。

## 监控与告警

**状态声明**：以下是**规则与阈值**（依据 2026-09-16 本机容器演练实测）；**告警渠道尚未接入任何环境** ⇒ 本项按「未验收」处理，不得读作「已接监控」（渠道接入 + 一次真实触发验证完成后，才在 `docs/delivery-readiness-checklist.md` 改口径）。

| # | 信号 | 判定（默认阈值） | 为什么是它 / 实测依据 |
| --- | --- | --- | --- |
| 1 | **beat 是否在派发** | 日志中 `Sending due task` 断档 ≥5 分钟 ⇒ 告警 | 调度停 ⇒ 周期任务全停（Outbox 不发布、生命周期作业与到期扫描不跑）。实测 `outbox-publisher` 每 15s 派发一次（5 分钟 = 20 个周期） |
| 2 | **worker 容器健康** | healthcheck（`celery -A app.worker inspect ping --timeout 10`，interval 30s / retries 3）转 `unhealthy` ⇒ 告警 | 覆盖「worker 挂死但容器还在」；编排内置探活（见「容器化部署」第 4 条） |
| 3 | **app 健康** | `GET /api/v1/health` 非 200 或超时 ⇒ 告警 | HTTP 入口存活；演练实测 `{"status":"ok"}` |
| 4 | **Outbox 积压** | `SELECT count(*) FROM workbench_event_outbox WHERE published_at IS NULL` 连续 2 个派发周期（约 30s）不下降 ⇒ 告警 | 单周期批上限 100（`publish_pending(limit=100)`）、beat 每 15s ⇒ 稳态每周期清零；不为零即「消费跟不上生产」 |
| 5 | **死信新增** | `workbench_dead_letters` 出现 `replayed_at IS NULL` 的新行 ⇒ 告警 | 死信 = 重试到 `WORKBENCH_OUTBOX_MAX_ATTEMPTS` 仍失败；可先接已有的脱敏 webhook（`WORKBENCH_DEAD_LETTER_WEBHOOK_URL`，见「异步链路」第 4 条） |
| 6 | **审计是否在落** | 有业务流量时 `SELECT max(occurred_at) FROM workbench_audit_log` 长时间不推进 ⇒ 告警 | 审计是合规证据；演练实测扫描链路 4 轮共落 1600 行（actor=`system:worker`）。阈值按客户业务节奏定并写入客户交付记录 |
| 7 | **宿主磁盘** | 使用率 ≥80% 预警、≥90% 严重 | 容器日志已设上限（`json-file` / `max-size=10m` / `max-file=5`，三服务，2026-09-16 `docker inspect` 实查生效），但备份、对象存储与数据库仍会增长 |
| 8 | **PostgreSQL 连接数** | 使用率 >80%（`max_connections=100` 时即 >80 条）⇒ 告警 | 见「容量与并发」的连接账目（稳态 = 38 + 2×并发 + 1） |
| 9 | **worker 资源** | 单容器 RSS 持续 >512MiB ⇒ 告警 | 实测峰值 206.3MiB（并发 4）；阈值取最高实测的 ≈2.5 倍——先告警、人工判断，**不自动重启** |

**接入方式（三选一，按客户环境定）**：① 客户既有监控平台（Prometheus / Zabbix / 云监控）按其承载方式落地上表规则；② 宿主侧轻量采集脚本 + 邮件或 webhook（可复用死信 webhook 的通知形态，注意载荷脱敏）；③ 云厂商容器 / 数据库自带的健康与容量告警。**无论选哪种，都要把「实际接入 + 一次真实触发验证」写入客户交付记录**——规则写在手册里不等于告警已生效。

## 容量与并发

**数据来源**：2026-09-16 本机容器演练（独立 compose project + 独立端口；播种 Outbox 600 条事件 + 2 租户 × 200 篇到期文档）。**本机数据不替代客户侧压测**（Linux 宿主、客户数据规模、PostgreSQL 参数与网络时延均不同）。

| 指标 | 实测值 |
| --- | --- |
| 扫描单任务（400 篇到期文档：逐条 flip + 逐条审计） | ≈**2.0–2.1s**（实测 2.0458s / 2.0846s，≈195 篇/s；并发 2 与并发 4 下同量级） |
| 扫描空转（0 候选，常态周期） | **2.6ms** |
| 发布单任务（100 事件批） | **0.067–0.121s**（并发 2）；**0.071–0.076s**（并发 4，6 条全部） |
| 冷启动首任务（建池 + 运行时装配） | **0.23–0.27s** |
| 600 条事件排空（墙钟，6 个发布任务同时派发） | 并发 2 ≈**0.27s**；并发 4 **157ms** |
| 全库连接峰值（含 app 启动即持有的 38 条 + 探针 1 条） | 并发 2 → **43**；并发 4 → **49**（PG `max_connections=100`） |
| worker 单容器 RSS | 并发 2：123.2 → **124.9 MiB**；并发 4：**206.3 MiB** |
| worker CPU（空闲） | **0.13%**（并发 2）/ **0.19%**（并发 4） |

**连接账目（决定 `max_connections`）**：稳态 = **38（`app` 启动即持——各 `build_*` 组件各自建池、`min_size=1` 累加）+ 2×并发（`worker` 每个任务子进程 2 个池：共享池 + 审计池）+ 1（运维 / 探针）**；负载下个别池会瞬态扩容（各池 `max_size=10`，实测峰值即上表 43 / 49）。**要求 `max_connections ≥ 100`**（默认值即可满足），使用率 >80% 时告警（见「监控与告警」第 8 条）。

**参数决定（2026-09-16，按实测数据调整）**：

1. **`--concurrency` 保留默认 2**（`WORKBENCH_WORKER_CONCURRENCY`）。生产排空节奏由 beat 决定（每 15s 一批、每批上限 100 条 ⇒ 上限 400 条/分钟），实测单批仅 0.07–0.24s ⇒ **worker 不是瓶颈**；并发 2 与并发 4 的单任务耗时同量级（并发只增加「同时能跑几个任务」，并发 4 仅在人工构造的 600 条瞬时负载下把墙钟从 ≈0.27s 压到 157ms，不构成生产收益）。
2. **新增 `--max-tasks-per-child`（默认 1000，`WORKBENCH_WORKER_MAX_TASKS_PER_CHILD`）**。不设上限时子进程寿命无限，第三方客户端若按任务泄漏内存，会在无人值守长跑中持续累积。实测单次重装配 ≈**0.26–0.27s**，beat 三类排程合计约 **8.6k 任务/天**（outbox 5760 + lifecycle 2880 + scan 24）⇒ 每天回收 2–4 次、总开销 <1.5s/天；收益是**内存增长有上界**。回收已实测：预算设 3 时派 10 个任务，子进程 PID 全部轮换（62164/62165/62166 → 62507/62518/62519）、**父进程（62102）不重启**；回收后首任务 ≈0.25–0.28s（重装配），热子进程同任务仅 0.0024–0.0038s。
3. **扩容信号**：① Outbox 连续 2 个周期未清零；② worker 单容器 RSS 持续 >512MiB；③ PostgreSQL 连接使用率 >80%。出现任一条先核上面账目，再按「升并发（连接数同步 +2/并发）」或「加 `worker` 副本」处理，**不静默改参数**。
4. **交付前必须在客户侧复测**：按 `docs/delivery-remaining-checklist.md` 组 1 的并发压测口径（`scripts/staging_concurrency_probe.py`）在 staging 执行；本机数据只用于「默认参数是否合理」的决策与本手册的阈值取值。

## 恢复与回滚

1. 恢复必须先在隔离数据库演练，验证备份可读、对象索引一致、租户隔离与审计可查询。
2. 恢复通过后，维护窗口内停止写入，将应用版本和数据库恢复到同一已验证组合。
3. 回滚只使用已演练的数据库备份和对象存储清单；禁止手工修改用量账本或审计记录。
4. 恢复完成后重新执行预检、冒烟测试和权限测试，并记录操作人、时间、原因和结果。

## 客户数据导出与删除

1. 导出和删除通过生命周期异步作业申请，不能在 HTTP 请求线程处理大批量数据。
2. 删除申请进入冷静期，最终导出完成且冷静期结束后才能执行。
3. 导出只交付客户授权范围内的元数据、产物引用、用量与审计；严禁包含密码、Cookie、验证码、令牌、原始 API 密钥和客户原文。
4. 删除后保留最小删除审计，不保留客户原文。删除、导出和恢复均须可追溯。

## 客户交接

1. 交付客户管理员清单、岗位能力包清单、知识库权限范围、Runtime 版本、数据保留策略和支持联系人。
2. 客户管理员只管理本租户；超级管理员权限必须单独登记、按需授权并可撤销。
3. 进行一次客户管理员验收：查看租户、查看用量、申请导出、申请删除后撤销或等待冷静期的流程演练。
4. 标注尚未通过真实验收的能力，尤其是第三方发布渠道、自动化浏览器协助、外部 Runtime 和 GEO 适配器。

## 支持升级

1. 事件、权限、迁移、备份或 Runtime 异常先创建审计工单并保留脱敏诊断编号。
2. 涉及越权、数据泄露、提示词注入或未知发布回执时，立即暂停相关任务与授权，转人工处理。
3. 任何客户数据问题不得要求客户上传密码、Cookie、验证码、浏览器会话或原始密钥。
4. 修复后需在隔离环境复现、增加测试、完成预检和验收记录后再恢复服务。
