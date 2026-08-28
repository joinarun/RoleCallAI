"""One-meeting-per-process LiveKit RTC to Google ADK bridge."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta

from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.apps import App
from google.adk.runners import Runner
from google.genai import types
from livekit import rtc
from livekit.agents import AgentServer, AutoSubscribe, JobContext, cli

from app.agent import build_live_agent
from app.agent_tools import MeetingToolScope, bind_meeting_scope
from app.app_utils import services as adk_services
from app.config import get_settings
from app.domain.enums import FloorOwnerType
from app.domain.models import LiveKitMessage, TranscriptSegment
from app.live.adk_session import live_run_config
from app.live.audio import FloorAudioFrame, FloorAudioFramer
from app.observability import configure_observability
from app.retrieval.memory import RoomMemoryService
from app.services.livekit import LiveKitService
from app.services.meetings import MeetingService
from app.storage.factory import get_repository

logger = logging.getLogger("rolecall.worker")


def _exclusive_meeting_load(agent_server: AgentServer) -> float:
    """Advertise a pod as full once it owns a meeting job."""
    return 1.0 if agent_server.active_jobs else 0.0


server = AgentServer(
    num_idle_processes=1,
    load_fnc=_exclusive_meeting_load,
    load_threshold=0.5,
    prometheus_port=9090,
)


def _occurrence_id(ctx: JobContext) -> str:
    try:
        metadata = json.loads(ctx.job.metadata or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return str(metadata.get("occurrenceId") or ctx.room.name)


def _pcm_rate(mime_type: str | None, fallback: int = 24000) -> int:
    match = re.search(r"rate=(\d+)", mime_type or "")
    return int(match.group(1)) if match else fallback


@server.rtc_session(agent_name="rolecall-meeting")
async def meeting_entrypoint(ctx: JobContext) -> None:
    settings = get_settings()
    configure_observability(settings)
    repository = get_repository()
    occurrence_id = _occurrence_id(ctx)
    occurrence = repository.get_occurrence(occurrence_id)
    room = repository.get_room(occurrence.room_id)
    meetings = MeetingService(repository, settings)
    memory = RoomMemoryService(settings)
    livekit = LiveKitService(settings)
    tool_scope = MeetingToolScope(
        occurrence_id=occurrence_id,
        repository=repository,
        meetings=meetings,
        memory=memory,
    )

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    output_source = rtc.AudioSource(sample_rate=48000, num_channels=1, queue_size_ms=1000)
    output_track = rtc.LocalAudioTrack.create_audio_track("rolecall-agent", output_source)
    await ctx.room.local_participant.publish_track(
        output_track,
        rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
    )
    await ctx.room.local_participant.set_attributes(
        {"rolecall.role": "agent", "lk.agent.state": "connecting"}
    )

    request_queue = LiveRequestQueue()
    # Twenty-five model-ready 80 ms frames provide two seconds of bounded
    # jitter tolerance. Previously this queue held raw ~10 ms LiveKit chunks,
    # which left only ~250 ms and dropped speech during brief model stalls.
    input_frames: asyncio.Queue[FloorAudioFrame] = asyncio.Queue(maxsize=25)
    output_frames: asyncio.Queue[rtc.AudioFrame] = asyncio.Queue(maxsize=200)
    stream_tasks: set[asyncio.Task[None]] = set()
    stop = asyncio.Event()
    audio_frames_dropped = 0
    last_gap_log_at = datetime.min.replace(tzinfo=UTC)
    last_human_final_at: float | None = None
    last_human_audio_slot_id: str | None = None
    last_controller_heartbeat = time.monotonic()
    audio_stream_open = False
    # The controller refreshes this snapshot at 2 Hz. Audio callbacks must not
    # perform synchronous Firestore reads: LiveKit can deliver ~100 raw chunks
    # per second, and those network reads previously starved the queue before a
    # later participant's turn.
    floor_snapshot = (
        occurrence.current_floor_type,
        occurrence.current_floor_slot_id,
        occurrence.floor_epoch,
    )

    async def publish_message(message_type: str, payload: dict[str, object]) -> None:
        current = await asyncio.to_thread(repository.get_occurrence, occurrence_id)
        message = LiveKitMessage(
            type=message_type,
            occurrence_id=occurrence_id,
            sequence=current.sequence,
            payload=payload,
        )
        await ctx.room.local_participant.publish_data(
            message.model_dump_json(by_alias=True), reliable=True, topic="rolecall.v1"
        )

    async def consume_track(track: rtc.Track, participant: rtc.RemoteParticipant) -> None:
        nonlocal audio_frames_dropped, last_gap_log_at
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        stream = rtc.AudioStream(track)
        resamplers: dict[int, rtc.AudioResampler] = {}
        framer = FloorAudioFramer(sample_rate=16000, frame_ms=80)
        async for event in stream:
            floor_type, floor_slot_id, floor_epoch = floor_snapshot
            expected_identity = (
                f"seat:{floor_slot_id}"
                if floor_type == FloorOwnerType.SEAT and floor_slot_id
                else ""
            )
            if participant.identity != expected_identity:
                framer.clear()
                continue
            frame = event.frame
            resampler = resamplers.setdefault(
                frame.sample_rate,
                rtc.AudioResampler(input_rate=frame.sample_rate, output_rate=16000, num_channels=1),
            )
            for converted in resampler.push(frame):
                data = bytes(converted.data)
                for scoped_frame in framer.push(floor_slot_id or "", floor_epoch, data):
                    if input_frames.full():
                        audio_frames_dropped += 1
                        try:
                            input_frames.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        now = datetime.now(UTC)
                        if now - last_gap_log_at >= timedelta(seconds=10):
                            logger.warning(
                                "event=audio_gap occurrence_id=%s dropped_frames=%d",
                                occurrence_id,
                                audio_frames_dropped,
                            )
                            last_gap_log_at = now
                            audio_frames_dropped = 0
                    input_frames.put_nowait(scoped_frame)

    def on_track_subscribed(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        del publication
        task = asyncio.create_task(consume_track(track, participant))
        stream_tasks.add(task)
        task.add_done_callback(stream_tasks.discard)

    def on_data_received(packet: rtc.DataPacket) -> None:
        if packet.topic != "rolecall.v1" or not packet.participant:
            return
        try:
            message = LiveKitMessage.model_validate_json(packet.data)
        except Exception:
            return
        if message.occurrence_id != occurrence_id or message.type != "hand.raise":
            return
        identity = packet.participant.identity
        if not identity.startswith("seat:"):
            return
        meetings.raise_hand(occurrence_id, identity.removeprefix("seat:"))

    ctx.room.on("track_subscribed", on_track_subscribed)
    ctx.room.on("data_received", on_data_received)
    for participant in ctx.room.remote_participants.values():
        for publication in participant.track_publications.values():
            if publication.track:
                on_track_subscribed(publication.track, publication, participant)

    async def send_audio_upstream() -> None:
        nonlocal audio_stream_open, last_human_audio_slot_id
        while not stop.is_set():
            try:
                scoped_frame = await asyncio.wait_for(input_frames.get(), timeout=1.05)
            except TimeoutError:
                if audio_stream_open:
                    # Gemini's automatic VAD expects AudioStreamEnd whenever
                    # microphone input pauses for about a second. It flushes
                    # cached speech and still permits later audio to resume.
                    request_queue.send_audio_stream_end()
                    audio_stream_open = False
                continue
            floor_type, floor_slot_id, floor_epoch = floor_snapshot
            if (
                floor_type != FloorOwnerType.SEAT
                or floor_slot_id != scoped_frame.slot_id
                or floor_epoch != scoped_frame.floor_epoch
            ):
                continue
            request_queue.send_realtime(
                types.Blob(mime_type="audio/pcm;rate=16000", data=scoped_frame.data)
            )
            last_human_audio_slot_id = scoped_frame.slot_id
            audio_stream_open = True

    async def send_audio_downstream() -> None:
        """Keep real-time LiveKit playout from blocking Gemini event intake."""
        while not stop.is_set():
            frame = await output_frames.get()
            await output_source.capture_frame(frame)

    async def persist_caption(
        speaker_type: FloorOwnerType, speaker_id: str, speaker_name: str, text: str
    ) -> None:
        nonlocal last_human_final_at
        existing_segments = await asyncio.to_thread(
            repository.list_transcript_segments, occurrence_id
        )
        sequence = len(existing_segments) + 1
        now = datetime.now(UTC)
        segment = TranscriptSegment(
            id=f"{occurrence_id}:segment:{sequence}",
            occurrence_id=occurrence_id,
            sequence=sequence,
            speaker_type=speaker_type,
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            text=" ".join(text.split()),
            started_at=now,
            ended_at=now,
            expires_at=now + timedelta(days=settings.retention_days),
        )
        await asyncio.to_thread(repository.save_transcript_segment, segment)
        await publish_message("caption.final", segment.model_dump(mode="json"))
        if speaker_type == FloorOwnerType.SEAT:
            last_human_final_at = time.perf_counter()

    async def run_adk() -> None:
        nonlocal last_human_final_at
        live_agent = build_live_agent(room, occurrence)
        adk_app = App(root_agent=live_agent, name="rolecall_ai")
        runner = Runner(
            app=adk_app,
            session_service=adk_services.get_session_service(),
            memory_service=memory._get_service(),
            auto_create_session=True,
        )
        request_queue.send_content(
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        text=(
                            "Begin the meeting now. Read authoritative state, welcome present "
                            "participants by name, and facilitate according to the configured role."
                        )
                    )
                ],
            )
        )
        input_buffer = ""
        output_buffer = ""
        failure_started: datetime | None = None
        while not stop.is_set():
            try:
                with bind_meeting_scope(tool_scope):
                    async for event in runner.run_live(
                        user_id=room.id,
                        session_id=occurrence_id,
                        live_request_queue=request_queue,
                        run_config=live_run_config(),
                    ):
                        failure_started = None
                        if event.input_transcription and event.input_transcription.text:
                            input_buffer += event.input_transcription.text
                            if event.input_transcription.finished and input_buffer.strip():
                                current = repository.get_occurrence(occurrence_id)
                                slot_id = (
                                    last_human_audio_slot_id
                                    or current.current_floor_slot_id
                                    or "unknown"
                                )
                                attendance = current.attendance.get(slot_id)
                                await persist_caption(
                                    FloorOwnerType.SEAT,
                                    slot_id,
                                    attendance.display_name if attendance else "Participant",
                                    input_buffer,
                                )
                                input_buffer = ""
                        if event.output_transcription and event.output_transcription.text:
                            output_buffer += event.output_transcription.text
                            if event.output_transcription.finished and output_buffer.strip():
                                await persist_caption(
                                    FloorOwnerType.AGENT, "agent", room.agent_name, output_buffer
                                )
                                output_buffer = ""
                        if event.interrupted:
                            output_source.clear_queue()
                            while not output_frames.empty():
                                try:
                                    output_frames.get_nowait()
                                except asyncio.QueueEmpty:
                                    break
                        for part in (
                            event.content.parts if event.content and event.content.parts else []
                        ):
                            blob = part.inline_data
                            if (
                                not blob
                                or not blob.data
                                or not (blob.mime_type or "").startswith("audio/")
                            ):
                                continue
                            if last_human_final_at is not None:
                                logger.info(
                                    "event=agent_audio_latency occurrence_id=%s latency_ms=%.1f",
                                    occurrence_id,
                                    (time.perf_counter() - last_human_final_at) * 1000,
                                )
                                last_human_final_at = None
                            source_rate = _pcm_rate(blob.mime_type)
                            frame = rtc.AudioFrame(
                                blob.data,
                                sample_rate=source_rate,
                                num_channels=1,
                                samples_per_channel=len(blob.data) // 2,
                            )
                            resampler = rtc.AudioResampler(
                                input_rate=source_rate, output_rate=48000, num_channels=1
                            )
                            for converted in [*resampler.push(frame), *resampler.flush()]:
                                await output_frames.put(converted)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "event=model_reconnect occurrence_id=%s error_type=%s",
                    occurrence_id,
                    type(exc).__name__,
                )
                failure_started = failure_started or datetime.now(UTC)
                if datetime.now(UTC) - failure_started >= timedelta(
                    seconds=settings.agent_recovery_seconds
                ):
                    meetings.finish(occurrence_id, "agent_recovery_timeout")
                    stop.set()
                    return
                await asyncio.sleep(2)

    async def controller_loop() -> None:
        nonlocal audio_stream_open, floor_snapshot, last_controller_heartbeat
        last_sequence = -1
        last_floor_epoch = -1
        while not stop.is_set():
            current = await asyncio.to_thread(meetings.tick, occurrence_id)
            heartbeat_at = time.monotonic()
            if heartbeat_at - last_controller_heartbeat >= 15:
                current = await asyncio.to_thread(meetings.mark_agent_seen, occurrence_id)
                last_controller_heartbeat = heartbeat_at
            floor_snapshot = (
                current.current_floor_type,
                current.current_floor_slot_id,
                current.floor_epoch,
            )
            if current.sequence != last_sequence:
                last_sequence = current.sequence
                if current.floor_epoch != last_floor_epoch:
                    last_floor_epoch = current.floor_epoch
                    while not input_frames.empty():
                        try:
                            input_frames.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    if audio_stream_open and current.current_floor_type != FloorOwnerType.SEAT:
                        request_queue.send_audio_stream_end()
                        audio_stream_open = False
                await livekit.enforce_floor(current)
                await publish_message("meeting.state", current.model_dump(mode="json"))
            if not current.status.active or current.status.value == "PROCESSING":
                stop.set()
                return
            await asyncio.sleep(0.5)

    tasks = {
        asyncio.create_task(send_audio_upstream(), name="rolecall-audio-upstream"),
        asyncio.create_task(send_audio_downstream(), name="rolecall-audio-downstream"),
        asyncio.create_task(run_adk(), name="rolecall-adk-live"),
        asyncio.create_task(controller_loop(), name="rolecall-controller"),
    }
    results: list[object] = []
    await ctx.room.local_participant.set_attributes({"lk.agent.state": "listening"})
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop.set()
        request_queue.close()
        for task in tasks:
            if not task.done():
                task.cancel()
        results = list(await asyncio.gather(*tasks, return_exceptions=True))
        for task in stream_tasks:
            task.cancel()
        await asyncio.gather(*stream_tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, asyncio.CancelledError):
            continue
        if isinstance(result, BaseException):
            raise result


if __name__ == "__main__":
    cli.run_app(server)
