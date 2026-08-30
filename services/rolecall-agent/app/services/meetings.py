"""Deterministic meeting controller.

The LLM may request state changes through tools, but every mutation is validated
here. This module is the single authority for lifecycle, floor, and timer rules.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.domain.enums import FloorOwnerType, OccurrenceStatus, OutcomeKind
from app.domain.errors import (
    ConflictError,
    InvalidTransitionError,
    NotFoundError,
)
from app.domain.models import (
    Attendance,
    JoinRequest,
    Occurrence,
    OutboxRecord,
    Outcome,
)
from app.domain.repository import Repository
from app.retrieval.documents import DocumentService
from app.services.rooms import new_id

ALLOWED_TRANSITIONS: dict[OccurrenceStatus, set[OccurrenceStatus]] = {
    OccurrenceStatus.LOBBY: {OccurrenceStatus.STARTING, OccurrenceStatus.FAILED},
    OccurrenceStatus.STARTING: {OccurrenceStatus.RUNNING, OccurrenceStatus.FAILED},
    OccurrenceStatus.RUNNING: {
        OccurrenceStatus.ENDING,
        OccurrenceStatus.PROCESSING,
        OccurrenceStatus.FAILED,
    },
    OccurrenceStatus.ENDING: {OccurrenceStatus.PROCESSING, OccurrenceStatus.FAILED},
    OccurrenceStatus.PROCESSING: {OccurrenceStatus.COMPLETED, OccurrenceStatus.FAILED},
    OccurrenceStatus.COMPLETED: set(),
    OccurrenceStatus.FAILED: set(),
}


class MeetingService:
    def __init__(
        self,
        repository: Repository,
        settings: Settings,
        documents: DocumentService | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.documents = documents

    def get_or_create_occurrence(self, room_id: str, now: datetime | None = None) -> Occurrence:
        timestamp = now or datetime.now(UTC)
        active = self.repository.get_active_occurrence(room_id)
        if active:
            return active
        room = self.repository.get_room(room_id)
        previous = next(
            (
                item.recap
                for item in self.repository.list_occurrences(room_id)
                if item.status == OccurrenceStatus.COMPLETED and item.recap is not None
            ),
            None,
        )
        ready_document_version_ids, omitted_document_count = (
            self.documents.ready_version_ids(room_id) if self.documents else ([], 0)
        )
        candidate = Occurrence(
            id=new_id("occ"),
            room_id=room_id,
            number=room.occurrence_counter + 1,
            created_at=timestamp,
            lobby_deadline_at=timestamp
            + timedelta(seconds=self.settings.lobby_early_start_seconds),
            previous_recap=previous,
            ready_document_version_ids=ready_document_version_ids,
            omitted_document_count=omitted_document_count,
            end_meeting_slot_ids=[slot.id for slot in room.slots if slot.can_end_meeting],
        )
        return self.repository.create_occurrence_if_absent(candidate)

    def join(
        self,
        room_id: str,
        slot_id: str,
        request: JoinRequest,
        now: datetime | None = None,
    ) -> Occurrence:
        timestamp = now or datetime.now(UTC)
        room = self.repository.get_room(room_id)
        slot = next((item for item in room.slots if item.id == slot_id), None)
        if slot is None:
            raise NotFoundError("Seat not found")
        occurrence = self.get_or_create_occurrence(room_id, timestamp)

        def join_occurrence(current: Occurrence) -> Occurrence:
            existing = current.attendance.get(slot_id)
            if existing and existing.connected and existing.connection_id != request.connection_id:
                raise ConflictError("This seat is already connected")
            current.attendance[slot_id] = Attendance(
                slot_id=slot_id,
                display_name=request.name,
                consent_version=request.consent_version,
                joined_at=existing.joined_at if existing else timestamp,
                connected=True,
                connection_id=request.connection_id,
            )
            if current.status in {OccurrenceStatus.RUNNING, OccurrenceStatus.ENDING}:
                if slot_id not in current.turn_order:
                    current.turn_order.append(slot_id)
                current.absent_slot_ids = [
                    item for item in current.absent_slot_ids if item != slot_id
                ]
            current.sequence += 1
            return current

        occurrence = self.repository.mutate_occurrence(occurrence.id, join_occurrence)
        self.repository.update_seat_display_name(room_id, slot_id, request.name, timestamp)
        if occurrence.status == OccurrenceStatus.LOBBY and self._all_present(room, occurrence):
            occurrence = self.start(occurrence.id, slot_id, timestamp, force=False)
        return occurrence

    def reconnect(
        self,
        room_id: str,
        slot_id: str,
        connection_id: str,
    ) -> Occurrence:
        occurrence = self.repository.get_active_occurrence(room_id)
        if occurrence is None:
            raise NotFoundError("No active occurrence")
        if occurrence.status not in {
            OccurrenceStatus.LOBBY,
            OccurrenceStatus.STARTING,
            OccurrenceStatus.RUNNING,
            OccurrenceStatus.ENDING,
        }:
            raise ConflictError("This occurrence no longer accepts reconnects")

        def reconnect_participant(current: Occurrence) -> Occurrence:
            attendance = current.attendance.get(slot_id)
            if attendance is None or attendance.connection_id != connection_id:
                raise ConflictError("Reconnect identity does not match this seat")
            if attendance.connected:
                return current
            attendance.connected = True
            attendance.disconnected_at = None
            attendance.left_at = None
            if current.status in {OccurrenceStatus.RUNNING, OccurrenceStatus.ENDING}:
                if slot_id not in current.turn_order:
                    current.turn_order.append(slot_id)
                current.absent_slot_ids = [
                    item for item in current.absent_slot_ids if item != slot_id
                ]
            current.sequence += 1
            return current

        return self.repository.mutate_occurrence(occurrence.id, reconnect_participant)

    def start(
        self,
        occurrence_id: str,
        requester_slot_id: str,
        now: datetime | None = None,
        force: bool = False,
    ) -> Occurrence:
        timestamp = now or datetime.now(UTC)
        occurrence = self.repository.get_occurrence(occurrence_id)
        room = self.repository.get_room(occurrence.room_id)

        def begin(current: Occurrence) -> Occurrence:
            attendance = current.attendance.get(requester_slot_id)
            if not attendance or not attendance.connected:
                raise ConflictError("Only a present participant can start the meeting")
            if current.status != OccurrenceStatus.LOBBY:
                return current
            if (
                not force
                and not self._all_present(room, current)
                and timestamp < current.lobby_deadline_at
            ):
                raise ConflictError(
                    "Early start becomes available after the two-minute lobby grace"
                )
            present_ids = {
                slot_id for slot_id, item in current.attendance.items() if item.connected
            }
            current.absent_slot_ids = [slot.id for slot in room.slots if slot.id not in present_ids]
            current.turn_order = [slot.id for slot in room.slots if slot.id in present_ids]
            current.status = OccurrenceStatus.STARTING
            current.started_at = timestamp
            current.current_floor_type = FloorOwnerType.AGENT
            current.current_floor_slot_id = None
            current.next_floor_slot_id = None
            current.current_prompt = None
            current.floor_epoch += 1
            current.agent_last_seen_at = timestamp
            current.sequence += 1
            return current

        occurrence = self.repository.mutate_occurrence(occurrence_id, begin)
        if occurrence.status != OccurrenceStatus.STARTING:
            return occurrence

        def run(current: Occurrence) -> Occurrence:
            if current.status == OccurrenceStatus.STARTING:
                current.status = OccurrenceStatus.RUNNING
                current.sequence += 1
            return current

        return self.repository.mutate_occurrence(occurrence_id, run)

    def set_phase(self, occurrence_id: str, phase: OccurrenceStatus) -> Occurrence:
        now = datetime.now(UTC)

        def transition(current: Occurrence) -> Occurrence:
            if current.status == phase:
                return current
            if phase not in ALLOWED_TRANSITIONS[current.status]:
                raise InvalidTransitionError(f"Cannot transition {current.status} to {phase}")
            current.status = phase
            if phase == OccurrenceStatus.ENDING:
                current.ending_at = now
            if phase in {OccurrenceStatus.PROCESSING, OccurrenceStatus.FAILED}:
                current.ended_at = now
                current.current_floor_type = FloorOwnerType.NONE
                current.current_floor_slot_id = None
                current.next_floor_slot_id = None
                current.current_prompt = None
                current.floor_epoch += 1
            if phase == OccurrenceStatus.FAILED:
                current.expires_at = now + timedelta(days=self.settings.retention_days)
            current.sequence += 1
            return current

        return self.repository.mutate_occurrence(occurrence_id, transition)

    def give_floor(self, occurrence_id: str, slot_id: str, prompt: str) -> Occurrence:
        cleaned_prompt = prompt.strip()[:1000]

        def assign(current: Occurrence) -> Occurrence:
            if current.status not in {OccurrenceStatus.RUNNING, OccurrenceStatus.ENDING}:
                raise InvalidTransitionError("The floor can only change during a running meeting")
            attendance = current.attendance.get(slot_id)
            if attendance is None or not attendance.connected:
                raise ConflictError("Cannot give the floor to an absent participant")
            if (
                current.current_floor_type == FloorOwnerType.SEAT
                and current.current_floor_slot_id != slot_id
            ):
                raise ConflictError("Use advance_floor while a participant owns the floor")
            if current.next_floor_slot_id and current.next_floor_slot_id != slot_id:
                raise ConflictError("The controller selected a different next participant")
            if (
                current.current_floor_type == FloorOwnerType.SEAT
                and current.current_floor_slot_id == slot_id
                and current.current_prompt == cleaned_prompt
            ):
                return current
            floor_changed = (
                current.current_floor_type != FloorOwnerType.SEAT
                or current.current_floor_slot_id != slot_id
            )
            current.current_floor_type = FloorOwnerType.SEAT
            current.current_floor_slot_id = slot_id
            current.next_floor_slot_id = None
            current.current_prompt = cleaned_prompt
            if floor_changed:
                current.floor_epoch += 1
            current.sequence += 1
            return current

        return self.repository.mutate_occurrence(occurrence_id, assign)

    def give_agent_floor(self, occurrence_id: str) -> Occurrence:
        def assign(current: Occurrence) -> Occurrence:
            if current.status not in {OccurrenceStatus.RUNNING, OccurrenceStatus.ENDING}:
                raise InvalidTransitionError(
                    "The agent cannot take the floor outside a running meeting"
                )
            if (
                current.current_floor_type == FloorOwnerType.AGENT
                and current.current_floor_slot_id is None
            ):
                return current
            current.current_floor_type = FloorOwnerType.AGENT
            current.current_floor_slot_id = None
            current.next_floor_slot_id = None
            current.current_prompt = None
            current.floor_epoch += 1
            current.sequence += 1
            return current

        return self.repository.mutate_occurrence(occurrence_id, assign)

    def advance_floor(self, occurrence_id: str) -> Occurrence:
        def advance(current: Occurrence) -> Occurrence:
            if current.status not in {OccurrenceStatus.RUNNING, OccurrenceStatus.ENDING}:
                raise InvalidTransitionError("The floor can only advance during a running meeting")
            if (
                current.current_floor_type == FloorOwnerType.AGENT
                and current.next_floor_slot_id is not None
            ):
                return current
            current_slot = current.current_floor_slot_id
            start_index = (
                current.turn_order.index(current_slot) + 1
                if current_slot in current.turn_order
                else 0
            )
            ordered = current.turn_order[start_index:] + current.turn_order[:start_index]
            hand_raised = [item for item in current.hand_raise_queue if item in ordered]
            candidates = hand_raised + [item for item in ordered if item not in hand_raised]
            next_slot = next(
                (
                    slot_id
                    for slot_id in candidates
                    if slot_id != current_slot
                    and current.attendance.get(slot_id)
                    and current.attendance[slot_id].connected
                ),
                None,
            )
            if next_slot is None and current_slot:
                current_attendance = current.attendance.get(current_slot)
                if current_attendance and current_attendance.connected:
                    next_slot = current_slot
            if next_slot is not None:
                current.hand_raise_queue = [
                    item for item in current.hand_raise_queue if item != next_slot
                ]
            if (
                current.current_floor_type == FloorOwnerType.AGENT
                and current.current_floor_slot_id is None
                and current.next_floor_slot_id == next_slot
            ):
                return current
            # A human-to-human transition always passes through an agent-owned
            # bridge. This prevents the next microphone from opening while the
            # agent is still acknowledging or summarizing the previous update.
            current.current_floor_type = FloorOwnerType.AGENT
            current.current_floor_slot_id = None
            current.next_floor_slot_id = next_slot
            current.current_prompt = None
            current.floor_epoch += 1
            current.sequence += 1
            return current

        return self.repository.mutate_occurrence(occurrence_id, advance)

    def raise_hand(self, occurrence_id: str, slot_id: str) -> Occurrence:
        def enqueue(current: Occurrence) -> Occurrence:
            if current.status not in {OccurrenceStatus.RUNNING, OccurrenceStatus.ENDING}:
                raise InvalidTransitionError("Hands can only be raised during a running meeting")
            attendance = current.attendance.get(slot_id)
            if not attendance or not attendance.connected:
                raise ConflictError("Only a connected participant can raise a hand")
            if slot_id not in current.hand_raise_queue:
                current.hand_raise_queue.append(slot_id)
                current.sequence += 1
            return current

        return self.repository.mutate_occurrence(occurrence_id, enqueue)

    def disconnect(
        self, occurrence_id: str, slot_id: str, now: datetime | None = None
    ) -> Occurrence:
        timestamp = now or datetime.now(UTC)

        def mark_disconnected(current: Occurrence) -> Occurrence:
            attendance = current.attendance.get(slot_id)
            if attendance and attendance.connected:
                attendance.connected = False
                attendance.disconnected_at = timestamp
                current.sequence += 1
            return current

        return self.repository.mutate_occurrence(occurrence_id, mark_disconnected)

    def leave(
        self,
        occurrence_id: str,
        slot_id: str,
        connection_id: str,
        now: datetime | None = None,
    ) -> Occurrence:
        """Mark an intentional departure and skip its floor without reconnect hold."""
        timestamp = now or datetime.now(UTC)

        def mark_left(current: Occurrence) -> Occurrence:
            if current.status not in {
                OccurrenceStatus.LOBBY,
                OccurrenceStatus.STARTING,
                OccurrenceStatus.RUNNING,
                OccurrenceStatus.ENDING,
            }:
                raise ConflictError("This meeting no longer accepts participant departures")
            attendance = current.attendance.get(slot_id)
            if attendance is None or attendance.connection_id != connection_id:
                raise ConflictError("Leave identity does not match this seat connection")
            if not attendance.connected and attendance.left_at is not None:
                return current
            attendance.connected = False
            attendance.disconnected_at = timestamp
            attendance.left_at = timestamp
            current.hand_raise_queue = [
                item for item in current.hand_raise_queue if item != slot_id
            ]
            if current.current_floor_slot_id == slot_id:
                start_index = (
                    current.turn_order.index(slot_id) + 1 if slot_id in current.turn_order else 0
                )
                ordered = current.turn_order[start_index:] + current.turn_order[:start_index]
                current.next_floor_slot_id = next(
                    (
                        candidate
                        for candidate in ordered
                        if candidate != slot_id
                        and current.attendance.get(candidate)
                        and current.attendance[candidate].connected
                    ),
                    None,
                )
                current.current_floor_type = FloorOwnerType.AGENT
                current.current_floor_slot_id = None
                current.current_prompt = None
                current.floor_epoch += 1
            current.sequence += 1
            return current

        occurrence = self.repository.mutate_occurrence(occurrence_id, mark_left)
        if occurrence.status.active and not any(
            item.connected for item in occurrence.attendance.values()
        ):
            return self.finish(occurrence_id, "all_participants_left")
        return occurrence

    def record_outcome(
        self,
        occurrence_id: str,
        kind: OutcomeKind,
        text: str,
        owner_slot_id: str | None,
        idempotency_key: str,
    ) -> Outcome:
        cleaned = " ".join(text.split())[:2000]
        if not cleaned:
            raise ValueError("Outcome text cannot be blank")
        result: Outcome | None = None

        def persist(current: Occurrence) -> Occurrence:
            nonlocal result
            existing = next(
                (item for item in current.outcomes if item.idempotency_key == idempotency_key),
                None,
            )
            if existing:
                result = existing
                return current
            if owner_slot_id and owner_slot_id not in current.attendance:
                raise ConflictError("Outcome owner must be a participant in this occurrence")
            result = Outcome(
                id=new_id("out"),
                kind=kind,
                text=cleaned,
                owner_slot_id=owner_slot_id,
                idempotency_key=idempotency_key,
            )
            current.outcomes.append(result)
            return current

        self.repository.mutate_occurrence(occurrence_id, persist)
        if result is None:
            raise RuntimeError("Outcome mutation completed without a result")
        return result

    def remaining_seconds(self, occurrence_id: str, now: datetime | None = None) -> int:
        occurrence = self.repository.get_occurrence(occurrence_id)
        if occurrence.started_at is None:
            return self.repository.get_room(occurrence.room_id).duration_minutes * 60
        room = self.repository.get_room(occurrence.room_id)
        end = occurrence.started_at + timedelta(minutes=room.duration_minutes)
        return max(0, int((end - (now or datetime.now(UTC))).total_seconds()))

    def tick(self, occurrence_id: str, now: datetime | None = None) -> Occurrence:
        timestamp = now or datetime.now(UTC)
        occurrence = self.repository.get_occurrence(occurrence_id)
        if occurrence.status not in {OccurrenceStatus.RUNNING, OccurrenceStatus.ENDING}:
            return occurrence
        if occurrence.started_at is None:
            raise InvalidTransitionError("A running occurrence must have a start time")
        started_at = occurrence.started_at

        if occurrence.current_floor_slot_id:
            attendance = occurrence.attendance.get(occurrence.current_floor_slot_id)
            if (
                attendance
                and not attendance.connected
                and attendance.disconnected_at
                and timestamp
                >= attendance.disconnected_at
                + timedelta(seconds=self.settings.disconnect_hold_seconds)
            ):
                occurrence = self.advance_floor(occurrence_id)

        remaining = self.remaining_seconds(occurrence_id, timestamp)
        if (
            remaining <= self.settings.wrap_up_seconds
            and occurrence.status == OccurrenceStatus.RUNNING
        ):
            occurrence = self.set_phase(occurrence_id, OccurrenceStatus.ENDING)

        room = self.repository.get_room(occurrence.room_id)
        hard_end = started_at + timedelta(
            minutes=room.duration_minutes, seconds=self.settings.closing_grace_seconds
        )
        if timestamp >= hard_end:
            return self.finish(occurrence.id, "duration_elapsed")
        return occurrence

    def mark_agent_seen(self, occurrence_id: str, now: datetime | None = None) -> Occurrence:
        timestamp = now or datetime.now(UTC)

        def mark_seen(current: Occurrence) -> Occurrence:
            current.agent_last_seen_at = timestamp
            return current

        return self.repository.mutate_occurrence(occurrence_id, mark_seen)

    def finish(self, occurrence_id: str, reason: str) -> Occurrence:
        timestamp = datetime.now(UTC)

        def close(current: Occurrence) -> Occurrence:
            if current.status in {OccurrenceStatus.COMPLETED, OccurrenceStatus.FAILED}:
                return current
            if current.status != OccurrenceStatus.PROCESSING:
                current.status = OccurrenceStatus.PROCESSING
                current.ended_at = timestamp
                current.current_floor_type = FloorOwnerType.NONE
                current.current_floor_slot_id = None
                current.next_floor_slot_id = None
                current.current_prompt = None
                current.floor_epoch += 1
                current.failure_reason = reason if reason.startswith("agent_") else None
                current.sequence += 1
            return current

        occurrence = self.repository.mutate_occurrence(occurrence_id, close)
        if occurrence.status in {OccurrenceStatus.COMPLETED, OccurrenceStatus.FAILED}:
            return occurrence
        self.repository.ensure_outbox(
            OutboxRecord(
                id=f"postprocess:{occurrence.id}",
                topic=self.settings.postprocess_topic,
                aggregate_id=occurrence.id,
                payload={"occurrenceId": occurrence.id, "reason": reason},
            )
        )
        return occurrence

    @staticmethod
    def outcome_idempotency_key(
        occurrence_id: str, kind: OutcomeKind, text: str, owner_slot_id: str | None
    ) -> str:
        source = f"{occurrence_id}\0{kind.value}\0{text.strip()}\0{owner_slot_id or ''}"
        return hashlib.sha256(source.encode()).hexdigest()

    @staticmethod
    def _all_present(room, occurrence: Occurrence) -> bool:  # type: ignore[no-untyped-def]
        return all(
            slot.id in occurrence.attendance and occurrence.attendance[slot.id].connected
            for slot in room.slots
        )
