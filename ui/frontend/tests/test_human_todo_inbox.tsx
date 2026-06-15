// HumanTodoPanel as the ESCALATION INBOX (severity-tiered rebuild) + its
// single Dashboard mount. Covers what test_human_todo_panel.tsx (group/garble
// rendering) does not: the TIER ordering contract (the one-decision hero is
// the newest item of the HIGHEST present tier, never merely the newest item),
// same-kind collapse into one expandable group row, the copy button on the
// hero's verbatim resolve command, the honest 404 state (endpoint missing !=
// queue empty), the calm empty state, and — at the route level — that the
// Dashboard mounts EXACTLY ONE inbox (the double-mount regression: hero +
// legacy mid-page copy both polling /api/human_todo).
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import HumanTodoPanel from "../src/components/HumanTodoPanel";
import type { HumanTodoItem } from "../src/types/schemas";

// Mock the HTTP layer once for the whole file (the test_dashboard idiom —
// Dashboard's child panels all poll it). getHumanTodo defaults to an empty
// queue; individual tests steer it with mockRejectedValueOnce etc. The
// `initial`-prop renders below bypass polling entirely.
vi.mock("../src/api/http", () => ({
  // api/attest builds its URLs off API_BASE; "" keeps them relative so the
  // attestation tests' fetch stub matches by path suffix.
  API_BASE: "",
  getHealth: vi.fn().mockResolvedValue({
    ok: true,
    hostname: "spark",
    telemetry_last_seen: new Date().toISOString(),
    version: "test",
  }),
  getState: vi.fn().mockResolvedValue({ current_day: "2026-06-05" }),
  getIterations: vi.fn().mockResolvedValue({ iterations: [] }),
  getJournalEntry: vi.fn().mockResolvedValue({
    iteration_id: "iter-x",
    path: "journal/iterations/x.md",
    content: "# Journal",
  }),
  getActiveIteration: vi.fn().mockResolvedValue(null),
  getBaseline: vi.fn().mockResolvedValue({ rows: [] }),
  getWorkloadHint: vi.fn().mockResolvedValue({ regime: "idle" }),
  getSurfacedFindings: vi.fn().mockResolvedValue({ findings: [] }),
  getBubbles: vi.fn().mockResolvedValue({ bubbles: [] }),
  getHealthSignals: vi.fn().mockResolvedValue({ health_signals: [] }),
  getCoordinatorActive: vi.fn().mockResolvedValue(null),
  getHumanTodo: vi.fn().mockResolvedValue({ items: [], counts: {} }),
}));

// Dashboard-only feeds (single-mount test): quiet telemetry + no live calls.
vi.mock("../src/hooks/useTelemetryStream", () => ({
  useTelemetryStream: () => ({ samples: [], latest: null, connected: false }),
}));
vi.mock("../src/api/activity", () => ({
  getActivityMonitor: vi.fn().mockResolvedValue({
    available: true,
    active: [],
    recent: [],
    generated_at: new Date().toISOString(),
  }),
  getActivityGraph: vi.fn().mockResolvedValue({
    available: false,
    nodes: [],
    edges: [],
    generated_at: new Date().toISOString(),
  }),
  getActiveRun: vi.fn().mockResolvedValue(null),
}));

import { getHumanTodo } from "../src/api/http";
import {
  resetAttestCapabilityCache,
  type AttestAvailable,
} from "../src/api/attest";

// Dynamic `since` so age labels are deterministic relative to the real clock.
const daysAgo = (n: number) => new Date(Date.now() - n * 864e5).toISOString();

