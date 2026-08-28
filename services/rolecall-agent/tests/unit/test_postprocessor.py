from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.container import Container
from app.domain.enums import OccurrenceStatus
from app.domain.models import JoinRequest, MeetingRecap, RoomCreate
from app.jobs.postprocessor import ProcessingScope, bind_processing_scope, persist_recap


@pytest.mark.asyncio
async def test_recap_completion_is_atomic_remembered_and_broadcast(container: Container) -> None:
    created = container.rooms.create(
        RoomCreate(
            name="Post-processing room",
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
    processing = container.meetings.finish(occurrence.id, "test_complete")
    assert processing.status == OccurrenceStatus.PROCESSING

    add_recap = AsyncMock()
    container.memory.add_recap = add_recap  # type: ignore[method-assign]
    recap = MeetingRecap(summary="Ada owns the next prototype step.")

    with bind_processing_scope(ProcessingScope(container, occurrence.id)):
        await persist_recap(recap.model_dump(mode="json"), None)  # type: ignore[arg-type]
        await persist_recap(recap.model_dump(mode="json"), None)  # type: ignore[arg-type]

    completed = container.repository.get_occurrence(occurrence.id)
    assert completed.status == OccurrenceStatus.COMPLETED
    assert completed.recap == recap
    assert completed.memory_persisted_at is not None
    assert container.repository.get_room(room.id).active_occurrence_id is None
    add_recap.assert_awaited_once()
    assert (occurrence.id, "meeting.state") in container.livekit.published  # type: ignore[attr-defined]
    assert (occurrence.id, "recap.ready") in container.livekit.published  # type: ignore[attr-defined]
