from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.config import Settings
from app.container import Container, create_container
from app.domain.repository import InMemoryRepository


@dataclass
class FakeLiveKit:
    ensured: list[str]
    dispatched: list[str]
    enforced: list[str]
    published: list[tuple[str, str]]
    dispatch_attempts: list[str] = field(default_factory=list)

    def participant_token(self, occurrence, slot_id: str, display_name: str) -> str:  # type: ignore[no-untyped-def]
        return f"fake.jwt.{occurrence.id}.{slot_id}.{display_name}"

    async def ensure_room(self, occurrence) -> None:  # type: ignore[no-untyped-def]
        if occurrence.id not in self.ensured:
            self.ensured.append(occurrence.id)

    async def dispatch_agent(self, occurrence) -> None:  # type: ignore[no-untyped-def]
        self.dispatch_attempts.append(occurrence.id)
        if occurrence.id not in self.dispatched:
            self.dispatched.append(occurrence.id)

    async def enforce_floor(self, occurrence) -> None:  # type: ignore[no-untyped-def]
        self.enforced.append(occurrence.id)

    async def publish_message(self, occurrence, message_type: str, payload) -> bool:  # type: ignore[no-untyped-def]
        del payload
        self.published.append((occurrence.id, message_type))
        return True


@pytest.fixture
def settings() -> Settings:
    return Settings(
        env="test",
        repository="memory",
        public_base_url="https://rolecall.test",
        cookie_signing_key="test-signing-key-that-is-at-least-32-bytes",
        cookie_secure=False,
        lobby_early_start_seconds=120,
        disconnect_hold_seconds=30,
        wrap_up_seconds=120,
        closing_grace_seconds=60,
    )


@pytest.fixture
def repository() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def container(settings: Settings, repository: InMemoryRepository) -> Container:
    value = create_container(settings, repository)
    value.livekit = FakeLiveKit([], [], [], [])  # type: ignore[assignment]
    return value
