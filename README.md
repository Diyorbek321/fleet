# Fleet Watch Pro

Fleet management platform — live GPS tracking, driver assignments, maintenance, and fuel logs.

## Repo layout

```
fleet-watch-pro/
├── backend/     # FastAPI + async SQLAlchemy 2.0 + Alembic (Python 3.12)
├── frontend/    # Vite + React 18 + TS + shadcn/ui + React Query
└── _deprecated/ # Old sync backend + stale artifacts (safe to delete)
```

## Stack

- **Backend**: FastAPI, SQLAlchemy 2.0 (async), PostgreSQL + asyncpg, Alembic, JWT (access + refresh), Redis (token revocation + rate-limit + scheduler lock), WebSockets for live location broadcast. **Multi-tenant** — every customer is an `organization` and all data is org-scoped.
- **Frontend**: React 18, TypeScript, Vite, shadcn/ui, Tailwind, React Query, React Router, Leaflet + OpenStreetMap.

---

## Backend — quickstart

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — set DATABASE_URL, JWT_SECRET_KEY, CORS_ORIGINS

# Run migrations
PYTHONPATH=. alembic upgrade head

# Start dev server
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs
Health: http://localhost:8000/health, http://localhost:8000/health/db

### Alembic commands

```bash
# After changing a model, generate a new migration
PYTHONPATH=. alembic revision --autogenerate -m "describe change"

# Apply
PYTHONPATH=. alembic upgrade head

# Roll back one step
PYTHONPATH=. alembic downgrade -1
```

### Generate a JWT secret

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

---

## Frontend — quickstart

```bash
cd frontend
npm install
cp .env.example .env
# Edit .env — set VITE_API_URL (and VITE_WS_URL). Maps use OpenStreetMap, no token needed.
npm run dev
```

App: http://localhost:5173

Regenerate API types from the running backend:

```bash
npm run gen:api
```

---

## First account (multi-tenant onboarding)

The platform is multi-tenant — each fleet customer is an isolated `organization`.
FleetWatch is sold company by company, so companies are **provisioned by the platform
operator**, not by self-serve sign-up. `POST /api/auth/register` returns
`403 {"detail":"Public registration is disabled"}` unless you set
`ALLOW_PUBLIC_REGISTRATION=true` (demo/staging only).

**1. Create the platform superadmin** (once, from `backend/`):

```bash
SEED_SUPERADMIN_EMAIL=you@yourcompany.uz \
SEED_SUPERADMIN_PASSWORD='<strong-password>' \
python seed.py
```

This puts the superadmin in an organization named `Platform` that holds no fleet
data. The seeder is idempotent — an existing account is left untouched.

**2. Onboard a customer company** — log in as the superadmin and use the
`/organizations` page in the web app, or call the API directly:

```bash
curl -X POST http://localhost:8000/api/organizations \
  -H "Authorization: Bearer $SUPERADMIN_ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Acme Logistics","admin_email":"owner@acme.uz","admin_password":"password123"}'
```

The org and its first **admin** are created in one transaction. That admin adds
managers/operators via `POST /api/auth/users` (or the `/users` page), and driver
mobile logins via `POST /api/drivers/{id}/create-login`.

A superadmin manages companies (`/api/organizations/*`) but never sees their fleet
data — every fleet query is scoped to the signed-in user's own org, so one customer
can never see another's data. Suspending a company (`is_active = false`) blocks its
logins, REST calls, token refreshes and live WebSocket feed immediately.

## Money-first analytics

- `GET /api/analytics/leakage-summary` — top-line fuel waste + unauthorized-stop view
- `GET /api/analytics/fuel-anomalies` — per-truck efficiency vs. fleet baseline
- `GET /api/analytics/fuel-fraud` — **per-fill fraud flags** (oversized fills, price outliers, impossible burn)
- `GET /api/analytics/unauthorized-stops` — long stops outside any geofence
- `GET /api/reminders/expiring` — driver-licence + service-interval expiries (also runs as a scheduler job)

## Deployment

