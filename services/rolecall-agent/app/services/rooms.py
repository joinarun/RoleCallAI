"""Room administration and one-time invitation generation."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from app.config import Settings
from app.domain.enums import GameType, RoleType
from app.domain.errors import ConflictError, NotFoundError
from app.domain.models import (
    OutboxRecord,
    Room,
    RoomCreate,
    RoomCreatedResponse,
    RoomPatch,
    RoomUpdatedResponse,
    RoomView,
    Seat,
)
from app.domain.normalization import clean_display_text, normalize_room_name
from app.domain.repository import Repository
from app.security.capabilities import CapabilityService


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(12)}"


class RoomService:
    def __init__(
        self, repository: Repository, capabilities: CapabilityService, settings: Settings
    ) -> None:
        self.repository = repository
        self.capabilities = capabilities
        self.settings = settings

    def create(self, request: RoomCreate) -> RoomCreatedResponse:
        admin_secret, admin_digest = self.capabilities.issue_secret()
        seats: list[Seat] = []
        seat_secrets: list[tuple[str, str]] = []
        for ordinal in range(1, request.expected_participants + 1):
            secret, digest = self.capabilities.issue_secret()
            slot_id = new_id("slot")
            seats.append(Seat(id=slot_id, ordinal=ordinal, capability_digest=digest))
            seat_secrets.append((slot_id, secret))

        room = Room(
            id=new_id("room"),
            name=request.name,
            normalized_name=normalize_room_name(request.name),
            expected_participants=request.expected_participants,
            duration_minutes=request.duration_minutes,
            role=request.role,
            agent_name=request.agent_name,
            instructions=request.instructions.strip(),
            game=request.game,
            admin_capability_digest=admin_digest,
            slots=seats,
        )
        room = self.repository.create_room(room)
        return RoomCreatedResponse(
            room=RoomView.from_room(room),
            admin_url=self._capability_url("manage", room.id, admin_secret),
            seat_urls=[
                {"slotId": slot_id, "url": self._capability_url("join", room.id, secret)}
                for slot_id, secret in seat_secrets
            ],
        )

    def update(self, room_id: str, patch: RoomPatch) -> RoomUpdatedResponse:
        room = self.repository.get_room(room_id)
        if self.repository.get_active_occurrence(room_id):
            raise ConflictError("Room settings can only change while the room is idle")

        updates = patch.model_dump(exclude_none=True)
        new_seat_urls: list[dict[str, str]] = []
        if "name" in updates:
            room.name = clean_display_text(str(updates["name"]), max_length=100)
            room.normalized_name = normalize_room_name(room.name)
        for field in ("duration_minutes", "role", "agent_name", "instructions", "game"):
            if field in updates:
                setattr(room, field, updates[field])

        if patch.expected_participants is not None and patch.expected_participants != len(
            room.slots
        ):
            target = patch.expected_participants
            if target < len(room.slots):
                removed = sorted(room.slots, key=lambda item: item.ordinal)[target:]
                for slot in removed:
                    self.repository.revoke_capability_sessions(
                        room.id,
                        slot.id,
                        slot.capability_version + 1,
                    )
                room.slots = sorted(room.slots, key=lambda item: item.ordinal)[:target]
            else:
                for ordinal in range(len(room.slots) + 1, target + 1):
                    secret, digest = self.capabilities.issue_secret()
                    slot = Seat(id=new_id("slot"), ordinal=ordinal, capability_digest=digest)
                    room.slots.append(slot)
                    new_seat_urls.append(
                        {"slotId": slot.id, "url": self._capability_url("join", room.id, secret)}
                    )
            room.expected_participants = target

        if room.role == RoleType.FUN_FRIDAY:
            room.game = room.game or GameType.AUTO
        elif patch.game is not None:
            raise ValueError("game can only be set for the Fun Friday role")
        else:
            room.game = None

        room.updated_at = datetime.now(UTC)
        room = self.repository.save_room(room)
        return RoomUpdatedResponse(room=RoomView.from_room(room), new_seat_urls=new_seat_urls)

    def regenerate_seat(self, room_id: str, slot_id: str) -> str:
        room = self.repository.get_room(room_id)
        if self.repository.get_active_occurrence(room_id):
            raise ConflictError("Seat links can only be regenerated while the room is idle")
        slot = next((item for item in room.slots if item.id == slot_id), None)
        if slot is None:
            raise NotFoundError("Seat not found")
        secret, digest = self.capabilities.issue_secret()
        slot.capability_digest = digest
        slot.capability_version += 1
        room.updated_at = datetime.now(UTC)
        self.repository.save_room(room)
        self.repository.revoke_capability_sessions(room.id, slot.id, slot.capability_version)
        return self._capability_url("join", room.id, secret)

    def delete(self, room_id: str) -> None:
        room = self.repository.get_room(room_id)
        if self.repository.get_active_occurrence(room_id):
            raise ConflictError("An active room cannot be deleted")
        self.repository.ensure_outbox(
            OutboxRecord(
                id=f"room-delete:{room.id}",
                topic=self.settings.cleanup_topic,
                aggregate_id=room.id,
                payload={"action": "deleteRoom", "roomId": room.id},
            )
        )
        self.repository.delete_room(room_id)

    def _capability_url(self, route: str, room_id: str, secret: str) -> str:
        return f"{self.settings.public_base_url.rstrip('/')}/{route}/{room_id}#cap={secret}"
