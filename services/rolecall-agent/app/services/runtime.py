"""Durable voice-runtime state machine and debounced activity lease."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.domain.enums import RuntimeStatus
from app.domain.errors import ConflictError, RuntimeAsleepError
from app.domain.models import OutboxRecord, RuntimeState
from app.domain.repository import Repository


class RuntimeService:
    def __init__(self, repository: Repository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def get(self, now: datetime | None = None) -> RuntimeState:
        existing = self.repository.get_runtime_state()
        if existing is not None:
            return existing
        timestamp = now or datetime.now(UTC)
        state = RuntimeState(
            status=RuntimeStatus(self.settings.runtime_default_status),
            progress=100 if self.settings.runtime_default_status == "READY" else 0,
            message=(
                "Voice services are ready"
                if self.settings.runtime_default_status == "READY"
                else "Voice services are sleeping"
            ),
            last_activity_at=timestamp,
            last_activity_write_at=timestamp,
            ready_at=timestamp if self.settings.runtime_default_status == "READY" else None,
            sleeping_at=(timestamp if self.settings.runtime_default_status == "SLEEPING" else None),
        )
        return self.repository.save_runtime_state(state)

    def require_ready(self) -> RuntimeState:
        state = self.get()
        if state.status != RuntimeStatus.READY:
            raise RuntimeAsleepError(
                "Voice services are asleep. Ask the administrator to wake them before joining"
            )
        return state

    def activity(self, now: datetime | None = None) -> RuntimeState:
        timestamp = now or datetime.now(UTC)
        debounce = timedelta(seconds=self.settings.runtime_activity_debounce_seconds)
        initial = self.get(timestamp)

        def mutate(current: RuntimeState | None) -> RuntimeState:
            state = current or initial
            if timestamp - state.last_activity_write_at < debounce:
                return state
            state.last_activity_at = timestamp
            state.last_activity_write_at = timestamp
            state.updated_at = timestamp
            return state

        return self.repository.mutate_runtime_state(mutate)

    def wake(self, now: datetime | None = None) -> RuntimeState:
        timestamp = now or datetime.now(UTC)
        initial = self.get(timestamp)

        def mutate(current: RuntimeState | None) -> RuntimeState:
            state = current or initial
            if state.status == RuntimeStatus.READY:
                state.last_activity_at = timestamp
                state.updated_at = timestamp
                return state
            if state.status in {RuntimeStatus.WAKING, RuntimeStatus.SUSPENDING}:
                return state
            state.status = RuntimeStatus.WAKING
            state.progress = 1
            state.message = "Wake requested; restoring worker nodes"
            state.generation += 1
            state.operation_id = f"wake_{secrets.token_urlsafe(12)}"
            state.transition_started_at = timestamp
            state.error_code = None
            state.last_activity_at = timestamp
            state.last_activity_write_at = timestamp
            state.updated_at = timestamp
            return state

        state = self.repository.mutate_runtime_state(mutate)
        if state.status == RuntimeStatus.WAKING and state.operation_id:
            self.repository.ensure_outbox(
                OutboxRecord(
                    id=f"runtime:{state.operation_id}",
                    topic=self.settings.runtime_control_topic,
                    aggregate_id="voice",
                    payload={
                        "action": "wake",
                        "operationId": state.operation_id,
                        "generation": state.generation,
                    },
                )
            )
        return state

    def begin_suspend_if_idle(self, now: datetime | None = None) -> RuntimeState:
        timestamp = now or datetime.now(UTC)
        threshold = timedelta(minutes=self.settings.runtime_inactivity_minutes)
        initial = self.get(timestamp)

        def mutate(current: RuntimeState | None) -> RuntimeState:
            state = current or initial
            if state.status != RuntimeStatus.READY:
                return state
            if timestamp - state.last_activity_at < threshold:
                return state
            for room in self.repository.list_rooms(self.settings.admin_owner_id, limit=500):
                if self.repository.get_active_occurrence(room.id) is not None:
                    return state
            state.status = RuntimeStatus.SUSPENDING
            state.progress = 1
            state.message = "Idle threshold reached; suspending voice services"
            state.generation += 1
            state.operation_id = f"suspend_{secrets.token_urlsafe(12)}"
            state.transition_started_at = timestamp
            state.updated_at = timestamp
            return state

        state = self.repository.mutate_runtime_state(mutate)
        if state.status == RuntimeStatus.SUSPENDING and state.operation_id:
            self.repository.ensure_outbox(
                OutboxRecord(
                    id=f"runtime:{state.operation_id}",
                    topic=self.settings.runtime_control_topic,
                    aggregate_id="voice",
                    payload={
                        "action": "suspend",
                        "operationId": state.operation_id,
                        "generation": state.generation,
                    },
                )
            )
        return state

    def suspension_can_continue(self, operation_id: str) -> bool:
        """Return whether a suspend job still owns an idle, meeting-free lease."""

        state = self.get()
        if (
            state.status != RuntimeStatus.SUSPENDING
            or state.operation_id != operation_id
            or state.transition_started_at is None
            or state.last_activity_at > state.transition_started_at
        ):
            return False
        return not any(
            self.repository.get_active_occurrence(room.id) is not None
            for room in self.repository.list_rooms(self.settings.admin_owner_id, limit=500)
        )

    def finalize_suspend(self, operation_id: str, now: datetime | None = None) -> RuntimeState:
        """Atomically enter SLEEPING unless protected activity arrived mid-transition."""

        timestamp = now or datetime.now(UTC)

        def mutate(current: RuntimeState | None) -> RuntimeState:
            if current is None or current.operation_id != operation_id:
                raise ConflictError("Runtime operation is stale")
            if current.status != RuntimeStatus.SUSPENDING:
                return current
            if (
                current.transition_started_at is None
                or current.last_activity_at > current.transition_started_at
            ):
                return current
            current.status = RuntimeStatus.SLEEPING
            current.progress = 100
            current.message = "Voice services are sleeping; persistent data remains available"
            current.sleeping_at = timestamp
            current.transition_started_at = None
            current.updated_at = timestamp
            return current

        return self.repository.mutate_runtime_state(mutate)

    def update_transition(
        self,
        operation_id: str,
        status: RuntimeStatus,
        progress: int,
        message: str,
        error_code: str | None = None,
        now: datetime | None = None,
    ) -> RuntimeState:
        timestamp = now or datetime.now(UTC)

        def mutate(current: RuntimeState | None) -> RuntimeState:
            if current is None or current.operation_id != operation_id:
                raise ConflictError("Runtime operation is stale")
            current.status = status
            current.progress = progress
            current.message = message
            current.error_code = error_code
            current.updated_at = timestamp
            if status == RuntimeStatus.READY:
                current.ready_at = timestamp
                current.transition_started_at = None
            elif status == RuntimeStatus.SLEEPING:
                current.sleeping_at = timestamp
                current.transition_started_at = None
            return current

        return self.repository.mutate_runtime_state(mutate)
