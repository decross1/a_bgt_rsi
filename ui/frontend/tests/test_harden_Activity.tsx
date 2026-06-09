// Consolidated edge-case + property-fuzz hardening for Activity (merged from per-round files).
//
// This file merges the per-round adversarial hardening suites for the Activity
// route (formerly test_harden_Activity_r1..r5.tsx) into one. Each round keeps its
// own top-level describe so describe/it names never collide, and each round keeps
// its own render helper / lifecycle hooks verbatim.
//
// Helper-name note: rounds 1, 2, 3, and 5 each defined a module-level
// `renderActivityQuiet` with DIFFERENT signatures/bodies. To merge them into one
// module without collision they are suffix-renamed and their call-sites updated:
//   - r1's  (opts: { cycles, monitor })           -> renderActivityQuietR1
//   - r2/r3's (cycles: unknown)  [identical body]  -> renderActivityQuietCycles
//   - r5's  (monitor: unknown, captures `threw`)   -> renderActivityQuietMonitor
// r4's self-polling `renderQuietly` was already uniquely named and is unchanged.
// The ResizeObserver `beforeAll` shim (identical across r1/r2/r3/r5, idempotent)
// is hoisted once. r4's vi.mock(...) calls are module-hoisted and apply to the
// whole file, but rounds 1/2/3/5 render fully static (every initial* prop is
// injected, so Activity's `live` gates skip every poll) and never invoke the
// mocked api/http + api/activity fetchers, so the mocks are inert for them.

import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { GRAPH_FIXTURE, MONITOR_FIXTURE_IDLE } from "../src/fixtures/activity";
import type {
  ActiveRun,
  MonitorResponse,
  MonitorWorker,
} from "../src/types/activity";
import type { CoordinatorCycle } from "../src/types/schemas";

// ---------------------------------------------------------------------------
// r4 module-hoisted mocks (vi.mock is hoisted above all imports). These power
// the round-4 self-polling render only; the static rounds never call them.
// ---------------------------------------------------------------------------

// vi.mock factories are hoisted above the module body, so the shared data lives
// in a vi.hoisted block (the same pattern test_validate_routes_console.tsx uses).
// `box.run` is the per-test knob for active_run.json; the rest hand back a quiet
// idle monitor so only the enum vectors are under test.
const H = vi.hoisted(() => {
  const MONITOR: MonitorResponse = {
    available: true,
    telemetry_available: false,
    active: [],
    recent: [],
    last_activity_at: "2026-06-09T07:19:25.392025Z",
    live_calls: {
      active: false,
      count: 0,
      window_s: 60,
      calls_per_s: null,
      last_call_at: null,
      caller_tags: [],
      model: null,
    },
    synthetic_inference: {
      synthetic: true,
      source: "fixture",
      needs: "worker_activity.jsonl",
      note: "synthetic placeholder",
      workers: [],
    },
    generated_at: "2026-06-09T07:20:00.000000Z",
  };
  const GRAPH = {
    available: true,
    nodes: [],
    edges: [],
    detail: "overview",
    generated_at: "2026-06-09T07:20:00.000000Z",
  };
  // A cycle carrying NOVEL enum values across the board: an unseen
  // `topic_source` ("nemoclaw_agent"), an unseen overall `status`
  // ("quantum_superposition"), and a per-action outcome with an unseen
  // `status` ("degraded") alongside a real "errored" row. The route must (a)
  // not crash, (b) still surface the errored action as a red failed-dispatch
  // row, and (c) NOT invent a row for the unknown-status action.
  const CYCLE_FORWARD: CoordinatorCycle = {
    timestamp: "2026-06-09T07:19:25.392025Z",
    run_id: "coordinator_fwd01",
    agent: "coordinator",
    topic: "forward-compat enum probe",
    topic_source: "nemoclaw_agent",
    status: "quantum_superposition",
    plan: [
      { action: "run_loop_iteration", args: { topic: "x" } },
      { action: "nemoclaw_dispatch", args: {} },
    ],
    outcomes: [
      // a never-seen per-action status — must be ignored, not a spurious row
      { action: "nemoclaw_dispatch", status: "degraded" as unknown as "passed" },
      // a real errored action — must still become an explicit red row
      {
        action: "run_loop_iteration",
        status: "errored",
        error: "RuntimeError: nemoclaw sandbox not provisioned",
      },
    ],
    promoted_finding_ids: [],
    bubble_run_ids: [],
  };
  const box: { run: unknown } = { run: null };
  return { MONITOR, GRAPH, CYCLE_FORWARD, box };
});

