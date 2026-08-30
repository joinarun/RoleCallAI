"""Same-origin RoleCallAI SPA and FastAPI control-plane entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.admin_api import router as admin_router
from app.api import router
from app.container import create_container
from app.domain.errors import RoleCallError
from app.observability import configure_observability

logger = logging.getLogger("rolecall.control_plane")
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
WEB_DIST = WORKSPACE_ROOT / "apps" / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    container = create_container()
    configure_observability(container.settings)
    app.state.container = container
    yield


_initial_container = create_container()
_is_local = _initial_container.settings.env in {"local", "test"}
app = FastAPI(
    title="RoleCallAI",
    version="0.1.0",
    docs_url="/docs" if _is_local else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _is_local else None,
    default_response_class=JSONResponse,
    lifespan=lifespan,
)
app.include_router(router)
app.include_router(admin_router)

if _is_local:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "X-CSRF-Token",
            "X-Request-ID",
            "X-Upload-Content-Length",
        ],
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; connect-src 'self' https: wss: ws://localhost:*; "
        "script-src 'self' https://www.google.com https://www.gstatic.com; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'self'; "
        "frame-src https://www.google.com; frame-ancestors 'none'; form-action 'self'"
    )
    if not _is_local:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/v1/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(RoleCallError)
async def handle_domain_error(request: Request, exc: RoleCallError) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": str(exc)}},
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    del request
    fields = [".".join(str(part) for part in item["loc"]) for item in exc.errors()]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed",
                "fields": fields,
            }
        },
    )


@app.exception_handler(ValueError)
async def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "invalid_value", "message": str(exc)}},
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "event=unhandled_request_error method=%s path=%s error_type=%s",
        request.method,
        request.url.path,
        type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "Unexpected server error"}},
    )


@app.get("/healthz", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
def readiness() -> dict[str, str]:
    return {"status": "ready"}


if (WEB_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="web-assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):  # type: ignore[no-untyped-def]
    if path.startswith("v1/"):
        return JSONResponse(status_code=404, content={"error": {"code": "not_found"}})
    index = WEB_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        status_code=503,
        content={"error": {"code": "web_not_built", "message": "Run npm build in apps/web"}},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
