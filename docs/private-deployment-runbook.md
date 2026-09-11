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
8. 管理员账号必须先绑定动态口令（TOTP）才能获得完整会话：`WORKBENCH_REQUIRE_ADMIN_TOTP` 为真时，未绑定的 `super_admin` / `ceo` 登录只拿到受限会话（仅可完成绑定），绑定完成后重新登录才签发 `full` 范围令牌。用户更换设备或丢失验证器时，由超级管理员通过 `POST /api/v1/auth/accounts/{account_id}/totp-reset` 清除绑定后重新绑定。

Staging 验收按 [`docs/staging-acceptance-checklist.md`](staging-acceptance-checklist.md) 执行；缺少任一前置条件时停止，不以本地演练替代。

## 容器化部署

1. 构建应用镜像：`docker build -t workbench-app .`。
2. 与基础设施编排一起启动：`docker compose -f docker-compose.yml -f docker-compose.app.yml up -d`。应用容器以生产模式启动时会自动应用 `migrations/` 下的迁移。
3. 密钥只允许通过环境变量注入。编排文件用 `:?` 强制要求 `WORKBENCH_AUTH_SECRET`、`WORKBENCH_BACKUP_ENCRYPTION_KEY`、`WORKBENCH_BOOTSTRAP_TOKEN` 和数据库口令，缺失任一项即启动失败；`.dockerignore` 排除全部环境文件，镜像内不得存在任何密钥。
4. 容器以非 root 用户运行，健康检查走 `/api/v1/health`。
5. 本仓库的容器化资产只完成**静态校验**；真实镜像构建、容器启动与健康检查**尚未在具备 Docker 的环境中验收**，不得据此宣称已容器化交付。

## 迁移与备份

1. 迁移前暂停写入任务，记录当前应用版本、数据库迁移清单和 Runtime 固定版本。
2. 对数据库执行一致性备份，对对象存储创建版本化清单；备份文件使用独立的备份加密密钥加密。
3. 在隔离数据库先执行迁移和应用启动检查，确认迁移清单与 `migrations/` 一致。商业化持久化会自动应用 `migrations/001` 至 `015`，生产模式不允许内存回退。
4. 生产迁移完成后执行健康检查、租户读取、任务创建/取消和商业化读取的冒烟测试。
5. 任何失败均停止后续迁移，不在原数据库直接试错。

本地已完成一次临时 PostgreSQL 的迁移、商业化读写、`pg_dump` 导出及恢复到新数据库的演练；该结果不替代客户 staging 数据库、恢复窗口和客户管理员验收。

## 异步链路：Worker、Outbox 与死信

1. **启动 Worker**：`celery -A app.worker:celery_app worker --loglevel=INFO`。非 `development` 环境启动时会自动装配 Outbox 发布器（`configure_runtime`），并按 beat 计划（`app.worker` 中的 `outbox-publisher`，默认 15 秒）周期调用 `publish_pending` 发布 `workbench_event_outbox` 中未发布的记录。
2. **Outbox 重试**：单条记录发布失败时 `attempts` 加一并写入 `last_error`，成功后才置 `published_at`；达到 `WORKBENCH_OUTBOX_MAX_ATTEMPTS`（1 至 20 的正整数）后转入死信，不再自动重试。
3. **死信登记与人工重放**：死信写入 `workbench_dead_letters`。CEO 或超级管理员可用 `GET /api/v1/dead-letters` 查看本租户死信（含 `notified_at`，用于判断是否已发出通知），用 `POST /api/v1/dead-letters/{event_id}/replay` 人工重放；重放会再次发布事件并把 `replayed_at` / `replayed_by` 落库，重复重放返回 `already_replayed`。
4. **死信通知渠道配置**：设置 `WORKBENCH_DEAD_LETTER_WEBHOOK_URL` 后，死信登记会对该事件**去重通知一次**（`notified_at` 由空变为非空时才发送），超时由 `WORKBENCH_DEAD_LETTER_WEBHOOK_TIMEOUT_SECONDS`（1 至 30 秒，默认 5）控制；以 JSON POST 发送。**未配置该地址时不发送任何通知**，行为与未接入通知渠道时一致。
5. **通知失败的处理**：Webhook 请求失败（含非 2xx）**不会向上抛出、不会重试、不会打断 Outbox 发布循环**，只在审计中记录 `dead_letter.notification_failed`；成功发送记录 `dead_letter.notified`。因此通知失败时死信本身仍完整保留，可人工排查渠道后处理。
6. **通知载荷约定**：载荷固定字段为 `kind`、`event_id`、`tenant_id`、`action`、`aggregate_type`、`aggregate_id`、`attempts`、`error`、`occurred_at`。**绝不包含事件的 `payload`**；`error` 会截断到 200 字符，并把 `scheme://user:pass@host` 形式的凭证替换为 `scheme://***@host`。Webhook 地址与超时从环境变量注入，不得写入镜像或代码。

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
