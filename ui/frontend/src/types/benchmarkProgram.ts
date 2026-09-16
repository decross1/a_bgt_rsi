export type BenchmarkProgramStatus =
  | "draft"
  | "frozen"
  | "review_required"
  | "awaiting_baseline"
  | "running"
  | "complete"
  | "unavailable"
  | string;

export interface BenchmarkProgramRelease {
  version?: string | null;
  status?: BenchmarkProgramStatus | null;
  frozen_at?: string | null;
  published_at?: string | null;
  expires_at?: string | null;
  definition_sha256?: string | null;
  public_witness?: unknown;
  [key: string]: unknown;
}

export interface BenchmarkProgramDesign {
  capability_units_per_arm?: number | null;
  system_missions_per_arm?: number | null;
  model_calls_per_arm?: number | null;
  paired_model_call_cap?: number | null;
  categories?: unknown;
  [key: string]: unknown;
}

export interface BenchmarkProgramProgress {
  status?: BenchmarkProgramStatus | null;
  phase?: string | null;
  run_id?: string | null;
  completed_units?: number | null;
  total_units?: number | null;
  completed_calls?: number | null;
  total_calls?: number | null;
  blockers?: unknown;
  next_action?: string | null;
  [key: string]: unknown;
}

export interface BenchmarkProgramComparison {
  status?: BenchmarkProgramStatus | null;
  baseline?: unknown | null;
  arms?: unknown;
  matched_results?: unknown;
  history?: unknown;
  [key: string]: unknown;
}

export interface BenchmarkProgramLayer {
  status?: BenchmarkProgramStatus | null;
  summary?: string | null;
  evidence_refs?: unknown;
  [key: string]: unknown;
}

export interface BenchmarkProgramResponse {
  schema_version: "benchmark-program/v1";
  generated_at?: string | null;
  release?: BenchmarkProgramRelease | null;
  design?: BenchmarkProgramDesign | null;
  progress?: BenchmarkProgramProgress | null;
  comparison?: BenchmarkProgramComparison | null;
  layers?: {
    model?: BenchmarkProgramLayer | null;
    system?: BenchmarkProgramLayer | null;
    runtime?: BenchmarkProgramLayer | null;
    applied?: BenchmarkProgramLayer | null;
    [key: string]: BenchmarkProgramLayer | null | undefined;
  } | null;
  warnings?: unknown;
  archive_links?: unknown;
  [key: string]: unknown;
}
