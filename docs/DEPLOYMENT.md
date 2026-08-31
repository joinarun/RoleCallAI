# Development deployment status

Last verified: **2026-08-31**

RoleCallAI is deployed in Google Cloud project `proofroom-506314`. Application
processing and product data use `europe-west4`; the voice cluster is zonal in
`europe-west4-a`. The application uses only the named Firestore Native database
`rolecall-dev` and does not access the project's unrelated `(default)` database.

## Current release

| Component | Deployed release |
| --- | --- |
| Web/control plane | Cloud Run revision `rolecall-dev-control-00019-rnl`; 1 vCPU / 1 GiB limit; existing application image |
| Async/index/post-process API | Cloud Run revision `rolecall-dev-jobs-00019-r2s`; 1 vCPU / 4 GiB limit; existing application image |
| ADK voice worker | Artifact Registry tag `secure-rag-sleep-20260831-fix3` |
| Sleep/wake lifecycle jobs | Artifact Registry jobs tag `hackathon-rightsize-runtime-20260831` |
| Public application | `https://rolecall-dev-control-2502669067.europe-west4.run.app/` |
| Repository release record | GitHub `main`, including the conservative hackathon sizing release |

The executable images include the secure-admin, Firestore-vector RAG,
KMS-backed participant-link recovery, deterministic floor controller and
automatic runtime sleep/wake implementation. Commits after the image build add
only deployed acceptance harnesses and this release documentation, so another
container rollout is unnecessary until application or infrastructure source
changes.

## Current runtime shape

The environment is deliberately returned to `SLEEPING` after acceptance:

- durable runtime generation `11`, progress `100`, with no transition error;
- GKE media and worker managed instance groups both have target size `0`;
- LiveKit, Redis, ADK workers, cert-manager and both ingress controllers have
  zero replicas;
- signaling and TURN are internal `ClusterIP` services with no public
  load-balancer addresses;
- Cloud Run web/control remains addressable with minimum instances set to zero;
- Firestore, Cloud Storage, Artifact Registry, Secret Manager, KMS, Scheduler,
  Pub/Sub, reserved IPs and the GKE control plane remain provisioned.

Use the authenticated dashboard's **Wake voice services** button before a
meeting. The measured acceptance wake completed in 52.88 seconds, but the UI
conservatively asks administrators to allow 10–20 minutes. Participants cannot
wake the runtime.

When `READY`, the conservative profile uses one `e2-standard-2` media node and
two `e2-standard-2` worker nodes: 6 vCPU and 24 GiB total. Two ADK workers stay
warm with a 250m CPU request, 2 GiB memory request and unchanged 2 vCPU / 4 GiB
limits. Node pools may temporarily surge during a rolling update and converge
after the HPA and cluster-autoscaler stabilization windows.

## Migration result

- 10 existing rooms assigned to owner `shared-demo-admin`;
- 22 participant capabilities rotated, SHA-256 digested and KMS encrypted;
- all legacy admin capability digests removed;
- 10 legacy capability sessions revoked;
- fresh participant links available only through explicit authenticated
  dashboard requests with `Cache-Control: no-store`.

Previous management and participant links no longer authorize access.

## Acceptance evidence

| Area | Result |
| --- | --- |
| Backend | 88 tests passed; 2 intentionally skipped |
| Web | 7 tests passed; ESLint, TypeScript and production build passed |
| Terraform | Formatting and validation passed; reviewed plans applied with 0 creates and 0 destroys |
| Authentication | Unauthenticated admin APIs return 401; Argon2id sessions, CSRF, throttling, reCAPTCHA configuration and credential rotation passed |
| Voice | Reduced-hardware Gemini Live smoke heard both speakers, answered after participant two and spoke an eight-sentence closing; recap processing completed in 18.45 seconds |
| Sleep/wake | A deployed wake produced exactly 1 media + 2 worker nodes; the following suspend observed both pools at zero before committing generation 11 to `SLEEPING` |
| Meeting controls | Participant leave, delegated end-for-everyone and administrator end passed |
| Documents/RAG | Real upload, extraction, embedding and same-room/same-version vector retrieval passed; cross-room and wrong-version retrieval returned zero results |
| Memory/evaluation | 22 multi-turn cases and 8 EU-local metrics completed with no evaluator errors and a 1.0 mean for every metric |
| Sleep/wake | End-to-end wake passed; automatic suspend reached zero nodes and removed public media load balancers |
| Sleeping boundary | A valid participant reached the lobby but received `runtime_asleep`, created no occurrence and did not wake the runtime |
| Security | No deployed credentials, JWTs, cookies, document excerpts, personal email addresses or real capability tokens were found in tracked source or sampled Cloud logs |

The managed evaluation run also exceeded the required 0.8 quality threshold,
but four managed-judge capacity errors occurred. The prescribed evaluator using
the EU model endpoint was therefore used for the error-free final result.

The five-room/ten-publisher transport harness connected and streamed all 50
publishers on the reduced media node, which remained below 25% CPU in sampled
measurements. Its best full-run connection p95 was 5.79 seconds and therefore
did not meet the separate 5-second join-latency gate. Further runs from one Mac
and one public network became limited by LiveKit SDK ping/ICE timeouts while the
server remained lightly loaded. Treat this as capacity evidence, not a clean
latency acceptance; rerun the latency gate from distributed regional load
generators before claiming the five-room SLA.

The lifecycle manager does not trust a completed GKE resize operation by
itself. It waits for each node pool to have zero Ready Kubernetes nodes and
performs one bounded resize retry before allowing durable state to become
`SLEEPING`.

## Release process

This development environment intentionally uses custom Terraform and manual
Cloud Build. LiveKit requires GKE Standard host networking and public media
nodes, so the generic private/Autopilot scaffold is not compatible.

For the next application change:

1. run backend tests, web lint/typecheck/tests/build and agent evaluation;
2. build immutable control, jobs and worker images in Cloud Build;
3. run `terraform fmt`, `terraform validate` and review a saved Terraform plan;
4. confirm there is no active occurrence before applying runtime changes;
5. pause the idle Scheduler job during a long GKE maintenance apply, then resume
   it immediately afterward so auto-suspend cannot race the node rollout;
6. apply only after explicit approval, then run deployed UI, voice, RAG and
   sleeping-runtime acceptance checks;
7. return the environment to `SLEEPING` when verification finishes;
8. commit documentation and push the release record to GitHub.

When the runtime is sleeping, Terraform intentionally observes reversible drift
for zeroed Kubernetes workloads, deprovisioned media services and disabled
node-pool autoscaling. Wake the runtime before preparing a normal convergence
plan.

Related documents: [architecture](ARCHITECTURE.md), [normal flow](FLOW.md),
[operations](OPERATIONS.md), [cost estimate](../infra/terraform/COST_ESTIMATE.md)
and [full teardown](FULL_TEARDOWN.md).