describe("HumanTodoPanel — severity-tiered inbox", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("puts the newest item of the HIGHEST tier in the hero, never the globally newest", () => {
    const items: HumanTodoItem[] = [
      // tier 2 (review queue), newest overall by far
      {
        kind: "gate_verdict",
        id: "iter-new",
        title: "iter-new awaiting verdict",
        since: daysAgo(0.01),
        resolve_command: "gate_cli --iteration-id iter-new",
      },
      // tier 1 (ops)
      {
        kind: "stale_active_run",
        id: "run-stale",
        title: "active_run.json stale",
        since: daysAgo(1),
        resolve_command: "rm run_state/active_run.json",
      },
      // tier 0 (blocking) — OLDEST item, must still win the hero slot
      {
        kind: "state_gate",
        id: "gate-week1",
        title: "human_gates_pending: day-7 retrospective",
        since: daysAgo(6),
        detail: "the loop is gated on a state-file flag",
        resolve_command: "edit run_state/week1.state.json",
      },
      // tier 3 (informational)
      {
        kind: "bubble_ack",
        id: "bub-1",
        title: "Bubble from coord-1",
        since: daysAgo(0.5),
        resolve_command: "ack_cli --bubble-run-id coord-1",
      },
    ];
    render(<HumanTodoPanel initial={items} />);

    const hero = screen.getByTestId("human-todo-hero");
    expect(
      within(hero).getByText("human_gates_pending: day-7 retrospective"),
    ).toBeInTheDocument();
    // One-decision card: 1-line detail + the verbatim command.
    expect(
      within(hero).getByText("the loop is gated on a state-file flag"),
    ).toBeInTheDocument();
    expect(
      within(hero).getByText("edit run_state/week1.state.json").tagName,
    ).toBe("CODE");

    // The other kinds collapse into group rows ordered by tier: ops above
    // review queue above informational.
    const groups = screen
      .getAllByTestId(/^todo-group-/)
      .map((el) => el.getAttribute("data-testid"));
    expect(groups).toEqual([
      "todo-group-stale_active_run",
      "todo-group-gate_verdict",
      "todo-group-bubble_ack",
    ]);
    // The lone state_gate item was consumed by the hero — no group row.
    expect(screen.queryByTestId("todo-group-state_gate")).toBeNull();
  });

  it("labels a bubble_ack hero as informational (ack channel pending), not an action", () => {
    render(
      <HumanTodoPanel
        initial={[
          {
            kind: "bubble_ack",
            id: "bub-only",
            title: "Bubble from coord-9",
            since: daysAgo(1),
            resolve_command: "ack_cli --bubble-run-id coord-9",
          },
        ]}
      />,
    );
    const hero = screen.getByTestId("human-todo-hero");
    expect(hero).toHaveTextContent(/informational — ack channel pending/);
    expect(hero).not.toHaveTextContent(/needs you/);
  });

  it("collapses >=2 same-kind items into one expandable group row with count and oldest age", () => {
    const items: HumanTodoItem[] = [0.2, 2, 4].map((age, i) => ({
      kind: "gate_verdict",
      id: `iter-${i}`,
      title: `iter-${i} awaiting verdict`,
      since: daysAgo(age),
      resolve_command: `gate_cli --iteration-id iter-${i}`,
    }));
    render(<HumanTodoPanel initial={items} />);

    // Newest (iter-0) is the hero; the two older ones collapse into the group.
    expect(screen.getByTestId("human-todo-hero")).toHaveTextContent(
      "iter-0 awaiting verdict",
    );
    const group = screen.getByTestId("todo-group-gate_verdict");
    // Expandable disclosure: a real <details> with a <summary> row.
    expect(group.tagName).toBe("DETAILS");
    const summary = group.querySelector("summary")!;
    expect(summary).toHaveTextContent("2");
    expect(summary).toHaveTextContent("awaiting gate verdict");
    expect(summary).toHaveTextContent("oldest 4d");
    // Expanded content holds the full rows, oldest first.
    expect(within(group).getByTestId("todo-gate_verdict-0")).toHaveTextContent(
      "iter-2 awaiting verdict",
    );
    expect(within(group).getByTestId("todo-gate_verdict-1")).toHaveTextContent(
      "iter-1 awaiting verdict",
    );
  });

  it("renders a copy-to-clipboard button beside the hero's resolve command", () => {
    render(
      <HumanTodoPanel
        initial={[
          {
            kind: "gate_verdict",
            id: "iter-c",
            title: "iter-c awaiting verdict",
            since: daysAgo(1),
            resolve_command: "gate_cli --iteration-id iter-c --verdict valid",
          },
        ]}
      />,
    );
    const hero = screen.getByTestId("human-todo-hero");
    expect(
      within(hero).getByText("gate_cli --iteration-id iter-c --verdict valid")
        .tagName,
    ).toBe("CODE");
    expect(
      within(hero).getByRole("button", { name: "Copy resolve command" }),
    ).toBeInTheDocument();
  });

  it("renders the calm empty state when the queue is empty", () => {
    render(<HumanTodoPanel initial={[]} />);
    expect(screen.getByTestId("human-todo-empty")).toHaveTextContent(
      "Nothing needs you — the loop is unblocked.",
    );
    expect(screen.queryByTestId("human-todo-hero")).toBeNull();
  });

  it("renders the honest endpoint-missing state on 404, never the calm empty state", async () => {
    vi.mocked(getHumanTodo).mockRejectedValueOnce(new Error("404 Not Found"));
    render(<HumanTodoPanel />);
    await waitFor(() =>
      expect(screen.getByTestId("human-todo-error")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("human-todo-error")).toHaveTextContent(/404/);
    expect(screen.getByTestId("human-todo-error")).toHaveTextContent(/missing/);
    expect(screen.queryByTestId("human-todo-empty")).toBeNull();
  });

  it("does NOT mount the inbox on the Dashboard anymore — it moved to /todo (PART 1)", async () => {
    // 2026-06-14 work order PART 1: the HumanTodoPanel left the dashboard for
    // the /todo cockpit. The dashboard's at-a-glance escalation signal is now
    // the SystemActivityHero "N need you →" coupling, not a mounted panel — so
    // the panel must NOT appear here (the inbox has exactly one home).
    const { default: Dashboard } = await import("../src/routes/Dashboard");
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("system-activity-hero")).toBeInTheDocument(),
    );
    expect(screen.queryAllByTestId("human-todo-panel")).toHaveLength(0);
  });
});

