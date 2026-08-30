"""Recoverable participant capabilities encrypted for authenticated administration."""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from google.cloud import kms

from app.config import Settings


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class SeatLinkCipher:
    """Uses Cloud KMS in deployed environments and authenticated AES-GCM locally."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._kms_client: kms.KeyManagementServiceClient | None = None
        self._local_key = hashlib.sha256(
            settings.cookie_signing_key.get_secret_value().encode("utf-8")
        ).digest()

    @staticmethod
    def associated_data(room_id: str, slot_id: str, version: int) -> bytes:
        return f"rolecall-seat-v1\0{room_id}\0{slot_id}\0{version}".encode()

    def encrypt(self, secret: str, room_id: str, slot_id: str, version: int) -> str:
        plaintext = secret.encode("utf-8")
        aad = self.associated_data(room_id, slot_id, version)
        if self.settings.seat_link_kms_key:
            client = self._kms_client or kms.KeyManagementServiceClient()
            self._kms_client = client
            response = client.encrypt(
                request={
                    "name": self.settings.seat_link_kms_key,
                    "plaintext": plaintext,
                    "additional_authenticated_data": aad,
                }
            )
            return f"kms1.{_encode(response.ciphertext)}"

        nonce = os.urandom(12)
        ciphertext = AESGCM(self._local_key).encrypt(nonce, plaintext, aad)
        return f"local1.{_encode(nonce + ciphertext)}"

    def decrypt(self, ciphertext: str, room_id: str, slot_id: str, version: int) -> str:
        aad = self.associated_data(room_id, slot_id, version)
        scheme, separator, payload = ciphertext.partition(".")
        if not separator:
            raise ValueError("Unsupported seat capability ciphertext")
        if scheme == "kms1":
            if not self.settings.seat_link_kms_key:
                raise ValueError("Cloud KMS is not configured")
            client = self._kms_client or kms.KeyManagementServiceClient()
            self._kms_client = client
            response = client.decrypt(
                request={
                    "name": self.settings.seat_link_kms_key,
                    "ciphertext": _decode(payload),
                    "additional_authenticated_data": aad,
                }
            )
            return response.plaintext.decode("utf-8")
        if scheme == "local1" and self.settings.env in {"local", "test"}:
            raw = _decode(payload)
            return AESGCM(self._local_key).decrypt(raw[:12], raw[12:], aad).decode("utf-8")
        raise ValueError("Unsupported seat capability ciphertext")
