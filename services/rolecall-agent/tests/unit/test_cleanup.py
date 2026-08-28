from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.container import Container
from app.domain.enums import OccurrenceStatus
from app.domain.models import JoinRequest, RoomCreate
from app.jobs.cleanup import cleanup_expired, reconcile_active_occurrences


def test_cleanup_marks_stuck_postprocessing_failed_and_releases_room(
    container: Container,
) -> None:
    created = container.rooms.create(
        RoomCreate(
            name="Stuck processing room",
            expected_participants=2,
            duration_minutes=5,
            role="SCRUM_MASTER",
            agent_name="Nova",
        )
    )
    room = container.repository.get_room(created.room.id)
    occurrence = container.meetings.join(
        room.id,
        room.slots[0].id,
        JoinRequest(name="Ada", consent_version="v1", connection_id="connection-ada"),
    )
    container.meetings.finish(occurrence.id, "test_processing")
    now = datetime.now(UTC)

    def age(current):  # type: ignore[no-untyped-def]
        current.ended_at = now - timedelta(minutes=61)
        return current

    container.repository.mutate_occurrence(occurrence.id, age)
    counts = cleanup_expired(container, now)

    failed = container.repository.get_occurrence(occurrence.id)
    assert counts["stuckProcessing"] == 1
    assert failed.status == OccurrenceStatus.FAILED
    assert failed.failure_reason == "postprocessing_timeout"
    assert failed.expires_at == failed.ended_at + timedelta(days=container.settings.retention_days)
    assert container.repository.get_room(room.id).active_occurrence_id is None


def _running_occurrence(container: Container, name: str):  # type: ignore[no-untyped-def]
    created = container.rooms.create(
        RoomCreate(
            name=name,
            expected_participants=2,
            duration_minutes=5,
            role="SCRUM_MASTER",
            agent_name="Nova",
        )
    )
    room = container.repository.get_room(created.room.id)
    container.meetings.join(
        room.id,
        room.slots[0].id,
        JoinRequest(name="Ada", consent_version="v1", connection_id=f"{name}-ada"),
    )
    return container.meetings.join(
        room.id,
        room.slots[1].id,
        JoinRequest(name="Lin", consent_version="v1", connection_id=f"{name}-lin"),
    )


def test_reconciliation_finishes_a_meeting_after_agent_heartbeat_timeout(
    container: Container,
) -> None:
    occurrence = _running_occurrence(container, "Lost worker room")
    now = datetime.now(UTC)

    def lose_heartbeat(current):  # type: ignore[no-untyped-def]
        current.started_at = now - timedelta(seconds=90)
        current.agent_last_seen_at = now - timedelta(seconds=61)
        return current

    container.repository.mutate_occurrence(occurrence.id, lose_heartbeat)
    counts = reconcile_active_occurrences(container, now)

    closed = container.repository.get_occurrence(occurrence.id)
    assert counts == {"durationElapsed": 0, "agentRecoveryTimeout": 1}
    assert closed.status == OccurrenceStatus.PROCESSING
    assert closed.failure_reason == "agent_recovery_timeout"
    assert len(container.repository.list_pending_outbox(10)) == 1
    assert reconcile_active_occurrences(container, now) == {
        "durationElapsed": 0,
        "agentRecoveryTimeout": 0,
    }


def test_reconciliation_enforces_hard_end_but_preserves_healthy_meetings(
    container: Container,
) -> None:
    expired = _running_occurrence(container, "Expired timer room")
    healthy = _running_occurrence(container, "Healthy timer room")
    now = datetime.now(UTC)

    def expire_timer(current):  # type: ignore[no-untyped-def]
        current.started_at = now - timedelta(minutes=6, seconds=1)
        current.agent_last_seen_at = now
        return current

    def keep_healthy(current):  # type: ignore[no-untyped-def]
        current.started_at = now - timedelta(minutes=1)
        current.agent_last_seen_at = now - timedelta(seconds=15)
        return current

    container.repository.mutate_occurrence(expired.id, expire_timer)
    container.repository.mutate_occurrence(healthy.id, keep_healthy)
    counts = reconcile_active_occurrences(container, now)

    assert counts == {"durationElapsed": 1, "agentRecoveryTimeout": 0}
    assert container.repository.get_occurrence(expired.id).status == OccurrenceStatus.PROCESSING
    assert container.repository.get_occurrence(healthy.id).status == OccurrenceStatus.RUNNING
