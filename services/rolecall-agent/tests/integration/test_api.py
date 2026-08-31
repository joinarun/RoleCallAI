from __future__ import annotations

from fastapi.testclient import TestClient

from app.container import Container
from app.domain.enums import RuntimeStatus
from app.fast_api_app import app

BASE_URL = "https://rolecall.test"
ORIGIN = {"Origin": BASE_URL}


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


def login_admin(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/v1/auth/login",
        headers=ORIGIN,
        json={
            "username": "judge-local",
            "password": "local-rolecall-admin-password",
            "recaptchaToken": "test-assessment",
        },
    )
    assert response.status_code == 200, response.text
    return {**ORIGIN, "X-CSRF-Token": response.json()["csrfToken"]}


def create_room(client: TestClient, headers: dict[str, str], name: str = "API room") -> dict:
    response = client.post("/v1/admin/rooms", headers=headers, json=room_payload(name))
    assert response.status_code == 201, response.text
    return response.json()


def exchange(client: TestClient, room_id: str, url: str) -> None:
    token = url.split("#cap=", 1)[1]
    response = client.post("/v1/capability-sessions", json={"roomId": room_id, "token": token})
    assert response.status_code == 200, response.text


def test_legacy_creation_is_rejected_and_authenticated_dashboard_lists_all_rooms(
    container: Container,
) -> None:
    with TestClient(app, base_url=BASE_URL) as client:
        app.state.container = container
        assert client.post("/v1/rooms", json=room_payload()).status_code == 401
        assert client.get("/v1/admin/rooms").status_code == 401
        assert client.post("/v1/admin/rooms", json={}).status_code == 401
        headers = login_admin(client)
        first = create_room(client, headers, "Dashboard one")
        second = create_room(client, headers, "Dashboard two")
        dashboard = client.get("/v1/admin/rooms")
        assert dashboard.status_code == 200
        assert [item["room"]["name"] for item in dashboard.json()["rooms"]] == [
            "Dashboard two",
            "Dashboard one",
        ]
        assert "adminUrl" not in first
        assert "adminUrl" not in second
        links = client.get(f"/v1/admin/rooms/{first['room']['id']}/seat-links")
        assert links.status_code == 200
        assert links.headers["cache-control"] == "no-store"
        assert len(links.json()) == 2


def test_login_requires_origin_and_csrf_protects_mutations(container: Container) -> None:
    with TestClient(app, base_url=BASE_URL) as client:
        app.state.container = container
        payload = {
            "username": "judge-local",
            "password": "local-rolecall-admin-password",
            "recaptchaToken": "test-assessment",
        }
        assert client.post("/v1/auth/login", json=payload).status_code == 403
        headers = login_admin(client)
        assert (
            client.post("/v1/admin/rooms", headers=ORIGIN, json=room_payload()).status_code == 403
        )
        assert (
            client.post("/v1/admin/rooms", headers=headers, json=room_payload()).status_code == 201
        )


