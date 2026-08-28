"""Versioned RoleCallAI HTTP API."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from livekit import api as livekit_api
from pydantic import BaseModel

from app.container import Container
from app.domain.enums import CapabilityKind, OccurrenceStatus
from app.domain.errors import ForbiddenError, NotFoundError, UnauthorizedError
from app.domain.models import (
    CapabilityClaims,
    CapabilityExchangeRequest,
    CapabilityExchangeResponse,
    HistoryItem,
    JoinRequest,
    JoinResponse,
    ParticipantRoomView,
    RefreshRequest,
    RoomCreate,
    RoomCreatedResponse,
    RoomPatch,
    RoomUpdatedResponse,
    RoomView,
    StartRequest,
)

logger = logging.getLogger("rolecall.api")
router = APIRouter(prefix="/v1")


class PubSubEnvelope(BaseModel):
    message: dict[str, Any]
    subscription: str | None = None


def _container(request: Request) -> Container:
    return request.app.state.container


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _claims(request: Request) -> CapabilityClaims:
    container = _container(request)
    return container.capabilities.authenticate(request.cookies.get(container.settings.cookie_name))


def _authorize_room(claims: CapabilityClaims, room_id: str, kind: CapabilityKind) -> None:
    if claims.room_id != room_id or claims.kind != kind:
        raise ForbiddenError("Capability does not grant access to this room")


@router.post("/rooms", response_model=RoomCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_room(request: Request, payload: RoomCreate) -> RoomCreatedResponse:
    container = _container(request)
    container.rate_limiter.enforce(
        container.rate_limiter.privacy_key("room-create", _client_ip(request)),
        container.settings.room_create_rate_per_hour,
        3600,
    )
    return container.rooms.create(payload)


@router.post("/capability-sessions", response_model=CapabilityExchangeResponse)
def exchange_capability(
    request: Request, response: Response, payload: CapabilityExchangeRequest
) -> CapabilityExchangeResponse:
    container = _container(request)
    try:
        cookie, claims = container.capabilities.exchange(payload.room_id, payload.token)
    except UnauthorizedError:
        container.rate_limiter.enforce(
            container.rate_limiter.privacy_key("capability-failure", _client_ip(request)),
            container.settings.capability_failure_rate_per_minute,
            60,
        )
        raise
    response.set_cookie(
        key=container.settings.cookie_name,
        value=cookie,
        max_age=container.settings.capability_session_minutes * 60,
        secure=container.settings.cookie_secure,
        httponly=True,
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return CapabilityExchangeResponse(
        room_id=claims.room_id,
        scope=claims.kind,
        slot_id=claims.slot_id,
        expires_at=claims.expires_at,
    )


@router.delete("/capability-sessions", status_code=status.HTTP_204_NO_CONTENT)
def clear_capability_session(request: Request, response: Response) -> None:
    container = _container(request)
    response.delete_cookie(container.settings.cookie_name, path="/")


@router.get("/capability-sessions/current", response_model=CapabilityExchangeResponse)
def current_capability_session(request: Request) -> CapabilityExchangeResponse:
    claims = _claims(request)
    return CapabilityExchangeResponse(
        room_id=claims.room_id,
        scope=claims.kind,
        slot_id=claims.slot_id,
        expires_at=claims.expires_at,
    )


@router.get("/rooms/{room_id}")
def get_room(request: Request, room_id: str):  # type: ignore[no-untyped-def]
    claims = _claims(request)
    if claims.room_id != room_id:
        raise ForbiddenError("Capability does not grant access to this room")
    room = _container(request).repository.get_room(room_id)
    if claims.kind == CapabilityKind.SEAT and claims.slot_id:
        return ParticipantRoomView.from_room_and_slot(room, claims.slot_id)
    return RoomView.from_room(room)


@router.patch("/rooms/{room_id}", response_model=RoomUpdatedResponse)
def update_room(request: Request, room_id: str, payload: RoomPatch) -> RoomUpdatedResponse:
    claims = _claims(request)
    _authorize_room(claims, room_id, CapabilityKind.ADMIN)
    return _container(request).rooms.update(room_id, payload)


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_room(request: Request, room_id: str) -> None:
    claims = _claims(request)
    _authorize_room(claims, room_id, CapabilityKind.ADMIN)
    _container(request).rooms.delete(room_id)


@router.post(
    "/rooms/{room_id}/slots/{slot_id}:regenerate",
    response_model=dict[str, str],
)
def regenerate_seat(request: Request, room_id: str, slot_id: str) -> dict[str, str]:
    claims = _claims(request)
    _authorize_room(claims, room_id, CapabilityKind.ADMIN)
    return {"url": _container(request).rooms.regenerate_seat(room_id, slot_id)}


@router.post("/rooms/{room_id}:join", response_model=JoinResponse)
async def join_room(request: Request, room_id: str, payload: JoinRequest) -> JoinResponse:
    claims = _claims(request)
    _authorize_room(claims, room_id, CapabilityKind.SEAT)
    if not claims.slot_id:
        raise ForbiddenError("Seat capability required")
    container = _container(request)
    occurrence = container.meetings.join(room_id, claims.slot_id, payload)
    await container.livekit.ensure_room(occurrence)
    if occurrence.status in {OccurrenceStatus.RUNNING, OccurrenceStatus.ENDING}:
        await container.livekit.dispatch_agent(occurrence)
    room = container.repository.get_room(room_id)
    return JoinResponse(
        occurrence=occurrence,
        livekit_url=container.settings.livekit_url,
        livekit_token=container.livekit.participant_token(occurrence, claims.slot_id, payload.name),
        slot_id=claims.slot_id,
        room_name=room.name,
        agent_name=room.agent_name,
        expected_participants=room.expected_participants,
        connection_id=payload.connection_id,
    )


@router.post("/rooms/{room_id}:refresh", response_model=JoinResponse)
async def refresh_room_token(
    request: Request, room_id: str, payload: RefreshRequest
) -> JoinResponse:
    claims = _claims(request)
    _authorize_room(claims, room_id, CapabilityKind.SEAT)
    if not claims.slot_id:
        raise ForbiddenError("Seat capability required")
    container = _container(request)
    occurrence = container.meetings.reconnect(room_id, claims.slot_id, payload.connection_id)
    if occurrence.status in {OccurrenceStatus.RUNNING, OccurrenceStatus.ENDING}:
        await container.livekit.ensure_room(occurrence)
        await container.livekit.dispatch_agent(occurrence)
    attendance = occurrence.attendance.get(claims.slot_id)
    if attendance is None:
        raise ForbiddenError("Join the occurrence before refreshing")
    room = container.repository.get_room(room_id)
    return JoinResponse(
        occurrence=occurrence,
        livekit_url=container.settings.livekit_url,
        livekit_token=container.livekit.participant_token(
            occurrence, claims.slot_id, attendance.display_name
        ),
        slot_id=claims.slot_id,
        room_name=room.name,
        agent_name=room.agent_name,
        expected_participants=room.expected_participants,
        connection_id=attendance.connection_id,
    )


@router.post("/occurrences/{occurrence_id}:start")
async def start_occurrence(request: Request, occurrence_id: str, payload: StartRequest):  # type: ignore[no-untyped-def]
    del payload
    claims = _claims(request)
    if claims.kind != CapabilityKind.SEAT or not claims.slot_id:
        raise ForbiddenError("A present participant capability is required")
    container = _container(request)
    occurrence = container.repository.get_occurrence(occurrence_id)
    if occurrence.room_id != claims.room_id:
        raise ForbiddenError("Capability does not grant access to this occurrence")
    occurrence = container.meetings.start(occurrence_id, claims.slot_id)
    await container.livekit.dispatch_agent(occurrence)
    return occurrence


@router.get("/occurrences/{occurrence_id}/state")
def occurrence_state(request: Request, occurrence_id: str):  # type: ignore[no-untyped-def]
    claims = _claims(request)
    occurrence = _container(request).repository.get_occurrence(occurrence_id)
    if claims.room_id != occurrence.room_id:
        raise ForbiddenError("Capability does not grant access to this occurrence")
    return occurrence


@router.post("/occurrences/{occurrence_id}:hand-raise")
def hand_raise(request: Request, occurrence_id: str):  # type: ignore[no-untyped-def]
    claims = _claims(request)
    if claims.kind != CapabilityKind.SEAT or not claims.slot_id:
        raise ForbiddenError("Seat capability required")
    occurrence = _container(request).repository.get_occurrence(occurrence_id)
    if occurrence.room_id != claims.room_id:
        raise ForbiddenError("Capability does not grant access to this occurrence")
    return _container(request).meetings.raise_hand(occurrence_id, claims.slot_id)


@router.get("/occurrences/{occurrence_id}/recap")
def participant_recap(request: Request, occurrence_id: str):  # type: ignore[no-untyped-def]
    claims = _claims(request)
    occurrence = _container(request).repository.get_occurrence(occurrence_id)
    if occurrence.room_id != claims.room_id:
        raise ForbiddenError("Capability does not grant access to this occurrence")
    if claims.kind == CapabilityKind.SEAT and claims.slot_id not in occurrence.attendance:
        raise ForbiddenError("Recap is available only to attendees")
    if occurrence.recap is None:
        raise NotFoundError("Recap is not ready")
    return occurrence.recap


@router.get("/rooms/{room_id}/history", response_model=list[HistoryItem])
def room_history(request: Request, room_id: str) -> list[HistoryItem]:
    claims = _claims(request)
    _authorize_room(claims, room_id, CapabilityKind.ADMIN)
    return [
        HistoryItem(
            occurrence_id=item.id,
            number=item.number,
            status=item.status,
            created_at=item.created_at,
            started_at=item.started_at,
            ended_at=item.ended_at,
            recap=item.recap,
        )
        for item in _container(request).repository.list_occurrences(room_id, limit=90)
    ]


@router.get("/rooms/{room_id}/current-occurrence")
def current_occurrence(request: Request, room_id: str):  # type: ignore[no-untyped-def]
    claims = _claims(request)
    _authorize_room(claims, room_id, CapabilityKind.ADMIN)
    return _container(request).repository.get_active_occurrence(room_id)


@router.get("/occurrences/{occurrence_id}/transcript")
def admin_transcript(request: Request, occurrence_id: str):  # type: ignore[no-untyped-def]
    claims = _claims(request)
    occurrence = _container(request).repository.get_occurrence(occurrence_id)
    _authorize_room(claims, occurrence.room_id, CapabilityKind.ADMIN)
    return _container(request).repository.list_transcript_segments(occurrence_id)


@router.post("/internal/livekit/webhook", include_in_schema=False)
async def livekit_webhook(request: Request) -> JSONResponse:
    container = _container(request)
    body = (await request.body()).decode()
    receiver = livekit_api.WebhookReceiver(
        livekit_api.TokenVerifier(
            container.settings.livekit_api_key.get_secret_value(),
            container.settings.livekit_api_secret.get_secret_value(),
        )
    )
    event = receiver.receive(body, request.headers.get("authorization", ""))
    if event.event == "participant_left" and event.room and event.participant:
        identity = event.participant.identity
        if identity.startswith("seat:"):
            try:
                container.meetings.disconnect(event.room.name, identity.removeprefix("seat:"))
            except NotFoundError:
                pass
    return JSONResponse({"ok": True})


def decode_pubsub(envelope: PubSubEnvelope) -> dict[str, Any]:
    encoded = envelope.message.get("data")
    if not isinstance(encoded, str):
        raise ValueError("Pub/Sub message data is required")
    return json.loads(base64.b64decode(encoded, validate=True))
