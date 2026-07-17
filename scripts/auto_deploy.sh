#!/bin/bash
# PaperMind 自动部署脚本 - cron 轮询 main 分支 tarball 部署
# 触发: crontab 每 30 分钟（见下方 crontab 配置）
# 逻辑: 查 main SHA → 与上次部署 SHA 比 → 有新提交则下载 tarball → rsync 覆盖 → docker compose build + up -d → 健康检查
#
# crontab 配置:
#   */30 * * * * /opt/PaperMind/scripts/auto_deploy.sh >> /opt/PaperMind/logs/deploy_cron.log 2>&1
#
# 注意: 本脚本会随仓库进 tarball，rsync 覆盖时不会被删（在 scripts/ 下）。
# .env / deploy/ / .last_deploy_sha / data/ / logs/ 被 rsync 排除保留。
set -euo pipefail

PROJECT_DIR="/opt/PaperMind"
REPO="Color2333/PaperMind"
BRANCH="main"
SHA_FILE="$PROJECT_DIR/.last_deploy_sha"
LOCK_FILE="/tmp/pm_deploy.lock"
LOG_FILE="$PROJECT_DIR/logs/deploy.log"
TMP_TGZ="/tmp/pm_src.tgz"
TMP_DIR="/tmp/pm_deploy_src"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

# 防并发: 构建耗时长，避免重叠
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "SKIP: 另一个部署进程正在运行"
    exit 0
fi

cd "$PROJECT_DIR"

# 1. 查 main 最新 SHA
log "=== 检查 main 分支最新提交 ==="
REMOTE_SHA=$(curl -s --max-time 15 "https://api.github.com/repos/$REPO/commits/$BRANCH" | python3 -c "import sys,json; print(json.load(sys.stdin)['sha'])" 2>/dev/null || echo "")
if [ -z "$REMOTE_SHA" ]; then
    log "FAIL: 无法获取远程 SHA (api.github.com 不可达)"
    exit 1
fi
REMOTE_SHA_SHORT="${REMOTE_SHA:0:12}"
log "远程 main SHA: $REMOTE_SHA_SHORT"

# 2. 比较上次部署 SHA
LAST_SHA=""
if [ -f "$SHA_FILE" ]; then
    LAST_SHA=$(cat "$SHA_FILE")
fi
if [ "$REMOTE_SHA" = "$LAST_SHA" ]; then
    log "SKIP: 无新提交 (当前已部署 $REMOTE_SHA_SHORT)"
    exit 0
fi
log "检测到新提交! 上次=${LAST_SHA:0:12} → 新=$REMOTE_SHA_SHORT"

# 3. 下载 tarball
log "下载 main tarball..."
if ! curl -sL --max-time 120 "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" -o "$TMP_TGZ"; then
    log "FAIL: tarball 下载失败"
    exit 1
fi
log "下载完成: $(du -h $TMP_TGZ | cut -f1)"

# 4. 解压
log "解压..."
rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"
tar -xzf "$TMP_TGZ" -C "$TMP_DIR"
SRC_DIR=$(ls -d "$TMP_DIR"/PaperMind-* 2>/dev/null | head -1)
if [ -z "$SRC_DIR" ] || [ ! -d "$SRC_DIR" ]; then
    log "FAIL: 解压后未找到源码目录"
    exit 1
fi
log "源码目录: $(basename $SRC_DIR)"

# 5. rsync 覆盖 (排除保留项)
log "rsync 覆盖代码..."
rsync -a --delete \
    --exclude='.env' \
    --exclude='.env.bak.*' \
    --exclude='deploy/' \
    --exclude='.last_deploy_sha' \
    --exclude='data/' \
    --exclude='logs/' \
    --exclude='__pycache__/' \
    "$SRC_DIR/" "$PROJECT_DIR/"
log "代码已更新"

# 6. 重建 + 重启
log "docker compose build..."
if ! docker compose build 2>&1 | tee -a "$LOG_FILE" | tail -5; then
    log "FAIL: 构建失败，保留旧 SHA (下次重试)"
    exit 1
fi

log "docker compose up -d..."
if ! docker compose up -d 2>&1 | tee -a "$LOG_FILE" | tail -10; then
    log "FAIL: 启动失败"
    exit 1
fi

# 7. 健康检查
log "等待健康检查 (40s)..."
sleep 40
if curl -sf --max-time 10 http://localhost:8002/health >/dev/null 2>&1; then
    log "OK: backend 健康检查通过"
    echo "$REMOTE_SHA" > "$SHA_FILE"
    log "=== 部署成功! SHA=$REMOTE_SHA_SHORT 已记录 ==="
else
    log "WARN: backend 健康检查未通过 (可能还在启动)，但已记录 SHA"
    echo "$REMOTE_SHA" > "$SHA_FILE"
fi

# 8. 清理
rm -f "$TMP_TGZ"
rm -rf "$TMP_DIR"
log "清理完成"
