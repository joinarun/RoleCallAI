#!/usr/bin/env python3
"""Refuse a dev-environment suspend while durable meeting work is active."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping

ACTIVE_STATUSES = ("LOBBY", "STARTING", "RUNNING", "ENDING", "PROCESSING")


def summarize_runtime(active_counts: Mapping[str, int], pending_outbox: int) -> dict[str, object]:
    """Build the non-sensitive guard result consumed by the shell operator."""

    normalized = {status: int(active_counts.get(status, 0)) for status in ACTIVE_STATUSES}
    if any(count < 0 for count in normalized.values()) or pending_outbox < 0:
        raise ValueError("Runtime counts cannot be negative")
    active_total = sum(normalized.values())
    return {
        "safeToSuspend": active_total == 0 and pending_outbox == 0,
        "activeOccurrences": active_total,
        "activeByStatus": normalized,
        "pendingOutbox": int(pending_outbox),
    }


def inspect_firestore(project_id: str, database: str) -> dict[str, object]:
    """Read only aggregate-safe state from the explicitly named Firestore database."""

    if database == "(default)":
        raise ValueError("The runtime guard refuses to inspect the default Firestore database")

    from google.cloud import firestore
    from google.cloud.firestore_v1 import FieldFilter

    client = firestore.Client(project=project_id, database=database)
    active_counts: dict[str, int] = {}
    for status in ACTIVE_STATUSES:
        query = client.collection("occurrences").where(
            filter=FieldFilter("status", "==", status)
        )
        active_counts[status] = sum(1 for _ in query.stream())

    pending_query = client.collection("outbox").where(
        filter=FieldFilter("published_at", "==", None)
    )
    pending_outbox = sum(1 for _ in pending_query.stream())
    return summarize_runtime(active_counts, pending_outbox)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether RoleCallAI can be suspended without interrupting durable work."
    )
    parser.add_argument("--project", required=True, help="Google Cloud project ID")
    parser.add_argument("--database", required=True, help="Named Firestore database ID")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = inspect_firestore(args.project, args.database)
    # A failed safety check must fail closed regardless of SDK/auth failure type.
    except Exception as error:
        print(
            json.dumps(
                {
                    "safeToSuspend": False,
                    "error": f"Firestore safety check failed: {type(error).__name__}",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    print(json.dumps(result, sort_keys=True))
    return 0 if result["safeToSuspend"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
