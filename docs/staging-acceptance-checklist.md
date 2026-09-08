# Staging 验收清单

本清单用于客户隔离 staging 环境，不适用于本地开发环境。未满足前置条件时停止验收，不使用本地内存仓储或 fake connection 代替真实服务。

## 前置条件

- [ ] `WORKBENCH_ENV` 已设置为非 `development`
- [ ] `WORKBENCH_STORAGE_BACKEND=postgres`
- [ ] `WORKBENCH_DATABASE_URL` 指向独立 staging PostgreSQL
- [ ] `WORKBENCH_AUTH_SECRET` 至少 32 个字符，并通过部署密钥系统注入
- [ ] `WORKBENCH_BACKUP_ENCRYPTION_KEY` 已配置，且备份密钥与应用密钥分离
- [ ] `WORKBENCH_APPLIED_MIGRATIONS` 已从目标数据库读取
- [ ] `WORKBENCH_RETENTION_POLICY` 和 `WORKBENCH_RUNTIME_VERSIONS` 已登记
- [ ] staging 租户、客户管理员、对象存储命名空间和 Redis 实例彼此隔离

## 执行顺序

1. 运行 `python scripts/commercial_g0_preflight.py`，结果必须为 `pass`。
2. 在维护窗口前执行一致性备份，并保存备份校验值和操作记录。
3. 启动应用，让迁移 runner 应用 `001` 至当前最新迁移；记录新增迁移版本。
4. 执行健康检查、租户读取、客户管理员权限检查和跨租户 404 检查。
5. 创建一条低风险任务，验证 PostgreSQL 持久化、审计和幂等重复提交。
6. 写入一条用量账本记录，验证租户范围汇总和幂等重复写入。
7. 申请导出和删除，验证异步任务、删除冷静期、最终导出标记和删除后状态。
8. 将备份恢复到隔离数据库，验证租户、审计、用量和生命周期记录可读取。
9. 记录失败回放、人工接管、恢复耗时和所有未通过项。

## 通过标准

- 所有前置条件和预检项为 `pass`。
- 迁移、备份和恢复均有可追溯证据。
- 租户越权、重复提交、删除冷静期和敏感字段脱敏检查均通过。
- 不存在未登记的生产密钥、Cookie、客户原文或临时会话文件。

## 当前状态

本仓库已完成本地真实 PostgreSQL 迁移与备份恢复演练；当前机器未配置 staging 环境变量，因此本清单尚未通过 staging 验收。
