"""Bounded PCM16 framing and deterministic sample-rate conversion utilities."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class FloorAudioFrame:
    """One model-ready frame bound to the authoritative floor generation."""

    slot_id: str
    floor_epoch: int
    data: bytes


class Pcm16FrameBuffer:
    """Accumulate arbitrary PCM chunks into bounded 50-100 ms frames."""

    def __init__(self, sample_rate: int = 16000, frame_ms: int = 80) -> None:
        if sample_rate <= 0:
            raise ValueError("sample rate must be positive")
        if not 50 <= frame_ms <= 100:
            raise ValueError("frame_ms must be between 50 and 100")
        self.frame_bytes = sample_rate * frame_ms // 1000 * 2
        self._pending = bytearray()

    def push(self, data: bytes) -> list[bytes]:
        if len(data) % 2:
            raise ValueError("PCM16 byte length must be even")
        self._pending.extend(data)
        frames: list[bytes] = []
        while len(self._pending) >= self.frame_bytes:
            frames.append(bytes(self._pending[: self.frame_bytes]))
            del self._pending[: self.frame_bytes]
        return frames

    def clear(self) -> None:
        self._pending.clear()


class FloorAudioFramer:
    """Frame PCM after floor scoping so queued audio cannot cross a handoff."""

    def __init__(self, sample_rate: int = 16000, frame_ms: int = 80) -> None:
        self._buffer = Pcm16FrameBuffer(sample_rate=sample_rate, frame_ms=frame_ms)
        self._scope: tuple[str, int] | None = None

    def push(self, slot_id: str, floor_epoch: int, data: bytes) -> list[FloorAudioFrame]:
        scope = (slot_id, floor_epoch)
        if self._scope != scope:
            self._buffer.clear()
            self._scope = scope
        return [
            FloorAudioFrame(slot_id=slot_id, floor_epoch=floor_epoch, data=frame)
            for frame in self._buffer.push(data)
        ]

    def clear(self) -> None:
        self._scope = None
        self._buffer.clear()


def resample_pcm16(data: bytes, input_rate: int, output_rate: int) -> bytes:
    """Linearly resample mono little-endian PCM16 without retaining audio."""
    if input_rate <= 0 or output_rate <= 0:
        raise ValueError("sample rates must be positive")
    if len(data) % 2:
        raise ValueError("PCM16 byte length must be even")
    if not data or input_rate == output_rate:
        return data
    samples = np.frombuffer(data, dtype="<i2").astype(np.float32)
    output_length = max(1, round(len(samples) * output_rate / input_rate))
    source_positions = np.linspace(0, len(samples) - 1, num=len(samples), dtype=np.float32)
    output_positions = np.linspace(0, len(samples) - 1, num=output_length, dtype=np.float32)
    output = np.interp(output_positions, source_positions, samples)
    return np.clip(np.rint(output), -32768, 32767).astype("<i2").tobytes()


def frame_pcm16(data: bytes, sample_rate: int, frame_ms: int = 80) -> Iterator[bytes]:
    """Yield 50-100 ms mono frames, dropping no complete samples."""
    if not 50 <= frame_ms <= 100:
        raise ValueError("frame_ms must be between 50 and 100")
    frame_bytes = sample_rate * frame_ms // 1000 * 2
    for offset in range(0, len(data), frame_bytes):
        chunk = data[offset : offset + frame_bytes]
        if chunk:
            yield chunk
