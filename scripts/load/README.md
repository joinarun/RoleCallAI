# Synthetic LiveKit load

`synthetic_livekit.py` creates uniquely prefixed test rooms, connects in
room-interleaved batches, publishes a 48 kHz synthetic microphone from ten
participants per room, reports connection percentiles, and deletes only those
test-created rooms. Defaults match the Phase 1 target: five simultaneous
ten-person rooms for 15 seconds. Batched connection setup avoids overwhelming
one local SDK callback queue while all 50 publishers still stream together.

It calls no Gemini model and requires an explicit execution guard:

```bash
cd services/rolecall-agent
ROLECALL_LOAD_ALLOW=1 \
LIVEKIT_URL=ws://127.0.0.1:7880 \
LIVEKIT_API_KEY=replace-with-local-livekit-api-key \
LIVEKIT_API_SECRET=replace-with-local-livekit-secret-at-least-32-bytes \
uv run python ../../scripts/load/synthetic_livekit.py
```

For the deployed dev environment, retrieve credentials without writing a
service-account key and run only after cloud/load approval. This is a media
transport capacity test; deterministic floor tests and the single native-audio
Gemini smoke meeting are separate gates.
