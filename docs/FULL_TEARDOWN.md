# Full teardown and recreation runbook

`scripts/full-environment.sh` is the irreversible, near-zero-idle-cost lifecycle
tool for the RoleCallAI development environment. It is pinned by the ignored
`.rolecall.local.env` to project `proofroom-506314`, `europe-west4`, and named
Firestore database `rolecall-dev`.

## Sleep or destroy

| Goal | Command | Data/endpoints |
| --- | --- | --- |
| Pause voice use | `make runtime-down` | Preserves the app, rooms, links, documents, history, IPs and credentials. |
| Remove RoleCallAI | `make environment-destroy` | Permanently deletes Terraform-managed RoleCallAI resources and data. |

Use sleep for normal cost control. Destroy only when losing all RoleCallAI data
and creating new endpoints/credentials later is acceptable.

## Deletion boundary

The destroy workflow removes:

- the named `rolecall-dev` Firestore database, including admin sessions, rooms,
  participant capability digests/ciphertexts, documents/chunks/vectors,
  transcripts, recaps and runtime state;
- the private document bucket and immutable originals;
- the Agent Platform Memory Bank;
- the GKE cluster, ephemeral Redis, node pools, LiveKit/ADK workloads,
  load balancers, reserved IPs, certificates, VPC, subnet, NAT and firewalls;
- Cloud Run web/jobs services and both runtime Jobs;
- Pub/Sub event/dead-letter topics, subscriptions and all three Scheduler jobs;
- the reCAPTCHA key, Cloud KMS seat-link key, four Secret Manager secrets and
  all RoleCallAI service accounts/IAM bindings;
- the Artifact Registry repository and application images;
- RoleCallAI Monitoring dashboards, alerts and log-based metrics.

The workflow verifies that the unrelated `(default)` Firestore database still
exists at its configured location. It intentionally leaves project APIs enabled,
Google-managed service identities, historical Logging/Build records and the
shared Cloud Build staging bucket. Those may be shared with other workloads and
can retain small historical storage costs.

Recreation cannot recover deleted data. It generates new login credentials,
participant capabilities, KMS/Secret versions, Memory Bank identity, IPs and
`sslip.io` endpoints.

## Prerequisites

```bash
cp .rolecall.local.env.example .rolecall.local.env
gcloud auth login
gcloud auth application-default login
make environment-status
```

- Run from this repository with its current private Terraform state.
- Never commit `.rolecall.local.env`, Terraform state, saved plans or generated
  credentials.
- Do not run Terraform, sleep/wake or another lifecycle command concurrently.
- Never run create while status is `PARTIAL`; finish destroy first.

## Destroy

Preview every mutation first:

```bash
./scripts/full-environment.sh destroy --dry-run
```

Then run the guarded operation:

```bash
make environment-destroy
```

The interactive confirmation is:

```text
DELETE rolecall-dev FROM proofroom-506314
```

For controlled non-interactive use:

```bash
./scripts/full-environment.sh destroy \
  --confirm-token delete-proofroom-506314-rolecall-dev
```

The script refuses active occurrences or pending outbox work, freezes the three
Scheduler jobs, applies a narrowly scoped Terraform override for protected
Firestore/KMS/Secret/GCS resources, creates a saved destroy plan, requests a
second count-aware confirmation, applies it, and then requires an empty managed
state. It also records the deletion time for Firestore's database-ID reuse
window. Allow roughly 20–40 minutes.

## Recreate

```bash
./scripts/full-environment.sh create --dry-run
make environment-create
```

The interactive confirmation is:

```text
CREATE rolecall-dev IN proofroom-506314
```

Creation runs tests and linters, bootstraps APIs/build identity/repository,
builds all three images with Cloud Build, honors the Firestore reuse delay,
applies a saved Terraform plan, verifies the `(default)` database is untouched,
and checks Cloud Run plus the voice plane. It then creates the admin secret
container, but the plaintext shared credential must still be generated from a
trusted terminal with `scripts/rotate-admin-credentials.py`.

After a clean recreation, migrate/create rooms and use `make runtime-down` to
return the voice plane to `SLEEPING`. Allow roughly 30–60 minutes for the full
create path.

## Interrupted operations

Before destructive apply starts, the script restores scheduler state and
deletion protections on failure. After Terraform has begun deleting, inspect
and converge the destroy instead of trying to restore partial resources:

```bash
make environment-status
./scripts/full-environment.sh destroy --dry-run
make environment-destroy
```

Create is convergent and may be rerun after correcting the reported problem.

References: [manage Firestore databases](https://cloud.google.com/firestore/docs/manage-databases),
[Terraform Firestore database](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/firestore_database),
and [delete a GKE cluster](https://cloud.google.com/kubernetes-engine/docs/how-to/deleting-a-cluster).

The Lyria lobby MP3 is a versioned repository asset, not cloud product data.
Teardown removes its deployed copies with Cloud Run/Artifact Registry but not
the source asset in Git; recreation never calls Lyria.