vi.mock("../src/api/http", () => ({
  getActiveIteration: vi.fn().mockResolvedValue(null),
  getCoordinatorActive: vi.fn().mockResolvedValue(null),
  getCoordinatorCycles: vi
    .fn()
    .mockResolvedValue({ cycles: [H.CYCLE_FORWARD] }),
}));
vi.mock("../src/api/activity", () => ({
  getActivityGraph: vi.fn().mockResolvedValue(H.GRAPH),
  getActivityMonitor: vi.fn().mockResolvedValue(H.MONITOR),
  getActiveRun: vi.fn().mockImplementation(() => Promise.resolve(H.box.run)),
}));

import Activity from "../src/routes/Activity";

// @xyflow/react reaches for ResizeObserver on mount; jsdom lacks it (same shim
// the neighbor monitor test installs). Idempotent — one install covers every
// round below.
beforeAll(() => {
  if (typeof globalThis.ResizeObserver === "undefined") {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  }
});

// ===========================================================================
// Round 1 — absent optional fields on producer-owned rows
// ===========================================================================

// Render the page fully static (no polling) with the given coordinator cycles
// and monitor, while spying on console.error/warn. Returns the spies + a render
// handle so a test can both assert "no console noise" and inspect the DOM.
function renderActivityQuietR1(opts: {
  cycles: CoordinatorCycle[];
  monitor: MonitorResponse;
}) {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  const handle = render(
    <MemoryRouter>
      <Activity
        initialGraph={GRAPH_FIXTURE}
        initialMonitor={opts.monitor}
        initialIteration={null}
        initialActiveRun={null}
        initialCoordinatorActive={null}
        initialCoordinatorCycles={opts.cycles}
      />
    </MemoryRouter>,
  );
  const calls = {
    error: errSpy.mock.calls.map((c) => String(c[0])),
    warn: warnSpy.mock.calls.map((c) => String(c[0])),
  };
  errSpy.mockRestore();
  warnSpy.mockRestore();
  return { handle, calls };
}

