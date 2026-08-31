# RoleCallAI development cost estimate

The deployed environment is currently kept in the automatically sleeping shape
described below. See [`docs/DEPLOYMENT.md`](../../docs/DEPLOYMENT.md) for the
verified zero-node and load-balancer state.

Estimate date: **2026-08-31**. Currency: **USD list price**, before tax,
contract discounts and internet data transfer. A month is modeled as 730 hours.
This is a planning estimate, not a billing quote.

## Executive estimate

| Development state | Estimated monthly cost |
| --- | ---: |
| Fully destroyed | Approximately **$0 RoleCallAI fixed runtime**; shared historical storage may remain |
| Automatically sleeping | **$11–$85** plus low-volume storage/operations |
| `READY` at minimum size for the entire month | **$206–$279** plus usage |
| 100 × 30-minute meetings while otherwise sleeping | Roughly **$173–$248** total, depending on wake hours and model use |
| Nine-node ceiling held for an entire month | **$574–$647** plus usage |

The range is the zonal GKE management fee. Google lists $0.10 per cluster-hour
($73 for 730 hours) and a $74.40 monthly billing-account credit for one eligible
zonal Standard or Autopilot cluster. If another cluster consumes that credit,
use the upper number. The credit does not cover node compute.

## Sleeping cost boundary

After 30 idle minutes RoleCallAI has zero GKE nodes, zero voice pods and no
LiveKit/TURN forwarding rules. Cloud Run stays min-zero. Approximate retained
monthly fixed costs are:

| Retained resource | Monthly planning amount |
| --- | ---: |
| Zonal GKE control plane | $0–$73.00 |
| 2 reserved, unused regional IPv4 addresses | $7.30 |
| Cloud NAT external IPv4 address | about $3.65 |
| 1 software KMS key version | $0.06 |
| 4 active Secret Manager versions | about $0.24 |
| **Sleeping fixed subtotal** | **$11.25–$84.25** |

Firestore, GCS, Artifact Registry, Scheduler, Pub/Sub, Cloud Run, Monitoring,
reCAPTCHA and KMS operations are usage/storage based and are not guaranteed to
be zero. At small hackathon volume they should be low, but retained documents,
large logs, repeated wake operations or heavy dashboard use increase the bill.
Named Firestore databases do not receive Firestore's free operation/storage
quota.

Google currently charges reserved external IPs even when not in use. Addresses
attached to forwarding rules have no separate address charge, which applies
only while the voice load balancers exist. reCAPTCHA Premium includes the first
10,000 assessments per month at no charge; usage from 10,001–100,000 is an $8
flat tier.

## Voice plane fixed infrastructure

Minimum `READY` topology is one media node plus two worker nodes. Both pools use
`e2-standard-2` with 50 GiB balanced boot disks. Redis is an ephemeral pod and
has no managed-service line item.

| Resource | Full-month minimum calculation | Monthly |
| --- | --- | ---: |
| 3 × `e2-standard-2` | Existing Netherlands SKU rates × 730 h | $164.38 |
| 3 × 50 GiB `pd-balanced` | 150 GiB × $0.11/GiB-month | $16.50 |
| 3 regional forwarding rules | first five × $0.025/h × 730 | $18.25 |
| Public Cloud NAT | 3 assigned VMs + one IP | $6.72 |
| GKE management | $0.10/h × 730, less available credit | $0–$73.00 |
| KMS and secrets | one key version + four secret versions | about $0.30 |
| **Running fixed minimum** |  | **$206.15–$279.15** |

At the nine-node ceiling, compute is about $493.14, disks $49.50, NAT fixed
charges $12.85 and forwarding rules $18.25. Including KMS/secrets and the
possible GKE fee gives **$574–$647/month** before AI, network, storage,
database-operation and observability usage. Autoscaling charges only while the
additional nodes exist.

## AI and document usage

### Voice meetings

The existing meeting model assumes standard Gemini 2.5 Flash Live rates, about
25 audio tokens/second and context rebilling on each turn. With one turn per
minute, 55% participant speech, 30% agent speech, and configured context
compression, planning values are:

| Meeting duration | Approximate Gemini Live cost |
| --- | ---: |
| 5 minutes | $0.10 |
| 15 minutes | $0.59 |
| 30 minutes | $1.60 |
| 60 minutes | $3.47 |

Actual session usage metadata is authoritative. Silence, interruptions, tool
traces and context compression can move these figures materially.

### Recaps, memory and RAG

- A representative 30-minute typed recap is approximately $0.012 using the
  configured EU summary model and the previously reviewed introductory rates.
- `gemini-embedding-001` online input is currently listed at $0.00015 per 1,000
  input tokens. Embedding five million document tokens would therefore be about
  $0.75; output embeddings have no separate model charge.
- Firestore vector search bills returned document reads plus one document read
  for each batch of up to 100 kNN vector index entries scanned. Storage includes
  vectors and vector indexes.
- A 5-result retrieval from a small room corpus is inexpensive, but the named
  database has no free quota and repeated retrieval still creates billable
  reads.
- GCS originals, Firestore chunks/vectors and document metadata have 90-day
  retention, limiting long-lived development storage.

## Example: 100 meetings

Assume 100 30-minute meetings, 50 hours of voice use, the runtime awake for 60
hours total during the month, five million newly embedded document tokens and
low-volume serverless/data use:

| Component | Approximate monthly amount |
| --- | ---: |
| Voice infrastructure for 60 hours | $18–$24, plus sleeping residual |
| Gemini Live | $160.00 |
| Gemini recaps | $1.20 |
| Document embeddings | $0.75 |
| Firestore/GCS/Cloud Run/Pub/Sub/Memory/observability allowance | $10.00 |

The resulting order-of-magnitude total is **$173–$248**, with most uncertainty
coming from the billing-account GKE credit, actual Live API context, how long the
runtime remains awake, data transfer and logs. Set a billing budget/alerts;
budgets notify but do not stop service consumption.

## Current primary pricing references

- [GKE pricing](https://cloud.google.com/kubernetes-engine/pricing)
- [VPC and external IPv4 pricing](https://cloud.google.com/vpc/network-pricing)
- [Firestore and vector-query pricing](https://cloud.google.com/firestore/pricing)
- [Vertex AI generative AI and embedding pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing)
- [reCAPTCHA billing](https://docs.cloud.google.com/recaptcha/docs/billing-information)
- [Cloud KMS pricing](https://cloud.google.com/kms/pricing)
- [Cloud Load Balancing pricing](https://cloud.google.com/load-balancing/pricing)
- [Cloud NAT pricing](https://cloud.google.com/nat/pricing)
