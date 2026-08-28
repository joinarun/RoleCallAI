# RoleCallAI development architecture

This is the Phase 1 topology for the locally configured Google Cloud project.
New application processing and product data are in `europe-west4`; an existing
`(default)` Firestore database is not used.
Document upload and RAG are not part of this build.

## System diagram

[Open the zoomable SVG export](diagrams/architecture.svg).

```mermaid
flowchart TB
    subgraph Clients["Users"]
        direction LR
        Admin["Admin browser"]
        People["Participant browsers<br/>2-10 people per room"]
    end

    subgraph EU["Google Cloud · europe-west4"]
        direction TB

        subgraph Serverless["Serverless application"]
            direction LR
            CRControl["Cloud Run: web + control API<br/>1 service · 0-10 instances"]
            CRJobs["Cloud Run: async jobs<br/>1 service · 0-10 instances"]
        end

        subgraph VPC["RoleCall VPC + Cloud NAT"]
            direction TB
            subgraph Edge["Regional public edge · 2 reserved IPs"]
                direction LR
                SignalEdge["Signaling load balancer<br/>TCP 80/443"]
                TurnEdge["TURN load balancer<br/>TCP 5349 + UDP 3478"]
            end

            subgraph GKE["Zonal GKE Standard · europe-west4-a<br/>2 pools · 3 nodes minimum / 9 maximum"]
                direction LR
                subgraph Media["Media pool<br/>1-3 e2-standard-4 nodes"]
                    LiveKit["LiveKit Server<br/>1-3 pods · host networking"]
                end
                subgraph Workers["Worker pool<br/>2-6 e2-standard-4 nodes"]
                    SignalIngress["Signaling ingress-nginx<br/>1 pod"]
                    TurnIngress["TURN ingress-nginx<br/>1 pod"]
                    AgentWorker["ADK + LiveKit RTC worker<br/>2-6 pods"]
                    Certs["cert-manager<br/>3 pods"]
                end
            end
        end

        subgraph Managed["Managed data and AI"]
            direction LR
            Firestore[("Firestore Native<br/>rolecall-dev · 1 database")]
            Redis[("Memorystore Redis Basic<br/>1 instance · 1 GiB")]
            Secrets["Secret Manager<br/>3 secrets"]
            Memory["Vertex AI Agent Platform<br/>1 Memory Bank"]
            GeminiLive["Vertex AI Gemini Live<br/>native-audio voice model"]
            GeminiSummary["Vertex AI Gemini<br/>EU summary/evaluation model"]
        end

        subgraph Operations["Events, build, and operations"]
            direction LR
            Scheduler["Cloud Scheduler<br/>2 jobs"]
            PubSub["Pub/Sub<br/>4 topics · 2 push subscriptions"]
            CloudBuild["Cloud Build + source staging<br/>manual builds · 0 normally"]
            Artifact["Artifact Registry<br/>1 Docker repository"]
            Observe["Cloud Logging, Monitoring, Trace<br/>1 dashboard · 4 alerts"]
        end
    end

    Admin -->|"admin capability over HTTPS"| CRControl
    People -->|"seat capability, join, captions"| CRControl
    People <-->|"WebSocket signaling"| SignalEdge
    People <-->|"TURN fallback"| TurnEdge
    People <-->|"direct WebRTC media<br/>UDP 50000-60000 or TCP 7881"| LiveKit

    SignalEdge --> SignalIngress --> LiveKit
    TurnEdge --> TurnIngress --> LiveKit
    CRControl -->|"room + JWT API"| LiveKit
    LiveKit <-->|"room audio + data"| AgentWorker
    AgentWorker <-->|"PCM audio + tool calls"| GeminiLive

    CRControl --> Firestore
    CRControl --> Redis
    CRControl --> Secrets
    AgentWorker --> Firestore
    AgentWorker --> Redis
    AgentWorker --> Memory
    AgentWorker --> Secrets

    Scheduler -->|"outbox + retention"| CRJobs
    CRJobs <-->|"publish + OIDC push"| PubSub
    CRJobs --> Firestore
    CRJobs --> Memory
    CRJobs --> GeminiSummary

    CloudBuild -->|"push images"| Artifact
    Artifact -.-> CRControl
    Artifact -.-> CRJobs
    Artifact -.-> AgentWorker
    CRControl -.-> Observe
    CRJobs -.-> Observe
    AgentWorker -.-> Observe
```

