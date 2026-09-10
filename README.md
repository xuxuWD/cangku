# 公司数字员工工作台

公司内部数字员工智能自动化工作台的独立项目仓库。主员工端采用 Windows 桌面端，网页端用于管理和远程协作，手机端先以 PWA 伴侣形式提供审批与提醒。

## 项目边界

- 本仓库只存放公司工作台的需求、调研、设计、实现和验收资料。
- GEO 项目、客户项目和其他实验项目使用各自独立的 Git 仓库，不在本仓库合并或引用其代码历史。
- 当前仓库已具备第一阶段控制平面骨架：健康检查、任务幂等、租户隔离、风险审批、审计计数、模型路由、分层记忆和受控成长提案。
- 高风险能力已统一进入策略中心：第三方 Skill、Shell、特权沙箱、知识库写入、岗位提示词和生产工作流修改默认需要审核，不允许单次批准直接绕过灰度和回滚条件。
- 计划中的“协同动态”只作为任务状态表现层，先做静态列表，后续再评估可关闭的动画效果；不会引入第三方项目的无认证动作网关或素材。
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

开源企业智能体平台选型记录见 [`docs/open-source-agent-platform-research.md`](docs/open-source-agent-platform-research.md)，其中包含 RAGFlow、AgentScope、BISHENG、Coze Studio、Dify、FastGPT 等候选的能力与许可证边界。

启动基础设施：

```powershell
docker compose up -d
```

基础设施包含 PostgreSQL + pgvector、Redis 和 MinIO。复制 `.env.example` 为 `.env` 并替换所有随机密钥后再启动；Compose 端口只绑定本机，不能直接当作生产编排文件。

生产启动必须设置 `WORKBENCH_ENV=production`、`WORKBENCH_STORAGE_BACKEND=postgres`、可访问的 PostgreSQL 地址、长度不少于 32 位的 `WORKBENCH_AUTH_SECRET`、不同值的 `WORKBENCH_BACKUP_ENCRYPTION_KEY` 和 1 到 20 的 `WORKBENCH_OUTBOX_MAX_ATTEMPTS`。缺少任一项时服务会拒绝启动，不会悄悄回退到内存数据。

## 容器化运行

应用镜像定义在 `Dockerfile`，编排在 `docker-compose.app.yml`（与基础设施编排配合使用）：

```powershell
docker build -t workbench-app .
docker compose -f docker-compose.yml -f docker-compose.app.yml up -d
```

约定与边界：

- 镜像以 `python:3.12-slim` 为基础，**以非 root 用户 `workbench` 运行**，健康检查走 `/api/v1/health`（使用标准库，不依赖 curl）。
- **所有密钥只从环境注入**：`.dockerignore` 排除了全部环境文件，编排文件用 `:?` 强制要求 `WORKBENCH_AUTH_SECRET`、`WORKBENCH_BACKUP_ENCRYPTION_KEY`、`WORKBENCH_BOOTSTRAP_TOKEN` 与数据库口令，缺失任一项即启动失败。
- 应用以生产模式启动时会**自动应用 `migrations/` 下的迁移**，无需单独执行迁移步骤。
- 容器内一律使用服务名寻址（`postgres`、`redis`、`minio`），端口只绑定宿主回环地址。

**当前状态**：容器化资产已完成静态校验（`tests/test_container_assets.py`），但**真实镜像构建与容器运行尚未验收**，不得据此宣称已容器化交付。

## Worker 启动

生产环境使用独立进程运行 Celery Worker 和定时调度器。启动前必须完成 PostgreSQL、Redis 和迁移配置：

```powershell
celery -A app.worker:celery_app worker --loglevel=INFO
celery -A app.worker:celery_app beat --loglevel=INFO
```

Worker 只在 PostgreSQL 模式下自动接入 Outbox 发布器；开发环境不会连接外部数据库或 Redis。真实 Worker、消息堆积、死信通知和 staging 验收仍属于交付门禁。

## 第一阶段 API 行为

- `GET /api/v1/health`：服务健康检查。
- `POST /api/v1/tasks`：创建任务；高风险任务自动进入待审批状态。
- `GET /api/v1/tasks/{task_id}`：在当前租户范围查看任务。
- `POST /api/v1/tasks/{task_id}/approve`：由 CEO 或超级管理员审批高风险任务。

任务创建和审批会产生统一事件，供多端同步任务状态。开发环境使用内存事件总线；生产环境使用 PostgreSQL Outbox、Redis Streams 和 Celery，失败事件经过有限重试后进入死信队列。

任务创建支持幂等键。重复提交不会创建第二个任务，也不会重复写入审计事件。所有高风险动作都必须经过服务端权限策略，前端隐藏按钮不属于安全边界。

自建账号流程：员工通过 `POST /api/v1/auth/registrations` 提交申请，超级管理员审批并指定角色与租户后，用 `POST /api/v1/auth/sessions` 登录换取短期会话令牌。首个管理员凭部署注入的 `WORKBENCH_BOOTSTRAP_TOKEN` 自助申请。会话有效期由 `WORKBENCH_SESSION_TTL_SECONDS` 控制（默认 900 秒），配置项见 `.env.example`。

## 安全边界

- 不保存或上传第三方系统的密码、Cookie、验证码、会话快照、原始 API 密钥；自建账号只保存本地口令的 scrypt 哈希，不保存明文口令。
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

## 管理台前端

首个 React 管理台位于 `admin-web/`，当前提供中文“知识权限管理”页面。运行 `cd admin-web; npm install; npm run dev` 可启动本地管理台；具体 API 和开发身份配置见 `admin-web/README.md`。

当前内部 Alpha 另提供“公众号内容工作台”页面：员工可提交主题与正文摘录，使用 Mock Runtime 生成可编辑草稿，自行确认后下载 Markdown 内容包。该流程不抓取网页、不调用真实模型，也不会自动发布；真实模型、平台接入和生产验收仍未完成。
