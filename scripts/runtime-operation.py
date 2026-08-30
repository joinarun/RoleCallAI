#!/usr/bin/env python3
"""Create a guarded manual runtime transition without publishing an outbox event."""

from __future__ import annotations

import argparse
import secrets
from datetime import UTC, datetime

from google.cloud import firestore
from google.cloud.firestore_v1 import transactional

from app.domain.enums import OccurrenceStatus, RuntimeStatus
from app.domain.models import RuntimeState


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("wake", "suspend"))
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", default="rolecall-dev")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.database == "(default)":
        raise SystemExit("Refusing to access the default Firestore database")
    client = firestore.Client(project=args.project, database=args.database)
    if args.action == "suspend":
        for status in (
            OccurrenceStatus.LOBBY,
            OccurrenceStatus.STARTING,
            OccurrenceStatus.RUNNING,
            OccurrenceStatus.ENDING,
            OccurrenceStatus.PROCESSING,
        ):
            if next(
                client.collection("occurrences")
                .where(filter=firestore.FieldFilter("status", "==", status.value))
                .limit(1)
                .stream(),
                None,
            ):
                raise SystemExit("Suspend refused while a meeting is active")

    reference = client.collection("runtime").document("voice")
    now = datetime.now(UTC)

    @transactional
    def start(transaction):  # type: ignore[no-untyped-def]
        snapshot = reference.get(transaction=transaction)
        state = (
            RuntimeState.model_validate(snapshot.to_dict())
            if snapshot.exists
            else RuntimeState(
                status=RuntimeStatus.READY,
                progress=100,
                message="Voice services are ready",
                last_activity_at=now,
                last_activity_write_at=now,
            )
        )
        terminal = RuntimeStatus.READY if args.action == "wake" else RuntimeStatus.SLEEPING
        transitional = RuntimeStatus.WAKING if args.action == "wake" else RuntimeStatus.SUSPENDING
        if state.status == terminal:
            return f"already:{terminal.value}"
        if state.status == transitional and state.operation_id:
            return state.operation_id
        state.status = transitional
        state.progress = 1
        state.message = f"Manual {args.action} requested"
        state.generation += 1
        state.operation_id = f"manual_{args.action}_{secrets.token_urlsafe(12)}"
        state.transition_started_at = now
        state.error_code = None
        state.updated_at = now
        if args.action == "wake":
            state.last_activity_at = now
            state.last_activity_write_at = now
        transaction.set(reference, state.model_dump(mode="python", by_alias=False))
        return state.operation_id

    print(start(client.transaction()))


if __name__ == "__main__":
    main()