- **Backend**: build `backend/Dockerfile` (runs `alembic upgrade head` then uvicorn). Needs managed Postgres + Redis. In `ENV=prod`, Redis is required and a strong `JWT_SECRET_KEY` + `CORS_ORIGINS` are enforced at startup. Optional `SENTRY_DSN` for error tracking.
- **Frontend**: build `frontend/Dockerfile` (Vite build → nginx). Set `VITE_API_URL`/`VITE_WS_URL` at build time; edit the API origin in `frontend/nginx.conf`'s CSP.
- **Mobile**: per-profile API URL via `EXPO_PUBLIC_API_URL` in `mobile/eas.json` (replace the placeholder `fleetwatch.uz` hosts).
- **CI/CD**: `.github/workflows/ci.yml` (tests, migrations on Postgres). `deploy.yml` builds + pushes images to GHCR — enable by setting repo variable `ENABLE_DEPLOY=true`.

## Status

- [x] **Multi-tenancy** — `organizations` + `org_id` on every table, all queries org-scoped, cross-org isolation tested
- [x] **Auth hardening** — org sign-up, RBAC on all mutations, no client-supplied roles, strict prod secret/CORS guard
- [x] **Horizontal-scale ready** — Redis-backed rate-limit + refresh tokens + scheduler lock, per-org WebSocket rooms, tuned DB pool, GPS-history index
- [x] Fuel-fraud detection + document-expiry reminders
- [x] Repo restructured into `backend/` + `frontend/`
- [x] Alembic migrations
- [x] `.env.example` for both sides
- [x] Real auth (JWT + refresh rotation, Redis-ready revocation)
- [x] React Query data hooks replacing Contexts
- [x] WebSocket live map (token-auth, auto-reconnect)
- [x] Per-device GPS enrollment (IMEI + API key, bcrypt-hashed)
- [x] i18n (EN / UZ / RU) with language switcher
- [x] Tests + CI (pytest 68/68, vitest 29/29, jest 25/25 mobile, GitHub Actions workflow)
- [x] Drivers management UI (CRUD + truck assignment)
- [x] Reports (fleet summary + per-truck distance from GPS history)
- [x] Rate limiting (slowapi) + prod secret guard + structured logging
- [x] Dockerfile (production image: migrations + uvicorn)
- [x] Maintenance backend wiring (CRUD + APScheduler overdue checks + safety-score recalc)
- [x] Geofencing (circular zones + enter/exit events, live WS broadcast)
- [x] Trip segmentation (moving/stopped segments from GPS history + API)

## Connecting real GPS hardware

See [`docs/GT06_TRACCAR_SETUP.md`](docs/GT06_TRACCAR_SETUP.md) for the Concox GT06
→ Traccar → Fleet Watch Pro pipeline. Same pattern works for Teltonika, Queclink,
and ~200 other device models.

## Onboarding a real GPS device

1. Admin enrolls a device via `POST /api/devices`:
   ```bash
   curl -X POST http://localhost:8000/api/devices \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"imei":"352094081234567","name":"Truck Alpha tracker","truck_id":"..."}'
   ```
   Response contains the `api_key` **once** — store it on the device or in Traccar's device config. It cannot be retrieved later; use `POST /api/devices/{id}/rotate-key` to reissue.

2. Device/Traccar forwards positions to `POST /api/gps/ingest` with headers:
   - `X-API-Key: <api_key>`
   - `X-IMEI: <imei>`
   - JSON body: `{"points":[{"latitude":…, "longitude":…, "speed":…}]}` — `truck_id` is optional when the device is assigned.

## i18n

Translations live in `frontend/src/i18n/locales/`. Supported languages:
- English (`en.json`) — source of truth
- O‘zbekcha (`uz.json`)
- Русский (`ru.json`)

To add a language, create a new locale file and register it in `frontend/src/i18n/index.ts`.

## Deploy targets

- **Backend**: Railway / Fly.io / Render (managed Postgres + Redis).
- **Frontend**: Vercel / Netlify / Cloudflare Pages.

See next steps in the team doc.
