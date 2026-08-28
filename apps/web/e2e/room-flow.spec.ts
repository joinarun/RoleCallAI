import { expect, test } from "@playwright/test";

import { createRoom, newVoiceContext, prepareSeat } from "./helpers";

test("admin creates a private room and opens its management view", async ({ page }, testInfo) => {
  const name = `Friday Studio ${testInfo.project.name} ${Date.now()}`;
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /give every meeting/i })).toBeVisible();

  await page.getByLabel("Room name").fill(name);
  await page.getByLabel("Participants").selectOption("2");
  await page.getByLabel("Duration").selectOption("5");
  await page.getByRole("button", { name: /continue/i }).click();
  await page.getByRole("radio", { name: /fun friday/i }).click();
  await page.getByRole("button", { name: /continue/i }).click();
  await page.getByLabel("Agent name").fill("Pixel");
  await page.getByLabel("Game").selectOption("CATEGORIES");
  await page.getByLabel("How should the agent run it?").fill("Run two fair rounds and keep the pace warm.");
  await page.getByRole("button", { name: /create private room/i }).click();

  await expect(page.getByText("Room ready")).toBeVisible();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await expect(page.getByText("One-time link vault")).toBeVisible();
  await expect(page.getByText("PARTICIPANT SEAT")).toHaveCount(2);

  await page.getByRole("button", { name: /open admin room/i }).click();
  await expect(page).toHaveURL((url) => url.pathname.startsWith("/manage/") && url.hash === "");
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await expect(page.getByText("Room is idle")).toBeVisible();
  await expect(page.getByText("2 invitations")).toBeVisible();
  await page.getByRole("button", { name: /settings/i }).click();
  await page.getByLabel("Agent name").fill("Pixel Prime");
  await page.getByLabel("Participants").selectOption("3");
  await page.getByRole("button", { name: /save settings/i }).click();
  await expect(page.getByRole("status")).toContainText(/newly created seat links/i);
  await page.getByRole("button", { name: /overview/i }).click();
  await expect(page.getByText("3 invitations")).toBeVisible();
  await page.getByRole("button", { name: /history/i }).click();
  await expect(page.getByRole("heading", { name: /meetings and outcomes/i })).toBeVisible();
});

test("seat fragment is removed, synthetic microphone works, and duplicate seat is rejected", async ({
  browser,
  request,
}, testInfo) => {
  const created = await createRoom(
    request,
    `Participant flow ${testInfo.project.name} ${Date.now()}`,
  );
  const seatUrl = created.seatUrls[0].url;

  const firstContext = await newVoiceContext(browser);
  const firstPage = await firstContext.newPage();
  await prepareSeat(firstPage, seatUrl, "Ada");
  await firstPage.getByRole("button", { name: /enter voice room/i }).click();
  await expect(firstPage.getByRole("heading", { name: created.room.name })).toBeVisible();
  await expect(firstPage.getByText("LOBBY", { exact: true })).toBeVisible();
  await expect(firstPage.getByRole("button", { name: /mic unlocks on your turn/i })).toBeDisabled();

  const secondContext = await newVoiceContext(browser);
  const secondPage = await secondContext.newPage();
  await prepareSeat(secondPage, seatUrl, "Ada duplicate");
  await secondPage.getByRole("button", { name: /enter voice room/i }).click();
  await expect(secondPage.getByRole("alert")).toContainText(/already connected/i);

  await secondContext.close();
  await firstContext.close();
});
