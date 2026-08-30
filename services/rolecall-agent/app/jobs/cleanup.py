"""Daily retention cleanup across Firestore, Agent Sessions, and Memory Bank."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import agentplatform
from google.cloud import firestore

from app.container import Container
from app.domain.enums import FloorOwnerType, OccurrenceStatus
from app.domain.models import Occurrence
from app.domain.repository import InMemoryRepository
from app.storage.firestore import FirestoreRepository


def _agent_engine_name(container: Container) -> str | None:
    value = container.settings.agent_engine_id
    if not value:
        return None
    if value.startswith("projects/"):
        return value
    return (
        f"projects/{container.settings.project_id}/locations/{container.settings.region}"
        f"/reasoningEngines/{value}"
    )


def cleanup_expired(container: Container, now: datetime | None = None) -> dict[str, int]:
    timestamp = now or datetime.now(UTC)
    counts = {
        "capabilitySessions": 0,
        "transcriptSegments": 0,
        "occurrences": 0,
        "memories": 0,
        "agentSessions": 0,
        "stuckProcessing": 0,
        "adminSessions": 0,
        "loginFailures": 0,
        "documentVersions": 0,
        "documentChunks": 0,
        "documentObjects": 0,
    }
    repository = container.repository
    _reconcile_stuck_processing(container, timestamp, counts)
    if isinstance(repository, InMemoryRepository):
        with repository._lock:
            for key, session in list(repository.sessions.items()):
                if session.expires_at <= timestamp:
                    del repository.sessions[key]
                    counts["capabilitySessions"] += 1
            for occurrence_id, segments in list(repository.transcripts.items()):
                for segment_id, segment in list(segments.items()):
                    if segment.expires_at <= timestamp:
                        del segments[segment_id]
                        counts["transcriptSegments"] += 1
                if not segments:
                    repository.transcripts.pop(occurrence_id, None)
            for occurrence_id, occurrence in list(repository.occurrences.items()):
                if occurrence.expires_at and occurrence.expires_at <= timestamp:
                    del repository.occurrences[occurrence_id]
                    repository.active_by_room.pop(occurrence.room_id, None)
                    counts["occurrences"] += 1
            for key, session in list(repository.admin_sessions.items()):
                if session.expires_at <= timestamp:
                    del repository.admin_sessions[key]
                    counts["adminSessions"] += 1
            for key, failures in list(repository.login_failures.items()):
                remaining = [item for item in failures if item[1] > timestamp]
                counts["loginFailures"] += len(failures) - len(remaining)
                if remaining:
                    repository.login_failures[key] = remaining
                else:
                    repository.login_failures.pop(key, None)
            expired_versions = [
                version.model_copy(deep=True)
                for version in repository.document_versions.values()
                if version.expires_at <= timestamp
            ]
            for version in expired_versions:
                counts["documentChunks"] += repository.delete_document_chunks(
                    version.room_id, version.id
                )
                container.documents.object_store.delete(version.object_name)
                counts["documentObjects"] += 1
                repository.document_versions.pop(version.id, None)
                counts["documentVersions"] += 1
                document = repository.documents.get(version.document_id)
                if document:
                    if document.active_version_id == version.id:
                        document.active_version_id = None
                    if document.pending_version_id == version.id:
                        document.pending_version_id = None
                    if not document.active_version_id and not document.pending_version_id:
                        document.deleted_at = timestamp
                    repository.documents[document.id] = document
    elif isinstance(repository, FirestoreRepository):
        _cleanup_firestore(container, repository, timestamp, counts)

    agent_counts = cleanup_expired_agent_data(container, timestamp)
    counts["memories"] += agent_counts["memories"]
    counts["agentSessions"] += agent_counts["agentSessions"]
    return counts


def reconcile_active_occurrences(
    container: Container, now: datetime | None = None
) -> dict[str, int]:
    """Close meetings whose hard timer elapsed or whose worker heartbeat was lost."""
    timestamp = now or datetime.now(UTC)
    repository = container.repository
    active_statuses = {
        OccurrenceStatus.STARTING,
        OccurrenceStatus.RUNNING,
        OccurrenceStatus.ENDING,
    }
    if isinstance(repository, InMemoryRepository):
        with repository._lock:
            occurrences = [
                item.model_copy(deep=True)
                for item in repository.occurrences.values()
                if item.status in active_statuses
            ]
    elif isinstance(repository, FirestoreRepository):
        occurrences: list[Occurrence] = []
        for status in active_statuses:
            query = repository.client.collection("occurrences").where(
                filter=firestore.FieldFilter("status", "==", status.value)
            )
            occurrences.extend(
                Occurrence.model_validate(snapshot.to_dict()) for snapshot in query.stream()
            )
    else:
        occurrences = []

    counts = {"durationElapsed": 0, "agentRecoveryTimeout": 0}
    for occurrence in occurrences:
        room = repository.get_room(occurrence.room_id)
        hard_end = (
            occurrence.started_at
            + timedelta(
                minutes=room.duration_minutes,
                seconds=container.settings.closing_grace_seconds,
            )
            if occurrence.started_at
            else None
        )
        heartbeat = occurrence.agent_last_seen_at or occurrence.started_at or occurrence.created_at
        reason: str | None = None
        if hard_end is not None and timestamp >= hard_end:
            reason = "duration_elapsed"
        elif timestamp >= heartbeat + timedelta(seconds=container.settings.agent_recovery_seconds):
            reason = "agent_recovery_timeout"
        if reason is None:
            continue
        finished = container.meetings.finish(occurrence.id, reason)
        if finished.status == OccurrenceStatus.PROCESSING:
            counter = "durationElapsed" if reason == "duration_elapsed" else "agentRecoveryTimeout"
            counts[counter] += 1
    return counts


def _reconcile_stuck_processing(
    container: Container, timestamp: datetime, counts: dict[str, int]
) -> None:
    repository = container.repository
    cutoff = timestamp - timedelta(minutes=container.settings.processing_timeout_minutes)
    stuck_ids: list[str] = []
    if isinstance(repository, InMemoryRepository):
        with repository._lock:
            stuck_ids = [
                item.id
                for item in repository.occurrences.values()
                if item.status == OccurrenceStatus.PROCESSING
                and item.ended_at is not None
                and item.ended_at <= cutoff
            ]
    elif isinstance(repository, FirestoreRepository):
        query = repository.client.collection("occurrences").where(
            filter=firestore.FieldFilter("status", "==", OccurrenceStatus.PROCESSING.value)
        )
        stuck_ids = [
            snapshot.id
            for snapshot in query.stream()
            if (ended_at := snapshot.to_dict().get("ended_at")) is not None and ended_at <= cutoff
        ]

    for occurrence_id in stuck_ids:

        def fail(current):  # type: ignore[no-untyped-def]
            if current.status != OccurrenceStatus.PROCESSING:
                return current
            current.status = OccurrenceStatus.FAILED
            current.failure_reason = "postprocessing_timeout"
            current.current_floor_type = FloorOwnerType.NONE
            current.current_floor_slot_id = None
            current.next_floor_slot_id = None
            current.floor_epoch += 1
            current.expires_at = (current.ended_at or timestamp) + timedelta(
                days=container.settings.retention_days
            )
            current.sequence += 1
            return current

        failed = repository.mutate_occurrence(occurrence_id, fail)
        if failed.status == OccurrenceStatus.FAILED:
            counts["stuckProcessing"] += 1


def cleanup_expired_agent_data(
    container: Container,
    timestamp: datetime,
    *,
    room_id: str | None = None,
) -> dict[str, int]:
    """Delete expired Agent Platform data, optionally constrained to one room.

    The room constraint is also used by the deployed acceptance test so it can
    advance the retention clock without touching any other development data.
    """
    counts = {"memories": 0, "agentSessions": 0}
    engine_name = _agent_engine_name(container)
    if not engine_name:
        return counts

    client = agentplatform.Client(
        project=container.settings.project_id,
        location=container.settings.region,
    )
    for memory in client.agent_engines.list_memories(name=engine_name):
        memory_user_id = (memory.scope or {}).get("user_id")
        if room_id is not None and memory_user_id != room_id:
            continue
        if memory.expire_time and memory.expire_time <= timestamp and memory.name:
            client.agent_engines.delete_memory(name=memory.name)
            counts["memories"] += 1
    for session in client.agent_engines.list_sessions(name=engine_name):
        if room_id is not None and session.user_id != room_id:
            continue
        if session.expire_time and session.expire_time <= timestamp and session.name:
            client.agent_engines.delete_session(name=session.name)
            counts["agentSessions"] += 1
    return counts


def delete_room_artifacts(container: Container, payload: dict[str, Any]) -> dict[str, int]:
    """Idempotently remove non-room artifacts after an admin deletion."""
    room_id = str(payload["roomId"])
    deleted = {
        "firestore": 0,
        "memories": 0,
        "documentObjects": 0,
    }

    repository = container.repository
    if isinstance(repository, InMemoryRepository):
        with repository._lock:
            occurrence_ids = {
                item.id for item in repository.occurrences.values() if item.room_id == room_id
            }
            for key in occurrence_ids:
                repository.occurrences.pop(key, None)
                repository.transcripts.pop(key, None)
                deleted["firestore"] += 1
            for key in [
                key
                for key, session in repository.sessions.items()
                if session.claims.room_id == room_id
            ]:
                del repository.sessions[key]
                deleted["firestore"] += 1
            for document_id, document in list(repository.documents.items()):
                if document.room_id != room_id:
                    continue
                for version_id, version in list(repository.document_versions.items()):
                    if version.document_id != document_id:
                        continue
                    repository.delete_document_chunks(room_id, version_id)
                    container.documents.object_store.delete(version.object_name)
                    repository.document_versions.pop(version_id, None)
                    deleted["documentObjects"] += 1
                repository.documents.pop(document_id, None)
                deleted["firestore"] += 1
    elif isinstance(repository, FirestoreRepository):
        occurrences = repository.client.collection("occurrences").where(
            filter=firestore.FieldFilter("room_id", "==", room_id)
        )
        for snapshot in occurrences.stream():
            transcripts = repository.client.collection("transcript_segments").where(
                filter=firestore.FieldFilter("occurrence_id", "==", snapshot.id)
            )
            for segment in transcripts.stream():
                segment.reference.delete()
                deleted["firestore"] += 1
            snapshot.reference.delete()
            deleted["firestore"] += 1
        sessions = repository.client.collection("capability_sessions").where(
            filter=firestore.FieldFilter("claims.room_id", "==", room_id)
        )
        for snapshot in sessions.stream():
            snapshot.reference.delete()
            deleted["firestore"] += 1
        documents = repository.client.collection("documents").where(
            filter=firestore.FieldFilter("room_id", "==", room_id)
        )
        for document in documents.stream():
            versions = repository.client.collection("document_versions").where(
                filter=firestore.FieldFilter("document_id", "==", document.id)
            )
            for version in versions.stream():
                payload = version.to_dict()
                deleted["firestore"] += repository.delete_document_chunks(room_id, version.id)
                container.documents.object_store.delete(str(payload["object_name"]))
                deleted["documentObjects"] += 1
                version.reference.delete()
                deleted["firestore"] += 1
            document.reference.delete()
            deleted["firestore"] += 1

    engine_name = _agent_engine_name(container)
    if engine_name:
        platform_client = agentplatform.Client(
            project=container.settings.project_id,
            location=container.settings.region,
        )
        for memory in platform_client.agent_engines.list_memories(name=engine_name):
            if memory.name and memory.scope and memory.scope.get("user_id") == room_id:
                platform_client.agent_engines.delete_memory(name=memory.name)
                deleted["memories"] += 1
        for session in platform_client.agent_engines.list_sessions(name=engine_name):
            if session.name and session.user_id == room_id:
                platform_client.agent_engines.delete_session(name=session.name)
    return deleted


def _cleanup_firestore(
    container: Container,
    repository: FirestoreRepository,
    timestamp: datetime,
    counts: dict[str, int],
) -> None:
    client = repository.client
    for collection, field, counter in (
        ("admin_sessions", "expires_at", "adminSessions"),
        ("capability_sessions", "expires_at", "capabilitySessions"),
        ("login_failures", "expires_at", "loginFailures"),
        ("transcript_segments", "expires_at", "transcriptSegments"),
        ("occurrences", "expires_at", "occurrences"),
    ):
        query = client.collection(collection).where(
            filter=firestore.FieldFilter(field, "<=", timestamp)
        )
        _delete_snapshots(query.stream(), counts, counter)
    expired_versions = list(
        client.collection("document_versions")
        .where(filter=firestore.FieldFilter("expires_at", "<=", timestamp))
        .stream()
    )
    for snapshot in expired_versions:
        version = snapshot.to_dict()
        room_id = str(version["room_id"])
        version_id = snapshot.id
        counts["documentChunks"] += repository.delete_document_chunks(room_id, version_id)
        container.documents.object_store.delete(str(version["object_name"]))
        counts["documentObjects"] += 1
        document_ref = client.collection("documents").document(str(version["document_id"]))
        document_snapshot = document_ref.get()
        if document_snapshot.exists:
            document = document_snapshot.to_dict()
            updates: dict[str, Any] = {"updated_at": timestamp}
            if document.get("active_version_id") == version_id:
                updates["active_version_id"] = None
            if document.get("pending_version_id") == version_id:
                updates["pending_version_id"] = None
            remaining_active = updates.get("active_version_id", document.get("active_version_id"))
            remaining_pending = updates.get(
                "pending_version_id", document.get("pending_version_id")
            )
            if not remaining_active and not remaining_pending:
                updates["deleted_at"] = timestamp
            document_ref.update(updates)
        snapshot.reference.delete()
        counts["documentVersions"] += 1


def _delete_snapshots(snapshots: Any, counts: dict[str, int], counter: str) -> None:
    for snapshot in snapshots:
        snapshot.reference.delete()
        counts[counter] += 1
