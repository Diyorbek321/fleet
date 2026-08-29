#!/usr/bin/env bash
#
# Nightly backup for the Fleet Watch production Droplet.
#
#   ./scripts/backup.sh
#
# Captures BOTH halves of the customer's data:
#   1. Postgres  — every row (trucks, trips, GPS history, money).
#   2. uploads/  — driver-uploaded trip document photos. These live on a Docker
#                  volume on local disk, NOT in Postgres, so a pg_dump alone
#                  restores a database full of trips whose yo'l varaqasi photos
#                  are gone forever. Both, or neither.
#
# A backup that never leaves the Droplet is not a backup — it dies with the
# disk it was protecting against. Set BACKUP_S3_* below to copy each run
# off-box; the script warns loudly (and still succeeds) when they are unset.
#
# Cron it as root on the Droplet:
#   0 3 * * * /opt/fleet-watch-pro/scripts/backup.sh >> /var/log/fleet-backup.log 2>&1
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$REPO_ROOT/docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env.prod}"

log() { printf '%s  %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

[ -f "$COMPOSE_FILE" ] || die "compose file not found: $COMPOSE_FILE"
[ -f "$ENV_FILE" ]     || die "env file not found: $ENV_FILE (copy .env.prod.example and fill it in)"

# Read a key out of the env file. Settings therefore work in the two places an
# operator will naturally put them — exported in the cron environment, or
# written into .env.prod next to everything else — with the environment
# winning. Without this fallback, credentials pasted into .env.prod would be
# ignored and the off-box upload would silently never happen, which is the one
# failure this whole script exists to prevent.
env_get() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' | xargs || true; }

# DB credentials come from the same file the stack itself boots from, so a
# renamed database can never silently back up the wrong thing.
POSTGRES_USER="${POSTGRES_USER:-$(env_get POSTGRES_USER)}"
POSTGRES_DB="${POSTGRES_DB:-$(env_get POSTGRES_DB)}"
POSTGRES_USER="${POSTGRES_USER:-fleet}"
POSTGRES_DB="${POSTGRES_DB:-fleet}"

# Where snapshots land, and how many daily ones to keep before the oldest is
# dropped. 7 covers "we noticed on Monday that Friday's data looks wrong".
BACKUP_DIR="${BACKUP_DIR:-$(env_get BACKUP_DIR)}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/fleet-watch}"
RETENTION_DAYS="${RETENTION_DAYS:-$(env_get RETENTION_DAYS)}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

# Optional off-box copy (DigitalOcean Spaces / any S3). Runs through the
# dockerised aws CLI so the Droplet needs no extra host packages.
BACKUP_S3_BUCKET="${BACKUP_S3_BUCKET:-$(env_get BACKUP_S3_BUCKET)}"
BACKUP_S3_ENDPOINT="${BACKUP_S3_ENDPOINT:-$(env_get BACKUP_S3_ENDPOINT)}"
BACKUP_S3_KEY="${BACKUP_S3_KEY:-$(env_get BACKUP_S3_KEY)}"
BACKUP_S3_SECRET="${BACKUP_S3_SECRET:-$(env_get BACKUP_S3_SECRET)}"

# Credentials without a bucket means someone half-configured this and believes
# backups are leaving the box. Fail rather than warn about an "unset" bucket as
# if it had never been intended.
if [ -z "$BACKUP_S3_BUCKET" ] && [ -n "${BACKUP_S3_KEY}${BACKUP_S3_SECRET}" ]; then
    die "BACKUP_S3_KEY/SECRET are set but BACKUP_S3_BUCKET is empty — off-box upload would be skipped"
fi

COMPOSE=(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE")
PROJECT_NAME="$("${COMPOSE[@]}" config --format json 2>/dev/null | sed -n 's/.*"name":[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
PROJECT_NAME="${PROJECT_NAME:-fleetwatch}"
UPLOADS_VOLUME="${PROJECT_NAME}_uploads"

STAMP="$(date -u '+%Y-%m-%dT%H-%M-%SZ')"
DEST="$BACKUP_DIR/$STAMP"

# Stage into a temp dir and only publish on full success, so a run killed
# halfway never leaves a truncated snapshot that looks restorable.
STAGE="$(mktemp -d)"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

log "backup start  project=$PROJECT_NAME  db=$POSTGRES_DB"

# ---- 1. Postgres ----------------------------------------------------------
# --clean --if-exists makes the dump re-runnable against a database that still
# has the old schema, which is exactly the situation during a real restore.
log "dumping postgres…"
"${COMPOSE[@]}" exec -T postgres \
    pg_dump -U "$POSTGRES_USER" --clean --if-exists "$POSTGRES_DB" \
    | gzip -9 > "$STAGE/postgres.sql.gz"

DUMP_BYTES="$(stat -c%s "$STAGE/postgres.sql.gz")"
gzip -t "$STAGE/postgres.sql.gz" || die "dump failed its own gzip integrity check"

# Verify the dump by its own trailer, not by its size. pg_dump writes
# "PostgreSQL database dump complete" only after it has finished successfully,
# so its presence proves completeness in a way a byte count never can: a real
# fleet database of a few hundred trips gzips down to single-digit kilobytes,
# and any size floor generous enough to catch a truncated dump would reject a
# perfectly good small tenant. This also catches the case where
# `docker compose exec` exits 0 while pg_dump inside it did not.
gunzip -c "$STAGE/postgres.sql.gz" | grep -q 'PostgreSQL database dump complete' \
    || die "dump has no completion marker — pg_dump did not finish; NOT publishing this snapshot"
log "  postgres.sql.gz  $(numfmt --to=iec "$DUMP_BYTES" 2>/dev/null || echo "${DUMP_BYTES}B")"

# ---- 2. Uploaded trip documents -------------------------------------------
if docker volume inspect "$UPLOADS_VOLUME" >/dev/null 2>&1; then
    log "archiving uploads volume…"
    docker run --rm \
        -v "$UPLOADS_VOLUME":/data:ro \
        -v "$STAGE":/backup \
        alpine:3.20 tar czf /backup/uploads.tar.gz -C /data . \
        || die "failed to archive $UPLOADS_VOLUME"
    UPLOAD_BYTES="$(stat -c%s "$STAGE/uploads.tar.gz")"
    log "  uploads.tar.gz   $(numfmt --to=iec "$UPLOAD_BYTES" 2>/dev/null || echo "${UPLOAD_BYTES}B")"
else
    # Not fatal: a fresh deployment has no documents yet. But say so plainly —
    # silence here is how you discover at restore time that photos were never
    # in the backup at all.
    log "WARNING: docker volume '$UPLOADS_VOLUME' not found — NO trip documents in this backup"
    UPLOAD_BYTES=0
fi

# ---- 3. Manifest ----------------------------------------------------------
# Records what this snapshot is, so a restore months later does not have to
# guess which code revision the schema belongs to.
GIT_SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
cat > "$STAGE/manifest.txt" <<MANIFEST
taken_at_utc=$STAMP
git_sha=$GIT_SHA
postgres_db=$POSTGRES_DB
postgres_bytes=$DUMP_BYTES
uploads_bytes=$UPLOAD_BYTES
uploads_volume=$UPLOADS_VOLUME
host=$(hostname)
MANIFEST

# ---- 4. Publish -----------------------------------------------------------
mkdir -p "$DEST"
mv "$STAGE"/* "$DEST/"
log "wrote $DEST"

# ---- 5. Off-box copy ------------------------------------------------------
if [ -n "$BACKUP_S3_BUCKET" ]; then
    log "uploading to $BACKUP_S3_BUCKET/$STAMP…"
    docker run --rm \
        -e AWS_ACCESS_KEY_ID="$BACKUP_S3_KEY" \
        -e AWS_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET" \
        -v "$DEST":/backup:ro \
        amazon/aws-cli:2 \
        ${BACKUP_S3_ENDPOINT:+--endpoint-url "$BACKUP_S3_ENDPOINT"} \
        s3 cp /backup "$BACKUP_S3_BUCKET/$STAMP" --recursive \
        || die "off-box upload failed — the local copy at $DEST is intact"
    log "  uploaded"
else
    log "WARNING: BACKUP_S3_BUCKET unset — this backup lives only on this Droplet."
    log "         A disk failure destroys the data AND its backup together."
fi

# ---- 6. Rotate ------------------------------------------------------------
# Prune by count, not by mtime: if the box was off for a fortnight, an
# mtime rule would delete every surviving backup at once.
mapfile -t OLD < <(find "$BACKUP_DIR" -maxdepth 1 -mindepth 1 -type d | sort | head -n "-$RETENTION_DAYS")
for dir in "${OLD[@]:-}"; do
    [ -n "$dir" ] || continue
    log "pruning old backup $(basename "$dir")"
    rm -rf "$dir"
done

log "backup done  ($(ls -1 "$BACKUP_DIR" | wc -l) snapshots retained)"
