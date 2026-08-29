from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from typing import List

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="Fleet Backend", alias="APP_NAME")
    env: str = Field(default="dev", alias="ENV")
    debug: bool = Field(default=False, alias="DEBUG")

    database_url: str = Field(alias="DATABASE_URL")

    @field_validator("database_url")
    @classmethod
    def _ensure_async_driver(cls, v: str) -> str:
        """Managed hosts (Railway, Render, Heroku) hand out plain
        ``postgres://`` / ``postgresql://`` URLs, but this app uses the async
        ``asyncpg`` driver. Coerce the scheme so the same env var works
        everywhere without manual editing.
        """
        if v.startswith("postgresql+"):  # already explicit (e.g. +asyncpg)
            return v
        if v.startswith("postgresql://"):
            return "postgresql+asyncpg://" + v[len("postgresql://"):]
        if v.startswith("postgres://"):
            return "postgresql+asyncpg://" + v[len("postgres://"):]
        return v

    jwt_secret_key: str = Field(alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    # 90 days keeps drivers signed in on their phones through long stretches
    # of light use — the mobile app also transparently rotates this token on
    # every /api/auth/refresh, so an active driver effectively never expires.
    refresh_token_expire_days: int = Field(default=90, alias="REFRESH_TOKEN_EXPIRE_DAYS")

    # Self-service sign-up at POST /api/auth/register. Off by default because
    # this is a paid, operator-provisioned product: an open sign-up endpoint would
    # let anyone create a tenant (and burn storage, scheduler and Telegram quota)
    # without ever appearing in the platform operator's books. Companies are
    # created by a superadmin via POST /api/organizations instead. Flip it on only
    # for demo/staging deployments where a throwaway tenant is the point.
    allow_public_registration: bool = Field(default=False, alias="ALLOW_PUBLIC_REGISTRATION")

    cors_origins: str = Field(default="", alias="CORS_ORIGINS")

    gps_api_keys: str = Field(default="", alias="GPS_API_KEYS")

    # ---- GPS history retention ----
    # Every position ping writes one truck_location_history row. A phone pings
    # every 15s, so one truck driving 10h/day produces ~2 400 rows/day and a
    # 20-truck fleet ~1.4M rows/month — unbounded growth that eventually
    # outgrows the droplet's disk and slows every analytics scan.
    # A background job purges rows older than this many days. 90 comfortably
    # covers the 30-day default leakage window plus quarter-end review; set to
    # 0 to disable purging (keep everything forever) if disk is not a concern.
    # Analytics windows are clamped to this value so a report can never mix a
    # full-period fuel total with a truncated distance total.
    gps_history_retention_days: int = Field(default=90, alias="GPS_HISTORY_RETENTION_DAYS")
    # Rows deleted per statement. Batched so a first purge on a table that has
    # grown to millions of rows never takes a long lock or blows up the WAL.
    gps_purge_batch_size: int = Field(default=10_000, alias="GPS_PURGE_BATCH_SIZE")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    use_redis_refresh_tokens: bool = Field(default=False, alias="USE_REDIS_REFRESH_TOKENS")

    # ---- Database connection pool (ignored for SQLite) ----
    db_pool_size: int = Field(default=10, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, alias="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")
    db_pool_recycle: int = Field(default=1800, alias="DB_POOL_RECYCLE")

    # ---- Observability ----
    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")

    # ---- Reports ----
    # Calendar-period reports need local boundaries: a month that starts at
    # 00:00 UTC starts at 05:00 on the 1st in Tashkent, which files the first
    # five hours of business under the previous month.
    report_timezone: str = Field(default="Asia/Tashkent", alias="REPORT_TIMEZONE")

    # ---- Push notifications (Expo) ----
    # Expo's push endpoint accepts unauthenticated sends, so this is optional
    # and delivery works without it. Set it once a project switches on Expo's
    # "enhanced security", which then requires the header.
    expo_access_token: str = Field(default="", alias="EXPO_ACCESS_TOKEN")

    ai_api_key: str = Field(default="", alias="AI_API_KEY")
    ai_base_url: str = Field(default="https://api.openai.com/v1", alias="AI_BASE_URL")
    ai_model: str = Field(default="gpt-4o-mini", alias="AI_MODEL")

    # ---- Object storage (DigitalOcean Spaces, S3-compatible) ----
    # All default to empty so the app boots without storage configured; document
    # uploads return 503 until these are set. ``spaces_endpoint`` is optional —
    # when empty it is derived from the region.
    spaces_key: str = Field(default="", alias="SPACES_KEY")
    spaces_secret: str = Field(default="", alias="SPACES_SECRET")
    spaces_region: str = Field(default="fra1", alias="SPACES_REGION")
    spaces_bucket: str = Field(default="", alias="SPACES_BUCKET")
    spaces_endpoint: str = Field(default="", alias="SPACES_ENDPOINT")

    # ---- Local-disk document storage (active backend) ----
    # Trip documents are stored on a persistent volume and served via signed
    # API URLs. ``api_public_url`` is the API's externally reachable base
    # (e.g. https://fleetapi.eduly.uz) so signed file URLs work cross-origin.
    upload_dir: str = Field(default="/data/uploads", alias="UPLOAD_DIR")
    api_public_url: str = Field(default="", alias="API_PUBLIC_URL")

    # Background scheduler — disabled automatically under tests (env == "test").
    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    scheduler_interval_minutes: int = Field(default=15, alias="SCHEDULER_INTERVAL_MINUTES")

    # ---- Telegram notifications (customer-facing) ----
    # Empty ``telegram_bot_token`` means the feature is disabled: the webhook
    # returns 404, subscription-link generation still works so dispatchers can
    # be onboarded, and the scheduler job is a no-op. Enable by creating a bot
    # via @BotFather and setting TELEGRAM_BOT_TOKEN + TELEGRAM_BOT_USERNAME.
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_bot_username: str = Field(default="", alias="TELEGRAM_BOT_USERNAME")
    # Shared secret Telegram passes back in the ``X-Telegram-Bot-Api-Secret-Token``
    # header on webhook calls. Set the same value when registering the webhook
    # via setWebhook. Empty = skip verification (fine for dev / long-polling).
    telegram_webhook_secret: str = Field(default="", alias="TELEGRAM_WEBHOOK_SECRET")
    # Hour of the day (0-23, UTC) when the daily "where is my cargo" batch fires.
    # Uzbekistan is UTC+5, so 3 UTC = 08:00 local — a sensible default.
    telegram_daily_hour_utc: int = Field(default=3, alias="TELEGRAM_DAILY_HOUR_UTC")
    # Externally reachable base URL of this API (e.g. https://fleetapi.eduly.uz),
    # used to register the Telegram webhook (setWebhook) on startup. Empty =
    # skip registration with a startup warning; the bot can still be wired up
    # manually via the Telegram Bot API.
    public_api_url: str = Field(default="", alias="PUBLIC_API_URL")

    @property
    def is_prod(self) -> bool:
        return self.env.lower() in {"prod", "production"}

    @property
    def spaces_configured(self) -> bool:
        """True when the minimum credentials for object storage are present."""
        return bool(self.spaces_key and self.spaces_secret and self.spaces_bucket)

    @property
    def spaces_endpoint_url(self) -> str:
        """The Spaces endpoint, derived from the region when not set explicitly."""
        return self.spaces_endpoint or f"https://{self.spaces_region}.digitaloceanspaces.com"

    @property
    def telegram_configured(self) -> bool:
        """True when a bot token is set — feature-gate for the notification stack."""
        return bool(self.telegram_bot_token.strip())

    @property
    def telegram_daily_hour(self) -> int:
        """Clamp the configured daily-batch hour to a valid 0-23 range."""
        h = self.telegram_daily_hour_utc
        return h if 0 <= h <= 23 else 3

    @property
    def redis_enabled(self) -> bool:
        """Use Redis for refresh-token revocation, rate-limit storage and the
        scheduler lock whenever explicitly enabled OR running in production.

        In production this is forced on so horizontal scaling (multiple workers /
        replicas) is correct: shared revocation, shared rate limits, single-fire
        scheduled jobs. It fails loudly if Redis is unreachable rather than
        silently degrading to per-process in-memory state.
        """
        return self.use_redis_refresh_tokens or self.is_prod

    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def gps_keys_set(self) -> set[str]:
        return {k.strip() for k in self.gps_api_keys.split(",") if k.strip()}

settings = Settings()
