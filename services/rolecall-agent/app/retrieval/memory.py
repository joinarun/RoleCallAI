"""Curated Agent Platform Memory Bank access scoped by room ID."""

from __future__ import annotations

import json

from google.adk.events import Event
from google.adk.memory import VertexAiMemoryBankService
from google.genai import types

from app.config import Settings
from app.domain.models import MeetingRecap, Occurrence


class RoomMemoryService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._service: VertexAiMemoryBankService | None = None

    def _get_service(self) -> VertexAiMemoryBankService | None:
        if not self.settings.agent_engine_id:
            return None
        if self._service is None:
            engine_id = self.settings.agent_engine_id.rsplit("/", 1)[-1]
            self._service = VertexAiMemoryBankService(
                project=self.settings.project_id,
                location=self.settings.region,
                agent_engine_id=engine_id,
            )
        return self._service

    async def search(self, room_id: str, query: str, slot_id: str | None) -> list[dict[str, str]]:
        service = self._get_service()
        if service is None:
            return []
        scoped_query = f"stable seat {slot_id}: {query}" if slot_id else query
        response = await service.search_memory(
            app_name="rolecall-ai",
            user_id=room_id,
            query=scoped_query,
        )
        results: list[dict[str, str]] = []
        for memory in response.memories[:8]:
            text = " ".join(
                part.text or ""
                for part in (memory.content.parts or [])
                if getattr(part, "text", None)
            ).strip()
            if text:
                results.append({"id": memory.id or "", "text": text[:1200]})
        return results

    async def add_recap(self, occurrence: Occurrence, recap: MeetingRecap) -> None:
        service = self._get_service()
        if service is None:
            return
        facts = {
            "occurrenceId": occurrence.id,
            "decisions": recap.decisions,
            "actions": [item.model_dump(mode="json") for item in recap.actions],
            "blockers": recap.blockers,
            "ideas": recap.ideas,
            "gameResults": [item.model_dump(mode="json") for item in recap.game_results],
            "seatNames": {
                slot_id: attendance.display_name
                for slot_id, attendance in occurrence.attendance.items()
            },
        }
        event = Event(
            id=f"recap:{occurrence.id}",
            author="rolecall_postprocessor",
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        text=(
                            "Curated meeting facts. Stable seat IDs are identity anchors. "
                            + json.dumps(facts, ensure_ascii=False)
                        )
                    )
                ],
            ),
        )
        await service.add_events_to_memory(
            app_name="rolecall-ai",
            user_id=occurrence.room_id,
            session_id=occurrence.id,
            events=[event],
            custom_metadata={
                "occurrence_id": occurrence.id,
                "expires_at": str(occurrence.expires_at),
            },
        )
