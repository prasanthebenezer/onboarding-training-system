#!/usr/bin/env bash
# Daily backup of training records + videos. Run from the repo dir via cron, e.g.:
#   15 2 * * * cd /opt/onboarding-training-system && ./scripts/backup.sh >> backup.log 2>&1
# Copy ./backups OFF the VPS (e.g. rclone to cloud storage). ISO evidence must survive a server loss.
set -euo pipefail
STAMP=$(date +%Y%m%d-%H%M)
mkdir -p backups
docker compose exec -T db pg_dump -U training training | gzip > "backups/db-$STAMP.sql.gz"
docker compose run --rm -T --user 0 -v "$PWD/backups:/out" --entrypoint tar app czf "/out/media-$STAMP.tgz" -C /data media
find backups -type f -mtime +30 -delete
echo "backup ok $STAMP"
