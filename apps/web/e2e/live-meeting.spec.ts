import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import { apiURL, createRoom, newVoiceContext, prepareSeat } from "./helpers";

test.skip(process.env.ROLECALL_E2E_LIVEKIT !== "1", "requires the local LiveKit transport");

const here = dirname(fileURLToPath(import.meta.url));
const agentProject = resolve(here, "../../../services/rolecall-agent");
const controlScript = resolve(here, "helpers/livekit_control.py");

function livekitControl<T>(...args: string[]): T {
  const output = execFileSync(
    "uv",
    ["run", "--project", agentProject, "python", controlScript, ...args],
    {
      encoding: "utf8",
      env: {
        ...process.env,
        LIVEKIT_URL: "http://127.0.0.1:7880",
        LIVEKIT_API_KEY:
          process.env.LIVEKIT_API_KEY ?? "replace-with-local-livekit-api-key",
        LIVEKIT_API_SECRET:
          process.env.LIVEKIT_API_SECRET ?? "replace-with-local-livekit-secret-at-least-32-bytes",
      },
    },
  );
  return JSON.parse(output) as T;
}

test("two synthetic-mic participants receive floor, captions, and recap", async ({
  browser,
  request,
}) => {
  const created = await createRoom(request, `Live transport ${Date.now()}`);
  const firstContext = await newVoiceContext(browser);
  const secondContext = await newVoiceContext(browser);
  const firstPage = await firstContext.newPage();
  const secondPage = await secondContext.newPage();
  let occurrenceId: string | undefined;

  try {
    await prepareSeat(firstPage, created.seatUrls[0].url, "Ada");
    const firstJoinResponse = firstPage.waitForResponse(
      (response) => response.url().endsWith(`${created.room.id}:join`) && response.request().method() === "POST",
    );
    await firstPage.getByRole("button", { name: /enter voice room/i }).click();
    const firstJoin = await (await firstJoinResponse).json();

    await prepareSeat(secondPage, created.seatUrls[1].url, "Ben");
    const secondJoinResponse = secondPage.waitForResponse(
      (response) => response.url().endsWith(`${created.room.id}:join`) && response.request().method() === "POST",
    );
    await secondPage.getByRole("button", { name: /enter voice room/i }).click();
    const secondResponse = await secondJoinResponse;
    expect(secondResponse.ok()).toBeTruthy();
    const secondJoin = await secondResponse.json();

    const occurrence = secondJoin.occurrence;
    occurrenceId = occurrence.id;
    expect(firstJoin.occurrence.id).toBe(occurrence.id);
    await expect(firstPage.getByText("connected", { exact: true })).toBeVisible({ timeout: 5_000 });
    await expect(secondPage.getByText("connected", { exact: true })).toBeVisible({ timeout: 5_000 });

    await expect
      .poll(() => livekitControl<Array<{ identity: string }>>("participants", occurrence.id).length)
      .toBe(2);

    const firstSlot = created.seatUrls[0].slotId;
    const secondSlot = created.seatUrls[1].slotId;
    livekitControl("permission", occurrence.id, `seat:${firstSlot}`, "--can-publish");
    const runningState = {
      ...occurrence,
      status: "RUNNING",
      currentFloorType: "SEAT",
      currentFloorSlotId: firstSlot,
      handRaiseQueue: [secondSlot],
      sequence: occurrence.sequence + 1,
    };
    livekitControl(
      "send",
      occurrence.id,
      JSON.stringify({
        v: 1,
        type: "meeting.state",
        occurrenceId: occurrence.id,
        sequence: runningState.sequence,
        payload: runningState,
      }),
    );

    const microphoneControl = firstPage.getByRole("button", { name: /^(mute|unmute)$/i });
    await expect(microphoneControl).toBeEnabled();
    if ((await microphoneControl.innerText()).trim() === "Unmute") await microphoneControl.click();
    await expect(firstPage.getByText("You own the floor")).toBeVisible();
    await expect(secondPage.getByRole("button", { name: "Hand raised" })).toBeDisabled();
    await expect
      .poll(() => {
        const people = livekitControl<Array<{ identity: string; tracks: number }>>(
          "participants",
          occurrence.id,
        );
        return people.find((item) => item.identity === `seat:${firstSlot}`)?.tracks ?? 0;
      })
      .toBeGreaterThan(0);

    const now = new Date().toISOString();
    const caption = {
      id: "caption-e2e",
      occurrenceId: occurrence.id,
      sequence: 1,
      speakerType: "AGENT",
      speakerId: "agent",
      speakerName: "Nova",
      text: "The pilot starts with three design partners.",
      startedAt: now,
      endedAt: now,
      expiresAt: new Date(Date.now() + 90 * 86_400_000).toISOString(),
    };
    livekitControl(
      "send",
      occurrence.id,
      JSON.stringify({
        v: 1,
        type: "caption.final",
        occurrenceId: occurrence.id,
        sequence: runningState.sequence + 1,
        payload: caption,
      }),
    );
    await expect(firstPage.getByText(caption.text)).toBeVisible();

    const recap = {
      summary: "The group agreed to test onboarding with three design partners.",
      decisions: ["Run the pilot"],
      actions: [{ text: "Ada will recruit design partners", ownerSlotId: firstSlot }],
      blockers: [],
      ideas: ["Guided onboarding checklist"],
      gameResults: [],
      generatedAt: now,
    };
    await firstPage.route(`${apiURL}/v1/occurrences/${occurrence.id}/recap`, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(recap) }),
    );
    const processingState = {
      ...runningState,
      status: "PROCESSING",
      currentFloorType: "AGENT",
      currentFloorSlotId: null,
      sequence: runningState.sequence + 2,
    };
    livekitControl(
      "send",
      occurrence.id,
      JSON.stringify({
        v: 1,
        type: "meeting.state",
        occurrenceId: occurrence.id,
        sequence: processingState.sequence,
        payload: processingState,
      }),
    );
    await expect(firstPage.getByRole("heading", { name: "Clear words. Concrete next steps." })).toBeVisible({ timeout: 8_000 });
    await expect(firstPage.getByText(recap.summary)).toBeVisible();
  } finally {
    await firstContext.close();
    await secondContext.close();
    if (occurrenceId) {
      try {
        livekitControl("delete", occurrenceId);
      } catch {
        // The local LiveKit process teardown also removes test rooms.
      }
    }
  }
});
