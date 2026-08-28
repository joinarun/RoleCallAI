"""Server-scoped, idempotent ADK function tools.

The LiveKit worker binds a scope before entering ``Runner.run_live``. Tool
arguments intentionally contain no room, occurrence, or session IDs.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from app.domain.enums import OccurrenceStatus, OutcomeKind
from app.domain.errors import RoleCallError
from app.domain.repository import Repository
from app.retrieval.memory import RoomMemoryService
from app.services.meetings import MeetingService


@dataclass(frozen=True)
class MeetingToolScope:
    occurrence_id: str
    repository: Repository
    meetings: MeetingService
    memory: RoomMemoryService


_SCOPE: ContextVar[MeetingToolScope | None] = ContextVar("rolecall_tool_scope", default=None)


@contextmanager
def bind_meeting_scope(scope: MeetingToolScope):  # type: ignore[no-untyped-def]
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        _SCOPE.reset(token)


def _scope() -> MeetingToolScope:
    scope = _SCOPE.get()
    if scope is None:
        raise RuntimeError("Meeting tools require a server-bound occurrence scope")
    return scope


def get_meeting_state() -> dict[str, Any]:
    """Return the authoritative lifecycle, floor, attendance, and turn order."""
    scope = _scope()
    occurrence = scope.repository.get_occurrence(scope.occurrence_id)
    room = scope.repository.get_room(occurrence.room_id)
    return {
        "status": occurrence.status.value,
        "agentName": room.agent_name,
        "role": room.role.value,
        "participants": [
            {
                "slotId": slot_id,
                "name": attendance.display_name,
                "connected": attendance.connected,
            }
            for slot_id, attendance in occurrence.attendance.items()
        ],
        "absentSlotIds": occurrence.absent_slot_ids,
        "turnOrder": occurrence.turn_order,
        "currentFloor": {
            "type": occurrence.current_floor_type.value,
            "slotId": occurrence.current_floor_slot_id,
        },
        "handRaiseQueue": occurrence.hand_raise_queue,
    }


def set_phase(phase: OccurrenceStatus) -> dict[str, Any]:
    """Request a validated lifecycle transition using an OccurrenceStatus value."""
    scope = _scope()
    try:
        requested_phase = OccurrenceStatus(phase)
    except ValueError:
        return {"status": "rejected", "reason": "unknown lifecycle phase"}
    try:
        occurrence = scope.meetings.set_phase(scope.occurrence_id, requested_phase)
    except RoleCallError as exc:
        return {"status": "rejected", "reason": str(exc)[:240]}
    return {"status": "ok", "phase": occurrence.status.value}


def give_floor(slot_id: str, prompt: str) -> dict[str, Any]:
    """Give the audio floor to a connected stable seat with a short spoken prompt."""
    scope = _scope()
    try:
        occurrence = scope.meetings.give_floor(scope.occurrence_id, slot_id, prompt)
    except RoleCallError as exc:
        return {"status": "rejected", "reason": str(exc)[:240]}
    return {
        "status": "ok",
        "floorSlotId": occurrence.current_floor_slot_id,
        "sequence": occurrence.sequence,
    }


def advance_floor() -> dict[str, Any]:
    """Advance according to controller turn order and queued hand raises."""
    scope = _scope()
    try:
        occurrence = scope.meetings.advance_floor(scope.occurrence_id)
    except RoleCallError as exc:
        return {"status": "rejected", "reason": str(exc)[:240]}
    return {
        "status": "ok",
        "floorType": occurrence.current_floor_type.value,
        "floorSlotId": occurrence.current_floor_slot_id,
        "sequence": occurrence.sequence,
    }


def record_outcome(kind: OutcomeKind, text: str, owner_slot_id: str | None) -> dict[str, Any]:
    """Persist a decision, action, blocker, idea, commitment, or game result.

    Use a stable seat ID for an owner. Pass null when an outcome has no owner.
    """
    scope = _scope()
    try:
        outcome_kind = OutcomeKind(kind)
    except ValueError:
        return {"status": "rejected", "reason": "unknown outcome kind"}
    key = scope.meetings.outcome_idempotency_key(
        scope.occurrence_id, outcome_kind, text, owner_slot_id
    )
    try:
        outcome = scope.meetings.record_outcome(
            scope.occurrence_id,
            outcome_kind,
            text,
            owner_slot_id,
            key,
        )
    except (RoleCallError, ValueError) as exc:
        return {"status": "rejected", "reason": str(exc)[:240]}
    return {"status": "ok", "outcomeId": outcome.id, "kind": outcome.kind.value}


def get_remaining_time() -> dict[str, Any]:
    """Return authoritative remaining configured meeting time in seconds."""
    scope = _scope()
    return {"remainingSeconds": scope.meetings.remaining_seconds(scope.occurrence_id)}


async def search_room_memory(query: str, slot_id: str | None) -> dict[str, Any]:
    """Search retained facts for this room, optionally anchored to a stable seat."""
    scope = _scope()
    occurrence = scope.repository.get_occurrence(scope.occurrence_id)
    memories = await scope.memory.search(occurrence.room_id, query, slot_id)
    return {"memories": memories}


def finish_meeting(reason: str) -> dict[str, Any]:
    """Close live facilitation and enqueue idempotent partial/full post-processing."""
    scope = _scope()
    try:
        occurrence = scope.meetings.finish(scope.occurrence_id, reason)
    except RoleCallError as exc:
        return {"status": "rejected", "reason": str(exc)[:240]}
    return {"status": "ok", "phase": occurrence.status.value}


MEETING_TOOLS = [
    get_meeting_state,
    set_phase,
    give_floor,
    advance_floor,
    record_outcome,
    get_remaining_time,
    search_room_memory,
    finish_meeting,
]
