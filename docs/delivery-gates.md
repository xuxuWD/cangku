# 交付门禁

## 当前阶段

- [x] 独立 Git 仓库与 GEO 边界确认
- [x] FastAPI 服务入口和健康检查
- [x] 开发期任务幂等、租户隔离、风险审批和审计计数
- [x] 模型能力筛选与敏感数据阻断
- [x] 分层记忆和受控成长提案
- [x] 基础依赖、环境示例和 Docker Compose
- [x] 契约测试和 Python 编译检查
- [x] PostgreSQL 任务 CRUD、唯一约束、原子审批和迁移 runner 契约
- [x] PostgreSQL 连接池适配、审计读取和审批事务契约
- [ ] staging 数据库实测、迁移回滚演练和真实并发压测
- [x] Redis Streams/Celery 事件总线、Outbox 事务写入与幂等消费者骨架
- [x] Celery Worker/Outbox 的可注入运行骨架、死信登记与人工重放接口（开发期）
- [ ] Celery Worker 实跑、Outbox 生产连接池、死信通知渠道和 staging 验收
- [ ] 统一登录、设备绑定和生产密钥管理
- [ ] Electron 桌面端和 PWA 伴侣端
- [ ] GEO 版本化适配器
- [ ] 真实 staging 与真实平台账号验收

## 每次提交必须满足

1. 先增加或更新行为测试，再修改生产代码。
2. `python -m pytest -q` 全部通过。
3. `python -m compileall -q app tests extract_pdf.py` 通过。
4. 新接口同步更新 `docs/api-contract.md`。
5. 不提交 `.env`、密钥、Cookie、浏览器会话、客户原文或临时媒体。
6. 未通过真实验收的能力不能写成“已上线”“已发布”或“已收录”。
