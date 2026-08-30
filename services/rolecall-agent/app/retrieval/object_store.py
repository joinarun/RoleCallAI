"""Private immutable document object storage."""

from __future__ import annotations

from threading import RLock
from typing import BinaryIO

from google.cloud import storage

from app.config import Settings


class DocumentObjectStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: storage.Client | None = None
        self._memory: dict[str, bytes] = {}
        self._lock = RLock()

    def upload(self, object_name: str, source: BinaryIO, media_type: str) -> None:
        source.seek(0)
        if not self.settings.documents_bucket:
            if self.settings.env not in {"local", "test"}:
                raise RuntimeError("Document bucket is not configured")
            with self._lock:
                if object_name in self._memory:
                    raise ValueError("Immutable object already exists")
                self._memory[object_name] = source.read()
            source.seek(0)
            return
        client = self._client or storage.Client(project=self.settings.project_id)
        self._client = client
        blob = client.bucket(self.settings.documents_bucket).blob(object_name)
        if blob.exists(client):
            raise ValueError("Immutable object already exists")
        blob.upload_from_file(source, content_type=media_type, rewind=True, if_generation_match=0)

    def download(self, object_name: str) -> bytes:
        if not self.settings.documents_bucket:
            with self._lock:
                return self._memory[object_name]
        client = self._client or storage.Client(project=self.settings.project_id)
        self._client = client
        return client.bucket(self.settings.documents_bucket).blob(object_name).download_as_bytes()

    def delete(self, object_name: str) -> None:
        if not self.settings.documents_bucket:
            with self._lock:
                self._memory.pop(object_name, None)
            return
        client = self._client or storage.Client(project=self.settings.project_id)
        self._client = client
        blob = client.bucket(self.settings.documents_bucket).blob(object_name)
        try:
            blob.delete()
        except Exception as exc:
            if exc.__class__.__name__ != "NotFound":
                raise
