"""Bounded PCM16 framing and deterministic sample-rate conversion utilities."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np


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
