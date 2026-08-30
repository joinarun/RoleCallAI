"""Firestore-backed fixed-window limits that remain available while GKE sleeps."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.domain.errors import RateLimitError
from app.domain.repository import Repository


class DurableRateLimiter:
    def __init__(self, repository: Repository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def enforce(
        self,
        category: str,
        subject: str,
        limit: int,
        window: timedelta,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        key = self._privacy_key(category, subject)
        count = self.repository.count_login_failures(key, timestamp - window)
        self.repository.record_login_failure(key, timestamp, timestamp + window)
        if count + 1 > limit:
            raise RateLimitError("Rate limit exceeded")

    def _privacy_key(self, category: str, subject: str) -> str:
        digest = hmac.new(
            self.settings.cookie_signing_key.get_secret_value().encode("utf-8"),
            f"{category}\0{subject}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"rate:{category}:{digest}"
