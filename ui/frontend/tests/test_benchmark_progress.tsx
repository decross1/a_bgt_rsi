import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import BenchmarkProgress from "../src/routes/BenchmarkProgress";
import type { BenchmarkProgressResponse } from "../src/types/benchmarkProgress";

const emptyMetrics = {
  success_rate: null, ctt_per_hour: null, rsr_2of3: null,
  recorded_wall_seconds: null, mean_recorded_seconds_per_transport_attempt: null,
  repair_rate: null, protocol_valid_rate: null, annotation_disagreements: null,
};

const fixture: BenchmarkProgressResponse = {
  schema_version: "weekly-upgrade-progress/v1",
  generated_at: "2026-09-14T12:00:00Z",
  current_week: "2026-W38",
  availability: { trials: true, evaluations: true, budget: true, completion: true, activation: true, reviews: true },
  automation: { mode: "review_only", status: "active", activated_at: "2026-09-14T10:30:00Z", schedule: "Sunday 05:30 UTC", promotion_enabled: false },
  summary: {
    weeks_seen: 1, latest_week: "2026-W38", terminal_trials: 8,
    recorded_evaluations: 8, complete_executions: 5, comparable_transitions: 0,
    upgrade_established: false,
    headline: "Baseline recorded; no performance upgrade established",
    current_week_budget: { limit_minutes: 120, charged_minutes: 57.58828, trial_charge_minutes: 54.58828, prior_import_minutes: 3, remaining_minutes: 62.41172, active_reservations: 0, accounting_note: "Includes a conservative prior-use debit." },
  },
  warnings: [{ code: "prior_import", scope: "Budget", detail: "Charged allowance includes a conservative prior-usage debit." }],
  weeks: [{
    week: "2026-W38", status: "measured", terminal_trials: 8, recorded_evaluations: 8, complete_executions: 5,
    review: { status: "review_complete", decision: "revision_required", experiment_proposals: 1, source_count: 8, frontier_calls: 2 },
    budget: { limit_minutes: 120, charged_minutes: 57.58828, trial_charge_minutes: 54.58828, prior_import_minutes: 3, remaining_minutes: 62.41172, active_reservations: 0, accounting_note: "Includes a conservative prior-use debit." },
    families: [
      {
        id: "qwen_reasoning_effort", label: "Qwen reasoning effort", kind: "policy",
        status: "incomplete", execution_status: "incomplete_transport", evaluation_status: "partial",
        semantic_verdict: "candidate_benefit_not_verified",
        evidence: { class: "UNVERIFIED_OPERATOR_SUMMARY", candidate_benefit_verified: false },
        completeness: { expected: 36, returned: 35, protocol_valid: 35, timeouts: 1 },
        comparison: {
          eligible: false, explanation: "Insufficient comparable history", history_points: 1,
          fingerprint: "cohort-qwen-v1", basis: ["suite", "fixtures", "grader", "budgets"], break_reasons: [],
          points: [{ week: "2026-W38", status: "incomplete", baseline: { arm_id: "xhigh", success_rate: 13 / 18, successes: 13, success_denominator: 18 }, candidate: { arm_id: "medium", success_rate: 12 / 18, successes: 12, success_denominator: 18 }, delta_success_rate: -1 / 18, trial_count: 3 }],
        },
        arms: [
          { id: "xhigh", label: "Current xhigh", configuration: "temperature .2 · top-p .95 · xhigh", transport_expected: 18, transport_returned: 17, objective_successes: 13, objective_total: 18, repair_successes: null, repair_total: null, timeouts: 1, metrics: { ...emptyMetrics, success_rate: 13 / 18, ctt_per_hour: 39.460417, rsr_2of3: 4 / 6, recorded_wall_seconds: 1185.998631, mean_recorded_seconds_per_transport_attempt: 65.888813 } },
          { id: "medium", label: "Candidate medium", configuration: "temperature .2 · top-p .95 · medium", transport_expected: 18, transport_returned: 18, objective_successes: 12, objective_total: 18, repair_successes: null, repair_total: null, timeouts: 0, metrics: { ...emptyMetrics, success_rate: 12 / 18, ctt_per_hour: 67.147185, rsr_2of3: 5 / 6, recorded_wall_seconds: 643.36279, mean_recorded_seconds_per_transport_attempt: 35.742377 } },
        ],
        uncertainty: { kind: "none", metric: null, low: null, high: null, n: 3 },
        provenance: { trial_ids: ["2026-W38-qwen"], manifest_sha256: ["a".repeat(64)], run_sha256: ["b".repeat(64)], evaluation_sha256: ["c".repeat(64)], summary_sha256: ["d".repeat(64)], source_commits: ["9e27b38"] },
        details: { note: "One timeout makes the pair incomplete.", fixture_count: 6, repeat_count: 3, grader_bound: true },
      },
      {
        id: "context", label: "Resident context capability", kind: "context",
        interpretation_note: "Arms differ in model, maximum-context lane, and reasoning mode; scores and timing are descriptive, not causal.",
        status: "complete", execution_status: "complete", evaluation_status: "recorded",
        semantic_verdict: "candidate_benefit_not_verified",
        evidence: { class: "UNVERIFIED_OPERATOR_SUMMARY", candidate_benefit_verified: false },
        completeness: { expected: 8, returned: 8, protocol_valid: 7, timeouts: 0 },
        comparison: {
          eligible: false, explanation: "Only one week is recorded", history_points: 1,
          fingerprint: "cohort-context-v1", basis: ["suite", "fixtures"], break_reasons: [],
          points: [{ week: "2026-W38", status: "complete", baseline: { arm_id: "gemma", success_rate: 1, successes: 4, success_denominator: 4 }, candidate: { arm_id: "qwen", success_rate: .75, successes: 3, success_denominator: 4 }, delta_success_rate: -.25, trial_count: 1 }],
        },
        arms: [{ id: "gemma", label: "Gemma", configuration: null, transport_expected: 4, transport_returned: 4, objective_successes: 4, objective_total: 4, repair_successes: null, repair_total: null, timeouts: 0, metrics: { ...emptyMetrics, success_rate: 1 } }],
        uncertainty: { kind: "bootstrap_95", metric: "failure_inclusive_delta_candidate_minus_baseline", low: -.75, high: 0, n: 4 },
        provenance: { trial_ids: ["2026-W38-context"], manifest_sha256: [], run_sha256: [], evaluation_sha256: [], summary_sha256: [], source_commits: [] },
        details: { note: null, fixture_count: 4, repeat_count: 1, grader_bound: true },
      },
    ],
  }],
};

