#!/bin/bash
# PaperMind Docker 快速部署脚本
# @author Color2333
#
# 使用方法:
#   ./scripts/docker_deploy.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DEPLOY_DIR="$PROJECT_ROOT/deploy"

echo "========================================"
echo "PaperMind Docker 部署脚本"
echo "========================================"
echo

# Step 1: 检查配置文件
echo "📋 检查配置文件..."
if [ ! -f "$DEPLOY_DIR/.env" ]; then
    echo "⚠️  配置文件不存在，从模板复制..."
    cp "$DEPLOY_DIR/.env.example" "$DEPLOY_DIR/.env"
    echo "✅ 已创建 $DEPLOY_DIR/.env"
    echo
    echo "❗ 请编辑 $DEPLOY_DIR/.env 填写以下配置:"
    echo "   - XIAOMI_API_KEY (小米 MiMo，默认 provider) 或 ZHIPU_API_KEY/其他 LLM API Key"
    echo "   - SMTP_USER (邮箱地址)"
    echo "   - SMTP_PASSWORD (SMTP 授权码)"
    echo "   - NOTIFY_DEFAULT_TO (接收日报的邮箱)"
    echo
    read -p "填写完成后按回车继续..."
fi

# Step 2: 检查 Docker
echo "🐳 检查 Docker 环境..."
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，请先安装 Docker"
    exit 1
fi

if ! command -v docker compose &> /dev/null; then
    echo "❌ Docker Compose 未安装，请先安装 Docker Compose"
    exit 1
fi

echo "✅ Docker 环境正常"
echo

# Step 3: 停止旧容器
echo "🛑 停止旧容器（如果有）..."
cd "$PROJECT_ROOT"
docker compose down 2>/dev/null || true
echo

# Step 4: 构建镜像
echo "🔨 构建 Docker 镜像..."
echo "   这可能需要几分钟，请耐心等待..."
docker compose build
echo

# Step 5: 启动服务
echo "🚀 启动服务..."
docker compose up -d
echo

# Step 6: 查看状态
echo "📊 查看服务状态..."
docker compose ps
echo

# Step 7: 查看日志
echo "💡 提示:"
echo "   - 前端地址：http://localhost:3002"
echo "   - 后端 API: http://localhost:8002"
echo "   - 查看日志：docker compose logs -f"
echo "   - 停止服务：docker compose down"
echo "   - 重启服务：docker compose restart"
echo

echo "========================================"
echo "✅ 部署完成！"
echo "========================================"
