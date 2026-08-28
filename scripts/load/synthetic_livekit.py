#!/usr/bin/env python3
"""Five-room synthetic-audio LiveKit capacity check with no model calls."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import time
from array import array
from dataclasses import dataclass
from datetime import timedelta

from livekit import api, rtc

SAMPLE_RATE = 48_000
FRAME_MS = 20
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_MS // 1000


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)
    return ordered[max(0, index)]


def audio_frame(frequency: float) -> rtc.AudioFrame:
    samples = array(
        "h",
        (
            int(4_000 * math.sin(2 * math.pi * frequency * sample / SAMPLE_RATE))
            for sample in range(SAMPLES_PER_FRAME)
        ),
    )
    return rtc.AudioFrame(
        data=samples.tobytes(),
        sample_rate=SAMPLE_RATE,
        num_channels=1,
        samples_per_channel=SAMPLES_PER_FRAME,
    )


@dataclass
class SyntheticParticipant:
    room_name: str
    identity: str
    url: str
    token: str
    frequency: float
    room: rtc.Room | None = None
    source: rtc.AudioSource | None = None
    connect_seconds: float = 0.0

    async def connect(self) -> None:
        started = time.perf_counter()
        self.room = rtc.Room()
        await asyncio.wait_for(self.room.connect(self.url, self.token), timeout=15)
        self.connect_seconds = time.perf_counter() - started
        self.source = rtc.AudioSource(SAMPLE_RATE, 1, queue_size_ms=200)
        track = rtc.LocalAudioTrack.create_audio_track("synthetic-microphone", self.source)
        await self.room.local_participant.publish_track(
            track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )

    async def stream(self, duration_seconds: float, start: asyncio.Event) -> None:
        if self.source is None:
            raise RuntimeError("participant is not connected")
        frame = audio_frame(self.frequency)
        await start.wait()
        deadline = time.perf_counter() + duration_seconds
        while time.perf_counter() < deadline:
            await self.source.capture_frame(frame)

    async def close(self) -> None:
        if self.room is not None:
            await self.room.disconnect()


def token(key: str, secret: str, room: str, identity: str) -> str:
    return (
        api.AccessToken(key, secret)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room,
                can_subscribe=True,
                can_publish=True,
                can_publish_data=True,
            )
        )
        .with_ttl(timedelta(minutes=15))
        .to_jwt()
    )


async def run(args: argparse.Namespace) -> dict[str, object]:
    key = os.environ.get("LIVEKIT_API_KEY")
    secret = os.environ.get("LIVEKIT_API_SECRET")
    if not key or not secret:
        raise RuntimeError("LIVEKIT_API_KEY and LIVEKIT_API_SECRET are required")
    http_url = args.url.replace("ws://", "http://").replace("wss://", "https://")
    server = api.LiveKitAPI(http_url, key, secret)
    stamp = int(time.time())
    room_names = [f"rolecall-load-{stamp}-{index + 1}" for index in range(args.rooms)]
    participants: list[SyntheticParticipant] = []
    errors: list[str] = []
    try:
        for room_name in room_names:
            await server.room.create_room(
                api.CreateRoomRequest(
                    name=room_name,
                    empty_timeout=120,
                    departure_timeout=10,
                    max_participants=args.participants,
                    metadata=json.dumps({"purpose": "rolecall-synthetic-load"}),
                )
            )
        # Interleave rooms so each connection batch adds load evenly instead of
        # making one room absorb an artificial same-process callback burst.
        for index in range(args.participants):
            for room_name in room_names:
                identity = f"synthetic-{index + 1}"
                participants.append(
                    SyntheticParticipant(
                        room_name=room_name,
                        identity=identity,
                        url=args.url,
                        token=token(key, secret, room_name, identity),
                        frequency=180 + index * 17,
                    )
                )

        ready: list[SyntheticParticipant] = []
        for offset in range(0, len(participants), args.connect_batch_size):
            batch = participants[offset : offset + args.connect_batch_size]
            connections = await asyncio.gather(
                *(participant.connect() for participant in batch),
                return_exceptions=True,
            )
            for participant, result in zip(batch, connections, strict=True):
                if isinstance(result, BaseException):
                    errors.append(
                        f"{participant.room_name}/{participant.identity}: {type(result).__name__}"
                    )
                else:
                    ready.append(participant)
            if offset + args.connect_batch_size < len(participants):
                await asyncio.sleep(args.connect_batch_delay)

        start = asyncio.Event()
        streams = [asyncio.create_task(item.stream(args.duration, start)) for item in ready]
        start.set()
        stream_results = await asyncio.gather(*streams, return_exceptions=True)
        for participant, result in zip(ready, stream_results, strict=True):
            if isinstance(result, BaseException):
                errors.append(
                    f"{participant.room_name}/{participant.identity} stream: {type(result).__name__}"
                )

        connect_times = [item.connect_seconds for item in ready]
        summary = {
            "rooms": args.rooms,
            "participantsPerRoom": args.participants,
            "attemptedConnections": len(participants),
            "successfulConnections": len(ready),
            "durationSeconds": args.duration,
            "connectBatchSize": args.connect_batch_size,
            "connectBatchDelaySeconds": args.connect_batch_delay,
            "connectP50Seconds": round(statistics.median(connect_times), 3)
            if connect_times
            else None,
            "connectP95Seconds": round(percentile(connect_times, 0.95), 3)
            if connect_times
            else None,
            "errors": errors,
            "modelCalls": 0,
        }
        if errors or len(ready) != len(participants):
            raise RuntimeError(json.dumps(summary))
        if percentile(connect_times, 0.95) >= args.max_connect_p95:
            raise RuntimeError(json.dumps(summary | {"failure": "connect p95 exceeded"}))
        return summary
    finally:
        await asyncio.gather(*(item.close() for item in participants), return_exceptions=True)
        if not args.keep_rooms:
            for room_name in room_names:
                try:
                    await server.room.delete_room(api.DeleteRoomRequest(room=room_name))
                except api.ServerError as exc:
                    if exc.code != api.ServerErrorCode.NOT_FOUND:
                        raise
        await server.aclose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.environ.get("LIVEKIT_URL", "ws://127.0.0.1:7880"))
    parser.add_argument("--rooms", type=int, default=5, choices=range(1, 6))
    parser.add_argument("--participants", type=int, default=10, choices=range(2, 11))
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--connect-batch-size", type=int, default=5)
    parser.add_argument("--connect-batch-delay", type=float, default=0.25)
    parser.add_argument("--max-connect-p95", type=float, default=5.0)
    parser.add_argument("--keep-rooms", action="store_true")
    args = parser.parse_args()
    if args.duration <= 0 or args.duration > 300:
        parser.error("duration must be between 0 and 300 seconds")
    if args.connect_batch_size <= 0 or args.connect_batch_size > 50:
        parser.error("connect batch size must be between 1 and 50")
    if args.connect_batch_delay < 0 or args.connect_batch_delay > 10:
        parser.error("connect batch delay must be between 0 and 10 seconds")
    return args


def main() -> None:
    args = parse_args()
    if os.environ.get("ROLECALL_LOAD_ALLOW") != "1":
        raise SystemExit("Set ROLECALL_LOAD_ALLOW=1 to authorize this synthetic transport load")
    print(json.dumps(asyncio.run(run(args)), indent=2))


if __name__ == "__main__":
    main()
