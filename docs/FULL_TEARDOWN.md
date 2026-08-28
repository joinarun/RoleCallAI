# Full teardown and recreation runbook

`scripts/full-environment.sh` is the irreversible, near-zero-idle-cost lifecycle
tool for the RoleCallAI development environment. It is pinned to project
and endpoint coordinates in the ignored `.rolecall.local.env`, and to the named
Firestore database `rolecall-dev`.

## Choose suspend or destroy

| Goal | Command | Data and links | Endpoints | Expected residual RoleCallAI fixed cost |
| --- | --- | --- | --- | --- |
| Pause for a short period | `make runtime-down` | Preserved | Preserved | About $59–$132/month plus usage |
| Remove the environment | `make environment-destroy` | Permanently deleted | Deleted | Approximately $0; shared/history costs may remain |

Use suspend/resume when you expect to continue with the same rooms, links,
history, credentials, IPs, and hostnames. Use full teardown only when permanent
data loss and a later clean deployment are acceptable.

## Permanent deletion boundary

`environment-destroy` deletes every resource managed by this RoleCallAI
Terraform state, including:

- the `rolecall-dev` named Firestore database and all rooms, invite digests,
  attendance, transcripts, recaps, outcomes, and outbox records;
- Agent Platform Memory Bank data;
- Memorystore Redis and its transient capability/rate-limit state;
- the GKE cluster, node pools, LiveKit/worker pods, Kubernetes releases,
  load balancers, reserved addresses, certificates, VPC, subnet, NAT, and
  firewall rules;
- both Cloud Run services, Pub/Sub topics/subscriptions, Scheduler jobs,
  monitoring resources, Secret Manager secrets and versions;
- the RoleCallAI Artifact Registry repository and all three application images;
- RoleCallAI service accounts and Terraform-managed IAM bindings.

The script explicitly verifies and preserves the unrelated `(default)`
Firestore database in its configured expected location. It also leaves enabled project APIs,
Google-managed service identities, historical Cloud Logging/Cloud Build records,
and the project-wide Cloud Build source-staging bucket. Those are shared or
historical project resources, and removing them could affect workloads outside
RoleCallAI. APIs have no idle charge merely for being enabled, although retained
logs or staging objects can have small storage charges.

Recreation does not recover deleted data. It generates new secrets, Memory Bank
identity, reserved IPs, `sslip.io` hostnames, room capabilities, and participant
links.

## Prerequisites and safety rules

- Run from the repository that contains the current local Terraform state.
- Keep that state and `local-data/` private; saved plans can contain secrets.
- Authenticate `gcloud` and Application Default Credentials with an identity
  allowed to administer the project.
- Do not run this script, Terraform, `dev-runtime.sh`, or another deployment
  concurrently. The script uses an exact local operation lock and refuses a
  second teardown/recreate process from this workspace.
- Never run `create` while `status` reports `PARTIAL`. Finish teardown by
  rerunning `destroy` first.

Create the ignored local configuration from the sanitized template before the
first operation:

```bash
cp .rolecall.local.env.example .rolecall.local.env
```

```bash
gcloud auth login
gcloud auth application-default login
make environment-status
```

## Destroy

First run the read-only preview:

```bash
./scripts/full-environment.sh destroy --dry-run
```

The preview checks the project and `(default)` database, validates Terraform,
checks for active meetings and pending outbox work, and shows the protection
changes and destruction sequence without mutating Google Cloud.

Run the permanent teardown interactively:

```bash
make environment-destroy
```

The first prompt requires:

```text
DELETE rolecall-dev FROM your-gcp-project-id
```

After generating the saved destroy plan, the script asks for a second phrase
containing the current Terraform entry count. This prevents a stale assumption
about the deletion scope. For controlled non-interactive use, the equivalent is:

```bash
./scripts/full-environment.sh destroy \
  --confirm-token delete-your-gcp-project-id-rolecall-dev
```

The destroy sequence is:

1. Refuse deletion while any occurrence is active or outbox work is pending.
2. Remove public Cloud Run access and pause Scheduler, then repeat the guard.
3. Temporarily disable deletion protection on only `rolecall-dev` Firestore and
   the `rolecall-dev` GKE cluster.
4. Generate and apply a saved Terraform destroy plan.
5. Require an empty managed Terraform state, absence of the named database, and
   continued presence of the configured `(default)` database.
6. Save a local deletion timestamp used to honor Firestore's database-ID reuse
   delay during recreation.

Allow roughly 20–40 minutes. GKE, Redis, private service networking, and
Firestore deletion can account for most of that time.

## Create

Preview the clean-deployment sequence without changing Google Cloud:

```bash
./scripts/full-environment.sh create --dry-run
```

Then recreate the full billable environment:

```bash
make environment-create
```

The confirmation phrase is:

```text
CREATE rolecall-dev IN your-gcp-project-id
```

For controlled non-interactive use:

```bash
./scripts/full-environment.sh create \
  --confirm-token create-your-gcp-project-id-rolecall-dev
```

Creation runs all local unit tests and linters before spending money. It then:

1. bootstraps required APIs, the Cloud Build service account and IAM, and the
   empty Artifact Registry repository with a targeted Terraform apply;
2. builds and pushes the control, jobs, and worker images with Cloud Build;
3. waits for Firestore's database-ID reuse window if the destroy was recent;
4. creates and applies a saved full Terraform plan;
5. waits for LiveKit and worker rollouts and TLS certificates;
6. probes the Cloud Run readiness and LiveKit TLS endpoints, rechecks the
   `(default)` database, and requires a final no-change Terraform plan.

Allow roughly 30–60 minutes. Certificate issuance, GKE node provisioning, image
builds, and API propagation can extend this window. Use `make environment-status`
afterward; newly generated endpoint URLs are also printed by the script.

## Interrupted or failed operations

Before the destroy plan begins, an error automatically restores normal deletion
protections and any public/scheduler state the script froze. Once Terraform has
started destroying resources, automatic restoration would be unsafe. In that
case:

```bash
make environment-status
./scripts/full-environment.sh destroy --dry-run
make environment-destroy
```

Rerunning `destroy` is safe and converges the remaining Terraform resources to
zero. Do not run `create` until status is `DESTROYED`. Creation is also
convergent: if it fails after the bootstrap or partial apply, rerun
`make environment-create` after correcting the reported problem.

Google documents the named-database deletion/reuse behavior and GKE cluster
deletion semantics here:

- [Manage Firestore databases](https://cloud.google.com/firestore/docs/manage-databases)
- [Terraform Firestore database resource](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/firestore_database)
- [Delete a GKE cluster](https://cloud.google.com/kubernetes-engine/docs/how-to/deleting-a-cluster)
