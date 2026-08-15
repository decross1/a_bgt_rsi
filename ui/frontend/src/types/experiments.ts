// Page B — Interactive Experiment Digestion. Types mirror
// ui/backend/experiments.py. The experiments are HETEROGENEOUS: most
// fields are nullable because a given experiment may carry a JSON summary,
// a markdown summary, both, or neither.

export interface ExperimentFlags {
  has_results_dir: boolean;
  has_summary_json: boolean;
  has_summary_md: boolean;
  has_per_round: boolean;
  has_trials: boolean;
  n_results_files: number;
}

export interface ExperimentListItem extends ExperimentFlags {
  id: string;
  title: string;
}

// (ExperimentsListResponse died with the /api/experiments INDEX endpoint in
// UI simplification S3; ExperimentListItem survives as ResearchExperiment's
// base — /api/research is the index the page renders.)

// exp001-shape summary.json. Producer fields beyond these may exist; the
// per-opponent rows are passed through generically.
export interface PerOpponentSummary {
  opponent: string;
  n_rounds?: number;
  llm_coop_rate?: number;
  opp_coop_rate?: number;
  llm_mean_payoff?: number;
  opp_mean_payoff?: number;
  first_d_round_llm?: number | null;
  first_d_round_opp?: number | null;
  llm_parse_failures?: number;
  llm_default_d_plays?: number;
  wall_clock_s?: number;
}

// exp004/005-shape per_mechanism row. exp004 carries efficiency+revenue;
// exp005 carries a signed-residual instead. Every metric is optional — the
// table adapts to whichever columns the rows actually carry.
export interface PerMechanismSummary {
  mechanism: string;
  truthful_fraction?: number;
  mean_efficiency?: number;
  mean_revenue?: number;
  mean_signed_residual?: number;
  parse_failure_rate?: number;
  verdict?: string;
}

export interface SummaryJson {
  n_opponents?: number;
  rounds_per_opponent?: number;
  total_rounds?: number;
  via_orchestrator?: boolean;
  total_wall_clock_s?: number;
  per_opponent?: PerOpponentSummary[];
  // exp004/005 per-mechanism rows; exp006 flat top-level verdict.
  per_mechanism?: PerMechanismSummary[];
  verdict?: string;
  n_trials?: number;
  // The flat shape (exp006) carries arbitrary scalar metrics at top level
  // (designer_mean_efficiency, feasibility_rate, …). An index signature keeps
  // them reachable generically so the scalar-metrics card can render them
  // without enumerating every producer field.
  [key: string]: unknown;
}

export interface PerRoundEntry {
  round: number | null;
  llm: string | null;
  opp: string | null;
  llm_payoff: number | null;
  opp_payoff: number | null;
  // Running cumulative payoff, accumulated server-side so the chart plots the
  // total without re-walking rows. Present on the JSON (exp001) shape.
  cum_llm?: number;
  cum_opp?: number;
}

// Server-derived OUTCOME verdict. For the JSON shape (exp001) it classifies
// whether the LLM was EXPLOITED; for the markdown shape (exp003) it is the
// verdict line pulled from summary.md. Null when no verdict can be derived.
export interface ExploitedOpponent {
  opponent: string;
  llm_mean_payoff: number;
  opp_mean_payoff: number;
  gap: number;
}

export interface Headline {
  verdict: string;
  tone: "ok" | "warn" | "bad";
  // JSON-shape fields (absent on the markdown verdict).
  n_exploited?: number;
  n_opponents?: number;
  worst?: ExploitedOpponent | null;
  exploited?: ExploitedOpponent[];
  // The payoff-gap threshold (op - lp) the backend used to classify an
  // opponent as exploiting the LLM. Single source of truth — the table tint
  // consumes this instead of re-hardcoding the value client-side.
  exploit_gap_threshold?: number;
  mean_llm_coop_rate?: number | null;
  total_parse_failures?: number;
  // Shape discriminator + per_mechanism tally fields (exp004/005). "flat"
  // (exp006) carries only verdict/tone/kind. Absent on the legacy per_opponent
  // and markdown headlines.
  kind?: "per_mechanism" | "flat";
  n_mechanisms?: number;
  n_yes?: number;
}

export interface PerRoundAggregate {
  by_opponent: Record<string, PerRoundEntry[]>;
  total_rows: number;
  truncated: boolean;
  // false for exp001 — per-round rows carry no task_id, so a round cannot
  // be linked into the call-chain inspector. The UI surfaces this honestly.
  round_inspector_linkage: boolean;
}

export interface TrialsSample {
  // Generic — the backend does not assume a fixed trial schema.
  sample: Record<string, unknown>[];
  total_rows: number;
  truncated: boolean;
}

export interface ExperimentDetail extends ExperimentFlags {
  id: string;
  title: string;
  summary_json: SummaryJson | null;
  summary_json_error?: string;
  summary_md: string | null;
  summary_md_error?: string;
  per_round: PerRoundAggregate | null;
  trials: TrialsSample | null;
  headline: Headline | null;
}

// ─── Research page (GET /api/research) — tier-grouped index ───────────
// Mirrors ui/backend/experiments.py's /api/research. Experiments are grouped
// by sandbox tier; each carries a lightweight {text, tone} verdict (null when
// no summary was readable — never fabricated) and the loop iterations it
// bridged into ([] when none).

// One iteration that bridged this experiment's outcome into the loop. Built
// from a loop_memory.jsonl row's experiment_outcome block.
export interface ResearchBridge {
  iteration_id: string | null;
  metric: string | null;
  // The producer's value can be a scalar or an object; we render scalars.
  value: number | string | null | Record<string, unknown>;
  trials?: number | null;
}

// A lightweight verdict for the research card (reuses the detail headline
// logic server-side). Null when no summary was readable.
export interface ResearchVerdict {
  text: string | null;
  tone: "ok" | "warn" | "bad" | null;
}

export interface ResearchExperiment extends ExperimentListItem {
  verdict: ResearchVerdict | null;
  bridge: ResearchBridge[];
}

export interface ResearchTier {
  tier: string;
  label: string;
  description: string;
  experiments: ResearchExperiment[];
}

export interface ResearchResponse {
  available: boolean;
  reason?: string;
  tiers: ResearchTier[];
  untiered: ResearchExperiment[];
}
