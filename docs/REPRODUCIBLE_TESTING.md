# Reproducible testing

This guide gives reviewers two independent paths: exercise the maintained
Google Cloud deployment or reproduce code-level verification locally.

## A. Hosted judge path

Application: <https://rolecall-dev-control-2502669067.europe-west4.run.app/>

Judges receive the shared admin credential privately through Devpost. It is not
recoverable from Git, page source, Cloud logs, or this document. Public
reviewers can request access at
[github.com/joinarun/RoleCallAI](https://github.com/joinarun/RoleCallAI) or
[x.com/aforarun2001](https://x.com/aforarun2001).

### Expected test

1. Sign in and complete reCAPTCHA. Invalid and unknown credentials receive the
   same generic response.
2. If runtime is `SLEEPING`, click **Wake voice services** and wait for `READY`.
   Participants cannot perform this action.
3. Create a 5-minute, two-seat room using Scrum Master or Fun Friday.
4. Optional grounding test: upload a small text PDF/TXT containing one unique,
   non-sensitive fact and wait for `READY` indexing status.
5. Reveal seat links. Open each in a separate browser profile/device so cookies
   and microphone permissions are independent.
6. Enter different names, accept consent, and enter. The join interaction may
   start soft Lyria lobby music. If autoplay is blocked, select **Play music**;
   Mute is remembered locally.
7. Join the second seat. All expected seats trigger automatic start. On each
   turn, only the named floor owner can publish.
8. Let both people finish naturally. Check that the facilitator responds after
   participant two and does not move on while speech is active.
9. End normally or use an authorized **End for everyone** control. Confirm that
   closing audio completes, processing ends, and the result shows summary,
   date, time, duration, audio quality, outcomes, and any citations.
10. Return to the admin dashboard and verify the occurrence under History.

### Observable pass conditions

- Unauthenticated room APIs and creation controls are unavailable.
- Lobby music is quiet, optional, never published to LiveKit, and stops before
  meeting audio begins.
- Both participants receive a turn; off-floor microphones remain disabled.
- Final captions appear once per utterance and the spoken closing is not cut.
- A relevant room document is cited; another room cannot retrieve it.
- No raw-audio or recording control exists.
- Leaving the environment idle eventually returns runtime to `SLEEPING`.

## B. Local deterministic verification

Prerequisites: Node.js 22+, `uv`, Docker, and Playwright browser dependencies.

```bash
make install
make test
make lint
make build
make eval-validate
```

The default unit/integration suite uses in-memory fakes and controlled cloud
contracts. It does not spend model credits. The media generator is safe by
default:

```bash
uv run --project services/rolecall-agent \
  python scripts/media/generate_lobby_music.py --dry-run
```

The checked-in MP3 means reviewers should **not** regenerate it. The generator
refuses to send a request without exact cost confirmation and refuses to
overwrite the asset.

For UI end-to-end testing, start API and Vite in separate terminals, then run:

```bash
make dev-api
make dev-web
make test-e2e
```

The real LiveKit test is explicit because it starts media dependencies:

```bash
cd apps/web
ROLECALL_E2E_LIVEKIT=1 npm run test:e2e:live
```

Model-based evaluations and deployed smoke/load checks are separately gated;
see `services/rolecall-agent/tests/eval/datasets/README.md` and
`scripts/load/README.md`. Final deployed evidence, including known load-test
limitations, is in [DEPLOYMENT.md](DEPLOYMENT.md).

## Security check before publishing

```bash
git status --short
git ls-files | rg '(\.env$|\.tfstate|\.tfplan|local-data|\.codex-tmp)'
rg -n --hidden --glob '!.git/**' --glob '!*.mp3' \
  '(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|Bearer [A-Za-z0-9._-]+|cap=[A-Za-z0-9_-]{20,})'
```

Expected result: no credential material or local state is tracked.
