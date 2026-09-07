# 内容工作台 SQLite 持久化设计规格

> 日期：2026-09-07  
> 状态：已确认设计，待用户审阅  
> 范围：为内容工作台 Alpha 增加本地 SQLite 持久化，不改变现有内容 API 契约。

## 1. 目标

将内容工作台当前的进程内 `ContentStore` 替换为可重启恢复的本地 SQLite 仓储，使任务、草稿、确认状态、幂等关系和审计记录在后端进程重启后仍然可查询。

## 2. 范围与非目标

包含：

- 新增保持现有 `ContentStore` 行为契约的 `SQLiteContentStore`。
- 开发环境默认数据库文件 `data/content-workbench.sqlite3`。
- 通过 `CONTENT_STORE_PATH` 允许部署或测试覆盖文件路径。
- 启动时创建数据目录和内容工作台所需表及索引。
- 事务化保存任务、草稿、确认/撤销和审计变更。
- 保留内存仓储作为单元测试和显式临时场景的实现。

不包含：

- 不修改内容工作台 HTTP 路径、请求响应结构或权限规则。
- 不把现有商业化任务、事件、知识权限仓储迁移到 SQLite。
- 不引入 PostgreSQL 兼容层、后台迁移服务或跨进程分布式锁。
- 不把 SQLite 文件纳入 Git，不承诺生产多副本或高并发部署能力。

## 3. 架构

应用层通过一个内容仓储接口访问记录。现有内存实现继续用于测试；应用启动时根据配置选择 SQLite 实现：

```text
ContentService
    -> ContentStore contract
        -> SQLiteContentStore (development default)
        -> ContentStore (tests/explicit memory mode)
```

仓储负责记录序列化、事务、幂等索引和租户/用户范围过滤；业务服务继续负责输入规范化、Mock 生成、版本控制、权限决策和审计语义。

## 4. 配置与生命周期

- 新增 `content_store_path` 设置，环境变量名为 `CONTENT_STORE_PATH`。
- 默认值为项目根目录下的 `data/content-workbench.sqlite3`。
- 绝对路径按原样使用；相对路径相对于项目根目录解析。
- 应用启动时创建父目录、打开 SQLite 连接并执行幂等建表语句。
- SQLite 连接使用线程安全配置，并由仓储统一关闭；每个公共操作完成后提交或回滚事务。
- 数据库文件路径不可写时，启动应明确失败，不得静默退回内存存储。

## 5. 数据模型

使用四张表保存当前内容领域已有的结构化数据：

### 5.1 `content_tasks`

- `task_id` 主键
- `tenant_id`、`created_by`、`idempotency_key`
- `input_fingerprint`
- `brief_json`：规范化后的主题、来源和知识引用
- `run_ids_json`
- `created_at`、`updated_at`

在 `(tenant_id, created_by, idempotency_key)` 上建立唯一索引，保证同一用户租户内幂等创建。

### 5.2 `content_drafts`

- `draft_id` 主键
- `task_id` 外键逻辑关联
- `run_id`、`tenant_id`
- `title`、`summary`、`body_markdown`
- `image_suggestions_json`、`citations_json`
- `revision`、`status`
- `confirmed_by`、`confirmed_at`
- `created_at`、`updated_at`

按 `(task_id, revision)` 建立唯一索引，按任务和版本倒序读取当前草稿。

### 5.3 `content_audits`

- `audit_id` 主键
- `task_id`、`tenant_id`、`actor_id`
- `action`、`detail_json`
- `created_at`

按 `(task_id, created_at, audit_id)` 建立读取索引，保证审计顺序稳定。

### 5.4 `content_store_meta`

- `key` 主键
- `value`

用于记录 SQLite schema 版本。当前版本为 `1`，启动时可重复执行版本一致的初始化语句。

## 6. 读写与并发语义

- `find_by_idempotency`、`get` 在单个只读事务中完成，并继续执行现有租户、用户和 elevated 过滤。
- `add` 在一个写事务中同时写入任务、初始草稿、运行 ID 和幂等索引；唯一键冲突转换为现有服务层可识别的幂等冲突路径。
- 草稿编辑使用现有 `revision` 条件更新；受影响行数为零时返回版本冲突，不覆盖新版本。
- 确认、撤销确认和审计写入在同一事务中完成，避免出现状态已变更但审计缺失的中间结果。
- SQLite 忙等待时间设置为短超时；超时错误向上层报告为可重试的存储错误，不回退到内存。

## 7. 兼容与错误处理

- `ContentService` 不感知具体存储实现，现有 API 响应和错误码保持不变。
- 老的内存测试不需要数据库文件；测试可为每个用例传入临时 SQLite 路径验证持久化行为。
- 数据库初始化或读写失败记录脱敏错误信息，并返回通用服务错误；不把 SQL、文件路径中的敏感信息写入员工响应。
- 内容导出仍由现有导出模块完成，仓储只提供已确认的当前草稿和审计数据。

## 8. 测试策略

### 8.1 仓储测试

- 创建后可按任务 ID 查询，重启新的仓储实例后仍可查询。
- 幂等键在同一租户用户范围内唯一，不同租户或用户可以复用。
- 租户、用户和 elevated 读取规则与内存实现一致。
- 草稿版本、确认字段和审计列表可完整往返序列化。
- 版本冲突不覆盖已有草稿。
- 数据库目录自动创建；不可写或损坏数据库返回明确错误。

### 8.2 回归测试

- 现有内容服务、内容 API、Alpha 闭环测试全部通过。
- 后端全量测试、Python 编译检查通过。
- 前端测试和构建不因仓储替换发生变化。
- 浏览器端执行“生成 -> 编辑 -> 保存 -> 确认 -> 下载”，并验证服务重启后任务仍可恢复。

## 9. 验收标准

- 停止并重新启动后端后，使用原任务 ID 可以恢复任务状态、当前草稿和确认状态。
- 相同幂等键重试不创建第二个业务任务；不同输入仍返回冲突。
- 草稿编辑、确认、撤销和导出行为与 SQLite 替换前一致。
- 现有 API 契约和权限测试无回归。
- SQLite 文件位于 `data/`，被 `.gitignore` 排除，工作区不产生数据库提交。
