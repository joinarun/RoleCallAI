# RoleCallAI development cost estimate

Estimate date: **2026-08-27**. Currency: **USD list price**, before tax,
contract discounts, credits other than the explicitly noted GKE free-tier
credit, and internet data transfer. A month is modeled as 730 hours.

This is a planning estimate, not a billing quote. Actual Gemini Live charges
depend on the usage metadata returned by each session because Live API context
is reprocessed on every turn.

## Executive estimate

| Development state | Estimated monthly cost |
| --- | ---: |
| Fully destroyed with `scripts/full-environment.sh destroy` | **Approximately $0 RoleCallAI fixed runtime**; shared historical storage/operations may remain |
| Suspended with `scripts/dev-runtime.sh down` | **$59–$132** plus low-volume usage |
| Deployed at minimum size | **$407–$480** |
| Active dev month: 100 30-minute meetings | **$580–$653** |
| Autoscaling ceiling held for an entire month, before usage | **$1,104–$1,177** |

The range is the GKE management fee: a zonal Standard cluster costs $73 for a
730-hour month, but Google provides $74.40/month of billing-account-level credit
for one zonal Standard or Autopilot cluster. If another eligible cluster has
already consumed that credit, use the upper value.

The guarded suspend command removes public control access, pauses schedulers,
and scales both GKE node pools to zero without deleting data. Its estimate
retains Redis, load balancers/reserved IPs, the GKE control plane, Firestore,
networking, and low-volume managed-service storage. See
[`docs/OPERATIONS.md`](../../docs/OPERATIONS.md) for the exact boundary and
resume procedure.

The full-environment destroy command removes all Terraform-managed RoleCallAI
compute, databases, network resources, images, secrets, and public endpoints.
It intentionally leaves enabled shared project APIs, Google-managed service
identities, historical logs/build records, and the shared Cloud Build staging
bucket, so tiny storage or historical-data charges outside the RoleCallAI
runtime may remain. See
[`docs/FULL_TEARDOWN.md`](../../docs/FULL_TEARDOWN.md).

Deployment status: the GKE cluster and its minimum three nodes are running, so
the fixed infrastructure run rate is already accruing. Cloud Build and the EU
model evaluation also incurred small one-time usage charges during deployment.
All current nodes use GKE's standard logging profile; the max-throughput
profile's roughly 2-vCPU-per-node reservation is not present.

## Fixed infrastructure

Minimum topology is one media node plus two general worker nodes. The ceiling
is three media plus six general nodes. Both pools use `e2-standard-4` with a
50 GiB balanced persistent boot disk.

| Resource | Minimum calculation | Monthly |
| --- | --- | ---: |
| 3 × `e2-standard-4` | 3 × (4 × $0.02401338 vCPU-h + 16 × $0.003379068 GiB-h) × 730 | $328.76 |
| 3 × 50 GiB `pd-balanced` | 150 GiB × $0.11/GiB-month | $16.50 |
| Memorystore Redis Basic, 1 GiB | 1 GiB × $0.051/GiB-h × 730 | $37.23 |
| Regional forwarding rules | first five rules × $0.025/h × 730 | $18.25 |
| Public Cloud NAT, three assigned VMs, one IP | (3 × $0.0014/h + $0.005/h) × 730 | $6.72 |
| GKE management | $0.10/h × 730, less available billing-account credit | $0–$73.00 |
| **Minimum** |  | **$407.46–$480.46** |

Phase 1 no longer provisions document storage or Vertex AI RAG Engine.

At the configured nine-node ceiling, compute is $986.28, disks are $49.50, and
NAT fixed charges are about $12.85. Including Redis, load balancing, and the
possible GKE fee yields **$1,104.11–$1,177.11/month** before model,
traffic, storage, database-operation, and observability usage. Normal
autoscaling is billed only for the time additional nodes exist; this ceiling is
not the expected dev bill.

## Gemini and agent usage

### Live meetings

Current standard Gemini 2.5 Flash Live API prices are $3 per million input
audio tokens, $12 per million output audio tokens, $0.50 per million input text
tokens, and $2 per million output text tokens. Audio accumulates at about 25
tokens/second, and previous context is billed again on each turn.

The model below assumes:

- one model turn per meeting minute;
- human floor audio during 55% of elapsed time;
- agent output audio during 30%;
- a 6,000-token trusted prompt/tool context billed on each turn;
- context compression at 25,000 tokens to a 12,000-token sliding window, as
  configured by the worker;
- input and output transcription enabled.

| Meeting duration | Estimated Live API cost |
| --- | ---: |
| 5 minutes | $0.10 |
| 15 minutes | $0.59 |
| 30 minutes | $1.60 |
| 60 minutes | $3.47 |

Silence, handoff cadence, interruptions, tool traces, and compression timing can
move these values materially. Production cost reporting must aggregate the
session usage metadata instead of relying on this model.

### Post-processing and memory

- A representative 30-minute recap with 8,000 input and 1,200 output tokens is
  about **$0.012** using regional Gemini 3.7 Flash introductory pricing
  ($0.825/M input and $4.125/M output through 2026-12-31).
- Memory Bank and Sessions move to the current Agent Platform resource pricing
  on 2026-09-01: $0.30/GiB-month storage, $0.085 per three million reads, and
  $0.085 per one million writes, with generation/embedding model tokens billed
  separately. Phase 1 volumes should make operations and storage small; model
  generation is the larger component.

## Active development scenario

For 100 meetings/month at 30 minutes each:

| Variable component | Assumption | Monthly |
| --- | --- | ---: |
| Gemini Live | 100 × $1.60 | $160.00 |
| Gemini recap | 100 × $0.012 | $1.20 |
| Memory generation/embedding allowance | low-volume curated facts | $1.00 |
| Cloud Run, Firestore, Pub/Sub, Secret Manager, Artifact Registry/Cloud Build staging, network data, and observability allowance | low-volume dev use | $10.00 |
| **Usage subtotal** |  | **$172.20** |
| **Expected total** | fixed + usage | **$579.66–$652.66** |

The $10 allowance is deliberately not a guarantee. It assumes scale-to-zero
Cloud Run services, small transcripts, no large internet egress, and logs/metrics
within low-volume dev usage. Load tests, verbose metrics, or sustained node
scale-out should be estimated separately.

## Rate sources

- [Google Cloud SKU table](https://cloud.google.com/skus) — queried in USD on
  2026-08-27 for SKU `012A-5DBB-1352` (E2 core Netherlands),
  `B1BC-108E-2AD9` (E2 RAM Netherlands), `5CFD-16B2-4F41` (balanced PD),
  and `D9D3-B766-BB10` (Redis Basic M1).
- [GKE pricing](https://cloud.google.com/kubernetes-engine/pricing) — $0.10 per
  cluster-hour and the $74.40 billing-account monthly credit.
- [Cloud Load Balancing pricing](https://cloud.google.com/load-balancing/pricing)
  — first five regional forwarding rules at $0.025/hour and $0.008/GiB in each
  processing direction.
- [Cloud NAT pricing](https://cloud.google.com/nat/pricing) — per-assigned-VM,
  external-IP, and processed-GiB rates.
- [Gemini generative AI pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing)
  — Gemini Live, Gemini 3.7 Flash, and embedding rates.
- [Live API cost behavior](https://ai.google.dev/gemini-api/docs/live-api/best-practices)
  — audio accumulation, per-turn context rebilling, transcription surcharge,
  and context compression guidance.
- [Agent Platform pricing](https://cloud.google.com/products/gemini-enterprise-agent-platform/pricing)
  — Memory Bank and Sessions storage/operation rates and effective dates.
