# 公司数字员工工作台：应用镜像
#
# 构建：
#   docker build -t workbench-app .
# 运行（与基础设施一起，见 docker-compose.app.yml；该编排起三个服务，均用本镜像、不同 command）：
#   app    = HTTP 入口（下方 CMD 的 uvicorn，唯一跑迁移的进程）
#   worker = Celery 执行进程（celery -A app.worker worker）
#   beat   = Celery 调度进程（celery -A app.worker beat，**独立进程**，禁止 -B 内嵌）
#   docker compose -f docker-compose.yml -f docker-compose.app.yml up -d
#
# 约定：
# - 所有密钥只从环境注入，绝不写入镜像层。
# - 以非 root 用户运行。
# - 生产模式下应用启动时会自动应用 migrations/ 下的迁移。

# 基础镜像按 digest 钉死（非 tag）：tag 可变、digest 不可变；与段二规格 §4 的 WORKBENCH_EXEC_IMAGE_DIGEST 口径一致
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/workbench

# 先只复制锁定清单并安装，利用层缓存
# 依赖版本与哈希全部钉死（requirements.lock；--require-hashes 强制校验）⇒ 构建可复现、且被篡改会 fail-closed
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

# 运行用户（非 root）
RUN groupadd --system workbench \
    && useradd --system --gid workbench --home-dir /srv/workbench --shell /usr/sbin/nologin workbench

# Celery Beat 排程文件落点：镜像内预建并授权（`docker-compose.app.yml` 的 beat 服务把命名卷挂到这里）。
# 命名卷首次挂载会继承该目录的属主/权限 ⇒ 非 root 用户才写得进 schedule 文件；
# 否则卷属 root:root，beat 启动即失败（「编排看起来对、起不来」）。
RUN mkdir -p /var/lib/celery && chown workbench:workbench /var/lib/celery

# 内容库（默认 SQLite，`WORKBENCH_CONTENT_STORE_BACKEND=sqlite`）落点：同理预建并授权；
# app 服务把命名卷挂到这里做持久化。缺这一步时 app 启动即 `PermissionError: /srv/workbench/data`
# 并进入重启循环（2026-09-15 容器演练实测）。
RUN mkdir -p /srv/workbench/data && chown workbench:workbench /srv/workbench/data

# 只复制运行所需内容；其余路径由 .dockerignore 排除
COPY --chown=workbench:workbench app ./app
COPY --chown=workbench:workbench migrations ./migrations
COPY --chown=workbench:workbench scripts ./scripts
COPY --chown=workbench:workbench pyproject.toml ./

USER workbench

EXPOSE 8000

# slim 镜像没有 curl，健康检查使用标准库
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
