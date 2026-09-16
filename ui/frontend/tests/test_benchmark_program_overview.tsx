import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import BenchmarkProgramOverview from "../src/components/BenchmarkProgramOverview";
import type { BenchmarkProgramResponse } from "../src/types/benchmarkProgram";

function program(status: "draft" | "frozen" | "review_required"): BenchmarkProgramResponse {
  return {
    schema_version: "benchmark-program/v1",
    generated_at: "2026-09-16T04:00:00Z",
    release: { version: "1.0.0", status, expires_at: "2026-10-14T00:00:00Z", definition_sha256: "abc" },
    design: {
      capability_units_per_arm: 18,
      system_missions_per_arm: 3,
      model_calls_per_arm: 29,
      paired_model_call_cap: 58,
      categories: [{ id: "science_evidence", label: "Scientific reasoning and evidence", units: 4 }],
    },
    progress: { status: status === "frozen" ? "awaiting_baseline" : status, completed_units: 0, total_units: 21, blockers: [], next_action: "Run the registered panel." },
    comparison: { status: "not_started", baseline: null, arms: [], matched_results: [] },
    layers: { model: { status: "not_started", summary: "Prospective only." } },
    warnings: [],
  };
}

describe("BenchmarkProgramOverview", () => {
  it("shows the narrow fixed canary design and withholds a missing baseline", () => {
    render(<BenchmarkProgramOverview initial={program("frozen")} />);
    expect(screen.getByRole("heading", { name: "Fixed regression canary" })).toBeInTheDocument();
    expect(screen.getByText("frozen")).toBeInTheDocument();
    expect(screen.getByText("18")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("29 / arm")).toBeInTheDocument();
    expect(screen.getByText(/58 paired calls maximum/)).toBeInTheDocument();
    expect(screen.getByText(/0 of 21 registered units/)).toBeInTheDocument();
    expect(screen.getByText(/Baseline not established/)).toBeInTheDocument();
    expect(screen.queryByText(/trend improved|upgrade established/i)).toBeNull();
  });

  it.each([
    ["draft", /remains a draft/i],
    ["frozen", /public definition is frozen/i],
    ["review_required", /reached its review date/i],
  ] as const)("renders the %s release truth explicitly", (status, expected) => {
    render(<BenchmarkProgramOverview initial={program(status)} />);
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it("fails closed when the API withholds an invalid definition", () => {
    render(<BenchmarkProgramOverview initial={{
      ...program("draft"),
      release: null,
      design: null,
      comparison: { status: "withheld_invalid_definition", baseline: null, history: [] },
      warnings: ["Benchmark definition is unavailable or invalid; scores are withheld."],
    }} />);
    expect(screen.getByRole("heading", { name: /definition unavailable/i })).toBeInTheDocument();
    expect(screen.getByText(/scores, run readiness, and comparisons are withheld/i)).toBeInTheDocument();
    expect(screen.queryByText("29 / arm")).toBeNull();
  });

  it("shows the source-reported in-flight lifecycle phase", () => {
    const running = program("frozen");
    running.progress = {
      ...running.progress,
      status: "running",
      phase: "evaluation",
      run_id: "stable-benchmark-20260916-a.resident",
    };
    render(<BenchmarkProgramOverview initial={running} />);
    expect(screen.getByTestId("benchmark-program-phase")).toHaveTextContent(
      "Phase: evaluation · stable-benchmark-20260916-a.resident",
    );
  });

  it("renders numeric matched canary evidence with uncertainty and run provenance", () => {
    const admitted = program("frozen");
    admitted.comparison = {
      status: "recorded",
      baseline: { arm_id: "base" },
      arms: [{ id: "base", label: "Baseline", profile: "qwen", total_wall_seconds: 91.2, week: "2026-W38" }],
      matched_results: [{
        id: "science",
        domain: "science",
        metric: "objective_success",
        unit: "percent",
        baseline_value: 50,
        candidate_value: 75,
        delta: 25,
        n_pairs: 4,
        discordant_counts: { baseline_wins: 0, candidate_wins: 1, ties: 3 },
        uncertainty: { method: "paired_cluster_bootstrap", lower: null, upper: null },
        week: "2026-W38",
        date: "2026-09-16",
        profile: "fixed-v1",
      }],
      history: [{
        comparison_id: "canary-2026-w38",
        arm_id: "resident",
        label: "Resident reference",
        admission_status: "admitted",
        observed_terminal_status: "complete",
        results: [{
          construct: "quantitative_inference",
          domain: "science_evidence",
          panel: "model_capability",
          successful_units: 1,
          planned_units: 2,
          metric: "objective_success",
          unit: "percent",
          value: 50,
        }],
        started_at: "2026-09-16T04:00:00Z",
        finished_at: "2026-09-16T04:08:00Z",
        week: "2026-W38",
        wall_seconds: 91.2,
        model_calls: 21,
        policy: {
          role_map: { actor: "primary" },
          routes: { primary: { model: "resident-gemma", profile: "fixed-v1", expected_policy: { temperature: 0.2, top_p: 0.95, reasoning_effort: "xhigh" } } },
        },
      }, {
        comparison_id: "canary-2026-w38",
        arm_id: "flash",
        label: "Flash candidate",
        admission_status: "not_evaluated",
        observed_terminal_status: "unissued",
        results: [],
        started_at: null,
        finished_at: null,
        week: null,
        wall_seconds: null,
        model_calls: null,
        policy: null,
      }],
    };
    render(<BenchmarkProgramOverview initial={admitted} />);
    const table = screen.getByTestId("benchmark-matched-results");
    expect(within(table).getByText("50.0%")).toBeInTheDocument();
    expect(within(table).getByText("75.0%")).toBeInTheDocument();
    expect(within(table).getByText("+25.0 pp")).toBeInTheDocument();
    expect(within(table).getByText(/candidate wins 1/)).toBeInTheDocument();
    expect(within(table).getByText(/interval not available/)).toBeInTheDocument();
    expect(screen.getByText(/descriptive canary signals, not benchmark proof/i)).toBeInTheDocument();
    const history = screen.getByTestId("benchmark-run-history");
    expect(within(history).getByText("Resident reference")).toBeInTheDocument();
    expect(within(history).getByText("quantitative inference")).toBeInTheDocument();
    expect(within(history).getByText("50.0%")).toBeInTheDocument();
    expect(within(history).getByText("91.2 s evaluation wall")).toBeInTheDocument();
    expect(within(history).getByText(/temperature 0.2 · top-p 0.95 · reasoning xhigh/)).toBeInTheDocument();
    expect(within(history).getByText("Flash candidate")).toBeInTheDocument();
    expect(within(history).getByText(/explicitly unissued/)).toBeInTheDocument();
    expect(screen.getByText(/does not compute an across-construct score/i)).toBeInTheDocument();
  });
});
