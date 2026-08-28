from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.agent_tools import (
    MeetingToolScope,
    bind_meeting_scope,
    finish_meeting,
    get_meeting_state,
    record_outcome,
)
from app.container import Container
from app.domain.enums import FloorOwnerType, GameType, OccurrenceStatus, RoleType
from app.domain.errors import ConflictError, UnauthorizedError
from app.domain.models import (
    JoinRequest,
    RoomCreate,
    RoomPatch,
    TranscriptSegment,
)
from app.domain.normalization import normalize_room_name
from app.domain.roles import ROLE_PROMPTS
from app.live.audio import FloorAudioFramer, Pcm16FrameBuffer, frame_pcm16, resample_pcm16


def create_room(container: Container, name: str = "Daily Sync", participants: int = 2):
    return container.rooms.create(
        RoomCreate(
            name=name,
            expected_participants=participants,
            duration_minutes=5,
            role=RoleType.SCRUM_MASTER,
            agent_name="Nova",
            instructions="Ask about blockers.",
        )
    )


def test_room_names_are_nfkc_casefolded_and_unique(container: Container) -> None:
    assert normalize_room_name("  \uff24aily   SYNC ") == "daily sync"
    create_room(container, "\uff24aily   SYNC")
    with pytest.raises(ConflictError):
        create_room(container, "daily sync")


def test_room_validation_boundaries() -> None:
    with pytest.raises(ValidationError):
        RoomCreate(
            name="Too small",
            expected_participants=1,
            duration_minutes=5,
            role="SCRUM_MASTER",
            agent_name="Nova",
        )
    with pytest.raises(ValidationError):
        RoomCreate(
            name="Too long",
            expected_participants=2,
            duration_minutes=61,
            role="SCRUM_MASTER",
            agent_name="Nova",
        )


def test_every_builtin_role_has_substantial_trusted_guidance() -> None:
    assert set(ROLE_PROMPTS) == set(RoleType)
    for role, prompt in ROLE_PROMPTS.items():
        assert len(prompt) >= 120, role
        assert "At the end" in prompt or role == RoleType.CUSTOM


def test_capabilities_are_hashed_exchanged_and_revoked(container: Container) -> None:
    created = create_room(container)
    room = container.repository.get_room(created.room.id)
    seat_url = created.seat_urls[0]["url"]
    secret = seat_url.split("#cap=", 1)[1]
    assert secret not in room.slots[0].capability_digest
    cookie, claims = container.capabilities.exchange(room.id, secret)
    assert container.capabilities.authenticate(cookie).slot_id == claims.slot_id
    replacement = container.rooms.regenerate_seat(room.id, room.slots[0].id)
    assert replacement != seat_url
    with pytest.raises(UnauthorizedError):
        container.capabilities.authenticate(cookie)


def test_room_update_normalizes_game_and_revokes_removed_seat_sessions(
    container: Container,
) -> None:
    created = container.rooms.create(
        RoomCreate(
            name="Friday room",
            expected_participants=3,
            duration_minutes=15,
            role=RoleType.FUN_FRIDAY,
            agent_name="Pixel",
            game=GameType.CATEGORIES,
        )
    )
    removed_url = created.seat_urls[2]["url"]
    removed_secret = removed_url.split("#cap=", 1)[1]
    removed_cookie, _ = container.capabilities.exchange(created.room.id, removed_secret)

    updated = container.rooms.update(
        created.room.id,
        RoomPatch(
            role=RoleType.SCRUM_MASTER,
            expected_participants=2,
            duration_minutes=30,
            agent_name="Nova Prime",
        ),
    )
    assert updated.room.game is None
    assert updated.room.duration_minutes == 30
    assert updated.room.agent_name == "Nova Prime"
    with pytest.raises(UnauthorizedError):
        container.capabilities.authenticate(removed_cookie)
    with pytest.raises(ValueError, match="Fun Friday"):
        container.rooms.update(
            created.room.id,
            RoomPatch(game=GameType.WOULD_YOU_RATHER),
        )


