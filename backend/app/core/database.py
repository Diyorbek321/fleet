from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool
from app.core.config import settings

# SQLite (dev) uses a different pool implementation that rejects QueuePool
# sizing kwargs, so only tune the pool for real (Postgres) engines.
_engine_kwargs: dict = {"echo": settings.debug, "pool_pre_ping": True}
if settings.env.lower() == "test":
    # Under pytest every test runs in its own event loop, but this engine is a
    # module-level singleton — a pooled asyncpg connection would be handed to a
    # loop that didn't open it ("attached to a different loop"). NullPool opens
    # and closes a connection per checkout, so nothing outlives its loop. Test
    # databases are local, so the extra connect cost is irrelevant.
    _engine_kwargs["poolclass"] = NullPool
elif not settings.is_sqlite():
    _engine_kwargs.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
    )

engine = create_async_engine(settings.database_url, **_engine_kwargs)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

class Base(DeclarativeBase):
    pass

async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
