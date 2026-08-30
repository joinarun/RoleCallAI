import { expect, test } from "@playwright/test";

import { createRoom, loginPage, newVoiceContext, prepareSeat } from "./helpers";

test("admin logs in, creates a private room, and manages it in the dashboard", async ({ page }, testInfo) => {
  const name = `Friday Studio ${testInfo.project.name} ${Date.now()}`;
  await loginPage(page);
  await page.getByRole("button", { name: /create room/i }).click();

  await page.getByLabel("Room name").fill(name);
  await page.getByLabel("Participants").selectOption("2");
  await page.getByLabel("Duration").selectOption("5");
  await page.getByRole("button", { name: /continue/i }).click();
  await page.getByRole("radio", { name: /fun friday/i }).click();
  await page.getByRole("button", { name: /continue/i }).click();
  await page.getByLabel("Agent name").fill("Pixel");
  await page.getByLabel("Game", { exact: true }).selectOption("CATEGORIES");
  await page.getByLabel("How should the agent run it?").fill("Run two fair rounds and keep the pace warm.");
  await page.getByRole("button", { name: /create private room/i }).click();

  await expect(page.getByText("Room ready")).toBeVisible();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await expect(page.getByText("Participant links")).toBeVisible();
  await expect(page.locator(".seat-link")).toHaveCount(2);
  await page.getByRole("button", { name: /return to dashboard/i }).click();

  const card = page.locator(".dashboard-room-card").filter({ has: page.getByRole("heading", { name, exact: true }) });
  await expect(card).toContainText("Pixel · Fun Friday");
  await card.getByRole("button", { name: /manage room/i }).click();
  await expect(card.getByText("Participants and links")).toBeVisible();
  await expect(card.locator(".dashboard-seat")).toHaveCount(2);
  await card.getByLabel("Agent name").fill("Pixel Prime");
  await card.getByLabel("Seats").fill("3");
  await card.getByRole("button", { name: /save settings/i }).click();
  await expect(card).toContainText("Pixel Prime · Fun Friday");

  await card.getByRole("button", { name: /close controls/i }).click();
  await card.getByRole("button", { name: /manage room/i }).click();
  await expect(card.locator(".dashboard-seat")).toHaveCount(3);
  await card.locator(".permission-toggle input").first().click();
  await expect(card.locator(".permission-toggle input").first()).toBeChecked();
  await expect(card.getByText("Meeting documents")).toBeVisible();
  await expect(page.getByRole("heading", { name: /recent conversations/i })).toBeVisible();
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
  await firstPage.reload();
  await expect(firstPage.getByText(/previously approved microphone/i)).toBeVisible();
  await firstPage.getByLabel("Your name").fill("Ada");
  await firstPage.getByRole("checkbox").check();
  await firstPage.getByRole("button", { name: /enter voice room/i }).click();
  await expect(firstPage.getByRole("heading", { name: created.room.name })).toBeVisible();
  await expect(firstPage.getByText("LOBBY", { exact: true })).toBeVisible();
  await expect(firstPage.getByRole("button", { name: /mic unlocks on your turn/i })).toBeDisabled();

  const secondContext = await newVoiceContext(browser);
  const secondPage = await secondContext.newPage();
  await prepareSeat(secondPage, seatUrl, "Ada duplicate");
  await secondPage.getByRole("button", { name: /enter voice room/i }).click();
  await expect(secondPage.getByRole("alert")).toContainText(/already connected/i);

  firstPage.once("dialog", (dialog) => dialog.accept());
  await firstPage.getByRole("button", { name: /leave meeting/i }).click();
  await expect(firstPage.getByRole("heading", { name: /meeting can continue without you/i })).toBeVisible();

  await secondContext.close();
  await firstContext.close();
});
