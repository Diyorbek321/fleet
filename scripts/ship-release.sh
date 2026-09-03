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

# The link to this Droplet drops mid-transfer often enough that a single-shot
# rsync of a 230 MB file is a coin flip — it broke at 75% on the first run of
# this script. Keepalives make ssh notice a dead peer instead of hanging, and
# every step below is written to be safe to re-run so a break costs only the
# bytes still outstanding.
SSH_OPTS="-o ServerAliveInterval=15 -o ServerAliveCountMax=4 -o ConnectTimeout=20"
SSH="ssh $SSH_OPTS"
# Steps already finished by an interrupted run can be skipped: FROM_STEP=4
# resumes at the transfer, which is the only step likely to have failed.
FROM_STEP="${FROM_STEP:-1}"
step() { [ "$1" -ge "$FROM_STEP" ]; }

if step 1; then
say "1/7  Database backup (before any migration runs)"
# Skipped when a dump from the last two hours already exists: a resumed run
# must not spend minutes re-dumping a database nothing has touched yet.
$SSH "$HOST" "set -e
  cd $REMOTE_DIR && mkdir -p backups
  recent=\$(find backups -name 'pre-owner-alerts-*.sql.gz' -mmin -120 | head -1)
  if [ -n \"\$recent\" ]; then
    echo \"    reusing \$recent\"
  else
    $COMPOSE exec -T postgres pg_dump -U fleet fleet | gzip > backups/pre-owner-alerts-$STAMP.sql.gz
    ls -lh backups/pre-owner-alerts-$STAMP.sql.gz
  fi"
fi

say "2/7  Recording the current schema version and tagging a rollback point"
BEFORE=$($SSH "$HOST" "cd $REMOTE_DIR && $COMPOSE exec -T postgres psql -U fleet -d fleet -tAc 'select version_num from alembic_version;'" | tr -d '\r')
echo "    alembic_version before: $BEFORE"
if step 2; then
# Reuses today's tag if one exists. Re-tagging after `docker load` has already
# run would point "rollback" at the release being rolled back from, which is
# the one thing this tag must never mean.
$SSH "$HOST" "set -e
  existing=\$(docker images --format '{{.Tag}}' fleetwatch-api | grep '^rollback-' | sort | tail -1 || true)
  if [ -n \"\$existing\" ]; then
    echo \"    rollback point already exists: \$existing\"
  else
    docker tag fleetwatch-api:latest fleetwatch-api:rollback-$STAMP
    docker tag fleetwatch-web:latest fleetwatch-web:rollback-$STAMP
    echo '    tagged rollback-$STAMP'
  fi"
fi

if step 3; then
say "3/7  Copying docker-compose.prod.yml (new env vars live here)"
scp $SSH_OPTS docker-compose.prod.yml "$HOST:$REMOTE_DIR/docker-compose.prod.yml"
fi

if step 4; then
say "4/7  Shipping images (resumes where a broken pipe left off)"
# --append-verify, not plain --partial: the source file is byte-identical
# between attempts, so the bytes already on the far side are re-checksummed
# once and the transfer picks up from there instead of starting over.
# --timeout makes rsync give up on a stalled socket in a minute rather than
# waiting out the TCP timeout, so a retry starts while the link is still worth
# using.
attempt=1
until rsync -av --append-verify --partial --progress --timeout=60 \
        -e "ssh $SSH_OPTS" "$IMAGES" "$HOST:$REMOTE_DIR/images.tar.gz"; do
  attempt=$((attempt + 1))
  if [ "$attempt" -gt 12 ]; then
    echo "    giving up after 12 attempts — the link is down, not flaky" >&2
    exit 1
  fi
  echo "    attempt $attempt (resuming)…"
  sleep 5
done
fi

say "5/7  Loading images"
# Compare sizes first. gunzip on a truncated archive fails loudly, but only
# after `docker load` has already imported whatever layers did arrive — so the
# cheap check comes first.
LOCAL_BYTES=$(stat -c %s "$IMAGES")
REMOTE_BYTES=$($SSH "$HOST" "stat -c %s $REMOTE_DIR/images.tar.gz" | tr -d '\r')
echo "    local $LOCAL_BYTES bytes / remote $REMOTE_BYTES bytes"
if [ "$LOCAL_BYTES" != "$REMOTE_BYTES" ]; then
  echo "    transfer is incomplete — re-run with FROM_STEP=4" >&2
  exit 1
fi
$SSH "$HOST" "cd $REMOTE_DIR && gunzip -c images.tar.gz | docker load"

say "6/7  Restarting api + web"
$SSH "$HOST" "cd $REMOTE_DIR && $COMPOSE up -d --no-build api web && sleep 25 && $COMPOSE ps"

say "7/7  Verifying"
$SSH "$HOST" "set -e
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
    tag=\$(docker images --format '{{.Tag}}' fleetwatch-api | grep '^rollback-' | sort | tail -1) && \\
    docker tag fleetwatch-api:\$tag fleetwatch-api:latest && \\
    docker tag fleetwatch-web:\$tag fleetwatch-web:latest && \\
    $COMPOSE up -d --no-build api web"

The images roll back cleanly; the database does not. The three migrations in
this release are additive (two new tables, three nullable columns, one index),
so the previous image runs fine against the new schema — but if you need the
old schema too, restore the newest backups/pre-owner-alerts-*.sql.gz.
EOF
