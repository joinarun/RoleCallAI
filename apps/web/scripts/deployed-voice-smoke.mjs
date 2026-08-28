import { access } from "node:fs/promises";

import { chromium, request } from "@playwright/test";

const baseURL = process.env.ROLECALL_SMOKE_BASE_URL?.replace(/\/$/, "");
const firstAudio = process.env.ROLECALL_SMOKE_AUDIO_ONE;
const secondAudio = process.env.ROLECALL_SMOKE_AUDIO_TWO;

if (!baseURL || !firstAudio || !secondAudio) {
  throw new Error(
    "Set ROLECALL_SMOKE_BASE_URL, ROLECALL_SMOKE_AUDIO_ONE, and ROLECALL_SMOKE_AUDIO_TWO.",
  );
}
await Promise.all([access(firstAudio), access(secondAudio)]);

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

const publicApi = await request.newContext({ baseURL });
const adminApi = await request.newContext({ baseURL });
let firstParticipant;
let secondParticipant;
let roomId;
let roomDeleted = false;

async function currentOccurrence() {
  if (!roomId) return null;
  const response = await adminApi.get(`/v1/rooms/${roomId}/current-occurrence`);
  return jsonResponse(response, "read current occurrence");
}

async function finishActiveOccurrence() {
  const current = await currentOccurrence().catch(() => null);
  if (!current || !["LOBBY", "STARTING", "RUNNING", "ENDING"].includes(current.status)) return;
  await adminApi.post(`/v1/occurrences/${current.id}:end`).catch(() => undefined);
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
    await publicApi.post("/v1/rooms", {
      data: {
        name: `Deployed two-person voice smoke ${Date.now()}`,
        expectedParticipants: 2,
        durationMinutes: 5,
        role: "SCRUM_MASTER",
        agentName: "Nova",
        instructions:
          "Run exactly one concise stand-up round and ask each participant once. After both responses, do not open another round. Speak a closing recap with four short, complete numbered sentences, then call finish_meeting as the final action.",
        game: null,
      },
    }),
    "create smoke room",
  );
  roomId = created.room.id;

  const adminUrl = new URL(created.adminUrl);
  const adminToken = new URLSearchParams(adminUrl.hash.slice(1)).get("cap");
  if (!adminToken) throw new Error("Admin capability was not returned");
  await jsonResponse(
    await adminApi.post("/v1/capability-sessions", {
      data: { roomId, token: adminToken },
    }),
    "exchange admin capability",
  );

  const firstSlot = created.seatUrls[0].slotId;
  const secondSlot = created.seatUrls[1].slotId;
  await jsonResponse(
    await adminApi.put(`/v1/rooms/${roomId}/slots/${secondSlot}:end-meeting-permission`, {
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
    const response = await adminApi.get(`/v1/occurrences/${firstOccurrenceId}/transcript`);
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
    const response = await adminApi.get(`/v1/occurrences/${firstOccurrenceId}/transcript`);
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
    const response = await adminApi.get(`/v1/occurrences/${leaveJoin.occurrence.id}/state`);
    const occurrence = await jsonResponse(response, "read leave occurrence");
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
    await adminApi.post(`/v1/occurrences/${adminEndJoin.occurrence.id}:end`),
    "admin end meeting",
  );
  await waitForIdle();

  await jsonResponse(await adminApi.delete(`/v1/rooms/${roomId}`), "delete smoke room");
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
      adminEnd: true,
      cleanup: "smoke room deleted",
    }),
  );
} finally {
  if (!roomDeleted && roomId) {
    await finishActiveOccurrence().catch(() => undefined);
    await waitForIdle().catch(() => undefined);
    await adminApi.delete(`/v1/rooms/${roomId}`).catch(() => undefined);
  }
  await Promise.allSettled([
    firstParticipant?.context.close(),
    secondParticipant?.context.close(),
  ]);
  await Promise.allSettled([
    firstParticipant?.browser.close(),
    secondParticipant?.browser.close(),
    publicApi.dispose(),
    adminApi.dispose(),
  ]);
}
