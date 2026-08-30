import { access } from "node:fs/promises";

import { chromium, request } from "@playwright/test";

const baseURL = process.env.ROLECALL_SMOKE_BASE_URL?.replace(/\/$/, "");
const storageStatePath = process.env.ROLECALL_SMOKE_ADMIN_STORAGE_STATE;
if (!baseURL || !storageStatePath) {
  throw new Error("Set ROLECALL_SMOKE_BASE_URL and ROLECALL_SMOKE_ADMIN_STORAGE_STATE.");
}
await access(storageStatePath);

async function jsonResponse(response, operation) {
  if (!response.ok()) throw new Error(`${operation} failed with HTTP ${response.status()}`);
  return response.json();
}

const adminApi = await request.newContext({ baseURL, storageState: storageStatePath });
let browser;

try {
  const before = await jsonResponse(await adminApi.get("/v1/runtime"), "read sleeping runtime");
  if (before.status !== "SLEEPING") {
    throw new Error(`Expected SLEEPING runtime, received ${before.status}`);
  }

  const dashboard = await jsonResponse(await adminApi.get("/v1/admin/rooms"), "read dashboard");
  const fixture = dashboard.rooms.find((item) => item.room.slots.length > 0 && !item.currentOccurrence);
  if (!fixture) throw new Error("No idle room with a participant seat is available");
  await jsonResponse(
    await adminApi.get(`/v1/admin/rooms/${fixture.room.id}/documents`),
    "read sleeping document library",
  );

  const links = await jsonResponse(
    await adminApi.get(`/v1/admin/rooms/${fixture.room.id}/seat-links`),
    "recover participant link",
  );
  const participantURL = links[0]?.url;
  if (!participantURL) throw new Error("The selected room has no recoverable participant link");

  browser = await chromium.launch({
    headless: true,
    args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
  });
  const context = await browser.newContext({ baseURL, permissions: ["microphone"] });
  const page = await context.newPage();
  await page.goto(participantURL);
  await page.getByRole("heading", { name: /sound good/i }).waitFor();
  await page.getByLabel("Your name").fill("Sleeping Runtime Check");
  await page.getByRole("button", { name: /run check/i }).click();
  await page.getByText("Microphone ready").waitFor();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: /enter voice room/i }).click();
  await page.getByRole("alert").filter({ hasText: /voice services are sleeping/i }).waitFor();

  const after = await jsonResponse(await adminApi.get("/v1/runtime"), "re-read sleeping runtime");
  const refreshed = await jsonResponse(await adminApi.get("/v1/admin/rooms"), "re-read dashboard");
  const roomAfter = refreshed.rooms.find((item) => item.room.id === fixture.room.id);
  if (after.status !== "SLEEPING" || after.generation !== before.generation) {
    throw new Error("Participant activity changed or woke the sleeping runtime");
  }
  if (roomAfter?.currentOccurrence) {
    throw new Error("A sleeping participant join created an occurrence");
  }

  console.log(JSON.stringify({
    status: "passed",
    participantReachedLobby: true,
    typedSleepingMessage: true,
    runtimeRemainedSleeping: true,
    occurrenceCreated: false,
    dashboardAvailable: true,
    documentLibraryAvailable: true,
  }));
} finally {
  await browser?.close();
  await adminApi.dispose();
}
