from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.agent import app, build_live_agent, root_agent
from app.config import Settings
from app.domain.enums import RoleType
from app.domain.models import Occurrence, Room
from app.jobs.postprocessor import summary_agent


def test_model_endpoints_are_explicit_and_eu_scoped() -> None:
    room = Room(
        id="room-model-endpoints",
        name="Endpoint test",
        normalized_name="endpoint test",
        expected_participants=2,
        duration_minutes=5,
        role=RoleType.SCRUM_MASTER,
        agent_name="Nova",
        instructions="",
        admin_capability_digest="digest",
        slots=[],
    )
    occurrence = Occurrence(
        id="occurrence-model-endpoints",
        room_id=room.id,
        number=1,
        lobby_deadline_at=datetime.now(UTC),
    )
    live_agent = build_live_agent(room, occurrence)

    assert live_agent.model.client_kwargs["location"] == "europe-west4"
    assert root_agent.model.client_kwargs["location"] == "eu"
    assert summary_agent.model.client_kwargs["location"] == "eu"
    assert app.name == "app"


def test_summary_model_cannot_be_routed_outside_eu() -> None:
    with pytest.raises(ValidationError):
        Settings(summary_model_location="global")  # type: ignore[arg-type]
