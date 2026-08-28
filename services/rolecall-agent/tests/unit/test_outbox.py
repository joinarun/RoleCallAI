from __future__ import annotations

from app.container import Container
from app.domain.enums import RoleType
from app.domain.models import RoomCreate
from app.jobs.outbox import drain_outbox


class Future:
    def result(self, timeout: float | None = None) -> str:
        assert timeout == 30
        return "message-1"


class Publisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bytes, dict[str, str]]] = []

    def topic_path(self, project: str, topic: str) -> str:
        return f"projects/{project}/topics/{topic}"

    def publish(self, topic: str, data: bytes, **attrs: str) -> Future:
        self.messages.append((topic, data, attrs))
        return Future()


def test_outbox_publishes_once_and_marks_record(container: Container) -> None:
    created = container.rooms.create(
        RoomCreate(
            name="Outbox room",
            expected_participants=2,
            duration_minutes=10,
            role=RoleType.SCRUM_MASTER,
            agent_name="Nova",
        )
    )
    container.rooms.delete(created.room.id)
    publisher = Publisher()
    assert drain_outbox(container, publisher) == {"published": 1, "failed": 0}
    assert len(publisher.messages) == 1
    assert drain_outbox(container, publisher) == {"published": 0, "failed": 0}
