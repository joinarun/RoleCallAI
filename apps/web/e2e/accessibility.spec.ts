import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { createRoom } from "./helpers";

const wcagTags = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function expectWcagClean(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(wcagTags).analyze();
  const summary = results.violations
    .map((violation) => {
      const targets = violation.nodes.map((node) => node.target.join(" ")).join(", ");
      return `${violation.id}: ${violation.help} (${targets})`;
    })
    .join("\n");

  expect(results.violations, summary).toEqual([]);
}

test("creation flow is WCAG AA clean, keyboard reachable, and responsive", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /let ai lead the conversation forward/i })).toBeVisible();

  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: /skip to content/i })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();

  const fitsViewport = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(fitsViewport).toBeTruthy();
  await expectWcagClean(page);
});

test("admin and participant entry surfaces are WCAG AA clean", async ({ page, request }, testInfo) => {
  const created = await createRoom(
    request,
    `Accessibility ${testInfo.project.name} ${Date.now()}`,
  );

  await page.goto(created.adminUrl);
  await expect(page).toHaveURL((url) => url.pathname.startsWith("/manage/") && url.hash === "");
  await expect(page.getByText("Room is idle")).toBeVisible();
  await expectWcagClean(page);

  await page.goto(created.seatUrls[0].url);
  await expect(page).toHaveURL((url) => url.pathname.startsWith("/join/") && url.hash === "");
  await expect(page.getByRole("heading", { name: /sound good/i })).toBeVisible();
  await expectWcagClean(page);

  await page.getByLabel("Your name").fill("Ada");
  await page.getByRole("button", { name: /run check/i }).click();
  await expect(page.getByText("Microphone ready")).toBeVisible();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: /enter voice room/i }).click();
  await expect(page.getByText("LOBBY", { exact: true })).toBeVisible();
  await expectWcagClean(page);
});

test("private home workspace is WCAG AA clean and responsive", async ({ page, request }, testInfo) => {
  const created = await createRoom(
    request,
    `Workspace accessibility ${testInfo.project.name} ${Date.now()}`,
  );

  await page.goto("/");
  await page.evaluate((room) => {
    sessionStorage.setItem(`rolecall-links:${room.room.id}`, JSON.stringify(room));
  }, created);
  await page.reload();

  await expect(page.getByRole("heading", { name: /rooms, people and outcomes/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: created.room.name, exact: true })).toBeVisible();
  await expect(page.locator(".dashboard-seat")).toHaveCount(2);
  const fitsViewport = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(fitsViewport).toBeTruthy();
  await expectWcagClean(page);
});
