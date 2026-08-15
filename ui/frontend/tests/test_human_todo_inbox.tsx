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
  // The Dashboard (mounted by the PART 1 single-mount test) now polls the
  // processes route — mock it so the import resolves (empty = no rows).
  getProcesses: vi.fn().mockResolvedValue({ processes: [] }),
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

// --- FE1: select-only mode (closes the calibration-bypass at the source) ---
//
// In select mode the inbox is a SELECTOR for the calibration-capture flow:
// each row's title is a clickable selector (onSelect(id), aria-pressed off
// selectedId) and the GATED writers — GateVerdictForm + FindingReviewForm —
// are SUPPRESSED so no verdict is written without calibration. BubbleAck +
// Defer + the CLI fallback stay inline (not the bypass). Default-off (no
// selectMode) leaves every inline writer exactly as before.

const FINDING_ITEM: HumanTodoItem = {
  kind: "finding_review",
  id: "f-0042",
  title: "Finding f-0042 surfaced",
  since: daysAgo(2),
  // clears the ladder bar (work order B) — below-L4 findings are demoted
  evidence_level: "L4",
  resolve_command: "python -m orchestrator.finding_session",
};
const BUBBLE_ITEM: HumanTodoItem = {
  kind: "bubble_ack",
  id: "coord-1",
  title: "Bubble from coord-1",
  since: daysAgo(3),
  resolve_command: "ack_cli --bubble-run-id coord-1",
};

