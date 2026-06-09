// REAL-DATA validation for the coordinator "active phases" surface
// (CoordinatorPhases, fed by getCoordinatorActive()). The companion
// test_coordinator_phases.tsx covers the component against the fixture; THIS
// file validates the end-to-end render path against the shapes the LIVE
// backend actually returns — the two real cases observed on 2026-06-09:
//
//   (a) run_state/active_run.json is ABSENT → GET /api/coordinator/active is
//       204 (verified in-process against the real repo) → getCoordinatorActive()
//       resolves null → CoordinatorPhases renders the QUIET IDLE state
//       (data-testid coordinator-idle), never a blank gap or a crash.
//   (b) a real coordinator cycle is in flight → the backend serves the
//       active_run JSON the producer writes (orchestrator/active_run.py +
//       schema/active_run.schema.json) → CoordinatorPhases renders the
//       assess→plan→validate→dispatch stepper with the chosen-topic narration.
//
// We drive getCoordinatorActive() itself (not a hand-built prop) so the 204→null
// contract is exercised, mocking fetch the way test_baseline_card.tsx /
// test_activity_monitor.tsx do. Each case also asserts a clean render: no
// console.error / console.warn (the "renders without console errors" gate —
// there is no headless browser, so jsdom + a console spy stands in).
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CoordinatorPhases from "../src/components/CoordinatorPhases";
import { getCoordinatorActive } from "../src/api/http";
import type { CoordinatorActiveRun } from "../src/types/schemas";

// A real coordinator active_run, shaped from orchestrator/active_run.py's
// write_active_run/update_active_run + schema/active_run.schema.json (NOT the
// test fixture): required {run_id, kind, label, started_at}, plus current_step
// / step_started_at / narration from update_active_run. `n_err` is a
// schema-allowed (additionalProperties:true) field the component never reads —
// included to prove real rows with extra keys render fine. There is NO
// top-level `topic` field — the chosen topic lives in narration (per the EMIT
// reconciliation in ui_plan.md §AUTONOMY OBSERVABILITY).
const REAL_ACTIVE_RUN: CoordinatorActiveRun & { n_err: number } = {
  run_id: "coordinator-2026-06-09T12:00:00",
  kind: "coordinator",
  label: "coordinator_cycle",
  started_at: "2026-06-09T12:00:00+00:00",
  current_step: "dispatch",
  step_started_at: "2026-06-09T12:00:30+00:00",
  narration:
    "Chose 'Truthfulness of VCG in combinatorial auctions' " +
    "(topic_source=coordinator) — lowest-coverage game-theory topic in the " +
    "last 9 iterations; dispatching a loop iteration at k=8.",
  n_err: 0,
};

// Mirror the live backend's 204 (active_run.json absent): empty body, status
// 204. getCoordinatorActive() branches on resp.status === 204 → null. Matches
// the {status:204, ok:false} mock in test_activity_monitor.tsx.
function mockFetch204(): void {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    status: 204,
    ok: false,
  } as Response);
}

function mockFetchActive(run: CoordinatorActiveRun): void {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    status: 200,
    ok: true,
    json: async () => run,
  } as Response);
}

describe("CoordinatorPhases — validated against live backend shapes", () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("absent active_run.json → 204 → getCoordinatorActive() null → quiet idle (no crash)", async () => {
    mockFetch204();

    // The real backend returns 204 when run_state/active_run.json is absent
    // (validated in-process against the real repo). The helper must yield null,
    // not throw.
    const activeRun = await getCoordinatorActive();
    expect(activeRun).toBeNull();

    render(<CoordinatorPhases activeRun={activeRun} />);

    // Absence is legible: the idle state renders, not a blank gap.
    expect(screen.getByTestId("coordinator-phases")).toBeInTheDocument();
    expect(screen.getByTestId("coordinator-idle")).toHaveTextContent(
      "coordinator idle",
    );
    // No stepper / phase chips / narration in the idle state.
    expect(screen.queryByTestId("coordinator-stepper")).toBeNull();
    expect(screen.queryByTestId("phase-dispatch")).toBeNull();
    expect(screen.queryByTestId("coordinator-narration")).toBeNull();

    // Renders without console errors (jsdom stand-in for "no console errors").
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a real coordinator active_run → 200 → renders the stepper + narration (no crash)", async () => {
    mockFetchActive(REAL_ACTIVE_RUN);

    const activeRun = await getCoordinatorActive();
    expect(activeRun).not.toBeNull();
    expect(activeRun?.kind).toBe("coordinator");

    render(<CoordinatorPhases activeRun={activeRun} />);

    // The four phases render as a stepper.
    expect(screen.getByTestId("coordinator-stepper")).toBeInTheDocument();
    for (const phase of ["assess", "plan", "validate", "dispatch"]) {
      expect(screen.getByTestId(`phase-${phase}`)).toHaveTextContent(phase);
    }
    // current_step=dispatch → dispatch active, the three before it done.
    const dispatch = screen.getByTestId("phase-dispatch");
    expect(dispatch).toHaveAttribute("data-state", "active");
    expect(dispatch).toHaveAttribute("aria-current", "step");
    for (const prior of ["assess", "plan", "validate"]) {
      expect(screen.getByTestId(`phase-${prior}`)).toHaveAttribute(
        "data-state",
        "done",
      );
    }
    // The chosen topic surfaces via narration (the real shape carries no
    // top-level `topic` — only narration).
    const narration = screen.getByTestId("coordinator-narration");
    expect(narration).toHaveTextContent(
      "Truthfulness of VCG in combinatorial auctions",
    );
    expect(narration).toHaveTextContent("topic_source=coordinator");
    // The required run_id renders as the header chip. (run_id is typed
    // optional on CoordinatorActiveRun for forward-compat, but this fixture
    // provably sets it — assert non-null so getByText takes a Matcher.)
    expect(screen.getByText(REAL_ACTIVE_RUN.run_id!)).toBeInTheDocument();
    // Idle state is NOT shown when a cycle is live.
    expect(screen.queryByTestId("coordinator-idle")).toBeNull();

    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a real coordinator run mid-open with current_step null → no phase highlighted, no crash", async () => {
    // write_active_run opens the run BEFORE the first update_active_run sets a
    // step, so the live file can legitimately carry current_step:null (schema
    // allows ["string","null"]). The stepper must still render — every phase
    // reads "future", nothing highlighted — and must not throw.
    const opening: CoordinatorActiveRun = {
      run_id: "coordinator-2026-06-09T12:05:00",
      kind: "coordinator",
      label: "coordinator_cycle",
      started_at: "2026-06-09T12:05:00+00:00",
      current_step: null,
      narration: null,
    };
    mockFetchActive(opening);
    const activeRun = await getCoordinatorActive();

    render(<CoordinatorPhases activeRun={activeRun} />);

    expect(screen.getByTestId("coordinator-stepper")).toBeInTheDocument();
    for (const phase of ["assess", "plan", "validate", "dispatch"]) {
      expect(screen.getByTestId(`phase-${phase}`)).toHaveAttribute(
        "data-state",
        "future",
      );
    }
    // null narration → the narration block is simply omitted (no empty box).
    expect(screen.queryByTestId("coordinator-narration")).toBeNull();

    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});
