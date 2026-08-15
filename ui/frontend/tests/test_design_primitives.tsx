// test_design_primitives — StatusDot + ListRow + Card (R0 design system).
// Pins: StatusDot colors ride ONLY the semantic status token set and pulse is
// opt-in; ListRow is a plain row until onClick makes it a keyboard-operable
// button with the hover/selected surface step; Card is surface+border, no
// shadow styling hook at all.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Card from "../src/design/Card";
import ListRow from "../src/design/ListRow";
import StatusDot from "../src/design/StatusDot";

afterEach(() => {
  cleanup();
});

describe("StatusDot", () => {
  it.each([
    ["ok", "var(--status-ok)"],
    ["warn", "var(--status-warn)"],
    ["bad", "var(--status-bad)"],
    ["info", "var(--status-info)"],
    ["idle", "var(--status-idle)"],
  ] as const)("%s rides its semantic status token", (status, token) => {
    render(<StatusDot status={status} />);
    const dot = screen.getByTestId("status-dot");
    expect(dot.style.color).toBe(token);
    expect(dot).toHaveAttribute("data-status", status);
  });

  it("does not pulse by default; pulse adds the animation class", () => {
    render(<StatusDot status="info" />);
    expect(screen.getByTestId("status-dot")).not.toHaveClass("dsn-dot--pulse");
    cleanup();
    render(<StatusDot status="info" pulse />);
    expect(screen.getByTestId("status-dot")).toHaveClass("dsn-dot--pulse");
  });

  it("is named for screen readers (label overrides the status word)", () => {
    render(<StatusDot status="ok" label="run passing" />);
    expect(screen.getByRole("img", { name: "run passing" })).toBeInTheDocument();
    cleanup();
    render(<StatusDot status="warn" />);
    expect(screen.getByRole("img", { name: "warn" })).toBeInTheDocument();
  });
});

describe("ListRow", () => {
  it("renders a non-interactive row by default", () => {
    render(<ListRow>content</ListRow>);
    const row = screen.getByTestId("list-row");
    expect(row).toHaveClass("dsn-row");
    expect(row).not.toHaveAttribute("role");
    expect(row).not.toHaveAttribute("tabindex");
  });

  it("onClick makes it a keyboard-operable button", () => {
    const onClick = vi.fn();
    render(<ListRow onClick={onClick}>go</ListRow>);
    const row = screen.getByRole("button");
    expect(row).toHaveClass("dsn-row--interactive");
    fireEvent.click(row);
    fireEvent.keyDown(row, { key: "Enter" });
    fireEvent.keyDown(row, { key: " " });
    fireEvent.keyDown(row, { key: "x" }); // no-op
    expect(onClick).toHaveBeenCalledTimes(3);
  });

  it("selected shows the surface step", () => {
    render(<ListRow selected>row</ListRow>);
    expect(screen.getByTestId("list-row")).toHaveClass("dsn-row--selected");
  });
});

describe("Card", () => {
  it("renders the surface shell with an optional title", () => {
    render(<Card title="novelty">body text</Card>);
    const card = screen.getByTestId("card");
    expect(card).toHaveClass("dsn-card");
    expect(screen.getByRole("heading", { name: "novelty" })).toBeInTheDocument();
    expect(screen.getByText("body text")).toBeInTheDocument();
  });

  it("omits the heading when no title is given", () => {
    render(<Card>just body</Card>);
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  });
});
