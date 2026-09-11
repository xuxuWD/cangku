# Staging 验收清单

本清单用于客户隔离 staging 环境，不适用于本地开发环境。未满足前置条件时停止验收，不使用本地内存仓储或 fake connection 代替真实服务。

> **只想做只读核对**（不改数据、不跑迁移）：用 [`docs/readonly-verification-runbook.md`](readonly-verification-runbook.md) —— 含 9 条已验证的只读 SQL、会话级只读包装、判读标准，以及明确排除的写命令清单。

## 前置条件

- [ ] `WORKBENCH_ENV` 已设置为非 `development`
- [ ] `WORKBENCH_STORAGE_BACKEND=postgres`
- [ ] `WORKBENCH_DATABASE_URL` 指向独立 staging PostgreSQL
- [ ] **目标 PostgreSQL 已安装 `pgvector` 扩展**（迁移 `001_initial.sql` 的第一句是 `CREATE EXTENSION IF NOT EXISTS vector`；官方 `postgres` 镜像**不含**该扩展，缺失时迁移直接抛 `FeatureNotSupported: extension "vector" is not available`。已在 2026-09-12 本机一次性容器上复现，改用 `pgvector/pgvector:pg16` 后通过）
- [ ] `WORKBENCH_AUTH_SECRET` 至少 32 个字符，并通过部署密钥系统注入
- [ ] `WORKBENCH_BACKUP_ENCRYPTION_KEY` 已配置，且备份密钥与应用密钥分离
- [ ] `WORKBENCH_APPLIED_MIGRATIONS` 已从目标数据库读取
- [ ] `WORKBENCH_RETENTION_POLICY` 和 `WORKBENCH_RUNTIME_VERSIONS` 已登记
- [ ] staging 租户、客户管理员、对象存储命名空间和 Redis 实例彼此隔离
- [ ] staging 独立主机地址、staging 租户标识和对象存储命名空间已登记
- [ ] RAGFlow 和 AgentScope 隔离测试账号已提供，并声明就绪
- [ ] `python scripts/staging_preflight.py` 返回 `pass`
- [ ] `python scripts/runtime_staging_preflight.py` 返回 `pass`
- [ ] RAGFlow/AgentScope HTTPS 地址、固定版本、认证注入标记和网络白名单已登记

## 执行顺序

1. 先按 `.env.staging.example` 登记独立 PostgreSQL、Redis、对象存储、staging 租户和测试账号，再运行 `python scripts/staging_preflight.py`，结果必须为 `pass`；它会聚合基础设施隔离、商业化 G0 和外部 Runtime 元数据校验，`commercial_g0_preflight.py` 与 `runtime_staging_preflight.py` 只作为分组复核。
2. 在维护窗口前执行一致性备份，并保存备份校验值和操作记录。
3. 启动应用，让迁移 runner 应用 `001` 至当前最新迁移；记录新增迁移版本。
4. 执行健康检查、租户读取、客户管理员权限检查和跨租户 404 检查。
5. 创建一条低风险任务，验证 PostgreSQL 持久化、审计和幂等重复提交。
6. 写入一条用量账本记录，验证租户范围汇总和幂等重复写入。
7. 申请导出和删除，验证异步任务、删除冷静期、最终导出标记和删除后状态。
8. 将备份恢复到隔离数据库，验证租户、审计、用量和生命周期记录可读取。
9. 记录失败回放、人工接管、恢复耗时和所有未通过项。
10. 对 RAGFlow 执行知识库范围、跨租户拒绝和引用完整性测试；对 AgentScope 执行健康、事件、暂停/恢复/取消、审批、usage、超时和 replay 测试。
11. 前置条件全部满足后，执行跨租户隔离测试、并发压测和沙箱验证，保存指标、失败回放和人工接管记录。

## 通过标准

- 所有前置条件和预检项为 `pass`。
- 迁移、备份和恢复均有可追溯证据。
- 租户越权、重复提交、删除冷静期和敏感字段脱敏检查均通过。
- 不存在未登记的生产密钥、Cookie、客户原文或临时会话文件。
- 预检脚本只验证部署元数据，不作为真实外部服务可用性或生产验收证据。

## 当前状态

本仓库已完成本地真实 PostgreSQL 迁移与备份恢复演练；已提供 `.env.staging.example` 部署模板与 `scripts/staging_preflight.py` 统一预检。当前机器未配置 staging 环境变量，等待独立主机资源、部署注入密钥和 RAGFlow/AgentScope 测试账号后进入联调，因此本清单尚未通过 staging 验收。
