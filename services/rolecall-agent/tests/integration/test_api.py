from __future__ import annotations

from fastapi.testclient import TestClient

from app.container import Container
from app.fast_api_app import app


def room_payload(name: str = "API room") -> dict[str, object]:
    return {
        "name": name,
        "expectedParticipants": 2,
        "durationMinutes": 10,
        "role": "SCRUM_MASTER",
        "agentName": "Nova",
        "instructions": "Keep it focused.",
        "game": None,
    }


def exchange(client: TestClient, room_id: str, url: str) -> None:
    token = url.split("#cap=", 1)[1]
    response = client.post("/v1/capability-sessions", json={"roomId": room_id, "token": token})
    assert response.status_code == 200, response.text


def capability_token(url: str) -> str:
    return url.split("#cap=", 1)[1]


def test_dashboard_resolves_only_admin_links_supplied_by_the_browser(
    container: Container,
) -> None:
    with TestClient(app) as client:
        app.state.container = container
        first = client.post("/v1/rooms", json=room_payload("Dashboard one")).json()
        second = client.post("/v1/rooms", json=room_payload("Dashboard two")).json()
        response = client.post(
            "/v1/dashboard/rooms",
            json={
                "rooms": [
                    {
                        "roomId": first["room"]["id"],
                        "token": capability_token(first["adminUrl"]),
                    },
                    {
                        "roomId": second["room"]["id"],
                        "token": capability_token(second["adminUrl"]),
                    },
                ]
            },
        )
        assert response.status_code == 200, response.text
        assert [item["room"]["name"] for item in response.json()["rooms"]] == [
            "Dashboard one",
            "Dashboard two",
        ]
        assert response.json()["unavailableRoomIds"] == []
        assert capability_token(first["adminUrl"]) not in response.text

        seat_is_not_admin = client.post(
            "/v1/dashboard/rooms",
            json={
                "rooms": [
                    {
                        "roomId": first["room"]["id"],
                        "token": capability_token(first["seatUrls"][0]["url"]),
                    }
                ]
            },
        )
        assert seat_is_not_admin.status_code == 200
        assert seat_is_not_admin.json()["rooms"] == []
        assert seat_is_not_admin.json()["unavailableRoomIds"] == [first["room"]["id"]]


def test_end_to_end_capability_room_and_join_flow(container: Container) -> None:
    with TestClient(app) as client:
        app.state.container = container
        created_response = client.post("/v1/rooms", json=room_payload())
        assert created_response.status_code == 201, created_response.text
        created = created_response.json()
        room_id = created["room"]["id"]
        assert "capabilityDigest" not in created_response.text

        admin = TestClient(app)
        app.state.container = container
        exchange(admin, room_id, created["adminUrl"])
        assert admin.get(f"/v1/rooms/{room_id}").status_code == 200
        assert admin.get(f"/v1/rooms/{room_id}/history").json() == []

        participants: list[TestClient] = []
        join_results = []
        for index, invite in enumerate(created["seatUrls"], start=1):
            participant = TestClient(app)
            app.state.container = container
            exchange(participant, room_id, invite["url"])
            current = participant.get("/v1/capability-sessions/current")
            assert current.json()["scope"] == "SEAT"
            joined = participant.post(
                f"/v1/rooms/{room_id}:join",
                json={
                    "name": f"Person {index}",
                    "consentVersion": "v1",
                    "connectionId": f"connection-{index}",
                },
            )
            assert joined.status_code == 200, joined.text
            join_results.append(joined.json())
            participants.append(participant)

        assert join_results[0]["occurrence"]["status"] == "LOBBY"
        assert join_results[1]["occurrence"]["status"] == "RUNNING"
        occurrence_id = join_results[1]["occurrence"]["id"]
        assert container.livekit.ensured == [occurrence_id]  # type: ignore[attr-defined]
        assert container.livekit.dispatched == [occurrence_id]  # type: ignore[attr-defined]
        assert participants[0].get(f"/v1/rooms/{room_id}/history").status_code == 403
        assert admin.get(f"/v1/rooms/{room_id}/current-occurrence").json()["id"] == occurrence_id


def test_duplicate_seat_is_rejected_over_http(container: Container) -> None:
    with TestClient(app) as creator:
        app.state.container = container
        created = creator.post("/v1/rooms", json=room_payload("Duplicate room")).json()
        room_id = created["room"]["id"]
        participant = TestClient(app)
        app.state.container = container
        exchange(participant, room_id, created["seatUrls"][0]["url"])
        first = participant.post(
            f"/v1/rooms/{room_id}:join",
            json={"name": "One", "consentVersion": "v1", "connectionId": "connection-a"},
        )
        assert first.status_code == 200
        duplicate = participant.post(
            f"/v1/rooms/{room_id}:join",
            json={"name": "One", "consentVersion": "v1", "connectionId": "connection-b"},
        )
        assert duplicate.status_code == 409