describe("Activity hardening — absent optional fields on producer-owned rows", () => {
  afterEach(() => vi.restoreAllMocks());

  it("survives a coordinator cycle row with NO outcomes array (was: not iterable)", () => {
    // A legacy/partial row: a real plan, but `outcomes` omitted entirely.
    const LEGACY_NO_OUTCOMES = [
      {
        timestamp: "2026-06-09T07:00:00Z",
        run_id: "coordinator_legacy",
        agent: "coordinator",
        topic: "legacy topic, no outcomes recorded",
        topic_source: "arxiv_pick",
        status: "planned",
        plan: [{ action: "run_loop_iteration", args: { topic: "x" } }],
        // outcomes intentionally ABSENT
      } as unknown as CoordinatorCycle,
    ];
    const { handle, calls } = renderActivityQuietR1({
      cycles: LEGACY_NO_OUTCOMES,
      monitor: MONITOR_FIXTURE_IDLE,
    });
    // The page rendered its landmark hero — not a blank/thrown surface.
    expect(handle.getByTestId("active-now")).toBeInTheDocument();
    expect(handle.getByTestId("coordinator-activity")).toBeInTheDocument();
    // No errored outcome -> no failed-dispatch surface, and crucially no crash.
    expect(handle.queryByTestId("failed-dispatches")).toBeNull();
    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });

  // NOTE: a monitor payload missing the `active` array entirely ALSO crashes —
  // but in the CHILD component ActiveWorkersPanel.tsx:88 (`data.active.length`),
  // which this round may not edit. Activity's own idle-gate read is now guarded
  // (`monitor?.active?.length ?? 0`); the ActiveWorkersPanel guard is reported
  // as a followup for the serial integrator. No full-page test for that case
  // here, since the page cannot render past the un-owned child until it is fixed.

  it("still surfaces an errored action when a SIBLING row in the batch is malformed", () => {
    // One well-formed errored row + one row missing outcomes. The malformed row
    // must be skipped silently; the errored one must STILL produce its explicit
    // red failed-dispatch row (absence of a bad row never hides a real failure).
    const MIXED = [
      {
        timestamp: "2026-06-09T07:01:00Z",
        run_id: "coordinator_bad",
        agent: "coordinator",
        topic: "malformed sibling",
        topic_source: "arxiv_pick",
        plan: [{ action: "noop" }],
        // outcomes ABSENT
      } as unknown as CoordinatorCycle,
      {
        timestamp: "2026-06-09T07:02:00Z",
        run_id: "coordinator_good",
        agent: "coordinator",
        topic: "real failure",
        topic_source: "arxiv_pick",
        status: "executed",
        plan: [{ action: "noop", args: { reason: "x" } }],
        outcomes: [
          { action: "noop", status: "errored", error: "RuntimeError: boom" },
        ],
        promoted_finding_ids: [],
        bubble_run_ids: [],
      } as unknown as CoordinatorCycle,
    ];
    const { handle, calls } = renderActivityQuietR1({
      cycles: MIXED,
      monitor: MONITOR_FIXTURE_IDLE,
    });
    const failed = handle.getByTestId("failed-dispatches");
    const row = within(failed).getByTestId("failed-dispatch-coordinator_good");
    expect(row).toHaveTextContent("noop");
    expect(row).toHaveTextContent("RuntimeError: boom");
    // Exactly one failed-dispatch row (the malformed sibling contributed none).
    expect(
      failed.querySelectorAll('[data-testid^="failed-dispatch-"]'),
    ).toHaveLength(1);
    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });

  it("does not emit a duplicate React key when two errored rows both lack run_id", () => {
    // Two producer rows both missing run_id, each with an errored action of the
    // same name. The old key `${run_id}-${action}` collided to `undefined-noop`
    // for both -> a React duplicate-key console.error. The key now folds in the
    // index, so the batch renders both rows quietly.
    const TWO_NO_RUNID = [
      {
        timestamp: "2026-06-09T07:03:00Z",
        agent: "coordinator",
        topic: "first",
        topic_source: "arxiv_pick",
        plan: [{ action: "noop" }],
        outcomes: [{ action: "noop", status: "errored", error: "boom A" }],
      } as unknown as CoordinatorCycle,
      {
        timestamp: "2026-06-09T07:04:00Z",
        agent: "coordinator",
        topic: "second",
        topic_source: "arxiv_pick",
        plan: [{ action: "noop" }],
        outcomes: [{ action: "noop", status: "errored", error: "boom B" }],
      } as unknown as CoordinatorCycle,
    ];
    const { handle, calls } = renderActivityQuietR1({
      cycles: TWO_NO_RUNID,
      monitor: MONITOR_FIXTURE_IDLE,
    });
    const failed = handle.getByTestId("failed-dispatches");
    expect(
      failed.querySelectorAll('[data-testid^="failed-dispatch-"]'),
    ).toHaveLength(2);
    expect(failed).toHaveTextContent("boom A");
    expect(failed).toHaveTextContent("boom B");
    // The duplicate-key warning React prints is a console.error — assert none.
    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });
});

// ===========================================================================
// Round 2 — malformed value TYPES on producer-owned rows
// ===========================================================================

// Render the page fully static (no polling) with the given coordinator cycles,
// while spying on console.error/warn. `cycles` is typed loosely on purpose — the
// whole point is to feed malformed-TYPE values a producer could emit but the
// TS contract forbids. Returns the spies + a render handle.
// (Shared verbatim with round 3 — identical body, so a single helper serves both.)
function renderActivityQuietCycles(cycles: unknown) {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  const handle = render(
    <MemoryRouter>
      <Activity
        initialGraph={GRAPH_FIXTURE}
        initialMonitor={MONITOR_FIXTURE_IDLE}
        initialIteration={null}
        initialActiveRun={null}
        initialCoordinatorActive={null}
        initialCoordinatorCycles={cycles as CoordinatorCycle[]}
      />
    </MemoryRouter>,
  );
  const calls = {
    error: errSpy.mock.calls.map((c) => String(c[0])),
    warn: warnSpy.mock.calls.map((c) => String(c[0])),
  };
  errSpy.mockRestore();
  warnSpy.mockRestore();
  return { handle, calls };
}

