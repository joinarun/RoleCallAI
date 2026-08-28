"""Loopback-only ADK server adapter for ``agents-cli eval generate``.

agents-cli 1.4 serializes an evaluation event's ``state_delta`` as a top-level
``stateDelta`` field. ADK's session endpoint accepts prior events, but its Event
schema ignores that field because event state belongs under ``actions`` (which
the endpoint intentionally rejects for client-supplied history). This adapter
moves only the trusted ``rolecallEval`` fixture into initial session state and
leaves the conversation history intact.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from google.adk.cli.fast_api import get_fast_api_app
from starlette.types import Message, Receive, Scope, Send

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_SESSION_PATH = re.compile(r"^/apps/app/users/eval-cli-user/sessions/?$")
_MAX_REQUEST_BYTES = 2 * 1024 * 1024


def rewrite_session_seed(raw_body: bytes) -> bytes:
    """Move the validated RoleCallAI fixture into ADK initial session state."""
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return raw_body
    if not isinstance(payload, dict):
        return raw_body

    state = payload.get("state")
    if not isinstance(state, dict):
        state = {}
    fixture: dict[str, Any] | None = None
    events = payload.get("events")
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            delta = event.pop("stateDelta", None)
            if not isinstance(delta, dict):
                continue
            candidate = delta.get("rolecallEval")
            if isinstance(candidate, dict) and candidate.get("scenarioId"):
                fixture = candidate
    if fixture is None:
        return raw_body

    state["rolecallEval"] = fixture
    payload["state"] = state
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()


class EvalStateSeedMiddleware:
    """Rewrite only loopback requests for the fixed evaluation user and app."""

    def __init__(self, wrapped_app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.wrapped_app = wrapped_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        client = scope.get("client")
        client_host = client[0] if client else ""
        if (
            scope.get("type") != "http"
            or scope.get("method") != "POST"
            or not _SESSION_PATH.fullmatch(str(scope.get("path", "")))
            or client_host not in {"127.0.0.1", "::1", "testclient"}
        ):
            await self.wrapped_app(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                await self.wrapped_app(scope, _single_message_receive(message), send)
                return
            body.extend(message.get("body", b""))
            if len(body) > _MAX_REQUEST_BYTES:
                await self.wrapped_app(scope, _single_message_receive(message), send)
                return
            if not message.get("more_body", False):
                break

        rewritten = rewrite_session_seed(bytes(body))
        headers = [
            (name, value)
            for name, value in scope.get("headers", [])
            if name.lower() != b"content-length"
        ]
        headers.append((b"content-length", str(len(rewritten)).encode()))
        rewritten_scope = dict(scope)
        rewritten_scope["headers"] = headers
        await self.wrapped_app(
            rewritten_scope,
            _single_message_receive(
                {"type": "http.request", "body": rewritten, "more_body": False}
            ),
            send,
        )


def _single_message_receive(message: Message) -> Receive:
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return message
        return {"type": "http.disconnect"}

    return receive


_adk_app = get_fast_api_app(
    agents_dir=str(_SERVICE_ROOT),
    session_service_uri="memory://",
    artifact_service_uri="memory://",
    memory_service_uri="memory://",
    use_local_storage=False,
    web=False,
    auto_create_session=False,
)
app = EvalStateSeedMiddleware(_adk_app)
