import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ResearchOpsCard } from "../src/components/ResearchOpsCard";

const sha = (c: string) => c.repeat(64);
const receipt = () => ({
  schema: "research-ops-status/v1", observed_at: new Date().toISOString(),
  active_campaign: { campaign_id: "v2-campaign", manifest_sha256: sha("a") },
  campaign_queue: { status: "all_registered_topics_consumed", eligible_count: 0,
    consumed_count: 1, loop_source_sha256: sha("b") },
  next_registered_campaign: { campaign_id: "next-campaign", manifest_sha256: sha("c"),
    registered_topic_count: 12, activation_required: true },
  last_productive: { kind: "campaign_iteration_recorded", iteration_id: "iter-001",
    topic_id: "topic-001", at: new Date().toISOString(), gate_status: "pending",
    loop_source_sha256: sha("b") },
  last_cycle: { run_id: "cycle-001", at: new Date().toISOString(), terminal_status: "executed",
    action_code: "noop",
    planned_count: 0, dispatched_count: 0, outcome_count: 1,
    action_kind: "noop" as string | null, promoted_count: 0, substantive_progress: false,
    raw_row_sha256: sha("d"), cycles_source_sha256: sha("e") },
  budget: { source_status: "available", spent_today: 3, daily_cap: 60,
    paced_allowance: 44, ledger_sha256: sha("f") },
  dispatch_gate: { operator_pause: false, other_actionable_work: "not_assessed" },
  ingestion: { source_status: "unknown", latest_attempt_status: "unknown",
    last_success_at: null as string | null, last_success_input_sha256: null as string | null,
    last_success_pointer_sha256: null as string | null },
});
const show = (data: unknown, failing = false) => render(<MemoryRouter><ResearchOpsCard data={data} failing={failing} /></MemoryRouter>);
const payoffObservation = (): Record<string, unknown> & { jobs: Record<string, unknown>[] } => ({
  schema_version: "registered-payoff-jobs-observation/v1", source_status: "available",
  checked_at: new Date().toISOString(), queue_source_sha256: sha("9"),
  timer_activation: "not_verified", comparison_eligible: false,
  jobs: [
    { job_id: "payoff-representation-a", panel_id: "payoff-representation-a",
      not_before: "2026-09-15T19:00:00+00:00", expires_at: "2026-09-16T00:00:00+00:00",
      eligibility_window: { not_before: "2026-09-15T19:00:00+00:00", expires_at: "2026-09-16T00:00:00+00:00" },
      role: "first_fresh_payoff_representation_diagnostic", state: "eligible_prepared",
      attempt_index: 0, prepared_window_present: true, last_availability_refusal: null,
      terminal_diagnostic: null, comparison_eligible: false },
    { job_id: "payoff-representation-b", panel_id: "payoff-representation-b",
      not_before: "2026-09-16T03:30:00+00:00", expires_at: "2026-09-16T08:00:00+00:00",
      eligibility_window: { not_before: "2026-09-16T03:30:00+00:00", expires_at: "2026-09-16T08:00:00+00:00" },
      role: "fresh_input_followup_not_same_prompt_reseed", state: "not_due",
      attempt_index: 0, prepared_window_present: false, last_availability_refusal: null,
      terminal_diagnostic: null, comparison_eligible: false },
  ],
});
const payoffTerminal = () => ({
  schema_version: "registered-payoff-terminal-diagnostic/v1",
  status: "admitted_diagnostic", finished_at: "2026-09-16T03:35:08+00:00",
  attempted_calls: 12,
  summary: { strict_shape_valid: 12, focal_correct: 1, total_correct: 1, both_correct: 0 },
  by_view: {
    seat_table: { attempted: 6, returned: 6, strict_shape_valid: 6,
      focal_correct: 0, total_correct: 1, both_correct: 0 },
    word_list: { attempted: 6, returned: 6, strict_shape_valid: 6,
      focal_correct: 1, total_correct: 0, both_correct: 0 },
  },
  admission_receipt_sha256: sha("1"), job_admission_receipt_sha256: sha("2"),
  dispatch_result_sha256: sha("3"), claim_scope: "instrument_only_unlinked",
  campaign_link: null, thesis_credit: false, promotion_authorized: false,
  comparison_eligible: false, scientific_novelty_claimed: false,
});
const guardedObservation = () => {
  const base = (arm: string) => ({
    window_id: "qfn-followon-known-opponent-lab8h-bridge-" + arm,
    terminal_status: "incomplete", restoration_status: "guard_and_parent_verified",
    final_record_status: "absent", started_at: new Date().toISOString(),
    finished_at: new Date().toISOString(), result_raw_sha256: sha("1"),
    state_raw_sha256: sha("2"), plan_raw_sha256: sha("3"),
    parent_emergency_raw_sha256: sha("4"), partial_prompt_receipts: null as number | null,
    partial_audit_raw_sha256: null as string | null, iteration_id: null as string | null,
    loop_memory_raw_sha256: null as string | null, journal_raw_sha256: null as string | null,
    scientific_admission_claimed: false,
  });
  return {
    schema_version: "guarded-research-attempts-observation/v1",
    observed_at: new Date().toISOString(), source_status: "available",
    latest_terminal_window_id: "qfn-followon-known-opponent-lab8h-bridge-c",
    attempts: [
      { ...base("d"), terminal_status: "no_terminal_receipt",
        restoration_status: "unknown", final_record_status: "unknown",
        started_at: null, finished_at: null, result_raw_sha256: null,
        state_raw_sha256: null, plan_raw_sha256: null,
        parent_emergency_raw_sha256: null },
      base("c"),
      { ...base("b"), partial_prompt_receipts: 15,
        partial_audit_raw_sha256: sha("5") },
      { ...base("a"), restoration_status: "guard_verified_parent_unverified" },
    ],
    current_source_replay: "not_performed", scientific_admission_claimed: false,
    private_content_exported: false,
  };
};
const guardedRow = (label: string, content: string) =>
  (_: string, element: Element | null) => element?.tagName === "DD" &&
    !!element.textContent?.includes(label + ": " + content);

