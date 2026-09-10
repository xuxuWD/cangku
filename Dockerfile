# 公司数字员工工作台：应用镜像
#
# 构建：
#   docker build -t workbench-app .
# 运行（与基础设施一起，见 docker-compose.app.yml）：
#   docker compose -f docker-compose.yml -f docker-compose.app.yml up -d
#
# 约定：
# - 所有密钥只从环境注入，绝不写入镜像层。
# - 以非 root 用户运行。
# - 生产模式下应用启动时会自动应用 migrations/ 下的迁移。

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/workbench

# 先只复制依赖清单并安装，利用层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 运行用户（非 root）
RUN groupadd --system workbench \
    && useradd --system --gid workbench --home-dir /srv/workbench --shell /usr/sbin/nologin workbench

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
