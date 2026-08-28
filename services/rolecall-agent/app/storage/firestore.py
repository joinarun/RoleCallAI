"""Named-database Firestore repository.

All collection paths are rooted in the explicitly configured named database.
The adapter never creates a client for ``(default)``.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from google.api_core import exceptions as google_exceptions
from google.cloud import firestore
from google.cloud.firestore_v1 import transactional
from pydantic import BaseModel

from app.domain.errors import ConflictError, NotFoundError
from app.domain.models import (
    CapabilityRecord,
    CapabilitySession,
    Occurrence,
    OutboxRecord,
    Room,
    TranscriptSegment,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
ResultT = TypeVar("ResultT")


def _data(model: BaseModel) -> dict[str, Any]:
    # API models serialize as camelCase, but Firestore queries, indexes, TTL
    # fields, and atomic updates use the internal snake_case schema.
    return model.model_dump(mode="python", by_alias=False)


def _model(model_type: type[ModelT], snapshot: Any) -> ModelT:
    if not snapshot.exists:
        raise NotFoundError("Record not found")
    return model_type.model_validate(snapshot.to_dict())


def _was_aborted(error: BaseException) -> bool:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        if isinstance(current, google_exceptions.Aborted):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def _run_contentious_transaction(
    client: firestore.Client,
    operation: Callable[[Any], ResultT],
    *,
    attempts: int = 3,
) -> ResultT:
    """Retry a fresh transaction after the SDK exhausts an aborted transaction.

    The Firestore SDK retries each transaction internally. Under a simultaneous
    first-arrival burst, however, its retry transaction can keep the same queue
    position and exhaust all attempts. Starting a fresh transaction after a
    short backoff is safe for the idempotent occurrence mutations below.
    """

    for attempt in range(attempts):
        try:
            return operation(client.transaction())
        except (google_exceptions.Aborted, ValueError) as error:
            if not _was_aborted(error) or attempt == attempts - 1:
                raise
            time.sleep(0.025 * (2**attempt))
    raise RuntimeError("unreachable transaction retry state")


class FirestoreRepository:
    """Production repository with transactional room and occurrence invariants."""

    def __init__(self, project_id: str, database: str) -> None:
        if database == "(default)":
            raise ValueError("RoleCallAI refuses to use the default Firestore database")
        self.client = firestore.Client(project=project_id, database=database)

    @property
    def rooms(self):  # type: ignore[no-untyped-def]
        return self.client.collection("rooms")

    def create_room(self, room: Room) -> Room:
        room_ref = self.rooms.document(room.id)
        name_id = hashlib.sha256(room.normalized_name.encode()).hexdigest()
        name_ref = self.client.collection("room_name_keys").document(name_id)
        transaction = self.client.transaction()

        @transactional
        def create(txn):  # type: ignore[no-untyped-def]
            if name_ref.get(transaction=txn).exists:
                raise ConflictError("A room with this name already exists")
            txn.create(name_ref, {"room_id": room.id, "normalized_name": room.normalized_name})
            txn.create(room_ref, _data(room))
            txn.create(
                self.client.collection("capabilities").document(room.admin_capability_digest),
                _data(
                    CapabilityRecord(
                        room_id=room.id,
                        kind="ADMIN",
                        digest=room.admin_capability_digest,
                        version=room.admin_capability_version,
                    )
                ),
            )
            for slot in room.slots:
                txn.create(
                    self.client.collection("capabilities").document(slot.capability_digest),
                    _data(
                        CapabilityRecord(
                            room_id=room.id,
                            kind="SEAT",
                            digest=slot.capability_digest,
                            version=slot.capability_version,
                            slot_id=slot.id,
                        )
                    ),
                )

        create(transaction)
        return room

    def get_room(self, room_id: str) -> Room:
        return _model(Room, self.rooms.document(room_id).get())

    def save_room(self, room: Room) -> Room:
        room_ref = self.rooms.document(room.id)
        transaction = self.client.transaction()

        @transactional
        def save(txn):  # type: ignore[no-untyped-def]
            current_snapshot = room_ref.get(transaction=txn)
            if not current_snapshot.exists:
                raise NotFoundError("Room not found")
            current = Room.model_validate(current_snapshot.to_dict())
            if current.active_occurrence_id:
                raise ConflictError("Room settings can only change while the room is idle")
            updated = room.model_copy(deep=True)
            updated.occurrence_counter = max(updated.occurrence_counter, current.occurrence_counter)
            if current.active_occurrence_id:
                updated.active_occurrence_id = current.active_occurrence_id

            old_name_id = hashlib.sha256(current.normalized_name.encode()).hexdigest()
            new_name_id = hashlib.sha256(updated.normalized_name.encode()).hexdigest()
            if old_name_id != new_name_id:
                new_ref = self.client.collection("room_name_keys").document(new_name_id)
                if new_ref.get(transaction=txn).exists:
                    raise ConflictError("A room with this name already exists")
                txn.create(new_ref, {"room_id": room.id, "normalized_name": room.normalized_name})
                txn.delete(self.client.collection("room_name_keys").document(old_name_id))
            txn.set(room_ref, _data(updated))

            old_capabilities = {
                current.admin_capability_digest,
                *(slot.capability_digest for slot in current.slots),
            }
            new_records = [
                CapabilityRecord(
                    room_id=room.id,
                    kind="ADMIN",
                    digest=room.admin_capability_digest,
                    version=room.admin_capability_version,
                ),
                *[
                    CapabilityRecord(
                        room_id=room.id,
                        kind="SEAT",
                        digest=slot.capability_digest,
                        version=slot.capability_version,
                        slot_id=slot.id,
                    )
                    for slot in room.slots
                ],
            ]
            new_capabilities = {item.digest for item in new_records}
            for digest in old_capabilities - new_capabilities:
                txn.delete(self.client.collection("capabilities").document(digest))
            for record in new_records:
                txn.set(
                    self.client.collection("capabilities").document(record.digest), _data(record)
                )
            return updated

        return save(transaction)

    def update_seat_display_name(
        self, room_id: str, slot_id: str, display_name: str, updated_at: datetime
    ) -> Room:
        room_ref = self.rooms.document(room_id)

        @transactional
        def update(txn):  # type: ignore[no-untyped-def]
            snapshot = room_ref.get(transaction=txn)
            if not snapshot.exists:
                raise NotFoundError("Room not found")
            room = Room.model_validate(snapshot.to_dict())
            slot = next((item for item in room.slots if item.id == slot_id), None)
            if slot is None:
                raise NotFoundError("Seat not found")
            slot.last_display_name = display_name
            room.updated_at = updated_at
            txn.set(room_ref, _data(room))
            return room

        return _run_contentious_transaction(self.client, update)

    def set_seat_end_meeting_permission(
        self, room_id: str, slot_id: str, allowed: bool, updated_at: datetime
    ) -> Room:
        room_ref = self.rooms.document(room_id)

        @transactional
        def update(txn):  # type: ignore[no-untyped-def]
            snapshot = room_ref.get(transaction=txn)
            if not snapshot.exists:
                raise NotFoundError("Room not found")
            room = Room.model_validate(snapshot.to_dict())
            slot = next((item for item in room.slots if item.id == slot_id), None)
            if slot is None:
                raise NotFoundError("Seat not found")
            slot.can_end_meeting = allowed
            room.updated_at = updated_at
            txn.set(room_ref, _data(room))
            return room

        return _run_contentious_transaction(self.client, update)

    def delete_room(self, room_id: str) -> None:
        room = self.get_room(room_id)
        batch = self.client.batch()
        batch.delete(self.rooms.document(room_id))
        batch.delete(
            self.client.collection("room_name_keys").document(
                hashlib.sha256(room.normalized_name.encode()).hexdigest()
            )
        )
        batch.delete(self.client.collection("capabilities").document(room.admin_capability_digest))
        for slot in room.slots:
            batch.delete(self.client.collection("capabilities").document(slot.capability_digest))
        batch.commit()

    def find_capability(self, digest: str) -> CapabilityRecord | None:
        snapshot = self.client.collection("capabilities").document(digest).get()
        return CapabilityRecord.model_validate(snapshot.to_dict()) if snapshot.exists else None

    def save_capability_session(self, session: CapabilitySession) -> None:
        self.client.collection("capability_sessions").document(session.session_digest).set(
            _data(session)
        )

    def get_capability_session(self, digest: str) -> CapabilitySession | None:
        snapshot = self.client.collection("capability_sessions").document(digest).get()
        return CapabilitySession.model_validate(snapshot.to_dict()) if snapshot.exists else None

    def revoke_capability_sessions(
        self, room_id: str, slot_id: str | None, before_version: int
    ) -> int:
        query = self.client.collection("capability_sessions").where(
            filter=firestore.FieldFilter("claims.room_id", "==", room_id)
        )
        count = 0
        batch = self.client.batch()
        for snapshot in query.stream():
            session = CapabilitySession.model_validate(snapshot.to_dict())
            if (
                session.claims.slot_id == slot_id
                and session.claims.capability_version < before_version
                and session.revoked_at is None
            ):
                batch.update(snapshot.reference, {"revoked_at": datetime.now(UTC)})
                count += 1
        if count:
            batch.commit()
        return count

    def create_occurrence_if_absent(self, occurrence: Occurrence) -> Occurrence:
        room_ref = self.rooms.document(occurrence.room_id)
        occurrence_ref = self.client.collection("occurrences").document(occurrence.id)

        for attempt in range(5):
            room_snapshot = room_ref.get()
            if not room_snapshot.exists:
                raise NotFoundError("Room not found")
            room_data = room_snapshot.to_dict()
            active_id = room_data.get("active_occurrence_id")
            if active_id:
                active_snapshot = self.client.collection("occurrences").document(active_id).get()
                if active_snapshot.exists:
                    active = Occurrence.model_validate(active_snapshot.to_dict())
                    if active.status.active:
                        return active
            created = occurrence.model_copy(deep=True)
            created.number = int(room_data.get("occurrence_counter", 0)) + 1
            batch = self.client.batch()
            batch.create(occurrence_ref, _data(created))
            batch.update(
                room_ref,
                {
                    "active_occurrence_id": created.id,
                    "occurrence_counter": created.number,
                },
                option=firestore.LastUpdateOption(room_snapshot.update_time),
            )
            try:
                batch.commit()
                return created
            except (
                google_exceptions.Aborted,
                google_exceptions.AlreadyExists,
                google_exceptions.FailedPrecondition,
            ):
                if attempt == 4:
                    raise
                time.sleep(0.025 * (2**attempt))
        raise RuntimeError("unreachable occurrence creation retry state")

    def get_occurrence(self, occurrence_id: str) -> Occurrence:
        return _model(
            Occurrence, self.client.collection("occurrences").document(occurrence_id).get()
        )

    def save_occurrence(self, occurrence: Occurrence) -> Occurrence:
        occurrence_ref = self.client.collection("occurrences").document(occurrence.id)
        room_ref = self.rooms.document(occurrence.room_id)

        @transactional
        def save(txn):  # type: ignore[no-untyped-def]
            room_snapshot = room_ref.get(transaction=txn)
            if not room_snapshot.exists:
                raise NotFoundError("Room not found")
            txn.set(occurrence_ref, _data(occurrence))
            if occurrence.status.active:
                txn.update(room_ref, {"active_occurrence_id": occurrence.id})
            else:
                if room_snapshot.to_dict().get("active_occurrence_id") == occurrence.id:
                    txn.update(room_ref, {"active_occurrence_id": firestore.DELETE_FIELD})

        _run_contentious_transaction(self.client, save)
        return occurrence

    def mutate_occurrence(
        self, occurrence_id: str, mutation: Callable[[Occurrence], Occurrence]
    ) -> Occurrence:
        occurrence_ref = self.client.collection("occurrences").document(occurrence_id)
        # Resolve the immutable room identity before opening the transaction so every
        # transaction that touches both records locks them in the same order: room,
        # then occurrence. This prevents floor/lifecycle and attendance updates from
        # deadlocking each other under concurrent requests.
        seed_snapshot = occurrence_ref.get()
        if not seed_snapshot.exists:
            raise NotFoundError("Occurrence not found")
        seed = Occurrence.model_validate(seed_snapshot.to_dict())
        room_ref = self.rooms.document(seed.room_id)

        @transactional
        def mutate(txn):  # type: ignore[no-untyped-def]
            room_snapshot = room_ref.get(transaction=txn)
            if not room_snapshot.exists:
                raise NotFoundError("Room not found")
            occurrence_snapshot = occurrence_ref.get(transaction=txn)
            if not occurrence_snapshot.exists:
                raise NotFoundError("Occurrence not found")
            current = Occurrence.model_validate(occurrence_snapshot.to_dict())
            if current.room_id != seed.room_id:
                raise ValueError("Occurrence room identity changed")
            updated = mutation(current.model_copy(deep=True))
            if updated.id != occurrence_id or updated.room_id != current.room_id:
                raise ValueError("Occurrence mutation cannot change identity")
            txn.set(occurrence_ref, _data(updated))
            active_id = room_snapshot.to_dict().get("active_occurrence_id")
            if updated.status.active:
                txn.update(room_ref, {"active_occurrence_id": updated.id})
            elif active_id == updated.id:
                txn.update(room_ref, {"active_occurrence_id": firestore.DELETE_FIELD})
            return updated

        return _run_contentious_transaction(self.client, mutate)

    def get_active_occurrence(self, room_id: str) -> Occurrence | None:
        room_snapshot = self.rooms.document(room_id).get()
        if not room_snapshot.exists:
            raise NotFoundError("Room not found")
        active_id = room_snapshot.to_dict().get("active_occurrence_id")
        if not active_id:
            return None
        occurrence = self.get_occurrence(active_id)
        return occurrence if occurrence.status.active else None

    def list_occurrences(self, room_id: str, limit: int = 100) -> list[Occurrence]:
        query = (
            self.client.collection("occurrences")
            .where(filter=firestore.FieldFilter("room_id", "==", room_id))
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return [Occurrence.model_validate(item.to_dict()) for item in query.stream()]

    def save_transcript_segment(self, segment: TranscriptSegment) -> TranscriptSegment:
        self.client.collection("transcript_segments").document(segment.id).set(_data(segment))
        return segment

    def list_transcript_segments(self, occurrence_id: str) -> list[TranscriptSegment]:
        query = (
            self.client.collection("transcript_segments")
            .where(filter=firestore.FieldFilter("occurrence_id", "==", occurrence_id))
            .order_by("sequence")
        )
        return [TranscriptSegment.model_validate(item.to_dict()) for item in query.stream()]

    def save_outbox(self, record: OutboxRecord) -> OutboxRecord:
        self.client.collection("outbox").document(record.id).set(_data(record))
        return record

    def ensure_outbox(self, record: OutboxRecord) -> OutboxRecord:
        record_ref = self.client.collection("outbox").document(record.id)
        transaction = self.client.transaction()

        @transactional
        def ensure(txn):  # type: ignore[no-untyped-def]
            snapshot = record_ref.get(transaction=txn)
            if snapshot.exists:
                return OutboxRecord.model_validate(snapshot.to_dict())
            txn.create(record_ref, _data(record))
            return record

        return ensure(transaction)

    def list_pending_outbox(self, limit: int = 100) -> list[OutboxRecord]:
        query = (
            self.client.collection("outbox")
            .where(filter=firestore.FieldFilter("published_at", "==", None))
            .order_by("created_at")
            .limit(limit)
        )
        return [OutboxRecord.model_validate(item.to_dict()) for item in query.stream()]
