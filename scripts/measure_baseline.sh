#!/usr/bin/env bash
# A2 资源基线测量脚本（在阿里云服务器上运行）
#
# 用法：
#   ssh your-server "bash -s" < scripts/measure_baseline.sh
#   或在服务器上直接运行：bash scripts/measure_baseline.sh
#
# 输出：JSON 格式的基线数据（容器 RSS/启动时间/镜像大小），供 H1/H2 决策门使用。
# 前提：Docker Compose 已启动（docker compose ps 确认）。

set -euo pipefail

echo "=== PaperMind A2 资源基线测量 ==="
echo "时间: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# --- Docker 容器资源 ---
echo "--- 容器资源 ---"
for container in $(docker ps --format '{{.Names}}' | grep -E 'papermind|frontend'); do
    stats=$(docker stats --no-stream --format '{{.MemUsage}}\t{{.CPUPerc}}' "$container" 2>/dev/null || echo "N/A")
    mem=$(echo "$stats" | cut -f1)
    cpu=$(echo "$stats" | cut -f2)
    echo "  $container: mem=$mem cpu=$cpu"
done

# --- 镜像大小 ---
echo ""
echo "--- 镜像大小 ---"
for img in $(docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' | grep -i papermind); do
    echo "  $img"
done

# --- 冷启动时间 ---
echo ""
echo "--- 冷启动时间（docker compose down + up 计时）---"
echo "  跳过（需要手动确认，避免影响运行中的服务）"
echo "  手动测量方法："
echo "    docker compose down"
echo "    time docker compose up -d --wait"
echo "    （记录 --wait 返回时间）"

# --- API 空闲 RSS（宿主机视角）---
echo ""
echo "--- API 进程 RSS ---"
for pid in $(pgrep -f "uvicorn\|papermind" 2>/dev/null | head -5); do
    rss_kb=$(grep VmRSS "/proc/$pid/status" 2>/dev/null | awk '{print $2}')
    cmd=$(cat "/proc/$pid/cmdline" 2>/dev/null | tr '\0' ' ' | head -c 80)
    if [ -n "$rss_kb" ]; then
        echo "  PID=$pid RSS=$((rss_kb/1024))MB cmd=$cmd"
    fi
done

# --- Go Core（如果已部署）---
echo ""
echo "--- Go Core ---"
if command -v go &>/dev/null; then
    echo "  Go 版本: $(go version)"
else
    echo "  Go 未安装（C0 骨架在本地构建）"
fi

# --- Python 依赖大小 ---
echo ""
echo "--- venv 大小 ---"
if [ -d ".venv" ]; then
    echo "  .venv: $(du -sh .venv --format=freebsd 2>/dev/null || du -sh .venv 2>/dev/null | awk '{print $1}')"
fi

echo ""
echo "=== 测量完成 ==="
echo "请将以上输出保存到 docs/plans/ 目录作为 A2 基线记录。"
