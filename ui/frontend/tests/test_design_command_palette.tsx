// test_design_command_palette — the global Cmd+K palette (R0 design system).
// Pins: closed by default; ⌘K and Ctrl+K toggle it; Esc and scrim-click close;
// it lists a "Go to" entry for every route in App.tsx; selecting one navigates
// and closes; registerPaletteActions adds entries and its unsubscribe removes
// them (the registry survives for R1-R4 verbs — routes only ship here).
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import CommandPalette, {
  registerPaletteActions,
} from "../src/design/CommandPalette";

afterEach(() => {
  cleanup();
});

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location">{location.pathname}</span>;
}

function mount() {
  render(
    <MemoryRouter initialEntries={["/"]}>
      <CommandPalette />
      <LocationProbe />
    </MemoryRouter>,
  );
}

const openPalette = () =>
  fireEvent.keyDown(window, { key: "k", metaKey: true });

describe("CommandPalette — open/close", () => {
  it("is closed by default and opens on ⌘K", () => {
    mount();
    expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument();
    openPalette();
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Go to…")).toBeInTheDocument();
  });

  it("Ctrl+K works too (non-mac), and a second press toggles closed", () => {
    mount();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument();
  });

  it("plain k does not open it", () => {
    mount();
    fireEvent.keyDown(window, { key: "k" });
    expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument();
  });

  it("Esc closes; scrim click closes", () => {
    mount();
    openPalette();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument();
    openPalette();
    fireEvent.click(screen.getByTestId("palette-scrim"));
    expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument();
  });
});

describe("CommandPalette — navigation entries", () => {
  it("lists every route surface", () => {
    mount();
    openPalette();
    for (const label of [
      "pulse",
      "ladder",
      "dossiers",
      "channel",
      "cycles",
      "experiments",
      "graph",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("clicking an entry navigates there and closes the palette", () => {
    mount();
    openPalette();
    fireEvent.click(screen.getByText("ladder"));
    expect(screen.getByTestId("location")).toHaveTextContent("/ladder");
    expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument();
  });

  it("typing filters, Enter selects the highlighted entry", () => {
    mount();
    openPalette();
    const input = screen.getByPlaceholderText("Go to…");
    fireEvent.change(input, { target: { value: "chan" } });
    expect(screen.queryByText("experiments")).not.toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByTestId("location")).toHaveTextContent("/channel");
  });
});

describe("CommandPalette — registerable actions", () => {
  it("registered actions appear under their group and run on select", () => {
    const perform = vi.fn();
    const unregister = registerPaletteActions([
      { id: "act-refresh", label: "refresh pulse", group: "Pulse", perform },
    ]);
    try {
      mount();
      openPalette();
      expect(screen.getByText("Pulse")).toBeInTheDocument();
      fireEvent.click(screen.getByText("refresh pulse"));
      expect(perform).toHaveBeenCalledTimes(1);
      expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument();
    } finally {
      unregister();
    }
  });

  it("unsubscribe removes the entries", () => {
    const unregister = registerPaletteActions([
      { id: "act-x", label: "transient action", perform: () => {} },
    ]);
    unregister();
    mount();
    openPalette();
    expect(screen.queryByText("transient action")).not.toBeInTheDocument();
  });
});
