"""Room document lifecycle, immutable uploads, and indexing dispatch."""

from __future__ import annotations

import io
import re
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO

from app.config import Settings
from app.domain.enums import DocumentStatus
from app.domain.errors import ConflictError
from app.domain.models import (
    DocumentVersion,
    DocumentView,
    OutboxRecord,
    RoomDocument,
)
from app.domain.repository import Repository
from app.retrieval.object_store import DocumentObjectStore
from app.services.rooms import new_id

ALLOWED_TYPES = {
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
    },
    ".pptx": {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/zip",
        "application/octet-stream",
    },
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".markdown": {"text/markdown", "text/plain", "application/octet-stream"},
}
MAX_OPENXML_ENTRIES = 5_000
MAX_OPENXML_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_OPENXML_COMPRESSION_RATIO = 100


def validate_upload(
    filename: str, media_type: str, source: BinaryIO, max_bytes: int
) -> tuple[str, int]:
    safe_name = Path(filename).name
    if not safe_name or safe_name != filename or "\x00" in safe_name:
        raise ValueError("Invalid document filename")
    extension = Path(safe_name).suffix.casefold()
    if extension not in ALLOWED_TYPES:
        raise ValueError("Supported document types are PDF, DOCX, PPTX, TXT, and Markdown")
    normalized_media_type = (media_type or "application/octet-stream").split(";", 1)[0].casefold()
    if normalized_media_type not in ALLOWED_TYPES[extension]:
        raise ValueError("Document content type does not match its extension")

    source.seek(0, io.SEEK_END)
    size = source.tell()
    source.seek(0)
    if size <= 0:
        raise ValueError("Document is empty")
    if size > max_bytes:
        raise ValueError("Document exceeds the 25 MB limit")
    signature = source.read(8)
    source.seek(0)
    if extension == ".pdf" and not signature.startswith(b"%PDF-"):
        raise ValueError("File is not a valid PDF")
    if extension in {".docx", ".pptx"}:
        if not signature.startswith(b"PK"):
            raise ValueError("File is not a valid Open XML document")
        try:
            with zipfile.ZipFile(source) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_OPENXML_ENTRIES:
                    raise ValueError("Open XML archive contains too many entries")
                uncompressed = sum(item.file_size for item in entries)
                compressed = sum(item.compress_size for item in entries) or 1
                if (
                    uncompressed > MAX_OPENXML_UNCOMPRESSED_BYTES
                    or uncompressed / compressed > MAX_OPENXML_COMPRESSION_RATIO
                ):
                    raise ValueError("Open XML archive expands beyond the safe limit")
                names = {item.filename for item in entries}
                marker = "word/document.xml" if extension == ".docx" else "ppt/presentation.xml"
                if marker not in names:
                    raise ValueError("Document signature does not match its extension")
                if any(name.casefold().endswith("vbaproject.bin") for name in names):
                    raise ValueError("Macro-enabled documents are not supported")
        except zipfile.BadZipFile as exc:
            raise ValueError("File is not a valid Open XML document") from exc
        finally:
            source.seek(0)
    if extension in {".txt", ".md", ".markdown"}:
        sample = source.read(min(size, 64 * 1024))
        source.seek(0)
        if b"\x00" in sample:
            raise ValueError("Text documents must contain UTF-8 text")
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Text documents must use UTF-8 encoding") from exc
    return extension, size