describe("ResearchOpsCard", () => {
  it("separates exhausted campaign topics, recorded iterations, no-op plans, dispatch, and unknown ingestion", () => {
    show(receipt());
    expect(screen.getByText("All topics in this campaign have been used")).toBeInTheDocument();
    expect(screen.getByText(/Other useful research actions have not been assessed/)).toBeInTheDocument();
    expect(screen.getByText(/Next registered campaign next-campaign awaits activation/)).toBeInTheDocument();
    expect(screen.getByText(/iter-001/)).toBeInTheDocument();
    expect(screen.getByText(/Review gate: pending/)).toBeInTheDocument();
    expect(screen.getByText(/does not itself establish an accepted finding/)).toBeInTheDocument();
    expect(screen.getByText(/No-op plan · 0 planned · 0 dispatched/)).toBeInTheDocument();
    expect(screen.getByText(/Today's coordinator allowance: 3\/60 used/)).toBeInTheDocument();
    expect(screen.getByText("Source attempt status unknown")).toBeInTheDocument();
    expect(screen.getByText(/Last receipt-bound success: not verified/)).toBeInTheDocument();
    const diagnostics = screen.getByTestId("recorded-diagnostic-studies");
    expect(diagnostics).not.toHaveAttribute("open");
    expect(within(diagnostics).getByText("Registered payoff jobs")).toBeInTheDocument();
    expect(diagnostics).not.toContainElement(screen.getByText("Latest coordinator cycle"));
  });

  it("shows an eligible topic and a receipt-bound source success without treating a plan as dispatch", () => {
    const data = receipt();
    data.campaign_queue = { ...data.campaign_queue, status: "eligible", eligible_count: 2 };
    data.last_cycle = { ...data.last_cycle, action_code: "actions_planned", planned_count: 2,
      dispatched_count: 1 };
    data.ingestion = { ...data.ingestion, source_status: "available", latest_attempt_status: "succeeded",
      last_success_at: new Date().toISOString(), last_success_input_sha256: sha("1"),
      last_success_pointer_sha256: sha("2") };
    show(data);
    expect(screen.getByText("2 registered topics eligible")).toBeInTheDocument();
    expect(screen.getByText(/Plan recorded · 2 planned · 1 dispatched/)).toBeInTheDocument();
    expect(screen.getByText("Latest source attempt succeeded")).toBeInTheDocument();
    expect(screen.queryByText(/Last receipt-bound success: not verified/)).not.toBeInTheDocument();
  });

  it("states when a bound promotion check advanced no research record", () => {
    const data = receipt();
    data.last_cycle = { ...data.last_cycle, action_code: "actions_planned", planned_count: 1,
      dispatched_count: 1, action_kind: "promote_findings", promoted_count: 0,
      substantive_progress: false };
    const { rerender } = show(data);
    const line = screen.getByText(/Promotion check completed · 0 findings promoted/);
    expect(line).toHaveTextContent("no research record advanced");
    expect(screen.getByRole("link", { name: "view trace" })).toHaveAttribute("href", "/cycles");
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data, last_cycle: {
      ...data.last_cycle, promoted_count: 1,
    } }} /></MemoryRouter>);
    expect(screen.queryByText(/0 findings promoted/)).not.toBeInTheDocument();
    expect(screen.getByText(/Plan recorded · 1 planned · 1 dispatched/)).toBeInTheDocument();
  });

  it("shows a source-bound latest no-plan cycle without falling back to older progress", () => {
    const data = receipt();
    data.last_cycle = { ...data.last_cycle, terminal_status: "no_valid_plan",
      action_code: "no_valid_plan", planned_count: 0, dispatched_count: 0,
      outcome_count: 0, action_kind: null, promoted_count: 0,
      substantive_progress: false };
    const { rerender } = show(data);
    expect(screen.getByText(/No valid plan; no actions dispatched/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "view trace" })).toHaveAttribute("href", "/cycles");
    expect(screen.getByText(/cycle-001/)).toBeInTheDocument();
    expect(screen.queryByText(/Promotion check completed/)).not.toBeInTheDocument();

    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data, last_cycle: {
      ...data.last_cycle, outcome_count: 1,
    } }} /></MemoryRouter>);
    expect(screen.queryByText(/No valid plan; no actions dispatched/)).not.toBeInTheDocument();
    expect(screen.getByText("No bound coordinator check")).toBeInTheDocument();
  });

  it("prioritizes the registered successor and labels the legacy fetch failure as log-only", () => {
    const data = {
      ...receipt(),
      next_work: { code: "activate_registered_successor", campaign_id: "next-campaign",
        topic_id: null, study_id: null, manifest_sha256: sha("c"),
        preregistration_sha256: null, activation_required: true },
      ingestion_legacy_log: { status: "fetch_failed_log_observed",
        started_at: new Date().toISOString(), log_sha256: sha("3"),
        http_codes_observed: ["429", "503"], retry_count_observed: 6,
        receipt_bound: false },
    };
    show(data);
    expect(screen.getByText("Activate registered successor next-campaign")).toBeInTheDocument();
    expect(screen.getByText(/Registered next step; no task dispatch is implied/)).toBeInTheDocument();
    expect(screen.getByText(/Legacy log observed a failed fetch/)).toBeInTheDocument();
    expect(screen.getByText(/HTTP 429\/503; 6 retries/)).toBeInTheDocument();
    expect(screen.getByText("Source attempt status unknown")).toBeInTheDocument();
    expect(screen.queryByText("Latest source attempt succeeded")).not.toBeInTheDocument();
  });

  it("requires exact archived binary-pilot admission before offering review", () => {
    const data = {
      ...receipt(),
      next_work: { code: "review_admitted_empirical_pilot", campaign_id: "v2-campaign",
        topic_id: null, study_id: "known-opponent-utility-response-pilot-v1",
        manifest_sha256: sha("a"), preregistration_sha256: sha("4"),
        activation_required: false, pilot_admission_receipt_sha256: sha("5") },
      empirical_pilot: { status: "recorded_admitted", window_id: "binary-pilot-001",
        admission_receipt_sha256: sha("5"), pilot_run_sha256: sha("6"),
        attempted_calls: 108, complete_episodes: 12, current_source_replay: "not_performed" },
    };
    const { rerender } = show(data);
    expect(screen.getByText(/Review admitted binary pilot/)).toBeInTheDocument();
    expect(screen.getByText(/12 complete episodes, 108 attempted calls/)).toBeInTheDocument();
    expect(screen.getByText(/continuous-weight hypothesis remains unconfirmed/)).toBeInTheDocument();
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data,
      empirical_pilot: { ...data.empirical_pilot, admission_receipt_sha256: sha("7") } }} /></MemoryRouter>);
    expect(screen.queryByText(/Review admitted binary pilot/)).not.toBeInTheDocument();
  });

  it("keeps the exhausted topic queue visible beside advisory pilot review and staged successor", () => {
    const campaignId = "v2-known-opponent-utility-20260915";
    const data = {
      ...receipt(),
      active_campaign: { campaign_id: campaignId, manifest_sha256: sha("a") },
      campaign_queue: { status: "all_registered_topics_consumed",
        eligible_count: 0, consumed_count: 3, eligible_topic_ids: [],
        loop_source_sha256: sha("b") },
      next_registered_campaign: null,
      next_work: { code: "review_admitted_empirical_pilot",
        campaign_id: campaignId, topic_id: null,
        study_id: "known-opponent-utility-response-pilot-v1",
        manifest_sha256: sha("a"), preregistration_sha256: sha("4"),
        activation_required: false, pilot_admission_receipt_sha256: sha("5") },
      empirical_pilot: { status: "recorded_admitted",
        window_id: "qfn-followon-known-opponent-lab8h-a",
        admission_receipt_sha256: sha("5"), pilot_run_sha256: sha("6"),
        attempted_calls: 108, complete_episodes: 12,
        current_source_replay: "not_performed" },
    };
    const { rerender } = show(data);
    expect(screen.getByText(/Registered topic queue exhausted: 0 of 3 eligible/)).toBeInTheDocument();
    expect(screen.getByText(/no further topic dispatch from this campaign/)).toBeInTheDocument();
    expect(screen.getByText(/Review admitted binary pilot/)).toBeInTheDocument();
    expect(screen.getByText(/already recorded pilot; it is not a new topic run/)).toBeInTheDocument();
    expect(screen.queryByText(/Next registered campaign/)).not.toBeInTheDocument();
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data,
      next_registered_campaign: {
        campaign_id: "v2-utility-mechanism-followon-20260915",
        manifest_sha256: sha("c"), registered_topic_count: 3,
        activation_required: true,
      } }} /></MemoryRouter>);
    expect(screen.getByText(/Next registered campaign v2-utility-mechanism-followon-20260915 awaits activation/)).toBeInTheDocument();
    expect(screen.getByText(/Active campaign v2-known-opponent-utility-20260915/)).toBeInTheDocument();
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data,
      campaign_queue: { status: "eligible", eligible_count: 1,
        consumed_count: 2, eligible_topic_ids: ["topic-known-third-001"],
        loop_source_sha256: sha("b") } }} /></MemoryRouter>);
    expect(screen.getByText(/Registered topic queue: 1 of 3 eligible; 2 used/)).toBeInTheDocument();
    expect(screen.getByText(/Next eligible registered topic topic-known-third-001/)).toBeInTheDocument();
    expect(screen.getByText(/Review admitted binary pilot/)).toBeInTheDocument();
  });

  it("shows admitted binary-pilot behavior by utility without accepting a theory claim", () => {
    const admission = sha("5"), run = sha("6");
    const behavior = {
      schema_version: "known-opponent-pilot-behavior/v1",
      admission_receipt_sha256: admission, pilot_run_sha256: run,
      manifest_raw_sha256: sha("7"), scheduled_action_calls: 96,
      valid_action_calls: 96, complete_episodes: 12,
      zero_regret_complete_episodes: 3, comprehension_passed: 0,
      comprehension_scheduled_episodes: 12, comprehension_prompt_forms: 2,
      form_repetitions_each: 6,
      by_utility: { own_payoff: { complete: 6, zero_regret: 3 },
        joint_payoff: { complete: 6, zero_regret: 0 } },
      current_source_replay: "not_performed", theory_accepted: false,
      strategy_causal_claim: false,
    };
    const data = {
      ...receipt(),
      next_work: { code: "review_admitted_empirical_pilot", campaign_id: "v2-campaign",
        topic_id: null, study_id: "known-opponent-utility-response-pilot-v1",
        manifest_sha256: sha("a"), preregistration_sha256: sha("4"),
        activation_required: false, pilot_admission_receipt_sha256: admission },
      empirical_pilot: { status: "recorded_admitted",
        window_id: "qfn-followon-known-opponent-lab8h-a",
        admission_receipt_sha256: admission, pilot_run_sha256: run,
        attempted_calls: 108, complete_episodes: 12,
        current_source_replay: "not_performed", behavior_summary: behavior },
    };
    const { rerender } = show(data);
    expect(screen.getByText(/Action syntax: 96\/96 scheduled actions valid/)).toBeInTheDocument();
    expect(screen.getByText(/Zero regret: 3\/12 complete episodes/)).toBeInTheDocument();
    expect(screen.getByText(/3\/6 own-payoff; 0\/6 joint-payoff/)).toBeInTheDocument();
    expect(screen.getByText(/Comprehension: 0\/12 episodes correct/)).toBeInTheDocument();
    expect(screen.getByText(/two prompt forms repeated six times each/)).toBeInTheDocument();
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data, next_work: {
      ...data.next_work, code: "run_preregistered_campaign_topic",
      topic_id: "next-topic", pilot_admission_receipt_sha256: null,
    } }} /></MemoryRouter>);
    expect(screen.getByText(/Action syntax: 96\/96/)).toBeInTheDocument();
    expect(screen.queryByText(/Review admitted binary pilot/)).not.toBeInTheDocument();
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data, empirical_pilot: {
      ...data.empirical_pilot, behavior_summary: { ...behavior,
        zero_regret_complete_episodes: 13 } } }} /></MemoryRouter>);
    expect(screen.queryByText(/Action syntax: 96\/96/)).not.toBeInTheDocument();
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data, empirical_pilot: {
      ...data.empirical_pilot, behavior_summary: { ...behavior,
        admission_receipt_sha256: sha("8") } } }} /></MemoryRouter>);
    expect(screen.queryByText(/Action syntax: 96\/96/)).not.toBeInTheDocument();
  });

  it("labels a prepared Mia arm as pending without displaying attempted calls", () => {
    const data = { ...receipt(), mia_known_opponent_pilot: {
      schema_version: "known-opponent-mia-ui-observation/v1",
      status: "prepared_admission_pending",
      window_id: "qfn-followon-known-opponent-mia-lab8h-a",
      window_raw_sha256: sha("1"), matched_gemma_admission_sha256: sha("2"),
      current_source_replay: "not_performed", comparison_eligible: false,
      promotion_authorized: false, trading_claim_authorized: false,
      private_content_exported: false, arms: null,
    } };
    const { rerender } = show(data);
    expect(screen.getByText(/Registered Mia window prepared; restored-window admission/)).toBeInTheDocument();
    expect(screen.getByText(/Preparation is not an executed call or a model score/)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: /matched known-opponent pilot arms/i })).not.toBeInTheDocument();
    const recorded = { ...data.mia_known_opponent_pilot,
      status: "recorded_admission_report_pending", mia_admission_sha256: sha("3") };
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data,
      mia_known_opponent_pilot: recorded }} /></MemoryRouter>);
    expect(screen.getByText(/Archived Mia admission receipt recorded; descriptive comparison source verification is pending/)).toBeInTheDocument();
  });

  it("shows only a raw-bound descriptive two-arm pilot with separate regret denominators", () => {
    const admission = sha("5"), run = sha("6");
    const behavior = { schema_version: "known-opponent-pilot-behavior/v1",
      admission_receipt_sha256: admission, pilot_run_sha256: run,
      manifest_raw_sha256: sha("7"), scheduled_action_calls: 96,
      valid_action_calls: 96, complete_episodes: 12,
      zero_regret_complete_episodes: 3, comprehension_passed: 0,
      comprehension_scheduled_episodes: 12, comprehension_prompt_forms: 2,
      form_repetitions_each: 6,
      by_utility: { own_payoff: { complete: 6, zero_regret: 3 },
        joint_payoff: { complete: 6, zero_regret: 0 } },
      current_source_replay: "not_performed", theory_accepted: false,
      strategy_causal_claim: false };
    const gemma = { scheduled_cells: 12, recorded_cells: 12,
      scheduled_action_calls: 96, attempted_calls: 108, arithmetic_passed: 0,
      valid_action_calls: 96, complete_episodes: 12,
      zero_regret_complete_episodes: 3, returned_sse_verified: 108,
      evaluator_elapsed_s: 23.614,
      by_utility: behavior.by_utility };
    const mia = { ...gemma, zero_regret_complete_episodes: 2,
      evaluator_elapsed_s: 84.5,
      by_utility: { own_payoff: { complete: 6, zero_regret: 1 },
        joint_payoff: { complete: 6, zero_regret: 1 } } };
    const pilot = { schema_version: "known-opponent-mia-ui-observation/v1",
      status: "admitted_descriptive", window_id: "qfn-followon-known-opponent-mia-lab8h-a",
      window_raw_sha256: sha("1"), matched_gemma_admission_sha256: admission,
      report_raw_sha256: sha("2"), index_raw_sha256: sha("3"),
      report_source_sha256: sha("4"), mia_admission_sha256: sha("8"),
      current_source_replay: "not_performed", comparison_eligible: false,
      promotion_authorized: false, trading_claim_authorized: false,
      private_content_exported: false, arms: { gemma, mia } };
    const data = { ...receipt(),
      empirical_pilot: { status: "recorded_admitted",
        window_id: "qfn-followon-known-opponent-lab8h-a",
        admission_receipt_sha256: admission, pilot_run_sha256: run,
        attempted_calls: 108, complete_episodes: 12,
        current_source_replay: "not_performed", behavior_summary: behavior },
      mia_known_opponent_pilot: pilot };
    const { rerender } = show(data);
    const table = screen.getByRole("table", { name: "Descriptive matched known-opponent pilot arms" });
    expect(table).toHaveTextContent("Resident Gemma");
    expect(table).toHaveTextContent("Optimized Flash Mia · MTP3");
    expect(table).toHaveTextContent("3/6");
    expect(table).toHaveTextContent("1/6");
    expect(table).toHaveTextContent("23.6 s");
    expect(table).toHaveTextContent("84.5 s");
    expect(screen.getByText(/incomplete episodes have unknown full-horizon regret/)).toBeInTheDocument();
    expect(screen.getByText(/Private response replay ran at publication/)).toBeInTheDocument();
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data,
      mia_known_opponent_pilot: { ...pilot, arms: { gemma, mia: {
        ...mia, attempted_calls: 107, valid_action_calls: 95,
        returned_sse_verified: 107, complete_episodes: 11,
        by_utility: { own_payoff: { complete: 5, zero_regret: 1 },
          joint_payoff: { complete: 6, zero_regret: 1 } }
      } } }
    }} /></MemoryRouter>);
    expect(screen.getByRole("table", { name: /matched known-opponent pilot arms/i })).toHaveTextContent("11/12");
    expect(screen.getByRole("table", { name: /matched known-opponent pilot arms/i })).toHaveTextContent("1/5");
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data,
      mia_known_opponent_pilot: { ...pilot, arms: { gemma, mia: {
        ...mia, evaluator_elapsed_s: Number.NaN } } }
    }} /></MemoryRouter>);
    expect(screen.queryByRole("table", { name: /matched known-opponent pilot arms/i })).not.toBeInTheDocument();
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data,
      mia_known_opponent_pilot: { ...pilot, matched_gemma_admission_sha256: sha("9") }
    }} /></MemoryRouter>);
    expect(screen.queryByRole("table", { name: /matched known-opponent pilot arms/i })).not.toBeInTheDocument();
    expect(screen.getByText(/outcome counts withheld/)).toBeInTheDocument();
  });

  it("shows the two registered payoff job windows without claiming timer activation or dispatch", () => {
    show({ ...receipt(), next_work: { code: "run_preregistered_campaign_topic",
      topic_id: "unrelated-topic" }, payoff_jobs: payoffObservation() });
    expect(screen.getByText("Registered payoff jobs")).toBeInTheDocument();
    expect(screen.getByText("A · first fresh input")).toBeInTheDocument();
    expect(screen.getByText(/Prepared and eligible/)).toBeInTheDocument();
    expect(screen.getByText("B · fresh-input follow-up")).toBeInTheDocument();
    expect(screen.getByText(/Not due/)).toBeInTheDocument();
    expect(screen.getAllByText(/Eligibility window/)).toHaveLength(2);
    expect(screen.getByText(/Last source-bound queue check/)).toBeInTheDocument();
    expect(screen.getByText(/Timer activation is not verified/)).toBeInTheDocument();
    expect(screen.getByText(/preparation alone does not establish execution/)).toBeInTheDocument();
    expect(screen.queryByText(/timer enabled/i)).not.toBeInTheDocument();
  });

  it("shows only a fully bounded terminal payoff diagnostic as instrument-only evidence", () => {
    const observation = payoffObservation();
    observation.jobs[1] = { ...observation.jobs[1], state: "admitted_attempt_verified",
      prepared_window_present: true, terminal_diagnostic: payoffTerminal() };
    const data = { ...receipt(), payoff_jobs: observation };
    const { rerender } = show(data);
    const diagnostic = screen.getByTestId("payoff-terminal-payoff-representation-b");
    expect(diagnostic).toHaveTextContent("Completed Sep 16, 2026, 3:35 AM UTC · 12 calls attempted");
    expect(diagnostic).toHaveTextContent("Strict shape 12/12 · focal payoff 1/12 · total payoff 1/12 · both 0/12");
    expect(diagnostic).toHaveTextContent("Seat table: 6/6 strict shape, 0 focal, 1 total, 0 both");
    expect(diagnostic).toHaveTextContent("Word list: 6/6 strict shape, 1 focal, 0 total, 0 both");
    expect(diagnostic).toHaveTextContent("Instrument-only diagnostic · unlinked to the active campaign");
    expect(screen.getByText("Per-view breakdown and evidence boundary")).toBeInTheDocument();
    expect(diagnostic).toHaveTextContent("no thesis credit, promotion, comparison, or scientific novelty claim");
    expect(screen.getByText(/Recorded diagnostic studies · latest payoff completed Sep 16, 2026, 3:35 AM UTC/)).toBeInTheDocument();

    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data, payoff_jobs: {
      ...observation, jobs: [observation.jobs[0], { ...observation.jobs[1],
        state: "eligible_prepared" }],
    } }} /></MemoryRouter>);
    expect(screen.queryByTestId("payoff-terminal-payoff-representation-b")).not.toBeInTheDocument();

    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data, payoff_jobs: {
      ...observation, jobs: [observation.jobs[0], { ...observation.jobs[1],
        terminal_diagnostic: { ...payoffTerminal(), campaign_link: "v2-campaign" } }],
    } }} /></MemoryRouter>);
    expect(screen.queryByTestId("payoff-terminal-payoff-representation-b")).not.toBeInTheDocument();
    expect(screen.getByText(/Admitted attempt verified at last queue check/)).toBeInTheDocument();

    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data, payoff_jobs: {
      ...observation, jobs: [observation.jobs[0], { ...observation.jobs[1],
        terminal_diagnostic: { ...payoffTerminal(), summary: {
          ...payoffTerminal().summary, focal_correct: 2,
        } } }],
    } }} /></MemoryRouter>);
    expect(screen.queryByTestId("payoff-terminal-payoff-representation-b")).not.toBeInTheDocument();

    const impossible = payoffTerminal();
    impossible.summary.both_correct = 1;
    impossible.by_view.seat_table.both_correct = 1;
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data, payoff_jobs: {
      ...observation, jobs: [observation.jobs[0], { ...observation.jobs[1],
        terminal_diagnostic: impossible }],
    } }} /></MemoryRouter>);
    expect(screen.queryByTestId("payoff-terminal-payoff-representation-b")).not.toBeInTheDocument();
  });

  it("withholds payoff readiness when a row, source hash, or check time is unbound", () => {
    const observation = payoffObservation();
    const data = { ...receipt(), payoff_jobs: observation };
    const { rerender } = show(data);
    expect(screen.getByText(/Prepared and eligible/)).toBeInTheDocument();
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data, payoff_jobs: {
      ...observation, jobs: [{ ...observation.jobs[0], state: "admitted_attempt_verified",
        comparison_eligible: true }, observation.jobs[1]] } }} /></MemoryRouter>);
    expect(screen.queryByText(/Admitted attempt verified/)).not.toBeInTheDocument();
    expect(screen.getByText(/queue observation unavailable or stale/)).toBeInTheDocument();
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data, payoff_jobs: {
      ...observation, queue_source_sha256: "unbound" } }} /></MemoryRouter>);
    expect(screen.queryByText(/Prepared and eligible/)).not.toBeInTheDocument();
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data, payoff_jobs: {
      ...observation, checked_at: new Date(Date.now() - 10 * 60_000).toISOString() } }} /></MemoryRouter>);
    expect(screen.queryByText(/Prepared and eligible/)).not.toBeInTheDocument();
  });

  it("labels an unavailable payoff package instead of inventing a prepared job", () => {
    show({ ...receipt(), payoff_jobs: {
      schema_version: "registered-payoff-jobs-observation/v1",
      source_status: "package_unavailable", checked_at: new Date().toISOString(),
      queue_source_sha256: null, jobs: null, timer_activation: "not_verified",
      comparison_eligible: false } });
    expect(screen.getByText(/Payoff job package unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/Prepared and eligible/)).not.toBeInTheDocument();
  });

  it("shows guarded A/B/C as incomplete history and D unknown without changing the last linked iteration", () => {
    show({ ...receipt(), guarded_research_attempts: guardedObservation() });
    expect(screen.getByText("Guarded research attempts")).toBeInTheDocument();
    expect(screen.getByText(/Latest terminal observation C/)).toBeInTheDocument();
    expect(screen.getByText(guardedRow("D", "No terminal receipt observed"))).toBeInTheDocument();
    expect(screen.getByText(guardedRow("C", "Incomplete; guard and parent verified restoration"))).toBeInTheDocument();
    expect(screen.getByText(guardedRow("B", "Incomplete; guard and parent verified restoration"))).toBeInTheDocument();
    expect(screen.getByText(guardedRow("A", "Incomplete; guard recorded restoration, parent recovery unverified"))).toBeInTheDocument();
    expect(screen.getByText(/15 prompt receipts; no empirical or scientific result was admitted/)).toBeInTheDocument();
    expect(screen.getByText(/iter-001/)).toBeInTheDocument();
    expect(screen.queryByText(/journal_fallback_enum_mismatch/)).not.toBeInTheDocument();
  });

  it("withholds unbound guarded receipts and distinguishes guard record from final journal binding", () => {
    const observation = guardedObservation();
    const data = { ...receipt(), guarded_research_attempts: observation };
    const { rerender } = show(data);
    expect(screen.getByText(guardedRow("B", "Incomplete"))).toBeInTheDocument();
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data, guarded_research_attempts: {
      ...observation, attempts: [observation.attempts[0], observation.attempts[1],
        { ...observation.attempts[2], result_raw_sha256: "unbound" },
        observation.attempts[3]] } }} /></MemoryRouter>);
    expect(screen.getByText(/Guarded attempt receipts unavailable or unbound/)).toBeInTheDocument();
    const d = { ...observation.attempts[2],
      window_id: "qfn-followon-known-opponent-lab8h-bridge-d",
      terminal_status: "guard_recorded_final_unverified",
      restoration_status: "guard_verified_parent_unverified",
      final_record_status: "unverified", iteration_id: "iter-2026-09-15-006",
      partial_prompt_receipts: null, partial_audit_raw_sha256: null,
      parent_emergency_raw_sha256: null,
    };
    const pending = { ...observation,
      latest_terminal_window_id: d.window_id,
      attempts: [d, observation.attempts[1], observation.attempts[2],
        observation.attempts[3]] };
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data,
      guarded_research_attempts: pending }} /></MemoryRouter>);
    expect(screen.getByText(guardedRow("D", "Guard recorded and restored; final iteration record unverified"))).toBeInTheDocument();
    expect(screen.queryByText(/acceptance of its scientific claim/)).not.toBeInTheDocument();
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...data, guarded_research_attempts: {
      ...pending, attempts: [{ ...d, terminal_status: "guard_recorded_final_bound",
        final_record_status: "bound", loop_memory_raw_sha256: sha("6"),
        journal_raw_sha256: sha("7") }, observation.attempts[1],
        observation.attempts[2], observation.attempts[3]] } }} /></MemoryRouter>);
    expect(screen.getByText(guardedRow("D", "Guard recorded and restored; final iteration record bound"))).toBeInTheDocument();
    expect(screen.getByText(/not acceptance of its scientific claim/)).toBeInTheDocument();
  });

  it("withholds current work on stale, wrong-schema, or failed reads", () => {
    const stale = { ...receipt(), observed_at: new Date(Date.now() - 10 * 60_000).toISOString() };
    const { rerender } = show(stale);
    expect(screen.getByText("Current observation unavailable")).toBeInTheDocument();
    expect(screen.queryByText(/No-op plan · 0 planned/)).not.toBeInTheDocument();
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...receipt(), schema: "unknown" }} /></MemoryRouter>);
    expect(screen.getByText("Current observation unavailable")).toBeInTheDocument();
    rerender(<MemoryRouter><ResearchOpsCard data={receipt()} failing /></MemoryRouter>);
    expect(screen.getByText("Current observation unavailable")).toBeInTheDocument();
  });

  it("withholds tampered linked-iteration, cycle, and source-success details", () => {
    const data = receipt();
    data.last_productive = { ...data.last_productive, loop_source_sha256: "unbound" };
    data.last_cycle = { ...data.last_cycle, raw_row_sha256: "unbound" };
    data.ingestion = { ...data.ingestion, source_status: "available", latest_attempt_status: "succeeded",
      last_success_at: new Date().toISOString(), last_success_input_sha256: "unbound",
      last_success_pointer_sha256: sha("2") };
    show(data);
    expect(screen.getByText("No linked iteration verified in this observation")).toBeInTheDocument();
    expect(screen.getByText("No bound coordinator check")).toBeInTheDocument();
    expect(screen.getByText(/Last receipt-bound success: not verified/)).toBeInTheDocument();
  });
});
