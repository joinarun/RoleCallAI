# Lyria lobby soundtrack

RoleCallAI uses Google Lyria 3 Pro Preview for quiet, professional lobby music.
This is a **build-time media asset**, not a runtime agent call.

## Cost and privacy design

- Exactly one generation request produced the checked-in track.
- Estimated generation cost: **$0.08**; runtime Lyria calls/cost: **zero**.
- The global request contained one fixed creative prompt and no admin identity,
  participant, room, document, transcript, instruction, or audio.
- The MP3 is bundled into the Cloud Run frontend and served from the same
  origin. It never enters LiveKit, ADK, Gemini, Firestore, or telemetry.

Exact model, prompt, timestamp, media metadata, checksum, cost estimate, and
data boundary are in
`apps/web/src/assets/audio/rolecall-lobby-lyria.provenance.json`.

## Browser behavior

- Attempt playback only after LiveKit connects while occurrence is `LOBBY`.
- Default volume is 14%; Play/Mute handles autoplay and preference.
- Mute preference is local and contains no identity.
- Music fades for 600 ms and stops before `STARTING`, or on disconnect/unmount.
- Missing/blocked/corrupt music never blocks join or meeting start.
- Passive playback does not count as activity and cannot keep GKE awake.

## Intentional replacement only

```bash
uv run --project services/rolecall-agent \
  python scripts/media/generate_lobby_music.py --dry-run

# Only after archiving the prior approved asset and reviewing the prompt:
uv run --project services/rolecall-agent \
  python scripts/media/generate_lobby_music.py \
  --project YOUR_PROJECT_ID \
  --confirm-cost-usd 0.08
```

The generator refuses overwrite and an unconfirmed request. Do not silently
retry an artistically unsuitable result; obtain a new cost approval first.

Google references:
[Lyria 3](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/lyria/lyria-3)
and [music generation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/music/generate-music).