describe("Activity hardening r2 — malformed value TYPES on producer-owned rows", () => {
  afterEach(() => vi.restoreAllMocks());

  it("survives `cycles` arriving as a non-array object (was: cycles is not iterable)", () => {
    // A degraded backend / hand-edited state: the cycles payload is an object,
    // not the contract's list. The page must render its hero, not throw.
    const BAD_CYCLES = { run_id: "oops", outcomes: [] } as unknown;
    const { handle, calls } = renderActivityQuietCycles(BAD_CYCLES);
    expect(handle.getByTestId("active-now")).toBeInTheDocument();
    expect(handle.getByTestId("coordinator-activity")).toBeInTheDocument();
    // No iterable cycles → no failed-dispatch surface, and crucially no crash.
    expect(handle.queryByTestId("failed-dispatches")).toBeNull();
    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });

  it("survives a row whose `outcomes` is a non-array (object/string), not the contract list", () => {
    // Two malformed rows: outcomes as a dict, and outcomes as a bare string.
    // Both are skipped (no errored outcome can be read), never a crash.
    const BAD_OUTCOMES = [
      {
        timestamp: "2026-06-09T07:00:00Z",
        run_id: "coordinator_dict_outcomes",
        agent: "coordinator",
        topic: "outcomes is a dict",
        topic_source: "arxiv_pick",
        plan: [{ action: "run_loop_iteration" }],
        outcomes: { action: "run_loop_iteration", status: "errored" },
      } as unknown as CoordinatorCycle,
      {
        timestamp: "2026-06-09T07:01:00Z",
        run_id: "coordinator_str_outcomes",
        agent: "coordinator",
        topic: "outcomes is a string",
        topic_source: "arxiv_pick",
        plan: [{ action: "run_loop_iteration" }],
        outcomes: "errored",
      } as unknown as CoordinatorCycle,
    ];
    const { handle, calls } = renderActivityQuietCycles(BAD_OUTCOMES);
    expect(handle.getByTestId("coordinator-activity")).toBeInTheDocument();
    // Neither malformed row can yield an errored OUTCOME, so no red surface.
    expect(handle.queryByTestId("failed-dispatches")).toBeNull();
    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });

  it("renders a numeric epoch `timestamp` without throwing or printing NaN", () => {
    // The producer wrote timestamp as epoch millis (a number), not an ISO string.
    // The row carries a real errored action, so its red row MUST still render —
    // and shortTimestamp must not throw on `(number).replace` nor print "NaN".
    const NUM_TS = [
      {
        timestamp: 1717916400000 as unknown as string,
        run_id: "coordinator_numeric_ts",
        agent: "coordinator",
        topic: "numeric timestamp row",
        topic_source: "arxiv_pick",
        status: "executed",
        plan: [{ action: "run_loop_iteration", args: { k: 8 } }],
        outcomes: [
          {
            action: "run_loop_iteration",
            status: "errored",
            error: "RuntimeError: dispatch failed",
          },
        ],
        promoted_finding_ids: [],
        bubble_run_ids: [],
      } as unknown as CoordinatorCycle,
    ];
    const { handle, calls } = renderActivityQuietCycles(NUM_TS);
    const failed = handle.getByTestId("failed-dispatches");
    const row = within(failed).getByTestId("failed-dispatch-coordinator_numeric_ts");
    // The real failure is still surfaced (the bad timestamp didn't swallow it).
    expect(row).toHaveTextContent("run_loop_iteration");
    expect(row).toHaveTextContent("RuntimeError: dispatch failed");
    // Never the literal "NaN" anywhere in the surfaced row.
    expect(row.textContent ?? "").not.toContain("NaN");
    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });

  it("still surfaces a real errored row when a SIBLING row carries malformed-type fields", () => {
    // Mixed batch: a row with a non-array `outcomes` (skipped) + a well-formed
    // errored row. The malformed sibling must not hide the real failure, and the
    // batch must render quietly (no thrown route, no console noise).
    const MIXED = [
      {
        timestamp: "2026-06-09T07:02:00Z",
        run_id: "coordinator_bad_type",
        agent: "coordinator",
        topic: "malformed sibling (outcomes is an object)",
        topic_source: "arxiv_pick",
        plan: [{ action: "noop" }],
        outcomes: { action: "noop", status: "errored" },
      } as unknown as CoordinatorCycle,
      {
        timestamp: "2026-06-09T07:03:00Z",
        run_id: "coordinator_good",
        agent: "coordinator",
        topic: "real failure",
        topic_source: "arxiv_pick",
        status: "executed",
        plan: [{ action: "noop", args: { reason: "x" } }],
        outcomes: [{ action: "noop", status: "errored", error: "boom" }],
        promoted_finding_ids: [],
        bubble_run_ids: [],
      } as unknown as CoordinatorCycle,
    ];
    const { handle, calls } = renderActivityQuietCycles(MIXED);
    const failed = handle.getByTestId("failed-dispatches");
    const row = within(failed).getByTestId("failed-dispatch-coordinator_good");
    expect(row).toHaveTextContent("noop");
    expect(row).toHaveTextContent("boom");
    // Exactly one failed-dispatch row (the malformed-type sibling contributed none).
    expect(
      failed.querySelectorAll('[data-testid^="failed-dispatch-"]'),
    ).toHaveLength(1);
    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });
});

