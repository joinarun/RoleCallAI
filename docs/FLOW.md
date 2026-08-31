# RoleCallAI normal use-case flow

[Open the zoomable sequence export](diagrams/normal-use-flow.svg).

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"#070b22","primaryColor":"#151b3b","primaryTextColor":"#f7f7ff","primaryBorderColor":"#8077ff","lineColor":"#6be3bd","secondaryColor":"#101735","tertiaryColor":"#0b102b","clusterBkg":"#0b102b","clusterBorder":"#39406b","noteBkgColor":"#1b244d","noteTextColor":"#f7f7ff","noteBorderColor":"#ff8c86","actorBkg":"#151b3b","actorBorder":"#8077ff","actorTextColor":"#f7f7ff","signalColor":"#6be3bd","signalTextColor":"#dfe4ff","labelBoxBkgColor":"#101735","labelBoxBorderColor":"#8077ff","labelTextColor":"#f7f7ff","loopTextColor":"#f7f7ff"}}}%%
sequenceDiagram
    autonumber
    actor Admin
    actor P as Participants
    participant Web as Cloud Run React + FastAPI
    participant Sec as reCAPTCHA + Secret Manager + KMS
    participant DB as Firestore rolecall-dev
    participant Q as Pub/Sub + async jobs
    participant Store as Cloud Storage
    participant Runtime as Runtime Job + GKE
    participant LK as LiveKit
    participant Agent as ADK RTC worker
    participant AI as Vertex AI / Agent Platform
    Admin->>Web: Login with reCAPTCHA
    Web->>Sec: Verify risk + credential version
    Web->>DB: Throttle and create 8-hour session
    alt Voice runtime is SLEEPING
      Admin->>Web: Wake voice services
      Web->>Runtime: Start idempotent wake
      Runtime->>LK: Restore 1 media + 2 worker nodes, 9 pods, TLS and TURN
      Runtime->>DB: Mark READY after health checks
    end
    Admin->>Web: Create room and optional document
    Web->>Sec: KMS-encrypt seat capabilities
    opt Document supplied
      Web->>Store: Save immutable private version
      Web->>Q: Publish index event
      Q->>AI: Generate 768D embeddings
      Q->>DB: Store room-scoped vectors + citations
    end
    Admin->>Web: Explicitly reveal participant links
    loop Each participant
      P->>Web: Exchange URL-fragment capability
      Web->>DB: Verify digest + seat availability
      P->>Web: Name + consent + enter room
      Web-->>P: Same-origin static Lyria MP3
      Note over P,Web: Local lobby playback only<br/>No model call and no LiveKit music track
      Web-->>P: Short-lived LiveKit JWT when READY
      P->>LK: Join browser audio
    end
    LK->>Agent: Dispatch named facilitator
    Agent->>DB: Load role, prior recap, frozen documents
    Note over P,Agent: Lobby music fades/stops before STARTING
    Agent->>AI: Start resumable Gemini Live session
    loop Deterministic floor turns
      Agent->>LK: Enable publish only for floor owner
      P->>Agent: Speaker audio or reliable hand raise
      opt Context is useful
        AI->>Agent: search_room_docs(query)
        Agent->>DB: Search room + frozen versions only
      end
      AI-->>Agent: Native audio + finalized caption
      Agent-->>P: Voice + caption + citations
      Agent->>DB: Persist finalized text/outcomes only
    end
    Agent-->>P: Complete spoken closing
    Agent->>Q: Idempotent post-processing
    Q->>AI: Gemini 3.7 typed recap
    Q->>DB: Save recap + memory and mark COMPLETED
    Web-->>Admin: History + transcript + recap
    Web-->>P: Attended recap
    Note over Web,Runtime: 30 idle minutes + no active meeting suspends voice to zero nodes/pods
```

## Runtime lifecycle

[Open the zoomable runtime lifecycle](diagrams/runtime-lifecycle.svg).

```mermaid
stateDiagram-v2
    [*] --> SLEEPING
    SLEEPING --> WAKING: authenticated admin wake
    WAKING --> READY: nodes, pods, TLS and media pass
    WAKING --> ERROR: recovery exhausted
    ERROR --> WAKING: admin retry
    READY --> SUSPENDING: 30m idle + no active occurrence
    SUSPENDING --> SLEEPING: joins blocked, LB removed, nodes zero
    SUSPENDING --> READY: protected activity aborts suspension
```

## Meeting lifecycle

[Open the zoomable meeting lifecycle](diagrams/meeting-lifecycle.svg).

```mermaid
stateDiagram-v2
    [*] --> LOBBY: first valid arrival
    LOBBY --> STARTING: all seats or grace start
    STARTING --> RUNNING: worker + Gemini ready
    RUNNING --> ENDING: timer or authorized end
    ENDING --> PROCESSING: spoken close finishes
    PROCESSING --> COMPLETED: recap + memory persisted
    STARTING --> FAILED: unrecoverable startup
    RUNNING --> PROCESSING: preserve partial meeting after failure
    PROCESSING --> FAILED: post-processing recovery exhausted
```

The floor controller—not Gemini—controls transitions and microphones. An admin
can delegate **End for everyone**. Late arrivals join the remaining order;
disconnected speakers keep the floor for 30 seconds; the worker gets a bounded
recovery window before partial processing.

See [reproducible testing](REPRODUCIBLE_TESTING.md) for a judge walkthrough and
[operations](OPERATIONS.md) for wake/suspend behavior.