The two load-balanced endpoints provide stable TLS signaling and TURN addresses.
LiveKit media itself uses direct public networking on the dedicated media node,
which is why the media pool uses GKE Standard with host networking rather than
Cloud Run, Autopilot, or a private-only cluster.

## Deployed counts and scale limits

| Layer | Deployed minimum / current steady state | Configured ceiling | Notes |
| --- | ---: | ---: | --- |
| Cloud Run web/control | 0 idle instances | 10 | One service; starts on an HTTP request. |
| Cloud Run async jobs | 0 idle instances | 10 | One internal service; invoked by Scheduler and Pub/Sub. |
| GKE cluster | 1 zonal Standard cluster | 1 | Google manages the control plane. |
| GKE media nodes | 1 `e2-standard-4` | 3 | Public IP, host networking, 50 GiB balanced boot disk. |
| GKE worker nodes | 2 `e2-standard-4` | 6 | ADK workers, ingress, cert-manager, and GKE system workloads. |
| LiveKit pods | 1 | 3 | One media pod per media node. |
| RoleCall ADK worker pods | 2 | 6 | Each process handles one live meeting at a time. |
| Ingress controller pods | 2 total | 2 | One signaling pod and one TURN pod. |
| cert-manager pods | 3 total | 3 | Controller, CA injector, and webhook. |
| Repository-managed GKE pods | **8 total** | **14 total** | Excludes GKE-managed system pods and DaemonSets, whose count follows node count. |
| Memorystore Redis | 1 Basic instance, 1 GiB | 1 | LiveKit routing, capability state, and rate limits. |
| Firestore | 1 named Native database | 1 | Rooms, occurrences, captions, outcomes, outbox, and retention metadata. |
| Agent Platform | 1 Memory Bank | 1 | Cross-meeting room memory; no RAG corpus. |
| Public edge | 2 reserved IPs, 2 load-balanced endpoints, 3 forwarding rules | Fixed | Signaling TCP plus TURN TCP/UDP. |
| Scheduler / Pub/Sub | 2 jobs, 4 topics, 2 subscriptions | Fixed | Includes two dead-letter topics. |
| Security / identity | 3 secrets, 7 service accounts | Fixed | Secret Manager, IAM, and Workload Identity; no key files. |
| Build | 0 active builds normally, 1 image repository | On demand | Manual Cloud Build, Cloud Storage source staging, and Artifact Registry. |
| Observability | 1 dashboard, 4 alert policies, 4 log-based metrics | Fixed configuration | Cloud Logging, Monitoring, managed Prometheus, and Trace. |

The normal running minimum is three VM nodes and eight repository-managed pods.
Cloud Run does not reserve an instance at idle because both services have a
minimum of zero.

## Trust and data boundaries

- The deterministic controller owns lifecycle, time, turn order, and LiveKit
  publish permissions; Gemini cannot bypass those checks.
- Capability secrets are exchanged from URL fragments and only SHA-256 digests
  are stored. Raw audio stays in bounded memory and is never recorded.
- Final transcript segments, recaps, and curated memory are retained for 90 days.
- Browsers never access Firestore, Redis, Memory Bank, Secret Manager, or Gemini
  directly. All product-data access is server-scoped.
- LiveKit and the workers use private Redis connectivity inside the VPC. Cloud
  NAT supplies controlled outbound access from GKE to Google APIs.

## Related material

- [Normal use-case flow](FLOW.md)
- [Suspend and resume runbook](OPERATIONS.md)
- [Current cost model](../infra/terraform/COST_ESTIMATE.md)
