from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from app.config import Settings
from app.container import create_container
from app.domain.enums import OccurrenceStatus
from app.domain.models import JoinRequest, RoomCreate
from app.storage.firestore import FirestoreRepository


@pytest.mark.skipif(
    not os.getenv("FIRESTORE_EMULATOR_HOST"),
    reason="requires FIRESTORE_EMULATOR_HOST",
)
def test_named_firestore_transactions_preserve_concurrent_arrivals() -> None:
    settings = Settings(env="test", repository="firestore")
    repository = FirestoreRepository(settings.project_id, settings.firestore_database)
    container = create_container(settings, repository)
    created = container.rooms.create(
        RoomCreate(
            name=f"Concurrent emulator {uuid4().hex}",
            expected_participants=2,
            duration_minutes=5,
            role="SCRUM_MASTER",
            agent_name="Nova",
        )
    )
    room = repository.get_room(created.room.id)

    def join(index: int):  # type: ignore[no-untyped-def]
        slot = room.slots[index]
        return container.meetings.join(
            room.id,
            slot.id,
            JoinRequest(
                name=f"Person {index + 1}",
                consent_version="v1",
                connection_id=f"connection-{index + 1}",
            ),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        arrivals = list(executor.map(join, range(2)))

    occurrence = repository.get_occurrence(arrivals[-1].id)
    persisted_room = repository.get_room(room.id)
    assert occurrence.status == OccurrenceStatus.RUNNING
    assert len(occurrence.attendance) == 2
    assert persisted_room.active_occurrence_id == occurrence.id
    assert persisted_room.occurrence_counter == 1

    delegated = container.rooms.set_end_meeting_permission(room.id, room.slots[0].id, True)
    assert delegated.slots[0].can_end_meeting is True
    assert room.slots[0].id in repository.get_occurrence(occurrence.id).end_meeting_slot_ids

    container.meetings.finish(occurrence.id, "emulator_test")

    def complete(current):  # type: ignore[no-untyped-def]
        current.status = OccurrenceStatus.COMPLETED
        return current

    repository.mutate_occurrence(occurrence.id, complete)
    assert repository.get_room(room.id).active_occurrence_id is None

    next_occurrence = container.meetings.join(
        room.id,
        room.slots[0].id,
        JoinRequest(
            name="Person 1",
            consent_version="v1",
            connection_id="connection-next",
        ),
    )
    assert next_occurrence.number == 2
