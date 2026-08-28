# RoleCallAI

RoleCallAI is a browser-based, voice-only meeting room led by a configurable Google ADK agent. The deterministic meeting controller owns the clock, lifecycle, turn order, and LiveKit publish permissions; Gemini supplies the facilitator's language and judgment.

The UI provides twelve built-in facilitator roles plus Custom, participant leave controls, admin/delegated end-for-everyone controls, and a remembered microphone check that is requested again only when browser access is unavailable.

This repository is the Phase 1 development monorepo. It contains:

- `apps/web` — React/Vite/TypeScript admin and participant UI.
- `services/rolecall-agent` — FastAPI control plane, ADK live agent, LiveKit RTC worker, postprocessor, and cleanup worker.
- `infra/terraform` — Google Cloud development infrastructure for `europe-west4`.
- `infra/kubernetes` — LiveKit and worker Kubernetes configuration used by Terraform/Helm.
- `apps/web/e2e` and `scripts/load` — browser and synthetic-media acceptance harnesses.

## Local development

Prerequisites: Node.js 22+, `uv`, Docker, and (for full voice testing) a local LiveKit server.

```bash
make install
make dev-api
make dev-web
```

The API defaults to an in-memory repository in local mode. Set `ROLECALL_REPOSITORY=firestore` and run the Firestore emulator for persistence-oriented integration tests. See [.env.example](.env.example).

```bash
make test
make lint
make build
make test-e2e
make eval-validate
```

`npm run capture:previews` in `apps/web` captures reproducible desktop and mobile UI previews while the local API and Vite server are running. The real LiveKit browser test is opt-in with `npm run test:e2e:live` because it starts Redis and LiveKit through Docker.

## Deployment boundary

Terraform targets the Google Cloud project supplied in the ignored
`infra/terraform/vars/dev.tfvars`, region `europe-west4`, and named Firestore
database `rolecall-dev`. It does not reference the existing `(default)`
Firestore database.

Do not run `terraform apply` or deploy images without explicit approval after reviewing the generated plan, resource inventory, and cost estimate. The repository deliberately has no remote, CI/CD pipeline, or production environment.

## Development deployment

Copy the sanitized configuration templates before planning or operating a cloud
environment. Both destination files are ignored by Git:

```bash
cp infra/terraform/vars/dev.tfvars.example infra/terraform/vars/dev.tfvars
cp .rolecall.local.env.example .rolecall.local.env
```

Set the project, ACME contact, and generated deployment endpoints locally. The
current run-rate model is in
[`infra/terraform/COST_ESTIMATE.md`](infra/terraform/COST_ESTIMATE.md).

Project diagrams and the cost-saving runtime controls are documented here:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Google services, topology,
  node counts, pod counts, and scale limits.
- [`docs/FLOW.md`](docs/FLOW.md) — normal room and meeting sequence.
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — guarded suspend/resume runbook.
- [`docs/FULL_TEARDOWN.md`](docs/FULL_TEARDOWN.md) — permanent teardown and
  complete recreation runbook.

```bash
make runtime-status
./scripts/dev-runtime.sh down --dry-run --yes
make runtime-down
make runtime-up
```

For a near-zero-cost, irreversible teardown of the RoleCallAI environment, use
the separately guarded full-environment workflow. It deletes all Terraform-managed
RoleCallAI resources and data, while preserving the project's unrelated
`(default)` Firestore database:

```bash
make environment-status
./scripts/full-environment.sh destroy --dry-run
make environment-destroy
make environment-create
```

Read [`docs/FULL_TEARDOWN.md`](docs/FULL_TEARDOWN.md) before running either
mutating command. Destroyed rooms, links, history, and memory cannot be restored
by `environment-create`.

## Security and privacy defaults

- Capability tokens live in URL fragments and are exchanged for Secure, HttpOnly cookies.
- Only SHA-256 capability digests are persisted.
- Raw meeting audio is memory-only and LiveKit egress is disabled.
- Final transcript segments, recaps, and curated meeting memory expire after 90 days.
- Phase 1 has no document upload or RAG feature.
- GenAI message-content telemetry is disabled.
