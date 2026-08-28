import { expect, type APIRequestContext, type Browser, type BrowserContext, type Page } from "@playwright/test";

export const apiURL = "http://127.0.0.1:8000";

export type CreatedRoom = {
  room: {
    id: string;
    name: string;
    slots: Array<{ id: string; ordinal: number }>;
  };
  adminUrl: string;
  seatUrls: Array<{ slotId: string; url: string }>;
};

export async function createRoom(
  request: APIRequestContext,
  name: string,
  expectedParticipants = 2,
): Promise<CreatedRoom> {
  const response = await request.post(`${apiURL}/v1/rooms`, {
    data: {
      name,
      expectedParticipants,
      durationMinutes: 5,
      role: "SCRUM_MASTER",
      agentName: "Nova",
      instructions: "Keep updates concise and ask about blockers.",
      game: null,
    },
  });
  expect(response.ok()).toBeTruthy();
  return response.json() as Promise<CreatedRoom>;
}

export async function newVoiceContext(browser: Browser): Promise<BrowserContext> {
  return browser.newContext({
    baseURL: "http://127.0.0.1:5173",
    permissions: ["microphone"],
  });
}

export async function prepareSeat(page: Page, seatUrl: string, name: string): Promise<void> {
  await page.goto(seatUrl);
  await expect(page).toHaveURL((url) => url.hash === "");
  await expect(page.getByRole("heading", { name: /sound good/i })).toBeVisible();
  await page.getByLabel("Your name").fill(name);
  await page.getByRole("button", { name: /run check/i }).click();
  await expect(page.getByText("Microphone ready")).toBeVisible();
  await page.getByRole("checkbox").check();
}
