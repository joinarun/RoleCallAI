"""State-backed ADK tools used only by the text evaluation runner.

The production live agent binds :mod:`app.agent_tools` to a real occurrence.
``agents-cli eval`` runs over HTTP without a LiveKit job, so its fixture state
is carried in the ADK session instead. These tools intentionally expose the
same names and arguments while preserving controller validation and the rule
that the model cannot provide room/session/occurrence identifiers.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from google.adk.tools import ToolContext

from app.domain.enums import OccurrenceStatus, OutcomeKind

_ACTIVE_PHASES = {"STARTING", "RUNNING", "ENDING"}
_ALLOWED_TRANSITIONS = {
    "LOBBY": {"STARTING"},
    "STARTING": {"RUNNING", "FAILED"},
    "RUNNING": {"ENDING", "PROCESSING", "FAILED"},
    "ENDING": {"PROCESSING", "FAILED"},
    "PROCESSING": {"COMPLETED", "FAILED"},
    "COMPLETED": set(),
    "FAILED": set(),
}


def _fixture(tool_context: ToolContext) -> dict[str, Any]:
    fixture = tool_context.state.get("rolecallEval")
    if not isinstance(fixture, dict) or not fixture.get("scenarioId"):
        raise RuntimeError("Evaluation tools require a seeded rolecallEval session state")
    return deepcopy(fixture)


def _save(tool_context: ToolContext, fixture: dict[str, Any]) -> None:
    # Reassign the top-level value so ADK records a state delta.
    tool_context.state["rolecallEval"] = fixture


def _meeting(fixture: dict[str, Any]) -> dict[str, Any]:
    meeting = fixture.get("meetingState")
    if not isinstance(meeting, dict):
        raise RuntimeError("Evaluation fixture is missing meetingState")
    return meeting


def _participants(meeting: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["slotId"]): item
        for item in meeting.get("participants", [])
        if isinstance(item, dict) and item.get("slotId")
    }


def get_meeting_state(tool_context: ToolContext) -> dict[str, Any]:
    """Return seeded authoritative lifecycle, floor, attendance, and turn order."""
    return deepcopy(_meeting(_fixture(tool_context)))


def set_phase(phase: OccurrenceStatus, tool_context: ToolContext) -> dict[str, Any]:
    """Request a controller-validated lifecycle transition."""
    fixture = _fixture(tool_context)
    meeting = _meeting(fixture)
    try:
        target = OccurrenceStatus(phase).value
    except ValueError:
        return {"status": "rejected", "reason": "unknown lifecycle phase"}
    current = str(meeting.get("status", "LOBBY"))
    if target not in _ALLOWED_TRANSITIONS.get(current, set()):
        return {"status": "rejected", "reason": f"invalid transition {current} -> {target}"}
    meeting["status"] = target
    _save(tool_context, fixture)
    return {"status": "ok", "phase": target}


def give_floor(slot_id: str, prompt: str, tool_context: ToolContext) -> dict[str, Any]:
    """Give the floor only to a connected, present stable seat."""
    fixture = _fixture(tool_context)
    meeting = _meeting(fixture)
    participant = _participants(meeting).get(slot_id)
    if meeting.get("status") not in _ACTIVE_PHASES:
        return {"status": "rejected", "reason": "meeting is not active"}
    if not participant or not participant.get("connected", False):
        return {"status": "rejected", "reason": "seat is absent or disconnected"}
    current_floor = meeting.get("currentFloor") or {}
    if current_floor.get("type") == "SEAT" and current_floor.get("slotId") != slot_id:
        return {
            "status": "rejected",
            "reason": "use advance_floor while a participant owns the floor",
        }
    pending = meeting.get("nextFloorSlotId")
    if pending and pending != slot_id:
        return {
            "status": "rejected",
            "reason": "the controller selected a different next participant",
        }
    meeting["currentFloor"] = {"type": "SEAT", "slotId": slot_id}
    meeting["nextFloorSlotId"] = None
    meeting["sequence"] = int(meeting.get("sequence", 0)) + 1
    meeting["lastFloorPrompt"] = " ".join(prompt.split())[:240]
    _save(tool_context, fixture)
    return {"status": "ok", "floorSlotId": slot_id, "sequence": meeting["sequence"]}


def advance_floor(tool_context: ToolContext) -> dict[str, Any]:
    """Return to agent floor and select the next deterministic participant."""
    fixture = _fixture(tool_context)
    meeting = _meeting(fixture)
    current_floor = meeting.get("currentFloor") or {}
    if current_floor.get("type") == "AGENT" and meeting.get("nextFloorSlotId") is not None:
        return {
            "status": "ok",
            "floorType": "AGENT",
            "floorSlotId": None,
            "nextFloorSlotId": meeting.get("nextFloorSlotId"),
            "sequence": int(meeting.get("sequence", 0)),
        }
    participants = _participants(meeting)
    queue = list(meeting.get("handRaiseQueue", []))
    order = list(meeting.get("turnOrder", []))
    current = current_floor.get("slotId")
    candidates = (
        queue + order[order.index(current) + 1 :] + order if current in order else queue + order
    )
    selected = next(
        (
            slot_id
            for slot_id in candidates
            if slot_id != current
            and slot_id in participants
            and participants[slot_id].get("connected", False)
        ),
        None,
    )
    if (
        selected is None
        and current in participants
        and participants[current].get("connected", False)
    ):
        selected = current
    meeting["handRaiseQueue"] = [item for item in queue if item != selected]
    meeting["currentFloor"] = {"type": "AGENT", "slotId": None}
    meeting["nextFloorSlotId"] = selected
    meeting["sequence"] = int(meeting.get("sequence", 0)) + 1
    _save(tool_context, fixture)
    return {
        "status": "ok",
        "floorType": "AGENT",
        "floorSlotId": None,
        "nextFloorSlotId": selected,
        "sequence": meeting["sequence"],
    }


def record_outcome(
    kind: OutcomeKind,
    text: str,
    owner_slot_id: str | None,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Record an idempotent typed fixture outcome with an optional known owner."""
    fixture = _fixture(tool_context)
    meeting = _meeting(fixture)
    try:
        outcome_kind = OutcomeKind(kind).value
    except ValueError:
        return {"status": "rejected", "reason": "unknown outcome kind"}
    if owner_slot_id is not None and owner_slot_id not in _participants(meeting):
        return {"status": "rejected", "reason": "unknown owner seat"}
    clean_text = " ".join(text.split())[:1000]
    digest = hashlib.sha256(
        f"{outcome_kind}\x00{clean_text}\x00{owner_slot_id or ''}".encode()
    ).hexdigest()[:16]
    outcomes = fixture.setdefault("outcomes", [])
    if not any(item.get("outcomeId") == digest for item in outcomes):
        outcomes.append(
            {
                "outcomeId": digest,
                "kind": outcome_kind,
                "text": clean_text,
                "ownerSlotId": owner_slot_id,
            }
        )
    _save(tool_context, fixture)
    return {"status": "ok", "outcomeId": digest, "kind": outcome_kind}


