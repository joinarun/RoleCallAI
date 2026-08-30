from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.domain.enums import RoleType, RuntimeStatus
from app.domain.models import JoinRequest, RoomCreate
from app.domain.repository import InMemoryRepository
from app.security.capabilities import CapabilityService
from app.security.seat_links import SeatLinkCipher
from app.services.meetings import MeetingService
from app.services.rooms import RoomService
from app.services.runtime import RuntimeService


def _services() -> tuple[InMemoryRepository, RoomService, MeetingService, RuntimeService]:
    settings = Settings(
        env="test",
        repository="memory",
        public_base_url="https://rolecall.test",
        cookie_signing_key="runtime-test-key-that-is-at-least-32-bytes",
        runtime_default_status="READY",
        runtime_inactivity_minutes=30,
        runtime_activity_debounce_seconds=60,
    )
    repository = InMemoryRepository()
    capabilities = CapabilityService(repository, settings)
    rooms = RoomService(repository, capabilities, SeatLinkCipher(settings), settings)
    return (
        repository,
        rooms,
        MeetingService(repository, settings),
        RuntimeService(repository, settings),
    )


def test_activity_is_debounced_and_idle_suspend_is_idempotent() -> None:
    repository, _, _, runtime = _services()
    now = datetime.now(UTC)
    initial = runtime.get(now)
    assert (
        runtime.activity(now + timedelta(seconds=30)).last_activity_at == initial.last_activity_at
    )
    touched = runtime.activity(now + timedelta(seconds=61))
    assert touched.last_activity_at == now + timedelta(seconds=61)

    state = runtime.begin_suspend_if_idle(now + timedelta(minutes=31, seconds=61))
    assert state.status == RuntimeStatus.SUSPENDING
    assert len(repository.list_pending_outbox()) == 1
    repeated = runtime.begin_suspend_if_idle(now + timedelta(minutes=32, seconds=61))
    assert repeated.operation_id == state.operation_id
    assert len(repository.list_pending_outbox()) == 1


def test_active_lobby_prevents_suspend_and_admin_wake_records_activity() -> None:
    _, rooms, meetings, runtime = _services()
    now = datetime.now(UTC)
    created = rooms.create(
        RoomCreate(
            name="Runtime Guard Room",
            expected_participants=2,
            duration_minutes=10,
            role=RoleType.SCRUM_MASTER,
            agent_name="Nova",
        )
    )
    slot_id = created.room.slots[0].id
    meetings.join(
        created.room.id,
        slot_id,
        JoinRequest(name="Arun", consent_version="phase1-v1", connection_id="conn-one"),
        now=now,
    )
    runtime.get(now)
    assert runtime.begin_suspend_if_idle(now + timedelta(minutes=31)).status == RuntimeStatus.READY

    state = runtime.get()
    state.status = RuntimeStatus.SLEEPING
    runtime.repository.save_runtime_state(state)
    waking = runtime.wake(now + timedelta(minutes=32))
    assert waking.status == RuntimeStatus.WAKING
    assert waking.last_activity_at == now + timedelta(minutes=32)


def test_activity_during_suspend_cancels_the_idle_lease() -> None:
    _, _, _, runtime = _services()
    now = datetime.now(UTC)
    runtime.get(now)
    suspending = runtime.begin_suspend_if_idle(now + timedelta(minutes=31))
    assert suspending.status == RuntimeStatus.SUSPENDING
    assert suspending.operation_id is not None
    assert runtime.suspension_can_continue(suspending.operation_id)

    runtime.activity(now + timedelta(minutes=31, seconds=1))
    assert not runtime.suspension_can_continue(suspending.operation_id)
    assert runtime.finalize_suspend(suspending.operation_id).status == RuntimeStatus.SUSPENDING


def test_finalize_suspend_is_idempotent_without_new_activity() -> None:
    _, _, _, runtime = _services()
    now = datetime.now(UTC)
    runtime.get(now)
    suspending = runtime.begin_suspend_if_idle(now + timedelta(minutes=31))
    assert suspending.operation_id is not None

    sleeping = runtime.finalize_suspend(suspending.operation_id, now + timedelta(minutes=32))
    assert sleeping.status == RuntimeStatus.SLEEPING
    assert runtime.finalize_suspend(suspending.operation_id).status == RuntimeStatus.SLEEPING
