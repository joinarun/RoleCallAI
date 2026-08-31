# Development sleep, wake and operations

RoleCallAI automatically suspends its expensive voice plane after 30 minutes
without genuine UI or meeting activity. The Cloud Run web/bootstrap service
remains addressable at the existing `run.app` URL and scales to zero between
requests. Room management and document indexing still work while voice sleeps.
The currently deployed revisions and acceptance evidence are recorded in
[DEPLOYMENT.md](DEPLOYMENT.md).

## Normal admin workflow

1. Open the home page and sign in with the shared judge credential.
2. Complete the reCAPTCHA checkbox. Five failures per IP or twenty per network
   prefix in ten minutes are throttled in Firestore.
3. If the runtime card says `SLEEPING`, click **Wake voice services**.
4. Wait for `READY` before sharing or using participant links. Provisioning
   normally takes 10–20 minutes.
5. Create/edit rooms and upload documents. Indexing does not wake GKE.
6. After all meetings finish, leave the application idle. The five-minute
   scheduler check starts a guarded suspension after 30 idle minutes.

Participants cannot wake the runtime. A valid seat link receives the typed
`runtime_asleep` response until an admin wakes it.

Lobby music does not wake or keep the runtime alive. It is a static same-origin
MP3 played only after a successful participant join; passive playback does not
write activity. See [LYRIA.md](LYRIA.md).

## Conservative READY profile

The hackathon profile keeps the same models, audio path, worker limits, two warm
workers and autoscaling ceilings while reducing the minimum compute shape:

- one `e2-standard-2` LiveKit media node;
- two `e2-standard-2` platform/worker nodes;
- two workers requested at 250m CPU and 2 GiB each, with unchanged 2 vCPU and
  4 GiB limits;
- Cloud Run control at 1 vCPU / 1 GiB and async jobs at 1 vCPU / 4 GiB.

This is 6 vCPU and 24 GiB across the normal three-node GKE shape. HPA and node
pool maxima remain six workers, three media nodes and six worker nodes. A
rolling update can temporarily add nodes or pods; evaluate cost only after both
autoscalers settle.

## Runtime states

| State | Meaning |
| --- | --- |
| `SLEEPING` | Joins blocked; zero GKE nodes/pods; LiveKit/TURN services absent. |
| `WAKING` | Nodes, Redis, ingress, certificates, LiveKit and workers are being restored. |
| `READY` | End-to-end health passed and participant joins are enabled. |
| `SUSPENDING` | New joins blocked while the voice plane safely scales down. |
| `ERROR` | A transition failed; the dashboard shows progress/error and permits an admin retry. |

The state and transition timestamps are durable in named Firestore. Runtime
operations are idempotent, single-task Cloud Run Jobs. The suspend job refuses
to proceed while an occurrence is in `LOBBY`, `STARTING`, `RUNNING`, `ENDING`,
or `PROCESSING`.

## What sleeps

- both GKE pools resize to zero after autoscaling is disabled;
- LiveKit, two ADK workers, ephemeral Redis, ingress and cert-manager scale to
  zero;
- LiveKit signaling and TURN Services are switched to internal `ClusterIP`
  services, which deprovisions their load balancers while retaining both
  reserved public IP addresses;
- participant joins remain blocked until the next wake passes end-to-end health.

## What remains

| Resource | Why it remains | Idle behavior |
| --- | --- | --- |
| Cloud Run web/control | Login, dashboard and the Wake button must stay addressable. | Min zero; billed only while serving requests. |
| Cloud Run async API and Jobs | Document/retention tasks and transitions. | Min zero / no task while idle. |
| GKE zonal control plane | Preserves cluster configuration for 10–20 minute wake. | $0.10/cluster-hour before the billing-account zonal GKE credit. |
| Reserved IPs | Keeps disposable `sslip.io` names stable. | Reserved-but-unused IPv4 pricing applies while sleeping. |
| Firestore/GCS/Artifact Registry | Preserves rooms, sessions, documents, vectors and images. | Storage and operation based. |
| Secret Manager/KMS | Preserves login, cookies, LiveKit credentials and seat-link recovery. | Small key/secret storage plus operations. |
| Scheduler/Pub/Sub/Monitoring | Idle checks, retention and operational visibility. | Low-volume operation based. |

There is no managed Memorystore instance. Redis is a one-replica, ephemeral
in-cluster pod and therefore has no separate idle charge.

## Local operator fallback

The same guarded lifecycle can be invoked from the repository when the UI/job
path is unavailable:

```bash
cp .rolecall.local.env.example .rolecall.local.env
gcloud auth login
gcloud auth application-default login

make runtime-status
./scripts/dev-runtime.sh down --dry-run --yes
make runtime-down
make runtime-up
```

`dev-runtime.sh` starts the corresponding Cloud Run Job and waits for the
durable runtime state. It does not disable the web service, document pipeline,
or Pub/Sub. It temporarily pauses only the idle-check Scheduler around a manual
transition and always resumes it afterward, preventing an automatic duplicate
operation. Operations are safe to retry after interruption.

The suspend job independently verifies that each node pool has zero Ready nodes
after GKE accepts the resize. It retries the resize once on a delayed drain and
does not finalize `SLEEPING` if the observed pool state remains nonzero.

For planned GKE/Terraform maintenance that may exceed a few minutes, pause
`rolecall-dev-runtime-idle-check` before the apply and resume it immediately
afterward. This prevents the five-minute idle check from launching suspension
while nodes are rolling. Never leave the Scheduler job paused after maintenance.

For a local emergency path that directly writes the guarded operation request,
use `scripts/runtime-operation.py`; it is pinned to `rolecall-dev` and rejects
an active meeting before suspension.

## Credentials and participant links

Generate or rotate the single shared credential only from a trusted terminal:

```bash
uv run --project services/rolecall-agent \
  python scripts/rotate-admin-credentials.py \
  --project proofroom-506314 \
  --database rolecall-dev \
  --secret projects/proofroom-506314/secrets/rolecall-dev-admin-credentials
```

The command prints the random username and 24-character password once and
stores only the username, Argon2id hash and credential version in regional
Secret Manager. Rotation revokes all admin sessions. Never redirect the output
into the repository, shell history, CI logs or chat.

Participant links are credentials too. The dashboard decrypts them only after
an explicit request; responses are `no-store`. Regeneration revokes the prior
link and active participant sessions.

## Document operations

Accepted files are PDF, DOCX, PPTX, TXT and Markdown. Limits are 25 MB/file,
20 active files, 200 MB/room, 500 pages/slides and one million extracted
characters. Scanned/encrypted PDFs, macros, mismatched signatures and files
without extractable text are rejected. Document changes are disabled during an
active meeting. A failed replacement leaves the previous ready version active.

Originals, chunks/vectors and metadata expire after 90 days. Participants see
sanitized excerpts and citation chips, never the original download.

## Full teardown

For permanent deletion rather than sleep, use the separately guarded
[full teardown and recreation runbook](FULL_TEARDOWN.md). Full teardown loses
rooms, links, documents, transcripts, recaps and credentials.

References: [Cloud Run autoscaling](https://docs.cloud.google.com/run/docs/about-instance-autoscaling),
[GKE cluster autoscaler behavior](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/cluster-autoscaler),
and [GKE resize](https://docs.cloud.google.com/sdk/gcloud/reference/container/clusters/resize).
