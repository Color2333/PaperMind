#!/bin/bash
# PaperMind SQLite DB 在线备份（Docker 卷架构适配）
# 替代旧 backup.sh（其假设 bind mount + 路径 bug 导致静默零产出）
#
# 用法:
#   ./scripts/backup_db.sh daily    # 每日备份，保留 7 天
#   ./scripts/backup_db.sh weekly   # 每周归档，保留 28 天
#   ./scripts/backup_db.sh          # 默认 daily
#
# cron:
#   0 3 * * *   /opt/PaperMind/scripts/backup_db.sh daily  >> /opt/PaperMind/logs/backup.log 2>&1
#   30 4 * * 1  /opt/PaperMind/scripts/backup_db.sh weekly >> /opt/PaperMind/logs/backup.log 2>&1
#
# 原理: 容器内 sqlite3 .backup 在线一致性备份（WAL 安全），docker cp 取出，gzip 压缩。
# 不读 volume 挂载点，不写进线上 data 目录，避免与库同盘无容灾意义。
set -euo pipefail

KIND="${1:-daily}"
CONTAINER="papermind-backend"
DB_PATH="/app/data/papermind.db"
TMP_NAME="_bk_tmp.db"
BACKUP_DIR="/opt/PaperMind/backups"
LOG_FILE="/opt/PaperMind/logs/backup.log"

# 保留天数：daily 7 天，weekly 28 天
case "$KIND" in
  daily)  KEEP_DAYS=7  ;;
  weekly) KEEP_DAYS=28 ;;
  *) echo "用法: $0 [daily|weekly]"; exit 1 ;;
esac

mkdir -p "$BACKUP_DIR"

TS=$(date +%Y%m%d_%H%M%S)
BK_FILE="$BACKUP_DIR/papermind_${TS}_${KIND}.db.gz"
HOST_TMP="/tmp/pm_bk_$$.db"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

log "=== 备份开始 ($KIND) ==="

# 1. 容器内在线一致性备份（sqlite3 .backup，WAL 安全）
log "容器内 .backup..."
if ! docker exec "$CONTAINER" sqlite3 "$DB_PATH" ".backup '/app/data/$TMP_NAME'" 2>&1 | tee -a "$LOG_FILE"; then
  log "FAIL: 容器内 .backup 失败"
  exit 1
fi

# 2. 取出到宿主机
log "docker cp 取出..."
if ! docker cp "$CONTAINER:/app/data/$TMP_NAME" "$HOST_TMP" 2>&1 | tee -a "$LOG_FILE"; then
  log "FAIL: docker cp 失败"
  docker exec "$CONTAINER" rm -f "/app/data/$TMP_NAME" 2>/dev/null || true
  exit 1
fi

# 3. 删容器内临时文件
docker exec "$CONTAINER" rm -f "/app/data/$TMP_NAME" 2>/dev/null || true

# 4. 压缩到目标文件
log "gzip 压缩..."
gzip -c "$HOST_TMP" > "$BK_FILE"
rm -f "$HOST_TMP"

SIZE=$(du -h "$BK_FILE" | cut -f1)
log "OK: 备份完成 $BK_FILE ($SIZE)"

# 5. 完整性校验（解压后跑 integrity_check）
log "完整性校验..."
CHECK=$(gunzip -c "$BK_FILE" | sqlite3 ":memory:" ".restore" 2>&1 || true)
# 用更简单的方式：gunzip 后对文件跑 integrity_check
TMP_CHECK="/tmp/pm_check_$$.db"
gunzip -c "$BK_FILE" > "$TMP_CHECK"
RESULT=$(sqlite3 "$TMP_CHECK" "PRAGMA integrity_check;" 2>&1)
rm -f "$TMP_CHECK"
if [ "$RESULT" = "ok" ]; then
  log "OK: integrity_check 通过"
else
  log "WARN: integrity_check 异常: $RESULT"
fi

# 6. 保留策略：删超过 KEEP_DAYS 天的同类备份
DELETED=$(find "$BACKUP_DIR" -name "papermind_*_${KIND}.db.gz" -mtime +${KEEP_DAYS} -print -delete 2>/dev/null | wc -l)
log "清理: 删除 ${DELETED} 个超过 ${KEEP_DAYS} 天的 ${KIND} 备份"

# 7. 当前备份数量统计
COUNT=$(find "$BACKUP_DIR" -name "papermind_*_${KIND}.db.gz" | wc -l)
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
log "当前 ${KIND} 备份: ${COUNT} 个, backups/ 总占用: ${TOTAL_SIZE}"
log "=== 备份结束 ==="
