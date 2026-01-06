"""
Core modules - cache, storage, CDP queue.
"""
from app.core.cache import ContentCache, content_cache
from app.core.storage import JobStorage, RedisJobStorage, InMemoryJobStorage, storage, redis_client
from app.core.cdp_queue import fetch_with_cdp, shutdown_cdp_pool, CDPWorkerPool

__all__ = [
    "ContentCache", "content_cache",
    "JobStorage", "RedisJobStorage", "InMemoryJobStorage", "storage", "redis_client",
    "fetch_with_cdp", "shutdown_cdp_pool", "CDPWorkerPool",
]
