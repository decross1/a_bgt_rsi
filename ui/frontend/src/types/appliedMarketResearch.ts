export interface MarketCaptureBatch {
  id: string;
  status: string;
  symbol?: string;
  sealed_at?: string | null;
  batch_sha256?: string;
  collector_source_verified?: boolean;
  collector_source_status?: "current_verified" | "historical_source_unavailable";
  requests_attempted?: number;
  requests_succeeded?: number;
  requests_failed?: number;
  source_valid_frames?: number;
  raw_bytes?: number;
  has_depth_snapshot?: boolean;
  trade_pages?: number;
  cursor_gap?: boolean;
  page_gap?: boolean;
  backlog_unresolved?: boolean;
}

export interface AppliedMarketResearchProgress {
  schema_version: "applied-market-research-progress/v1";
  observed_at: string;
  status: "not_started" | "data_recorded" | "attempts_recorded" | "unavailable";
  research_focus: string;
  evidence_scope: string;
  paper_result: "not_tested";
  orders_placed: 0;
  scan_complete: boolean;
  max_recent_batches: number;
  batches: MarketCaptureBatch[];
  warnings: string[];
  stages: { id: string; label: string; status: string }[];
}