def test_local_admin_cors_preflight_does_not_require_a_session(container: Container) -> None:
    with TestClient(app, base_url=BASE_URL) as client:
        app.state.container = container
        response = client.options(
            "/v1/admin/rooms",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-csrf-token",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_failed_capability_exchange_uses_durable_throttle(container: Container) -> None:
    with TestClient(app, base_url=BASE_URL) as client:
        app.state.container = container
        payload = {"roomId": "room_missing", "token": "x" * 43}
        for _ in range(container.settings.capability_failure_rate_per_minute):
            assert client.post("/v1/capability-sessions", json=payload).status_code == 401
        throttled = client.post("/v1/capability-sessions", json=payload)
        assert throttled.status_code == 429


def test_end_to_end_participant_join_flow(container: Container) -> None:
    with TestClient(app, base_url=BASE_URL) as admin:
        app.state.container = container
        headers = login_admin(admin)
        created = create_room(admin, headers)
        room_id = created["room"]["id"]
        participants: list[TestClient] = []
        joins = []
        for index, invitation in enumerate(created["seatUrls"], start=1):
            participant = TestClient(app, base_url=BASE_URL)
            app.state.container = container
            exchange(participant, room_id, invitation["url"])
            joined = participant.post(
                f"/v1/rooms/{room_id}:join",
                json={
                    "name": f"Person {index}",
                    "consentVersion": "v1",
                    "connectionId": f"connection-{index}",
                },
            )
            assert joined.status_code == 200, joined.text
            joins.append(joined.json())
            participants.append(participant)
        assert joins[0]["occurrence"]["status"] == "LOBBY"
        assert joins[1]["occurrence"]["status"] == "RUNNING"
        occurrence_id = joins[1]["occurrence"]["id"]
        assert container.livekit.ensured == [occurrence_id]  # type: ignore[attr-defined]
        assert container.livekit.dispatched == [occurrence_id]  # type: ignore[attr-defined]
        assert admin.get(f"/v1/admin/rooms/{room_id}/history").status_code == 200
        for participant in participants:
            participant.close()


def test_duplicate_seat_is_rejected(container: Container) -> None:
    with TestClient(app, base_url=BASE_URL) as admin:
        app.state.container = container
        created = create_room(admin, login_admin(admin), "Duplicate room")
        room_id = created["room"]["id"]
        participant = TestClient(app, base_url=BASE_URL)
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


def test_admin_delegates_end_meeting_and_can_end_lobby(container: Container) -> None:
    with TestClient(app, base_url=BASE_URL) as admin:
        app.state.container = container
        headers = login_admin(admin)
        created = create_room(admin, headers, "Delegated controls")
        room_id = created["room"]["id"]
        participant = TestClient(app, base_url=BASE_URL)
        exchange(participant, room_id, created["seatUrls"][0]["url"])
        joined = participant.post(
            f"/v1/rooms/{room_id}:join",
            json={
                "name": "One",
                "consentVersion": "v1",
                "connectionId": "control-connection",
            },
        ).json()
        occurrence_id = joined["occurrence"]["id"]
        slot_id = joined["slotId"]
        permission = admin.put(
            f"/v1/admin/rooms/{room_id}/slots/{slot_id}:end-meeting-permission",
            headers=headers,
            json={"allowed": True},
        )
        assert permission.status_code == 200
        ended = participant.post(f"/v1/occurrences/{occurrence_id}:end")
        assert ended.status_code == 200
        assert ended.json()["status"] == "PROCESSING"

        second = create_room(admin, headers, "Admin ends lobby")
        second_participant = TestClient(app, base_url=BASE_URL)
        exchange(second_participant, second["room"]["id"], second["seatUrls"][0]["url"])
        lobby = second_participant.post(
            f"/v1/rooms/{second['room']['id']}:join",
            json={
                "name": "Waiting",
                "consentVersion": "v1",
                "connectionId": "waiting-connection",
            },
        ).json()
        admin_end = admin.post(
            f"/v1/admin/occurrences/{lobby['occurrence']['id']}:end",
            headers=headers,
            json={"reason": "ended_by_admin"},
        )
        assert admin_end.status_code == 200
        assert admin_end.json()["status"] == "PROCESSING"


def test_sleeping_runtime_blocks_participant_without_creating_occurrence(
    container: Container,
) -> None:
    with TestClient(app, base_url=BASE_URL) as admin:
        app.state.container = container
        created = create_room(admin, login_admin(admin), "Sleeping room")
        room_id = created["room"]["id"]
        state = container.runtime.get()
        state.status = RuntimeStatus.SLEEPING
        state.progress = 0
        container.repository.save_runtime_state(state)
        participant = TestClient(app, base_url=BASE_URL)
        exchange(participant, room_id, created["seatUrls"][0]["url"])
        response = participant.post(
            f"/v1/rooms/{room_id}:join",
            json={
                "name": "Blocked",
                "consentVersion": "v1",
                "connectionId": "sleeping-connection",
            },
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "runtime_asleep"
        assert container.repository.get_active_occurrence(room_id) is None
