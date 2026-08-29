# Deploying Fleet Watch Pro to a DigitalOcean Droplet

One Droplet runs the whole stack with Docker Compose. Caddy terminates TLS and
auto-provisions Let's Encrypt certificates; Postgres and Redis stay private on
the internal network. Migrations apply automatically on every backend start.

```
Internet → Caddy (:443, auto-HTTPS) → web (SPA)   :8080
                                     → api (FastAPI):8000 → postgres + redis
```

## 1. Create the Droplet

- **Image:** Ubuntu 24.04 LTS
- **Plan:** Basic, **2 GB RAM / 1 vCPU** (~$12/mo) is comfortable for this stack.
  1 GB works but leaves little headroom for the Docker build.
- **Region:** FRA1 (Frankfurt) — closest low-latency option for Central Asia.
- Add your SSH key.

## 2. Point DNS at the Droplet

Create two **A records** at your DNS provider, both pointing to the Droplet's
public IP:

| Record           | Type | Value         |
| ---------------- | ---- | ------------- |
| `app.yourdomain` | A    | `<droplet IP>` |
| `api.yourdomain` | A    | `<droplet IP>` |

Caddy can only issue certificates once these resolve, so do this first.

## 3. Install Docker

```bash
ssh root@<droplet-ip>
# copy scripts/droplet-setup.sh over, or pull it from your repo, then:
bash droplet-setup.sh
```

This installs Docker + Compose and opens only SSH/80/443 in the firewall.

## 4. Clone and configure

```bash
git clone https://github.com/<you>/fleet-watch-pro.git
cd fleet-watch-pro
cp .env.prod.example .env.prod
nano .env.prod          # set APP_DOMAIN, API_DOMAIN, POSTGRES_PASSWORD,
                        # JWT_SECRET_KEY, GPS_API_KEYS
```

Generate the JWT secret with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

## 5. Launch

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

First build takes a few minutes. Watch it come up:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f caddy
```

Caddy will log certificate issuance for both domains. Then:

- `https://app.yourdomain` → the web app
- `https://api.yourdomain/health` → `{"status":"ok"}`

## 6. Seed the platform superadmin

FleetWatch is sold company by company, so customer organizations are
**provisioned by you**, not by self-serve sign-up: `ALLOW_PUBLIC_REGISTRATION`
defaults to `false`, and `POST /api/auth/register` answers
`403 {"detail":"Public registration is disabled"}`. The superadmin account is
therefore the only way into a fresh deployment — create it first:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec \
  -e SEED_SUPERADMIN_EMAIL=you@yourcompany.uz \
  -e SEED_SUPERADMIN_PASSWORD='<strong-password>' \
  api python seed.py --superadmin-only
```

This creates the account inside an organization named `Platform`, which holds no
fleet data. The seeder is idempotent — if the email already exists it prints a
notice and changes nothing, so re-running it after an update is safe.

Log in at `https://app.yourdomain`; a superadmin lands on `/organizations`.
Onboard each customer company from there (or via `POST /api/organizations`),
which creates the org and its first admin in one transaction.

The older `SEED_ADMIN_EMAIL`/`SEED_ADMIN_PASSWORD` pair still seeds a demo fleet
organization and is optional — skip it on a real deployment.

## 7. Mobile app

In `mobile/eas.json`, set `EXPO_PUBLIC_API_URL` to `https://api.yourdomain` per
profile, then build with EAS. Must be HTTPS.

---

## Day-2 operations

**Update to the latest code:**

```bash
git pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

### Backups

Customer data lives in **two** places, and a backup that captures only one is
worthless: Postgres holds every row, while driver-uploaded trip document photos
(`yo'l varaqasi`) sit on the `uploads` Docker volume on local disk. Restore a
`pg_dump` alone and you get a database full of trips whose photos are gone.

`scripts/backup.sh` captures both, verifies the dump completed, writes a
manifest, and rotates old snapshots:

```bash
./scripts/backup.sh
```

Cron it as root:

```cron
0 3 * * * /opt/fleet-watch-pro/scripts/backup.sh >> /var/log/fleet-backup.log 2>&1
```

**Send it off the box.** A backup stored on the Droplet dies with the disk it
was protecting against, so set these in `.env.prod` (or the cron environment)
to copy each run to DigitalOcean Spaces:

```bash
BACKUP_S3_BUCKET=s3://your-backup-space
BACKUP_S3_ENDPOINT=https://fra1.digitaloceanspaces.com
BACKUP_S3_KEY=...
BACKUP_S3_SECRET=...
```

Without them the script still runs and still warns on every invocation.

Tunables: `BACKUP_DIR` (default `/var/backups/fleet-watch`), `RETENTION_DAYS`
(default 7, pruned by count so an outage cannot wipe every snapshot at once).

### Restore

```bash
./scripts/restore.sh /var/backups/fleet-watch/2026-08-29T03-00-00Z
```

Stops the API, restores Postgres with `ON_ERROR_STOP` (a partial restore fails
loudly instead of silently handing you a database missing tables), replaces the
uploads volume, restarts the API, and verifies `/health/db` before reporting
success. It requires you to type the database name to confirm; `FORCE=1` skips
that prompt for the unattended drill below.

### Restore drill — do this before you take a paying customer

An untested backup is a guess. The failure modes that matter (a dump that only
ever captured an empty schema, an uploads volume that was never mounted) stay
invisible until the day you need them, which is the worst possible day to find
out. Once, on a scratch Droplet:

```bash
./scripts/backup.sh                          # take one
docker compose ... exec -T postgres psql -U fleet -d fleet \
  -c 'select count(*) from organizations'    # note the number
FORCE=1 ./scripts/restore.sh /var/backups/fleet-watch/<newest>
```

Then confirm the row counts match and that a trip's document photo still opens
in the manager panel. Repeat after any change to the storage layout.

**Logs:** `docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f api`

## Notes

- The live-map WebSocket runs in a single backend process — correct for one
  Droplet. If you ever run the `api` service with `--scale api=N`, add Redis
  pub/sub first so location updates fan out across replicas.
- DigitalOcean's weekly Droplet snapshot/backup (a few $/mo) is a useful
  whole-box safety net on top of `scripts/backup.sh`, not a replacement for it:
  snapshots are weekly and restore the entire machine, so they cannot recover a
  single tenant's data from Tuesday.
- To use DigitalOcean **Managed Postgres** instead of the in-compose one, drop
  the `postgres` service and point `DATABASE_URL` at the managed cluster's
  connection string (the app coerces `postgres://` to the async driver).
