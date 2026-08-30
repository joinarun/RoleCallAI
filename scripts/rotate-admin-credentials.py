#!/usr/bin/env python3
"""Rotate the shared demo administrator credential without persisting plaintext."""

from __future__ import annotations

import argparse
import json
import secrets
import string
from datetime import UTC, datetime

from argon2 import PasswordHasher
from google.api_core.exceptions import NotFound
from google.cloud import firestore, secretmanager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", default="rolecall-dev")
    parser.add_argument("--secret", required=True)
    return parser.parse_args()


def next_version(client: secretmanager.SecretManagerServiceClient, secret: str) -> int:
    try:
        payload = client.access_secret_version(
            request={"name": f"{secret.rstrip('/')}/versions/latest"}
        ).payload.data
    except NotFound:
        return 1
    return int(json.loads(payload.decode("utf-8"))["version"]) + 1


def revoke_sessions(project: str, database: str, credential_version: int) -> int:
    client = firestore.Client(project=project, database=database)
    snapshots = list(
        client.collection("admin_sessions")
        .where(filter=firestore.FieldFilter("credential_version", "<", credential_version))
        .stream()
    )
    revoked = 0
    for offset in range(0, len(snapshots), 400):
        batch = client.batch()
        for snapshot in snapshots[offset : offset + 400]:
            if snapshot.to_dict().get("revoked_at") is None:
                batch.update(snapshot.reference, {"revoked_at": datetime.now(UTC)})
                revoked += 1
        batch.commit()
    return revoked


def main() -> None:
    args = parse_args()
    if args.database == "(default)":
        raise SystemExit("Refusing to access the default Firestore database")
    alphabet = string.ascii_letters + string.digits + "-_.!@"
    username = f"judge-{secrets.token_hex(4)}"
    password = "".join(secrets.choice(alphabet) for _ in range(24))
    secret_client = secretmanager.SecretManagerServiceClient()
    version = next_version(secret_client, args.secret)
    value = {
        "username": username,
        "password_hash": PasswordHasher().hash(password),
        "version": version,
    }
    secret_client.add_secret_version(
        request={
            "parent": args.secret,
            "payload": {"data": json.dumps(value, separators=(",", ":")).encode("utf-8")},
        }
    )
    revoked = revoke_sessions(args.project, args.database, version)
    print("Save these RoleCallAI credentials now. The plaintext is not stored elsewhere.")
    print(f"Username: {username}")
    print(f"Password: {password}")
    print(f"Credential version: {version}")
    print(f"Prior admin sessions revoked: {revoked}")


if __name__ == "__main__":
    main()
