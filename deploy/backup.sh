#!/usr/bin/env bash
# 每日备份：数据库（在线备份，WAL 安全）+ 上传照片，保留最近 30 天
# crontab（在服务器 ubuntu 用户下执行）：
#   crontab -e
#   0 3 * * * /home/ubuntu/MyProjects/18805-MHT/deploy/backup.sh >> /home/ubuntu/MyProjects/18805-MHT/logs/backup.log 2>&1
set -euo pipefail

BASE=/home/ubuntu/MyProjects/18805-MHT
STAMP=$(date +%F)
DB=$BASE/data/orders.db
DEST=$BASE/backup

mkdir -p "$DEST"

# 使用 sqlite3 在线备份（不再拷贝 wal/shm 文件）
sqlite3 "$DB" ".backup '$DEST/orders_$STAMP.db'"

# 打包上传图片
tar -czf "$DEST/uploads_$STAMP.tar.gz" -C "$BASE" uploads

# 保留最近 30 天
find "$DEST" \( -name '*.db' -o -name '*.tar.gz' \) -printf '%T@ %p\n' \
  | sort -rn \
  | tail -n +31 \
  | cut -d' ' -f2- \
  | xargs -r rm -f

echo "backup done: $STAMP"
