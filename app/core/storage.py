"""
Job storage implementations (Redis and In-Memory).
"""
import time
import redis
from abc import ABC, abstractmethod
from typing import Dict, Optional

from app.logging_config import logger
from app.config import REDIS_HOST, REDIS_PORT


# Storage interface and implementations
class JobStorage(ABC):
    @abstractmethod
    def set(self, key: str, value: str, expiry: int = None) -> None:
        pass

    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        pass

    @abstractmethod
    def ping(self) -> bool:
        pass


class RedisJobStorage(JobStorage):
    def __init__(self, host: str, port: int):
        self.client = redis.Redis(host=host, port=port, decode_responses=True)
        self.host = host
        self.port = port

    def set(self, key: str, value: str, expiry: int = None) -> None:
        self.client.set(key, value, ex=expiry)

    def get(self, key: str) -> Optional[str]:
        return self.client.get(key)

    def ping(self) -> bool:
        try:
            self.client.ping()
            return True
        except Exception:
            return False


class InMemoryJobStorage(JobStorage):
    def __init__(self):
        self.data: Dict[str, str] = {}
        self.expiry_times: Dict[str, float] = {}

    def set(self, key: str, value: str, expiry: int = None) -> None:
        self.data[key] = value
        if expiry:
            self.expiry_times[key] = time.time() + expiry

    def get(self, key: str) -> Optional[str]:
        if key in self.data:
            if key in self.expiry_times and time.time() > self.expiry_times[key]:
                del self.data[key]
                del self.expiry_times[key]
                return None
            return self.data[key]
        return None

    def ping(self) -> bool:
        return True


class DummyRedisClient:
    """Wrapper that redirects Redis calls to in-memory storage."""
    def __init__(self, storage: InMemoryJobStorage):
        self.storage = storage

    def set(self, key: str, value: str, ex: int = None) -> None:
        return self.storage.set(key, value, expiry=ex)

    def get(self, key: str) -> Optional[str]:
        return self.storage.get(key)

    def ping(self) -> bool:
        return self.storage.ping()


def init_storage():
    """Initialize storage backend (Redis or in-memory fallback)."""
    try:
        storage = RedisJobStorage(host=REDIS_HOST, port=REDIS_PORT)
        if storage.ping():
            logger.info(f"Using Redis storage at {REDIS_HOST}:{REDIS_PORT}")
            return storage, storage.client
        else:
            logger.warning(f"Could not connect to Redis at {REDIS_HOST}:{REDIS_PORT}, falling back to in-memory storage")
            storage = InMemoryJobStorage()
            return storage, DummyRedisClient(storage)
    except Exception as e:
        logger.warning(f"Error initializing Redis: {str(e)}, using in-memory storage")
        storage = InMemoryJobStorage()
        return storage, DummyRedisClient(storage)


# Initialize storage
storage, redis_client = init_storage()
