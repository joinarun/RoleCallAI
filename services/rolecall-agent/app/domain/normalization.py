"""Canonical user-input normalization."""

import re
import unicodedata

_SPACE_RUN = re.compile(r"\s+")


def normalize_room_name(value: str) -> str:
    """Return an NFKC/casefold key used for uniqueness checks."""
    display = _SPACE_RUN.sub(" ", unicodedata.normalize("NFKC", value).strip())
    return display.casefold()


def clean_display_text(value: str, *, max_length: int) -> str:
    """Normalize spacing while retaining Unicode display characters."""
    cleaned = _SPACE_RUN.sub(" ", unicodedata.normalize("NFKC", value).strip())
    if not cleaned:
        raise ValueError("value cannot be blank")
    if len(cleaned) > max_length:
        raise ValueError(f"value must be at most {max_length} characters")
    return cleaned