afterEach(cleanup);

function renderPage(data: BenchmarkProgressResponse | null = fixture) {
  return render(<MemoryRouter><BenchmarkProgress initial={data} /></MemoryRouter>);
}

describe("Benchmark Progress", () => {
  it("states the baseline without inventing a week-over-week gain", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Benchmark Progress" })).toBeInTheDocument();
    expect(screen.getByText("baseline recorded", { selector: ".benchmark-chip" })).toBeInTheDocument();
    expect(screen.getByText(/No upgrade has been established/)).toBeInTheDocument();
    expect(screen.getByText("0", { selector: ".benchmark-summary-grid dd" })).toBeInTheDocument();
    expect(screen.getAllByText("Baseline only")).toHaveLength(2);
    expect(screen.queryByText("Candidate delta")).not.toBeInTheDocument();
  });

  it("separates review, evaluation receipts and complete execution", () => {
    renderPage();
    const split = document.querySelector(".benchmark-review-measurement") as HTMLElement;
    expect(within(split).getByText("Frontier review")).toBeInTheDocument();
    expect(within(split).getByText("Recorded evaluation")).toBeInTheDocument();
    expect(within(split).getByText("8 summaries · 5 complete executions")).toBeInTheDocument();
    expect(within(split).getByText(/1 experiment proposal/)).toBeInTheDocument();
  });

  it("discloses allowance accounting instead of calling it measured GPU runtime", () => {
    renderPage();
    expect(screen.getByText("Weekly Spark allowance")).toBeInTheDocument();
    expect(screen.getByText(/Includes 3.0 min prior-use debit/)).toBeInTheDocument();
    expect(screen.queryByText(/GPU budget|GPU-min/i)).not.toBeInTheDocument();
  });

  it("bounds the allowance meter while disclosing an overrun", () => {
    const budget = { ...fixture.summary.current_week_budget!, charged_minutes: 125, remaining_minutes: -5 };
    renderPage({ ...fixture, summary: { ...fixture.summary, current_week_budget: budget } });
    const meter = screen.getByRole("meter", { name: "Weekly Spark allowance charged" });
    expect(meter).toHaveAttribute("aria-valuemax", "120");
    expect(meter).toHaveAttribute("aria-valuenow", "120");
    expect(screen.getByText(/5.0 min over allowance/)).toBeInTheDocument();
  });

  it("shows denominators, missing values, configurations and expanded provenance", () => {
    renderPage();
    const family = screen.getByTestId("benchmark-family-qwen_reasoning_effort");
    expect(within(family).getByText(/13/)).toBeInTheDocument();
    expect(within(family).getAllByText("objective tasks")).toHaveLength(2);
    expect(within(family).getAllByText("returned / expected")).toHaveLength(2);
    expect(within(family).getAllByText(/temperature .2/)).toHaveLength(2);
    expect(within(screen.getByTestId("benchmark-family-context")).getAllByText("Not measured").length).toBeGreaterThan(0);
    fireEvent.click(within(family).getByText("Evidence, uncertainty and provenance"));
    expect(within(family).getByText("a".repeat(64))).toBeInTheDocument();
    expect(within(family).getByText(/No confidence band is inferred/)).toBeInTheDocument();
    expect(within(family).getByText("unverified operator summary")).toBeInTheDocument();
    const context = screen.getByTestId("benchmark-family-context");
    expect(within(context).getByText("Interpretation limit")).toBeInTheDocument();
    expect(within(context).getByText(/descriptive, not causal/)).toBeInTheDocument();
    fireEvent.click(within(context).getByText("Evidence, uncertainty and provenance"));
    expect(within(context).getByText(/-75 pp to 0 pp/)).toBeInTheDocument();
  });

  it("filters families by text and incomplete status", () => {
    renderPage();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search" }), { target: { value: "context" } });
    expect(screen.getByTestId("benchmark-family-context")).toBeInTheDocument();
    expect(screen.queryByTestId("benchmark-family-qwen_reasoning_effort")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search" }), { target: { value: "" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Show" }), { target: { value: "incomplete" } });
    expect(screen.getByTestId("benchmark-family-qwen_reasoning_effort")).toBeInTheDocument();
    expect(screen.queryByTestId("benchmark-family-context")).not.toBeInTheDocument();
  });

  it("does not render deltas from an ineligible two-point series", () => {
    const twoPoints = [...fixture.weeks[0].families[0].comparison.points, { ...fixture.weeks[0].families[0].comparison.points[0], week: "2026-W39" }];
    const changed = { ...fixture, weeks: [{ ...fixture.weeks[0], families: [{ ...fixture.weeks[0].families[0], comparison: { ...fixture.weeks[0].families[0].comparison, history_points: 2, points: twoPoints, eligible: false, explanation: "Cohort fingerprint changed", break_reasons: ["fixture set changed"] } }] }] };
    renderPage(changed);
    expect(screen.getByText("Not comparable")).toBeInTheDocument();
    expect(screen.queryByText("Candidate delta")).not.toBeInTheDocument();
  });

  it("keeps objective-task denominators separate from transport calls", () => {
    const base = fixture.weeks[0].families[0];
    const diversity = {
      ...base,
      id: "diversity_selection",
      label: "Diversity and selection",
      arms: [{
        ...base.arms[0], id: "diverse", label: "Diverse candidate",
        transport_expected: 20, transport_returned: 20,
        objective_successes: 0, objective_total: 5,
        metrics: { ...base.arms[0].metrics, success_rate: 0 },
      }],
    };
    renderPage({ ...fixture, weeks: [{ ...fixture.weeks[0], families: [diversity] }] });
    const family = screen.getByTestId("benchmark-family-diversity_selection");
    expect(within(family).getByText("0 / 5")).toBeInTheDocument();
    expect(within(family).getByText("20 / 20")).toBeInTheDocument();
    expect(within(family).getByText("0%")).toBeInTheDocument();
  });

  it("links capability tracking to the separate thesis evidence page", () => {
    renderPage();
    expect(screen.getByRole("link", { name: /Open Research for thesis evidence/ })).toHaveAttribute("href", "/ladder");
    expect(screen.getByText(/does not automatically rerun benchmark panels/)).toBeInTheDocument();
  });

  it("renders honest empty and malformed-source states", () => {
    const first = renderPage(null);
    expect(screen.getByText("Unable to load benchmark history")).toBeInTheDocument();
    expect(screen.queryByText(/0 measured/)).not.toBeInTheDocument();
    first.unmount();
    renderPage({ schema_version: "weekly-upgrade-progress/v1", generated_at: "bad", current_week: "", weeks: [] } as unknown as BenchmarkProgressResponse);
    expect(screen.getByText(/response shape is incomplete/)).toBeInTheDocument();
    expect(screen.getByText("No measured weeks yet")).toBeInTheDocument();
    expect(screen.getByText(/Missing history is not a zero score/)).toBeInTheDocument();
  });

  it("marks counters and history unavailable when benchmark sources are unavailable", () => {
    renderPage({
      ...fixture,
      availability: { trials: false, evaluations: false, budget: false, completion: false, activation: false, reviews: false },
      summary: {
        ...fixture.summary,
        weeks_seen: 0,
        latest_week: null,
        terminal_trials: 0,
        recorded_evaluations: 0,
        complete_executions: 0,
        current_week_budget: null,
      },
      weeks: [],
    });
    expect(screen.getByRole("heading", { name: "Benchmark sources unavailable" })).toBeInTheDocument();
    expect(screen.getByText(/Trial and evaluation sources were unavailable/)).toBeInTheDocument();
    expect(screen.getByText("Unavailable", { selector: ".benchmark-summary-grid dd .benchmark-missing" })).toBeInTheDocument();
    expect(screen.getByText(/Evaluation source unavailable · Execution source unavailable/)).toBeInTheDocument();
    expect(screen.queryByText("0 recorded evaluations · 0 complete executions")).not.toBeInTheDocument();
  });

  it("separates review activity from a week with no benchmark measurements", () => {
    renderPage({ ...fixture, weeks: [{ ...fixture.weeks[0], families: [] }] });
    expect(screen.getByText("No benchmark measurements recorded this week")).toBeInTheDocument();
    expect(screen.getByText(/Frontier review activity is recorded separately/)).toBeInTheDocument();
    expect(screen.queryByText("No matching benchmark families")).not.toBeInTheDocument();
  });
});
