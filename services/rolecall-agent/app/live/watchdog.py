"""Deterministic recovery for a silent facilitator-owned floor."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WatchdogAction(StrEnum):
    NUDGE = "NUDGE"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True)
class WatchdogDecision:
    action: WatchdogAction
    attempt: int


class AgentResponseWatchdog:
    """Detect an agent floor that produces no audio and request recovery."""

    def __init__(
        self,
        response_timeout_seconds: float,
        recovery_timeout_seconds: float,
        max_nudges: int = 2,
    ) -> None:
        if response_timeout_seconds <= 0:
            raise ValueError("response timeout must be positive")
        if recovery_timeout_seconds <= response_timeout_seconds:
            raise ValueError("recovery timeout must exceed response timeout")
        if max_nudges < 1:
            raise ValueError("max nudges must be positive")
        self.response_timeout_seconds = response_timeout_seconds
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.max_nudges = max_nudges
        self._floor_epoch: int | None = None
        self._waiting_since: float | None = None
        self._next_nudge_at: float | None = None
        self._nudge_count = 0
        self._timed_out = False

    def observe_floor(self, agent_owns_floor: bool, floor_epoch: int, now: float) -> None:
        if not agent_owns_floor:
            self._floor_epoch = floor_epoch
            self._waiting_since = None
            self._next_nudge_at = None
            self._nudge_count = 0
            self._timed_out = False
            return
        if self._floor_epoch == floor_epoch:
            return
        self._floor_epoch = floor_epoch
        self._waiting_since = now
        self._next_nudge_at = now + self.response_timeout_seconds
        self._nudge_count = 0
        self._timed_out = False

    def note_agent_audio(self) -> int:
        recovered_after = self._nudge_count
        self._waiting_since = None
        self._next_nudge_at = None
        self._nudge_count = 0
        return recovered_after

    def poll(self, now: float) -> WatchdogDecision | None:
        if self._waiting_since is None or self._timed_out:
            return None
        if now - self._waiting_since >= self.recovery_timeout_seconds:
            self._timed_out = True
            return WatchdogDecision(WatchdogAction.TIMEOUT, self._nudge_count)
        if (
            self._next_nudge_at is not None
            and now >= self._next_nudge_at
            and self._nudge_count < self.max_nudges
        ):
            self._nudge_count += 1
            self._next_nudge_at = now + self.response_timeout_seconds
            return WatchdogDecision(WatchdogAction.NUDGE, self._nudge_count)
        return None
