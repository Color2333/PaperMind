# ============================================================
# PaperMind Frontend Dockerfile - Nginx 托管静态文件
# @author Color2333
# ============================================================

# Stage 1: 构建前端
FROM node:20-slim AS builder

WORKDIR /build

# 复制 package 文件（优先使用 lock 文件）
COPY package*.json ./

# 安装依赖（有 lock 用 ci，没有用 install）
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi

# 复制源码
COPY . ./

# 构建生产版本
RUN npm run build

# ============================================================
# Stage 2: Nginx 托管
# ============================================================
FROM nginx:alpine

# 复制自定义 Nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 复制构建产物
COPY --from=builder /build/dist /usr/share/nginx/html

# 暴露 80 端口
EXPOSE 80

# Nginx 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:80 || exit 1

# 启动 Nginx（前台模式）
CMD ["nginx", "-g", "daemon off;"]