def test_first_arrival_creates_one_occurrence_and_duplicate_connection_is_rejected(
    container: Container,
) -> None:
    created = create_room(container)
    room = container.repository.get_room(created.room.id)
    first = container.meetings.join(
        room.id,
        room.slots[0].id,
        JoinRequest(name="Arun", consent_version="v1", connection_id="connection-a"),
    )
    same = container.meetings.get_or_create_occurrence(room.id)
    assert first.id == same.id
    assert first.status == OccurrenceStatus.LOBBY
    persisted_room = container.repository.get_room(room.id)
    assert persisted_room.active_occurrence_id == first.id
    assert persisted_room.occurrence_counter == 1
    with pytest.raises(ConflictError):
        container.meetings.join(
            room.id,
            room.slots[0].id,
            JoinRequest(name="Arun clone", consent_version="v1", connection_id="connection-b"),
        )
    with pytest.raises(ConflictError, match="idle"):
        container.rooms.update(room.id, RoomPatch(duration_minutes=10))
    with pytest.raises(ConflictError, match="idle"):
        container.rooms.regenerate_seat(room.id, room.slots[0].id)


def test_all_expected_seats_auto_start_and_late_start_obeys_grace(container: Container) -> None:
    created = create_room(container)
    room = container.repository.get_room(created.room.id)
    now = datetime(2026, 8, 27, 10, 0, tzinfo=UTC)
    occurrence = container.meetings.join(
        room.id,
        room.slots[0].id,
        JoinRequest(name="One", consent_version="v1", connection_id="connection-1"),
        now,
    )
    with pytest.raises(ConflictError):
        container.meetings.start(occurrence.id, room.slots[0].id, now + timedelta(seconds=119))
    started = container.meetings.start(
        occurrence.id, room.slots[0].id, now + timedelta(seconds=120)
    )
    assert started.status == OccurrenceStatus.RUNNING
    assert room.slots[1].id in started.absent_slot_ids

    other = create_room(container, "Second room")
    other_room = container.repository.get_room(other.room.id)
    container.meetings.join(
        other_room.id,
        other_room.slots[0].id,
        JoinRequest(name="One", consent_version="v1", connection_id="connection-1"),
        now,
    )
    auto = container.meetings.join(
        other_room.id,
        other_room.slots[1].id,
        JoinRequest(name="Two", consent_version="v1", connection_id="connection-2"),
        now + timedelta(seconds=3),
    )
    assert auto.status == OccurrenceStatus.RUNNING
    assert auto.turn_order == [slot.id for slot in other_room.slots]


def test_floor_transitions_hand_raise_disconnect_hold_and_timer(container: Container) -> None:
    created = create_room(container)
    room = container.repository.get_room(created.room.id)
    now = datetime(2026, 8, 27, 10, 0, tzinfo=UTC)
    container.meetings.join(
        room.id,
        room.slots[0].id,
        JoinRequest(name="One", consent_version="v1", connection_id="connection-1"),
        now,
    )
    occurrence = container.meetings.join(
        room.id,
        room.slots[1].id,
        JoinRequest(name="Two", consent_version="v1", connection_id="connection-2"),
        now,
    )
    occurrence = container.meetings.give_floor(occurrence.id, room.slots[0].id, "Status?")
    assert occurrence.current_floor_type == FloorOwnerType.SEAT
    repeated = container.meetings.give_floor(occurrence.id, room.slots[0].id, "Status?")
    assert repeated.sequence == occurrence.sequence
    with pytest.raises(ConflictError, match="advance_floor"):
        container.meetings.give_floor(occurrence.id, room.slots[1].id, "Skip rotation")
    container.meetings.raise_hand(occurrence.id, room.slots[1].id)
    handoff = container.meetings.advance_floor(occurrence.id)
    assert handoff.current_floor_type == FloorOwnerType.AGENT
    assert handoff.current_floor_slot_id is None
    assert handoff.next_floor_slot_id == room.slots[1].id
    container.meetings.give_floor(occurrence.id, room.slots[1].id, "What is your update?")
    container.meetings.disconnect(occurrence.id, room.slots[1].id, now)
    held = container.meetings.tick(occurrence.id, now + timedelta(seconds=29))
    assert held.current_floor_slot_id == room.slots[1].id
    skipped = container.meetings.tick(occurrence.id, now + timedelta(seconds=30))
    assert skipped.current_floor_type == FloorOwnerType.AGENT
    assert skipped.current_floor_slot_id is None
    assert skipped.next_floor_slot_id == room.slots[0].id
    running_sequence = skipped.sequence
    ending = container.meetings.tick(occurrence.id, now + timedelta(minutes=3))
    assert ending.status == OccurrenceStatus.ENDING
    assert ending.sequence > running_sequence
    processing = container.meetings.tick(occurrence.id, now + timedelta(minutes=6))
    assert processing.status == OccurrenceStatus.PROCESSING
    assert processing.sequence > ending.sequence
    assert any(
        item.aggregate_id == occurrence.id for item in container.repository.list_pending_outbox()
    )