class DocumentService:
    def __init__(
        self,
        repository: Repository,
        object_store: DocumentObjectStore,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.object_store = object_store
        self.settings = settings

    def list(self, room_id: str) -> list[DocumentView]:
        self.repository.get_room(room_id)
        return [self._view(document) for document in self.repository.list_documents(room_id)]

    def upload(
        self,
        room_id: str,
        filename: str,
        media_type: str,
        source: BinaryIO,
        *,
        document_id: str | None = None,
    ) -> DocumentView:
        self._assert_idle(room_id)
        extension, size = validate_upload(
            filename, media_type, source, self.settings.document_max_bytes
        )
        documents = self.repository.list_documents(room_id)
        if document_id is None and len(documents) >= self.settings.document_max_files_per_room:
            raise ConflictError("Room already has the maximum of 20 active documents")
        total_bytes = sum(self._latest_size(item) for item in documents)
        replacing_size = 0
        if document_id is not None:
            document = self.repository.get_document(room_id, document_id)
            replacing_size = self._latest_size(document)
            if document.pending_version_id:
                raise ConflictError("Wait for the current replacement to finish indexing")
            version_number = document.version_counter + 1
        else:
            document_id = new_id("doc")
            document = RoomDocument(
                id=document_id,
                room_id=room_id,
                title=self._title(filename),
            )
            version_number = 1
        if total_bytes - replacing_size + size > self.settings.document_max_room_bytes:
            raise ConflictError("Room documents exceed the 200 MB combined limit")

        version_id = new_id("docv")
        timestamp = datetime.now(UTC)
        object_name = f"rooms/{room_id}/documents/{document_id}/versions/{version_id}{extension}"
        version = DocumentVersion(
            id=version_id,
            room_id=room_id,
            document_id=document_id,
            version=version_number,
            original_filename=filename,
            title=document.title,
            media_type=media_type or "application/octet-stream",
            extension=extension,
            object_name=object_name,
            size_bytes=size,
            expires_at=timestamp + timedelta(days=self.settings.retention_days),
        )
        self.object_store.upload(object_name, source, version.media_type)
        if version_number == 1:
            document.pending_version_id = version.id
            document.version_counter = 1
            self.repository.create_document(document, version)
        else:
            self.repository.create_document_version(version)
            document.pending_version_id = version.id
            document.version_counter = version_number
            document.updated_at = timestamp
            self.repository.save_document(document)
        self._enqueue_index(version)
        return self._view(document)

    def retry(self, room_id: str, document_id: str) -> DocumentView:
        self._assert_idle(room_id)
        document = self.repository.get_document(room_id, document_id)
        version_id = document.pending_version_id
        if not version_id:
            raise ConflictError("Document has no failed version to retry")
        version = self.repository.get_document_version(room_id, version_id)
        if version.status != DocumentStatus.FAILED:
            raise ConflictError("Only a failed document version can be retried")
        version.status = DocumentStatus.PENDING
        version.error_code = None
        version.error_message = None
        version.updated_at = datetime.now(UTC)
        self.repository.save_document_version(version)
        self._enqueue_index(version, retry=True)
        return self._view(document)

    def delete(self, room_id: str, document_id: str) -> None:
        self._assert_idle(room_id)
        document = self.repository.get_document(room_id, document_id)
        timestamp = datetime.now(UTC)
        for version in self.repository.list_document_versions(room_id, document_id):
            self.repository.delete_document_chunks(room_id, version.id)
            self.object_store.delete(version.object_name)
            version.status = DocumentStatus.DELETED
            version.updated_at = timestamp
            self.repository.save_document_version(version)
        document.deleted_at = timestamp
        document.active_version_id = None
        document.pending_version_id = None
        document.updated_at = timestamp
        self.repository.save_document(document)

    def ready_version_ids(self, room_id: str) -> tuple[list[str], int]:
        documents = self.repository.list_documents(room_id)
        ready = [item.active_version_id for item in documents if item.active_version_id]
        omitted = sum(
            1
            for item in documents
            if item.active_version_id is None or item.pending_version_id is not None
        )
        return [item for item in ready if item], omitted

    def _assert_idle(self, room_id: str) -> None:
        self.repository.get_room(room_id)
        if self.repository.get_active_occurrence(room_id) is not None:
            raise ConflictError("Documents can only change while the room is idle")

    def _latest_size(self, document: RoomDocument) -> int:
        version_id = document.pending_version_id or document.active_version_id
        if not version_id:
            return 0
        return self.repository.get_document_version(document.room_id, version_id).size_bytes

    def _view(self, document: RoomDocument) -> DocumentView:
        return DocumentView(
            document=document,
            active_version=(
                self.repository.get_document_version(document.room_id, document.active_version_id)
                if document.active_version_id
                else None
            ),
            pending_version=(
                self.repository.get_document_version(document.room_id, document.pending_version_id)
                if document.pending_version_id
                else None
            ),
        )

    def _enqueue_index(self, version: DocumentVersion, retry: bool = False) -> None:
        suffix = f":retry:{int(version.updated_at.timestamp())}" if retry else ""
        self.repository.ensure_outbox(
            OutboxRecord(
                id=f"document-index:{version.id}{suffix}",
                topic=self.settings.document_index_topic,
                aggregate_id=version.id,
                payload={
                    "action": "indexDocument",
                    "roomId": version.room_id,
                    "documentId": version.document_id,
                    "versionId": version.id,
                },
            )
        )

    @staticmethod
    def _title(filename: str) -> str:
        title = re.sub(r"[_-]+", " ", Path(filename).stem).strip()
        return (title or "Untitled document")[:160]
