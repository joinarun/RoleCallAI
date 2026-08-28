import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const here = dirname(fileURLToPath(import.meta.url));
const outputDir = resolve(here, "../test-results/previews");
const webBase = process.env.ROLECALL_PREVIEW_WEB_URL ?? "http://127.0.0.1:5173";
const apiBase = process.env.ROLECALL_PREVIEW_API_URL ?? "http://127.0.0.1:8000";

await mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
});

try {
  const desktop = await browser.newContext({
    baseURL: webBase,
    viewport: { width: 1440, height: 960 },
  });
  const desktopPage = await desktop.newPage();
  await desktopPage.goto("/");
  await desktopPage.getByRole("heading", { name: /give every meeting/i }).waitFor();
  await desktopPage.screenshot({ path: resolve(outputDir, "create-desktop.png"), fullPage: true });

  const roomResponse = await desktopPage.request.post(`${apiBase}/v1/rooms`, {
    data: {
      name: `Roadmap Lab · ${String(Date.now()).slice(-4)}`,
      expectedParticipants: 4,
      durationMinutes: 20,
      role: "BRAINSTORM",
      agentName: "Orbit",
      instructions:
        "Frame the topic, gather divergent ideas, cluster themes, and turn the top ideas into assigned next steps.",
      game: null,
    },
  });
  if (!roomResponse.ok()) {
    throw new Error(`Could not create preview room (${roomResponse.status()})`);
  }
  const created = await roomResponse.json();

  await desktopPage.goto(created.adminUrl);
  await desktopPage.getByText("Room is idle").waitFor();
  await desktopPage.screenshot({
    path: resolve(outputDir, "admin-overview-desktop.png"),
    fullPage: true,
  });
  await desktop.close();

  const mobile = await browser.newContext({
    baseURL: webBase,
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    permissions: ["microphone"],
  });
  const mobilePage = await mobile.newPage();
  await mobilePage.goto(created.seatUrls[0].url);
  await mobilePage.getByRole("heading", { name: /sound good/i }).waitFor();
  await mobilePage.screenshot({
    path: resolve(outputDir, "participant-lobby-mobile.png"),
    fullPage: true,
  });

  await mobilePage.getByLabel("Your name").fill("Ada");
  await mobilePage.getByRole("button", { name: /run check/i }).click();
  await mobilePage.getByText("Microphone ready").waitFor();
  await mobilePage.getByRole("checkbox").check();
  await mobilePage.getByRole("button", { name: /enter voice room/i }).click();
  await mobilePage.getByRole("heading", { name: /roadmap lab/i }).waitFor();
  await mobilePage.getByText("LOBBY", { exact: true }).waitFor();
  await mobilePage.screenshot({
    path: resolve(outputDir, "meeting-mobile.png"),
    fullPage: true,
  });
  await mobile.close();

  process.stdout.write(`Captured UI previews in ${outputDir}\n`);
} finally {
  await browser.close();
}
