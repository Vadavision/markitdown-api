"""
Content caching with TTL.
Extracted from api.py - DO NOT MODIFY unless updating source.
"""
import time
import hashlib
from typing import Dict, Optional

from app.logging_config import logger
from app.config import CACHE_TTL, CACHE_ENABLED


class ContentCache:
    """Simple in-memory cache with TTL for URL content."""

    def __init__(self, ttl: int = 3600):
        self.ttl = ttl
        self._cache: Dict[str, tuple[str, float]] = {}  # hash -> (content, timestamp)

    def _hash_key(self, url: str, query: Optional[str] = None) -> str:
        """Create a hash key from URL and optional query."""
        key = f"{url}:{query or ''}"
        return hashlib.md5(key.encode()).hexdigest()

    def get(self, url: str, query: Optional[str] = None) -> Optional[str]:
        """Get cached content if valid."""
        key = self._hash_key(url, query)
        if key in self._cache:
            content, timestamp = self._cache[key]
            if time.time() - timestamp < self.ttl:
                logger.info("cache_hit", url=url, key=key[:8])
                return content
            # Expired, remove it
            del self._cache[key]
        return None

    def set(self, url: str, content: str, query: Optional[str] = None) -> None:
        """Cache content with timestamp."""
        key = self._hash_key(url, query)
        self._cache[key] = (content, time.time())
        logger.info("cache_set", url=url, key=key[:8], size=len(content))

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()

    def cleanup_expired(self) -> int:
        """Remove expired entries, return count removed."""
        now = time.time()
        expired = [k for k, (_, ts) in self._cache.items() if now - ts >= self.ttl]
        for key in expired:
            del self._cache[key]
        return len(expired)


# Initialize content cache
content_cache = ContentCache(ttl=CACHE_TTL) if CACHE_ENABLED else None
