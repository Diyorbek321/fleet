from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi import _rate_limit_exceeded_handler

from app.core.config import settings
from app.core.database import engine
from app.core.logging import configure_logging, logger
from app.core.rate_limit import limiter
from app.services.refresh_tokens import refresh_store
from app.services.scheduler import shutdown_scheduler, start_scheduler

from app.routers.auth import router as auth_router
from app.routers.trucks import router as trucks_router
from app.routers.drivers import router as drivers_router
from app.routers.maintenance import router as maintenance_router
from app.routers.devices import router as devices_router
from app.routers.gps import router as gps_router
from app.routers.reports import router as reports_router
from app.routers.me import router as me_router
from app.routers.ws import router as ws_router
from app.routers.geofences import router as geofences_router
from app.routers.trips import router as trips_router
from app.routers.analytics import router as analytics_router
from app.routers.driver_data import router as driver_data_router
from app.routers.reminders import router as reminders_router
from app.routers.queue import router as queue_router


INSECURE_JWT_TOKENS = {"", "CHANGE_ME", "CHANGE_ME_SUPER_SECRET", "dev", "devsecret"}


def _check_secrets() -> None:
    """Refuse to start outside local dev with insecure defaults.

    Enforced for every env except ``dev`` (so staging/prod can't accidentally
    ship the committed placeholder secret). The test secret is long and not in
    the blocklist, so the suite still starts.
    """
    if settings.env.lower() == "dev":
        return
    secret = settings.jwt_secret_key.strip()
    if (
        len(secret) < 32
        or secret in INSECURE_JWT_TOKENS
        or "CHANGE_ME" in secret
        or secret.lower() in {"dev", "devsecret", "password", "changeme"}
    ):
        raise RuntimeError(
            "JWT_SECRET_KEY is missing or insecure. Set a long random value before starting. "
            "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(64))'"
        )
    # In production a browser app cannot work without CORS origins configured;
    # fail loud rather than silently shipping an unreachable API.
    if settings.is_prod and not settings.cors_origins_list():
        raise RuntimeError("CORS_ORIGINS must be set in production (comma-separated allowed origins).")


def _init_sentry() -> None:
    """Wire error tracking when a DSN is configured. No-op otherwise."""
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.env,
            integrations=[StarletteIntegration(), FastApiIntegration()],
            traces_sample_rate=0.1,
            send_default_pii=False,
        )
        logger.info("sentry_initialized", env=settings.env)
    except Exception:  # pragma: no cover - never let observability wiring block startup
        logger.exception("sentry_init_failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    _check_secrets()
    _init_sentry()
    await refresh_store.init()
    start_scheduler()
    logger.info("app_startup", env=settings.env, cors=settings.cors_origins_list())
    yield
    shutdown_scheduler()
    await engine.dispose()
    logger.info("app_shutdown")


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS — restrict methods/headers in production
origins = settings.cors_origins_list()
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-IMEI"],
    )


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.env}


@app.get("/health/db")
async def health_db():
    from sqlalchemy import text
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok"}

# Include routers
app.include_router(auth_router)
app.include_router(trucks_router)
app.include_router(drivers_router)
app.include_router(maintenance_router)
app.include_router(devices_router)
app.include_router(gps_router)
app.include_router(reports_router)
app.include_router(me_router)
app.include_router(ws_router)
app.include_router(geofences_router)
app.include_router(trips_router)
app.include_router(analytics_router)
app.include_router(driver_data_router)
app.include_router(reminders_router)
app.include_router(queue_router)
