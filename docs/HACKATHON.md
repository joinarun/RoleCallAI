# Hackathon submission guide

RoleCallAI targets the **Collaborative Partner** category of the All Things AI:
Agentic Hackathon. It acts in a live, multi-user environment rather than merely
chatting or reading a script.

## Four-minute video outline

| Time | Story | On-screen proof |
| --- | --- | --- |
| 0:00–0:30 | Meetings fail when nobody protects participation, time, and follow-through. | Product title and facilitator roles. |
| 0:30–1:05 | Secure admin creates a reusable room and optionally adds context. | Login/reCAPTCHA, dashboard, room, indexed document. |
| 1:05–2:20 | The agent runs a real two-person meeting. | Soft Lyria lobby, automatic start, enforced floor, both speakers, captions, citation. |
| 2:20–2:55 | Conversation becomes durable work. | Spoken close, actions/owners, recap, history, prior commitment. |
| 2:55–3:35 | Explain architecture and safety. | Cloud Run, Firestore, GKE/LiveKit, ADK, Gemini, RAG, Memory Bank. |
| 3:35–4:00 | Show readiness and cost discipline. | Tests/evals, 30-minute sleep, zero voice nodes/pods, repository. |

Use [the pitch deck](presentation/RoleCallAI-Hackathon-4-Minute-Pitch.pptx) and
[architecture deck](presentation/RoleCallAI-Architecture.pptx).

## Google technology evidence

| Capability | Implementation |
| --- | --- |
| Agent framework | Google ADK 2.x `Agent`, live `Runner`, validated tools, post-meeting Workflow. |
| Qualifying model | Gemini 3.7 Flash on the EU endpoint for recaps and evaluation. |
| Real-time intelligence | Gemini Live 2.5 Flash native audio. |
| Retrieval | `gemini-embedding-001` plus room-scoped Firestore vector search. |
| Long-term context | Agent Platform Memory Bank plus deterministic prior recap. |
| Creative-model bonus | Lyria 3 Pro Preview generated the static lobby soundtrack once. |
| Google Cloud | Cloud Run, GKE, Firestore, Storage, Pub/Sub, Scheduler, KMS, Secret Manager, reCAPTCHA, Cloud Build, Artifact Registry, observability. |

This project uses **Lyria**, not Veo or Gemma. Lyria never hears meeting audio
and is not part of facilitator reasoning.

## Judging alignment

- **Innovation and utility:** one voice agent coordinates many humans,
  remembers commitments, grounds private context, and supports twelve roles.
- **Architecture and stack:** deterministic floor enforcement, validated tools,
  room isolation, no raw-audio persistence, regional data, and a clear
  build-time/runtime Lyria boundary.
- **Demo and readiness:** hosted URL, responsive UI, reproducible tests,
  EU-local evaluation fallback, infrastructure as code, costs, and suspension.

## Honest limitations

- One shared hackathon admin; no signup, MFA, recovery, or production tenancy.
- English, voice-only Phase 1; no camera, screen sharing, or audio recording.
- Lyria generation is global-only. Its fixed prompt contained no user data; all
  meeting and document processing remains European.
- A single-node synthetic run demonstrated 50 publishers, but best
  public-network connection p95 was 5.79 seconds, above the 5-second target.
- `run.app` and `sslip.io` names are development endpoints.

## Submission checklist

- Hosted URL and private judge credential in Devpost.
- Public repository with setup instructions and no credentials.
- Four-minute real-product video.
- Architecture diagram with services, counts, and trust boundary.
- Model/framework inventory and Lyria provenance.
- Reproducible tests, self-hosting, limitations, costs, and sleep/wake evidence.

Official page:
[allthingsagentichackathon.devpost.com](https://allthingsagentichackathon.devpost.com/).