describe("HumanTodoPanel — select-only mode (FE1)", () => {
  beforeEach(() => {
    resetAttestCapabilityCache();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
    resetAttestCapabilityCache();
  });

  it("suppresses the GateVerdictForm and FindingReviewForm (the gated writers) in select mode", async () => {
    // The kept DeferForms self-resolve the capability handshake — stub it so
    // the only thing absent is the suppressed gated writers, not a fetch error.
    vi.stubGlobal("fetch", async (url: unknown) => {
      const u = String(url);
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      throw new Error(`unstubbed fetch: ${u}`);
    });
    render(
      <HumanTodoPanel
        initial={[GATE_ITEM, FINDING_ITEM]}
        attest={CAP_ALL}
        selectMode
        onSelect={() => {}}
        selectedId={null}
      />,
    );

    // The defer surfaces mount once the handshake resolves; the gated writers
    // never do — gated OFF by family.
    await waitFor(() => expect(screen.getAllByTestId("defer-form").length).toBe(2));
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
    expect(screen.queryByTestId("finding-review-form")).toBeNull();
    // Their verdict buttons are gone too.
    expect(screen.queryByRole("button", { name: "valid" })).toBeNull();
    expect(screen.queryByRole("button", { name: "needs_revision" })).toBeNull();
  });

  it("keeps BubbleAck, Defer, and the CLI fallback inline in select mode", async () => {
    // Each mounted form self-resolves the page-load-cached
    // GET /api/attest/available — stub it (no live write) so the kept surfaces
    // mount; the gated writers stay suppressed regardless.
    vi.stubGlobal("fetch", async (url: unknown) => {
      const u = String(url);
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      throw new Error(`unstubbed fetch: ${u}`);
    });
    render(
      <HumanTodoPanel
        initial={[GATE_ITEM, BUBBLE_ITEM]}
        attest={CAP_ALL}
        selectMode
        onSelect={() => {}}
        selectedId={null}
      />,
    );

    // bubble_ack is an ack channel, not a gate decision — it stays.
    expect(await screen.findByTestId("bubble-ack-form")).toBeInTheDocument();
    // Defer stays on every blessed kind (the gate item keeps its defer surface).
    expect(screen.getAllByTestId("defer-form").length).toBeGreaterThanOrEqual(1);
    // The verbatim CLI fallback is still rendered per item.
    expect(screen.getAllByTestId("todo-cli-fallback").length).toBeGreaterThanOrEqual(1);
    expect(
      screen.getAllByRole("button", { name: "Copy resolve command" }).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("clicking a row's title selector fires onSelect(id) and drives aria-pressed off selectedId", () => {
    // The selector button renders synchronously (not gated on capability); the
    // kept DeferForm self-fetches the handshake, so stub it quietly.
    vi.stubGlobal("fetch", async (url: unknown) => {
      const u = String(url);
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      throw new Error(`unstubbed fetch: ${u}`);
    });
    const onSelect = vi.fn();
    const { rerender } = render(
      <HumanTodoPanel
        initial={[GATE_ITEM]}
        attest={CAP_ALL}
        selectMode
        onSelect={onSelect}
        selectedId={null}
      />,
    );

    // The hero row's title is a selector button — clicking it selects the id.
    const hero = screen.getByTestId("human-todo-hero");
    const selector = within(hero).getByRole("button", {
      name: /iter-2026-06-09-001 awaiting verdict/,
    });
    expect(selector).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(selector);
    expect(onSelect).toHaveBeenCalledWith("iter-2026-06-09-001");

    // selectedId drives the aria-pressed affordance.
    rerender(
      <HumanTodoPanel
        initial={[GATE_ITEM]}
        attest={CAP_ALL}
        selectMode
        onSelect={onSelect}
        selectedId="iter-2026-06-09-001"
      />,
    );
    expect(
      within(screen.getByTestId("human-todo-hero")).getByRole("button", {
        name: /iter-2026-06-09-001 awaiting verdict/,
      }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("default-off: without selectMode the inline writers render unchanged and the title is not a selector", async () => {
    vi.stubGlobal("fetch", async (url: unknown) => {
      const u = String(url);
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      throw new Error(`unstubbed fetch: ${u}`);
    });
    const onSelect = vi.fn();
    render(
      <HumanTodoPanel
        initial={[GATE_ITEM]}
        attest={CAP_ALL}
        onSelect={onSelect}
        selectedId={null}
      />,
    );

    // The gated writer renders as before.
    expect(await screen.findByTestId("gate-verdict-form")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "valid" })).toBeInTheDocument();
    // The title is plain text, not a selector — clicking it cannot fire onSelect.
    const hero = screen.getByTestId("human-todo-hero");
    expect(
      within(hero).queryByRole("button", {
        name: /iter-2026-06-09-001 awaiting verdict/,
      }),
    ).toBeNull();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("preserves the todo-<kind>-<kindIndex> testid scheme in select mode", () => {
    vi.stubGlobal("fetch", async (url: unknown) => {
      const u = String(url);
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      throw new Error(`unstubbed fetch: ${u}`);
    });
    render(
      <HumanTodoPanel
        initial={[
          { ...GATE_ITEM, id: "iter-a", title: "iter-a awaiting verdict", since: daysAgo(1) },
          { ...GATE_ITEM, id: "iter-b", title: "iter-b awaiting verdict", since: daysAgo(3) },
        ]}
        attest={CAP_ALL}
        selectMode
        onSelect={() => {}}
        selectedId={null}
      />,
    );
    // Newest is the hero; the older one collapses into the group, both keyed by
    // their oldest-first index within the kind.
    expect(screen.getByTestId("human-todo-hero")).toHaveTextContent(
      "iter-a awaiting verdict",
    );
    const group = screen.getByTestId("todo-group-gate_verdict");
    expect(within(group).getByTestId("todo-gate_verdict-0")).toHaveTextContent(
      "iter-b awaiting verdict",
    );
  });

  // --- ADVERSARIAL closure: the §6.5.4 calibration-bypass cannot reopen ---
  //
  // The invariant: in select mode NO verdict-WRITE affordance reaches the inbox
  // for ANY kind — neither the live producer spellings (gate_verdict /
  // finding_review) NOR the legacy generations folded by the deferKindOf family
  // helper (bubble_unacked / state_file_gate). The verdict kinds have NO alias
  // spelling (DEFER_KIND_ALIASES maps gate_verdict→gate_verdict,
  // finding_review→finding_review only), so the only way a verdict writer could
  // leak is the kind arriving verbatim — proved suppressed in BOTH the hero and
  // the expandable group rows below.

  it("suppresses the verdict writers in select mode across BOTH the hero AND the group rows, for every present kind", async () => {
    vi.stubGlobal("fetch", async (url: unknown) => {
      const u = String(url);
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      throw new Error(`unstubbed fetch: ${u}`);
    });
    // Two gate_verdict + two finding_review so each kind has a hero AND a
    // collapsed group row — the suppression must hold in both placements. Plus a
    // finding hero-tier check by giving findings the newest `since`.
    render(
      <HumanTodoPanel
        initial={[
          { kind: "gate_verdict", id: "iter-g1", title: "iter-g1 awaiting verdict", since: daysAgo(2), resolve_command: "gate_cli --iteration-id iter-g1" },
          { kind: "gate_verdict", id: "iter-g2", title: "iter-g2 awaiting verdict", since: daysAgo(4), resolve_command: "gate_cli --iteration-id iter-g2" },
          { kind: "finding_review", id: "f-1", title: "f-1 surfaced", since: daysAgo(3), resolve_command: "finding_session f-1", evidence_level: "L4" },
          { kind: "finding_review", id: "f-2", title: "f-2 surfaced", since: daysAgo(5), resolve_command: "finding_session f-2", evidence_level: "L5" },
        ]}
        attest={CAP_ALL}
        selectMode
        onSelect={() => {}}
        selectedId={null}
      />,
    );

    // Defer mounts for all four (it is kept); the verdict writers never do.
    await waitFor(() => expect(screen.getAllByTestId("defer-form").length).toBe(4));
    // No verdict-WRITE affordance anywhere in the inbox — not the form testids,
    // not their submit buttons. This is the bypass closure for these kinds.
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
    expect(screen.queryByTestId("finding-review-form")).toBeNull();
    expect(screen.queryByRole("button", { name: "valid" })).toBeNull();
    expect(screen.queryByRole("button", { name: "invalid" })).toBeNull();
    expect(screen.queryByRole("button", { name: "needs_revision" })).toBeNull();
    // And the group rows (the expandable second-copy of each kind) carry no
    // writer either — verified by there being exactly zero verdict form nodes.
    expect(screen.queryAllByTestId("gate-verdict-form")).toHaveLength(0);
    expect(screen.queryAllByTestId("finding-review-form")).toHaveLength(0);
  });

  it("suppresses verdict writers for the LEGACY producer spellings too, but keeps their non-verdict surfaces (bubble_unacked → ack stays; state_file_gate → defer-only)", async () => {
    vi.stubGlobal("fetch", async (url: unknown) => {
      const u = String(url);
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      throw new Error(`unstubbed fetch: ${u}`);
    });
    render(
      <HumanTodoPanel
        initial={[
          // legacy ack spelling — folds to bubble_ack; ack is NOT a verdict, stays
          { kind: "bubble_unacked", id: "bub-legacy", title: "legacy bubble", since: daysAgo(1), resolve_command: "ack_cli --bubble-run-id bub-legacy" },
          // legacy state-gate spelling — folds to state_gate; defer-only
          { kind: "state_file_gate", id: "gate-legacy", title: "legacy state gate", since: daysAgo(2), resolve_command: "edit run_state/week1.state.json" },
        ]}
        attest={CAP_ALL}
        selectMode
        onSelect={() => {}}
        selectedId={null}
      />,
    );

    // No verdict writer is reachable for either legacy spelling.
    await waitFor(() => expect(screen.getAllByTestId("defer-form").length).toBeGreaterThanOrEqual(1));
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
    expect(screen.queryByTestId("finding-review-form")).toBeNull();
    // bubble_unacked keeps its ack channel (not a gate decision); state_file_gate
    // keeps only defer. Neither is a calibration-bypassing verdict write.
    expect(screen.getByTestId("bubble-ack-form")).toBeInTheDocument();
  });

  it("HOSTILE: a row with an EMPTY-string id is NOT selectable and never fires onSelect('') — asText('') is '' not null", () => {
    // asText("") returns "" (the string path), so `id !== null` alone would
    // make this row a selector and fire onSelect("") — a bad selection key the
    // cockpit's .find() can never match. The selector guard must require a
    // NON-EMPTY string id; the row still RENDERS (it needs the human) but as
    // plain text, not a clickable selector.
    vi.stubGlobal("fetch", async (url: unknown) => {
      const u = String(url);
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      throw new Error(`unstubbed fetch: ${u}`);
    });
    const onSelect = vi.fn();
    render(
      <HumanTodoPanel
        initial={[
          { kind: "gate_verdict", id: "", title: "empty-id row", since: daysAgo(1), resolve_command: "gate_cli --iteration-id ''" },
        ] as unknown as HumanTodoItem[]}
        attest={CAP_ALL}
        selectMode
        onSelect={onSelect}
        selectedId={null}
      />,
    );
    const hero = screen.getByTestId("human-todo-hero");
    // The row still renders (the human still needs it) — but the title is NOT a
    // selector button.
    expect(hero).toHaveTextContent("empty-id row");
    expect(
      within(hero).queryByRole("button", { name: /empty-id row/ }),
    ).toBeNull();
    // And the verdict writer is suppressed (select mode) regardless.
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("HOSTILE: a row with a NON-STRING id is NOT selectable and never fires onSelect with a bad id", () => {
    // asText(number/object) → null/stringified; an object/array id is dropped to
    // null by asText, so the row must not be a selector. (A numeric id WOULD
    // stringify, but the producer's ids are strings; the attack is the object id
    // that asText refuses to render.)
    vi.stubGlobal("fetch", async (url: unknown) => {
      const u = String(url);
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      throw new Error(`unstubbed fetch: ${u}`);
    });
    const onSelect = vi.fn();
    render(
      <HumanTodoPanel
        initial={[
          { kind: "gate_verdict", id: { nested: "id" }, title: "object-id row", since: daysAgo(1), resolve_command: "gate_cli" },
          { kind: "gate_verdict", id: ["arr", "id"], title: "array-id row", since: daysAgo(2), resolve_command: "gate_cli" },
        ] as unknown as HumanTodoItem[]}
        attest={CAP_ALL}
        selectMode
        onSelect={onSelect}
        selectedId={null}
      />,
    );
    // Neither object-id nor array-id row is a clickable selector.
    expect(screen.queryByRole("button", { name: /object-id row/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /array-id row/ })).toBeNull();
    // No verdict writer leaks; no onSelect fired with a non-string id.
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("HOSTILE: an OBJECT/ARRAY kind groups under 'unknown' and routes through the family helper to suppress every keyed writer in select mode", () => {
    // kind is producer-owned: the parent coerces a non-string kind to "unknown"
    // (asText), deferKindOf("unknown") → null, so NO keyed family renders — the
    // verdict writers cannot leak through an object kind spoofing gate_verdict.
    vi.stubGlobal("fetch", async (url: unknown) => {
      const u = String(url);
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      throw new Error(`unstubbed fetch: ${u}`);
    });
    render(
      <HumanTodoPanel
        initial={[
          { kind: { spoof: "gate_verdict" }, id: "obj-kind-1", title: "object-kind row", since: daysAgo(1), resolve_command: "x" },
          { kind: ["gate_verdict"], id: "arr-kind-1", title: "array-kind row", since: daysAgo(2), resolve_command: "x" },
        ] as unknown as HumanTodoItem[]}
        attest={CAP_ALL}
        selectMode
        onSelect={() => {}}
        selectedId={null}
      />,
    );
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
    expect(screen.queryByTestId("finding-review-form")).toBeNull();
    expect(screen.queryByRole("button", { name: "valid" })).toBeNull();
    // The rows still render under the raw "unknown" group (they need the human).
    expect(screen.getByTestId("todo-group-unknown")).toBeInTheDocument();
  });

  it("clicking the kept Defer / BubbleAck / Copy controls does NOT also fire onSelect (the selector is the title only, not the whole row)", async () => {
    vi.stubGlobal("fetch", async (url: unknown) => {
      const u = String(url);
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      throw new Error(`unstubbed fetch: ${u}`);
    });
    const onSelect = vi.fn();
    render(
      <HumanTodoPanel
        initial={[BUBBLE_ITEM]}
        attest={CAP_ALL}
        selectMode
        onSelect={onSelect}
        selectedId={null}
      />,
    );

    const hero = screen.getByTestId("human-todo-hero");
    // BubbleAck form mounts; clicking inside it (its disclosure summary) must
    // not bubble up to a row-level selection.
    expect(await within(hero).findByTestId("bubble-ack-form")).toBeInTheDocument();

    // The Copy button on the CLI fallback — clicking it must not select the row.
    const copy = within(hero).getByRole("button", { name: "Copy resolve command" });
    fireEvent.click(copy);
    expect(onSelect).not.toHaveBeenCalled();

    // The Defer disclosure summary — clicking it expands defer, not selects.
    const defer = within(hero).getByTestId("defer-form");
    const deferSummary = defer.querySelector("summary");
    if (deferSummary) fireEvent.click(deferSummary);
    expect(onSelect).not.toHaveBeenCalled();

    // Only the title selector fires onSelect — prove the affordance still works.
    const titleSelector = within(hero).getByRole("button", { name: /Bubble from coord-1/ });
    fireEvent.click(titleSelector);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("coord-1");
  });
});
