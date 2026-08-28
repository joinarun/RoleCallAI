from __future__ import annotations

import asyncio

import pytest

from app.live.playout import DeferredFinishCoordinator, drain_audio_playout


class FakeAudioSource:
    def __init__(self) -> None:
        self.playout_released = asyncio.Event()
        self.wait_started = asyncio.Event()

    async def wait_for_playout(self) -> None:
        self.wait_started.set()
        await self.playout_released.wait()


@pytest.mark.asyncio
async def test_deferred_finish_requires_the_turn_after_the_request() -> None:
    coordinator = DeferredFinishCoordinator()
    coordinator.note_turn_complete()
    coordinator.request("normal_completion")
    coordinator.request("must_not_replace_the_first_reason")

    waiting = asyncio.create_task(coordinator.wait_until_turn_complete(1))
    await asyncio.sleep(0)
    assert not waiting.done()

    coordinator.note_turn_complete()

    assert await waiting == "normal_completion"
    assert coordinator.target_completed_turns == 2


@pytest.mark.asyncio
async def test_playout_drain_waits_for_frame_capture_and_native_audio_queue() -> None:
    frames: asyncio.Queue[object] = asyncio.Queue()
    source = FakeAudioSource()
    frames.put_nowait(object())

    async def capture_queued_frame() -> None:
        await asyncio.sleep(0.01)
        await frames.get()
        frames.task_done()

    capture = asyncio.create_task(capture_queued_frame())
    drain = asyncio.create_task(drain_audio_playout(frames, source, 1))
    await source.wait_started.wait()
    assert not drain.done()

    source.playout_released.set()

    assert await drain is True
    await capture


@pytest.mark.asyncio
async def test_playout_drain_is_bounded_when_frames_never_capture() -> None:
    frames: asyncio.Queue[object] = asyncio.Queue()
    source = FakeAudioSource()
    frames.put_nowait(object())

    assert await drain_audio_playout(frames, source, 0.01) is False
    assert not source.wait_started.is_set()
