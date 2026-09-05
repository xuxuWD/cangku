# 公司数字员工工作台

公司内部数字员工智能自动化工作台的独立项目仓库。主员工端采用 Windows 桌面端，网页端用于管理和远程协作，手机端先以 PWA 伴侣形式提供审批与提醒。

## 项目边界

- 本仓库只存放公司工作台的需求、调研、设计、实现和验收资料。
- GEO 项目、客户项目和其他实验项目使用各自独立的 Git 仓库，不在本仓库合并或引用其代码历史。
- 当前仓库已具备第一阶段控制平面骨架：健康检查、任务幂等、租户隔离、风险审批、审计计数、模型路由、分层记忆和受控成长提案。
- 当前实现使用开发期内存仓储，生产部署切换到 PostgreSQL、Redis、对象存储和异步 Worker；API 契约保持不变。

## 当前资料

- `pdf_text.txt`：竞品方案 PDF 的文字提取结果，用于调研记录。
- `extract_pdf.py`：通用 PDF 文字提取工具，不包含个人机器的绝对路径。
- `tmp/`：PDF 页面图片和裁剪缓存，仅用于本地查看，不纳入版本控制。

## 本地运行控制平面

```powershell
python -m venv .venv
.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

服务启动后访问 `http://127.0.0.1:8000/docs` 查看中文 API 交互文档。开发接口使用 `X-Tenant-Id`、`X-User-Id` 和 `X-User-Role` 表示当前身份；正式环境必须替换为统一登录和短期会话，不能信任客户端自行填写的角色。

启动基础设施：

```powershell
docker compose up -d
```

基础设施包含 PostgreSQL + pgvector、Redis 和 MinIO。复制 `.env.example` 为 `.env` 并替换所有随机密钥后再启动；Compose 端口只绑定本机，不能直接当作生产编排文件。

生产启动必须设置 `WORKBENCH_ENV=production`、`WORKBENCH_STORAGE_BACKEND=postgres`、可访问的 PostgreSQL 地址和长度不少于 32 位的 `WORKBENCH_AUTH_SECRET`。缺少任一项时服务会拒绝启动，不会悄悄回退到内存数据。

## 第一阶段 API 行为

- `GET /api/v1/health`：服务健康检查。
- `POST /api/v1/tasks`：创建任务；高风险任务自动进入待审批状态。
- `GET /api/v1/tasks/{task_id}`：在当前租户范围查看任务。
- `POST /api/v1/tasks/{task_id}/approve`：由 CEO 或超级管理员审批高风险任务。

任务创建和审批会产生统一事件，供多端同步任务状态。开发环境使用内存事件总线；生产环境使用 PostgreSQL Outbox、Redis Streams 和 Celery，失败事件经过有限重试后进入死信队列。

任务创建支持幂等键。重复提交不会创建第二个任务，也不会重复写入审计事件。所有高风险动作都必须经过服务端权限策略，前端隐藏按钮不属于安全边界。

## 安全边界

- 不保存或上传密码、Cookie、验证码、会话快照、原始 API 密钥。
- 外部发布优先使用官方 API；无官方 API 时使用用户本人登录的本地授权助手，遇到验证码、风控或页面变化立即人工接管。
- 不实现 Cookie 嗅探、私有接口模拟、验证码绕过、滑块绕过、设备伪装或代理轮换。
- Hermes 式成长只生成候选技能、提示词和记忆提案，必须离线测试、管理员审核和可回滚后才能生效。

## 与 GEO 的边界

GEO 是独立项目，通过版本化适配器接入。工作台统一承载用户、岗位、权限、任务、审批、通知、用量和审计；GEO 继续负责 GEO 业务、证据、内容、观测和报告。禁止跨库写入、复制 GEO 内部表或把 GEO 内部实现暴露给客户端。

## 资料处理

使用 Python 运行通用解析工具：

```powershell
python -m pip install -r requirements.txt
python extract_pdf.py --input "资料路径.pdf" --output pdf_text.txt
```

原始 PDF、客户资料、账号信息、Cookie、API 密钥和本地环境文件不得提交到仓库。

## Git 约定

- `main`：经过审核的项目基线。
- `feature/<主题>`：独立功能开发分支。
- 每个提交只解决一个清晰的问题，并在提交前附上对应测试或资料依据。
- 未完成真实环境验收的功能，不标记为已上线或已验收。
