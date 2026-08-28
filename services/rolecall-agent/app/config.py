"""Environment-backed RoleCallAI configuration."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings shared by API, workers, and jobs."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_prefix="ROLECALL_",
        case_sensitive=False,
        extra="ignore",
    )

    env: Literal["local", "test", "dev", "prod"] = "local"
    public_base_url: str = "http://localhost:5173"
    repository: Literal["memory", "firestore"] = "memory"
    project_id: str = "local-dev-project"
    region: str = "europe-west4"
    firestore_database: str = "rolecall-dev"
    redis_url: str = "redis://localhost:6379/0"

    cookie_name: str = "rolecall_session"
    cookie_signing_key: SecretStr = SecretStr("local-development-key-change-me-32-bytes")
    cookie_secure: bool = False
    capability_session_minutes: int = 60
    livekit_token_minutes: int = 10

    livekit_url: str = "ws://localhost:7880"
    livekit_api_key: SecretStr = SecretStr("replace-with-local-livekit-api-key")
    livekit_api_secret: SecretStr = SecretStr("replace-with-local-livekit-secret-at-least-32-bytes")

    live_model: str = "gemini-live-2.5-flash-native-audio"
    summary_model: str = "gemini-3.7-flash"
    summary_model_location: Literal["eu"] = "eu"
    agent_engine_id: str | None = None

    retention_days: int = 90
    lobby_early_start_seconds: int = 120
    disconnect_hold_seconds: int = 30
    agent_recovery_seconds: int = 60
    agent_response_watchdog_seconds: int = 6
    human_turn_silence_ms: int = 2000
    wrap_up_seconds: int = 120
    closing_grace_seconds: int = 60
    closing_playout_timeout_seconds: int = 45
    processing_timeout_minutes: int = 60

    room_create_rate_per_hour: int = 5
    capability_failure_rate_per_minute: int = 20

    postprocess_topic: str = "rolecall-postprocess"
    cleanup_topic: str = "rolecall-cleanup"
    immediate_outbox_publish: bool = False
    pubsub_audience: str | None = None
    pubsub_invoker_email: str | None = None
    scheduler_invoker_email: str | None = None

    @field_validator("firestore_database")
    @classmethod
    def forbid_default_firestore(cls, value: str) -> str:
        """Prevent accidental reads or writes to the pre-existing default database."""
        if value == "(default)":
            raise ValueError("RoleCallAI must use the named rolecall-dev database")
        return value

    @field_validator("cookie_signing_key")
    @classmethod
    def validate_cookie_key(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("cookie signing key must be at least 32 characters")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
