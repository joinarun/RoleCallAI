from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import app.retrieval.memory as memory_module
from app.container import Container
from app.domain.models import (
    Attendance,
    MeetingRecap,
    Occurrence,
    RecapAction,
)
from app.retrieval.memory import RoomMemoryService


class FakeMemoryBank:
    def __init__(self) -> None:
        self.searches: list[dict[str, object]] = []
        self.additions: list[dict[str, object]] = []

    async def search_memory(self, **kwargs):  # type: ignore[no-untyped-def]
        self.searches.append(kwargs)
        return SimpleNamespace(
            memories=[
                SimpleNamespace(
                    id="memory-1",
                    content=SimpleNamespace(parts=[SimpleNamespace(text="Seat commitment")]),
                )
            ]
        )

    async def add_events_to_memory(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.additions.append(kwargs)


@pytest.mark.asyncio
async def test_memory_uses_room_session_and_stable_seat_scope(container: Container) -> None:
    container.settings.agent_engine_id = "engine-test"
    memory = RoomMemoryService(container.settings)
    fake = FakeMemoryBank()
    memory._service = fake  # type: ignore[assignment]

    found = await memory.search("room-stable", "What did I commit to?", "seat-stable")
    assert found == [{"id": "memory-1", "text": "Seat commitment"}]
    assert fake.searches[0]["user_id"] == "room-stable"
    assert fake.searches[0]["query"] == "stable seat seat-stable: What did I commit to?"

    now = datetime.now(UTC)
    occurrence = Occurrence(
        id="occurrence-two",
        room_id="room-stable",
        number=2,
        lobby_deadline_at=now,
        expires_at=now + timedelta(days=90),
        attendance={
            "seat-stable": Attendance(
                slot_id="seat-stable",
                display_name="Alex After Rename",
                consent_version="phase1-v1",
                joined_at=now,
                connection_id="connection-stable",
            )
        },
    )
    recap = MeetingRecap(
        summary="A concrete follow-up was assigned.",
        actions=[RecapAction(text="Ship the prototype", owner_slot_id="seat-stable")],
    )
    await memory.add_recap(occurrence, recap)

    addition = fake.additions[0]
    assert addition["user_id"] == "room-stable"
    assert addition["session_id"] == "occurrence-two"
    assert addition["custom_metadata"]["occurrence_id"] == "occurrence-two"  # type: ignore[index]


def test_memory_bank_extracts_id_from_full_reasoning_engine_name(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}

    def create_service(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return FakeMemoryBank()

    monkeypatch.setattr(memory_module, "VertexAiMemoryBankService", create_service)
    container.settings.agent_engine_id = (
        "projects/example-project/locations/europe-west4/reasoningEngines/123456"
    )

    RoomMemoryService(container.settings)._get_service()

    assert captured["agent_engine_id"] == "123456"
