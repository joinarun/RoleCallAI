"""Composition root for API and background handlers."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.domain.repository import Repository
from app.retrieval.documents import DocumentService
from app.retrieval.indexing import (
    DocumentIndexer,
    DocumentRetrievalService,
    EmbeddingService,
)
from app.retrieval.memory import RoomMemoryService
from app.retrieval.object_store import DocumentObjectStore
from app.security.admin_auth import AdminAuthService
from app.security.capabilities import CapabilityService
from app.security.durable_rate_limit import DurableRateLimiter
from app.security.seat_links import SeatLinkCipher
from app.services.livekit import LiveKitService
from app.services.meetings import MeetingService
from app.services.rooms import RoomService
from app.services.runtime import RuntimeService
from app.storage.factory import get_repository


@dataclass
class Container:
    settings: Settings
    repository: Repository
    capabilities: CapabilityService
    admin_auth: AdminAuthService
    seat_links: SeatLinkCipher
    rooms: RoomService
    documents: DocumentService
    document_indexer: DocumentIndexer
    document_retrieval: DocumentRetrievalService
    meetings: MeetingService
    runtime: RuntimeService
    livekit: LiveKitService
    memory: RoomMemoryService
    rate_limits: DurableRateLimiter


def create_container(
    settings: Settings | None = None, repository: Repository | None = None
) -> Container:
    settings = settings or get_settings()
    repository = repository or get_repository()
    capabilities = CapabilityService(repository, settings)
    seat_links = SeatLinkCipher(settings)
    object_store = DocumentObjectStore(settings)
    embeddings = EmbeddingService(settings)
    documents = DocumentService(repository, object_store, settings)
    return Container(
        settings=settings,
        repository=repository,
        capabilities=capabilities,
        admin_auth=AdminAuthService(repository, settings),
        seat_links=seat_links,
        rooms=RoomService(repository, capabilities, seat_links, settings),
        documents=documents,
        document_indexer=DocumentIndexer(repository, object_store, embeddings, settings),
        document_retrieval=DocumentRetrievalService(repository, embeddings, settings),
        meetings=MeetingService(repository, settings, documents),
        runtime=RuntimeService(repository, settings),
        livekit=LiveKitService(settings),
        memory=RoomMemoryService(settings),
        rate_limits=DurableRateLimiter(repository, settings),
    )
