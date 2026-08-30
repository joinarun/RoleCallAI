"""Dispatch idempotent voice-runtime operations to Cloud Run Jobs."""

from __future__ import annotations

import google.auth
from google.auth.transport.requests import AuthorizedSession

from app.config import Settings


def dispatch_runtime_job(settings: Settings, payload: dict[str, object]) -> str:
    action = str(payload.get("action", ""))
    if action not in {"wake", "suspend"}:
        raise ValueError("Unknown runtime action")
    operation_id = str(payload.get("operationId", ""))
    generation = int(payload.get("generation", 0))
    if not operation_id or generation <= 0:
        raise ValueError("Runtime operation metadata is missing")
    job = settings.runtime_wake_job if action == "wake" else settings.runtime_suspend_job
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = AuthorizedSession(credentials)
    url = (
        f"https://run.googleapis.com/v2/projects/{settings.project_id}/locations/"
        f"{settings.region}/jobs/{job}:run"
    )
    response = session.post(
        url,
        json={
            "overrides": {
                "containerOverrides": [
                    {
                        "name": "runtime-manager",
                        "env": [
                            {"name": "ROLECALL_RUNTIME_ACTION", "value": action},
                            {
                                "name": "ROLECALL_RUNTIME_OPERATION_ID",
                                "value": operation_id,
                            },
                            {
                                "name": "ROLECALL_RUNTIME_GENERATION",
                                "value": str(generation),
                            },
                        ],
                    }
                ],
                "taskCount": 1,
                "timeout": "1200s",
            }
        },
        timeout=30,
    )
    response.raise_for_status()
    return str(response.json().get("name", ""))
