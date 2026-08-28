"""Repository protocol and deterministic in-memory implementation."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from threading import RLock
from typing import Protocol

from app.domain.errors import ConflictError, NotFoundError
from app.domain.models import (
    CapabilityRecord,
    CapabilitySession,
    Occurrence,
    OutboxRecord,
    Room,
    TranscriptSegment,
)


class Repository(Protocol):
    def create_room(self, room: Room) -> Room: ...
    def get_room(self, room_id: str) -> Room: ...
    def save_room(self, room: Room) -> Room: ...
    def update_seat_display_name(
        self, room_id: str, slot_id: str, display_name: str, updated_at: datetime
    ) -> Room: ...
    def delete_room(self, room_id: str) -> None: ...
    def find_capability(self, digest: str) -> CapabilityRecord | None: ...
    def save_capability_session(self, session: CapabilitySession) -> None: ...
    def get_capability_session(self, digest: str) -> CapabilitySession | None: ...
    def revoke_capability_sessions(
        self, room_id: str, slot_id: str | None, before_version: int
    ) -> int: ...
    def create_occurrence_if_absent(self, occurrence: Occurrence) -> Occurrence: ...
    def get_occurrence(self, occurrence_id: str) -> Occurrence: ...
    def save_occurrence(self, occurrence: Occurrence) -> Occurrence: ...
    def mutate_occurrence(
        self, occurrence_id: str, mutation: Callable[[Occurrence], Occurrence]
    ) -> Occurrence: ...
    def get_active_occurrence(self, room_id: str) -> Occurrence | None: ...
    def list_occurrences(self, room_id: str, limit: int = 100) -> list[Occurrence]: ...
    def save_transcript_segment(self, segment: TranscriptSegment) -> TranscriptSegment: ...
    def list_transcript_segments(self, occurrence_id: str) -> list[TranscriptSegment]: ...
    def save_outbox(self, record: OutboxRecord) -> OutboxRecord: ...
    def ensure_outbox(self, record: OutboxRecord) -> OutboxRecord: ...
    def list_pending_outbox(self, limit: int = 100) -> list[OutboxRecord]: ...


class InMemoryRepository:
    """Thread-safe repository used for local development and hermetic tests."""

    def __init__(self) -> None:
        self._lock = RLock()
        self.rooms: dict[str, Room] = {}
        self.name_index: dict[str, str] = {}
        self.sessions: dict[str, CapabilitySession] = {}
        self.occurrences: dict[str, Occurrence] = {}
        self.active_by_room: dict[str, str] = {}
        self.transcripts: dict[str, dict[str, TranscriptSegment]] = {}
        self.outbox: dict[str, OutboxRecord] = {}

    def create_room(self, room: Room) -> Room:
        with self._lock:
            if room.normalized_name in self.name_index:
                raise ConflictError("A room with this name already exists")
            self.rooms[room.id] = deepcopy(room)
            self.name_index[room.normalized_name] = room.id
            return deepcopy(room)

    def get_room(self, room_id: str) -> Room:
        with self._lock:
            room = self.rooms.get(room_id)
            if room is None:
                raise NotFoundError("Room not found")
            return deepcopy(room)

    def save_room(self, room: Room) -> Room:
        with self._lock:
            current = self.rooms.get(room.id)
            if current is None:
                raise NotFoundError("Room not found")
            if current.active_occurrence_id:
                raise ConflictError("Room settings can only change while the room is idle")
            owner = self.name_index.get(room.normalized_name)
            if owner is not None and owner != room.id:
                raise ConflictError("A room with this name already exists")
            if current.normalized_name != room.normalized_name:
                self.name_index.pop(current.normalized_name, None)
            room.occurrence_counter = max(room.occurrence_counter, current.occurrence_counter)
            if current.active_occurrence_id:
                room.active_occurrence_id = current.active_occurrence_id
            self.name_index[room.normalized_name] = room.id
            self.rooms[room.id] = deepcopy(room)
            return deepcopy(room)

    def update_seat_display_name(
        self, room_id: str, slot_id: str, display_name: str, updated_at: datetime
    ) -> Room:
        with self._lock:
            room = self.rooms.get(room_id)
            if room is None:
                raise NotFoundError("Room not found")
            slot = next((item for item in room.slots if item.id == slot_id), None)
            if slot is None:
                raise NotFoundError("Seat not found")
            slot.last_display_name = display_name
            room.updated_at = updated_at
            self.rooms[room_id] = deepcopy(room)
            return deepcopy(room)

    def delete_room(self, room_id: str) -> None:
        with self._lock:
            room = self.rooms.pop(room_id, None)
            if room is None:
                raise NotFoundError("Room not found")
            self.name_index.pop(room.normalized_name, None)

    def find_capability(self, digest: str) -> CapabilityRecord | None:
        with self._lock:
            for room in self.rooms.values():
                if room.admin_capability_digest == digest:
                    return CapabilityRecord(
                        room_id=room.id,
                        kind="ADMIN",
                        digest=digest,
                        version=room.admin_capability_version,
                    )
                for slot in room.slots:
                    if slot.capability_digest == digest:
                        return CapabilityRecord(
                            room_id=room.id,
                            kind="SEAT",
                            digest=digest,
                            version=slot.capability_version,
                            slot_id=slot.id,
                        )
            return None

    def save_capability_session(self, session: CapabilitySession) -> None:
        with self._lock:
            self.sessions[session.session_digest] = deepcopy(session)

    def get_capability_session(self, digest: str) -> CapabilitySession | None:
        with self._lock:
            session = self.sessions.get(digest)
            return deepcopy(session) if session else None

    def revoke_capability_sessions(
        self, room_id: str, slot_id: str | None, before_version: int
    ) -> int:
        with self._lock:
            count = 0
            now = datetime.now().astimezone()
            for key, session in self.sessions.items():
                claims = session.claims
                if (
                    claims.room_id == room_id
                    and claims.slot_id == slot_id
                    and claims.capability_version < before_version
                    and session.revoked_at is None
                ):
                    session.revoked_at = now
                    self.sessions[key] = session
                    count += 1
            return count

    def create_occurrence_if_absent(self, occurrence: Occurrence) -> Occurrence:
        with self._lock:
            active_id = self.active_by_room.get(occurrence.room_id)
            if active_id:
                existing = self.occurrences.get(active_id)
                if existing and existing.status.active:
                    return deepcopy(existing)
            room = self.rooms.get(occurrence.room_id)
            if room is None:
                raise NotFoundError("Room not found")
            occurrence.number = room.occurrence_counter + 1
            room.occurrence_counter = occurrence.number
            room.active_occurrence_id = occurrence.id
            self.rooms[room.id] = deepcopy(room)
            self.occurrences[occurrence.id] = deepcopy(occurrence)
            self.active_by_room[occurrence.room_id] = occurrence.id
            return deepcopy(occurrence)

    def get_occurrence(self, occurrence_id: str) -> Occurrence:
        with self._lock:
            occurrence = self.occurrences.get(occurrence_id)
            if occurrence is None:
                raise NotFoundError("Occurrence not found")
            return deepcopy(occurrence)

    def save_occurrence(self, occurrence: Occurrence) -> Occurrence:
        with self._lock:
            if occurrence.id not in self.occurrences:
                raise NotFoundError("Occurrence not found")
            self.occurrences[occurrence.id] = deepcopy(occurrence)
            room = self.rooms.get(occurrence.room_id)
            if occurrence.status.active:
                self.active_by_room[occurrence.room_id] = occurrence.id
                if room:
                    room.active_occurrence_id = occurrence.id
            elif self.active_by_room.get(occurrence.room_id) == occurrence.id:
                self.active_by_room.pop(occurrence.room_id, None)
                if room:
                    room.active_occurrence_id = None
            if room:
                self.rooms[room.id] = deepcopy(room)
            return deepcopy(occurrence)

    def mutate_occurrence(
        self, occurrence_id: str, mutation: Callable[[Occurrence], Occurrence]
    ) -> Occurrence:
        with self._lock:
            current = self.occurrences.get(occurrence_id)
            if current is None:
                raise NotFoundError("Occurrence not found")
            updated = mutation(deepcopy(current))
            if updated.id != occurrence_id:
                raise ValueError("Occurrence mutation cannot change its ID")
            self.occurrences[occurrence_id] = deepcopy(updated)
            room = self.rooms.get(updated.room_id)
            if updated.status.active:
                self.active_by_room[updated.room_id] = updated.id
                if room:
                    room.active_occurrence_id = updated.id
            elif self.active_by_room.get(updated.room_id) == updated.id:
                self.active_by_room.pop(updated.room_id, None)
                if room:
                    room.active_occurrence_id = None
            if room:
                self.rooms[room.id] = deepcopy(room)
            return deepcopy(updated)

    def get_active_occurrence(self, room_id: str) -> Occurrence | None:
        with self._lock:
            occurrence_id = self.active_by_room.get(room_id)
            occurrence = self.occurrences.get(occurrence_id) if occurrence_id else None
            if occurrence and occurrence.status.active:
                return deepcopy(occurrence)
            return None

    def list_occurrences(self, room_id: str, limit: int = 100) -> list[Occurrence]:
        with self._lock:
            values = [
                deepcopy(item) for item in self.occurrences.values() if item.room_id == room_id
            ]
            values.sort(key=lambda item: item.created_at, reverse=True)
            return values[:limit]

    def save_transcript_segment(self, segment: TranscriptSegment) -> TranscriptSegment:
        with self._lock:
            self.transcripts.setdefault(segment.occurrence_id, {})[segment.id] = deepcopy(segment)
            return deepcopy(segment)

    def list_transcript_segments(self, occurrence_id: str) -> list[TranscriptSegment]:
        with self._lock:
            values = list(self.transcripts.get(occurrence_id, {}).values())
            return sorted((deepcopy(item) for item in values), key=lambda item: item.sequence)

    def save_outbox(self, record: OutboxRecord) -> OutboxRecord:
        with self._lock:
            self.outbox[record.id] = deepcopy(record)
            return deepcopy(record)

    def ensure_outbox(self, record: OutboxRecord) -> OutboxRecord:
        with self._lock:
            existing = self.outbox.get(record.id)
            if existing is not None:
                return deepcopy(existing)
            self.outbox[record.id] = deepcopy(record)
            return deepcopy(record)

    def list_pending_outbox(self, limit: int = 100) -> list[OutboxRecord]:
        with self._lock:
            values = [deepcopy(item) for item in self.outbox.values() if item.published_at is None]
            values.sort(key=lambda item: item.created_at)
            return values[:limit]
