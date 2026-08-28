# RoleCallAI Phase 1 evaluation

`basic-dataset.json` is the default `agents-cli` N+1 dataset. Its nineteen
multi-turn cases cover all twelve built-in roles plus Custom, stable-seat memory, absent and late
participants, floor and timing control, brainstorm clustering and materialization,
unsupported claims, and secret/cross-room isolation.

## Offline validation

This command parses every case with the Agent Platform SDK, checks scenario and
role coverage, validates both metric configurations, and performs no model or
cloud call:

```bash
uv run python tests/eval/validate_eval.py
```

The evaluation root agent uses `gemini-3.7-flash` and state-backed versions of
the eight production meeting tools. The deployed live worker continues to use
`gemini-live-2.5-flash-native-audio` and real controller-scoped tools.

## Post-approval evaluation

Do not run these commands before cloud/model-use approval. First start the
loopback-only eval adapter. It works around agents-cli 1.4's loss of N+1 event
state while allowing only the checked-in `rolecallEval` fixture into initial
session state:

```bash
uv run uvicorn tests.eval.eval_api:app --host 127.0.0.1 --port 18081
```

In a second terminal, generate traces with application state pinned to
`europe-west4` and Gemini 3.7 inference pinned to the EU multi-region endpoint:

```bash
GOOGLE_CLOUD_PROJECT=your-gcp-project-id \
GOOGLE_CLOUD_LOCATION=europe-west4 \
ROLECALL_SUMMARY_MODEL_LOCATION=eu \
agents-cli eval generate \
  --url http://127.0.0.1:18081 \
  --app-name app \
  --dataset tests/eval/datasets/basic-dataset.json \
  --output artifacts/traces/
```

First try managed metrics in Europe—never omit `--region`:

```bash
agents-cli eval grade \
  --traces artifacts/traces/ \
  --output artifacts/grade_results/ \
  --config tests/eval/eval_config.yaml \
  --project your-gcp-project-id \
  --region europe-west4
```

If a managed metric is unavailable in `europe-west4`, do not retry globally.
Use the local metric configuration; it calls `gemini-3.7-flash` explicitly on
the `eu` endpoint and caches one typed, multi-component verdict per case:

```bash
GOOGLE_CLOUD_PROJECT=your-gcp-project-id \
GOOGLE_CLOUD_LOCATION=europe-west4 \
ROLECALL_SUMMARY_MODEL_LOCATION=eu \
agents-cli eval grade \
  --traces artifacts/traces/ \
  --output artifacts/grade_results-eu-local/ \
  --config tests/eval/eval_config.eu-local.yaml
```

Finally gate the JSON result. Every normalized quality metric must be at least
0.8, and deterministic authorization/isolation must have a 1.0 mean and pass
rate:

```bash
uv run python tests/eval/validate_eval.py \
  --results artifacts/grade_results/results_TIMESTAMP.json
```

The short deployed native-audio smoke test remains separate because the text
eval runner cannot measure WebRTC latency, interruption, or audio quality.
