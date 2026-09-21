import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import BenchmarkProgramOverview from "../src/components/BenchmarkProgramOverview";
import { getBenchmarkProgram } from "../src/api/benchmarkProgram";
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
  afterEach(() => vi.unstubAllGlobals());

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
        role: "reference",
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
    const reference = screen.getByTestId("benchmark-reference-results");
    expect(within(reference).getByText("Quantitative inference")).toBeInTheDocument();
    expect(within(reference).getByText("1 / 2")).toBeInTheDocument();
    expect(within(reference.closest("section") as HTMLElement).getByText(/1 registered route/)).toBeInTheDocument();
    const history = screen.getByTestId("benchmark-run-history");
    expect(within(history).getByText("Resident reference")).toBeInTheDocument();
    expect(within(history).getByText("Quantitative inference")).toBeInTheDocument();
    expect(within(history).getByText("50.0%")).toBeInTheDocument();
    expect(within(history).getByText("91.2 s evaluation wall")).toBeInTheDocument();
    expect(within(history).getByText(/temperature 0.2 · top-p 0.95 · reasoning xhigh/)).toBeInTheDocument();
    expect(within(history).getByText("Flash candidate")).toBeInTheDocument();
    expect(within(history).getByText(/explicitly unissued/)).toBeInTheDocument();
    expect(screen.getByText(/does not compute an across-construct score/i)).toBeInTheDocument();
  });

  it("labels a reviewed baseline as diagnostics and withholds comparative quality", () => {
    const reviewed = program("frozen");
    const reference = {
      comparison_id: "canary-reviewed",
      arm_id: "resident",
      label: "Resident commissioning run",
      role: "reference",
      admission_status: "admitted",
      observed_terminal_status: "complete",
      results: [{
        construct: "science_evidence",
        domain: "science_evidence",
        panel: "model_capability",
        successful_units: 2,
        planned_units: 4,
        metric: "objective_success",
        unit: "percent",
        value: 50,
      }],
      wall_seconds: 120,
      model_calls: 21,
    };
    reviewed.measurement_review = {
      status: "commissioning_only",
      title: "Commissioning measurement review",
      summary: "Four task contracts limit quality interpretation.",
      interpretation: "Keep receipt evidence, but do not compare model quality.",
      next_action: "Publish a corrected prospective release.",
      affected_task_ids: ["SCI-RCT-001", "TOOL-NOCALL-001"],
      comparative_quality_allowed: false,
      source_path: "docs/benchmarks/measurement_reviews/review.json",
      reviewed_at: "2026-09-16T06:00:00Z",
    };
    reviewed.comparison = {
      status: "measurement_review_required",
      baseline: reference,
      history: [reference],
      matched_results: [{ construct: "science_evidence", baseline_value: 50, candidate_value: 75 }],
    };

    render(<BenchmarkProgramOverview initial={reviewed} />);

    expect(screen.getByTestId("benchmark-measurement-review")).toHaveTextContent(
      "Four task contracts limit quality interpretation.",
    );
    expect(screen.getByTestId("benchmark-reference-results")).toHaveTextContent(
      "Recorded diagnostic",
    );
    expect(screen.getByText(/does not admit them as trusted quality scores/i)).toBeInTheDocument();
    expect(screen.queryByTestId("benchmark-matched-results")).toBeNull();
    expect(screen.getByText(/Matched quality changes are withheld/i)).toBeInTheDocument();
  });

  it("does not promote an admitted candidate when the reference is still absent", () => {
    const candidateFirst = program("frozen");
    candidateFirst.comparison = {
      status: "awaiting_reference",
      baseline: null,
      history: [{
        comparison_id: "canary-candidate-first",
        arm_id: "candidate",
        label: "Candidate completed first",
        role: "candidate",
        admission_status: "admitted",
        observed_terminal_status: "complete",
        results: [{
          construct: "science_evidence",
          domain: "science_evidence",
          panel: "model_capability",
          successful_units: 4,
          planned_units: 4,
          metric: "objective_success",
          unit: "percent",
          value: 100,
        }],
      }],
      matched_results: [],
    };

    render(<BenchmarkProgramOverview initial={candidateFirst} />);

    expect(screen.getByRole("heading", { name: "Baseline not established" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Candidate completed first" })).toBeNull();
    expect(screen.queryByTestId("benchmark-reference-results")).toBeNull();
    expect(screen.getByText(/No baseline is admitted/)).toBeInTheDocument();
  });

  it("explains terminal 21-of-42 coverage as a complete reference and unissued candidate", () => {
    const terminal = program("frozen");
    const reference = {
      comparison_id: "canary-terminal",
      arm_id: "resident",
      label: "Resident reference",
      role: "reference",
      admission_status: "admitted",
      observed_terminal_status: "complete",
      completed_units: 21,
      model_calls: 28,
      results: [{ construct: "science_evidence", domain: "science_evidence",
        panel: "model_capability", successful_units: 4, planned_units: 4,
        metric: "objective_success", unit: "percent", value: 100 }],
    };
    const candidate = {
      comparison_id: "canary-terminal",
      arm_id: "flash-unissued",
      label: "Flash candidate — unissued",
      role: "candidate",
      admission_status: "not_evaluated",
      observed_terminal_status: "unissued",
      completed_units: 0,
      model_calls: 0,
      results: [],
    };
    terminal.progress = { status: "partial", comparison_id: "canary-terminal",
      completed_units: 21, total_units: 42,
      completed_calls: 28, total_calls: 58, blockers: [], next_action: "Inspect the unissued arm." };
    terminal.comparison = { status: "baseline_available", baseline: reference,
      arms: [reference, candidate], history: [reference, candidate], matched_results: [] };

    const rendered = render(<BenchmarkProgramOverview initial={terminal} />);

    expect(screen.getByText("Reference complete")).toBeInTheDocument();
    expect(screen.getByText("Cohort partial · candidate unissued")).toBeInTheDocument();
    expect(screen.getByText("Reference 21/21 complete · candidate 0/21 unissued · 28 / 58 calls")).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Stable benchmark registered units completed" })).toHaveAttribute(
      "aria-valuetext", "Reference 21 of 21 complete; candidate 0 of 21 unissued",
    );
    expect(screen.getAllByText(/This arm was explicitly unissued/)).toHaveLength(2);

    rendered.unmount();
    terminal.progress = { ...terminal.progress, phase: "evaluation",
      run_id: "stable-benchmark-current.resident" };
    render(<BenchmarkProgramOverview initial={terminal} />);
    expect(screen.getByText("partial")).toBeInTheDocument();
    expect(screen.queryByText("Reference complete")).toBeNull();
    expect(screen.getByTestId("benchmark-program-phase")).toHaveTextContent("Phase: evaluation");
  });

  it("does not borrow an old unissued arm when the current cohort candidate is pending", () => {
    const twoCohorts = program("frozen");
    const result = { construct: "science_evidence", domain: "science_evidence",
      panel: "model_capability", successful_units: 4, planned_units: 4,
      metric: "objective_success", unit: "percent", value: 100 };
    const oldReference = { comparison_id: "canary-old", arm_id: "resident-old",
      label: "Old resident reference", role: "reference", admission_status: "admitted",
      observed_terminal_status: "complete", completed_units: 21, model_calls: 28,
      results: [result] };
    const oldCandidate = { comparison_id: "canary-old", arm_id: "flash-old",
      label: "Old Flash candidate", role: "candidate", admission_status: "not_evaluated",
      observed_terminal_status: "unissued", completed_units: 0, model_calls: 0, results: [] };
    const currentReference = { ...oldReference, comparison_id: "canary-current",
      arm_id: "resident-current", label: "Current resident reference" };
    const currentCandidate = { comparison_id: "canary-current", arm_id: "flash-current",
      label: "Current Flash candidate", role: "candidate", admission_status: "awaiting_artifacts",
      observed_terminal_status: "pending", completed_units: 0, model_calls: null, results: [] };
    twoCohorts.progress = { status: "partial", comparison_id: "canary-current",
      completed_units: 21, total_units: 42, completed_calls: null, total_calls: 58,
      blockers: [], next_action: "Wait for the current candidate." };
    twoCohorts.comparison = { status: "baseline_available", baseline: oldReference,
      arms: [oldReference, oldCandidate, currentReference, currentCandidate],
      history: [oldReference, oldCandidate, currentReference, currentCandidate], matched_results: [] };

    render(<BenchmarkProgramOverview initial={twoCohorts} />);

    expect(screen.getByText("partial")).toBeInTheDocument();
    expect(screen.getByText("21 of 42 registered units")).toBeInTheDocument();
    expect(screen.queryByText("Reference complete")).toBeNull();
    expect(screen.queryByText("Cohort partial · candidate unissued")).toBeNull();
    expect(screen.getByRole("meter", { name: "Stable benchmark registered units completed" }))
      .not.toHaveAttribute("aria-valuetext");
  });

  it("uses human construct labels in the fixed product order while retaining raw keys", () => {
    const labeled = program("frozen");
    const keys = ["cournot", "deterministic_tool_use", "functional_code_repair",
      "proper_scoring_reporting", "public_goods", "science_evidence", "system_harness",
      "vickrey_auction"];
    const reference = {
      comparison_id: "canary-labels", arm_id: "resident", label: "Resident reference",
      role: "reference", admission_status: "admitted", observed_terminal_status: "complete",
      results: keys.map((construct) => ({ construct, domain: "model_capability",
        panel: "model_capability", successful_units: 1, planned_units: 1,
        metric: "objective_success", unit: "percent", value: 100 })),
    };
    labeled.comparison = { status: "baseline_available", baseline: reference,
      history: [reference], matched_results: [] };

    render(<BenchmarkProgramOverview initial={labeled} />);

    const table = screen.getByTestId("benchmark-reference-results");
    expect(within(table).getAllByRole("rowheader").map((cell) => cell.textContent)).toEqual([
      "Evidence and quantitative reasoning",
      "Functional code repair",
      "Deterministic tool use",
      "Public goods provision",
      "Vickrey auction",
      "Cournot quantity choice",
      "Brier score and truthful reporting",
      "Harness workflows",
    ]);
    expect(within(table).getByText("Cournot quantity choice")).toHaveAttribute(
      "title", "Construct key: cournot",
    );
  });

  it("shows a compact selector only when the catalog has multiple releases", () => {
    const catalogued = program("frozen");
    catalogued.available_releases = [
      { version: "1.0.0", label: "Commissioning archive", active: false, selected: true, href: "/benchmarks?release=1.0.0" },
      { version: "1.1.0", label: "Corrected active release", active: true, selected: false, href: "/benchmarks?release=1.1.0" },
    ];
    render(<BenchmarkProgramOverview initial={catalogued} release="1.0.0" />);
    const selector = screen.getByRole("navigation", { name: "Benchmark release" });
    expect(within(selector).getByRole("link", { name: /v1.0.0/ })).toHaveAttribute("aria-current", "page");
    expect(within(selector).getByRole("link", { name: /v1.1.0 · active/ })).toHaveAttribute("href", "/benchmarks?release=1.1.0");
  });

  it("separates the verified current resident from the unchanged frozen reference", () => {
    const current = program("frozen");
    current.release = { ...current.release, version: "1.1.0" };
    current.comparison = {
      status: "baseline_available",
      baseline: null,
      arms: [],
      history: [{
        comparison_id: "stable-v1-1",
        arm_id: "resident-stack",
        label: "Gemma precise actor + Qwen xhigh critic",
        role: "reference",
        admission_status: "admitted",
        observed_terminal_status: "complete",
        results: [{ construct: "science_evidence", domain: "science_evidence", panel: "model_capability", successful_units: 1, planned_units: 1, metric: "objective_success", unit: "percent", value: 100 }],
        policy: { routes: { gemma: { model: "gemma-4-26b-a4b" }, qwen: { model: "qwen3.8-27b-nvfp4-mtp" } } },
      }],
      matched_results: [],
    };
    render(<BenchmarkProgramOverview initial={current} initialServedModels={{
      flash: {
        url: "http://127.0.0.1:30080/v1",
        model: "nvidia/Qwen3.8-Flash-Next-NVFP4",
        error: null,
        probed_at: new Date().toISOString(),
        configured_model: "nvidia/Qwen3.8-Flash-Next-NVFP4",
        deployment_role: "production_resident",
        promotion_authorized: true,
        models_endpoint_status: "available",
        service_status: "online",
        identity_status: "match",
      },
    }} />);

    const banner = screen.getByTestId("benchmark-current-resident");
    expect(banner).toHaveTextContent("nvidia/Qwen3.8-Flash-Next-NVFP4");
    expect(banner).toHaveTextContent("verified online production resident");
    expect(banner).toHaveTextContent("not yet admitted on v1.1");
    expect(banner).toHaveTextContent("separate from the frozen historical reference");
    expect(screen.getByRole("heading", { name: "Gemma precise actor + Qwen xhigh critic" })).toBeInTheDocument();
  });

  it("withholds the current-serving banner when live identity does not verify", () => {
    const current = program("frozen");
    current.release = { ...current.release, version: "1.1.0" };
    render(<BenchmarkProgramOverview initial={current} initialServedModels={{
      flash: {
        url: "http://127.0.0.1:30080/v1",
        model: "different-model",
        error: null,
        probed_at: new Date().toISOString(),
        configured_model: "nvidia/Qwen3.8-Flash-Next-NVFP4",
        deployment_role: "production_resident",
        promotion_authorized: true,
        models_endpoint_status: "available",
        service_status: "online",
        identity_status: "mismatch",
      },
    }} />);
    expect(screen.queryByTestId("benchmark-current-resident")).toBeNull();
  });

  it("does not call retained serving data current after the inventory refresh fails", () => {
    const current = program("frozen");
    current.release = { ...current.release, version: "1.1.0" };
    render(<BenchmarkProgramOverview
      initial={current}
      initialServedModelsRefreshFailed
      initialServedModels={{
        flash: {
          url: "http://127.0.0.1:30080/v1",
          model: "nvidia/Qwen3.8-Flash-Next-NVFP4",
          error: null,
          probed_at: new Date().toISOString(),
          configured_model: "nvidia/Qwen3.8-Flash-Next-NVFP4",
          deployment_role: "production_resident",
          promotion_authorized: true,
          models_endpoint_status: "available",
          service_status: "online",
          identity_status: "match",
        },
      }}
    />);

    expect(screen.queryByTestId("benchmark-current-resident")).toBeNull();
    expect(screen.getByTestId("benchmark-current-resident-unavailable")).toHaveTextContent(
      "retained payload is not presented as current online evidence",
    );
  });

  it("does not call an old endpoint probe current after its freshness window", () => {
    const current = program("frozen");
    current.release = { ...current.release, version: "1.1.0" };
    render(<BenchmarkProgramOverview initial={current} initialServedModels={{
      flash: {
        url: "http://127.0.0.1:30080/v1",
        model: "nvidia/Qwen3.8-Flash-Next-NVFP4",
        error: null,
        probed_at: new Date(Date.now() - 90_001).toISOString(),
        configured_model: "nvidia/Qwen3.8-Flash-Next-NVFP4",
        deployment_role: "production_resident",
        promotion_authorized: true,
        models_endpoint_status: "available",
        service_status: "online",
        identity_status: "match",
      },
    }} />);

    expect(screen.queryByTestId("benchmark-current-resident")).toBeNull();
    expect(screen.getByTestId("benchmark-current-resident-unavailable")).toHaveTextContent(
      "does not have a fresh, identity-matched endpoint probe",
    );
  });

  it("requests an exact release and rejects a mismatched response without fallback", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(program("frozen")), {
      status: 200,
      headers: { "content-type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getBenchmarkProgram("1.1.0")).rejects.toThrow(
      /requested 1.1.0, received 1.0.0/,
    );
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "/api/benchmark_program?release=1.1.0",
    );
  });
});