// --- B4 write-back integration (D-046, docs/human_writeback_contract.md) ---
//
// Capability comes from the `attest` prop in fixture renders — the panel
// NEVER fetches it in initial mode, so these renders stay deterministic.
// Each mounted FORM self-resolves the page-load-cached
// GET /api/attest/available, so tests that mount forms stub global fetch
// (handshake + POSTs — never a live write). The confirmation re-poll goes
// through the module-mocked getHumanTodo — the same client the panel polls.

const CAP_ALL: AttestAvailable = {
  available: true,
  actions: { gate_verdict: true, finding_review: true, bubble_ack: true, defer: true },
};
const CAP_NONE: AttestAvailable = {
  available: false,
  actions: { gate_verdict: false, finding_review: false, bubble_ack: false, defer: false },
};

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    json: async () => body,
  } as unknown as Response;
}

const GATE_ITEM: HumanTodoItem = {
  kind: "gate_verdict",
  id: "iter-2026-06-09-001",
  title: "iter-2026-06-09-001 awaiting verdict",
  since: daysAgo(1),
  resolve_command:
    "python -m orchestrator.gate_cli --iteration-id iter-2026-06-09-001 --verdict valid",
};

describe("HumanTodoPanel — in-UI attestation (B4)", () => {
  beforeEach(() => {
    resetAttestCapabilityCache();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
    resetAttestCapabilityCache();
  });

  it("renders the gate form when capability allows, demoting the command to a collapsed CLI-fallback disclosure", async () => {
    vi.stubGlobal("fetch", async (url: unknown) => {
      const u = String(url);
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      throw new Error(`unstubbed fetch: ${u}`);
    });
    render(<HumanTodoPanel initial={[GATE_ITEM]} attest={CAP_ALL} />);

    // The three frozen verdict buttons appear once the form's cached
    // handshake resolves; defer is offered on every blessed kind.
    expect(await screen.findByRole("button", { name: "valid" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "needs_revision" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "invalid" })).toBeInTheDocument();
    expect(screen.getByTestId("defer-form")).toBeInTheDocument();

    // The verbatim resolve command STAYS — demoted, collapsed, copy-able.
    const fallback = screen.getByTestId("todo-cli-fallback") as HTMLDetailsElement;
    expect(fallback.tagName).toBe("DETAILS");
    expect(fallback.open).toBe(false);
    expect(fallback).toHaveTextContent("CLI fallback");
    expect(
      within(fallback).getByText(
        /orchestrator\.gate_cli --iteration-id iter-2026-06-09-001/,
      ).tagName,
    ).toBe("CODE");
  });

  it("offers ONLY defer for stale_active_run and state_gate — direct resolution stays primary-session", async () => {
    vi.stubGlobal("fetch", async (url: unknown) => {
      const u = String(url);
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      throw new Error(`unstubbed fetch: ${u}`);
    });
    render(
      <HumanTodoPanel
        initial={[
          {
            kind: "stale_active_run",
            id: "run-stale-1",
            title: "active_run.json stale",
            since: daysAgo(2),
            resolve_command: "inspect run_state/active_run.json",
          },
          {
            kind: "state_gate",
            id: "gate-week1-7",
            title: "human_gates_pending: day-7 retrospective",
            since: daysAgo(1),
            resolve_command: "edit run_state/week1.state.json",
          },
        ]}
        attest={CAP_ALL}
      />,
    );

    await waitFor(() => expect(screen.getAllByTestId("defer-form")).toHaveLength(2));
    // No direct attestation surface exists for these kinds — not blessed.
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
    expect(screen.queryByTestId("finding-review-form")).toBeNull();
    expect(screen.queryByTestId("bubble-ack-form")).toBeNull();
  });

  it("degrades to the open copy-paste fallback with a quiet skew note when capability is unavailable", () => {
    render(<HumanTodoPanel initial={[GATE_ITEM]} attest={CAP_NONE} />);

    // Quiet zinc note, not red — a missing capability is degradation.
    expect(screen.getByTestId("attest-skew-note")).toHaveTextContent(/CLI fallback/);
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
    expect(screen.queryByTestId("defer-form")).toBeNull();
    expect(screen.queryByRole("button", { name: "valid" })).toBeNull();

    // The fallback disclosure is forced OPEN — copy-paste is the action path.
    const fallback = screen.getByTestId("todo-cli-fallback") as HTMLDetailsElement;
    expect(fallback.open).toBe(true);
    expect(
      within(fallback).getByRole("button", { name: "Copy resolve command" }),
    ).toBeInTheDocument();
  });

  it("renders the shared EndpointMissingNote when unavailability came from a version-skew 404", async () => {
    // skew:true is what api/attest resolves from a 404 on the handshake —
    // the running backend binary predates /api/attest/* (Task-2 semantics).
    render(
      <HumanTodoPanel initial={[GATE_ITEM]} attest={{ ...CAP_NONE, skew: true }} />,
    );

    const note = await screen.findByTestId("endpoint-missing-note");
    expect(note).toHaveTextContent("/api/attest/available");
    expect(note).toHaveTextContent(/endpoint not in this backend build/);
    // The inline (non-skew) note does not double-render.
    expect(screen.queryByTestId("attest-skew-note")).toBeNull();
    // Degradation is identical: no forms, fallback forced open.
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
    expect((screen.getByTestId("todo-cli-fallback") as HTMLDetailsElement).open).toBe(
      true,
    );
  });

  it("never fetches capability in fixture renders without the attest prop — fallback open, no skew note", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    render(<HumanTodoPanel initial={[GATE_ITEM]} />);

    expect(fetchSpy).not.toHaveBeenCalled();
    // Capability UNKNOWN is not capability KNOWN-MISSING: no skew note.
    expect(screen.queryByTestId("attest-skew-note")).toBeNull();
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
    expect((screen.getByTestId("todo-cli-fallback") as HTMLDetailsElement).open).toBe(
      true,
    );
  });

  it("renders the deferred-to-dev-session tag on an open-deferral item, which stays listed AND counted", () => {
    render(
      <HumanTodoPanel
        initial={[
          {
            ...GATE_ITEM,
            id: "iter-deferred",
            title: "iter-deferred awaiting verdict",
            // Additive backend tagging (human_todo.py _tag_deferred).
            deferred: true,
            deferral: {
              note: "needs the primary session",
              by: "human:ui",
              at: daysAgo(0.5),
            },
          },
        ]}
      />,
    );

    const tag = screen.getByTestId("todo-deferred-tag");
    expect(tag).toHaveTextContent("deferred to dev session");
    expect(tag).toHaveTextContent("human:ui");
    expect(tag).toHaveTextContent("needs the primary session");
    // A deferral assigns the work; it does not resolve the item.
    expect(screen.getByTestId("human-todo-count")).toHaveTextContent("1");
  });

  it("submits a gate verdict from the inbox: POST, then re-poll — the item leaving the queue is the confirmation", async () => {
    vi.stubGlobal("fetch", async (url: unknown, init?: RequestInit) => {
      const u = String(url);
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      if (u.endsWith("/api/attest/gate_verdict") && init?.method === "POST") {
        // SYNTHETIC row mirroring the documented gate_cli stdout shape (the
        // appended loop_feedback ledger row).
        return jsonResponse(200, {
          iteration_id: "iter-2026-06-09-001",
          verdict: "needs_revision",
          note: "tighten the journal evidence",
          gated_by: "human:ui",
          gated_at: "2026-06-10T18:00:00Z",
        });
      }
      throw new Error(`unstubbed fetch: ${u}`);
    });
    // The confirmation re-poll goes through the mocked http client; an empty
    // queue == the item left (contract principle 5).
    vi.mocked(getHumanTodo).mockResolvedValueOnce({ items: [], counts: {} });

    render(<HumanTodoPanel initial={[GATE_ITEM]} attest={CAP_ALL} />);

    fireEvent.change(await screen.findByLabelText("gate verdict note (required)"), {
      target: { value: "tighten the journal evidence" },
    });
    fireEvent.click(screen.getByRole("button", { name: "needs_revision" }));

    const success = await screen.findByTestId("attest-success");
    expect(success).toHaveTextContent("human:ui");
    expect(success).toHaveTextContent("confirmed — item left the queue (re-poll)");
    // Exactly one getHumanTodo call: the form's re-poll (the fixture-mode
    // panel itself never polls).
    expect(vi.mocked(getHumanTodo)).toHaveBeenCalledTimes(1);
  });
});
