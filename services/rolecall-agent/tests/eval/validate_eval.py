"""Offline dataset/config validation and post-grade acceptance gate."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml
from agentplatform._genai.types import common

HERE = Path(__file__).resolve().parent
DATASET = HERE / "datasets" / "basic-dataset.json"
CONFIG = HERE / "eval_config.yaml"
EU_LOCAL_CONFIG = HERE / "eval_config.eu-local.yaml"
REQUIRED_METRICS = {
    "multi_turn_task_success",
    "multi_turn_tool_use_quality",
    "multi_turn_trajectory_quality",
    "hallucination",
    "instruction_following",
    "safety",
    "rolecall_quality",
    "rolecall_deterministic_invariants",
}
QUALITY_METRICS = REQUIRED_METRICS - {"rolecall_deterministic_invariants"}
EU_LOCAL_METRICS = {
    f"eu_{name}" if name not in {"rolecall_quality", "rolecall_deterministic_invariants"} else name
    for name in REQUIRED_METRICS
}
REQUIRED_CASE_PATTERNS = {
    "previous commitment": r"previous_commitment",
    "absent participant": r"absent",
    "late participant": r"late",
    "brainstorm clustering": r"diverge_cluster_materialize",
    "unsupported claim": r"unsupported_claim",
    "custom instructions": r"custom_role",
    "timing": r"timing",
    "floor": r"floor",
    "isolation": r"isolation",
}


def _fixture(case: dict[str, Any]) -> dict[str, Any]:
    turns = (case.get("agent_data") or {}).get("turns") or []
    for turn in turns:
        for event in turn.get("events") or []:
            state = event.get("state_delta") or event.get("stateDelta") or {}
            if isinstance(state.get("rolecallEval"), dict):
                return state["rolecallEval"]
    return {}


def validate_dataset() -> list[str]:
    payload = json.loads(DATASET.read_text(encoding="utf-8"))
    cases = payload.get("eval_cases") or []
    if len(cases) < 10:
        raise ValueError("Phase 1 evaluation requires at least ten cases")
    ids = [case.get("eval_case_id") for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Evaluation case IDs must be unique")

    roles: set[str] = set()
    for case in cases:
        common.EvalCase.model_validate(case)
        case_id = str(case.get("eval_case_id"))
        if case.get("prompt"):
            raise ValueError(f"{case_id}: use N+1 agent_data, not a top-level prompt")
        turns = (case.get("agent_data") or {}).get("turns") or []
        events = [event for turn in turns for event in (turn.get("events") or [])]
        if len(events) < 3 or events[-1].get("author") != "user":
            raise ValueError(f"{case_id}: trace must contain context and end with a user event")
        if not case.get("reference") or "rolecall" not in (case.get("rubric_groups") or {}):
            raise ValueError(f"{case_id}: reference and rolecall rubric group are required")
        fixture = _fixture(case)
        meeting = fixture.get("meetingState") or {}
        if fixture.get("scenarioId") != case_id or not fixture.get("expectedTools"):
            raise ValueError(f"{case_id}: scenario state and expected tools are required")
        roles.add(str(meeting.get("role")))
        participants = meeting.get("participants") or []
        if not 2 <= len(participants) <= 10:
            raise ValueError(f"{case_id}: participant count is outside Phase 1 limits")
        if any(not re.fullmatch(r"seat-[0-9]+", str(item.get("slotId"))) for item in participants):
            raise ValueError(f"{case_id}: participant identity must use stable seat IDs")

    expected_roles = {"SCRUM_MASTER", "FUN_FRIDAY", "BRAINSTORM", "CUSTOM"}
    if roles != expected_roles:
        raise ValueError(f"Role coverage mismatch: {sorted(roles)}")
    joined = "\n".join(str(item) for item in ids)
    missing = [
        label for label, pattern in REQUIRED_CASE_PATTERNS.items() if not re.search(pattern, joined)
    ]
    if missing:
        raise ValueError(f"Missing scenario coverage: {', '.join(missing)}")
    return [str(item) for item in ids]


def _validate_config(path: Path, required_metrics: set[str]) -> None:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    metrics = set(config.get("metrics_to_run") or [])
    if metrics != required_metrics:
        raise ValueError(
            f"{path.name} metric coverage mismatch: {sorted(metrics ^ required_metrics)}"
        )
    custom = {item.get("name"): item for item in config.get("custom_metrics") or []}
    custom_required = (
        required_metrics
        if path == EU_LOCAL_CONFIG
        else {"rolecall_quality", "rolecall_deterministic_invariants"}
    )
    for name in custom_required:
        item = custom.get(name) or {}
        path = HERE / str(item.get("custom_function_file", ""))
        if item.get("execution") != "local" or not path.is_file():
            raise ValueError(f"{name} must be a local file-backed metric")


def validate_config() -> None:
    _validate_config(CONFIG, REQUIRED_METRICS)
    _validate_config(EU_LOCAL_CONFIG, EU_LOCAL_METRICS)


def validate_results(path: Path, minimum: float) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = payload.get("summary_metrics") or payload.get("summaryMetrics") or []
    rows = {}
    for row in summary:
        name = str(row.get("metric_name") or row.get("metricName") or "").lower()
        name = re.sub(r"_v[0-9]+$", "", name)
        name = name.removeprefix("eu_")
        rows[name] = row
    missing = REQUIRED_METRICS - set(rows)
    if missing:
        raise ValueError(f"Grade output is missing metrics: {sorted(missing)}")
    for name in QUALITY_METRICS:
        row = rows[name]
        score = row.get("mean_score", row.get("meanScore"))
        if score is None or float(score) < minimum:
            raise ValueError(f"{name} score {score!r} is below {minimum:.2f}")
        if int(row.get("num_cases_error", row.get("numCasesError", 0)) or 0):
            raise ValueError(f"{name} contains evaluation errors")
    invariant = rows["rolecall_deterministic_invariants"]
    score = invariant.get("mean_score", invariant.get("meanScore"))
    pass_rate = invariant.get("pass_rate", invariant.get("passRate", score))
    if pass_rate is None:
        pass_rate = score
    if float(score or 0) != 1.0 or float(pass_rate or 0) != 1.0:
        raise ValueError("Deterministic authorization/isolation failures must be zero")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path)
    parser.add_argument("--minimum", type=float, default=0.8)
    args = parser.parse_args()
    case_ids = validate_dataset()
    validate_config()
    if args.results:
        validate_results(args.results, args.minimum)
    print(f"validated {len(case_ids)} Phase 1 eval cases and {len(REQUIRED_METRICS)} metrics")


if __name__ == "__main__":
    main()
