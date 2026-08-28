"""Deterministic target selection for a missed model floor handoff."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Protocol


class AttendanceLike(Protocol):
    display_name: str
    connected: bool


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def select_recovery_slot(
    turn_order: Sequence[str],
    attendance: Mapping[str, AttendanceLike],
    next_floor_slot_id: str | None,
    last_agent_caption: str,
) -> tuple[str | None, str]:
    """Select the intended connected seat, with deterministic fallbacks.

    A server-prepared ``nextFloorSlotId`` is authoritative. When the model
    spoke a participant's name but omitted ``give_floor``, use the last named
    connected participant. Otherwise preserve the configured turn order.
    """

    connected = [
        slot_id for slot_id in turn_order if slot_id in attendance and attendance[slot_id].connected
    ]
    if next_floor_slot_id in connected:
        return next_floor_slot_id, "prepared_next_floor"

    normalized_caption = _normalized(last_agent_caption)
    latest_match: tuple[int, str] | None = None
    for slot_id in connected:
        name = _normalized(attendance[slot_id].display_name).strip()
        if not name:
            continue
        matches = list(re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", normalized_caption))
        if matches and (latest_match is None or matches[-1].start() > latest_match[0]):
            latest_match = (matches[-1].start(), slot_id)
    if latest_match is not None:
        return latest_match[1], "last_named_participant"
    if connected:
        return connected[0], "turn_order"
    return None, "no_connected_participant"
