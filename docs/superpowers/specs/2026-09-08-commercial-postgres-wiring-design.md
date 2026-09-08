# 商业化 PostgreSQL 持久化装配设计

## 目标

让商业化租户、客户管理员、用量账本和生命周期作业在生产模式使用 PostgreSQL 持久化，同时保持开发模式的内存实现和现有 API 契约不变。

## 当前问题

`migrations/006_commercial_g0.sql` 和部分 `PostgresCommercialRepository` 已存在，但 `app/main.py` 始终直接实例化 `InMemoryCommercialRepository`、`InMemoryUsageLedger` 和内存生命周期服务。生产进程重启会丢失租户管理测试数据、用量汇总和导出/删除作业状态，且当前 PostgreSQL 仓储接口不足以支撑 API 所需的读取与管理员校验。

## 方案

采用分层持久化适配器：

- 商业化租户仓储负责租户、工作区、客户管理员和状态读取/变更。
- 用量仓储负责追加、幂等读取、汇总和冲正。
- 生命周期仓储负责导出/删除作业的创建、查询、最终导出标记和完成状态更新。
- 领域服务依赖协议或最小公共接口，不依赖具体内存/PostgreSQL 类。
- `bootstrap.py` 根据 `WORKBENCH_STORAGE_BACKEND` 统一装配实现；开发环境使用内存实现，PostgreSQL 模式使用持久化实现。
- `main.py` 只消费装配结果，不再直接创建商业化内存组件。

不采用单体仓储，避免把租户、账本和生命周期状态耦合在一个大型类中；也不保留生产环境的内存生命周期作业。

## 组件与接口

### 租户仓储

保持现有领域方法语义：

- `create_tenant`
- `get_tenant`
- `activate_tenant`
- `suspend_tenant`
- `create_workspace`
- `get_workspace`
- `add_customer_admin`
- `is_customer_admin`

PostgreSQL 查询必须带租户条件；跨租户或不存在资源统一抛出 `ResourceNotFound`。状态变更在事务内执行，并使用条件更新避免重复或非法转换。

### 用量仓储

统一 `append`、`total`、`total_cost_cents` 和 `reverse` 语义。追加使用 `(tenant_id, idempotency_key)` 唯一约束；重复追加返回已有记录；冲正只插入负向记录，不更新原始账本行。所有汇总查询按租户过滤。

### 生命周期仓储

生命周期服务继续负责权限、冷静期和最终导出规则；作业状态交由仓储保存。仓储至少支持：

- 创建导出/删除作业
- 按租户读取作业
- 按作业号读取并校验租户
- 标记最终导出完成
- 在冷静期结束且满足条件后标记删除完成

请求线程仍只创建异步作业，不执行大批量导出或删除。

## 装配与配置

新增商业化装配函数，沿用现有连接池创建和迁移 runner：

- `storage_backend=memory` 且开发环境：返回内存组件。
- `storage_backend=postgres`：创建或复用 PostgreSQL 连接池，先应用迁移，再返回 PostgreSQL 组件。
- 非开发环境禁止返回任何内存商业化仓储。

连接池可以由调用方注入，便于 fake connection 测试和 Worker/应用共享部署配置。`main.py` 的 API 路由和响应字段保持不变。

## 错误与一致性

- 跨租户资源访问统一表现为 `404`，不泄露资源存在性。
- 数据库唯一冲突按幂等语义返回已有记录，不重复写入用量或生命周期作业。
- 状态更新使用事务和条件谓词；受影响行数为零时返回领域冲突错误。
- 数据库连接或迁移失败时应用启动失败，不回退到内存。
- 导出载荷继续执行现有脱敏规则，不包含密码、Cookie、令牌、原始 API Key 或客户原文。

## 测试验收

- 为 PostgreSQL 租户、管理员、用量和生命周期仓储补充 fake connection 契约测试。
- 验证每条 SQL 都包含租户范围、事务边界、唯一幂等和追加式冲正。
- 验证 `bootstrap.py` 在开发/生产配置下选择正确实现，生产配置不会返回内存组件。
- 保持现有商业化 API、生命周期、用量和全量后端测试通过。
- 真实 PostgreSQL 连接、备份恢复和 staging 压测仍作为后续交付门禁，不在本设计内伪装为已验收。

## 非目标

- 不引入在线支付、SaaS 自动开通或计费网关。
- 不改变现有商业化 API 路径和客户端契约。
- 不在 HTTP 请求线程执行导出、删除、备份或恢复。
- 不接入真实客户数据或外部生产账号。
