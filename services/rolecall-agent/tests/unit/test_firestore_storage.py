from __future__ import annotations

from app.domain.models import Room
from app.storage.firestore import _data


def test_firestore_storage_uses_snake_case_schema() -> None:
    room = Room(
        id="room-storage-contract",
        name="Storage contract",
        normalized_name="storage contract",
        expected_participants=2,
        duration_minutes=5,
        role="SCRUM_MASTER",
        agent_name="Nova",
        instructions="",
        admin_capability_digest="admin-digest",
        slots=[],
        occurrence_counter=3,
        active_occurrence_id="occ-active",
    )

    stored = _data(room)

    assert stored["occurrence_counter"] == 3
    assert stored["active_occurrence_id"] == "occ-active"
    assert "occurrenceCounter" not in stored
    assert "activeOccurrenceId" not in stored
