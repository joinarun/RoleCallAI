from __future__ import annotations

import inspect
import json

import pytest
from google.adk.tools import FunctionTool

from app import agent_tools, eval_tools


class FakeToolContext:
    def __init__(self, fixture: dict | None = None) -> None:
        self.state = {"rolecallEval": fixture} if fixture else {}


def fixture() -> dict:
    return {
        "scenarioId": "unit-eval",
        "memoryMatches": [
            {"slotId": "seat-1", "kind": "COMMITMENT", "text": "Send plan"},
            {"slotId": "seat-2", "kind": "ACTION", "text": "Review plan"},
        ],
        "meetingState": {
            "status": "RUNNING",
            "participants": [
                {"slotId": "seat-1", "name": "One", "connected": True},
                {"slotId": "seat-2", "name": "Two", "connected": False},
            ],
            "turnOrder": ["seat-1", "seat-2"],
            "currentFloor": {"type": "AGENT", "slotId": None},
            "handRaiseQueue": ["seat-1"],
            "remainingSeconds": 90,
            "sequence": 3,
        },
    }


def _public_parameters(function) -> list[str]:  # type: ignore[no-untyped-def]
    return [name for name in inspect.signature(function).parameters if name != "tool_context"]


def test_evaluation_tool_contract_matches_production() -> None:
    production = {item.__name__: item for item in agent_tools.MEETING_TOOLS}
    evaluation = {item.__name__: item for item in eval_tools.EVALUATION_MEETING_TOOLS}
    assert evaluation.keys() == production.keys()
    for name in production:
        assert _public_parameters(evaluation[name]) == list(
            inspect.signature(production[name]).parameters
        )


def test_state_change_tool_schemas_constrain_persisted_enums() -> None:
    outcome_schema = (
        FunctionTool(agent_tools.record_outcome)
        ._get_declaration()
        .model_dump(by_alias=True, exclude_none=True)["parametersJsonSchema"]
    )
    phase_schema = (
        FunctionTool(agent_tools.set_phase)
        ._get_declaration()
        .model_dump(by_alias=True, exclude_none=True)["parametersJsonSchema"]
    )

    assert set(outcome_schema["$defs"]["OutcomeKind"]["enum"]) == {
        "DECISION",
        "ACTION",
        "BLOCKER",
        "IDEA",
        "COMMITMENT",
        "GAME_RESULT",
    }
    assert "RUNNING" in phase_schema["$defs"]["OccurrenceStatus"]["enum"]
    json.dumps(outcome_schema)


@pytest.mark.asyncio
async def test_evaluation_tools_preserve_controller_and_scope_invariants() -> None:
    context = FakeToolContext(fixture())

    assert eval_tools.get_meeting_state(context)["status"] == "RUNNING"
    rejected = eval_tools.give_floor("seat-2", "Status?", context)
    assert rejected["status"] == "rejected"
    assert eval_tools.give_floor("seat-1", "Your status?", context)["status"] == "ok"
    context.state["rolecallEval"]["meetingState"]["participants"][1]["connected"] = True
    rotation_bypass = eval_tools.give_floor("seat-2", "Skip rotation", context)
    assert rotation_bypass == {
        "status": "rejected",
        "reason": "use advance_floor while a participant owns the floor",
    }

    first = eval_tools.record_outcome("ACTION", "Send plan", "seat-1", context)
    second = eval_tools.record_outcome("ACTION", "Send plan", "seat-1", context)
    assert first["outcomeId"] == second["outcomeId"]
    assert len(context.state["rolecallEval"]["outcomes"]) == 1
    assert eval_tools.record_outcome("concern", "Invalid", None, context) == {
        "status": "rejected",
        "reason": "unknown outcome kind",
    }

    assert eval_tools.get_remaining_time(context) == {"remainingSeconds": 90}
    memories = await eval_tools.search_room_memory("commitment", "seat-1", context)
    assert [item["slotId"] for item in memories["memories"]] == ["seat-1"]

    assert eval_tools.set_phase("COMPLETED", context)["status"] == "rejected"
    assert eval_tools.finish_meeting("complete", context)["phase"] == "PROCESSING"


def test_evaluation_tools_require_seeded_session_state() -> None:
    with pytest.raises(RuntimeError, match="seeded rolecallEval"):
        eval_tools.get_meeting_state(FakeToolContext())
