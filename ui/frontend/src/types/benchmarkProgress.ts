export type AutomationMode = "review_only" | "trial_allowlisted" | "disabled" | "unknown";
export type BenchmarkFamilyStatus = "complete" | "incomplete" | "awaiting_annotation" | "mixed" | "unknown";

export interface BenchmarkProgressAvailability {
  trials: boolean;
  evaluations: boolean;
  budget: boolean;
  completion: boolean;
  activation: boolean;
  reviews: boolean;
}

export interface BenchmarkProgressAutomation {
  mode: AutomationMode;
  status: string | null;
  activated_at: string | null;
  schedule: string | null;
  promotion_enabled: boolean | null;
}

export interface BenchmarkWeekBudget {
  limit_minutes: number;
  charged_minutes: number;
  trial_charge_minutes: number;
  prior_import_minutes: number;
  remaining_minutes: number;
  active_reservations: number;
  accounting_note: string | null;
}

export interface BenchmarkProgressSummary {
  headline: string;
  upgrade_established: boolean | null;
  weeks_seen: number;
  latest_week: string | null;
  terminal_trials: number;
  recorded_evaluations: number;
  complete_executions: number;
  comparable_transitions: number;
  current_week_budget: BenchmarkWeekBudget | null;
}

export interface BenchmarkProgressWarning { code: string; scope: string; detail: string }

export interface BenchmarkReview {
  status: string | null;
  decision: "admitted" | "revision_required" | "rejected" | "no_card" | "unknown";
  experiment_proposals: 0 | 1;
  source_count: number | null;
  frontier_calls: number | null;
}

export interface BenchmarkArmMetrics {
  success_rate: number | null;
  ctt_per_hour: number | null;
  rsr_2of3: number | null;
  recorded_wall_seconds: number | null;
  mean_recorded_seconds_per_transport_attempt: number | null;
  repair_rate: number | null;
  protocol_valid_rate: number | null;
  annotation_disagreements: number | null;
}

export interface BenchmarkArm {
  id: string;
  label: string;
  configuration: string | null;
  transport_expected: number | null;
  transport_returned: number | null;
  objective_successes: number | null;
  objective_total: number | null;
  repair_successes: number | null;
  repair_total: number | null;
  timeouts: number | null;
  metrics: BenchmarkArmMetrics;
}

export interface BenchmarkComparisonPointArm {
  arm_id: string;
  success_rate: number | null;
  successes: number | null;
  success_denominator: number | null;
}

export interface BenchmarkComparisonPoint {
  week: string;
  status: BenchmarkFamilyStatus;
  baseline: BenchmarkComparisonPointArm;
  candidate: BenchmarkComparisonPointArm;
  delta_success_rate: number | null;
  trial_count: number;
}

export interface BenchmarkComparison {
  eligible: boolean;
  explanation: string;
  history_points: number;
  fingerprint: string | null;
  basis: string[];
  break_reasons: string[];
  points: BenchmarkComparisonPoint[];
}

export interface BenchmarkCompleteness { expected: number | null; returned: number | null; protocol_valid: number | null; timeouts: number | null }
export interface BenchmarkUncertainty {
  kind: "bootstrap_95" | "none";
  metric: "failure_inclusive_delta_candidate_minus_baseline" | null;
  /** Signed proportions in [-1, 1] for the candidate-minus-baseline delta. */
  low: number | null;
  high: number | null;
  n: number | null;
}

export interface BenchmarkProvenance {
  trial_ids: string[];
  manifest_sha256: string[];
  run_sha256: string[];
  evaluation_sha256: string[];
  summary_sha256: string[];
  source_commits: string[];
}

export interface BenchmarkDetails { fixture_count: number | null; repeat_count: number; grader_bound: boolean; note: string | null }

export interface BenchmarkFamily {
  id: string;
  label: string;
  kind: string;
  /** Source-provided limit on what this family's evidence can establish. */
  interpretation_note?: string;
  status: BenchmarkFamilyStatus;
  execution_status: string;
  evaluation_status: "recorded" | "partial" | "missing" | "invalid";
  semantic_verdict: "candidate_benefit_not_verified" | "unknown";
  evidence: {
    class: "UNVERIFIED_OPERATOR_SUMMARY" | "MIXED" | "NONE";
    candidate_benefit_verified: false | null;
  };
  completeness: BenchmarkCompleteness;
  comparison: BenchmarkComparison;
  arms: BenchmarkArm[];
  uncertainty: BenchmarkUncertainty;
  provenance: BenchmarkProvenance;
  details: BenchmarkDetails;
}

export interface BenchmarkWeek {
  week: string;
  status: "reviewed" | "measured" | "partial" | "unavailable";
  terminal_trials: number;
  recorded_evaluations: number;
  complete_executions: number;
  review: BenchmarkReview | null;
  budget: BenchmarkWeekBudget | null;
  families: BenchmarkFamily[];
}

export interface BenchmarkProgressResponse {
  schema_version: "weekly-upgrade-progress/v1";
  generated_at: string;
  current_week: string;
  availability: BenchmarkProgressAvailability;
  automation: BenchmarkProgressAutomation;
  summary: BenchmarkProgressSummary;
  warnings: BenchmarkProgressWarning[];
  weeks: BenchmarkWeek[];
}
