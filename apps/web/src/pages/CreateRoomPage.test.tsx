import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import { CreateRoomPage } from "./CreateRoomPage";

test("walks from room details to the role chooser", async () => {
  const user = userEvent.setup();
  render(<MemoryRouter><CreateRoomPage /></MemoryRouter>);
  expect(screen.getByRole("heading", { name: "Let AI Lead the Conversation Forward." })).toBeInTheDocument();
  await user.type(screen.getByLabelText("Room name"), "Product sync");
  await user.click(screen.getByRole("button", { name: /continue/i }));
  expect(screen.getByRole("radiogroup", { name: "Agent role" })).toBeInTheDocument();
  expect(document.querySelector(".create-layout")).toHaveClass("focused");
  expect(screen.getByRole("heading", { name: "Choose the facilitator" })).toHaveFocus();
  expect(screen.getByRole("radio", { name: /town hall moderator/i })).toBeInTheDocument();
  expect(screen.getByRole("radio", { name: /brainstorm/i })).toHaveAttribute("aria-checked", "false");
  await user.click(screen.getByRole("radio", { name: /brainstorm/i }));
  expect(screen.getByRole("radio", { name: /brainstorm/i })).toHaveAttribute("aria-checked", "true");
});

test("prefills the complete facilitator prompt when a role is selected", async () => {
  const user = userEvent.setup();
  render(<MemoryRouter><CreateRoomPage /></MemoryRouter>);
  await user.type(screen.getByLabelText("Room name"), "Discovery room");
  await user.click(screen.getByRole("button", { name: /continue/i }));
  await user.click(screen.getByRole("radio", { name: /product discovery facilitator/i }));
  await user.click(screen.getByRole("button", { name: /continue/i }));
  expect(
    (screen.getByPlaceholderText("Tone, agenda, topic, rules or desired outcome…") as HTMLTextAreaElement).value,
  ).toContain("Who is the user?");
});
