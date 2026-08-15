// test_design_peek_panel — PeekPanel, the Linear-style right slide-over (R0
// design system). Pins: closed = renders nothing; open = dialog with the
// children; Esc closes; backdrop click closes; panel click does NOT close;
// focus moves into the panel on open, Tab is trapped inside it, and focus
// returns to the opener on close. Pure presentation — no fetching.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PeekPanel from "../src/design/PeekPanel";

afterEach(() => {
  cleanup();
});

function Harness({ width }: { width?: number }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button onClick={() => setOpen(true)}>open peek</button>
      <PeekPanel
        open={open}
        onClose={() => setOpen(false)}
        title="finding detail"
        width={width}
      >
        <button>first inner</button>
        <button>last inner</button>
      </PeekPanel>
    </div>
  );
}

describe("PeekPanel — open/close", () => {
  it("renders nothing while closed", () => {
    render(<Harness />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByTestId("peek-backdrop")).not.toBeInTheDocument();
  });

  it("opens as an aria-modal dialog with title + children", () => {
    render(<Harness />);
    fireEvent.click(screen.getByText("open peek"));
    const dialog = screen.getByRole("dialog", { name: "finding detail" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("first inner")).toBeInTheDocument();
  });

  it("Esc closes", () => {
    render(<Harness />);
    fireEvent.click(screen.getByText("open peek"));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("backdrop click closes; a click inside the panel does not", () => {
    render(<Harness />);
    fireEvent.click(screen.getByText("open peek"));
    fireEvent.click(screen.getByTestId("peek-panel"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("peek-backdrop"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("the header close button closes", () => {
    render(<Harness />);
    fireEvent.click(screen.getByText("open peek"));
    fireEvent.click(screen.getByRole("button", { name: "close panel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("onClose is the caller's; the panel never closes itself silently", () => {
    const onClose = vi.fn();
    render(
      <PeekPanel open onClose={onClose} title="t">
        <span>body</span>
      </PeekPanel>,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    // caller has not flipped `open`, so the dialog is still there
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("PeekPanel — focus", () => {
  it("moves focus into the panel on open, back to the opener on close", () => {
    render(<Harness />);
    const opener = screen.getByText("open peek");
    opener.focus();
    fireEvent.click(opener);
    expect(screen.getByTestId("peek-panel")).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(opener).toHaveFocus();
  });

  it("traps Tab: forward from the last focusable wraps to the first", () => {
    render(<Harness />);
    fireEvent.click(screen.getByText("open peek"));
    screen.getByText("last inner").focus();
    fireEvent.keyDown(document, { key: "Tab" });
    // wrap goes to the panel's first focusable — the header close button
    expect(screen.getByRole("button", { name: "close panel" })).toHaveFocus();
  });

  it("traps Shift+Tab: backward from the panel/first wraps to the last", () => {
    render(<Harness />);
    fireEvent.click(screen.getByText("open peek"));
    // focus starts on the panel container itself
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(screen.getByText("last inner")).toHaveFocus();
  });
});

describe("PeekPanel — width", () => {
  it("exposes the width as the --peek-width custom property (default 480)", () => {
    render(<Harness width={520} />);
    fireEvent.click(screen.getByText("open peek"));
    expect(
      screen.getByTestId("peek-panel").style.getPropertyValue("--peek-width"),
    ).toBe("520px");
  });
});
