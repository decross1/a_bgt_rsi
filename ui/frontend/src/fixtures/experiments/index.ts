// Page B fixtures covering all three on-disk shapes. Components take an
// `initial` prop so tests bypass the network entirely.
import type {
  ExperimentDetail,
  ExperimentsListResponse,
} from "../../types/experiments";

// List response: one of each shape.
export const EXPERIMENTS_LIST_FIXTURE: ExperimentsListResponse = {
  available: true,
  experiments: [
    {
      id: "exp001_repeated_pd",
      title: "exp001 repeated pd",
      has_results_dir: true,
      has_summary_json: true,
      has_summary_md: false,
      has_per_round: true,
      has_trials: false,
      n_results_files: 7,
    },
    {
      id: "exp003_vickrey_rediscovery",
      title: "exp003 vickrey rediscovery",
      has_results_dir: true,
      has_summary_json: false,
      has_summary_md: true,
      has_per_round: false,
      has_trials: true,
      n_results_files: 3,
    },
    {
      id: "exp002_loop_v0_robustness",
      title: "exp002 loop v0 robustness",
      has_results_dir: false,
      has_summary_json: false,
      has_summary_md: false,
      has_per_round: false,
      has_trials: false,
      n_results_files: 0,
    },
  ],
};

export const EXPERIMENTS_LIST_UNAVAILABLE: ExperimentsListResponse = {
  available: false,
  reason: "experiments dir absent",
  experiments: [],
};

// exp001 — JSON-shaped detail with a per-opponent table + per-round series.
export const DETAIL_JSON_FIXTURE: ExperimentDetail = {
  id: "exp001_repeated_pd",
  title: "exp001 repeated pd",
  has_results_dir: true,
  has_summary_json: true,
  has_summary_md: false,
  has_per_round: true,
  has_trials: false,
  n_results_files: 7,
  summary_json: {
    n_opponents: 2,
    rounds_per_opponent: 4,
    total_rounds: 8,
    via_orchestrator: true,
    total_wall_clock_s: 39.2,
    per_opponent: [
      {
        opponent: "tft",
        n_rounds: 4,
        llm_coop_rate: 1.0,
        opp_coop_rate: 1.0,
        llm_mean_payoff: 5.0,
        opp_mean_payoff: 5.0,
        first_d_round_llm: null,
        llm_parse_failures: 0,
        wall_clock_s: 18.1,
      },
      {
        opponent: "all_d",
        n_rounds: 4,
        llm_coop_rate: 0.25,
        opp_coop_rate: 0.0,
        llm_mean_payoff: 0.75,
        opp_mean_payoff: 2.5,
        first_d_round_llm: 2,
        llm_parse_failures: 0,
        wall_clock_s: 21.1,
      },
    ],
  },
  summary_md: null,
  per_round: {
    by_opponent: {
      tft: [
        { round: 1, llm: "C", opp: "C", llm_payoff: 5, opp_payoff: 5, cum_llm: 5, cum_opp: 5 },
        { round: 2, llm: "C", opp: "C", llm_payoff: 5, opp_payoff: 5, cum_llm: 10, cum_opp: 10 },
        { round: 3, llm: "C", opp: "C", llm_payoff: 5, opp_payoff: 5, cum_llm: 15, cum_opp: 15 },
        { round: 4, llm: "C", opp: "C", llm_payoff: 5, opp_payoff: 5, cum_llm: 20, cum_opp: 20 },
      ],
      all_d: [
        { round: 1, llm: "C", opp: "D", llm_payoff: 0, opp_payoff: 7, cum_llm: 0, cum_opp: 7 },
        { round: 2, llm: "D", opp: "D", llm_payoff: 1, opp_payoff: 1, cum_llm: 1, cum_opp: 8 },
        { round: 3, llm: "D", opp: "D", llm_payoff: 1, opp_payoff: 1, cum_llm: 2, cum_opp: 9 },
        { round: 4, llm: "C", opp: "D", llm_payoff: 0, opp_payoff: 7, cum_llm: 2, cum_opp: 16 },
      ],
    },
    total_rows: 8,
    truncated: false,
    round_inspector_linkage: false,
  },
  trials: null,
  headline: {
    verdict:
      "EXPLOITED by all_d: opponent mean payoff 2.50 vs LLM 0.75",
    tone: "bad",
    n_exploited: 1,
    n_opponents: 2,
    worst: {
      opponent: "all_d",
      llm_mean_payoff: 0.75,
      opp_mean_payoff: 2.5,
      gap: 1.75,
    },
    exploited: [
      {
        opponent: "all_d",
        llm_mean_payoff: 0.75,
        opp_mean_payoff: 2.5,
        gap: 1.75,
      },
    ],
    exploit_gap_threshold: 0.5,
    mean_llm_coop_rate: 0.625,
    total_parse_failures: 0,
  },
};

// exp003 — markdown-shaped detail with a trials sample.
export const DETAIL_MD_FIXTURE: ExperimentDetail = {
  id: "exp003_vickrey_rediscovery",
  title: "exp003 vickrey rediscovery",
  has_results_dir: true,
  has_summary_json: false,
  has_summary_md: true,
  has_per_round: false,
  has_trials: true,
  n_results_files: 3,
  summary_json: null,
  summary_md:
    "# exp003 — Vickrey rediscovery summary\n\n" +
    "**Verdict: YES** — LLM bidders DID rediscover truthful bidding.\n\n" +
    "## Headline metrics\n\n" +
    "- Trials: 50 (errors: 0)\n" +
    "- Parse failures: 0/200 (0.0%)\n",
  per_round: null,
  trials: {
    sample: [
      {
        trial_idx: 0,
        bids: [2.97, 5.82, 12.51, 86.59],
        winner_idx: 3,
        price_paid: 12.51,
        tie_break: false,
      },
      {
        trial_idx: 1,
        bids: [35.12, 35.75, 34.49, 19.82],
        winner_idx: 1,
        price_paid: 35.12,
        tie_break: false,
      },
    ],
    total_rows: 50,
    truncated: true,
  },
  headline: {
    verdict: "Verdict: YES — LLM bidders DID rediscover truthful bidding.",
    tone: "ok",
  },
};

// exp002 — no results/ dir at all.
export const DETAIL_EMPTY_FIXTURE: ExperimentDetail = {
  id: "exp002_loop_v0_robustness",
  title: "exp002 loop v0 robustness",
  has_results_dir: false,
  has_summary_json: false,
  has_summary_md: false,
  has_per_round: false,
  has_trials: false,
  n_results_files: 0,
  summary_json: null,
  summary_md: null,
  per_round: null,
  trials: null,
  headline: null,
};
