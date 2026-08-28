"""Transactional-outbox publisher used by the reconciliation job."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Protocol

from google.cloud import pubsub_v1

from app.container import Container


class PublishFuture(Protocol):
    def result(self, timeout: float | None = None) -> str: ...


class Publisher(Protocol):
    def topic_path(self, project: str, topic: str) -> str: ...
    def publish(self, topic: str, data: bytes, **attrs: str) -> PublishFuture: ...


def drain_outbox(
    container: Container,
    publisher: Publisher | None = None,
    limit: int = 100,
) -> dict[str, int]:
    publisher = publisher or pubsub_v1.PublisherClient()
    published = 0
    failed = 0
    for record in container.repository.list_pending_outbox(limit):
        record.attempts += 1
        container.repository.save_outbox(record)
        try:
            topic_path = publisher.topic_path(container.settings.project_id, record.topic)
            future = publisher.publish(
                topic_path,
                json.dumps(record.payload, separators=(",", ":")).encode(),
                aggregate_id=record.aggregate_id,
                outbox_id=record.id,
            )
            future.result(timeout=30)
            record.published_at = datetime.now(UTC)
            container.repository.save_outbox(record)
            published += 1
        except Exception:
            failed += 1
    return {"published": published, "failed": failed}
