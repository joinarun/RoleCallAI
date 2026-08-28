"""Opt-in tests for cloud contracts that cannot be delegated to ADK eval."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.config import Settings
from app.container import create_container
from app.domain.models import Attendance, MeetingRecap, Occurrence, RecapAction
from app.domain.repository import InMemoryRepository
from app.jobs.cleanup import cleanup_expired_agent_data
from app.retrieval.memory import RoomMemoryService


async def _wait_for_memory(
    memory: RoomMemoryService,
    room_id: str,
    marker: str,
    *,
    present: bool,
) -> list[dict[str, str]]:
    """Poll eventual Memory Bank indexing/deletion with a bounded timeout."""
    results: list[dict[str, str]] = []
    for _ in range(30):
        results = await memory.search(room_id, marker, "seat-stable")
        if bool(results) is present:
            return results
        await asyncio.sleep(2)
    return results


@pytest.mark.skipif(
    os.getenv("ROLECALL_RUN_CLOUD_INTEGRATION") != "1",
    reason="requires the approved/deployed EU development environment",
)
@pytest.mark.asyncio
async def test_two_sessions_recall_stable_seat_and_expiry() -> None:
    """Prove cross-session stable-seat recall and the scoped 90-day cleanup path."""
    settings = Settings(env="dev", repository="memory")
    assert settings.agent_engine_id, "ROLECALL_AGENT_ENGINE_ID must identify the dev engine"
    assert settings.region == "europe-west4"

    now = datetime.now(UTC)
    marker = f"RCLOUD-{uuid4().hex}"
    room_id = f"memory-contract-{uuid4().hex}"
    first_occurrence = Occurrence(
        id=f"{room_id}-session-1",
        room_id=room_id,
        number=1,
        lobby_deadline_at=now,
        ended_at=now,
        expires_at=now + timedelta(days=settings.retention_days),
        attendance={
            "seat-stable": Attendance(
                slot_id="seat-stable",
                display_name="Alex Before Rename",
                consent_version="phase1-v1",
                joined_at=now,
                connection_id=f"connection-{uuid4().hex}",
            )
        },
    )
    recap = MeetingRecap(
        summary=f"The team committed to the uniquely tagged task {marker}.",
        actions=[
            RecapAction(
                text=f"Deliver the tagged prototype {marker}",
                owner_slot_id="seat-stable",
            )
        ],
    )
    memory = RoomMemoryService(settings)
    await memory.add_recap(first_occurrence, recap)

    # This lookup represents a second meeting session where the participant's
    # display name may have changed; the stable seat ID remains the identity.
    recalled = await _wait_for_memory(memory, room_id, marker, present=True)
    assert recalled, "the second session did not recall the first session's commitment"
    assert any("seat-stable" in item["text"] or marker in item["text"] for item in recalled)

    container = create_container(settings, InMemoryRepository())
    deleted = await asyncio.to_thread(
        cleanup_expired_agent_data,
        container,
        now + timedelta(days=settings.retention_days + 1),
        room_id=room_id,
    )
    assert deleted["memories"] > 0

    after_expiry = await _wait_for_memory(memory, room_id, marker, present=False)
    assert not after_expiry, "expired memory remained searchable after scoped cleanup"
