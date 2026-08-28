"""Private Cloud Run entry point for post-processing and cleanup pushes."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google.auth.transport import requests as auth_requests
from google.oauth2 import id_token

from app.api import PubSubEnvelope, decode_pubsub
from app.container import create_container
from app.jobs.cleanup import (
    cleanup_expired,
    delete_room_artifacts,
    reconcile_active_occurrences,
)
from app.jobs.outbox import drain_outbox
from app.jobs.postprocessor import process_occurrence
from app.observability import configure_observability

logger = logging.getLogger("rolecall.jobs")


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    container = create_container()
    configure_observability(container.settings)
    app.state.container = container
    yield


app = FastAPI(
    title="RoleCallAI private jobs",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    default_response_class=JSONResponse,
    lifespan=lifespan,
)


async def verify_push(request: Request) -> None:
    settings = request.app.state.container.settings
    if settings.env in {"local", "test"}:
        return
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        raise PermissionError("OIDC bearer token required")
    claims = await asyncio.to_thread(
        id_token.verify_oauth2_token,
        authorization.removeprefix("Bearer "),
        auth_requests.Request(),
        settings.pubsub_audience,
    )
    expected_email = (
        settings.pubsub_invoker_email
        if request.url.path.startswith("/v1/internal/pubsub/")
        else settings.scheduler_invoker_email
    )
    if expected_email and claims.get("email") != expected_email:
        raise PermissionError("Unexpected Pub/Sub push principal")


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(PermissionError)
async def handle_permission_error(request: Request, exc: PermissionError) -> JSONResponse:
    logger.warning(
        "event=job_auth_rejected path=%s error_type=%s",
        request.url.path,
        type(exc).__name__,
    )
    return JSONResponse(status_code=401, content={"error": {"code": "unauthorized"}})


@app.exception_handler(Exception)
async def handle_job_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "event=job_failed path=%s error_type=%s",
        request.url.path,
        type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "Job failed"}},
    )


@app.post("/v1/internal/pubsub/postprocess")
async def meeting_postprocess(request: Request, envelope: PubSubEnvelope):  # type: ignore[no-untyped-def]
    await verify_push(request)
    payload = decode_pubsub(envelope)
    recap = await process_occurrence(
        request.app.state.container,
        str(payload["occurrenceId"]),
    )
    return recap


@app.post("/v1/internal/pubsub/cleanup")
async def room_cleanup(request: Request, envelope: PubSubEnvelope):  # type: ignore[no-untyped-def]
    await verify_push(request)
    payload = decode_pubsub(envelope)
    if payload.get("action") != "deleteRoom":
        raise ValueError("Unknown cleanup action")
    return await asyncio.to_thread(
        delete_room_artifacts,
        request.app.state.container,
        payload,
    )


@app.post("/v1/internal/jobs/drain-outbox")
async def publish_outbox(request: Request):  # type: ignore[no-untyped-def]
    await verify_push(request)
    container = request.app.state.container
    reconciled = await asyncio.to_thread(reconcile_active_occurrences, container)
    drained = await asyncio.to_thread(drain_outbox, container)
    return {**drained, **reconciled}


@app.post("/v1/internal/jobs/cleanup")
async def retention_cleanup(request: Request):  # type: ignore[no-untyped-def]
    await verify_push(request)
    return await asyncio.to_thread(cleanup_expired, request.app.state.container)
