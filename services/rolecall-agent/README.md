# RoleCallAI agent and control plane

This Python package contains the FastAPI control plane, deterministic meeting
controller, Google ADK 2.x facilitator, LiveKit RTC worker, post-processing jobs,
and post-meeting memory workflow for RoleCallAI Phase 1.

All configured cloud processing uses the locally supplied project and is pinned
to `europe-west4`. Firestore access rejects `(default)` and targets the named
database `rolecall-dev`.

## Local setup

```bash
uv sync --all-extras --dev
uv run uvicorn app.fast_api_app:app --reload --port 8000
```

The default repository is in-memory. Local LiveKit/Redis dependencies are
defined in the monorepo `docker-compose.yml`.

## Verification

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest tests/unit tests/integration
uv run python tests/eval/validate_eval.py
```

Cloud Memory Bank acceptance and model-based agent evaluation are opt-in and
must run only after the deployment approval gate. See
`tests/eval/datasets/README.md` for the exact regional commands.

The repository's Lyria generator is an offline maintenance tool, not an ADK
runtime dependency. Its dry-run and cost-boundary tests are in the unit suite;
the generated MP3 is served by React and never enters the RTC audio bridge.

## Runtime entry points

- `app.fast_api_app:app`: same-origin SPA/API control plane.
- `app.job_api:app`: OIDC-authenticated post-processing, cleanup, and
  outbox endpoints.
- `python -m app.worker`: one-meeting-per-process LiveKit RTC/ADK worker.
- `app.agent:root_agent`: regional text evaluation agent used by `agents-cli`.

The live worker persists finalized transcript text only. Raw audio remains in
bounded memory, LiveKit egress is disabled, and GenAI message-content capture
must remain disabled.

## Deployment gate

Do not run `agents-cli deploy`, Cloud Build, image push, API enablement, or
Terraform apply from this package without reviewing the generated Terraform
plan, resource inventory, and cost estimate and obtaining explicit owner
approval.
