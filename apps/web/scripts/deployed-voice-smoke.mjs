import { access } from "node:fs/promises";

import { chromium, request } from "@playwright/test";

const baseURL = process.env.ROLECALL_SMOKE_BASE_URL?.replace(/\/$/, "");
const storageStatePath = process.env.ROLECALL_SMOKE_ADMIN_STORAGE_STATE;
const firstAudio = process.env.ROLECALL_SMOKE_AUDIO_ONE;
const secondAudio = process.env.ROLECALL_SMOKE_AUDIO_TWO;
const smokeRole = process.env.ROLECALL_SMOKE_ROLE ?? "SCRUM_MASTER";
const smokeGame = smokeRole === "FUN_FRIDAY" ? "RAPID_FIRE_TRIVIA" : null;
const smokeInstructions =
  process.env.ROLECALL_SMOKE_INSTRUCTIONS ??
  (smokeRole === "FUN_FRIDAY"
    ? "Run exactly one concise rapid-fire trivia round. Ask Ben Smoke first and Ada Smoke second, one question each. After both responses, do not open another round. Speak a closing recap with four short, complete numbered sentences, then call finish_meeting as the final action."
    : "Run exactly one concise stand-up round and ask each participant once. After both responses, do not open another round. Speak a closing recap with four short, complete numbered sentences, then call finish_meeting as the final action.");

if (!baseURL || !firstAudio || !secondAudio || !storageStatePath) {
  throw new Error(
    "Set ROLECALL_SMOKE_BASE_URL, ROLECALL_SMOKE_ADMIN_STORAGE_STATE, ROLECALL_SMOKE_AUDIO_ONE, and ROLECALL_SMOKE_AUDIO_TWO.",
  );
}
await Promise.all([access(firstAudio), access(secondAudio), access(storageStatePath)]);

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function jsonResponse(response, operation) {
  if (!response.ok()) {
    throw new Error(`${operation} failed with HTTP ${response.status()}`);
  }
  if (response.status() === 204) return null;
  return response.json();
}

async function waitUntil(label, operation, timeoutMs = 240_000, intervalMs = 3_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = await operation();
    if (value) return value;
    await delay(intervalMs);
  }
  throw new Error(`${label} did not complete within ${Math.round(timeoutMs / 1000)} seconds`);
}

async function launchParticipant(audioPath) {
  const browser = await chromium.launch({
    headless: true,
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
      `--use-file-for-fake-audio-capture=${audioPath}`,
    ],
  });
  const context = await browser.newContext({ baseURL, permissions: ["microphone"] });
  return { browser, context, page: await context.newPage() };
}

