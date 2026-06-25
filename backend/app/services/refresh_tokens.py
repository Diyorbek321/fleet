from __future__ import annotations

from typing import Optional
from datetime import timedelta
from app.core.config import settings

try:
    import redis.asyncio as redis
except Exception:  # pragma: no cover
    redis = None

class RefreshTokenStore:
    def __init__(self) -> None:
        self._mem: set[str] = set()
        self._redis = None

    async def init(self) -> None:
        if settings.redis_enabled:
            if redis is None:
                raise RuntimeError("redis package not available")
            self._redis = redis.from_url(settings.redis_url, decode_responses=True)

    async def put(self, token: str) -> None:
        if self._redis:
            await self._redis.setex(f"refresh:{token}", timedelta(days=settings.refresh_token_expire_days), "1")
        else:
            self._mem.add(token)

    async def exists(self, token: str) -> bool:
        if self._redis:
            val = await self._redis.get(f"refresh:{token}")
            return val is not None
        return token in self._mem

    async def revoke(self, token: str) -> None:
        if self._redis:
            await self._redis.delete(f"refresh:{token}")
        else:
            self._mem.discard(token)

refresh_store = RefreshTokenStore()
