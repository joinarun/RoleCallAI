#!/usr/bin/env python3
"""Assign shared ownership and rotate every legacy participant capability."""

from __future__ import annotations

import argparse
import base64
import hashlib
import secrets
from datetime import UTC, datetime

from google.cloud import firestore, kms
from google.cloud.firestore_v1 import transactional

from app.domain.enums import CapabilityKind
from app.domain.models import CapabilityRecord, Room
from app.security.seat_links import SeatLinkCipher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", default="rolecall-dev")
    parser.add_argument("--kms-key", required=True)
    parser.add_argument("--owner", default="shared-demo-admin")
    return parser.parse_args()


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def encrypt(
    client: kms.KeyManagementServiceClient,
    key: str,
    secret: str,
    room_id: str,
    slot_id: str,
    version: int,
) -> str:
    response = client.encrypt(
        request={
            "name": key,
            "plaintext": secret.encode("utf-8"),
            "additional_authenticated_data": SeatLinkCipher.associated_data(
                room_id, slot_id, version
            ),
        }
    )
    return f"kms1.{encode(response.ciphertext)}"


def migrate_room(
    client: firestore.Client,
    room_ref,  # type: ignore[no-untyped-def]
    rotations: dict[str, tuple[str, str, int]],
    owner: str,
) -> tuple[bool, int]:
    @transactional
    def migrate(transaction):  # type: ignore[no-untyped-def]
        current_snapshot = room_ref.get(transaction=transaction)
        if not current_snapshot.exists:
            return False, 0
        current = Room.model_validate(current_snapshot.to_dict())
        if current.active_occurrence_id:
            raise RuntimeError("A room became active during migration")
        if current.security_migration_version >= 1:
            return False, 0
        session_query = client.collection("capability_sessions").where(
            filter=firestore.FieldFilter("claims.room_id", "==", current.id)
        )
        sessions = list(transaction.get(session_query))
        if len(sessions) + len(current.slots) * 2 + 2 > 490:
            raise RuntimeError("A room has too many capability sessions for atomic migration")
        old_digests = [
            digest
            for digest in (
                current.admin_capability_digest,
                *(seat.capability_digest for seat in current.slots),
            )
            if digest
        ]
        for seat in current.slots:
            digest, ciphertext, version = rotations[seat.id]
            seat.capability_digest = digest
            seat.capability_ciphertext = ciphertext
            seat.capability_version = version
        current.owner_id = owner
        current.admin_capability_digest = None
        current.security_migration_version = 1
        timestamp = datetime.now(UTC)
        current.updated_at = timestamp
        transaction.set(room_ref, current.model_dump(mode="python", by_alias=False))
        for digest in old_digests:
            transaction.delete(client.collection("capabilities").document(digest))
        for seat in current.slots:
            record = CapabilityRecord(
                room_id=current.id,
                kind=CapabilityKind.SEAT,
                digest=seat.capability_digest,
                version=seat.capability_version,
                slot_id=seat.id,
            )
            transaction.set(
                client.collection("capabilities").document(record.digest),
                record.model_dump(mode="python", by_alias=False),
            )
        revoked = 0
        for snapshot in sessions:
            if snapshot.to_dict().get("revoked_at") is None:
                transaction.update(snapshot.reference, {"revoked_at": timestamp})
                revoked += 1
        return True, revoked

    return migrate(client.transaction())


def main() -> None:
    args = parse_args()
    if args.database == "(default)":
        raise SystemExit("Refusing to access the default Firestore database")
    client = firestore.Client(project=args.project, database=args.database)
    kms_client = kms.KeyManagementServiceClient()
    snapshots = list(client.collection("rooms").stream())
    rooms = [Room.model_validate(snapshot.to_dict()) for snapshot in snapshots]
    if any(room.active_occurrence_id for room in rooms):
        raise SystemExit("Migration refused: at least one room has an active occurrence")

    migrated_rooms = 0
    skipped_rooms = 0
    rotated_seats = 0
    revoked_sessions = 0
    for room in rooms:
        if room.security_migration_version >= 1:
            skipped_rooms += 1
            continue
        rotations: dict[str, tuple[str, str, int]] = {}
        for slot in room.slots:
            plaintext = secrets.token_urlsafe(32)
            version = slot.capability_version + 1
            rotations[slot.id] = (
                hashlib.sha256(plaintext.encode("utf-8")).hexdigest(),
                encrypt(kms_client, args.kms_key, plaintext, room.id, slot.id, version),
                version,
            )
        room_ref = client.collection("rooms").document(room.id)

        changed, room_revoked_sessions = migrate_room(client, room_ref, rotations, args.owner)
        if changed:
            migrated_rooms += 1
            rotated_seats += len(room.slots)
            revoked_sessions += room_revoked_sessions
        else:
            skipped_rooms += 1

    print(f"Rooms scanned: {len(rooms)}")
    print(f"Rooms migrated: {migrated_rooms}")
    print(f"Rooms already current: {skipped_rooms}")
    print(f"Participant seats rotated: {rotated_seats}")
    print(f"Capability sessions revoked: {revoked_sessions}")


if __name__ == "__main__":
    main()
