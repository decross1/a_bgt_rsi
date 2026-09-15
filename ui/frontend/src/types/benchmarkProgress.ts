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

export type ResearchPipelineStatus =
  | "not_yet_observed"
  | "partial"
  | "observed"
  | "unavailable";

export interface ResearchPipelineCounts {
  topic_attempts: number | null;
  dispatch_completions: number | null;
  dispatch_failures: number | null;
  ambiguous_dispatches: number | null;
  missing_dispatch_iteration_links: number | null;
  distinct_dispatched_iterations: number | null;
  iterations_recorded: number | null;
  missing_iteration_records: number | null;
  unlinked_iteration_records: number | null;
  campaign_link_mismatch_records: number | null;
  scope_assessed: number | null;
  in_scope: number | null;
  off_domain: number | null;
  scope_uncertain: number | null;
  evidence_assessed: number | null;
  l1_or_higher: number | null;
  l3_ready_for_skeptic: number | null;
  skeptic_reviews_recorded: number | null;
  promotion_rejections: number | null;
  promotion_validations: number | null;
  l4_validated: number | null;
  human_verdicts_recorded: number | null;
  l5_human_validated: number | null;
  evidence_levels: Record<"L0" | "L1" | "L2" | "L3" | "L4" | "L5", number | null>;
}

export interface ResearchPipelineStage {
  id: string;
  label: string;
  count: number | null;
  status: "recorded" | "not_yet_observed" | "unavailable";
}

export interface ResearchPipelineCoverage {
  id: string;
  label: string;
  covered: number | null;
  total: number | null;
  rate: number | null;
  status: "recorded" | "not_yet_observed" | "unavailable";
}

export interface ResearchPipelineRecord {
  attempt_id: string | null;
  cycle_run_id: string | null;
  recorded_at: string | null;
  topic_source: string;
  campaign_id: string;
  topic_id: string;
  dispatch_status: string;
  iteration_id: string | null;
  iteration_status: string;
  scope_status: string;
  evidence_level: "L0" | "L1" | "L2" | "L3" | "L4" | "L5" | null;
  /** Null when health-signal coverage cannot support provisional flags. */
  evidence_provisional: string[] | null;
  skeptic_status: string;
  promotion_status: string;
  human_validation_status: string;
  promotion_review_attempts: number | null;
}

export interface ResearchPipelineCampaign {
  campaign_id: string;
  title: string;
  status: string;
  opened_at: string;
  manifest_sha256: string;
  runtime?: {
    status: "inactive" | "active" | "closed" | "invalid" | "unknown";
    activated_at: string | null;
    activation_sha256: string | null;
    closed_at: string | null;
    closure_sha256: string | null;
  };
  research_question: {
    question_id: string;
    text: string;
    text_sha256: string;
  };
  evidence: {
    cpu_calibration_registered: boolean;
    cpu_calibration_verified: boolean | null;
    model_trial_status:
      | "not_registered"
      | "registered_no_bound_result"
      | "bound_result_observed"
      | "invalid_bound_result";
  };
}

export interface ResearchPipelineLineageCounts {
  explicit_match: number | null;
  unlinked_legacy: number | null;
  malformed_campaign_link: number | null;
  different_campaign: number | null;
  campaign_link_mismatch: number | null;
  malformed_record: number | null;
}

export interface ResearchPipelineSource {
  id: string;
  available: boolean;
  window_sha256: string | null;
  bytes_read: number;
  total_bytes: number | null;
  truncated_before: boolean;
  parsed_rows: number;
  malformed_rows: number;
}

export interface ResearchPipelineProgress {
  schema_version: "research-pipeline-progress/v1";
  generated_at: string;
  status: ResearchPipelineStatus;
  headline: string;
  campaign: ResearchPipelineCampaign | null;
  scope: { id: string; label: string; assessment_basis: string };
  cohort: {
    id: string;
    label: string;
    cutoff_at: string;
    cutoff_reason: string;
    cutoff_receipt_sha256: string;
    canonical_head: string;
    campaign_manifest_sha256?: string;
    membership_rule?: string;
  } | null;
  window: {
    week: string;
    mode?: "campaign_to_date";
    start_at: string;
    end_at: string;
    dispatch_end_at?: string;
    dispatch_closed?: boolean;
    complete: boolean;
  };
  counts: ResearchPipelineCounts | null;
  stages: ResearchPipelineStage[];
  coverage: ResearchPipelineCoverage[];
  bottleneck: { stage: string; status: string; explanation: string };
  records: ResearchPipelineRecord[];
  records_window?: {
    displayed: number;
    total: number | null;
    truncated: boolean;
  };
  qualifications: { code: string; detail: string }[];
  provenance: {
    join_contract?: string[];
    campaign_lineage?: Record<string, ResearchPipelineLineageCounts>;
    sources: ResearchPipelineSource[];
  };
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
  /** Optional during rolling backend/frontend deployments. */
  research_pipeline?: ResearchPipelineProgress;
  local_model_research?: LocalModelResearchProgress;
}

export interface LocalModelResearchProgress {
  schema_version: "local-model-research-progress/v1";
  status: "available" | "partial" | "unavailable";
  candidate: string;
  accounting: string;
  evidence_note: string;
  promotion_authorized: false;
  warnings: string[];
  qualification_runs: {
    id: string; status: "passed" | "failed" | "unknown" | "unfinished_receipt";
    phase: string; finished_at: string | null; candidate_window_minutes: number | null;
    minimum_memory_gib: number | null; probe_count: number | null;
    model_started: boolean | null;
    restoration: string; source_sha256: string;
    failure_class?: "experimental_startup_host_pageout_guardrail_abort" | "other_qualification_failure" | "restoration_unknown" | null;
    variant?: {
      id: string; repository: string; revision: string; served_model: string;
      image_id: string; model_artifact_sha256: string; spec_sha256: string;
      qualification_profile: string;
      evidence_class: "REGISTERED_SOURCE_ONLY" | "QUALIFICATION_ADMITTED";
    } | null;
  }[];
  comparisons: {
    id: string; status: "complete" | "incomplete"; manifest_sha256: string;
    comparison_eligible: boolean;
    run_sha256: Record<"resident" | "flash", string>; promotion_authorized: false;
    families: {
      family: string; comparison_eligible: boolean; paired_success_delta: number | null;
      equal_source_task_success_delta: number | null; source_task_interval_95: [number, number] | null;
      cohorts: Record<"resident" | "flash", {
        declared: number; attempted: number; passed: number;
        success_rate: number | null; successful_task_runs_per_hour: number | null;
      }>;
    }[];
  }[];
}