async function joinParticipant(page, seatUrl, roomId, roomName, name, runDeviceCheck = true) {
  await page.goto(seatUrl);
  await page.getByRole("heading", { name: /sound good/i }).waitFor({ timeout: 20_000 });
  await page.getByLabel("Your name").fill(name);
  if (runDeviceCheck) {
    await page.getByRole("button", { name: /run check/i }).click();
    await page.getByText("Microphone ready").waitFor({ timeout: 10_000 });
  }
  await page.getByRole("checkbox").check();
  const enter = page.getByRole("button", { name: /enter voice room/i });
  if (!(await enter.isEnabled())) {
    throw new Error("Enter voice room remained disabled after remembered microphone permission");
  }
  const joined = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/v1/rooms/${roomId}:join`) &&
      response.request().method() === "POST",
    { timeout: 20_000 },
  );
  await enter.click();
  const payload = await jsonResponse(await joined, `join ${name}`);
  await page.getByRole("heading", { name: roomName }).waitFor({ timeout: 20_000 });
  await page.getByText("connected", { exact: true }).waitFor({ timeout: 20_000 });
  return payload;
}

const adminApi = await request.newContext({ baseURL, storageState: storageStatePath });
const adminSession = await jsonResponse(
  await adminApi.get("/v1/auth/session"),
  "read admin session",
);
const mutationHeaders = { Origin: baseURL, "X-CSRF-Token": adminSession.csrfToken };
let firstParticipant;
let secondParticipant;
let roomId;
let roomDeleted = false;

async function currentOccurrence() {
  if (!roomId) return null;
  const dashboard = await jsonResponse(
    await adminApi.get("/v1/admin/rooms"),
    "read admin dashboard",
  );
  return dashboard.rooms.find((item) => item.room.id === roomId)?.currentOccurrence ?? null;
}

async function finishActiveOccurrence() {
  const current = await currentOccurrence().catch(() => null);
  if (!current || !["LOBBY", "STARTING", "RUNNING", "ENDING"].includes(current.status)) return;
  await adminApi.post(`/v1/admin/occurrences/${current.id}:end`, {
    headers: mutationHeaders,
    data: { reason: "voice_smoke_cleanup" },
  }).catch(() => undefined);
}

async function waitForIdle() {
  return waitUntil(
    "post-meeting processing",
    async () => ((await currentOccurrence()) === null ? true : false),
    180_000,
    5_000,
  );
}

try {
  const created = await jsonResponse(
    await adminApi.post("/v1/admin/rooms", {
      headers: mutationHeaders,
      data: {
        name: `Deployed ${smokeRole.toLowerCase()} voice smoke ${Date.now()}`,
        expectedParticipants: 2,
        durationMinutes: 5,
        role: smokeRole,
        agentName: "Nova",
        instructions: smokeInstructions,
        game: smokeGame,
      },
    }),
    "create smoke room",
  );
  roomId = created.room.id;

  const firstSlot = created.seatUrls[0].slotId;
  const secondSlot = created.seatUrls[1].slotId;
  await jsonResponse(
    await adminApi.put(`/v1/admin/rooms/${roomId}/slots/${secondSlot}:end-meeting-permission`, {
      headers: mutationHeaders,
      data: { allowed: true },
    }),
    "delegate participant end permission",
  );

  firstParticipant = await launchParticipant(firstAudio);
  secondParticipant = await launchParticipant(secondAudio);
  const firstJoin = await joinParticipant(
    firstParticipant.page,
    created.seatUrls[0].url,
    roomId,
    created.room.name,
    "Ada Smoke",
  );
  const secondJoin = await joinParticipant(
    secondParticipant.page,
    created.seatUrls[1].url,
    roomId,
    created.room.name,
    "Ben Smoke",
  );
  if (firstJoin.occurrence.id !== secondJoin.occurrence.id) {
    throw new Error("Participants joined different occurrences");
  }
  const firstOccurrenceId = secondJoin.occurrence.id;
  const voiceStartedAt = Date.now();
  let lastProgressAt = 0;

  const voiceEvidence = await waitUntil("two-participant voice handoff", async () => {
    const response = await adminApi.get(`/v1/admin/occurrences/${firstOccurrenceId}/transcript`);
    const transcript = await jsonResponse(response, "read smoke transcript");
    const firstSegments = transcript.filter(
      (segment) => segment.speakerType === "SEAT" && segment.speakerId === firstSlot,
    );
    const secondSegments = transcript.filter(
      (segment) => segment.speakerType === "SEAT" && segment.speakerId === secondSlot,
    );
    const agentSegments = transcript.filter((segment) => segment.speakerType === "AGENT");
    if (Date.now() - lastProgressAt >= 12_000) {
      lastProgressAt = Date.now();
      const state = await currentOccurrence();
      const floor =
        state?.currentFloorType === "SEAT"
          ? state.currentFloorSlotId === firstSlot
            ? "seat-1"
            : state.currentFloorSlotId === secondSlot
              ? "seat-2"
              : "unknown-seat"
          : state?.currentFloorType?.toLowerCase();
      const nextFloor =
        state?.nextFloorSlotId === firstSlot
          ? "seat-1"
          : state?.nextFloorSlotId === secondSlot
            ? "seat-2"
            : null;
      console.log(
        JSON.stringify({
          elapsedSeconds: Math.round((Date.now() - voiceStartedAt) / 1000),
          status: state?.status,
          floor,
          nextFloor,
          seat1Segments: firstSegments.length,
          seat2Segments: secondSegments.length,
          agentSegments: agentSegments.length,
        }),
      );
    }
    if (firstSegments.length === 0 || secondSegments.length === 0) return null;
    const secondFloorSequence = Math.max(...secondSegments.map((segment) => segment.sequence));
    const agentAfterSecond = transcript.some(
      (segment) => segment.speakerType === "AGENT" && segment.sequence > secondFloorSequence,
    );
    if (!agentAfterSecond) return null;
    return {
      transcriptSegments: transcript.length,
      humanSpeakersHeard: 2,
      agentRespondedAfterSecond: true,
    };
  });

  const closingCaption = await waitUntil("complete natural closing recap", async () => {
    const response = await adminApi.get(`/v1/admin/occurrences/${firstOccurrenceId}/transcript`);
    const transcript = await jsonResponse(response, "read natural closing transcript");
    const lastHumanSequence = Math.max(
      ...transcript
        .filter((segment) => segment.speakerType === "SEAT")
        .map((segment) => segment.sequence),
    );
    const closingText = transcript
      .filter(
        (segment) => segment.speakerType === "AGENT" && segment.sequence > lastHumanSequence,
      )
      .map((segment) => segment.text)
      .join(" ");
    const completeSentences = closingText.match(/[.!?](?:\s|$)/g)?.length ?? 0;
    if (completeSentences < 3) return null;
    return { completeSentences, characters: closingText.length };
  }, 120_000, 2_000);

  // The first occurrence must become idle without an admin/API end. This is
  // the deployed regression for deferred finish plus complete audio playout.
  const naturalClosingStartedAt = Date.now();
  await waitForIdle();
  const naturalClosingSeconds = (Date.now() - naturalClosingStartedAt) / 1000;

  await firstParticipant.page.getByRole("heading", { name: "Meeting summary" }).waitFor({
    timeout: 30_000,
  });
  for (const label of ["Date", "Time", "Duration", "Audio quality", "MEETING SUMMARY"]) {
    await firstParticipant.page.getByText(label, { exact: true }).waitFor();
  }
  await firstParticipant.page.getByRole("link", { name: /return to home workspace/i }).click();
  await firstParticipant.page.getByRole("heading", { name: /let ai lead the conversation forward/i }).waitFor();

  const leaveJoin = await joinParticipant(
    firstParticipant.page,
    `${baseURL}/join/${roomId}`,
    roomId,
    created.room.name,
    "Ada Smoke",
    false,
  );
  firstParticipant.page.once("dialog", (dialog) => dialog.accept());
  await firstParticipant.page.getByRole("button", { name: /leave meeting/i }).click();
  await firstParticipant.page
    .getByRole("heading", { name: /meeting can continue without you/i })
    .waitFor({ timeout: 15_000 });
  await waitUntil("participant leave propagation", async () => {
    const occurrence = await currentOccurrence();
    if (occurrence?.id !== leaveJoin.occurrence.id) return false;
    const attendance = occurrence?.attendance?.[firstSlot];
    return attendance?.connected === false && Boolean(attendance.leftAt);
  }, 30_000, 1_000);
  await waitForIdle();

  await joinParticipant(
    secondParticipant.page,
    `${baseURL}/join/${roomId}`,
    roomId,
    created.room.name,
    "Ben Smoke",
    false,
  );
  secondParticipant.page.once("dialog", (dialog) => dialog.accept());
  await secondParticipant.page.getByRole("button", { name: /end for everyone/i }).click();
  await secondParticipant.page.getByText(/turning the conversation into a recap/i).waitFor({
    timeout: 20_000,
  });
  await waitForIdle();

  const adminEndJoin = await joinParticipant(
    firstParticipant.page,
    `${baseURL}/join/${roomId}`,
    roomId,
    created.room.name,
    "Ada Smoke",
    false,
  );
  await jsonResponse(
    await adminApi.post(`/v1/admin/occurrences/${adminEndJoin.occurrence.id}:end`, {
      headers: mutationHeaders,
      data: { reason: "voice_smoke_admin_end" },
    }),
    "admin end meeting",
  );
  await waitForIdle();

  await jsonResponse(
    await adminApi.delete(`/v1/admin/rooms/${roomId}`, { headers: mutationHeaders }),
    "delete smoke room",
  );
  roomDeleted = true;
  console.log(
    JSON.stringify({
      status: "passed",
      voiceEvidence,
      closingCaption,
      naturalClosingSeconds,
      participantLeave: true,
      delegatedParticipantEnd: true,
      rememberedMicrophone: true,
      securedHomeBoundary: true,
      completionMetadata: true,
      adminEnd: true,
      cleanup: "smoke room deleted",
    }),
  );
} finally {
  if (!roomDeleted && roomId) {
    await finishActiveOccurrence().catch(() => undefined);
    await waitForIdle().catch(() => undefined);
    await adminApi.delete(`/v1/admin/rooms/${roomId}`, { headers: mutationHeaders }).catch(() => undefined);
  }
  await Promise.allSettled([
    firstParticipant?.context.close(),
    secondParticipant?.context.close(),
  ]);
  await Promise.allSettled([
    firstParticipant?.browser.close(),
    secondParticipant?.browser.close(),
    adminApi.dispose(),
  ]);
}
