import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { CapabilityBoundary } from "./CapabilityBoundary";

test("removes a capability fragment and renders only after cookie exchange", async () => {
  history.replaceState(null, "", "/join/room-1#cap=super-secret-token-value-that-is-long");
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        roomId: "room-1",
        scope: "SEAT",
        slotId: "slot-1",
        expiresAt: new Date(Date.now() + 60_000).toISOString(),
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  render(
    <CapabilityBoundary roomId="room-1" expected="SEAT">
      {(slotId) => <div>Ready {slotId}</div>}
    </CapabilityBoundary>,
  );
  expect(window.location.hash).toBe("");
  expect(await screen.findByText("Ready slot-1")).toBeInTheDocument();
  const request = fetchMock.mock.calls[0];
  expect(request[0]).toContain("/v1/capability-sessions");
  expect(JSON.parse(request[1].body)).toEqual({ roomId: "room-1", token: "super-secret-token-value-that-is-long" });
  vi.unstubAllGlobals();
});
