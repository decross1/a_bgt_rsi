/** Archived historical reference and separately typed H1 forward status. */
export interface HistoricalReferenceHorizon {
  horizon_hours: 1 | 4;
  validation_scored_rows: number;
  baseline_mse_bps2: number;
  flow_model_mse_bps2: number;
  mse_improvement_bps2: number;
  mse_improvement_95ci: [number, number];
  baseline_directional_accuracy: number;
  flow_model_directional_accuracy: number;
  directional_improvement: number;
  directional_improvement_95ci: [number, number];
  baseline_reference_net_bps_per_eligible_hour: number;
  flow_reference_net_bps_per_eligible_hour: number;
  baseline_doubled_reference_net_bps_per_eligible_hour: number;
  flow_doubled_reference_net_bps_per_eligible_hour: number;
}

export interface HistoricalTradeOnlyReference {
  status: "not_recorded" | "recorded_reference_only" | "source_unavailable";
  symbol?: "BTCUSDT";
  calendar_start?: string;
  calendar_end?: string;
  source_days?: number;
  source_hours?: number;
  source_rehash_at_publication?: boolean;
  score_replay_at_publication?: boolean;
  current_source_replay?: "not_performed" | "verified" | "unavailable";
  reference_roundtrip_cost_bps?: number;
  reference_doubled_roundtrip_cost_bps?: number;
  horizons: HistoricalReferenceHorizon[];
  publication_sha256?: string;
  gate_sha256?: string;
  result_sha256?: string;
  private_predictions_sha256?: string;
  runner_source_sha256?: string;
  archive_adapter_source_sha256?: string;
  historical_executable_quotes_proven: false;
  paper_forward_result: "not_tested";
  orders_placed: 0;
}

export interface ForwardH1Status {
  status: "topic_design_only" | "rest_plan_published_local" |
    "rest_reference_recorded" | "closed_missing_source" | "source_unavailable";
  primary_horizon_hours: 1;
  secondary_horizon_hours: 4;
  rest_reference_plan_published: boolean;
  rest_reference_result_published: boolean;
  strict_paper_study_registered: false;
  paper_supported: false;
  orders_placed: 0;
  study_id?: string;
  scheduled_cells?: number;
  source_valid_cells?: number | null;
  unknown_outcome_cells?: number | null;
  all_scheduled_reference_net_bps?: {
    candidate: number;
    baseline: number;
  } | null;
  plan_publication_sha256?: string;
  result_publication_sha256?: string;
  plan_sha256?: string;
  topic_sha256?: string;
  result_sha256?: string;
  private_cells_sha256?: string;
  score_replay_at_publication?: boolean;
  current_source_replay?: "not_performed" | "verified" | "unavailable";
  external_plan_freeze_proof?: "unverified";
  nonexecutable_reference_only?: true;
}

export interface AppliedReferenceProgress {
  schema_version: "applied-reference-progress/v1";
  historical_trade_only: HistoricalTradeOnlyReference;
  forward_h1: ForwardH1Status;
  warnings: string[];
}
