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

## 6. Seed the first admin

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec \
  -e SEED_ADMIN_EMAIL=admin@yourcompany.uz \
  -e SEED_ADMIN_PASSWORD='<strong-password>' \
  api python seed.py
```

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

**Back up the database** (cron this):

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T postgres \
  pg_dump -U fleet fleet | gzip > backup-$(date +%F).sql.gz
```

**Restore:**

```bash
gunzip -c backup-YYYY-MM-DD.sql.gz | \
  docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T postgres \
  psql -U fleet fleet
```

**Logs:** `docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f api`

## Notes

- The live-map WebSocket runs in a single backend process — correct for one
  Droplet. If you ever run the `api` service with `--scale api=N`, add Redis
  pub/sub first so location updates fan out across replicas.
- DigitalOcean's weekly Droplet snapshot/backup (a few $/mo) is the simplest
  whole-box safety net on top of the `pg_dump` above.
- To use DigitalOcean **Managed Postgres** instead of the in-compose one, drop
  the `postgres` service and point `DATABASE_URL` at the managed cluster's
  connection string (the app coerces `postgres://` to the async driver).
