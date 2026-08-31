# Deploy in your own Google Cloud project

This is a development/hackathon topology, not a turnkey production service.
Expect billable GKE control-plane, reserved-IP, storage, model, and network use
even though voice nodes sleep after 30 idle minutes.

## 1. Prerequisites

- A billed Google Cloud project where you can manage APIs, IAM, GKE, Cloud Run,
  Firestore, KMS, Secret Manager, reCAPTCHA, Pub/Sub, Storage, and Scheduler.
- Node.js 22+, `uv`, Docker, Google Cloud CLI, Terraform, `kubectl`, Helm, Make,
  Git, `rg`, and `ffprobe`.
- A monitored email address for ACME certificate expiry notices.
- No production data in a Firestore database named `rolecall-dev`.

Terraform creates a **named** Native Firestore database. It never imports,
modifies, or deletes `(default)`, and lifecycle wrappers verify that boundary.

## 2. Configure local, ignored inputs

```bash
git clone https://github.com/joinarun/RoleCallAI.git
cd RoleCallAI
cp infra/terraform/vars/dev.tfvars.example infra/terraform/vars/dev.tfvars
cp .rolecall.local.env.example .rolecall.local.env
```

Set your project, monitored ACME email, image tag, and generated endpoints in
those ignored files. Do not add them to Git.

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
make install
```

## 3. Verify before provisioning

```bash
make test
make lint
make build
make test-e2e
make eval-validate
make terraform-validate
make terraform-plan
./scripts/terraform-inventory.sh
```

Review the saved plan, generated resource inventory,
[cost estimate](../infra/terraform/COST_ESTIMATE.md), exact project, and named
database. Any variable, image tag, or Terraform change requires a fresh plan.

## 4. Create the environment

Preview the guarded orchestration:

```bash
./scripts/full-environment.sh create --dry-run
```

Then, with owner approval and the script's exact confirmation phrase:

```bash
make environment-create
```

The wrapper enables APIs, establishes build identity and Artifact Registry,
builds immutable control/jobs/worker images through Cloud Build, applies the
reviewed Terraform, waits for Firestore constraints, and verifies web/voice.
It does not create plaintext admin credentials.

## 5. Create the shared admin credential

Run from a trusted terminal. Save the one-time output in a password manager;
never redirect it to a file, CI log, issue, or chat.

```bash
uv run --project services/rolecall-agent \
  python scripts/rotate-admin-credentials.py \
  --project YOUR_PROJECT_ID \
  --database rolecall-dev \
  --secret projects/YOUR_PROJECT_ID/secrets/rolecall-dev-admin-credentials
```

Secret Manager receives only the username, Argon2id hash, and credential
version. Rotation invalidates all admin sessions.

## 6. Smoke-test and sleep

Use Terraform outputs for the Cloud Run URL and follow the hosted sequence in
[REPRODUCIBLE_TESTING.md](REPRODUCIBLE_TESTING.md), including one two-person
meeting. Then reduce cost:

```bash
make runtime-status
make runtime-down
```

`SLEEPING` means zero GKE nodes/pods and no public LiveKit/TURN load balancers,
not zero total Google Cloud cost. Restore with `make runtime-up` or the dashboard.

## 7. Music asset

No Lyria call is needed. The approved static MP3 and provenance are versioned.
If a maintainer intentionally replaces it, follow [LYRIA.md](LYRIA.md); Lyria 3
is global-only, so never place user data in the prompt.

## 8. Destruction

Never use raw `terraform destroy`. Use [FULL_TEARDOWN.md](FULL_TEARDOWN.md).
Destruction permanently removes rooms, links, documents, transcripts, recaps,
memory, and secrets.
