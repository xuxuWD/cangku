# 站内通知（收件箱）设计 · 口径草稿（待确认）

> **状态**：**草案，待确认**。确认后才进入实现（先写失败测试，再写实现）。
> **日期**：2026-09-11　**基线**：`main`（后端 1038 项测试通过，CI 已接入并实跑通过）

## 1. 目标与非目标

**目标**：让「需要等待结果的人」在系统内被明确告知结果，不再依赖口头同步或反复刷新页面。
README 已声明工作台「统一承载…通知」，当前仅实现**死信运维通知渠道**（`app/notifications.py` → Webhook），**面向员工的业务通知未实现**；本设计补齐这一块。

**非目标（明确不做）**：

| 不做 | 原因 |
| --- | --- |
| Web Push / 短信 / 邮件 | 需 HTTPS 域名 + VAPID 密钥或第三方通道，属外部资源（已登记的阻塞项） |
| 经 Outbox/Redis 异步投递 | Outbox + Worker 链路**从未在真实环境跑通**，把通知挂在未验收链路上不可靠 |
| 通知偏好设置（订阅/免打扰） | 无产品口径；先做「全量记录 + 未读」，偏好后置 |
| 在通知里携带驳回原因/客户原文 | 避免把可能的敏感内容复制进收件箱（与审计脱敏纪律一致） |

## 2. 命名（避免与既有模块冲突）

现有 `app/notifications.py` 已被**死信外发通知**占用（`NotificationChannel`/`DeadLetterNotifier`，唯一调用点 `app/bootstrap.py:271-280`）。因此本功能统一使用 **inbox（收件箱）** 词汇：

- 模块 `app/inbox.py`；表 `workbench_inbox_items`；接口前缀 `/api/v1/inbox`；服务 `InboxService`。

## 3. 触发事件与接收人（核心口径）

**接收人一律是「等待结果的人」**（发起人/申请人），**不是审批人**（审批人有既有「待我审批」聚合接口）。

| # | 事件 | 触发点（既有代码） | 接收人 | Phase |
| --- | --- | --- | --- | --- |
| E1 | 任务审批**通过** | `PostgresTaskRepository.approve` / `TaskStore.approve` | 任务创建人 `task.created_by` | 1 |
| E2 | 计划提案**通过 / 驳回** | `PlannerService.approve` / `reject` | 提案发起人 `proposal.created_by` | 1 |
| E3 | 编排优化提案**通过 / 驳回** | `OrchestrationProposalService.approve` / `reject` | 提案发起人 `created_by` | 1 |
| E4 | 内容发布失败转**人工接管** | `PublicationService.publish`（`status=manual_takeover`） | 内容负责人 `ContentRecord.created_by` | 1 |
| E5 | 运行**失败** | 运行终态落盘处（`run_metrics` 终态集合含 `failed`） | 任务创建人（`run_id → task_id → task.created_by` 反查） | 1 |
| E6 | 注册申请**批准** | `AccountService.approve` | 申请人本人（`account_id`） | 1 |
| E7 | 注册申请**驳回** | `AccountService.reject` | ~~申请人~~ → **不做站内通知**（见下） | — |

**两条必须如实说明的事实**：

1. **E7 不做站内通知**：被驳回的账号 `status=rejected` **无法登录**，站内通知他看不到。驳回结果仍只写审计（已有 `account.registration.rejected`）；将来若做邮件/短信再补。
2. **任务没有「驳回」动作**：任务状态机只有 `queued / pending_approval / cancelled`，故只有 E1（通过）。
3. **运行类通知需反查**：`RunRecord` 无 `user_id` 字段，E5 必须经 `task_id → task.created_by` 定位接收人；任务不存在时**跳过通知并记一条审计**，不猜接收人。

## 4. 数据模型（迁移 `019_inbox_items.sql`）

```sql
CREATE TABLE IF NOT EXISTS workbench_inbox_items (
    inbox_id     TEXT PRIMARY KEY,
    tenant_id    TEXT NOT NULL,
    recipient_id TEXT NOT NULL,           -- 接收人 user_id（申请人场景为 account_id）
    kind         TEXT NOT NULL,           -- 事件类型，见 §5 枚举
    title        TEXT NOT NULL,           -- 服务端按固定模板生成，不含客户原文/手机号
    target_type  TEXT,                    -- task / plan_proposal / orchestration_proposal /
                                          -- publication / run
    target_id    TEXT,                    -- 供客户端跳转，不做联表
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at      TIMESTAMPTZ              -- NULL = 未读
);
CREATE INDEX IF NOT EXISTS idx_workbench_inbox_items_recipient
    ON workbench_inbox_items (tenant_id, recipient_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_workbench_inbox_items_unread
    ON workbench_inbox_items (tenant_id, recipient_id, read_at);
```

**刻意不做的字段**：不存 `detail` JSON、不存事件正文、不存手机号 —— 收件箱只承载「发生了什么 + 去哪看」，避免把敏感内容二次落库。

## 5. 接口契约（新增，须同步 `docs/api-contract.md`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/inbox?unread_only=&limit=` | 只返回**本人**通知；`limit` 默认 50、范围 1–200（越界 422）；按 `created_at DESC`；返回 `{items, unread_count}` |
| `POST` | `/api/v1/inbox/{inbox_id}/read` | 标记已读；**他人/跨租户/不存在统一 404**（不泄露存在性）；重复标记幂等返回 200 |
| `POST` | `/api/v1/inbox/read-all` | 标记本人全部未读为已读，返回 `{updated}` |

