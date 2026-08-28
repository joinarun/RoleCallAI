"""ADK live-session configuration with no audio/blob persistence."""

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types

from app.config import get_settings


def live_run_config() -> RunConfig:
    settings = get_settings()
    return RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=[types.Modality.AUDIO],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                prefix_padding_ms=300,
                silence_duration_ms=settings.human_turn_silence_ms,
            ),
            activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
            turn_coverage=types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
        ),
        session_resumption=types.SessionResumptionConfig(),
        context_window_compression=types.ContextWindowCompressionConfig(
            trigger_tokens=25000,
            sliding_window=types.SlidingWindow(target_tokens=12000),
        ),
        save_input_blobs_as_artifacts=False,
        save_live_blob=False,
        save_live_audio=False,
    )
