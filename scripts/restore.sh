#!/usr/bin/env bash
#
# Restore a Fleet Watch snapshot produced by scripts/backup.sh.
#
#   ./scripts/restore.sh /var/backups/fleet-watch/2026-08-29T03-00-00Z
#
# THIS OVERWRITES THE TARGET DATABASE AND THE UPLOADS VOLUME. It refuses to run
# without an explicit typed confirmation, unless FORCE=1 is set (for the
# unattended restore drill described in DEPLOY-DROPLET.md).
#
# Run the drill on a scratch Droplet at least once. An untested backup is a
# guess: the failure modes that matter — a dump that only ever captured an
# empty schema, an uploads volume that was never mounted — are invisible until
# the day you need them, and that is the worst possible day to find out.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$REPO_ROOT/docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env.prod}"

log() { printf '%s  %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

SNAPSHOT="${1:-}"
[ -n "$SNAPSHOT" ] || die "usage: $0 <snapshot-dir>"
[ -d "$SNAPSHOT" ] || die "not a directory: $SNAPSHOT"
[ -f "$SNAPSHOT/postgres.sql.gz" ] || die "no postgres.sql.gz in $SNAPSHOT"
gzip -t "$SNAPSHOT/postgres.sql.gz" || die "postgres.sql.gz is corrupt — do not restore from it"

[ -f "$COMPOSE_FILE" ] || die "compose file not found: $COMPOSE_FILE"
[ -f "$ENV_FILE" ]     || die "env file not found: $ENV_FILE"

POSTGRES_USER="$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | cut -d= -f2- | tr -d '"' | xargs || true)"
POSTGRES_DB="$(grep -E '^POSTGRES_DB=' "$ENV_FILE" | cut -d= -f2- | tr -d '"' | xargs || true)"
POSTGRES_USER="${POSTGRES_USER:-fleet}"
POSTGRES_DB="${POSTGRES_DB:-fleet}"

COMPOSE=(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE")
PROJECT_NAME="$("${COMPOSE[@]}" config --format json 2>/dev/null | sed -n 's/.*"name":[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
PROJECT_NAME="${PROJECT_NAME:-fleetwatch}"
UPLOADS_VOLUME="${PROJECT_NAME}_uploads"

echo
[ -f "$SNAPSHOT/manifest.txt" ] && { echo "--- manifest ---"; cat "$SNAPSHOT/manifest.txt"; echo; }
echo "About to OVERWRITE:"
echo "  database        $POSTGRES_DB (user $POSTGRES_USER)"
echo "  uploads volume  $UPLOADS_VOLUME"
echo "from snapshot     $SNAPSHOT"
echo

if [ "${FORCE:-0}" != "1" ]; then
    read -r -p "Type the database name to confirm: " CONFIRM
    [ "$CONFIRM" = "$POSTGRES_DB" ] || die "confirmation did not match — nothing was changed"
fi

# Stop the API first. Restoring underneath a live app means in-flight requests
# write rows into a schema that is being dropped out from under them, and the
# connection pool holds sessions against tables that vanish mid-restore.
log "stopping api…"
"${COMPOSE[@]}" stop api >/dev/null

log "ensuring postgres is up…"
"${COMPOSE[@]}" up -d postgres >/dev/null
for _ in $(seq 1 30); do
    if "${COMPOSE[@]}" exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

log "restoring postgres…"
# ON_ERROR_STOP turns a half-applied restore into a loud failure. Without it
# psql prints errors, exits 0, and hands you a database that is quietly missing
# whichever tables failed.
gunzip -c "$SNAPSHOT/postgres.sql.gz" \
    | "${COMPOSE[@]}" exec -T postgres \
      psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null \
    || die "psql restore failed — the database is in a partial state, restore again before starting the api"

if [ -f "$SNAPSHOT/uploads.tar.gz" ]; then
    log "restoring uploads volume…"
    docker volume create "$UPLOADS_VOLUME" >/dev/null
    # Clear first: without it, files deleted since the snapshot come back to
    # life and the volume drifts further from the database on every restore.
    docker run --rm \
        -v "$UPLOADS_VOLUME":/data \
        -v "$SNAPSHOT":/backup:ro \
        alpine:3.20 sh -c 'rm -rf /data/* /data/..?* 2>/dev/null; tar xzf /backup/uploads.tar.gz -C /data' \
        || die "failed to restore uploads volume"
else
    log "WARNING: snapshot has no uploads.tar.gz — trip document photos will be missing"
fi

log "starting api…"
"${COMPOSE[@]}" up -d api >/dev/null

# Verify rather than assume. A restore that reports success while the app
# cannot reach its own database is the failure this whole script exists to
# prevent, so prove the round trip before declaring victory.
log "verifying…"
ORG_COUNT="$("${COMPOSE[@]}" exec -T postgres psql -tAX -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c 'select count(*) from organizations' 2>/dev/null || echo "?")"
log "  organizations rows: $ORG_COUNT"

for _ in $(seq 1 30); do
    if "${COMPOSE[@]}" exec -T api python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/db', timeout=3).status==200 else 1)" >/dev/null 2>&1; then
        log "  /health/db: ok"
        log "restore complete"
        exit 0
    fi
    sleep 2
done

die "api did not report a healthy database after restore — check: ${COMPOSE[*]} logs api"
