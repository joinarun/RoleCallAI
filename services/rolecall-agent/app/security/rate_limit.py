"""Redis-backed fixed-window limits with a process-local development fallback."""

from __future__ import annotations

import hashlib
import time
from threading import RLock

import redis

from app.config import Settings
from app.domain.errors import RateLimitError


class RateLimiter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self.local: dict[str, tuple[int, float]] = {}
        self.lock = RLock()

    @staticmethod
    def privacy_key(category: str, value: str) -> str:
        digest = hashlib.sha256(value.encode()).hexdigest()[:24]
        return f"rolecall:rate:{category}:{digest}"

    def enforce(self, key: str, limit: int, window_seconds: int) -> None:
        try:
            pipeline = self.redis.pipeline()
            pipeline.incr(key)
            pipeline.ttl(key)
            count, ttl = pipeline.execute()
            if ttl < 0:
                self.redis.expire(key, window_seconds)
            if int(count) > limit:
                raise RateLimitError("Rate limit exceeded")
            return
        except RateLimitError:
            raise
        except redis.RedisError:
            if self.settings.env not in {"local", "test"}:
                raise

        now = time.monotonic()
        with self.lock:
            count, deadline = self.local.get(key, (0, now + window_seconds))
            if now >= deadline:
                count, deadline = 0, now + window_seconds
            count += 1
            self.local[key] = (count, deadline)
            if count > limit:
                raise RateLimitError("Rate limit exceeded")
