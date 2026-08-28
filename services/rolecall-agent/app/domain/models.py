"""Pydantic domain and API models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import (
    CapabilityKind,
    FloorOwnerType,
    GameType,
    OccurrenceStatus,
    OutcomeKind,
    RoleType,
)
from app.domain.normalization import clean_display_text, normalize_room_name


def utc_now() -> datetime:
    return datetime.now(UTC)


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(word.capitalize() for word in tail)


class DomainModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=False,
        alias_generator=_to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class RoomCreate(DomainModel):
    name: str
    expected_participants: Annotated[int, Field(ge=2, le=10)]
    duration_minutes: Annotated[int, Field(ge=5, le=60)]
    role: RoleType
    agent_name: str
    instructions: Annotated[str, Field(max_length=8000)] = ""
    game: GameType | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return clean_display_text(value, max_length=100)

    @field_validator("agent_name")
    @classmethod
    def clean_agent_name(cls, value: str) -> str:
        return clean_display_text(value, max_length=60)

    @model_validator(mode="after")
    def validate_game(self) -> RoomCreate:
        if self.role == RoleType.FUN_FRIDAY and self.game is None:
            self.game = GameType.AUTO
        if self.role != RoleType.FUN_FRIDAY and self.game is not None:
            raise ValueError("game can only be set for the Fun Friday role")
        return self


class RoomPatch(DomainModel):
    name: str | None = None
    expected_participants: Annotated[int | None, Field(ge=2, le=10)] = None
    duration_minutes: Annotated[int | None, Field(ge=5, le=60)] = None
    role: RoleType | None = None
    agent_name: str | None = None
    instructions: Annotated[str | None, Field(max_length=8000)] = None
    game: GameType | None = None

    @field_validator("name")
    @classmethod
    def clean_optional_name(cls, value: str | None) -> str | None:
        return clean_display_text(value, max_length=100) if value is not None else None

    @field_validator("agent_name")
    @classmethod
    def clean_optional_agent_name(cls, value: str | None) -> str | None:
        return clean_display_text(value, max_length=60) if value is not None else None

    @field_validator("instructions")
    @classmethod
    def clean_optional_instructions(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class Seat(DomainModel):
    id: str
    ordinal: int
    capability_digest: str
    capability_version: int = 1
    last_display_name: str | None = None
    can_end_meeting: bool = False


class Room(DomainModel):
    id: str
    name: str
    normalized_name: str
    expected_participants: int
    duration_minutes: int
    role: RoleType
    agent_name: str
    instructions: str
    game: GameType | None = None
    admin_capability_digest: str
    admin_capability_version: int = 1
    slots: list[Seat]
    occurrence_counter: int = 0
    active_occurrence_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @classmethod
    def normalized_key(cls, name: str) -> str:
        return normalize_room_name(name)


class Attendance(DomainModel):
    slot_id: str
    display_name: str
    consent_version: str
    joined_at: datetime
    connected: bool = True
    connection_id: str
    disconnected_at: datetime | None = None
    left_at: datetime | None = None
    absent: bool = False


class Outcome(DomainModel):
    id: str
    kind: OutcomeKind
    text: str
    owner_slot_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    idempotency_key: str


class RecapAction(DomainModel):
    text: str
    owner_slot_id: str | None = None


class GameResult(DomainModel):
    label: str
    score: int | None = None
    slot_id: str | None = None


class MeetingRecap(DomainModel):
    summary: str
    decisions: list[str] = Field(default_factory=list)
    actions: list[RecapAction] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    ideas: list[str] = Field(default_factory=list)
    game_results: list[GameResult] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)


class TranscriptSegment(DomainModel):
    id: str
    occurrence_id: str
    sequence: int
    speaker_type: FloorOwnerType
    speaker_id: str
    speaker_name: str
    text: str
    started_at: datetime
    ended_at: datetime
    expires_at: datetime


class Occurrence(DomainModel):
    id: str
    room_id: str
    number: int
    status: OccurrenceStatus = OccurrenceStatus.LOBBY
    created_at: datetime = Field(default_factory=utc_now)
    lobby_deadline_at: datetime
    started_at: datetime | None = None
    ending_at: datetime | None = None
    ended_at: datetime | None = None
    expires_at: datetime | None = None
    attendance: dict[str, Attendance] = Field(default_factory=dict)
    absent_slot_ids: list[str] = Field(default_factory=list)
    turn_order: list[str] = Field(default_factory=list)
    current_floor_type: FloorOwnerType = FloorOwnerType.AGENT
    current_floor_slot_id: str | None = None
    next_floor_slot_id: str | None = None
    current_prompt: str | None = None
    floor_epoch: int = 0
    hand_raise_queue: list[str] = Field(default_factory=list)
    end_meeting_slot_ids: list[str] = Field(default_factory=list)
    outcomes: list[Outcome] = Field(default_factory=list)
    recap: MeetingRecap | None = None
    previous_recap: MeetingRecap | None = None
    memory_persisted_at: datetime | None = None
    sequence: int = 0
    agent_last_seen_at: datetime | None = None
    failure_reason: str | None = None


class CapabilityRecord(DomainModel):
    room_id: str
    kind: CapabilityKind
    digest: str
    version: int
    slot_id: str | None = None


class CapabilityClaims(DomainModel):
    session_id: str
    room_id: str
    kind: CapabilityKind
    capability_version: int
    slot_id: str | None = None
    issued_at: datetime
    expires_at: datetime


class CapabilitySession(DomainModel):
    session_digest: str
    claims: CapabilityClaims
    expires_at: datetime
    revoked_at: datetime | None = None


class OutboxRecord(DomainModel):
    id: str
    topic: str
    aggregate_id: str
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=utc_now)
    published_at: datetime | None = None
    attempts: int = 0


class RoomCreatedResponse(DomainModel):
    room: RoomView
    admin_url: str
    seat_urls: list[dict[str, str]]


class SeatView(DomainModel):
    id: str
    ordinal: int
    last_display_name: str | None = None
    can_end_meeting: bool = False


class RoomView(DomainModel):
    id: str
    name: str
    expected_participants: int
    duration_minutes: int
    role: RoleType
    agent_name: str
    instructions: str
    game: GameType | None = None
    slots: list[SeatView]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_room(cls, room: Room) -> RoomView:
        return cls(
            id=room.id,
            name=room.name,
            expected_participants=room.expected_participants,
            duration_minutes=room.duration_minutes,
            role=room.role,
            agent_name=room.agent_name,
            instructions=room.instructions,
            game=room.game,
            slots=[
                SeatView(
                    id=slot.id,
                    ordinal=slot.ordinal,
                    last_display_name=slot.last_display_name,
                    can_end_meeting=slot.can_end_meeting,
                )
                for slot in room.slots
            ],
            created_at=room.created_at,
            updated_at=room.updated_at,
        )


class ParticipantRoomView(DomainModel):
    id: str
    name: str
    expected_participants: int
    duration_minutes: int
    role: RoleType
    agent_name: str
    slots: list[SeatView]

    @classmethod
    def from_room_and_slot(cls, room: Room, slot_id: str) -> ParticipantRoomView:
        slot = next(item for item in room.slots if item.id == slot_id)
        return cls(
            id=room.id,
            name=room.name,
            expected_participants=room.expected_participants,
            duration_minutes=room.duration_minutes,
            role=room.role,
            agent_name=room.agent_name,
            slots=[
                SeatView(
                    id=slot.id,
                    ordinal=slot.ordinal,
                    last_display_name=slot.last_display_name,
                    can_end_meeting=slot.can_end_meeting,
                )
            ],
        )


class RoomUpdatedResponse(DomainModel):
    room: RoomView
    new_seat_urls: list[dict[str, str]] = Field(default_factory=list)


class CapabilityExchangeRequest(DomainModel):
    room_id: str
    token: Annotated[str, Field(min_length=32, max_length=512)]


class CapabilityExchangeResponse(DomainModel):
    room_id: str
    scope: CapabilityKind
    slot_id: str | None = None
    expires_at: datetime


class JoinRequest(DomainModel):
    name: str
    consent_version: Annotated[str, Field(min_length=1, max_length=40)]
    connection_id: Annotated[str, Field(min_length=8, max_length=200)]

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return clean_display_text(value, max_length=60)


class RefreshRequest(DomainModel):
    connection_id: Annotated[str, Field(min_length=8, max_length=200)]


class LeaveRequest(DomainModel):
    connection_id: Annotated[str, Field(min_length=8, max_length=200)]


class EndMeetingRequest(DomainModel):
    reason: Annotated[str, Field(min_length=1, max_length=240)] = "ended_by_authorized_user"


class EndMeetingPermissionRequest(DomainModel):
    allowed: bool


class JoinResponse(DomainModel):
    occurrence: Occurrence
    livekit_url: str
    livekit_token: str
    slot_id: str
    room_name: str
    agent_name: str
    expected_participants: int
    connection_id: str
    can_end_meeting: bool = False


class StartRequest(DomainModel):
    reason: str = "participant_requested"


class HistoryItem(DomainModel):
    occurrence_id: str
    number: int
    status: OccurrenceStatus
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    recap: MeetingRecap | None


class LiveKitMessage(DomainModel):
    v: Annotated[int, Field(ge=1, le=1)] = 1
    type: str
    occurrence_id: str
    sequence: Annotated[int, Field(ge=0)]
    payload: dict[str, Any]
