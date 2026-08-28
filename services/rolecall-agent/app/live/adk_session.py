"""ADK live-session configuration with no audio/blob persistence."""

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types


def live_run_config() -> RunConfig:
    return RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=[types.Modality.AUDIO],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        session_resumption=types.SessionResumptionConfig(),
        context_window_compression=types.ContextWindowCompressionConfig(
            trigger_tokens=25000,
            sliding_window=types.SlidingWindow(target_tokens=12000),
        ),
        save_input_blobs_as_artifacts=False,
        save_live_blob=False,
        save_live_audio=False,
    )
