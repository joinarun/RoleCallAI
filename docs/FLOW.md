# RoleCallAI normal use-case flow

## End-to-end sequence

[Open the zoomable sequence SVG](diagrams/normal-use-flow.svg).

```mermaid
sequenceDiagram
    autonumber
    actor Admin
    actor P as Participants (2-10)
    participant API as Cloud Run web/control
    participant DB as Firestore rolecall-dev
    participant LK as LiveKit on GKE
    participant W as ADK voice worker on GKE
    participant G as Gemini Live
    participant Q as Scheduler + Pub/Sub
    participant J as Cloud Run jobs
    participant M as Memory Bank

    Admin->>API: Create room, role, duration, seats, and instructions
    API->>DB: Transactionally save room and capability digests
    API-->>Admin: One admin URL and one unique URL per seat

    loop Each participant
        P->>API: Open join URL with token in URL fragment
        API->>DB: Validate SHA-256 capability digest
        API-->>P: Set short-lived secure HttpOnly cookie
        P->>API: Enter display name, consent, and pass first/required device check
        API->>DB: First arrival creates next occurrence transactionally
        API->>LK: Create/authorize LiveKit room and seat identity
        API-->>P: Occurrence state, LiveKit URL, and short-lived JWT
        P->>LK: Join browser audio room
    end

    alt All expected seats are present
        API->>DB: Move LOBBY to STARTING automatically
    else Two-minute lobby grace expires
        P->>API: Present participant starts and absentees are recorded
        API->>DB: Move LOBBY to STARTING
    end

    API->>LK: Dispatch occurrence to an available worker
    LK->>W: Worker joins as the voice agent
    W->>DB: Read room config and immediately previous recap
    W->>M: Retrieve older room memories when useful
    W->>G: Start resumable native-audio ADK live session
    W->>DB: Move occurrence to RUNNING

    loop Deterministic facilitated turns
        W->>LK: Grant publish permission only to current seat
        W->>G: Forward current speaker PCM audio and meeting state
        G-->>W: Agent audio, final captions, or validated tool proposal
        W-->>LK: Publish agent audio, captions, meeting events
        LK-->>P: Play agent and current speaker, update roster/timer/captions
        P-->>W: Current speaker interrupts naturally, others send hand.raise
        W->>DB: Persist only finalized transcript and outcomes
    end

    opt Admin delegates meeting control
        Admin->>API: Allow or revoke End for everyone on a seat
        API->>DB: Update room and active occurrence permissions
        API-->>P: Broadcast authoritative meeting state
    end

    alt Participant leaves intentionally
        P->>API: Leave with current connection identity
        API->>DB: Mark departed and skip floor immediately
    else Admin or delegated participant ends meeting
        Admin->>API: End for everyone
        API->>DB: Move partial/full occurrence to PROCESSING
    end

    W->>DB: Begin ENDING with two minutes left
    W-->>P: Recap owners, decisions, blockers, ideas, or game result
    W->>DB: Finish as PROCESSING and write an idempotent outbox record
    Q->>J: Drain outbox, then OIDC-authenticated postprocess push
    J->>G: Generate typed recap with EU summary model
    J->>DB: Validate and persist recap, then mark COMPLETED
    J->>M: Save explicit room facts keyed by stable seat IDs
    J-->>API: Recap is available
    API-->>P: Show latest attended recap
    API-->>Admin: Show 90-day history and finalized transcript

    Note over DB,M: The next occurrence receives the previous recap and can recall retained commitments.
```

## Meeting lifecycle

[Open the zoomable lifecycle SVG](diagrams/meeting-lifecycle.svg).

```mermaid
stateDiagram-v2
    [*] --> LOBBY: First valid seat arrival
    LOBBY --> STARTING: All seats present
    LOBBY --> STARTING: Present user starts after 2 minutes
    STARTING --> RUNNING: LiveKit worker and Gemini session ready
    RUNNING --> ENDING: 2 minutes remain or finish requested
    ENDING --> PROCESSING: Closing complete, maximum 60-second grace
    PROCESSING --> COMPLETED: Recap and memory persisted
    STARTING --> FAILED: Unrecoverable worker startup
    RUNNING --> PROCESSING: Agent unavailable for 60 seconds, preserve partial meeting
    PROCESSING --> FAILED: Post-processing exhausts recovery
    COMPLETED --> [*]
    FAILED --> [*]
```

## What changes by role

- **Scrum Master:** follows the stable seat order, recalls earlier commitments,
  probes blockers, and closes with owners and actions.
- **Fun Friday Organizer:** chooses or follows the configured game, rotates equal
  turns, tracks scores where applicable, and announces results.
- **Brainstorm Facilitator:** frames the topic, gathers divergent ideas, clusters
  and prioritizes them, and converts them into next steps.
- **Sprint Retrospective, Project Status, and Incident Response:** run blameless
  improvement, cross-team status, or fact-disciplined restoration workflows.
- **Course Instructor, Workshop Facilitator, and Technical Interviewer:** teach,
  guide collaborative activities, or evaluate fairly with balanced turns.
- **Product Discovery, Decision-Making, and Town Hall:** uncover evidence before
  solutions, compare options against criteria, or moderate relevant Q&A.
- **Custom:** applies the admin instructions inside the same timed, server-enforced
  floor and lifecycle framework.
