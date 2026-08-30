import { expect, type APIRequestContext, type Browser, type BrowserContext, type Page } from "@playwright/test";

export const apiURL = "http://127.0.0.1:8000";
export const webURL = "http://127.0.0.1:5173";

export type CreatedRoom = {
  room: {
    id: string;
    name: string;
    expectedParticipants: number;
    slots: Array<{ id: string; ordinal: number }>;
  };
  seatUrls: Array<{ slotId: string; url: string }>;
};

export async function loginAdmin(request: APIRequestContext): Promise<Record<string, string>> {
  const response = await request.post(`${apiURL}/v1/auth/login`, {
    headers: { Origin: webURL },
    data: {
      username: "judge-local",
      password: "local-rolecall-admin-password",
      recaptchaToken: "playwright-local-verification",
    },
  });
  expect(response.ok()).toBeTruthy();
  const session = await response.json();
  return { Origin: webURL, "X-CSRF-Token": session.csrfToken };
}

export async function loginPage(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /let ai lead the conversation forward/i })).toBeVisible();
  await page.getByLabel("Username").fill("judge-local");
  await page.getByLabel("Password").fill("local-rolecall-admin-password");
  const submit = page.getByRole("button", { name: /sign in securely/i });
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(page.getByRole("heading", { name: /rooms, people and outcomes/i })).toBeVisible();
}

export async function createRoom(
  request: APIRequestContext,
  name: string,
  expectedParticipants = 2,
): Promise<CreatedRoom> {
  const headers = await loginAdmin(request);
  const response = await request.post(`${apiURL}/v1/admin/rooms`, {
    headers,
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
    baseURL: webURL,
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
