"""Authenticated administration, document, and runtime API."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, File, Header, Request, Response, UploadFile, status

from app.container import Container
from app.domain.errors import ForbiddenError
from app.domain.models import (
    AdminLoginRequest,
    AdminSession,
    AdminSessionView,
    DashboardRoomItem,
    DashboardRoomsResponse,
    DocumentView,
    EndMeetingPermissionRequest,
    EndMeetingRequest,
    HistoryItem,
    RoomCreate,
    RoomCreatedResponse,
    RoomPatch,
    RoomUpdatedResponse,
    RoomView,
    RuntimeState,
    SeatLinkView,
)

router = APIRouter(prefix="/v1")


def _container(request: Request) -> Container:
    return request.app.state.container


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",", 1)[0].strip() or (
        request.client.host if request.client else "0.0.0.0"
    )


def _origin(request: Request) -> str:
    value = request.headers.get("origin", "")
    parsed = urlsplit(value)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""


def _require_same_origin(request: Request) -> None:
    expected = _container(request).settings.public_base_url.rstrip("/")
    if _origin(request) != expected:
        raise ForbiddenError("Invalid request origin")


def _admin(request: Request) -> AdminSession:
    container = _container(request)
    cookie = request.cookies.get(container.settings.admin_cookie_name)
    session, _, _ = container.admin_auth.authenticate(cookie)
    return session


def _admin_mutation(request: Request, csrf_token: str | None) -> AdminSession:
    _require_same_origin(request)
    container = _container(request)
    cookie = request.cookies.get(container.settings.admin_cookie_name)
    return container.admin_auth.require_csrf(cookie, csrf_token)


def _require_owned_room(request: Request, room_id: str) -> AdminSession:
    session = _admin(request)
    room = _container(request).repository.get_room(room_id)
    if room.owner_id != session.owner_id:
        raise ForbiddenError("Room is not owned by this administrator")
    return session


def _history_item(occurrence) -> HistoryItem:  # type: ignore[no-untyped-def]
    duration_seconds = None
    if occurrence.started_at and occurrence.ended_at:
        duration_seconds = max(
            0, int((occurrence.ended_at - occurrence.started_at).total_seconds())
        )
    return HistoryItem(
        occurrence_id=occurrence.id,
        number=occurrence.number,
        status=occurrence.status,
        created_at=occurrence.created_at,
        started_at=occurrence.started_at,
        ended_at=occurrence.ended_at,
        recap=occurrence.recap,
        participants=[item.display_name for item in occurrence.attendance.values()],
        duration_seconds=duration_seconds,
    )


@router.get("/auth/config")
def auth_config(request: Request) -> dict[str, str]:
    settings = _container(request).settings
    return {"recaptchaSiteKey": settings.recaptcha_site_key, "action": settings.recaptcha_action}


@router.post("/auth/login", response_model=AdminSessionView)
def login(
    request: Request,
    response: Response,
    payload: AdminLoginRequest,
) -> AdminSessionView:
    _require_same_origin(request)
    container = _container(request)
    cookie, view = container.admin_auth.login(
        payload.username,
        payload.password,
        payload.recaptcha_token,
        _client_ip(request),
    )
    response.set_cookie(
        key=container.settings.admin_cookie_name,
        value=cookie,
        max_age=container.settings.admin_session_hours * 60 * 60,
        secure=container.settings.cookie_secure,
        httponly=True,
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    container.runtime.activity()
    return view


@router.get("/auth/session", response_model=AdminSessionView)
def auth_session(request: Request, response: Response) -> AdminSessionView:
    container = _container(request)
    response.headers["Cache-Control"] = "no-store"
    return container.admin_auth.session_view(
        request.cookies.get(container.settings.admin_cookie_name)
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    x_csrf_token: str | None = Header(default=None),
) -> None:
    _admin_mutation(request, x_csrf_token)
    container = _container(request)
    container.admin_auth.logout(request.cookies.get(container.settings.admin_cookie_name))
    response.delete_cookie(container.settings.admin_cookie_name, path="/")
    response.headers["Cache-Control"] = "no-store"


@router.get("/runtime", response_model=RuntimeState)
def runtime_state(request: Request) -> RuntimeState:
    return _container(request).runtime.get()


@router.post("/runtime:wake", response_model=RuntimeState)
def wake_runtime(
    request: Request,
    x_csrf_token: str | None = Header(default=None),
) -> RuntimeState:
    _admin_mutation(request, x_csrf_token)
    return _container(request).runtime.wake()


@router.post("/runtime/activity", response_model=RuntimeState)
def runtime_activity(
    request: Request,
    x_csrf_token: str | None = Header(default=None),
) -> RuntimeState:
    _admin_mutation(request, x_csrf_token)
    return _container(request).runtime.activity()


@router.get("/admin/rooms", response_model=DashboardRoomsResponse)
def list_rooms(request: Request) -> DashboardRoomsResponse:
    session = _admin(request)
    container = _container(request)
    items: list[DashboardRoomItem] = []
    for room in container.repository.list_rooms(session.owner_id):
        current = container.repository.get_active_occurrence(room.id)
        history = [
            _history_item(item) for item in container.repository.list_occurrences(room.id, limit=90)
        ]
        items.append(
            DashboardRoomItem(
                room=RoomView.from_room(room),
                current_occurrence=current,
                history=history,
            )
        )
    return DashboardRoomsResponse(rooms=items)


@router.post(
    "/admin/rooms",
    response_model=RoomCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_room(
    request: Request,
    payload: RoomCreate,
    x_csrf_token: str | None = Header(default=None),
) -> RoomCreatedResponse:
    _admin_mutation(request, x_csrf_token)
    container = _container(request)
    container.rate_limits.enforce(
        "room-create",
        _client_ip(request),
        container.settings.room_create_rate_per_hour,
        timedelta(hours=1),
    )
    created = container.rooms.create(payload)
    container.runtime.activity()
    return created


@router.get("/admin/rooms/{room_id}", response_model=RoomView)
def get_room(request: Request, room_id: str) -> RoomView:
    _require_owned_room(request, room_id)
    return RoomView.from_room(_container(request).repository.get_room(room_id))


@router.patch("/admin/rooms/{room_id}", response_model=RoomUpdatedResponse)
def update_room(
    request: Request,
    room_id: str,
    payload: RoomPatch,
    x_csrf_token: str | None = Header(default=None),
) -> RoomUpdatedResponse:
    _admin_mutation(request, x_csrf_token)
    _require_owned_room(request, room_id)
    result = _container(request).rooms.update(room_id, payload)
    _container(request).runtime.activity()
    return result


@router.delete("/admin/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_room(
    request: Request,
    room_id: str,
    x_csrf_token: str | None = Header(default=None),
) -> None:
    _admin_mutation(request, x_csrf_token)
    _require_owned_room(request, room_id)
    _container(request).rooms.delete(room_id)


@router.get("/admin/rooms/{room_id}/seat-links", response_model=list[SeatLinkView])
def seat_links(request: Request, response: Response, room_id: str) -> list[SeatLinkView]:
    _require_owned_room(request, room_id)
    response.headers["Cache-Control"] = "no-store"
    return _container(request).rooms.seat_link_views(room_id)


@router.post(
    "/admin/rooms/{room_id}/slots/{slot_id}:regenerate",
    response_model=dict[str, str],
)
def regenerate_seat(
    request: Request,
    response: Response,
    room_id: str,
    slot_id: str,
    x_csrf_token: str | None = Header(default=None),
) -> dict[str, str]:
    _admin_mutation(request, x_csrf_token)
    _require_owned_room(request, room_id)
    response.headers["Cache-Control"] = "no-store"
    return {"url": _container(request).rooms.regenerate_seat(room_id, slot_id)}


@router.put(
    "/admin/rooms/{room_id}/slots/{slot_id}:end-meeting-permission",
    response_model=RoomView,
)
async def set_end_permission(
    request: Request,
    room_id: str,
    slot_id: str,
    payload: EndMeetingPermissionRequest,
    x_csrf_token: str | None = Header(default=None),
) -> RoomView:
    _admin_mutation(request, x_csrf_token)
    _require_owned_room(request, room_id)
    container = _container(request)
    room = container.rooms.set_end_meeting_permission(room_id, slot_id, payload.allowed)
    active = container.repository.get_active_occurrence(room_id)
    if active:
        await container.livekit.publish_message(
            active, "meeting.state", active.model_dump(mode="json")
        )
    return room


@router.get("/admin/rooms/{room_id}/history", response_model=list[HistoryItem])
def room_history(request: Request, room_id: str) -> list[HistoryItem]:
    _require_owned_room(request, room_id)
    return [
        _history_item(item)
        for item in _container(request).repository.list_occurrences(room_id, limit=90)
    ]


@router.get("/admin/occurrences/{occurrence_id}/transcript")
def transcript(request: Request, occurrence_id: str):  # type: ignore[no-untyped-def]
    occurrence = _container(request).repository.get_occurrence(occurrence_id)
    _require_owned_room(request, occurrence.room_id)
    return _container(request).repository.list_transcript_segments(occurrence_id)


@router.post("/admin/occurrences/{occurrence_id}:end")
async def end_occurrence(
    request: Request,
    occurrence_id: str,
    payload: EndMeetingRequest,
    x_csrf_token: str | None = Header(default=None),
):  # type: ignore[no-untyped-def]
    _admin_mutation(request, x_csrf_token)
    container = _container(request)
    occurrence = container.repository.get_occurrence(occurrence_id)
    _require_owned_room(request, occurrence.room_id)
    if occurrence.status.active:
        occurrence = container.meetings.finish(occurrence_id, payload.reason)
        await container.livekit.publish_message(
            occurrence, "meeting.state", occurrence.model_dump(mode="json")
        )
    return occurrence


@router.get("/admin/rooms/{room_id}/documents", response_model=list[DocumentView])
def list_documents(request: Request, room_id: str) -> list[DocumentView]:
    _require_owned_room(request, room_id)
    return _container(request).documents.list(room_id)


@router.post(
    "/admin/rooms/{room_id}/documents",
    response_model=DocumentView,
    status_code=status.HTTP_202_ACCEPTED,
)
def upload_document(
    request: Request,
    room_id: str,
    file: Annotated[UploadFile, File()],
    x_csrf_token: str | None = Header(default=None),
) -> DocumentView:
    _admin_mutation(request, x_csrf_token)
    _require_owned_room(request, room_id)
    if not file.filename:
        raise ValueError("Document filename is required")
    container = _container(request)
    container.rate_limits.enforce(
        "document-upload",
        _client_ip(request),
        container.settings.document_upload_rate_per_hour,
        timedelta(hours=1),
    )
    result = container.documents.upload(
        room_id, file.filename, file.content_type or "application/octet-stream", file.file
    )
    container.runtime.activity()
    return result


@router.post(
    "/admin/rooms/{room_id}/documents/{document_id}:replace",
    response_model=DocumentView,
    status_code=status.HTTP_202_ACCEPTED,
)
def replace_document(
    request: Request,
    room_id: str,
    document_id: str,
    file: Annotated[UploadFile, File()],
    x_csrf_token: str | None = Header(default=None),
) -> DocumentView:
    _admin_mutation(request, x_csrf_token)
    _require_owned_room(request, room_id)
    if not file.filename:
        raise ValueError("Document filename is required")
    container = _container(request)
    container.rate_limits.enforce(
        "document-upload",
        _client_ip(request),
        container.settings.document_upload_rate_per_hour,
        timedelta(hours=1),
    )
    return container.documents.upload(
        room_id,
        file.filename,
        file.content_type or "application/octet-stream",
        file.file,
        document_id=document_id,
    )


@router.post(
    "/admin/rooms/{room_id}/documents/{document_id}:retry",
    response_model=DocumentView,
)
def retry_document(
    request: Request,
    room_id: str,
    document_id: str,
    x_csrf_token: str | None = Header(default=None),
) -> DocumentView:
    _admin_mutation(request, x_csrf_token)
    _require_owned_room(request, room_id)
    return _container(request).documents.retry(room_id, document_id)


@router.delete(
    "/admin/rooms/{room_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_document(
    request: Request,
    room_id: str,
    document_id: str,
    x_csrf_token: str | None = Header(default=None),
) -> None:
    _admin_mutation(request, x_csrf_token)
    _require_owned_room(request, room_id)
    _container(request).documents.delete(room_id, document_id)
