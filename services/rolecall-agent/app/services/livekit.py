"""LiveKit room tokens and server-side publish permission enforcement."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from livekit import api

from app.config import Settings
from app.domain.enums import FloorOwnerType
from app.domain.models import LiveKitMessage, Occurrence

logger = logging.getLogger("rolecall.livekit")


class LiveKitService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def participant_token(self, occurrence: Occurrence, slot_id: str, display_name: str) -> str:
        can_publish = (
            occurrence.current_floor_type == FloorOwnerType.SEAT
            and occurrence.current_floor_slot_id == slot_id
        )
        grants = api.VideoGrants(
            room_join=True,
            room=occurrence.id,
            can_subscribe=True,
            can_publish=can_publish,
            can_publish_data=True,
            hidden=False,
        )
        return (
            api.AccessToken(
                self.settings.livekit_api_key.get_secret_value(),
                self.settings.livekit_api_secret.get_secret_value(),
            )
            .with_identity(f"seat:{slot_id}")
            .with_name(display_name)
            .with_grants(grants)
            .with_ttl(timedelta(minutes=self.settings.livekit_token_minutes))
            .to_jwt()
        )

    async def ensure_room(self, occurrence: Occurrence) -> None:
        """Create the exact occurrence room when server auto-creation is disabled."""
        if self.settings.env == "test":
            return
        client = self._api_client()
        try:
            existing = await client.room.list_rooms(api.ListRoomsRequest(names=[occurrence.id]))
            if existing.rooms:
                return
            try:
                await client.room.create_room(
                    api.CreateRoomRequest(
                        name=occurrence.id,
                        empty_timeout=max(300, self.settings.lobby_early_start_seconds + 60),
                        departure_timeout=self.settings.disconnect_hold_seconds,
                        max_participants=11,
                        metadata=json.dumps(
                            {"occurrenceId": occurrence.id, "roomId": occurrence.room_id}
                        ),
                    )
                )
            except api.ServerError as exc:
                if exc.code != api.ServerErrorCode.ALREADY_EXISTS:
                    raise
        finally:
            await client.aclose()

    async def enforce_floor(self, occurrence: Occurrence) -> None:
        """Set publish permission for every connected human in one authoritative pass."""
        if self.settings.env == "test":
            return
        client = self._api_client()
        try:
            for slot_id, attendance in occurrence.attendance.items():
                if not attendance.connected:
                    continue
                try:
                    await client.room.update_participant(
                        api.UpdateParticipantRequest(
                            room=occurrence.id,
                            identity=f"seat:{slot_id}",
                            permission=api.ParticipantPermission(
                                can_subscribe=True,
                                can_publish=(
                                    occurrence.current_floor_type == FloorOwnerType.SEAT
                                    and occurrence.current_floor_slot_id == slot_id
                                ),
                                can_publish_data=True,
                            ),
                        )
                    )
                except api.ServerError as exc:
                    if exc.code != api.ServerErrorCode.NOT_FOUND:
                        raise
        finally:
            await client.aclose()

    async def publish_message(
        self, occurrence: Occurrence, message_type: str, payload: dict[str, Any]
    ) -> bool:
        """Best-effort reliable room message; API polling remains the fallback."""
        if self.settings.env == "test":
            return False
        message = LiveKitMessage(
            type=message_type,
            occurrence_id=occurrence.id,
            sequence=occurrence.sequence,
            payload=payload,
        )
        client = self._api_client()
        try:
            participants = await client.room.list_participants(
                api.ListParticipantsRequest(room=occurrence.id)
            )
            if not participants.participants:
                return False
            await client.room.send_data(
                api.SendDataRequest(
                    room=occurrence.id,
                    data=message.model_dump_json(by_alias=True).encode(),
                    kind=0,
                    topic="rolecall.v1",
                )
            )
            return True
        except api.ServerError as exc:
            if exc.code == api.ServerErrorCode.NOT_FOUND:
                return False
            logger.warning(
                "event=livekit_data_publish_failed occurrence_id=%s error_code=%s",
                occurrence.id,
                exc.code,
            )
            return False
        finally:
            await client.aclose()

    async def dispatch_agent(self, occurrence: Occurrence) -> None:
        """Idempotently dispatch the named worker to an occurrence room."""
        client = self._api_client()
        try:
            dispatches = await client.agent_dispatch.list_dispatch(occurrence.id)
            if any(item.agent_name == "rolecall-meeting" for item in dispatches):
                return
            await client.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    room=occurrence.id,
                    agent_name="rolecall-meeting",
                    metadata=json.dumps({"occurrenceId": occurrence.id}),
                )
            )
        finally:
            await client.aclose()

    def _api_client(self) -> api.LiveKitAPI:
        return api.LiveKitAPI(
            self.settings.livekit_url.replace("ws://", "http://").replace("wss://", "https://"),
            self.settings.livekit_api_key.get_secret_value(),
            self.settings.livekit_api_secret.get_secret_value(),
        )
