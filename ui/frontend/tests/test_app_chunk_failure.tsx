import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("../src/components/LoopAlertBanner", () => ({
  default: () => <div data-testid="loop-alert-banner" />,
}));
vi.mock("../src/routes/Pulse", () => ({ default: () => <h1>Current work</h1> }));
// Unlike a component render failure, this rejects the lazy import itself.
vi.mock("../src/routes/Inspector", () => { throw new Error("Page chunk unavailable"); });

import App from "../src/App";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

it("keeps navigation available when a page module cannot be imported", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  window.history.replaceState({}, "", "/chain/req/missing-chunk");
  render(<App />);
  expect(await screen.findByRole("heading", { name: "This page could not be loaded" })).toBeInTheDocument();
  expect(screen.getByTestId("loop-alert-banner")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reload page" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("link", { name: "Now" }));
  expect(await screen.findByRole("heading", { name: "Current work" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "This page could not be loaded" })).toBeNull();
});