// ===========================================================================
// Round 3 — scale + content on producer-owned rows
// (reuses renderActivityQuietCycles — identical helper body to round 2)
// ===========================================================================

describe("Activity hardening r3 — scale + content on producer-owned rows", () => {
  afterEach(() => vi.restoreAllMocks());

  it("A: renders a 5k-char unbroken string in topic/action/error without throwing", () => {
    const big = "x".repeat(5000);
    const BIG_STRINGS = [
      {
        timestamp: "2026-06-09T07:00:00Z",
        run_id: "coordinator_bigstr",
        agent: "coordinator",
        topic: big,
        topic_source: "arxiv_pick",
        status: "executed",
        plan: [{ action: "run_loop_iteration", args: { k: 8 } }],
        outcomes: [{ action: big, status: "errored", error: big }],
        promoted_finding_ids: [],
        bubble_run_ids: [],
      } as unknown as CoordinatorCycle,
    ];
    const { handle, calls } = renderActivityQuietCycles(BIG_STRINGS);
    const row = within(handle.getByTestId("failed-dispatches")).getByTestId(
      "failed-dispatch-coordinator_bigstr",
    );
    // The full 5k string is present (not truncated away into a crash/blank).
    expect(row.textContent ?? "").toContain(big);
    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });

  it("B: renders 1500 errored rows with no duplicate-key warning or crash", () => {
    const MANY = Array.from({ length: 1500 }, (_, i) => ({
      timestamp: "2026-06-09T07:00:00Z",
      run_id: `coordinator_${i}`,
      agent: "coordinator",
      topic: `topic ${i}`,
      topic_source: "arxiv_pick",
      plan: [{ action: "noop" }],
      outcomes: [{ action: "noop", status: "errored", error: `boom ${i}` }],
    })) as unknown as CoordinatorCycle[];
    const { handle, calls } = renderActivityQuietCycles(MANY);
    const rendered = handle
      .getByTestId("failed-dispatches")
      .querySelectorAll('[data-testid^="failed-dispatch-"]');
    expect(rendered).toHaveLength(1500);
    // No React duplicate-key warning (it surfaces as a console.error) and no throw.
    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });

  it("C: renders unicode/emoji/RTL/newline/HTML-looking text as inert literal text", () => {
    // RTL override (U+202E), emoji, Arabic, a tab/newline, and an HTML-looking
    // <script> tag — all in producer text fields. React escapes text children, so
    // <script> is literal text, never markup; nothing throws or warns.
    const nasty = "نص عربي 🚀\n<script>alert(1)</script>\t 😀 ❤️ ‮RTL";
    const NASTY = [
      {
        timestamp: "2026-06-09T07:00:00Z",
        run_id: "coordinator_unicode",
        agent: "coordinator",
        topic: nasty,
        topic_source: "arxiv_pick",
        plan: [{ action: "noop" }],
        outcomes: [{ action: "noop", status: "errored", error: nasty }],
      } as unknown as CoordinatorCycle,
    ];
    const { handle, calls } = renderActivityQuietCycles(NASTY);
    const failed = handle.getByTestId("failed-dispatches");
    // The HTML-looking text is escaped to a text node, not parsed into an element:
    // no real <script> element exists in the rendered DOM.
    expect(failed.querySelector("script")).toBeNull();
    // The literal text is present (the topic + error both carry it).
    expect(failed.textContent ?? "").toContain("<script>alert(1)</script>");
    expect(failed.textContent ?? "").toContain("🚀");
    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });

  it("D: survives a non-string object/array in topic/action/error (was: Objects are not valid as a React child)", () => {
    // The producer wrote a structured value where the contract says string: topic
    // as an object, action as an array, error as a structured error object. Pre-fix
    // these reached JSX as React children and threw, blanking the whole page. They
    // must now render (coerced to text) and the page must stay up + console-quiet.
    const OBJ_FIELDS = [
      {
        timestamp: "2026-06-09T07:00:00Z",
        run_id: "coordinator_objfields",
        agent: "coordinator",
        topic: { label: "structured topic" } as unknown as string,
        topic_source: "arxiv_pick",
        status: "executed",
        plan: [{ action: "run_loop_iteration" }],
        outcomes: [
          {
            action: ["run_loop_iteration", "retry"] as unknown as string,
            status: "errored",
            error: { type: "ValueError", msg: "bad enum" } as unknown as string,
          },
        ],
        promoted_finding_ids: [],
        bubble_run_ids: [],
      } as unknown as CoordinatorCycle,
    ];
    const { handle, calls } = renderActivityQuietCycles(OBJ_FIELDS);
    // The page survived: its hero + the failed-dispatch surface both rendered.
    expect(handle.getByTestId("active-now")).toBeInTheDocument();
    const row = within(handle.getByTestId("failed-dispatches")).getByTestId(
      "failed-dispatch-coordinator_objfields",
    );
    // The structured error is surfaced as text (coerced), not swallowed into a
    // crash — the human still sees that this dispatch errored, and roughly why.
    expect(row.textContent ?? "").toContain("bad enum");
    // Crucially: no "Objects are not valid as a React child" (a console.error) and
    // no throw that would blank the page.
    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });

  it("D2: a non-string object SIBLING row never hides a real string-error failure", () => {
    // Mixed batch: a row whose error is an object (coerced, rendered) + a normal
    // string-error row. Both must surface as explicit red rows — the coercion path
    // must not swallow the well-formed failure beside it.
    const MIXED = [
      {
        timestamp: "2026-06-09T07:01:00Z",
        run_id: "coordinator_objerr",
        agent: "coordinator",
        topic: "object-error row",
        topic_source: "arxiv_pick",
        plan: [{ action: "noop" }],
        outcomes: [
          { action: "noop", status: "errored", error: { code: 500 } as unknown as string },
        ],
      } as unknown as CoordinatorCycle,
      {
        timestamp: "2026-06-09T07:02:00Z",
        run_id: "coordinator_good",
        agent: "coordinator",
        topic: "string-error row",
        topic_source: "arxiv_pick",
        status: "executed",
        plan: [{ action: "noop", args: { reason: "x" } }],
        outcomes: [{ action: "noop", status: "errored", error: "RuntimeError: boom" }],
        promoted_finding_ids: [],
        bubble_run_ids: [],
      } as unknown as CoordinatorCycle,
    ];
    const { handle, calls } = renderActivityQuietCycles(MIXED);
    const failed = handle.getByTestId("failed-dispatches");
    expect(
      failed.querySelectorAll('[data-testid^="failed-dispatch-"]'),
    ).toHaveLength(2);
    expect(failed).toHaveTextContent("RuntimeError: boom");
    expect(failed).toHaveTextContent("500");
    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });
});

