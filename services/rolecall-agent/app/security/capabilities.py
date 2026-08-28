"""Capability creation, one-time exchange, scoped sessions, and revocation."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from itsdangerous import BadSignature, URLSafeSerializer

from app.config import Settings
from app.domain.enums import CapabilityKind
from app.domain.errors import UnauthorizedError
from app.domain.models import CapabilityClaims, CapabilityRecord, CapabilitySession
from app.domain.repository import Repository


def sha256_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CapabilityService:
    """Issues high-entropy links and exchanges them without persisting plaintext."""

    def __init__(self, repository: Repository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings
        self.serializer = URLSafeSerializer(
            settings.cookie_signing_key.get_secret_value(), salt="rolecall-capability-session-v1"
        )

    @staticmethod
    def issue_secret() -> tuple[str, str]:
        secret = secrets.token_urlsafe(32)
        return secret, sha256_digest(secret)

    def exchange(
        self, room_id: str, token: str, now: datetime | None = None
    ) -> tuple[str, CapabilityClaims]:
        timestamp = now or datetime.now(UTC)
        record = self.verify_token(room_id, token)

        raw_session_id = secrets.token_urlsafe(32)
        claims = CapabilityClaims(
            session_id=raw_session_id,
            room_id=record.room_id,
            kind=record.kind,
            slot_id=record.slot_id,
            capability_version=record.version,
            issued_at=timestamp,
            expires_at=timestamp + timedelta(minutes=self.settings.capability_session_minutes),
        )
        self.repository.save_capability_session(
            CapabilitySession(
                session_digest=sha256_digest(raw_session_id),
                claims=claims,
                expires_at=claims.expires_at,
            )
        )
        cookie = self.serializer.dumps({"sid": raw_session_id})
        return cookie, claims

    def verify_token(
        self,
        room_id: str,
        token: str,
        required_kind: CapabilityKind | None = None,
    ) -> CapabilityRecord:
        """Validate a raw link capability without creating or replacing a cookie session."""

        digest = sha256_digest(token)
        record = self.repository.find_capability(digest)
        if (
            record is None
            or not hmac.compare_digest(record.room_id, room_id)
            or (required_kind is not None and record.kind != required_kind)
        ):
            raise UnauthorizedError("Invalid or revoked capability")
        return record

    def authenticate(self, cookie: str | None, now: datetime | None = None) -> CapabilityClaims:
        if not cookie:
            raise UnauthorizedError("Capability session required")
        try:
            data = self.serializer.loads(cookie)
            raw_session_id = str(data["sid"])
        except (BadSignature, KeyError, TypeError, ValueError) as exc:
            raise UnauthorizedError("Invalid capability session") from exc

        session = self.repository.get_capability_session(sha256_digest(raw_session_id))
        timestamp = now or datetime.now(UTC)
        if (
            session is None
            or session.revoked_at is not None
            or session.claims.expires_at <= timestamp
        ):
            raise UnauthorizedError("Capability session expired or revoked")

        current = self._current_record(session.claims)
        if current is None or current.version != session.claims.capability_version:
            raise UnauthorizedError("Capability has been revoked")
        return session.claims

    def require_admin(self, cookie: str | None) -> CapabilityClaims:
        claims = self.authenticate(cookie)
        if claims.kind != CapabilityKind.ADMIN:
            raise UnauthorizedError("Admin capability required")
        return claims

    def require_seat(self, cookie: str | None) -> CapabilityClaims:
        claims = self.authenticate(cookie)
        if claims.kind != CapabilityKind.SEAT or not claims.slot_id:
            raise UnauthorizedError("Participant capability required")
        return claims

    def _current_record(self, claims: CapabilityClaims) -> CapabilityRecord | None:
        room = self.repository.get_room(claims.room_id)
        if claims.kind == CapabilityKind.ADMIN:
            return CapabilityRecord(
                room_id=room.id,
                kind=CapabilityKind.ADMIN,
                digest=room.admin_capability_digest,
                version=room.admin_capability_version,
            )
        slot = next((item for item in room.slots if item.id == claims.slot_id), None)
        if slot is None:
            return None
        return CapabilityRecord(
            room_id=room.id,
            kind=CapabilityKind.SEAT,
            digest=slot.capability_digest,
            version=slot.capability_version,
            slot_id=slot.id,
        )
