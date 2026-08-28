import json

from tests.eval.validate_eval import QUALITY_METRICS, validate_results


def test_gate_accepts_null_custom_metric_pass_rate_when_every_case_passed(tmp_path) -> None:
    summary = [
        {
            "metric_name": name,
            "mean_score": 0.9,
            "num_cases_error": 0,
        }
        for name in QUALITY_METRICS
    ]
    summary.append(
        {
            "metric_name": "rolecall_deterministic_invariants",
            "mean_score": 1.0,
            "pass_rate": None,
            "num_cases_error": 0,
        }
    )
    results = tmp_path / "results.json"
    results.write_text(json.dumps({"summary_metrics": summary}), encoding="utf-8")

    validate_results(results, 0.8)
