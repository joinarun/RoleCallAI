import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { JoinRoomPage } from "./JoinRoomPage";

const originalMediaDevices = navigator.mediaDevices;
const originalPermissions = navigator.permissions;

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: originalMediaDevices });
  Object.defineProperty(navigator, "permissions", { configurable: true, value: originalPermissions });
});

test("reuses a successful microphone check when browser permission is still granted", async () => {
  history.replaceState(null, "", "/join/room-1#cap=super-secret-token-value-that-is-long");
  localStorage.setItem("rolecall-microphone-ready:v1", "ready");
  const getUserMedia = vi.fn();
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
  Object.defineProperty(navigator, "permissions", {
    configurable: true,
    value: {
      query: vi.fn().mockResolvedValue({
        state: "granted",
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    },
  });
  vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request) => {
    const url = String(input);
    if (url.includes("capability-sessions")) {
      return new Response(JSON.stringify({ roomId: "room-1", scope: "SEAT", slotId: "slot-1", expiresAt: new Date(Date.now() + 60_000).toISOString() }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    return new Response(JSON.stringify({
      id: "room-1",
      name: "Mobile sync",
      expectedParticipants: 2,
      durationMinutes: 15,
      role: "SCRUM_MASTER",
      agentName: "Nova",
      slots: [{ id: "slot-1", ordinal: 1, lastDisplayName: "Arun", canEndMeeting: false }],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }), { status: 200, headers: { "Content-Type": "application/json" } });
  }));

  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={["/join/room-1"]}>
      <Routes><Route path="/join/:roomId" element={<JoinRoomPage />} /></Routes>
    </MemoryRouter>,
  );

  expect(await screen.findByText("Previously approved microphone")).toBeInTheDocument();
  expect(getUserMedia).not.toHaveBeenCalled();
  await user.click(screen.getByRole("checkbox"));
  expect(screen.getByRole("button", { name: /enter voice room/i })).toBeEnabled();
});