def test_reconnect_requires_the_original_connection_identity(container: Container) -> None:
    created = create_room(container)
    room = container.repository.get_room(created.room.id)
    occurrence = container.meetings.join(
        room.id,
        room.slots[0].id,
        JoinRequest(name="One", consent_version="v1", connection_id="connection-original"),
    )
    disconnected = container.meetings.disconnect(occurrence.id, room.slots[0].id)
    with pytest.raises(ConflictError, match="Reconnect identity"):
        container.meetings.reconnect(room.id, room.slots[0].id, "connection-imposter")
    reconnected = container.meetings.reconnect(room.id, room.slots[0].id, "connection-original")
    assert reconnected.attendance[room.slots[0].id].connected
    assert reconnected.sequence > disconnected.sequence


def test_intentional_leave_skips_floor_and_finishes_when_last_person_leaves(
    container: Container,
) -> None:
    created = create_room(container)
    room = container.repository.get_room(created.room.id)
    first = container.meetings.join(
        room.id,
        room.slots[0].id,
        JoinRequest(name="One", consent_version="v1", connection_id="connection-one"),
    )
    occurrence = container.meetings.join(
        room.id,
        room.slots[1].id,
        JoinRequest(name="Two", consent_version="v1", connection_id="connection-two"),
    )
    container.meetings.give_floor(first.id, room.slots[0].id, "Your update?")

    left = container.meetings.leave(occurrence.id, room.slots[0].id, "connection-one")
    assert left.current_floor_type == FloorOwnerType.AGENT
    assert left.next_floor_slot_id == room.slots[1].id
    assert left.attendance[room.slots[0].id].left_at is not None
    with pytest.raises(ConflictError, match="identity"):
        container.meetings.leave(occurrence.id, room.slots[1].id, "wrong-connection")

    finished = container.meetings.leave(occurrence.id, room.slots[1].id, "connection-two")
    assert finished.status == OccurrenceStatus.PROCESSING


def test_finish_outbox_is_idempotent_and_does_not_reset_published_state(
    container: Container,
) -> None:
    created = create_room(container)
    room = container.repository.get_room(created.room.id)
    occurrence = container.meetings.join(
        room.id,
        room.slots[0].id,
        JoinRequest(name="One", consent_version="v1", connection_id="connection-one"),
    )
    first = container.meetings.finish(occurrence.id, "manual_test")
    record = container.repository.list_pending_outbox()[0]
    record.published_at = datetime.now(UTC)
    container.repository.save_outbox(record)

    second = container.meetings.finish(occurrence.id, "manual_test")

    assert second.sequence == first.sequence
    assert container.repository.list_pending_outbox() == []


