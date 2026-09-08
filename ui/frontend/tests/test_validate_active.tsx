// REAL-DATA validation for the coordinator "active phases" surface
// (CoordinatorPhases — fed post-S3 from the D-047 registry: the /cycles page
// polls getActiveRuns() and hands the kind==="coordinator" doc down; the old
// /api/coordinator/active mirror + getCoordinatorActive() died in S3). The
// companion test_coordinator_phases.tsx covers the component against the
// fixture; THIS file validates the end-to-end render path against the shapes
// the LIVE backend actually returns:
//
//   (a) no live coordinator run → GET /api/activity/active_runs returns
//       {runs: []} (or runs of other kinds only) → the page derives null →
//       CoordinatorPhases renders the QUIET IDLE state (data-testid
//       coordinator-idle), never a blank gap or a crash.
//   (b) a real coordinator cycle is in flight → the registry serves the
//       active-run doc the producer writes (orchestrator/active_run.py +
//       schema/active_run.schema.json) → CoordinatorPhases renders the
//       assess→plan→validate→dispatch stepper with the chosen-topic narration.
//
// We drive getActiveRuns() itself (not a hand-built prop) so the registry
// contract is exercised, mocking fetch the way the panel suites do. Each case
// also asserts a clean render: no console.error / console.warn.
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CoordinatorPhases from "../src/components/CoordinatorPhases";
import { getActiveRuns } from "../src/api/http";
import type { ActiveRun } from "../src/types/activity";
import type { CoordinatorActiveRun } from "../src/types/schemas";

// A real coordinator active-run doc, shaped from orchestrator/active_run.py's
// write_active_run/update_active_run + schema/active_run.schema.json (NOT the
// test fixture): required {run_id, kind, label, started_at}, plus current_step
// / step_started_at / narration from update_active_run. `n_err` is a
// schema-allowed (additionalProperties:true) field the component never reads —
// included to prove real rows with extra keys render fine. There is NO
// top-level `topic` field — the chosen topic lives in narration (per the EMIT
// reconciliation in ui_plan.md §AUTONOMY OBSERVABILITY).
const REAL_ACTIVE_RUN: ActiveRun = {
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

function mockRegistry(runs: ActiveRun[]): void {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    status: 200,
    ok: true,
    json: async () => ({ runs, skipped: 0 }),
  } as Response);
}

// The /cycles page's derivation, verbatim: the registry doc whose kind is
// "coordinator", else null (idle).
function coordinatorRunOf(runs: ActiveRun[]): CoordinatorActiveRun | null {
  return (
    (runs.find((r) => r != null && r.kind === "coordinator") as
      | CoordinatorActiveRun
      | undefined) ?? null
  );
}

describe("CoordinatorPhases — validated against live registry shapes", () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("empty registry (plus non-coordinator runs) → null → quiet idle (no crash)", async () => {
    // A live experiment run in the registry is NOT a coordinator cycle — the
    // phases panel must still read idle.
    mockRegistry([
      {
        run_id: "exp-2026-06-09-001",
        kind: "experiment",
        label: "exp003 probe",
        started_at: "2026-06-09T11:00:00+00:00",
      },
    ]);

    const body = await getActiveRuns();
    const activeRun = coordinatorRunOf(body.runs);
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

  it("a real coordinator doc in the registry → renders the stepper + narration (no crash)", async () => {
    mockRegistry([REAL_ACTIVE_RUN]);

    const body = await getActiveRuns();
    const activeRun = coordinatorRunOf(body.runs);
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
    // The required run_id renders as the header chip.
    expect(screen.getByText(REAL_ACTIVE_RUN.run_id)).toBeInTheDocument();
    // Idle state is NOT shown when a cycle is live.
    expect(screen.queryByTestId("coordinator-idle")).toBeNull();

    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a real coordinator run mid-open with current_step null → no phase highlighted, no crash", async () => {
    // write_active_run opens the run BEFORE the first update_active_run sets a
    // step, so the live doc can legitimately carry current_step:null (schema
    // allows ["string","null"]). The stepper must still render — every phase
    // reads "future", nothing highlighted — and must not throw.
    const opening: ActiveRun = {
      run_id: "coordinator-2026-06-09T12:05:00",
      kind: "coordinator",
      label: "coordinator_cycle",
      started_at: "2026-06-09T12:05:00+00:00",
      current_step: null,
      narration: null,
    };
    mockRegistry([opening]);
    const body = await getActiveRuns();
    const activeRun = coordinatorRunOf(body.runs);

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
