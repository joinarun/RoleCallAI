"""Composition root for API and background handlers."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.domain.repository import Repository
from app.retrieval.memory import RoomMemoryService
from app.security.capabilities import CapabilityService
from app.security.rate_limit import RateLimiter
from app.services.livekit import LiveKitService
from app.services.meetings import MeetingService
from app.services.rooms import RoomService
from app.storage.factory import get_repository


@dataclass
class Container:
    settings: Settings
    repository: Repository
    capabilities: CapabilityService
    rooms: RoomService
    meetings: MeetingService
    livekit: LiveKitService
    memory: RoomMemoryService
    rate_limiter: RateLimiter


def create_container(
    settings: Settings | None = None, repository: Repository | None = None
) -> Container:
    settings = settings or get_settings()
    repository = repository or get_repository()
    capabilities = CapabilityService(repository, settings)
    return Container(
        settings=settings,
        repository=repository,
        capabilities=capabilities,
        rooms=RoomService(repository, capabilities, settings),
        meetings=MeetingService(repository, settings),
        livekit=LiveKitService(settings),
        memory=RoomMemoryService(settings),
        rate_limiter=RateLimiter(settings),
    )
