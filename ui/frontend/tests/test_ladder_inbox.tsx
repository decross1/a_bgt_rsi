// Ladder-first inbox (2026-08-14 work order B): HumanTodoPanel shows ONLY
// findings whose evidence_level clears L4/L5; below-bar findings (including
// every legacy row with NO level) are demoted behind a "show demoted (N)"
// toggle. Zero-cleared weeks render the honest empty state ("Nothing cleared
// L4 this week") plus a per-level histogram derived from the items themselves.
// Operational kinds (gates, bubbles, stale run) are NOT ladder claims — the
// bar never hides them.
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import HumanTodoPanel from "../src/components/HumanTodoPanel";
import type { HumanTodoItem } from "../src/types/schemas";

const finding = (
  id: string,
  level?: unknown,
  extra: Partial<HumanTodoItem> = {},
): HumanTodoItem =>
  ({
    kind: "finding_review",
    id,
    title: `Finding ${id}`,
    since: "2026-08-10T00:00:00Z",
    resolve_command: `finding_session ${id}`,
    ...(level === undefined ? {} : { evidence_level: level }),
    ...extra,
  }) as HumanTodoItem;

describe("HumanTodoPanel — ladder-first inbox", () => {
  it("shows L4/L5 findings; hides no-level legacy rows behind the toggle", () => {
    render(
      <HumanTodoPanel
        initial={[
          finding("sf-l4", "L4"),
          finding("sf-l5", "L5"),
          finding("sf-legacy-1"),
          finding("sf-legacy-2"),
        ]}
      />,
    );
    // Bar-clearing rows render; legacy rows do not.
    expect(screen.getByText("Finding sf-l4")).toBeInTheDocument();
    expect(screen.getByText("Finding sf-l5")).toBeInTheDocument();
    expect(screen.queryByText("Finding sf-legacy-1")).toBeNull();
    expect(screen.queryByText("Finding sf-legacy-2")).toBeNull();
    // Badge counts what the inbox SHOWS.
    expect(screen.getByTestId("human-todo-count").textContent).toBe("2");
    // The toggle carries the demoted count.
    expect(screen.getByTestId("ladder-toggle").textContent).toBe(
      "show demoted (2)",
    );
    // Something cleared L4 — no zero-week line.
    expect(screen.queryByTestId("ladder-empty")).toBeNull();
  });

  it("the toggle reveals demoted rows and flips to 'hide demoted'", () => {
    render(
      <HumanTodoPanel initial={[finding("sf-l4", "L4"), finding("sf-legacy")]} />,
    );
    const toggle = screen.getByTestId("ladder-toggle");
    fireEvent.click(toggle);
    expect(screen.getByText("Finding sf-legacy")).toBeInTheDocument();
    expect(toggle.textContent).toBe("hide demoted (1)");
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("human-todo-count").textContent).toBe("2");
    fireEvent.click(toggle);
    expect(screen.queryByText("Finding sf-legacy")).toBeNull();
  });

  it("below-L4 leveled findings (L0..L3) are demoted too — the bar is L4/L5", () => {
    render(
      <HumanTodoPanel initial={[finding("sf-l1", "L1"), finding("sf-l3", "L3")]} />,
    );
    expect(screen.queryByText("Finding sf-l1")).toBeNull();
    expect(screen.queryByText("Finding sf-l3")).toBeNull();
    expect(screen.getByTestId("ladder-toggle").textContent).toBe(
      "show demoted (2)",
    );
  });

  it("zero-cleared week: honest empty state + per-level histogram from the items", () => {
    render(
      <HumanTodoPanel
        initial={[
          finding("sf-l1", "L1"),
          finding("sf-legacy-1"),
          finding("sf-legacy-2"),
        ]}
      />,
    );
    expect(screen.getByTestId("ladder-empty").textContent).toContain(
      "Nothing cleared L4 this week",
    );
    // Histogram covers ALL finding rows (demoted included), leveled first,
    // the legacy bucket last.
    expect(screen.getByTestId("ladder-counts").textContent).toContain(
      "L1 ×1 · no level ×2",
    );
    // The demoted-only inbox is NOT the calm "nothing needs you" state.
    expect(screen.queryByTestId("human-todo-empty")).toBeNull();
  });

  it("operational kinds are never demoted — no evidence_level required", () => {
    render(
      <HumanTodoPanel
        initial={[
          {
            kind: "gate_verdict",
            id: "iter-1",
            title: "iter-1 awaiting verdict",
          },
          { kind: "state_gate", id: "g-1", title: "blocking gate" },
          finding("sf-legacy"),
        ]}
      />,
    );
    expect(screen.getByText("iter-1 awaiting verdict")).toBeInTheDocument();
    expect(screen.getByText("blocking gate")).toBeInTheDocument();
    expect(screen.queryByText("Finding sf-legacy")).toBeNull();
    expect(screen.getByTestId("human-todo-count").textContent).toBe("2");
  });

  it("a malformed evidence_level (number/object/garbage) reads as below-bar, never crashes", () => {
    render(
      <HumanTodoPanel
        initial={[
          finding("sf-num", 4),
          finding("sf-obj", { level: "L4" }),
          finding("sf-word", "very-high"),
        ]}
      />,
    );
    expect(screen.queryByText("Finding sf-num")).toBeNull();
    expect(screen.queryByText("Finding sf-obj")).toBeNull();
    expect(screen.queryByText("Finding sf-word")).toBeNull();
    expect(screen.getByTestId("ladder-toggle").textContent).toBe(
      "show demoted (3)",
    );
    // All three land in the legacy histogram bucket.
    expect(screen.getByTestId("ladder-counts").textContent).toContain(
      "no level ×3",
    );
  });

  it("an empty queue keeps the calm state AND the honest zero-week line", () => {
    render(<HumanTodoPanel initial={[]} />);
    expect(screen.getByTestId("human-todo-empty")).toBeInTheDocument();
    expect(screen.getByTestId("ladder-empty")).toBeInTheDocument();
    // No findings at all -> no histogram, no toggle.
    expect(screen.queryByTestId("ladder-counts")).toBeNull();
    expect(screen.queryByTestId("ladder-toggle")).toBeNull();
  });
});