def get_remaining_time(tool_context: ToolContext) -> dict[str, Any]:
    """Return the seeded controller-owned remaining time."""
    meeting = _meeting(_fixture(tool_context))
    return {"remainingSeconds": max(0, int(meeting.get("remainingSeconds", 0)))}


async def search_room_memory(
    query: str,
    slot_id: str | None,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Return retained fixture facts, optionally restricted to a stable seat."""
    del query
    fixture = _fixture(tool_context)
    memories = list(fixture.get("memoryMatches", []))
    if slot_id is not None:
        memories = [item for item in memories if item.get("slotId") in {None, slot_id}]
    return {"memories": deepcopy(memories)}


def finish_meeting(reason: str, tool_context: ToolContext) -> dict[str, Any]:
    """Finish the fixture meeting and preserve a sanitized close reason."""
    fixture = _fixture(tool_context)
    meeting = _meeting(fixture)
    if meeting.get("status") not in _ACTIVE_PHASES:
        return {"status": "rejected", "reason": "meeting is not active"}
    meeting["status"] = "PROCESSING"
    fixture["finishReason"] = " ".join(reason.split())[:240]
    _save(tool_context, fixture)
    return {"status": "ok", "phase": "PROCESSING"}


EVALUATION_MEETING_TOOLS = [
    get_meeting_state,
    set_phase,
    give_floor,
    advance_floor,
    record_outcome,
    get_remaining_time,
    search_room_memory,
    finish_meeting,
]
