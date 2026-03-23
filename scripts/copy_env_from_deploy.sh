#!/bin/bash
# PaperMind - 从 deploy 目录复制 .env 到根目录
# @author Color2333
#
# 用途：将部署环境的配置文件复制到项目根目录，供本地开发或 Docker 使用
#
# 使用方法:
#   ./scripts/copy_env_from_deploy.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DEPLOY_DIR="$PROJECT_ROOT/deploy"

echo "========================================"
echo "PaperMind - 复制 deploy/.env 到根目录"
echo "========================================"
echo

# Step 1: 检查 deploy/.env 是否存在
echo "📋 检查配置文件..."
if [ ! -f "$DEPLOY_DIR/.env" ]; then
    echo "❌ 错误：$DEPLOY_DIR/.env 不存在"
    echo
    echo "可能的原因:"
    echo "  1. deploy 目录尚未创建"
    echo "  2. 配置文件在其他位置"
    echo
    echo "解决方案:"
    echo "  - 如果 .env 在其他位置，请手动复制到 deploy/ 目录"
    echo "  - 或者直接修改项目根目录的 .env 文件"
    echo
    exit 1
fi

# Step 2: 检查根目录是否已有 .env
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "⚠️  根目录已存在 .env 文件"
    echo
    read -p "是否覆盖？[y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "已取消操作"
        exit 0
    fi
    # 备份旧配置
    echo "📦 备份旧配置到 .env.backup..."
    cp "$PROJECT_ROOT/.env" "$PROJECT_ROOT/.env.backup"
    echo "✅ 备份完成"
    echo
fi

# Step 3: 复制配置文件
echo "📋 复制 $DEPLOY_DIR/.env → $PROJECT_ROOT/.env..."
cp "$DEPLOY_DIR/.env" "$PROJECT_ROOT/.env"
echo "✅ 复制完成"
echo

# Step 4: 验证配置
echo "🔍 验证配置文件..."
if grep -q "ZHIPU_API_KEY=" "$PROJECT_ROOT/.env"; then
    api_key=$(grep "ZHIPU_API_KEY=" "$PROJECT_ROOT/.env" | cut -d'=' -f2)
    if [ -n "$api_key" ]; then
        echo "✅ ZHIPU_API_KEY 已配置"
    else
        echo "⚠️  ZHIPU_API_KEY 为空，请编辑 .env 填写"
    fi
else
    echo "⚠️  未找到 ZHIPU_API_KEY 配置项"
fi
echo

# Step 5: 提示
echo "========================================"
echo "✅ 完成！"
echo "========================================"
echo
echo "下一步:"
echo "  1. 检查 .env 配置是否正确"
echo "  2. 启动服务:"
echo "     - 本地开发：source .venv/bin/activate && uvicorn apps.api.main:app --reload"
echo "     - Docker 部署：docker compose up -d"
echo
echo "💡 提示:"
echo "  - 本地开发：DATABASE_URL 使用 sqlite:///./data/papermind.db"
echo "  - Docker 部署：DATABASE_URL 使用 sqlite:////app/data/papermind.db"
echo
