/** Recorded, restored independent follow-on studies. */
export interface FollowonGroup {
  condition: string[];
  declared: number;
  attempted: number;
  passed: number;
  timeouts: number;
  errors: number;
  supported: number;
  unsupported: number;
  wall_seconds: number;
  calls: number;
  recorded_timings: number;
  mean_request_latency_seconds: number | null;
  mean_first_token_seconds: number | null;
  actual_input_tokens_min: number | null;
  actual_input_tokens_max: number | null;
}
export interface FollowonBlock {
  block_id: string;
  kind: string;
  run_sha256: string;
  attempted: number;
  passed: number | null;
  timeouts: number;
  groups: FollowonGroup[];
}
export interface RecordedFollowonWindow {
  id: string;
  cohort: "resident" | "flash";
  routes: ("resident_qwen" | "resident_gemma" | "flash_next_mia")[];
  status: "recorded_admitted" | "incomplete" | "source_unavailable";
  admission_class: "RECORDED_COMPLETED_WINDOW_ADMISSION" | null;
  current_source_replay: "not_performed" | "verified" | "unavailable" | "invalid";
  report_schema: "flash-followon-content-free-report/v1" | null;
  report_sha256: string | null;
  admission_sha256: string | null;
  recorded_controller_source_bundle_sha256: string | null;
  window_plan_sha256: string | null;
  result_sha256: string | null;
  exact_restoration_verified: boolean | null;
  comparison_eligible: false;
  blocks: FollowonBlock[];
}
export interface FollowonResultsProgress {
  schema_version: "local-followon-results-progress/v1";
  status: "available" | "partial" | "unavailable";
  windows: RecordedFollowonWindow[];
  warnings: string[];
  promotion_authorized: false;
}
