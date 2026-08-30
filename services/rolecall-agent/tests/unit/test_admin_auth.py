from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.domain.errors import RateLimitError, UnauthorizedError
from app.domain.repository import InMemoryRepository
from app.security.admin_auth import AdminAuthService, AdminCredential, RecaptchaVerifier


def auth_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "env": "test",
        "repository": "memory",
        "public_base_url": "https://rolecall.test",
        "cookie_signing_key": "admin-auth-test-key-that-is-at-least-32-bytes",
        "local_admin_username": "judge-test",
        "local_admin_password": "correct horse battery staple",
        "recaptcha_bypass": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_argon2_login_session_and_credential_rotation() -> None:
    repository = InMemoryRepository()
    auth = AdminAuthService(repository, auth_settings())
    now = datetime.now(UTC)

    cookie, view = auth.login(
        "judge-test", "correct horse battery staple", "test-token", "203.0.113.8", now
    )
    assert view.username == "judge-test"
    assert view.csrf_token not in cookie
    session, username, csrf = auth.authenticate(cookie, now + timedelta(minutes=1))
    assert username == "judge-test"
    assert session.csrf_digest != csrf

    auth.credentials._cached = AdminCredential(
        username="judge-new",
        password_hash=auth.password_hasher.hash("replacement-password"),
        version=2,
    )
    auth.credentials._cached_until = float("inf")
    with pytest.raises(UnauthorizedError, match="expired"):
        auth.authenticate(cookie, now + timedelta(minutes=2))


def test_unknown_username_and_wrong_password_are_indistinguishable() -> None:
    auth = AdminAuthService(InMemoryRepository(), auth_settings())
    messages: list[str] = []
    for username, password in (
        ("unknown-user", "correct horse battery staple"),
        ("judge-test", "incorrect-password"),
    ):
        with pytest.raises(UnauthorizedError) as raised:
            auth.login(username, password, "test-token", "198.51.100.7")
        messages.append(str(raised.value))
    assert messages == ["Login failed", "Login failed"]


def test_login_throttles_ip_and_network_prefix_durably() -> None:
    repository = InMemoryRepository()
    auth = AdminAuthService(
        repository,
        auth_settings(admin_login_ip_limit=2, admin_login_prefix_limit=3),
    )
    for _ in range(2):
        with pytest.raises(UnauthorizedError):
            auth.login("judge-test", "wrong", "test-token", "192.0.2.20")
    with pytest.raises(RateLimitError):
        auth.login("judge-test", "wrong", "test-token", "192.0.2.20")

    with pytest.raises(UnauthorizedError):
        auth.login("judge-test", "wrong", "test-token", "192.0.2.21")
    with pytest.raises(RateLimitError):
        auth.login("judge-test", "wrong", "test-token", "192.0.2.22")


def test_admin_session_expires_after_eight_hours() -> None:
    auth = AdminAuthService(InMemoryRepository(), auth_settings(admin_session_hours=8))
    now = datetime.now(UTC)
    cookie, _ = auth.login(
        "judge-test", "correct horse battery staple", "test-token", "203.0.113.9", now
    )
    with pytest.raises(UnauthorizedError, match="expired"):
        auth.authenticate(cookie, now + timedelta(hours=8, seconds=1))


class _AssessmentClient:
    def __init__(
        self,
        *,
        valid: bool = True,
        action: str = "admin_login",
        score: float = 0.9,
        hostname: str = "rolecall.test",
        labels: list[str] | None = None,
    ) -> None:
        self.response = SimpleNamespace(
            token_properties=SimpleNamespace(
                valid=valid,
                action=action,
                hostname=hostname,
            ),
            risk_analysis=SimpleNamespace(score=score),
            account_defender_assessment=SimpleNamespace(labels=labels or []),
        )

    def create_assessment(self, request: object) -> object:
        assert request
        return self.response


@pytest.mark.parametrize(
    ("overrides", "allowed"),
    [
        ({}, True),
        ({"valid": False}, False),
        ({"action": "different_action"}, False),
        ({"score": 0.2}, False),
        ({"hostname": "other.example"}, False),
        ({"labels": ["SUSPICIOUS_ACCOUNT_CREATION"]}, False),
    ],
)
def test_recaptcha_verdicts(overrides: dict[str, object], allowed: bool) -> None:
    settings = auth_settings(
        recaptcha_bypass=False,
        recaptcha_site_key="site-key",
        recaptcha_allowed_hostnames="rolecall.test",
        recaptcha_min_score=0.5,
    )
    verifier = RecaptchaVerifier(settings)
    verifier._client = _AssessmentClient(**overrides)  # type: ignore[arg-type]
    if allowed:
        verifier.verify("token", "judge-test")
    else:
        with pytest.raises(UnauthorizedError, match="Login failed"):
            verifier.verify("token", "judge-test")


def test_recaptcha_failure_counts_toward_login_throttle() -> None:
    repository = InMemoryRepository()
    auth = AdminAuthService(
        repository,
        auth_settings(
            recaptcha_bypass=False,
            recaptcha_site_key="site-key",
            recaptcha_allowed_hostnames="rolecall.test",
            admin_login_ip_limit=1,
        ),
    )
    auth.recaptcha._client = _AssessmentClient(valid=False)  # type: ignore[assignment]
    with pytest.raises(UnauthorizedError):
        auth.login("judge-test", "correct horse battery staple", "bad", "203.0.113.10")
    with pytest.raises(RateLimitError):
        auth.login("judge-test", "correct horse battery staple", "bad", "203.0.113.10")
