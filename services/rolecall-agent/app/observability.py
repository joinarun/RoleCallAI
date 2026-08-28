"""Privacy-preserving telemetry initialization."""

from __future__ import annotations

import json
import logging
import os
import re
import sys

from app.config import Settings

_REDACTIONS = (
    (re.compile(r"(?i)(#cap=)[^\s&]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(authorization[=: ]+bearer[ ]+)[^\s]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(rolecall_session=)[^;\s]+"), r"\1[REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), "[JWT]"),
    (
        re.compile(r"(?i)((?:new_handle|resumption_handle)[=:]\s*['\"]?)[^'\"\s,}]+"),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"(?i)(['\"]?(?:password|api_secret)['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+"),
        r"\1[REDACTED]",
    ),
)

_configured = False


class PrivacyJsonFormatter(logging.Formatter):
    """Emit Cloud Logging-compatible JSON while removing credential shapes."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        for pattern, replacement in _REDACTIONS:
            message = pattern.sub(replacement, message)
        return json.dumps(
            {
                "severity": record.levelname,
                "logger": record.name,
                "message": message,
                "service": os.getenv("ROLECALL_SERVICE_NAME", "rolecall"),
            },
            ensure_ascii=False,
        )


def configure_observability(settings: Settings) -> None:
    """Configure structured logs and optionally export traces without content."""
    global _configured
    os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "NO_CONTENT"
    os.environ["ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"] = "false"
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(PrivacyJsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    # ADK INFO messages can contain session-resumption handles. RoleCallAI emits
    # its own content-free reconnect and latency events instead.
    logging.getLogger("google_adk").setLevel(logging.WARNING)
    _configured = True
    if settings.env not in {"dev", "prod"}:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": os.getenv("ROLECALL_SERVICE_NAME", "rolecall"),
                "cloud.region": settings.region,
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter()))
    trace.set_tracer_provider(provider)
