# RoleCallAI secure development architecture

RoleCallAI runs in project `proofroom-506314`. Meeting processing and product
data remain in `europe-west4`; voice is zonal in `europe-west4-a`. The
application addresses named Firestore database `rolecall-dev`, never the
unrelated `(default)` database.

One transparent exception is separate from runtime: a developer sent one
fixed, non-personal prompt to global Lyria 3 Pro at build time. The resulting
MP3 is an immutable web asset. Lyria is not in the meeting path.

## System diagram

[Open the zoomable SVG export](diagrams/architecture.svg).

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"#070b22","primaryColor":"#151b3b","primaryTextColor":"#f7f7ff","primaryBorderColor":"#8077ff","lineColor":"#6be3bd","secondaryColor":"#101735","tertiaryColor":"#0b102b","clusterBkg":"#0b102b","clusterBorder":"#39406b","noteBkgColor":"#1b244d","noteTextColor":"#f7f7ff","noteBorderColor":"#ff8c86","actorBkg":"#151b3b","actorBorder":"#8077ff","actorTextColor":"#f7f7ff","signalColor":"#6be3bd","signalTextColor":"#dfe4ff","labelBoxBkgColor":"#101735","labelBoxBorderColor":"#8077ff","labelTextColor":"#f7f7ff","loopTextColor":"#f7f7ff"}}}%%
flowchart TB
    subgraph Build[One-time build-time media - global]
      DEV[Developer cost approval]
      LYRIA[Lyria 3 Pro Preview<br/>1 fixed prompt / 1 request]
      MP3[Static MP3 + provenance<br/>no user or meeting data]
      DEV --> LYRIA --> MP3
    end
    subgraph Users[Browsers]
      A[Admin]
      P[Participants<br/>2-10 per room]
    end
    subgraph GCP[Google Cloud runtime and product data - europe-west4]
      subgraph Serverless[Addressable and min-zero]
        WEB[Cloud Run React + FastAPI<br/>1 service / 0-10 instances]
        JOBS[Cloud Run async API<br/>1 service / 0-10 instances]
        WAKE[Cloud Run Jobs<br/>wake + suspend]
      end
      CAPTCHA[reCAPTCHA Enterprise]
      SM[Secret Manager<br/>4 regional secrets]
      KMS[Cloud KMS<br/>1 symmetric key]
      DB[(Firestore Native<br/>rolecall-dev + vector indexes)]
      GCS[(Cloud Storage<br/>private originals)]
      PS[Pub/Sub<br/>8 topics + 4 push subscriptions]
      SCH[Cloud Scheduler<br/>3 jobs]
      AI[Vertex AI / Agent Platform<br/>Gemini Live + 3.7 recap<br/>embeddings + Memory Bank]
      OBS[Logging + Monitoring + Trace]
      AR[Artifact Registry + Cloud Build]
      subgraph Voice[Voice plane - SLEEPING or READY]
        LB[LiveKit signaling + TURN LBs<br/>0 sleeping / 2 services READY]
        subgraph GKE[GKE Standard - europe-west4-a]
          MEDIA[Media pool e2-standard-2<br/>0 / 1 / 3 nodes]
          WORKERS[Worker pool e2-standard-2<br/>0 / 2 / 6 nodes]
          LK[LiveKit<br/>0 / 1 / 3 pods]
          ADK[ADK RTC workers<br/>0 / 2 / 6 pods]
          REDIS[(Ephemeral Redis<br/>0 / 1 pod)]
          EDGE[Ingress + cert-manager<br/>0 / 5 pods]
        end
      end
    end
    MP3 -->|bundled once| AR
    AR --> WEB
    WEB -->|same-origin static lobby audio| P
    A -->|login + admin APIs| WEB
    P -->|capability + lobby| WEB
    WEB --> CAPTCHA
    WEB --> SM
    WEB --> KMS
    WEB --> DB
    WEB --> GCS
    WEB --> PS
    PS --> JOBS
    SCH --> JOBS
    JOBS --> GCS
    JOBS --> DB
    JOBS --> AI
    JOBS --> WAKE
    WEB -->|admin-only wake| WAKE
    WAKE --> GKE
    WAKE --> LB
    P <-->|WebRTC only when READY| LB
    LB <--> LK
    LK <--> ADK
    ADK <--> REDIS
    ADK <--> AI
    ADK --> DB
    WEB -. redacted telemetry .-> OBS
    JOBS -. redacted telemetry .-> OBS
    ADK -. redacted telemetry .-> OBS
