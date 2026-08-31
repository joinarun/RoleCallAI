# RoleCallAI v1 product requirements

## Core agent and meeting

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| RC-MEET-001 | Controller owns lifecycle, timer, floor, and publish permission. | Off-floor publish is denied; invalid model transitions are rejected. |
| RC-MEET-002 | Support 2–10 humans in 5–60 minute reusable rooms. | Auto/grace start, absence, late arrival, and reconnect policies pass. |
| RC-MEET-003 | Built-in roles include everyone and produce structured outcomes. | Agent evaluation is at least 0.8 with no authorization/isolation failure. |
| RC-MEET-004 | Speech and captions complete without truncation or dead floor. | Two-person smoke hears both speakers and closing; watchdog/floor tests pass. |

## Identity, data, and retrieval

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| RC-SEC-001 | Admin APIs require login, reCAPTCHA, throttling, session, Origin, and CSRF controls. | Anonymous calls return 401; failures are generic; rotation revokes sessions. |
| RC-SEC-002 | Seat links are revocable capabilities. | Fragments are scrubbed; digest/KMS ciphertext persist; duplicate seat rejected. |
| RC-RAG-001 | Documents ground one room without cross-room access. | Search filters room/frozen versions; injection cannot alter tools; citations show. |
| RC-DATA-001 | Raw audio is never persisted. | No egress/blob persistence; only finalized transcript segments are written. |
| RC-DATA-002 | Meeting/document data expires after 90 days. | Expiry, cleanup, and lifecycle backstops are tested. |

## Cost-aware runtime

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| RC-COST-001 | Suspend voice after 30 idle minutes and no active occurrence. | Zero GKE nodes/pods and public media LBs; participant cannot wake. |
| RC-COST-002 | Conservative READY profile preserves quality. | 1 media + 2 worker nodes, two warm workers, unchanged model/audio, smoke passes. |

## Lobby music

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| RC-MEDIA-001 | One shared warm soundtrack generated with Lyria. | MP3 provenance/checksum and valid 44.1 kHz MPEG metadata are versioned. |
| RC-MEDIA-002 | Play only in connected lobby; never enter meeting media. | Accessible fallback/mute; 600 ms stop before `STARTING`; no LiveKit track. |
| RC-MEDIA-003 | Music failure cannot block a meeting. | Blocked/unavailable state leaves join/start functional. |
| RC-COST-003 | Generation is one-time and cost-capped. | Dry-run has no network/write; exact `$0.08` required; no overwrite. |
| RC-REGION-001 | European meeting data; global Lyria exception has no user data. | Fixed-prompt provenance; no runtime/user-derived Lyria request. |
