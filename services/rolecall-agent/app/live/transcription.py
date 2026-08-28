"""Utilities for assembling incremental Gemini Live transcriptions."""

from __future__ import annotations


class TranscriptAccumulator:
    """Merge transcription deltas and cumulative snapshots without duplication.

    Gemini Live may emit either a new text delta or a complete snapshot of the
    text accumulated so far. Treating both forms as deltas duplicates captions,
    particularly when the final event repeats the full transcript.
    """

    def __init__(self) -> None:
        self._text = ""

    @property
    def text(self) -> str:
        return self._text

    def add(self, fragment: str | None) -> str:
        incoming = fragment or ""
        if not incoming:
            return self._text
        if not self._text:
            self._text = incoming
            return self._text
        if incoming == self._text or self._text.startswith(incoming):
            return self._text
        if incoming.startswith(self._text):
            self._text = incoming
            return self._text

        # Preserve genuine deltas while removing repeated overlap at chunk
        # boundaries. Require at least two characters so ordinary repeated
        # letters do not collapse words.
        overlap = 0
        limit = min(len(self._text), len(incoming))
        for size in range(limit, 1, -1):
            if self._text.endswith(incoming[:size]):
                overlap = size
                break
        remainder = incoming[overlap:]
        if not remainder:
            return self._text
        if self._text[-1].isspace() or remainder[0].isspace() or remainder[0] in ".,!?;:)]}'\"":
            self._text += remainder
        else:
            self._text += f" {remainder}"
        return self._text

    def finish(self) -> str:
        completed = " ".join(self._text.split())
        self._text = ""
        return completed
