import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import { CreateRoomPage } from "./CreateRoomPage";

test("walks from room details to the role chooser", async () => {
  const user = userEvent.setup();
  render(<MemoryRouter><CreateRoomPage /></MemoryRouter>);
  await user.type(screen.getByLabelText("Room name"), "Product sync");
  await user.click(screen.getByRole("button", { name: /continue/i }));
  expect(screen.getByRole("radiogroup", { name: "Agent role" })).toBeInTheDocument();
  expect(screen.getByRole("radio", { name: /brainstorm/i })).toHaveAttribute("aria-checked", "false");
  await user.click(screen.getByRole("radio", { name: /brainstorm/i }));
  expect(screen.getByRole("radio", { name: /brainstorm/i })).toHaveAttribute("aria-checked", "true");
});