// ===========================================================================
// Round 4 — unknown / forward-compat enum values (self-polling, mocked fetchers)
// ===========================================================================

// Render Activity (self-polling, against the mocked fetchers), flush the async
// polls, and return any console.error/warn the render path emitted. A thrown
// render surfaces as a console.error here too, so a crash is caught either way.
async function renderQuietly() {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  render(
    <MemoryRouter>
      <Activity />
    </MemoryRouter>,
  );
  await waitFor(() => expect(true).toBe(true));
  await waitFor(() => expect(true).toBe(true));
  const calls = {
    error: errSpy.mock.calls.map((c) => String(c[0])),
    warn: warnSpy.mock.calls.map((c) => String(c[0])),
  };
  errSpy.mockRestore();
  warnSpy.mockRestore();
  return calls;
}

describe("Activity hardening r4: unknown / forward-compat enum values", () => {
  afterEach(() => {
    vi.clearAllMocks();
    H.box.run = null;
  });

  it("renders a NOVEL string active_run.kind verbatim (forward-compat path)", async () => {
    // A kind the type's union has never seen — the live EMIT contract literally
    // adds "coordinator"/"nemoclaw_agent". It must read as plain text.
    H.box.run = {
      run_id: "run-nemo-1",
      kind: "nemoclaw_agent",
      label: "nemoclaw sandbox run",
      started_at: "2026-06-09T07:00:00.000000Z",
    } as ActiveRun;
    const { error, warn } = await renderQuietly();
    const strip = screen.getByTestId("activity-status");
    expect(strip.textContent).toContain("nemoclaw_agent");
    expect(strip.textContent).toContain("run is in flight");
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("does not crash when active_run.kind is a non-string (malformed row)", async () => {
    // Producer-owned active_run.json: a legacy/malformed row carries kind as an
    // object. Before the fix this threw "Objects are not valid as a React
    // child" at the status strip and blanked the whole page.
    H.box.run = {
      run_id: "run-bad-1",
      kind: { name: "weird" } as unknown as string,
      label: "malformed run",
      started_at: "2026-06-09T07:00:00.000000Z",
    } as ActiveRun;
    const { error, warn } = await renderQuietly();
    // The hero region must still mount; the strip still reads "live" (a run is
    // in flight regardless of kind) and never renders the raw object.
    expect(screen.getByTestId("active-now")).toBeInTheDocument();
    const strip = screen.getByTestId("activity-status");
    expect(strip.textContent).toContain("run is in flight");
    expect(strip.textContent).not.toContain("[object Object]");
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("handles novel cycle topic_source / status + an unseen per-action outcome status", async () => {
    // No active run; the cycle carries the never-seen enum values. The failed-
    // dispatch surface must still show the one ERRORED action as a red row, must
    // NOT invent a row for the unknown-status ("degraded") action, and the page
    // must not crash on the unseen topic_source / overall status.
    H.box.run = null;
    const { error, warn } = await renderQuietly();
    const failed = await waitFor(() =>
      screen.getByTestId("failed-dispatches"),
    );
    expect(failed.textContent).toContain(
      "RuntimeError: nemoclaw sandbox not provisioned",
    );
    // exactly one failed-dispatch row (only the errored action; the unknown
    // "degraded" status is quietly skipped, not surfaced as a failure).
    expect(
      failed.querySelectorAll('[data-testid^="failed-dispatch-"]'),
    ).toHaveLength(1);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });
});

// ===========================================================================
// Round 5 — empty-vs-absent collections + boundary numbers
// ===========================================================================

// A valid synthetic_inference block so SyntheticInferencePanel (an un-owned
// child) stays on its happy path; the monitor-collection vectors are the only
// thing under test here.
const SYN_OK = {
  synthetic: true,
  source: "fixture",
  needs: "worker_activity.jsonl",
  note: "synthetic placeholder",
  workers: [],
};

// Render the page fully static (no polling) with the given monitor payload,
// while spying on console.error/warn. `monitor` is typed loosely on purpose —
// the whole point is to feed empty-vs-absent / wrong-typed collections a
// producer could emit but the TS contract narrows away. Returns the spies + a
// render handle. A thrown render is captured (not rethrown) so a crash is an
// assertable value, not a test-runner abort.
function renderActivityQuietMonitor(monitor: unknown) {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  let threw: unknown = null;
  let handle: ReturnType<typeof render> | null = null;
  try {
    handle = render(
      <MemoryRouter>
        <Activity
          initialGraph={GRAPH_FIXTURE}
          initialMonitor={monitor as MonitorResponse}
          initialIteration={null}
          initialActiveRun={null}
          initialCoordinatorActive={null}
          initialCoordinatorCycles={[]}
        />
      </MemoryRouter>,
    );
  } catch (e) {
    threw = e;
  }
  const calls = {
    error: errSpy.mock.calls.map((c) => String(c[0])),
    warn: warnSpy.mock.calls.map((c) => String(c[0])),
  };
  errSpy.mockRestore();
  warnSpy.mockRestore();
  return { handle, calls, threw };
}

describe("Activity hardening r5 — empty-vs-absent collections + boundary numbers", () => {
  afterEach(() => vi.restoreAllMocks());

  it("survives a monitor whose `active` is a non-array string (was: phantom count + data.active.map crash)", () => {
    // The degrade path wrote a status string where the list was expected. Pre-fix
    // this BOTH read "7 tasks active now" (the 7-char string's `.length`) AND
    // threw `data.active.map is not a function`, blanking the page.
    const BAD: unknown = {
      available: true,
      telemetry_available: false,
      active: "errored",
      recent: [],
      last_activity_at: "2026-06-09T07:19:25.392025Z",
      synthetic_inference: SYN_OK,
      generated_at: "2026-06-09T07:20:00.000000Z",
    };
    const { handle, calls, threw } = renderActivityQuietMonitor(BAD);
    // (a) The route did NOT throw — the page mounted past the bad scalar.
    expect(threw, `route threw: ${String(threw)}`).toBeNull();
    expect(handle!.getByTestId("active-now")).toBeInTheDocument();
    // (b) No phantom count: the strip reads the genuine idle state, not the
    // "…active now." phrasing derived from a string's `.length` (pre-fix it said
    // "7 tasks active now." from the 7-char "errored").
    const strip = handle!.getByTestId("activity-status");
    expect(strip.textContent).toContain("Idle");
    expect(strip.textContent ?? "").not.toContain("active now");
    expect(strip.textContent ?? "").not.toMatch(/\d+ tasks?/);
    // (c) ActiveWorkersPanel rendered its empty state (a real [] now), not a crash.
    expect(handle!.getByTestId("active-workers-empty")).toBeInTheDocument();
    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });

  it("survives a monitor whose `active` is a non-array object", () => {
    // A different malformed shape a producer could emit: `active` as a dict.
    // Same boundary normalization applies — read as empty, no crash.
    const BAD: unknown = {
      available: true,
      telemetry_available: false,
      active: { task_id: "x", status: "running" },
      recent: [],
      last_activity_at: "2026-06-09T07:19:25.392025Z",
      synthetic_inference: SYN_OK,
      generated_at: "2026-06-09T07:20:00.000000Z",
    };
    const { handle, calls, threw } = renderActivityQuietMonitor(BAD);
    expect(threw, `route threw: ${String(threw)}`).toBeNull();
    expect(handle!.getByTestId("active-workers-empty")).toBeInTheDocument();
    const strip = handle!.getByTestId("activity-status");
    expect(strip.textContent).toContain("Idle");
    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });

  it("survives a monitor with `active`/`recent` both ABSENT (partial body)", () => {
    // A partial /api/activity/monitor body that omitted the collections entirely.
    // The idle gate + ActiveWorkersPanel must read them as empty arrays.
    const PARTIAL: unknown = {
      available: true,
      telemetry_available: false,
      last_activity_at: "2026-06-09T07:19:25.392025Z",
      synthetic_inference: SYN_OK,
      generated_at: "2026-06-09T07:20:00.000000Z",
    };
    const { handle, calls, threw } = renderActivityQuietMonitor(PARTIAL);
    expect(threw, `route threw: ${String(threw)}`).toBeNull();
    expect(handle!.getByTestId("active-now")).toBeInTheDocument();
    expect(handle!.getByTestId("active-workers-empty")).toBeInTheDocument();
    // Genuinely idle (no workers, no run, no live calls) → the idle empty-state
    // renders rather than a blank gap.
    expect(handle!.getByTestId("activity-idle-empty")).toBeInTheDocument();
    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });

  it("BOUNDARY: a single real active worker still reads the singular '1 task active now.'", () => {
    // Guards that the normalization left the happy path + the `=== 1` plural
    // boundary intact: one real worker → "1 task" (not "1 tasks"), strip is live,
    // and the idle empty-state stays hidden.
    const ONE: MonitorWorker = {
      task_id: "seq-1",
      task_type: "summarize_paper",
      status: "running",
      worker_pid: 4242,
      timestamp: "2026-06-09T07:19:43.5Z",
      stage: "worker_invocation",
      detail: "spawning worker process",
      cpu_pct: 12.5,
      rss_mb: 660.2,
    };
    const M: MonitorResponse = {
      available: true,
      telemetry_available: true,
      active: [ONE],
      recent: [ONE],
      last_activity_at: "2026-06-09T07:19:43.5Z",
      synthetic_inference: SYN_OK,
      generated_at: "2026-06-09T07:20:00.000000Z",
    };
    const { handle, calls, threw } = renderActivityQuietMonitor(M);
    expect(threw, `route threw: ${String(threw)}`).toBeNull();
    const strip = handle!.getByTestId("activity-status");
    expect(strip.textContent).toContain("1 task active now.");
    expect(strip.textContent ?? "").not.toContain("1 tasks");
    // Live, not idle: the idle empty-state must be absent.
    expect(handle!.queryByTestId("activity-idle-empty")).toBeNull();
    // The one worker rendered as a row (the happy path is untouched).
    expect(
      within(handle!.getByTestId("active-workers-panel")).getByTestId("worker-seq-1"),
    ).toBeInTheDocument();
    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });
});
