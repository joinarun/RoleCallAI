from __future__ import annotations

import json
import logging

from app.observability import PrivacyJsonFormatter


def test_privacy_formatter_redacts_session_handles_passwords_and_jwts() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=("new_handle='resume-secret' password=turn-secret eyJheader.eyJpayload.eyJsignature"),
        args=(),
        exc_info=None,
    )

    message = json.loads(PrivacyJsonFormatter().format(record))["message"]

    assert "resume-secret" not in message
    assert "turn-secret" not in message
    assert "eyJpayload" not in message
    assert message.count("[REDACTED]") == 2
    assert "[JWT]" in message