```

## Runtime counts

| Resource | `SLEEPING` | `READY` minimum | Maximum |
| --- | ---: | ---: | ---: |
| Cloud Run web/control | 0 idle instances | demand-based | 10 |
| Cloud Run async API | 0 idle instances | demand-based | 10 |
| Cloud Run transition Jobs | 0 tasks | 0 except transition | 1 task/job |
| GKE media nodes | 0 | 1 × `e2-standard-2` | 3 |
| GKE worker nodes | 0 | 2 × `e2-standard-2` | 6 |
| LiveKit pods | 0 | 1 | 3 |
| ADK voice-worker pods | 0 | 2 | 6 |
| Redis pods | 0 | 1 | 1 |
| Ingress/cert-manager pods | 0 | 5 | 5 |
| Repository-managed GKE pods | **0** | **9** | **15** |
| Public signaling/TURN services | 0 | 2 services / 3 forwarding rules | fixed |

System DaemonSets are excluded. The conservative minimum is three
`e2-standard-2` nodes (6 vCPU, 24 GiB). Each worker requests 250m CPU/2 GiB and
retains a 2 vCPU/4 GiB limit. Sleeping retains the control plane and reserved
IPs but has zero nodes, pods, and public media services.

## Managed services

| Area | Service and count | Purpose |
| --- | --- | --- |
| Identity | 8 service accounts + Workload Identity | Least-privilege build, runtime, scheduling, and application identities. |
| Authentication | 1 reCAPTCHA key + regional admin secret | Bot-aware shared login and versioned invalidation. |
| Capabilities | 1 symmetric Cloud KMS key | Recover participant links explicitly; SHA-256 remains verifier. |
| Data | 1 named Firestore database | Rooms, sessions, transcripts, recaps, runtime, and vectors. |
| Documents | 1 private regional bucket | Immutable text-based source versions. |
| Events | 4 event + 4 DLQ topics; 4 push subscriptions | Index, recap, cleanup, and runtime orchestration. |
| Scheduling | 3 jobs | Outbox, retention, and five-minute idle check. |
| AI | 4 model/capability paths | Gemini Live, Gemini 3.7, embedding-001, Memory Bank. |
| Delivery | 1 registry + manual Cloud Build | Immutable control, jobs, and worker images. |
| Creative media | 1 Lyria-generated static MP3 | Build-time lobby ambience; zero runtime calls. |

## Trust boundaries

- The controller owns lifecycle, timer, floor, and LiveKit publish permission;
  Gemini cannot override those rules.
- `search_room_docs(query)` receives server-injected scope and only frozen ready
  versions. Retrieved text is evidence, never instructions.
- Admin and participant cookies are separate. Link reveal is explicit and
  `no-store`; capability secrets and JWTs are excluded from logs.
- Browsers never access Firestore, GCS, KMS, Memory Bank, or Gemini directly.
- Raw meeting audio is bounded and memory-only; only finalized text persists.
- Lyria receives no runtime request or user-derived input. Browser playback is
  a local static element, not a LiveKit track.
- Meeting/document data expires after 90 days; GenAI content capture is off.

Related: [normal flow](FLOW.md), [operations](OPERATIONS.md),
[Lyria boundary](LYRIA.md), and [cost estimate](../infra/terraform/COST_ESTIMATE.md).
