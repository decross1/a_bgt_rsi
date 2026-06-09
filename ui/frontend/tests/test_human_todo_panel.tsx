// HumanTodoPanel renders the human's work queue from an `initial` list (no
// fetch mock needed — mirrors BubblesPanel/SurfacedFindingsPanel). Covers: all
// five known kinds render grouped under humanized labels with their verbatim
// resolve commands; an empty queue is the CALM state; garbled (non-object /
// wrong-typed) rows are skipped without crashing the panel; the total-count
// badge is red-tinted only while something is blocked on the human.
import { render, screen, within } from "@testing-library/react";
import HumanTodoPanel from "../src/components/HumanTodoPanel";
import type { HumanTodoItem } from "../src/types/schemas";
import { describe, expect, it } from "vitest";

const TODO_FIXTURE: HumanTodoItem[] = [
  {
    kind: "gate_verdict",
    id: "iter-2026-06-05-001",
    title: "iter-2026-06-05-001 awaiting verdict",
    since: "2026-06-05T19:58:00Z",
    detail: "gate_status=pending, no loop_feedback row",
    resolve_command:
      "python -m orchestrator.gate_cli --iteration-id iter-2026-06-05-001 --verdict valid",
  },
  {
    kind: "gate_verdict",
    id: "iter-2026-06-04-002",
    title: "iter-2026-06-04-002 awaiting verdict",
    since: "2026-06-04T11:00:00Z",
    resolve_command:
      "python -m orchestrator.gate_cli --iteration-id iter-2026-06-04-002 --verdict valid",
  },
  {
    kind: "finding_review",
    id: "f-0042",
    title: "Finding f-0042 surfaced",
    since: "2026-06-07T09:00:00Z",
    resolve_command: "python -m orchestrator.finding_session",
  },
  {
    kind: "bubble_unacked",
    id: "coord-2026-06-08-003",
    title: "Bubble from coord-2026-06-08-003",
    since: "2026-06-08T16:30:00Z",
    resolve_command:
      "python -m orchestrator.ack_cli --bubble-run-id coord-2026-06-08-003",
  },
  {
    kind: "stale_active_run",
    id: "run-stale-1",
    title: "active_run.json stale for 3h",
    since: "2026-06-09T12:00:00Z",
    resolve_command: "rm run_state/active_run.json # after investigating",
  },
  {
    kind: "state_file_gate",
    id: "gate-week1-7",
    title: "human_gates_pending: day-7 retrospective",
    since: "2026-06-06T08:00:00Z",
    resolve_command: "edit run_state/week1.state.json human_gates_pending",
  },
];

describe("HumanTodoPanel", () => {
  it("renders all five kinds grouped under humanized labels with their resolve commands", () => {
    render(<HumanTodoPanel initial={TODO_FIXTURE} />);
    expect(screen.getByTestId("human-todo-panel")).toBeInTheDocument();

    // Humanized group headers for every known kind.
    for (const label of [
      "awaiting gate verdict",
      "finding review",
      "bubble unacknowledged",
      "stale active run",
      "state-file gate",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }

    // Items grouped by kind, oldest-first within the group: the June-4 gate
    // verdict precedes the June-5 one despite fixture order.
    const oldestGate = screen.getByTestId("todo-gate_verdict-0");
    expect(oldestGate).toHaveTextContent("iter-2026-06-04-002 awaiting verdict");
    const newerGate = screen.getByTestId("todo-gate_verdict-1");
    expect(newerGate).toHaveTextContent("iter-2026-06-05-001 awaiting verdict");

    // Each row carries its verbatim copy-able resolve command in a <code>
    // block plus a copy button (inert under jsdom — no navigator.clipboard).
    for (const item of TODO_FIXTURE) {
      const row = screen.getByText(item.title!).closest("li")!;
      const code = within(row as HTMLElement).getByText(item.resolve_command!);
      expect(code.tagName).toBe("CODE");
      expect(
        within(row as HTMLElement).getByRole("button", {
          name: "Copy resolve command",
        }),
      ).toBeInTheDocument();
    }

    // Total badge counts every item and is red-tinted while > 0.
    const badge = screen.getByTestId("human-todo-count");
    expect(badge).toHaveTextContent(String(TODO_FIXTURE.length));
    expect(badge.className).toContain("red");
  });

  it("renders the calm empty state with a quiet badge when nothing is blocked", () => {
    render(<HumanTodoPanel initial={[]} />);
    expect(screen.getByTestId("human-todo-empty")).toHaveTextContent(
      "Nothing needs you — the loop is unblocked.",
    );
    const badge = screen.getByTestId("human-todo-count");
    expect(badge).toHaveTextContent("0");
    expect(badge.className).not.toContain("red");
  });

  it("skips garbled rows without crashing and renders an unknown kind raw", () => {
    const garbled = [
      null,
      "not-an-object",
      42,
      ["array", "row"],
      // Wrong-typed fields on an otherwise-valid row: object title/since/
      // command must degrade per-field, never throw as a React child.
      {
        kind: "gate_verdict",
        id: "iter-bad-fields",
        title: { nested: "object" },
        since: { not: "a timestamp" },
        resolve_command: ["not", "a", "string"],
      },
      // Unknown kind renders raw (quiet), not dropped.
      {
        kind: "mystery_kind",
        id: "m-1",
        title: "a queue source we do not know yet",
        since: "2026-06-09T00:00:00Z",
      },
    ] as unknown as HumanTodoItem[];

    render(<HumanTodoPanel initial={garbled} />);
    const panel = screen.getByTestId("human-todo-panel");
    expect(panel).toBeInTheDocument();

    // Only the two object rows survive; the badge reflects renderable rows.
    expect(screen.getByTestId("human-todo-count")).toHaveTextContent("2");

    // Wrong-typed title degrades to the id; bad since renders the em-dash.
    const badRow = screen.getByTestId("todo-gate_verdict-0");
    expect(badRow).toHaveTextContent("iter-bad-fields");
    expect(badRow).toHaveTextContent("—");

    // Unknown kind: raw kind string as the group header, row rendered.
    expect(screen.getByText("mystery_kind")).toBeInTheDocument();
    expect(screen.getByTestId("todo-mystery_kind-0")).toHaveTextContent(
      "a queue source we do not know yet",
    );
  });

  it("coerces a non-array items payload to the clean empty state", () => {
    render(
      <HumanTodoPanel
        initial={{ not: "an array" } as unknown as HumanTodoItem[]}
      />,
    );
    expect(screen.getByTestId("human-todo-empty")).toBeInTheDocument();
    expect(screen.getByTestId("human-todo-count")).toHaveTextContent("0");
  });
});
