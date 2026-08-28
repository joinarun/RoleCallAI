from __future__ import annotations

from app.config import get_settings
from app.live.adk_session import live_run_config
from app.live.transcription import TranscriptAccumulator
from app.live.watchdog import AgentResponseWatchdog, WatchdogAction


def test_transcript_accumulator_merges_cumulative_and_delta_events() -> None:
    transcript = TranscriptAccumulator()
    transcript.add("I am working on billing.")
    transcript.add("I am working on billing.")
    assert transcript.finish() == "I am working on billing."

    transcript.add("I am working")
    transcript.add(" on billing")
    transcript.add("on billing and invoices.")
    assert transcript.finish() == "I am working on billing and invoices."


def test_transcript_accumulator_finishes_on_empty_final_event() -> None:
    transcript = TranscriptAccumulator()
    transcript.add("Complete response")
    transcript.add(None)
    assert transcript.finish() == "Complete response"
    assert transcript.finish() == ""


def test_live_vad_allows_a_normal_thinking_pause() -> None:
    config = live_run_config()
    detection = config.realtime_input_config.automatic_activity_detection
    assert detection.silence_duration_ms == get_settings().human_turn_silence_ms == 2000
    assert detection.end_of_speech_sensitivity.value == "END_SENSITIVITY_LOW"


def test_agent_response_watchdog_nudges_recovers_and_times_out() -> None:
    watchdog = AgentResponseWatchdog(6, 60, max_nudges=2)
    watchdog.observe_floor(True, 4, 100)
    assert watchdog.poll(105.9) is None
    first = watchdog.poll(106)
    assert first and first.action == WatchdogAction.NUDGE and first.attempt == 1
    assert watchdog.poll(111.9) is None
    second = watchdog.poll(112)
    assert second and second.action == WatchdogAction.NUDGE and second.attempt == 2
    assert watchdog.note_agent_audio() == 2
    assert watchdog.note_agent_audio() == 0
    assert watchdog.poll(200) is None

    watchdog.observe_floor(False, 5, 201)
    watchdog.observe_floor(True, 6, 202)
    timed_out = watchdog.poll(262)
    assert timed_out and timed_out.action == WatchdogAction.TIMEOUT
    assert watchdog.poll(300) is None
