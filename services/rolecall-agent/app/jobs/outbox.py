"""Transactional-outbox publisher used by the reconciliation job."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Protocol

from google.cloud import pubsub_v1

from app.config import Settings
from app.container import Container
from app.domain.repository import Repository


class PublishFuture(Protocol):
    def result(self, timeout: float | None = None) -> str: ...


class Publisher(Protocol):
    def topic_path(self, project: str, topic: str) -> str: ...
    def publish(self, topic: str, data: bytes, **attrs: str) -> PublishFuture: ...


def publish_outbox_record(
    settings: Settings,
    repository: Repository,
    record_id: str,
    publisher: Publisher | None = None,
) -> bool:
    """Publish one known outbox record now; the scheduler remains its retry path."""
    record = repository.get_outbox(record_id)
    if record.published_at is not None:
        return False
    publisher = publisher or pubsub_v1.PublisherClient()
    record.attempts += 1
    repository.save_outbox(record)
    topic_path = publisher.topic_path(settings.project_id, record.topic)
    future = publisher.publish(
        topic_path,
        json.dumps(record.payload, separators=(",", ":")).encode(),
        aggregate_id=record.aggregate_id,
        outbox_id=record.id,
    )
    future.result(timeout=30)
    record.published_at = datetime.now(UTC)
    repository.save_outbox(record)
    return True


def drain_outbox(
    container: Container,
    publisher: Publisher | None = None,
    limit: int = 100,
) -> dict[str, int]:
    publisher = publisher or pubsub_v1.PublisherClient()
    published = 0
    failed = 0
    for record in container.repository.list_pending_outbox(limit):
        try:
            if publish_outbox_record(
                container.settings, container.repository, record.id, publisher
            ):
                published += 1
        except Exception:
            failed += 1
    return {"published": published, "failed": failed}
