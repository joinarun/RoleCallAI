import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { HomePage } from "./HomePage";

afterEach(() => {
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

test("loads every room and meeting from the authenticated admin dashboard", async () => {
  const createdAt = "2026-08-28T09:00:00Z";
  const room = {
    id: "room-1",
    name: "Product sync",
    expectedParticipants: 2,
    durationMinutes: 15,
    role: "SCRUM_MASTER",
    agentName: "Nova",
    instructions: "Keep updates focused.",
    slots: [
      { id: "slot-1", ordinal: 1, lastDisplayName: "Arun", canEndMeeting: false },
      { id: "slot-2", ordinal: 2, lastDisplayName: "Jaya", canEndMeeting: false },
    ],
    createdAt,
    updatedAt: createdAt,
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.endsWith("/v1/auth/session")) return new Response(JSON.stringify({ authenticated: true, username: "judge-demo", ownerId: "shared-demo-admin", expiresAt: "2026-08-28T17:00:00Z", csrfToken: "csrf-token" }), { status: 200, headers: { "Content-Type": "application/json" } });
    if (path.endsWith("/v1/admin/rooms")) return new Response(JSON.stringify({ rooms: [{ room, currentOccurrence: null, history: [{ occurrenceId: "occ-1", number: 1, status: "COMPLETED", createdAt, startedAt: "2026-08-28T09:02:00Z", endedAt: "2026-08-28T09:14:30Z", participants: ["Arun", "Jaya"], durationSeconds: 750, recap: { summary: "The team confirmed the launch plan and assigned the final review.", decisions: [], actions: [], blockers: [], ideas: [], gameResults: [], citations: [], generatedAt: "2026-08-28T09:15:00Z" } }] }], unavailableRoomIds: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
    if (path.endsWith("/v1/runtime")) return new Response(JSON.stringify({ status: "READY", progress: 100, message: "Voice services are ready", generation: 1, lastActivityAt: createdAt, updatedAt: createdAt }), { status: 200, headers: { "Content-Type": "application/json" } });
    if (path.endsWith("/v1/runtime/activity")) return new Response(JSON.stringify({ status: "READY", progress: 100, message: "Voice services are ready", generation: 1, lastActivityAt: createdAt, updatedAt: createdAt }), { status: 200, headers: { "Content-Type": "application/json" } });
    return new Response(null, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<MemoryRouter><HomePage /></MemoryRouter>);

  expect(await screen.findByRole("heading", { name: "Product sync" })).toBeInTheDocument();
  expect(screen.getAllByText("The team confirmed the launch plan and assigned the final review.")).toHaveLength(2);
  expect(screen.getAllByText(/13 min/).length).toBeGreaterThan(0);
  expect(screen.getByText(/signed in as judge-demo/i)).toBeInTheDocument();
  expect(screen.queryByText(/private browser workspace/i)).not.toBeInTheDocument();
});

test("shows the protected login when no admin session exists", async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).endsWith("/v1/auth/session")) return new Response(JSON.stringify({ error: { code: "unauthorized", message: "Admin login required" } }), { status: 401, headers: { "Content-Type": "application/json" } });
    return new Response(JSON.stringify({ recaptchaSiteKey: "local-test", action: "admin_login" }), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter><HomePage /></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Open your workspace" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /sign in securely/i })).toBeInTheDocument();
});
