#!/usr/bin/env bash
#
# Ship the images already built on this laptop to the Droplet.
#
# The build cannot run on the server — its disk and RAM cannot survive a Vite
# build — so images are built here and loaded there. See DEPLOY-DROPLET.md and
# the redeploy checklist this script encodes:
#
#   1. back the database up BEFORE anything applies a migration
#   2. tag the running images as a rollback point BEFORE `docker load`
#      overwrites :latest
#   3. copy docker-compose.prod.yml over — the server's checkout only holds
#      config, so a new environment variable never reaches the container
#      otherwise
#   4. load, restart api + web only (caddy/postgres/redis have been up for
#      weeks and restarting them buys nothing)
#   5. verify: the migration advanced, the logs are clean, and the bundle the
#      server serves is the one just built
#
# Safe to re-run. Every step is idempotent and nothing is deleted.
#
# Usage:  ./scripts/ship-release.sh /path/to/images.tar.gz [expected-asset-hash]
set -euo pipefail

HOST="${DEPLOY_HOST:-root@139.59.132.176}"
REMOTE_DIR="${DEPLOY_DIR:-/root/fleet}"
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.prod"
IMAGES="${1:?usage: ship-release.sh <images.tar.gz> [expected-asset-hash]}"
EXPECT_ASSET="${2:-}"
STAMP="$(date +%Y%m%d-%H%M)"

say() { printf '\n\033[1m▸ %s\033[0m\n' "$1"; }

say "1/7  Database backup (before any migration runs)"
ssh "$HOST" "set -e
  cd $REMOTE_DIR && mkdir -p backups
  $COMPOSE exec -T postgres pg_dump -U fleet fleet | gzip > backups/pre-owner-alerts-$STAMP.sql.gz
  ls -lh backups/pre-owner-alerts-$STAMP.sql.gz"

say "2/7  Recording the current schema version and tagging a rollback point"
BEFORE=$(ssh "$HOST" "cd $REMOTE_DIR && $COMPOSE exec -T postgres psql -U fleet -d fleet -tAc 'select version_num from alembic_version;'" | tr -d '\r')
echo "    alembic_version before: $BEFORE"
ssh "$HOST" "set -e
  docker tag fleetwatch-api:latest fleetwatch-api:rollback-$STAMP
  docker tag fleetwatch-web:latest fleetwatch-web:rollback-$STAMP
  echo '    tagged rollback-$STAMP'"

say "3/7  Copying docker-compose.prod.yml (new env vars live here)"
scp docker-compose.prod.yml "$HOST:$REMOTE_DIR/docker-compose.prod.yml"

say "4/7  Shipping images (rsync --partial: a plain pipe breaks on this link)"
rsync -avz --partial --progress "$IMAGES" "$HOST:$REMOTE_DIR/images.tar.gz"

say "5/7  Loading images"
ssh "$HOST" "cd $REMOTE_DIR && gunzip -c images.tar.gz | docker load"

say "6/7  Restarting api + web"
ssh "$HOST" "cd $REMOTE_DIR && $COMPOSE up -d --no-build api web && sleep 25 && $COMPOSE ps"

say "7/7  Verifying"
ssh "$HOST" "set -e
  cd $REMOTE_DIR
  echo '--- schema version ---'
  $COMPOSE exec -T postgres psql -U fleet -d fleet -tAc 'select version_num from alembic_version;'
  echo '--- owner-alert tables present? ---'
  $COMPOSE exec -T postgres psql -U fleet -d fleet -tAc \"select tablename from pg_tables where tablename in ('telegram_accounts','notification_log') order by 1;\"
  echo '--- tracebacks in the last 200 log lines ---'
  $COMPOSE logs --tail=200 api | grep -ci traceback || echo 0
  echo '--- health ---'
  curl -fsS https://fleetapi.eduly.uz/health && echo
  curl -fsS https://fleetapi.eduly.uz/health/db && echo"

if [ -n "$EXPECT_ASSET" ]; then
  say "Bundle check — is the served JS the one just built?"
  # Proves the new bundle is live rather than a cached or stale one, which a
  # 200 from the health endpoint cannot tell you.
  if curl -fsS https://fleet.eduly.uz/ | grep -q "$EXPECT_ASSET"; then
    echo "    OK: $EXPECT_ASSET is being served"
  else
    echo "    MISMATCH: $EXPECT_ASSET not found in the served index.html" >&2
    exit 1
  fi
fi

cat <<EOF

Done. Schema moved from $BEFORE to whatever step 7 printed — it should be
d5e6f7a8b9c0.

To roll back:
  ssh $HOST "cd $REMOTE_DIR && \\
    docker tag fleetwatch-api:rollback-$STAMP fleetwatch-api:latest && \\
    docker tag fleetwatch-web:rollback-$STAMP fleetwatch-web:latest && \\
    $COMPOSE up -d --no-build api web"

The images roll back cleanly; the database does not. The three migrations in
this release are additive (two new tables, three nullable columns, one index),
so the previous image runs fine against the new schema — but if you need the
old schema too, restore backups/pre-owner-alerts-$STAMP.sql.gz.
EOF
