import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { saveRoomLinks } from "../lib/linkVault";
import type { RoomCreated } from "../types";
import { HomePage } from "./HomePage";

afterEach(() => {
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

test("shows saved rooms, participant links, history, duration and summaries", async () => {
  const createdAt = "2026-08-28T09:00:00Z";
  const stored: RoomCreated = {
    room: {
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
    },
    adminUrl: "https://rolecall.example/manage/room-1#cap=admin-secret-token-value-that-is-long",
    seatUrls: [
      { slotId: "slot-1", url: "https://rolecall.example/join/room-1#cap=seat-one-secret-token-value-long" },
      { slotId: "slot-2", url: "https://rolecall.example/join/room-1#cap=seat-two-secret-token-value-long" },
    ],
  };
  saveRoomLinks(stored);
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        rooms: [
          {
            room: stored.room,
            currentOccurrence: null,
            history: [
              {
                occurrenceId: "occ-1",
                number: 1,
                status: "COMPLETED",
                createdAt,
                startedAt: "2026-08-28T09:02:00Z",
                endedAt: "2026-08-28T09:14:30Z",
                participants: ["Arun", "Jaya"],
                durationSeconds: 750,
                recap: {
                  summary: "The team confirmed the launch plan and assigned the final review.",
                  decisions: [],
                  actions: [],
                  blockers: [],
                  ideas: [],
                  gameResults: [],
                  generatedAt: "2026-08-28T09:15:00Z",
                },
              },
            ],
          },
        ],
        unavailableRoomIds: [],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ),
  );
  vi.stubGlobal("fetch", fetchMock);

  render(<MemoryRouter><HomePage /></MemoryRouter>);

  expect(await screen.findByRole("heading", { name: "Product sync" })).toBeInTheDocument();
  expect(screen.getByText("Arun")).toBeInTheDocument();
  expect(screen.getByText("Jaya")).toBeInTheDocument();
  expect(screen.getAllByText("The team confirmed the launch plan and assigned the final review.")).toHaveLength(2);
  expect(screen.getAllByText(/13 min/).length).toBeGreaterThan(0);
  expect(screen.getByRole("link", { name: /manage room/i })).toHaveAttribute("href", stored.adminUrl);
  const requestBody = JSON.parse(fetchMock.mock.calls[0][1].body as string);
  expect(requestBody.rooms).toEqual([
    { roomId: "room-1", token: "admin-secret-token-value-that-is-long" },
  ]);
});
