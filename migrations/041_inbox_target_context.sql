-- 041_inbox_target_context.sql
-- S1 第三款：通知直达「该会话的该条卡」——`workbench_inbox_items` 增补两个**可空**的上文标识。
-- 依据：docs/api-contract.md「通知（收件箱）」；接缝出处
--       docs/superpowers/specs/2026-09-18-workbench-closed-loop-design.md §3（S1：通知点开直达该会话的该条卡）。
--
-- 约定：
--   * **只增列、不改既有列**：存量行为 `NULL` ⇒ 界面回落既有落点（按 `target_type/target_id` 打开任务 / 运行），零破坏；
--   * 只在**能从服务端权威链路反查出来**时写入（运行 → 幂等行 → 会话）；反查不到就留 `NULL`，不猜测、不伪造；
--   * 两列都只是**标识**（会话 id / 审批 id），不含标题、正文或任何用户文本；
--   * 无索引需求：读取路径始终按 `(tenant_id, recipient_id)` 前缀（迁移 `019` 既有索引）取列表后再用这两列。

ALTER TABLE workbench_inbox_items
    ADD COLUMN IF NOT EXISTS target_conversation_id TEXT,
    ADD COLUMN IF NOT EXISTS target_approval_id TEXT;