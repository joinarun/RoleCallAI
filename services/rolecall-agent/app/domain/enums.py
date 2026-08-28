"""Stable public and persisted RoleCallAI enums."""

from enum import StrEnum


class RoleType(StrEnum):
    SCRUM_MASTER = "SCRUM_MASTER"
    FUN_FRIDAY = "FUN_FRIDAY"
    BRAINSTORM = "BRAINSTORM"
    SPRINT_RETROSPECTIVE = "SPRINT_RETROSPECTIVE"
    PROJECT_STATUS = "PROJECT_STATUS"
    INCIDENT_RESPONSE = "INCIDENT_RESPONSE"
    COURSE_INSTRUCTOR = "COURSE_INSTRUCTOR"
    WORKSHOP_FACILITATOR = "WORKSHOP_FACILITATOR"
    TECHNICAL_INTERVIEWER = "TECHNICAL_INTERVIEWER"
    PRODUCT_DISCOVERY = "PRODUCT_DISCOVERY"
    DECISION_MAKING = "DECISION_MAKING"
    TOWN_HALL = "TOWN_HALL"
    CUSTOM = "CUSTOM"


class GameType(StrEnum):
    AUTO = "AUTO"
    RAPID_FIRE_TRIVIA = "RAPID_FIRE_TRIVIA"
    WOULD_YOU_RATHER = "WOULD_YOU_RATHER"
    CATEGORIES = "CATEGORIES"


class OccurrenceStatus(StrEnum):
    LOBBY = "LOBBY"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    ENDING = "ENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    @property
    def active(self) -> bool:
        return self in {
            self.LOBBY,
            self.STARTING,
            self.RUNNING,
            self.ENDING,
            self.PROCESSING,
        }


class OutcomeKind(StrEnum):
    DECISION = "DECISION"
    ACTION = "ACTION"
    BLOCKER = "BLOCKER"
    IDEA = "IDEA"
    COMMITMENT = "COMMITMENT"
    GAME_RESULT = "GAME_RESULT"


class CapabilityKind(StrEnum):
    ADMIN = "ADMIN"
    SEAT = "SEAT"


class FloorOwnerType(StrEnum):
    AGENT = "AGENT"
    SEAT = "SEAT"
    NONE = "NONE"
