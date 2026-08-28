import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { JoinResponse } from "../types";
import { MeetingSurface } from "./MeetingSurface";

const mocks = vi.hoisted(() => ({ useLiveMeeting: vi.fn() }));
vi.mock("../hooks/useLiveMeeting", () => ({ useLiveMeeting: mocks.useLiveMeeting }));

afterEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
});

test("shows meeting metadata and measured audio quality with the recap", () => {
  const recap = {
    summary: "The team agreed to ship the billing update after the final review.",
    decisions: ["Ship after review"],
    actions: [{ text: "Arun completes the review" }],
    blockers: [],
    ideas: [],
    gameResults: [],
    generatedAt: "2026-08-28T09:14:40Z",
  };
  const occurrence: JoinResponse["occurrence"] = {
    id: "occ-1",
    roomId: "room-1",
    number: 1,
    status: "COMPLETED",
    createdAt: "2026-08-28T09:00:00Z",
    lobbyDeadlineAt: "2026-08-28T09:02:00Z",
    startedAt: "2026-08-28T09:02:00Z",
    endedAt: "2026-08-28T09:12:30Z",
    attendance: {},
    absentSlotIds: [],
    turnOrder: [],
    currentFloorType: "NONE",
    currentFloorSlotId: null,
    nextFloorSlotId: null,
    floorEpoch: 4,
    handRaiseQueue: [],
    endMeetingSlotIds: [],
    recap,
    sequence: 10,
  };
  const join: JoinResponse = {
    occurrence,
    livekitUrl: "wss://livekit.example",
    livekitToken: "token",
    slotId: "slot-1",
    roomName: "Product sync",
    agentName: "Nova",
    expectedParticipants: 2,
    connectionId: "connection-1",
    canEndMeeting: false,
  };
  mocks.useLiveMeeting.mockReturnValue({
    connection: "disconnected",
    occurrence,
    setOccurrence: vi.fn(),
    captions: [],
    recap,
    micEnabled: false,
    micAllowed: false,
    mediaError: "",
    audioQuality: "excellent",
    left: false,
    toggleMic: vi.fn(),
    raiseHand: vi.fn(),
    leaveMeeting: vi.fn(),
  });

  render(<MeetingSurface join={join} />);

  expect(screen.getByRole("heading", { name: "Meeting summary" })).toBeInTheDocument();
  expect(screen.queryByText("Clear words. Concrete next steps.")).not.toBeInTheDocument();
  expect(screen.getByText("Date")).toBeInTheDocument();
  expect(screen.getByText("Time")).toBeInTheDocument();
  expect(screen.getByText("Duration")).toBeInTheDocument();
  expect(screen.getByText("10m 30s")).toBeInTheDocument();
  expect(screen.getByText("Audio quality")).toBeInTheDocument();
  expect(screen.getByText("Excellent")).toBeInTheDocument();
  expect(screen.getByText(recap.summary)).toBeInTheDocument();
});
