"""Versioned RoleCallAI HTTP API."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from livekit import api as livekit_api
from pydantic import BaseModel

from app.container import Container
from app.domain.enums import CapabilityKind, OccurrenceStatus
from app.domain.errors import ForbiddenError, NotFoundError, RateLimitError, UnauthorizedError
from app.domain.models import (
    CapabilityClaims,
    CapabilityExchangeRequest,
    CapabilityExchangeResponse,
    DashboardRoomsResponse,
    EndMeetingRequest,
    HistoryItem,
    JoinRequest,
    JoinResponse,
    LeaveRequest,
    ParticipantRoomView,
    RefreshRequest,
    RoomCreate,
    RoomCreatedResponse,
    StartRequest,
)
from app.jobs.outbox import publish_outbox_record

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
        raise ForbiddenError("This private room is not available with the current link")


def _history_item(occurrence):  # type: ignore[no-untyped-def]
    participant_names: list[str] = []
    seen_slots: set[str] = set()
    for slot_id in [*occurrence.turn_order, *occurrence.attendance]:
        if slot_id in seen_slots:
            continue
        seen_slots.add(slot_id)
        attendance = occurrence.attendance.get(slot_id)
        if attendance and attendance.display_name not in participant_names:
            participant_names.append(attendance.display_name)
    duration_seconds = None
    if occurrence.started_at and occurrence.ended_at:
        duration_seconds = max(
            0,
            int((occurrence.ended_at - occurrence.started_at).total_seconds()),
        )
    return HistoryItem(
        occurrence_id=occurrence.id,
        number=occurrence.number,
        status=occurrence.status,
        created_at=occurrence.created_at,
        started_at=occurrence.started_at,
        ended_at=occurrence.ended_at,
        recap=occurrence.recap,
        participants=participant_names,
        duration_seconds=duration_seconds,
    )


async def _publish_postprocess_now(container: Container, occurrence_id: str) -> None:
    """Reduce recap latency while preserving the scheduled outbox retry."""
    if not container.settings.immediate_outbox_publish:
        return
    try:
        await asyncio.to_thread(
            publish_outbox_record,
            container.settings,
            container.repository,
            f"postprocess:{occurrence_id}",
        )
    except Exception as exc:
        logger.warning(
            "event=outbox_immediate_publish_deferred occurrence_id=%s error_type=%s",
            occurrence_id,
            type(exc).__name__,
        )


@router.post("/rooms", response_model=RoomCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_room(request: Request, payload: RoomCreate) -> RoomCreatedResponse:
    del request, payload
    raise UnauthorizedError("Admin login required")


@router.post("/dashboard/rooms", response_model=DashboardRoomsResponse)
def dashboard_rooms(request: Request) -> DashboardRoomsResponse:
    del request
    raise UnauthorizedError("Admin login required")


@router.post("/capability-sessions", response_model=CapabilityExchangeResponse)
def exchange_capability(
    request: Request, response: Response, payload: CapabilityExchangeRequest
) -> CapabilityExchangeResponse:
    container = _container(request)
    try:
        cookie, claims = container.capabilities.exchange(payload.room_id, payload.token)
    except UnauthorizedError as exc:
        try:
            container.rate_limits.enforce(
                "capability-failure",
                _client_ip(request),
                container.settings.capability_failure_rate_per_minute,
                timedelta(minutes=1),
            )
        except RateLimitError as rate_error:
            raise rate_error from exc
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
    if claims.room_id != room_id or claims.kind != CapabilityKind.SEAT or not claims.slot_id:
        raise ForbiddenError("This private room is not available with the current link")
    room = _container(request).repository.get_room(room_id)
    return ParticipantRoomView.from_room_and_slot(room, claims.slot_id)


@router.patch("/rooms/{room_id}")
def update_room(request: Request, room_id: str) -> None:
    del request, room_id
    raise UnauthorizedError("Use the authenticated admin dashboard")


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_room(request: Request, room_id: str) -> None:
    del request, room_id
    raise UnauthorizedError("Use the authenticated admin dashboard")


@router.post(
    "/rooms/{room_id}/slots/{slot_id}:regenerate",
    response_model=dict[str, str],
)
def regenerate_seat(request: Request, room_id: str, slot_id: str) -> dict[str, str]:
    del request, room_id, slot_id
    raise UnauthorizedError("Use the authenticated admin dashboard")


@router.put(
    "/rooms/{room_id}/slots/{slot_id}:end-meeting-permission",
)
async def set_end_meeting_permission(
    request: Request,
    room_id: str,
    slot_id: str,
) -> None:
    del request, room_id, slot_id
    raise UnauthorizedError("Use the authenticated admin dashboard")


@router.post("/rooms/{room_id}:join", response_model=JoinResponse)
async def join_room(request: Request, room_id: str, payload: JoinRequest) -> JoinResponse:
    claims = _claims(request)
    _authorize_room(claims, room_id, CapabilityKind.SEAT)
    if not claims.slot_id:
        raise ForbiddenError("Seat capability required")
    container = _container(request)
    container.runtime.require_ready()
    occurrence = container.meetings.join(room_id, claims.slot_id, payload)
    container.runtime.activity()
    await container.livekit.ensure_room(occurrence)
    if occurrence.status in {OccurrenceStatus.RUNNING, OccurrenceStatus.ENDING}:
        await container.livekit.dispatch_agent(occurrence)
    room = container.repository.get_room(room_id)
    seat = next(item for item in room.slots if item.id == claims.slot_id)
    return JoinResponse(
        occurrence=occurrence,
        livekit_url=container.settings.livekit_url,
        livekit_token=container.livekit.participant_token(occurrence, claims.slot_id, payload.name),
        slot_id=claims.slot_id,
        room_name=room.name,
        agent_name=room.agent_name,
        expected_participants=room.expected_participants,
        connection_id=payload.connection_id,
        can_end_meeting=seat.can_end_meeting,
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
    container.runtime.require_ready()
    occurrence = container.meetings.reconnect(room_id, claims.slot_id, payload.connection_id)
    container.runtime.activity()
    if occurrence.status in {OccurrenceStatus.RUNNING, OccurrenceStatus.ENDING}:
        await container.livekit.ensure_room(occurrence)
        await container.livekit.dispatch_agent(occurrence)
    attendance = occurrence.attendance.get(claims.slot_id)
    if attendance is None:
        raise ForbiddenError("Join the occurrence before refreshing")
    room = container.repository.get_room(room_id)
    seat = next(item for item in room.slots if item.id == claims.slot_id)
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
        can_end_meeting=seat.can_end_meeting,
    )


@router.post("/occurrences/{occurrence_id}:start")
async def start_occurrence(request: Request, occurrence_id: str, payload: StartRequest):  # type: ignore[no-untyped-def]
    del payload
    claims = _claims(request)
    if claims.kind != CapabilityKind.SEAT or not claims.slot_id:
        raise ForbiddenError("A present participant capability is required")
    container = _container(request)
    container.runtime.require_ready()
    occurrence = container.repository.get_occurrence(occurrence_id)
    if occurrence.room_id != claims.room_id:
        raise ForbiddenError("This meeting is not available with the current link")
    occurrence = container.meetings.start(occurrence_id, claims.slot_id)
    container.runtime.activity()
    await container.livekit.dispatch_agent(occurrence)
    return occurrence


@router.get("/occurrences/{occurrence_id}/state")
def occurrence_state(request: Request, occurrence_id: str):  # type: ignore[no-untyped-def]
    claims = _claims(request)
    occurrence = _container(request).repository.get_occurrence(occurrence_id)
    if claims.room_id != occurrence.room_id:
        raise ForbiddenError("This meeting is not available with the current link")
    return occurrence


@router.post("/occurrences/{occurrence_id}:hand-raise")
def hand_raise(request: Request, occurrence_id: str):  # type: ignore[no-untyped-def]
    claims = _claims(request)
    if claims.kind != CapabilityKind.SEAT or not claims.slot_id:
        raise ForbiddenError("Seat capability required")
    occurrence = _container(request).repository.get_occurrence(occurrence_id)
    if occurrence.room_id != claims.room_id:
        raise ForbiddenError("This meeting is not available with the current link")
    container = _container(request)
    container.runtime.activity()
    return container.meetings.raise_hand(occurrence_id, claims.slot_id)


@router.post("/occurrences/{occurrence_id}:leave")
async def leave_occurrence(request: Request, occurrence_id: str, payload: LeaveRequest):  # type: ignore[no-untyped-def]
    claims = _claims(request)
    if claims.kind != CapabilityKind.SEAT or not claims.slot_id:
        raise ForbiddenError("Seat capability required")
    container = _container(request)
    occurrence = container.repository.get_occurrence(occurrence_id)
    if occurrence.room_id != claims.room_id:
        raise ForbiddenError("This meeting is not available with the current link")
    occurrence = container.meetings.leave(occurrence_id, claims.slot_id, payload.connection_id)
    container.runtime.activity()
    await container.livekit.enforce_floor(occurrence)
    await container.livekit.publish_message(
        occurrence, "meeting.state", occurrence.model_dump(mode="json")
    )
    if occurrence.status == OccurrenceStatus.PROCESSING:
        await _publish_postprocess_now(container, occurrence.id)
    return occurrence


@router.post("/occurrences/{occurrence_id}:end")
async def end_occurrence(
    request: Request,
    occurrence_id: str,
    payload: EndMeetingRequest | None = None,
):  # type: ignore[no-untyped-def]
    claims = _claims(request)
    container = _container(request)
    occurrence = container.repository.get_occurrence(occurrence_id)
    if occurrence.room_id != claims.room_id:
        raise ForbiddenError("This meeting is not available with the current link")

    if claims.kind != CapabilityKind.SEAT or not claims.slot_id:
        raise ForbiddenError("A delegated participant capability is required")
    room = container.repository.get_room(occurrence.room_id)
    seat = next((item for item in room.slots if item.id == claims.slot_id), None)
    attendance = occurrence.attendance.get(claims.slot_id)
    if not seat or not seat.can_end_meeting or not attendance or not attendance.connected:
        raise ForbiddenError("This participant cannot end the meeting for everyone")
    reason = "ended_by_delegated_participant"

    if payload and payload.reason.startswith("agent_"):
        # Preserve the operational meaning of agent_* failure reasons for the
        # worker only; public callers cannot manufacture a worker failure.
        raise ForbiddenError("Reserved meeting end reason")
    occurrence = container.meetings.finish(occurrence_id, reason)
    container.runtime.activity()
    await container.livekit.enforce_floor(occurrence)
    await container.livekit.publish_message(
        occurrence, "meeting.state", occurrence.model_dump(mode="json")
    )
    await _publish_postprocess_now(container, occurrence.id)
    return occurrence


@router.get("/occurrences/{occurrence_id}/recap")
def participant_recap(request: Request, occurrence_id: str):  # type: ignore[no-untyped-def]
    claims = _claims(request)
    occurrence = _container(request).repository.get_occurrence(occurrence_id)
    if occurrence.room_id != claims.room_id:
        raise ForbiddenError("This meeting is not available with the current link")
    if claims.kind == CapabilityKind.SEAT and claims.slot_id not in occurrence.attendance:
        raise ForbiddenError("Recap is available only to attendees")
    if occurrence.recap is None:
        raise NotFoundError("Recap is not ready")
    return occurrence.recap


@router.get("/rooms/{room_id}/history", response_model=list[HistoryItem])
def room_history(request: Request, room_id: str) -> list[HistoryItem]:
    del request, room_id
    raise UnauthorizedError("Use the authenticated admin dashboard")


@router.get("/rooms/{room_id}/current-occurrence")
def current_occurrence(request: Request, room_id: str):  # type: ignore[no-untyped-def]
    del request, room_id
    raise UnauthorizedError("Use the authenticated admin dashboard")


@router.get("/occurrences/{occurrence_id}/transcript")
def admin_transcript(request: Request, occurrence_id: str):  # type: ignore[no-untyped-def]
    del request, occurrence_id
    raise UnauthorizedError("Use the authenticated admin dashboard")


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