def test_tools_are_bound_and_outcomes_are_idempotent(container: Container) -> None:
    created = create_room(container)
    room = container.repository.get_room(created.room.id)
    occurrence = container.meetings.join(
        room.id,
        room.slots[0].id,
        JoinRequest(name="One", consent_version="v1", connection_id="connection-1"),
    )
    scope = MeetingToolScope(
        occurrence.id,
        container.repository,
        container.meetings,
        container.memory,
    )
    with bind_meeting_scope(scope):
        assert get_meeting_state()["participants"][0]["name"] == "One"
        first = record_outcome("ACTION", "Send the plan", room.slots[0].id)
        second = record_outcome("ACTION", "Send the plan", room.slots[0].id)
    assert first["outcomeId"] == second["outcomeId"]
    assert len(container.repository.get_occurrence(occurrence.id).outcomes) == 1


def test_live_finish_tool_defers_processing_until_worker_playout(container: Container) -> None:
    created = create_room(container)
    room = container.repository.get_room(created.room.id)
    container.meetings.join(
        room.id,
        room.slots[0].id,
        JoinRequest(name="One", consent_version="v1", connection_id="connection-1"),
    )
    occurrence = container.meetings.join(
        room.id,
        room.slots[1].id,
        JoinRequest(name="Two", consent_version="v1", connection_id="connection-2"),
    )
    requested: list[str] = []
    scope = MeetingToolScope(
        occurrence.id,
        container.repository,
        container.meetings,
        container.memory,
        defer_finish=requested.append,
    )

    with bind_meeting_scope(scope):
        result = finish_meeting("normal_completion")

    assert result == {
        "status": "ok",
        "phase": "RUNNING",
        "completion": "after_audio_playout",
    }
    assert requested == ["normal_completion"]
    assert container.repository.get_occurrence(occurrence.id).status == OccurrenceStatus.RUNNING
    assert container.repository.list_pending_outbox() == []


def test_pcm_resampling_and_framing() -> None:
    source = (b"\x00\x00\xff\x7f\x00\x80\x00\x00") * 160
    doubled = resample_pcm16(source, 16000, 32000)
    assert len(doubled) == len(source) * 2
    frames = list(frame_pcm16(doubled * 8, 32000, 80))
    assert all(len(frame) <= 32000 * 80 // 1000 * 2 for frame in frames)
    with pytest.raises(ValueError):
        list(frame_pcm16(source, 16000, 20))

    buffer = Pcm16FrameBuffer(sample_rate=16000, frame_ms=80)
    frame_bytes = 16000 * 80 // 1000 * 2
    assert buffer.push(b"\0\0" * 320) == []
    buffered = buffer.push(b"\0\0" * 960)
    assert [len(frame) for frame in buffered] == [frame_bytes]

    floor_buffer = FloorAudioFramer(sample_rate=16000, frame_ms=80)
    chunks = [b"\0\0" * 160 for _ in range(8)]
    scoped = [frame for chunk in chunks for frame in floor_buffer.push("seat-1", 7, chunk)]
    assert len(scoped) == 1
    assert scoped[0].slot_id == "seat-1"
    assert scoped[0].floor_epoch == 7
    # A floor handoff discards a partial frame instead of leaking it to the next speaker.
    floor_buffer.push("seat-1", 7, b"\0\0" * 160)
    assert floor_buffer.push("seat-2", 8, b"\0\0" * 1120) == []


def test_final_transcript_expiry(container: Container) -> None:
    created = create_room(container)
    room = container.repository.get_room(created.room.id)
    occurrence = container.meetings.join(
        room.id,
        room.slots[0].id,
        JoinRequest(name="One", consent_version="v1", connection_id="connection-1"),
    )
    now = datetime.now(UTC)
    segment = TranscriptSegment(
        id="segment-1",
        occurrence_id=occurrence.id,
        sequence=1,
        speaker_type="SEAT",
        speaker_id=room.slots[0].id,
        speaker_name="One",
        text="Final words only",
        started_at=now,
        ended_at=now,
        expires_at=now + timedelta(days=90),
    )
    container.repository.save_transcript_segment(segment)
    assert container.repository.list_transcript_segments(occurrence.id) == [segment]
