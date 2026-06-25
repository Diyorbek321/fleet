# Fleet Management Backend (FastAPI + PostgreSQL)

This project implements the backend API specified in your architecture:
- Trucks + real-time location + history
- Drivers + assignments + safety score history
- Maintenance + service intervals + maintenance records + fuel logs
- Auth: Users with JWT (access) + refresh token support (Redis-ready)
- GPS ingestion with API key auth
- WebSocket broadcast for live dashboards

## Tech
- FastAPI
- SQLAlchemy 2.0 (async)
- PostgreSQL (recommended)
- Alembic (migrations) – optional but scaffold included
- Redis (optional) for refresh tokens

## Quickstart

### 1) Create venv and install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Configure environment
Copy `.env.example` to `.env` and update values:
```bash
cp .env.example .env
```

### 3) Run locally
```bash
uvicorn app.main:app --reload
```

Open docs: http://127.0.0.1:8000/docs

## Notes
- This codebase is written to be production-ready, but you may still want:
  - Alembic migrations generation & management
  - Real geofencing rules and road speed limits integration
  - A scheduled job runner (Celery/APS cheduler/Cron) for maintenance checks and safety score calculation
  - Proper device/truck mapping and device enrollment
