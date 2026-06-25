from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# In production (or whenever Redis is enabled) the limiter MUST use shared Redis
# storage, otherwise each uvicorn worker/replica keeps its own counters and the
# effective limit becomes N× the configured value — defeating login brute-force
# protection behind a load balancer. In dev/test we fall back to in-memory.
_storage_uri = settings.redis_url if settings.redis_enabled else None

limiter = Limiter(key_func=get_remote_address, storage_uri=_storage_uri)
