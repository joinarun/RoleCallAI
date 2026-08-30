"""Shared-admin authentication, reCAPTCHA verification, and durable throttling."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from google.cloud import recaptchaenterprise_v1, secretmanager
from itsdangerous import BadSignature, URLSafeSerializer

from app.config import Settings
from app.domain.errors import ForbiddenError, RateLimitError, UnauthorizedError
from app.domain.models import AdminSession, AdminSessionView
from app.domain.repository import Repository
from app.security.capabilities import sha256_digest


@dataclass(frozen=True)
class AdminCredential:
    username: str
    password_hash: str
    version: int


class AdminCredentialProvider:
    """Reads the versioned Argon2 credential from Secret Manager with a short cache."""

    def __init__(self, settings: Settings, password_hasher: PasswordHasher) -> None:
        self.settings = settings
        self.password_hasher = password_hasher
        self._cached: AdminCredential | None = None
        self._cached_until = 0.0
        self._secret_client: secretmanager.SecretManagerServiceClient | None = None

    def get(self) -> AdminCredential:
        now = time.monotonic()
        if self._cached and now < self._cached_until:
            return self._cached
        if not self.settings.admin_credentials_secret:
            if self.settings.env not in {"local", "test"}:
                raise RuntimeError("Admin credentials are not configured")
            credential = AdminCredential(
                username=self.settings.local_admin_username,
                password_hash=self.password_hasher.hash(
                    self.settings.local_admin_password.get_secret_value()
                ),
                version=1,
            )
        else:
            client = self._secret_client or secretmanager.SecretManagerServiceClient()
            self._secret_client = client
            resource = self.settings.admin_credentials_secret
            if "/versions/" not in resource:
                resource = f"{resource.rstrip('/')}/versions/latest"
            payload = client.access_secret_version(request={"name": resource}).payload.data
            value = json.loads(payload.decode("utf-8"))
            credential = AdminCredential(
                username=str(value["username"]),
                password_hash=str(value["password_hash"]),
                version=int(value["version"]),
            )
        self._cached = credential
        self._cached_until = now + 60
        return credential


class RecaptchaVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: recaptchaenterprise_v1.RecaptchaEnterpriseServiceClient | None = None

    def verify(self, token: str, username: str) -> None:
        if self.settings.recaptcha_bypass and self.settings.env in {"local", "test"}:
            if not token:
                raise UnauthorizedError("Login failed")
            return

        client = self._client or recaptchaenterprise_v1.RecaptchaEnterpriseServiceClient()
        self._client = client
        event = recaptchaenterprise_v1.Event(
            site_key=self.settings.recaptcha_site_key,
            token=token,
            expected_action=self.settings.recaptcha_action,
            hashed_account_id=hashlib.sha256(username.encode("utf-8")).digest(),
        )
        assessment = recaptchaenterprise_v1.Assessment(event=event)
        response = client.create_assessment(
            request={
                "parent": f"projects/{self.settings.project_id}",
                "assessment": assessment,
            }
        )
        properties = response.token_properties
        hostnames = {
            hostname.strip().casefold()
            for hostname in self.settings.recaptcha_allowed_hostnames.split(",")
            if hostname.strip()
        }
        suspicious_labels = {
            str(label).upper()
            for label in getattr(response.account_defender_assessment, "labels", [])
        }
        if (
            not properties.valid
            or properties.action != self.settings.recaptcha_action
            or properties.hostname.casefold() not in hostnames
            or response.risk_analysis.score < self.settings.recaptcha_min_score
            or any("SUSPICIOUS" in label or "ATTACK" in label for label in suspicious_labels)
        ):
            raise UnauthorizedError("Login failed")


class AdminAuthService:
    def __init__(self, repository: Repository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings
        self.password_hasher = PasswordHasher()
        self.credentials = AdminCredentialProvider(settings, self.password_hasher)
        self.recaptcha = RecaptchaVerifier(settings)
        self.serializer = URLSafeSerializer(
            settings.cookie_signing_key.get_secret_value(), salt="rolecall-admin-session-v1"
        )

    def login(
        self,
        username: str,
        password: str,
        recaptcha_token: str,
        client_ip: str,
        now: datetime | None = None,
    ) -> tuple[str, AdminSessionView]:
        timestamp = now or datetime.now(UTC)
        ip_key, prefix_key = self._throttle_keys(client_ip)
        since = timestamp - timedelta(minutes=self.settings.admin_login_window_minutes)
        if (
            self.repository.count_login_failures(ip_key, since)
            >= self.settings.admin_login_ip_limit
            or self.repository.count_login_failures(prefix_key, since)
            >= self.settings.admin_login_prefix_limit
        ):
            raise RateLimitError("Too many login attempts. Try again later")

        try:
            self.recaptcha.verify(recaptcha_token, username)
        except UnauthorizedError:
            expires_at = timestamp + timedelta(minutes=self.settings.admin_login_window_minutes)
            self.repository.record_login_failure(ip_key, timestamp, expires_at)
            self.repository.record_login_failure(prefix_key, timestamp, expires_at)
            raise
        credential = self.credentials.get()
        password_valid = False
        try:
            password_valid = self.password_hasher.verify(credential.password_hash, password)
        except (VerificationError, InvalidHashError):
            password_valid = False
        username_valid = hmac.compare_digest(username, credential.username)
        if not (password_valid and username_valid):
            expires_at = timestamp + timedelta(minutes=self.settings.admin_login_window_minutes)
            self.repository.record_login_failure(ip_key, timestamp, expires_at)
            self.repository.record_login_failure(prefix_key, timestamp, expires_at)
            raise UnauthorizedError("Login failed")

        self.repository.clear_login_failures([ip_key, prefix_key])
        raw_session = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        session = AdminSession(
            session_digest=sha256_digest(raw_session),
            owner_id=self.settings.admin_owner_id,
            credential_version=credential.version,
            csrf_digest=sha256_digest(csrf_token),
            expires_at=timestamp + timedelta(hours=self.settings.admin_session_hours),
            source_prefix_hash=prefix_key,
        )
        self.repository.save_admin_session(session)
        cookie = self.serializer.dumps({"sid": raw_session, "csrf": csrf_token})
        return cookie, self._view(session, credential.username, csrf_token)

    def authenticate(
        self,
        cookie: str | None,
        now: datetime | None = None,
    ) -> tuple[AdminSession, str, str]:
        if not cookie:
            raise UnauthorizedError("Admin login required")
        try:
            payload = self.serializer.loads(cookie)
            raw_session = str(payload["sid"])
            csrf_token = str(payload["csrf"])
        except (BadSignature, KeyError, TypeError, ValueError) as exc:
            raise UnauthorizedError("Admin login required") from exc
        session = self.repository.get_admin_session(sha256_digest(raw_session))
        timestamp = now or datetime.now(UTC)
        credential = self.credentials.get()
        if (
            session is None
            or session.revoked_at is not None
            or session.expires_at <= timestamp
            or session.credential_version != credential.version
            or session.owner_id != self.settings.admin_owner_id
        ):
            raise UnauthorizedError("Admin session expired")
        if not hmac.compare_digest(session.csrf_digest, sha256_digest(csrf_token)):
            raise UnauthorizedError("Admin session expired")
        return session, credential.username, csrf_token

    def session_view(self, cookie: str | None) -> AdminSessionView:
        session, username, csrf_token = self.authenticate(cookie)
        return self._view(session, username, csrf_token)

    def require_csrf(self, cookie: str | None, csrf_token: str | None) -> AdminSession:
        session, _, _ = self.authenticate(cookie)
        if not csrf_token or not hmac.compare_digest(
            session.csrf_digest, sha256_digest(csrf_token)
        ):
            raise ForbiddenError("Invalid CSRF token")
        return session

    def logout(self, cookie: str | None) -> None:
        try:
            session, _, _ = self.authenticate(cookie)
        except UnauthorizedError:
            return
        session.revoked_at = datetime.now(UTC)
        self.repository.save_admin_session(session)

    def _throttle_keys(self, client_ip: str) -> tuple[str, str]:
        try:
            address = ipaddress.ip_address(client_ip)
        except ValueError:
            address = ipaddress.ip_address("0.0.0.0")
        prefix_length = 24 if address.version == 4 else 64
        prefix = ipaddress.ip_network(f"{address}/{prefix_length}", strict=False)
        return self._privacy_key("ip", str(address)), self._privacy_key("prefix", str(prefix))

    def _privacy_key(self, kind: str, value: str) -> str:
        digest = hmac.new(
            self.settings.cookie_signing_key.get_secret_value().encode("utf-8"),
            f"{kind}\0{value}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"login-{kind}:{digest}"

    @staticmethod
    def _view(session: AdminSession, username: str, csrf_token: str) -> AdminSessionView:
        return AdminSessionView(
            authenticated=True,
            username=username,
            owner_id=session.owner_id,
            expires_at=session.expires_at,
            csrf_token=csrf_token,
        )
