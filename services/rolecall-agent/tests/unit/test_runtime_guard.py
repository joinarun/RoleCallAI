from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_guard_module():
    guard_path = Path(__file__).parents[4] / "scripts" / "runtime_guard.py"
    spec = importlib.util.spec_from_file_location("runtime_guard", guard_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime_guard = _load_guard_module()


def test_guard_allows_suspend_only_when_runtime_is_empty() -> None:
    result = runtime_guard.summarize_runtime({}, pending_outbox=0)

    assert result["safeToSuspend"] is True
    assert result["activeOccurrences"] == 0
    assert result["activeByStatus"] == {
        "LOBBY": 0,
        "STARTING": 0,
        "RUNNING": 0,
        "ENDING": 0,
        "PROCESSING": 0,
    }


@pytest.mark.parametrize(
    ("active_counts", "pending_outbox"),
    [({"RUNNING": 1}, 0), ({"PROCESSING": 2}, 0), ({}, 1)],
)
def test_guard_blocks_active_or_unpublished_work(
    active_counts: dict[str, int], pending_outbox: int
) -> None:
    result = runtime_guard.summarize_runtime(active_counts, pending_outbox)

    assert result["safeToSuspend"] is False


def test_guard_rejects_invalid_counts() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        runtime_guard.summarize_runtime({"RUNNING": -1}, pending_outbox=0)


def test_guard_refuses_default_firestore_database() -> None:
    with pytest.raises(ValueError, match="refuses to inspect the default"):
        runtime_guard.inspect_firestore("example-project", "(default)")
