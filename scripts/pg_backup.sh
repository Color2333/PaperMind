#!/bin/bash
# PaperMind PostgreSQL 在线备份（pg_dump + 流式 gzip）
#
# 切到 PG 后替代 backup_db.sh（后者备份的是已不作主库的 SQLite 文件）。
# 保留 papermind.db 数据卷作回滚兜底即可，不再每天备份它。
#
# 用法:
#   ./scripts/pg_backup.sh daily    # 每日备份，保留 7 天
#   ./scripts/pg_backup.sh weekly   # 每周归档，保留 28 天
#   ./scripts/pg_backup.sh          # 默认 daily
#
# cron:
#   0 3 * * *   /opt/PaperMind/scripts/pg_backup.sh daily  >> /opt/PaperMind/logs/backup.log 2>&1
#   30 4 * * 1  /opt/PaperMind/scripts/pg_backup.sh weekly >> /opt/PaperMind/logs/backup.log 2>&1
#
# 原理: docker exec pg_dump 流式导出 → 管道 gzip → 落盘，不占临时文件空间。
# --no-owner --clean --if-exists: 恢复时先 DROP 已有对象再 CREATE，
# 既可恢复到空库也可覆盖已有库；--no-owner 避免 owner 不匹配。
set -euo pipefail

KIND="${1:-daily}"
CONTAINER="papermind-postgres"
BACKUP_DIR="/opt/PaperMind/backups"
LOG_FILE="/opt/PaperMind/logs/backup.log"

case "$KIND" in
  daily)  KEEP_DAYS=7  ;;
  weekly) KEEP_DAYS=28 ;;
  *) echo "用法: $0 [daily|weekly]"; exit 1 ;;
esac

mkdir -p "$BACKUP_DIR"

TS=$(date +%Y%m%d_%H%M%S)
BK_FILE="$BACKUP_DIR/papermind_pg_${TS}_${KIND}.sql.gz"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

log "=== PG 备份开始 ($KIND) ==="

# pg_dump 流式导出 + gzip 压缩（管道，不落地临时文件）
log "pg_dump + gzip..."
if ! docker exec "$CONTAINER" pg_dump -U papermind -d papermind \
    --no-owner --clean --if-exists 2>>"$LOG_FILE" | gzip > "$BK_FILE"; then
  log "FAIL: pg_dump 失败"
  rm -f "$BK_FILE"
  exit 1
fi

SIZE=$(du -h "$BK_FILE" | cut -f1)
log "OK: 备份完成 $BK_FILE ($SIZE)"

# 完整性校验：gzip -t 校验压缩流完整
log "gzip 完整性校验..."
if gzip -t "$BK_FILE" 2>>"$LOG_FILE"; then
  log "OK: gzip 校验通过"
else
  log "WARN: gzip 校验异常"
fi

# 保留策略：删超过 KEEP_DAYS 天的同类备份
DELETED=$(find "$BACKUP_DIR" -name "papermind_pg_*_${KIND}.sql.gz" -mtime +${KEEP_DAYS} -print -delete 2>/dev/null | wc -l)
log "清理: 删除 ${DELETED} 个超过 ${KEEP_DAYS} 天的 ${KIND} PG 备份"

# 当前备份数量统计
COUNT=$(find "$BACKUP_DIR" -name "papermind_pg_*_${KIND}.sql.gz" | wc -l)
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
log "当前 ${KIND} PG 备份: ${COUNT} 个, backups/ 总占用: ${TOTAL_SIZE}"
log "=== PG 备份结束 ==="