- 权限：仅 `current_user` 本人；无管理员越权读他人收件箱的接口。
- 未读定义：`read_at IS NULL`。
- `kind` 枚举（服务端固定字面量）：`task.approved`、`plan.approved`、`plan.rejected`、`orchestration.approved`、`orchestration.rejected`、`publication.manual_takeover`、`run.failed`、`account.registration.approved`。

## 6. 写入时机与失败策略（需你确认）

- **时机**：业务状态变更**成功之后**同步写一条通知（不加唯一约束——状态机已保证同一目标只成功变更一次）。
- **失败策略**：通知写入失败**不阻断业务**，但必须**写一条审计** `inbox.write_failed`（可观测的降级，不静默吞掉）。
  - 备选（更严）：写入失败即业务失败（把通知变成关键路径）——**不推荐**，审批被通知拖垮不划算。
  - 备选（更松）：失败只打日志——**违反**仓库既有「不静默」纪律，不采用。

## 7. 保留期与清理

- 默认保留 **90 天**，可配 `WORKBENCH_INBOX_RETENTION_DAYS`（范围 1–3650）。
- 清理方式：**写入时惰性删除过期行**（仿 `app/sessions.py` 的 `_purge`），不引入定时任务（Worker 链路未验收）。

## 8. 前端范围（Phase 1）

- **admin-web**：`AppShell.tsx` 的 `AppView` 增加 `'inbox'`，导航加「通知」入口（含未读数角标）；新增 `src/features/inbox/`（仿 `features/knowledgeAccess/` 的 page/api/types/state/test 结构）；点击通知按 `target_type/target_id` 跳转到对应页面（任务/提案走既有 `view` 路由）。
- **companion-pwa**：在既有轮询里叠加未读通知（复用 `usePendingApprovals` 的间隔策略：默认 30s、页面隐藏暂停、401 触发会话过期处理）；待办与通知分两个区块展示。

## 9. 测试计划（先写测试，后写实现）

| 层次 | 覆盖 |
| --- | --- |
| 仓储双实现 | 内存 + PostgreSQL（`RecordingConnection` 假连接）：写入、按接收人过滤、未读过滤、跨租户/他人不可见、标记已读幂等、惰性清理 |
| 服务层 | 事件→接收人映射逐条断言；E5 任务不存在时跳过并记审计；写入失败时业务仍成功且写了 `inbox.write_failed` |
| 接口层 | 列表/标记/全部已读的状态码矩阵；**跨租户与他人通知一律 404**；未登录 401；`limit` 越界 422 |
| 契约守护 | 新增路由必须出现在 `docs/api-contract.md`（既有 `test_api_contract_coverage.py` 守护）；迁移清单与 `.env.staging.example` 一致（既有 `test_staging_assets.py` 守护） |
| 前端 | `admin-web` 收件箱页（空态/加载/错误/未读角标/跳转）、`api.test.ts`；`companion-pwa` 通知区块与轮询 |

## 10. 风险与已知限制（实现后需如实登记）

1. 通知为**同步写入**：若数据库瞬时不可用，业务成功但通知丢失（有审计 `inbox.write_failed` 可查，无自动补发）。
2. 收件箱**只在系统内可见**：用户不登录就看不到（Web Push 属外部依赖，未做）。
3. 驳回类结果（注册驳回）**不产生站内通知**（接收人无法登录）。
4. 运行失败通知依赖 `task_id → created_by` 反查；任务已删除时不发通知（记审计）。

## 11. 待你确认的决策点

| # | 决策 | 我的建议 |
| --- | --- | --- |
| D1 | 事件范围是否含 E4（内容发布转人工接管）与 E5（运行失败） | 都纳入（这两类是"人必须接手"的场景） |
| D2 | 通知写入失败策略 | 不阻断业务 + 写审计 `inbox.write_failed` |
| D3 | Phase 1 前端是否两端都做 | 两端都做（后端接口一致，伴侣端复用轮询） |
| D4 | 保留期默认 90 天 | 采用；如需与 `retention_policy`（tasks 180/audit 730）对齐可改 |
| D5 | 是否引入 `WORKBENCH_INBOX_RETENTION_DAYS` 配置项 | 采用（有默认值，不新增部署必填项） |

## 12. 落地清单（确认后执行）

1. 迁移 `019_inbox_items.sql` + `.env.staging.example` 迁移清单登记（否则 `test_staging_assets.py` 失败）。
2. `app/inbox.py`（`InboxItem` / `InboxKind` / `InboxStore` 双实现 / `InboxService`）+ `InboxWriteFailed` 审计登记（`AuditAction` 与 `ALLOWED_DETAIL_KEYS`）。
3. 装配：`app/bootstrap.py` 新增 `build_inbox_service(...)`；`app/main.py` 三个接口 + 在 E1–E6 各触发点挂钩子。
4. `docs/api-contract.md` 新增章节；`docs/delivery-gates.md`（新门禁「站内通知」）与 `docs/delivery-readiness-checklist.md` 同步。
5. 前端两处 + 测试；`README.md` 的「通知」口径由「仅死信运维通知渠道」更新为「+ 站内通知」。
6. 全量回归（`pytest` + `compileall` + 前端 vitest + 桌面 node --test），CI 实跑确认。
