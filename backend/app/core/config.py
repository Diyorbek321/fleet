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
    refresh_token_expire_days: int = Field(default=7, alias="REFRESH_TOKEN_EXPIRE_DAYS")

    cors_origins: str = Field(default="", alias="CORS_ORIGINS")

    gps_api_keys: str = Field(default="", alias="GPS_API_KEYS")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    use_redis_refresh_tokens: bool = Field(default=False, alias="USE_REDIS_REFRESH_TOKENS")

    # ---- Database connection pool (ignored for SQLite) ----
    db_pool_size: int = Field(default=10, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, alias="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")
    db_pool_recycle: int = Field(default=1800, alias="DB_POOL_RECYCLE")

    # ---- Observability ----
    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")

    ai_api_key: str = Field(default="", alias="AI_API_KEY")
    ai_base_url: str = Field(default="https://api.openai.com/v1", alias="AI_BASE_URL")
    ai_model: str = Field(default="gpt-4o-mini", alias="AI_MODEL")

    # Background scheduler — disabled automatically under tests (env == "test").
    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    scheduler_interval_minutes: int = Field(default=15, alias="SCHEDULER_INTERVAL_MINUTES")

    @property
    def is_prod(self) -> bool:
        return self.env.lower() in {"prod", "production"}

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
