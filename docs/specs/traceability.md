# Requirement traceability

| Requirement | Primary implementation | Verification evidence |
| --- | --- | --- |
| RC-MEET-001/002 | `app/services/meetings.py`, `app/live/handoff.py`, `app/services/livekit.py` | `test_domain.py`, `test_live_runtime.py`, `live-meeting.spec.ts` |
| RC-MEET-003 | `app/domain/roles.py`, `app/agent.py`, eval datasets | `make eval-validate`, EU-local deployment record |
| RC-MEET-004 | `app/live/playout.py`, `app/live/watchdog.py` | `test_playout.py`, `test_live_runtime.py`, voice smoke |
| RC-SEC-001 | `app/security/admin_auth.py`, `app/admin_api.py` | `test_admin_auth.py`, browser tests |
| RC-SEC-002 | `app/security/capabilities.py`, `app/security/seat_links.py` | domain/integration tests and migration report |
| RC-RAG-001 | `app/retrieval/*`, `search_room_docs` | document, retrieval, and cloud-contract tests |
| RC-DATA-001/002 | RTC bridge, repository, cleanup job | audio/transcription, cleanup, expiry tests |
| RC-COST-001/002 | runtime manager/jobs and infrastructure sizing | runtime tests and deployed zero-node/READY evidence |
| RC-MEDIA-001 | static MP3 + provenance | `ffprobe` and SHA-256 check |
| RC-MEDIA-002/003 | `useLobbyMusic.ts`, `MeetingSurface.tsx` | `useLobbyMusic.test.tsx`, build, browser smoke |
| RC-COST-003/RC-REGION-001 | `generate_lobby_music.py` | `test_generate_lobby_music.py`, `docs/LYRIA.md` |

Paths under `app/` and `tests/` are relative to `services/rolecall-agent/`.
