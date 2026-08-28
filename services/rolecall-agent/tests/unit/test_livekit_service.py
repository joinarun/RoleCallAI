from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from livekit import api

from app.container import Container
from app.domain.enums import RoleType
from app.domain.models import JoinRequest, RoomCreate
from app.services.livekit import LiveKitService


class FakeRoomApi:
    def __init__(self, existing: bool = False, participants: bool = True) -> None:
        self.existing = existing
        self.participants = participants
        self.created: list[api.CreateRoomRequest] = []
        self.updated: list[api.UpdateParticipantRequest] = []
        self.sent: list[api.SendDataRequest] = []

    async def list_rooms(self, request: api.ListRoomsRequest):  # type: ignore[no-untyped-def]
        assert len(request.names) == 1
        return SimpleNamespace(rooms=[object()] if self.existing else [])

    async def create_room(self, request: api.CreateRoomRequest):  # type: ignore[no-untyped-def]
        self.created.append(request)
        return SimpleNamespace(name=request.name)

    async def update_participant(self, request: api.UpdateParticipantRequest):  # type: ignore[no-untyped-def]
        self.updated.append(request)
        return SimpleNamespace()

    async def send_data(self, request: api.SendDataRequest):  # type: ignore[no-untyped-def]
        self.sent.append(request)
        return SimpleNamespace()

    async def list_participants(self, request: api.ListParticipantsRequest):  # type: ignore[no-untyped-def]
        assert request.room
        return SimpleNamespace(participants=[object()] if self.participants else [])


class FakeClient:
    def __init__(self, room: FakeRoomApi, agent_dispatch=None) -> None:  # type: ignore[no-untyped-def]
        self.room = room
        self.agent_dispatch = agent_dispatch
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class FakeAgentDispatchApi:
    def __init__(self) -> None:
        self.listed_rooms: list[str] = []
        self.created: list[api.CreateAgentDispatchRequest] = []

    async def list_dispatch(self, room_name: str):  # type: ignore[no-untyped-def]
        self.listed_rooms.append(room_name)
        return [SimpleNamespace(agent_name=item.agent_name) for item in self.created]

    async def create_dispatch(self, request: api.CreateAgentDispatchRequest):  # type: ignore[no-untyped-def]
        self.created.append(request)
        return SimpleNamespace(agent_name=request.agent_name)


@pytest.mark.asyncio
async def test_livekit_occurrence_room_is_created_once(container: Container) -> None:
    created = container.rooms.create(
        RoomCreate(
            name="LiveKit room",
            expected_participants=2,
            duration_minutes=15,
            role=RoleType.SCRUM_MASTER,
            agent_name="Nova",
        )
    )
    occurrence = container.meetings.get_or_create_occurrence(created.room.id)
    container.settings.env = "local"
    livekit = LiveKitService(container.settings)

    room_api = FakeRoomApi()
    client = FakeClient(room_api)
    livekit._api_client = lambda: client  # type: ignore[method-assign]
    await livekit.ensure_room(occurrence)

    assert client.closed
    assert len(room_api.created) == 1
    request = room_api.created[0]
    assert request.name == occurrence.id
    assert request.max_participants == 11
    assert request.egress == api.RoomEgress()

    existing_api = FakeRoomApi(existing=True)
    existing_client = FakeClient(existing_api)
    livekit._api_client = lambda: existing_client  # type: ignore[method-assign]
    await livekit.ensure_room(occurrence)
    assert existing_api.created == []


@pytest.mark.asyncio
async def test_livekit_floor_enforcement_and_recap_message_are_server_scoped(
    container: Container,
) -> None:
    created = container.rooms.create(
        RoomCreate(
            name="LiveKit messages",
            expected_participants=2,
            duration_minutes=15,
            role=RoleType.SCRUM_MASTER,
            agent_name="Nova",
        )
    )
    room = container.repository.get_room(created.room.id)
    occurrence = container.meetings.join(
        room.id,
        room.slots[0].id,
        JoinRequest(name="Ada", consent_version="v1", connection_id="connection-ada"),
    )
    livekit = LiveKitService(container.settings)
    room_api = FakeRoomApi(existing=True)
    client = FakeClient(room_api)
    livekit._api_client = lambda: client  # type: ignore[method-assign]

    await livekit.enforce_floor(occurrence)
    assert [item.identity for item in room_api.updated] == [f"seat:{room.slots[0].id}"]
    assert room_api.updated[0].permission.can_publish is False

    sent = await livekit.publish_message(occurrence, "recap.ready", {"summary": "Done"})
    assert sent
    message = json.loads(room_api.sent[0].data)
    assert message["type"] == "recap.ready"
    assert message["occurrenceId"] == occurrence.id

    empty_api = FakeRoomApi(existing=True, participants=False)
    empty_client = FakeClient(empty_api)
    livekit._api_client = lambda: empty_client  # type: ignore[method-assign]
    assert not await livekit.publish_message(occurrence, "recap.ready", {"summary": "Done"})
    assert empty_api.sent == []
    assert empty_client.closed


@pytest.mark.asyncio
async def test_livekit_agent_dispatch_uses_current_sdk_contract_and_is_idempotent(
    container: Container,
) -> None:
    created = container.rooms.create(
        RoomCreate(
            name="LiveKit dispatch",
            expected_participants=2,
            duration_minutes=15,
            role=RoleType.SCRUM_MASTER,
            agent_name="Nova",
        )
    )
    occurrence = container.meetings.get_or_create_occurrence(created.room.id)
    livekit = LiveKitService(container.settings)
    dispatch_api = FakeAgentDispatchApi()
    client = FakeClient(FakeRoomApi(existing=True), dispatch_api)
    livekit._api_client = lambda: client  # type: ignore[method-assign]

    await livekit.dispatch_agent(occurrence)
    await livekit.dispatch_agent(occurrence)

    assert dispatch_api.listed_rooms == [occurrence.id, occurrence.id]
    assert len(dispatch_api.created) == 1
    assert dispatch_api.created[0].room == occurrence.id
    assert dispatch_api.created[0].agent_name == "rolecall-meeting"
    assert json.loads(dispatch_api.created[0].metadata) == {"occurrenceId": occurrence.id}
    assert client.closed
