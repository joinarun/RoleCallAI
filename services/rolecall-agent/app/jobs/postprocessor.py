"""Typed ADK 2.x graph workflow for meeting recap and curated memory."""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from google.adk import Agent, Context, Event, Workflow
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.runners import Runner
from google.genai import types
from pydantic import BaseModel

from app.app_utils import services as adk_services
from app.config import get_settings
from app.container import Container
from app.domain.enums import OccurrenceStatus
from app.domain.models import MeetingRecap


class SummaryInput(BaseModel):
    occurrence_id: str
    role: str
    admin_instructions: str
    participants: list[dict[str, str]]
    finalized_transcript: list[dict[str, Any]]
    controller_outcomes: list[dict[str, Any]]


@dataclass(frozen=True)
class ProcessingScope:
    container: Container
    occurrence_id: str


_PROCESSING_SCOPE: ContextVar[ProcessingScope | None] = ContextVar(
    "rolecall_processing_scope", default=None
)


@contextmanager
def bind_processing_scope(scope: ProcessingScope):  # type: ignore[no-untyped-def]
    token = _PROCESSING_SCOPE.set(scope)
    try:
        yield
    finally:
        _PROCESSING_SCOPE.reset(token)


def _scope() -> ProcessingScope:
    scope = _PROCESSING_SCOPE.get()
    if scope is None:
        raise RuntimeError("Post-processing workflow is missing its server scope")
    return scope


def normalize_transcript(node_input: str) -> Event:
    """Load final-only segments and trusted controller data into a typed input."""
    try:
        request = json.loads(node_input)
        occurrence_id = str(request.get("occurrenceId"))
    except (json.JSONDecodeError, AttributeError):
        occurrence_id = node_input.strip()
    scope = _scope()
    if occurrence_id != scope.occurrence_id:
        raise ValueError("Post-processing input does not match the server-bound occurrence")
    container = scope.container
    occurrence = container.repository.get_occurrence(occurrence_id)
    room = container.repository.get_room(occurrence.room_id)
    segments = container.repository.list_transcript_segments(occurrence_id)
    data = SummaryInput(
        occurrence_id=occurrence.id,
        role=room.role.value,
        admin_instructions=room.instructions,
        participants=[
            {"slotId": slot_id, "displayName": attendance.display_name}
            for slot_id, attendance in occurrence.attendance.items()
        ],
        finalized_transcript=[
            {
                "sequence": item.sequence,
                "speakerId": item.speaker_id,
                "speakerName": item.speaker_name,
                "text": item.text,
            }
            for item in segments
        ],
        controller_outcomes=[item.model_dump(mode="json") for item in occurrence.outcomes],
    )
    return Event(output=data.model_dump(mode="json"))


_settings = get_settings()
summary_agent = Agent(
    name="meeting_recap_writer",
    model=Gemini(
        model=_settings.summary_model,
        client_kwargs={
            "vertexai": True,
            "project": _settings.project_id,
            "location": _settings.summary_model_location,
        },
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    mode="single_turn",
    input_schema=SummaryInput,
    output_schema=MeetingRecap,
    instruction="""Create a faithful, concise meeting recap from finalized transcript segments.

Rules:
- Return only the requested structured MeetingRecap.
- Prefer controller outcomes and explicit participant statements; do not infer commitments.
- An action owner must be copied from a participant stable slotId or be null.
- Keep empty categories as empty arrays. Do not fabricate decisions, scores, or names.
""",
)


def validate_recap(node_input: dict[str, Any]) -> Event:
    """Reject hallucinated owners before persistence."""
    scope = _scope()
    occurrence = scope.container.repository.get_occurrence(scope.occurrence_id)
    recap = MeetingRecap.model_validate(node_input)
    allowed_slots = set(occurrence.attendance)
    invalid_owners = [
        action.owner_slot_id
        for action in recap.actions
        if action.owner_slot_id and action.owner_slot_id not in allowed_slots
    ]
    if invalid_owners:
        raise ValueError("Recap contains an owner outside this occurrence")
    # Retrieval citations are controller-owned. The summary model cannot invent,
    # modify, or broaden document evidence.
    recap.citations = occurrence.retrieval_citations
    return Event(output=recap.model_dump(mode="json"))


async def persist_recap(node_input: dict[str, Any], ctx: Context) -> Event:
    """Persist validated recap, complete the occurrence, and add curated facts."""
    del ctx
    scope = _scope()
    container = scope.container
    occurrence = container.repository.get_occurrence(scope.occurrence_id)
    proposed_recap = MeetingRecap.model_validate(node_input)

    def save_recap(current):  # type: ignore[no-untyped-def]
        if current.recap is None:
            current.recap = proposed_recap
            current.ended_at = current.ended_at or datetime.now(UTC)
            current.expires_at = current.ended_at + timedelta(
                days=container.settings.retention_days
            )
        return current

    occurrence = container.repository.mutate_occurrence(scope.occurrence_id, save_recap)
    recap = occurrence.recap or proposed_recap

    if occurrence.memory_persisted_at is None:
        await container.memory.add_recap(occurrence, recap)

        def mark_memory_persisted(current):  # type: ignore[no-untyped-def]
            current.memory_persisted_at = current.memory_persisted_at or datetime.now(UTC)
            return current

        occurrence = container.repository.mutate_occurrence(
            scope.occurrence_id, mark_memory_persisted
        )

    def complete(current):  # type: ignore[no-untyped-def]
        if current.status != OccurrenceStatus.COMPLETED:
            current.status = OccurrenceStatus.COMPLETED
            current.sequence += 1
        return current

    occurrence = container.repository.mutate_occurrence(scope.occurrence_id, complete)
    await container.livekit.publish_message(
        occurrence, "meeting.state", occurrence.model_dump(mode="json")
    )
    await container.livekit.publish_message(
        occurrence, "recap.ready", recap.model_dump(mode="json")
    )
    return Event(output=recap.model_dump(mode="json"))


POSTPROCESS_WORKFLOW = Workflow(
    name="rolecall_postprocessor",
    description="Normalize transcript, summarize, validate, persist, and remember curated facts.",
    edges=[
        ("START", normalize_transcript, summary_agent, validate_recap, persist_recap),
    ],
)


async def process_occurrence(container: Container, occurrence_id: str) -> MeetingRecap:
    occurrence = container.repository.get_occurrence(occurrence_id)
    if occurrence.status == OccurrenceStatus.COMPLETED and occurrence.recap:
        return occurrence.recap
    runner = Runner(
        app=App(root_agent=POSTPROCESS_WORKFLOW, name="rolecall_ai"),
        session_service=adk_services.get_session_service(),
        auto_create_session=True,
    )
    new_message = types.Content(
        role="user", parts=[types.Part(text=json.dumps({"occurrenceId": occurrence_id}))]
    )
    with bind_processing_scope(ProcessingScope(container, occurrence_id)):
        async for _ in runner.run_async(
            user_id=occurrence.room_id,
            session_id=occurrence.id,
            new_message=new_message,
        ):
            pass
    completed = container.repository.get_occurrence(occurrence_id)
    if completed.recap is None:
        raise RuntimeError("Post-processing workflow completed without a recap")
    return completed.recap
