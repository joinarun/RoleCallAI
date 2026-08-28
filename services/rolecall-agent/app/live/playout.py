"""Coordination primitives for finishing a live meeting without cutting audio."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

FrameT = TypeVar("FrameT")


class PlayoutSource(Protocol):
    async def wait_for_playout(self) -> None: ...


@dataclass
class DeferredFinishCoordinator:
    """Wait for the model turn containing ``finish_meeting`` to fully complete."""

    completed_turns: int = 0
    reason: str | None = None
    requested_at: float | None = None
    target_completed_turns: int | None = None
    _requested: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    _turn_ready: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)

    @property
    def requested(self) -> bool:
        return self.reason is not None

    def request(self, reason: str) -> None:
        """Idempotently request completion after the currently active model turn."""
        if self.requested:
            return
        self.reason = reason.strip()[:120] or "agent_requested"
        self.requested_at = time.monotonic()
        self.target_completed_turns = self.completed_turns + 1
        self._requested.set()

    def note_turn_complete(self) -> None:
        self.completed_turns += 1
        if (
            self.target_completed_turns is not None
            and self.completed_turns >= self.target_completed_turns
        ):
            self._turn_ready.set()

    async def wait_until_turn_complete(self, timeout_seconds: float) -> str:
        await self._requested.wait()
        await asyncio.wait_for(self._turn_ready.wait(), timeout=timeout_seconds)
        return self.reason or "agent_requested"


async def drain_audio_playout(
    output_frames: asyncio.Queue[FrameT],
    output_source: PlayoutSource,
    timeout_seconds: float,
) -> bool:
    """Wait until application frames and LiveKit's native queue have both played."""
    try:
        async with asyncio.timeout(max(timeout_seconds, 0.1)):
            await output_frames.join()
            await output_source.wait_for_playout()
    except TimeoutError:
        return False
    return True
