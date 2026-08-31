# RoleCallAI

**Let AI lead the conversation forward.**

RoleCallAI is a browser-based, voice-only meeting room led by a configurable
Google ADK facilitator. It runs stand-ups, retrospectives, brainstorming,
workshops, interviews, incident calls, games, and custom formats while a
deterministic controller—not the model—owns the clock, floor, microphone
permissions, and lifecycle.

[Try the hosted application](https://rolecall-dev-control-2502669067.europe-west4.run.app/)
· [Architecture](docs/ARCHITECTURE.md)
· [Four-minute demo guide](docs/HACKATHON.md)
· [Reproducible testing](docs/REPRODUCIBLE_TESTING.md)
· [Self-hosting](docs/SELF_HOSTING.md)

[Demo available in YouTube Video](https://youtu.be/lUjKNMtc42U)
## Why it is agentic

- **Acts, not just chats:** the ADK agent opens the meeting, calls on each
  participant, asks role-specific follow-ups, records outcomes, and closes on
  time through validated server tools.
- **Controls a real-time environment:** LiveKit publish permission is granted
  only to the current speaker, so a modified browser cannot bypass the floor.
- **Remembers responsibly:** completed recaps and stable-seat facts give later
  meetings continuity without retaining raw audio.
- **Grounds responses:** optional room documents are chunked and embedded with
  `gemini-embedding-001`; `search_room_docs()` performs room- and
  occurrence-scoped Firestore vector retrieval with participant-visible
  citations.
- **Uses native voice:** Gemini Live receives bounded PCM audio and returns
  natural speech plus finalized captions.
- **Adds a human touch:** one warm lobby soundtrack was generated with Google
  Lyria 3 Pro and is served as a static asset—no per-meeting music generation.

## Reproducible testing

### 1. Test the already-hosted Google Cloud application

The public application is:

<https://rolecall-dev-control-2502669067.europe-west4.run.app/>

Hackathon judges receive the shared admin username and password privately
through Devpost. Credentials are deliberately not committed to this repository.
Other reviewers can request temporary access through
[GitHub](https://github.com/joinarun/RoleCallAI) or
[X/Twitter](https://x.com/aforarun2001).

1. Open the URL, enter the supplied admin credential, and complete reCAPTCHA.
2. If the dashboard says `SLEEPING`, select **Wake voice services**. The page
   remains available while the costly voice plane sleeps; allow up to 10–20
   minutes for a cold wake.
3. Select **Create room**, choose a role, participant count, duration, agent
   name, and instructions. A document upload is optional.
4. Open the room, reveal its seat links, and copy one unique link per person.
5. Open each link in a separate browser profile/device, enter the participant
   name, accept the retention/processing consent, and enter the voice room.
6. The Lyria-generated lobby music starts softly after the join interaction.
   A visible Play/Mute control handles browser autoplay preferences. It fades
   out before Gemini or a participant takes the floor.
7. Join all expected seats for automatic start, or use the two-minute grace
   start. Speak only when the UI grants your floor. Watch finalized captions,
   citations, and the completed recap.
8. Leave the deployment idle when finished; the voice nodes and media load
   balancers automatically suspend after 30 minutes without genuine activity.

Exact expected results and troubleshooting are in
[docs/REPRODUCIBLE_TESTING.md](docs/REPRODUCIBLE_TESTING.md).

### 2. Deploy and test in your own Google Cloud project

Prerequisites are Node.js 22+, `uv`, Docker, Google Cloud CLI, Terraform,
`kubectl`, Helm, and a billed Google Cloud project. The stack is intentionally
custom because LiveKit requires GKE Standard host networking and public media
nodes.

```bash
gcloud auth login
gcloud auth application-default login
cp infra/terraform/vars/dev.tfvars.example infra/terraform/vars/dev.tfvars
cp .rolecall.local.env.example .rolecall.local.env
make install
make test
make lint
make build
make eval-validate
make terraform-validate
make terraform-plan
./scripts/terraform-inventory.sh
```

Review the saved Terraform plan, resource inventory, and
[cost estimate](infra/terraform/COST_ESTIMATE.md) before any apply. Then follow
the approval-gated procedure in [docs/SELF_HOSTING.md](docs/SELF_HOSTING.md).
It creates only named Firestore database `rolecall-dev`; lifecycle scripts
refuse to operate on an unrelated `(default)` database.

Lyria is **not** required to redeploy the checked-in application. The generated
MP3 and non-secret provenance are versioned. Maintainers who intentionally
replace it must use the one-request cost guard in [docs/LYRIA.md](docs/LYRIA.md).

## Technology

| Layer | Technology |
| --- | --- |
| Web | React 19, Vite 7, TypeScript, Playwright, Vitest |
| API/control | Python 3.11+, FastAPI, Pydantic |
| Agent | Google ADK 2.x, `Runner.run_live()`, ADK Workflow |
| Voice | Gemini Live native audio, LiveKit WebRTC, GKE Standard |
| Recap/evaluation | Gemini 3.7 Flash on the EU endpoint |
| RAG | Cloud Storage, `gemini-embedding-001`, Firestore vector search |
| Memory | Agent Platform Memory Bank plus deterministic previous recap |
| Music | Lyria 3 Pro Preview, generated once from a fixed global prompt |
| Security | Argon2id, reCAPTCHA Enterprise, Secret Manager, Cloud KMS |
| Operations | Terraform, Cloud Build, Cloud Run, Pub/Sub, Scheduler, Monitoring |

## Repository map

```text
apps/web/                    React admin and participant application
services/rolecall-agent/     FastAPI, ADK, RTC bridge, retrieval and jobs
infra/terraform/             Google Cloud infrastructure as code
infra/kubernetes/            LiveKit, Redis, ingress and worker Helm charts
scripts/                     Lifecycle, migration, media and load tools
docs/                        Architecture, flows, operations and public specs
docs/specs/                  Requirement and traceability documents for SDD
```

Start at [docs/README.md](docs/README.md) for the documentation index.

## Local development

```bash
make install
make dev-api   # terminal 1
make dev-web   # terminal 2
```

The API uses an in-memory repository by default. Local LiveKit and Redis are in
`docker-compose.yml`; Firestore emulator guidance is in the reproducible test
guide.

```bash
make test
make lint
make build
make test-e2e
make eval-validate
```

## Specification-driven development

The approved implementation contract is [.agents-cli-spec.md](.agents-cli-spec.md).
Public, testable requirements live in
[docs/specs/rolecallai-v1.md](docs/specs/rolecallai-v1.md), and
[docs/specs/traceability.md](docs/specs/traceability.md) maps each requirement
to code and evidence. New work should update the requirement, acceptance
criteria, implementation, tests, and traceability row in the same change.

## Security, privacy, and cost defaults

- Admin access uses a versioned Argon2id credential, reCAPTCHA risk assessment,
  durable throttling, Origin/CSRF validation, and an eight-hour HttpOnly session.
- Participant URL fragments are secret capabilities; only SHA-256 digests and
  KMS ciphertext are stored.
- Browsers never access Firestore, GCS, KMS, Memory Bank, or Gemini directly.
- Raw audio is bounded and memory-only; LiveKit egress recording is disabled.
- Finalized transcripts, recaps, citations, document versions, vectors, and
  memory expire after 90 days.
- Product data and meeting processing stay in Europe. The sole exception is the
  one-time Lyria request documented above; it contained no user or meeting data.
- After 30 idle minutes, GKE reaches zero nodes/pods and LiveKit/TURN public load
  balancers are removed. The GKE control plane, reserved IPs, and durable
  storage remain billable; see the [cost estimate](infra/terraform/COST_ESTIMATE.md).

## Hackathon evidence

RoleCallAI targets the **Collaborative Partner** category. The submission map,
official-rule checklist, demo timing, model inventory, and honest limitations
are collected in [docs/HACKATHON.md](docs/HACKATHON.md).
