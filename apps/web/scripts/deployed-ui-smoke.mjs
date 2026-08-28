import { chromium, request } from "@playwright/test";

const baseURL = process.env.ROLECALL_SMOKE_BASE_URL?.replace(/\/$/, "");
if (!baseURL) throw new Error("Set ROLECALL_SMOKE_BASE_URL.");

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function jsonResponse(response, operation) {
  if (!response.ok()) {
    throw new Error(`${operation} failed with HTTP ${response.status()}`);
  }
  if (response.status() === 204) return null;
  return response.json();
}

async function waitUntil(label, operation, timeoutMs = 180_000, intervalMs = 2_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = await operation();
    if (value) return value;
    await delay(intervalMs);
  }
  throw new Error(`${label} did not complete within ${Math.round(timeoutMs / 1000)} seconds`);
}

const publicApi = await request.newContext({ baseURL });
const adminApi = await request.newContext({ baseURL });
let browser;
let roomId;
let roomDeleted = false;

async function currentOccurrence() {
  if (!roomId) return null;
  const response = await adminApi.get(`/v1/rooms/${roomId}/current-occurrence`);
  return jsonResponse(response, "read current occurrence");
}

async function waitForIdle() {
  return waitUntil("post-meeting processing", async () => {
    return (await currentOccurrence()) === null;
  });
}

try {
  const created = await jsonResponse(
    await publicApi.post("/v1/rooms", {
      data: {
        name: `Deployed UI smoke ${Date.now()}`,
        expectedParticipants: 2,
        durationMinutes: 5,
        role: "SCRUM_MASTER",
        agentName: "Nova",
        instructions: "Keep this UI verification concise.",
        game: null,
      },
    }),
    "create UI smoke room",
  );
  roomId = created.room.id;

  const adminToken = new URLSearchParams(new URL(created.adminUrl).hash.slice(1)).get("cap");
  if (!adminToken) throw new Error("Admin capability was not returned");
  await jsonResponse(
    await adminApi.post("/v1/capability-sessions", {
      data: { roomId, token: adminToken },
    }),
    "exchange admin capability",
  );

  const updated = await jsonResponse(
    await adminApi.patch(`/v1/rooms/${roomId}`, {
      data: { agentName: "Nova Prime", durationMinutes: 10 },
    }),
    "update room settings",
  );
  if (updated.room.agentName !== "Nova Prime" || updated.room.durationMinutes !== 10) {
    throw new Error("Room settings did not persist their camelCase API fields");
  }

  browser = await chromium.launch({
    headless: true,
    args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
  });
  const context = await browser.newContext({ baseURL, permissions: ["microphone"] });
  const page = await context.newPage();

  await page.goto("/");
  await page.evaluate((room) => {
    sessionStorage.setItem(`rolecall-links:${room.room.id}`, JSON.stringify(room));
  }, created);
  await page.reload();
  await page.getByRole("heading", { name: /rooms, people and outcomes/i }).waitFor();
  await page.getByRole("heading", { name: created.room.name, exact: true }).waitFor();
  await page.getByText("Nova Prime · Scrum Master", { exact: true }).waitFor();
  if ((await page.locator(".dashboard-seat").count()) !== 2) {
    throw new Error("Home workspace did not render both participant links");
  }

  await page.goto(created.seatUrls[0].url);
  await page.getByRole("heading", { name: /sound good/i }).waitFor();
  await page.getByLabel("Your name").fill("UI Smoke Person");
  await page.getByRole("button", { name: /run check/i }).click();
  await page.getByText("Microphone ready").waitFor();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: /enter voice room/i }).click();
  await page.getByText("LOBBY", { exact: true }).waitFor({ timeout: 20_000 });

  const occurrence = await currentOccurrence();
  await jsonResponse(
    await adminApi.post(`/v1/occurrences/${occurrence.id}:end`),
    "end UI smoke meeting",
  );
  await page.getByRole("heading", { name: "Meeting summary" }).waitFor({ timeout: 180_000 });
  for (const label of ["Date", "Time", "Duration", "Audio quality", "MEETING SUMMARY"]) {
    await page.getByText(label, { exact: true }).waitFor();
  }
  const summary = (await page.locator(".recap-summary").textContent())?.trim();
  if (!summary) throw new Error("Completed meeting did not render its recap summary");

  await page.getByRole("link", { name: /return to home workspace/i }).click();
  await page.getByRole("heading", { name: /rooms, people and outcomes/i }).waitFor();
  await waitUntil("home workspace history", async () => {
    return (await page.locator(".workspace-history-row").count()) === 1;
  }, 30_000, 1_000);
  await page.getByText("UI Smoke Person", { exact: true }).first().waitFor();

  await waitForIdle();
  await jsonResponse(await adminApi.delete(`/v1/rooms/${roomId}`), "delete UI smoke room");
  roomDeleted = true;
  console.log(JSON.stringify({
    status: "passed",
    dashboard: true,
    settingsPersistence: true,
    completionMetadata: true,
    meetingHistory: true,
    cleanup: "smoke room deleted",
  }));
} finally {
  if (!roomDeleted && roomId) {
    const active = await currentOccurrence().catch(() => null);
    if (active && ["LOBBY", "STARTING", "RUNNING", "ENDING"].includes(active.status)) {
      await adminApi.post(`/v1/occurrences/${active.id}:end`).catch(() => undefined);
    }
    await waitForIdle().catch(() => undefined);
    await adminApi.delete(`/v1/rooms/${roomId}`).catch(() => undefined);
  }
  await Promise.allSettled([browser?.close(), publicApi.dispose(), adminApi.dispose()]);
}