def test_refresh_reconnects_only_the_original_browser_connection(container: Container) -> None:
    with TestClient(app) as creator:
        app.state.container = container
        created = creator.post("/v1/rooms", json=room_payload("Reconnect room")).json()
        room_id = created["room"]["id"]
        participant = TestClient(app)
        app.state.container = container
        exchange(participant, room_id, created["seatUrls"][0]["url"])
        joined = participant.post(
            f"/v1/rooms/{room_id}:join",
            json={
                "name": "One",
                "consentVersion": "v1",
                "connectionId": "connection-original",
            },
        ).json()
        occurrence_id = joined["occurrence"]["id"]
        slot_id = joined["slotId"]

        second = TestClient(app)
        app.state.container = container
        exchange(second, room_id, created["seatUrls"][1]["url"])
        started = second.post(
            f"/v1/rooms/{room_id}:join",
            json={
                "name": "Two",
                "consentVersion": "v1",
                "connectionId": "connection-second",
            },
        )
        assert started.status_code == 200
        assert started.json()["occurrence"]["status"] == "RUNNING"
        container.meetings.disconnect(occurrence_id, slot_id)

        rejected = participant.post(
            f"/v1/rooms/{room_id}:refresh",
            json={"connectionId": "connection-imposter"},
        )
        assert rejected.status_code == 409

        refreshed = participant.post(
            f"/v1/rooms/{room_id}:refresh",
            json={"connectionId": "connection-original"},
        )
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["connectionId"] == "connection-original"
        assert refreshed.json()["occurrence"]["attendance"][slot_id]["connected"] is True
        assert container.livekit.dispatch_attempts == [  # type: ignore[attr-defined]
            occurrence_id,
            occurrence_id,
        ]


def test_admin_delegates_end_meeting_and_only_authorized_seat_can_use_it(
    container: Container,
) -> None:
    with TestClient(app) as creator:
        app.state.container = container
        created = creator.post("/v1/rooms", json=room_payload("Delegated controls")).json()
        room_id = created["room"]["id"]

        admin = TestClient(app)
        app.state.container = container
        exchange(admin, room_id, created["adminUrl"])

        participants: list[TestClient] = []
        joins: list[dict] = []
        for index, invitation in enumerate(created["seatUrls"], start=1):
            participant = TestClient(app)
            app.state.container = container
            exchange(participant, room_id, invitation["url"])
            joined = participant.post(
                f"/v1/rooms/{room_id}:join",
                json={
                    "name": f"Person {index}",
                    "consentVersion": "v1",
                    "connectionId": f"control-connection-{index}",
                },
            )
            assert joined.status_code == 200, joined.text
            participants.append(participant)
            joins.append(joined.json())

        occurrence_id = joins[-1]["occurrence"]["id"]
        delegated_slot = joins[0]["slotId"]
        permission = admin.put(
            f"/v1/rooms/{room_id}/slots/{delegated_slot}:end-meeting-permission",
            json={"allowed": True},
        )
        assert permission.status_code == 200, permission.text
        assert (
            next(slot for slot in permission.json()["slots"] if slot["id"] == delegated_slot)[
                "canEndMeeting"
            ]
            is True
        )
        state = participants[0].get(f"/v1/occurrences/{occurrence_id}/state").json()
        assert delegated_slot in state["endMeetingSlotIds"]

        rejected = participants[1].post(f"/v1/occurrences/{occurrence_id}:end")
        assert rejected.status_code == 403
        revoked = admin.put(
            f"/v1/rooms/{room_id}/slots/{delegated_slot}:end-meeting-permission",
            json={"allowed": False},
        )
        assert revoked.status_code == 200
        assert participants[0].post(f"/v1/occurrences/{occurrence_id}:end").status_code == 403
        admin.put(
            f"/v1/rooms/{room_id}/slots/{delegated_slot}:end-meeting-permission",
            json={"allowed": True},
        )
        ended = participants[0].post(f"/v1/occurrences/{occurrence_id}:end")
        assert ended.status_code == 200, ended.text
        assert ended.json()["status"] == "PROCESSING"
        assert container.livekit.enforced[-1] == occurrence_id  # type: ignore[attr-defined]
        assert container.livekit.published[-1] == (occurrence_id, "meeting.state")  # type: ignore[attr-defined]


def test_participant_can_intentionally_leave_without_reconnect_hold(container: Container) -> None:
    with TestClient(app) as creator:
        app.state.container = container
        created = creator.post("/v1/rooms", json=room_payload("Leave control")).json()
        room_id = created["room"]["id"]
        participant = TestClient(app)
        app.state.container = container
        exchange(participant, room_id, created["seatUrls"][0]["url"])
        joined = participant.post(
            f"/v1/rooms/{room_id}:join",
            json={
                "name": "Leaver",
                "consentVersion": "v1",
                "connectionId": "leaving-connection",
            },
        ).json()

        rejected = participant.post(
            f"/v1/occurrences/{joined['occurrence']['id']}:leave",
            json={"connectionId": "wrong-connection"},
        )
        assert rejected.status_code == 409
        left = participant.post(
            f"/v1/occurrences/{joined['occurrence']['id']}:leave",
            json={"connectionId": "leaving-connection"},
        )
        assert left.status_code == 200, left.text
        assert left.json()["status"] == "PROCESSING"


def test_admin_can_end_a_lobby_for_everyone(container: Container) -> None:
    with TestClient(app) as creator:
        app.state.container = container
        created = creator.post("/v1/rooms", json=room_payload("Admin end lobby")).json()
        room_id = created["room"]["id"]
        admin = TestClient(app)
        app.state.container = container
        exchange(admin, room_id, created["adminUrl"])
        participant = TestClient(app)
        app.state.container = container
        exchange(participant, room_id, created["seatUrls"][0]["url"])
        joined = participant.post(
            f"/v1/rooms/{room_id}:join",
            json={
                "name": "Waiting person",
                "consentVersion": "v1",
                "connectionId": "admin-end-connection",
            },
        ).json()

        ended = admin.post(f"/v1/occurrences/{joined['occurrence']['id']}:end")
        assert ended.status_code == 200, ended.text
        assert ended.json()["status"] == "PROCESSING"
