"""Environment-backed RoleCallAI configuration."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
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

    participant_cookie_name: str = "rolecall_participant_session"
    admin_cookie_name: str = "rolecall_admin_session"
    cookie_signing_key: SecretStr = SecretStr("local-development-key-change-me-32-bytes")
    cookie_secure: bool = False
    capability_session_minutes: int = 60
    admin_session_hours: int = 8
    admin_owner_id: str = "shared-demo-admin"
    admin_credentials_secret: str | None = None
    local_admin_username: str = "judge-local"
    local_admin_password: SecretStr = SecretStr("local-rolecall-admin-password")
    recaptcha_site_key: str = "local-recaptcha-site-key"
    recaptcha_action: str = "admin_login"
    recaptcha_allowed_hostnames: str = "localhost,127.0.0.1"
    recaptcha_min_score: float = 0.5
    recaptcha_bypass: bool = True
    admin_login_ip_limit: int = 5
    admin_login_prefix_limit: int = 20
    admin_login_window_minutes: int = 10
    livekit_token_minutes: int = 10

    seat_link_kms_key: str | None = None

    livekit_url: str = "ws://localhost:7880"
    livekit_api_key: SecretStr = SecretStr("replace-with-local-livekit-api-key")
    livekit_api_secret: SecretStr = SecretStr("replace-with-local-livekit-secret-at-least-32-bytes")

    live_model: str = "gemini-live-2.5-flash-native-audio"
    summary_model: str = "gemini-3.7-flash"
    summary_model_location: Literal["eu"] = "eu"
    agent_engine_id: str | None = None

    documents_bucket: str = ""
    document_index_topic: str = "rolecall-document-index"
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768
    document_max_bytes: int = 25 * 1024 * 1024
    document_max_files_per_room: int = 20
    document_max_room_bytes: int = 200 * 1024 * 1024
    document_max_pages: int = 500
    document_max_characters: int = 1_000_000
    document_chunk_tokens: int = 800
    document_chunk_overlap_tokens: int = 120
    document_retrieval_limit: int = 5
    document_retrieval_max_distance: float = 0.45
    document_malware_scan_command: str = "clamdscan --no-summary"
    document_malware_scan_required: bool = False

    retention_days: int = 90
    lobby_early_start_seconds: int = 120
    disconnect_hold_seconds: int = 30
    agent_recovery_seconds: int = 60
    agent_response_watchdog_seconds: int = 6
    agent_handoff_watchdog_seconds: int = 3
    human_turn_silence_ms: int = 2000
    wrap_up_seconds: int = 120
    closing_grace_seconds: int = 60
    closing_playout_timeout_seconds: int = 45
    processing_timeout_minutes: int = 60

    room_create_rate_per_hour: int = 5
    document_upload_rate_per_hour: int = 20
    capability_failure_rate_per_minute: int = 20

    postprocess_topic: str = "rolecall-postprocess"
    cleanup_topic: str = "rolecall-cleanup"
    immediate_outbox_publish: bool = False
    pubsub_audience: str | None = None
    pubsub_invoker_email: str | None = None
    scheduler_invoker_email: str | None = None
    runtime_wake_job: str = "rolecall-runtime-wake"
    runtime_suspend_job: str = "rolecall-runtime-suspend"
    runtime_inactivity_minutes: int = 30
    runtime_activity_debounce_seconds: int = 60
    runtime_default_status: Literal["SLEEPING", "READY"] = "READY"
    runtime_control_topic: str = "rolecall-runtime-control"
    gke_cluster: str = "rolecall-dev"
    gke_zone: str = "europe-west4-a"
    gke_media_pool: str = "media"
    gke_worker_pool: str = "workers"
    runtime_media_min_nodes: int = 1
    runtime_media_max_nodes: int = 3
    runtime_worker_min_nodes: int = 2
    runtime_worker_max_nodes: int = 6
    livekit_signaling_ip: str = ""
    livekit_turn_ip: str = ""

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

    @field_validator("recaptcha_min_score")
    @classmethod
    def validate_recaptcha_score(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("reCAPTCHA minimum score must be between zero and one")
        return value

    @field_validator("embedding_dimensions")
    @classmethod
    def validate_embedding_dimensions(cls, value: int) -> int:
        if not 1 <= value <= 2048:
            raise ValueError("embedding dimensions must be supported by Firestore")
        return value

    @model_validator(mode="after")
    def forbid_production_captcha_bypass(self) -> Settings:
        if self.env in {"dev", "prod"} and self.recaptcha_bypass:
            raise ValueError("reCAPTCHA bypass is forbidden outside local/test environments")
        if self.env in {"dev", "prod"} and not self.admin_credentials_secret:
            raise ValueError("admin credential Secret Manager resource is required")
        if self.env in {"dev", "prod"} and not self.seat_link_kms_key:
            raise ValueError("seat link KMS key is required")
        if self.env in {"dev", "prod"} and not self.document_malware_scan_required:
            raise ValueError("document malware scanning is required outside local/test")
        return self

    @property
    def cookie_name(self) -> str:
        """Compatibility alias for participant-only capability code."""
        return self.participant_cookie_name


@lru_cache
def get_settings() -> Settings:
    return Settings()
