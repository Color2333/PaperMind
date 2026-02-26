# ============================================================
# PaperMind Docker - 单容器部署（Nginx + API + Worker）
# @author Bamzc
# ============================================================

# Stage 1: 前端构建
FROM node:20-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: Python 后端 + Nginx + Supervisor
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx supervisor curl sqlite3 && \
    rm -rf /var/lib/apt/lists/* && \
    rm -f /etc/nginx/sites-enabled/default

WORKDIR /app

# 后端源码 + 依赖安装
COPY pyproject.toml ./
COPY packages/ packages/
COPY apps/ apps/
RUN pip install --no-cache-dir ".[llm,pdf]" && \
    pip install --no-cache-dir umap-learn

# Alembic 数据库迁移
COPY alembic.ini ./
COPY infra/migrations/ infra/migrations/

# 前端构建产物
COPY --from=frontend /build/dist /app/frontend/dist

# 部署配置
COPY infra/nginx.conf /etc/nginx/conf.d/papermind.conf
COPY infra/supervisord.conf /etc/supervisor/conf.d/papermind.conf

# 数据目录（运行时由 volume 覆盖）
RUN mkdir -p /app/data/papers /app/data/briefs

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -sf http://localhost:8000/health || exit 1

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/papermind.conf"]
