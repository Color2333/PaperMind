# ============================================================
# PaperMind Frontend Dockerfile - Nginx 托管静态文件
# @author Color2333
# ============================================================

# Stage 1: 构建前端
FROM node:20-slim AS builder

WORKDIR /build

# 复制 package 文件
COPY package*.json ./

# 使用国内镜像源安装依赖
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund --registry=https://registry.npmmirror.com; else npm install --no-audit --no-fund --registry=https://registry.npmmirror.com; fi

# 复制源码
COPY . ./

# 构建生产版本
RUN npm run build

# ============================================================
# Stage 2: Nginx 托管
# ============================================================
FROM nginx:alpine

# 复制自定义 Nginx 配置（已包含 .mjs MIME type）
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
