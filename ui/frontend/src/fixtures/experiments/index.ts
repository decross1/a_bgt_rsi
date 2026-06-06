// Page B fixtures covering all three on-disk shapes. Components take an
// `initial` prop so tests bypass the network entirely.
import type {
  ExperimentDetail,
  ExperimentsListResponse,
  ResearchResponse,
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

// exp004 — per_mechanism shape WITH efficiency + revenue columns. All-YES
// verdicts -> ok 'YES on all 3 mechanisms' structured headline.
export const DETAIL_PER_MECHANISM_EFFICIENCY_FIXTURE: ExperimentDetail = {
  id: "exp004_combinatorial_auction",
  title: "exp004 combinatorial auction",
  has_results_dir: true,
  has_summary_json: true,
  has_summary_md: true,
  has_per_round: false,
  has_trials: true,
  n_results_files: 3,
  summary_json: {
    n_trials: 150,
    per_mechanism: [
      {
        mechanism: "first_price",
        truthful_fraction: 0.965,
        mean_efficiency: 0.9988,
        mean_revenue: 82.93,
        parse_failure_rate: 0.0,
        verdict: "YES",
      },
      {
        mechanism: "sequential_second_price",
        truthful_fraction: 0.965,
        mean_efficiency: 0.9771,
        mean_revenue: 61.137,
        parse_failure_rate: 0.0,
        verdict: "YES",
      },
      {
        mechanism: "vcg",
        truthful_fraction: 0.965,
        mean_efficiency: 0.9988,
        mean_revenue: 63.659,
        parse_failure_rate: 0.0,
        verdict: "YES",
      },
    ],
  },
  // BOTH-present shape: the real exp004 dir ships a summary.md alongside the
  // summary.json. This synthetic md carries a verdict that tones the OTHER way
  // (NO) so the no-clobber contract is load-bearing: the structured per_mechanism
  // headline (YES on all 3, ok/emerald) must survive and the markdown verdict
  // must NOT override it. The full prose still renders in its own card below.
  summary_md:
    "# exp004 — combinatorial-auction truthfulness summary\n\n" +
    "**Verdict: NO** — adversarial markdown that would tone red if it won.\n\n" +
    "## Per-mechanism verdicts\n\n" +
    "- first_price: YES\n- sequential_second_price: YES\n- vcg: YES\n",
  per_round: null,
  trials: null,
  headline: {
    verdict: "YES on all 3 mechanisms",
    tone: "ok",
    kind: "per_mechanism",
    n_mechanisms: 3,
    n_yes: 3,
  },
};

// exp005 — per_mechanism shape WITH a signed-residual column (no
// efficiency/revenue). Still all-YES.
export const DETAIL_PER_MECHANISM_RESIDUAL_FIXTURE: ExperimentDetail = {
  id: "exp005_mechanism_aware",
  title: "exp005 mechanism aware",
  has_results_dir: true,
  has_summary_json: true,
  has_summary_md: true,
  has_per_round: false,
  has_trials: true,
  n_results_files: 3,
  summary_json: {
    n_trials: 50,
    per_mechanism: [
      {
        mechanism: "first_price",
        truthful_fraction: 0.9317,
        mean_signed_residual: -1.5647,
        parse_failure_rate: 0.0,
        verdict: "YES",
      },
      {
        mechanism: "sequential_second_price",
        truthful_fraction: 0.9533,
        mean_signed_residual: -1.3116,
        parse_failure_rate: 0.0,
        verdict: "YES",
      },
      {
        mechanism: "vcg",
        truthful_fraction: 0.8083,
        mean_signed_residual: -4.9017,
        parse_failure_rate: 0.0,
        verdict: "YES",
      },
    ],
  },
  summary_md: null,
  per_round: null,
  trials: null,
  headline: {
    verdict: "YES on all 3 mechanisms",
    tone: "ok",
    kind: "per_mechanism",
    n_mechanisms: 3,
    n_yes: 3,
  },
};

// per_mechanism shape with a MIXED YES/NO split (not all-YES). One row is
// missing a metric cell (no truthful_fraction on the NO row) so the dash-not-
// fabricated guarantee for the mechanism table is exercised. Headline tones
// amber (warn) and the NO row's chip reads red.
export const DETAIL_PER_MECHANISM_MIXED_FIXTURE: ExperimentDetail = {
  id: "exp004_combinatorial_auction",
  title: "exp004 combinatorial auction (mixed)",
  has_results_dir: true,
  has_summary_json: true,
  has_summary_md: false,
  has_per_round: false,
  has_trials: true,
  n_results_files: 3,
  summary_json: {
    n_trials: 150,
    per_mechanism: [
      {
        mechanism: "first_price",
        truthful_fraction: 0.965,
        mean_efficiency: 0.9988,
        mean_revenue: 82.93,
        parse_failure_rate: 0.0,
        verdict: "YES",
      },
      {
        // No truthful_fraction here -> the cell must render a dash, not 0/faked.
        mechanism: "vcg",
        mean_efficiency: 0.71,
        mean_revenue: 40.1,
        parse_failure_rate: 0.12,
        verdict: "NO",
      },
    ],
  },
  summary_md: null,
  per_round: null,
  trials: null,
  headline: {
    verdict: "Mixed: YES on 1/2 mechanisms",
    tone: "warn",
    kind: "per_mechanism",
    n_mechanisms: 2,
    n_yes: 1,
  },
};

// per_mechanism shape where EVERY row is NO -> headline tones red (bad).
export const DETAIL_PER_MECHANISM_ALL_NO_FIXTURE: ExperimentDetail = {
  id: "exp004_combinatorial_auction",
  title: "exp004 combinatorial auction (all-no)",
  has_results_dir: true,
  has_summary_json: true,
  has_summary_md: false,
  has_per_round: false,
  has_trials: true,
  n_results_files: 3,
  summary_json: {
    n_trials: 150,
    per_mechanism: [
      {
        mechanism: "first_price",
        truthful_fraction: 0.42,
        mean_efficiency: 0.61,
        mean_revenue: 30.0,
        parse_failure_rate: 0.0,
        verdict: "NO",
      },
      {
        mechanism: "vcg",
        truthful_fraction: 0.38,
        mean_efficiency: 0.55,
        mean_revenue: 28.0,
        parse_failure_rate: 0.0,
        verdict: "NO",
      },
    ],
  },
  summary_md: null,
  per_round: null,
  trials: null,
  headline: {
    verdict: "NO on all 2 mechanisms",
    tone: "bad",
    kind: "per_mechanism",
    n_mechanisms: 2,
    n_yes: 0,
  },
};

// exp006 — FLAT shape: a top-level NO verdict + scalar metrics, no
// per_mechanism rows. The metrics card renders the scalars; the headline reads
// red from the NO token.
export const DETAIL_FLAT_FIXTURE: ExperimentDetail = {
  id: "exp006_mechanism_design",
  title: "exp006 mechanism design",
  has_results_dir: true,
  has_summary_json: true,
  has_summary_md: true,
  has_per_round: false,
  has_trials: true,
  n_results_files: 3,
  summary_json: {
    verdict: "NO",
    n_trials: 40,
    n_errors: 0,
    designer_mean_efficiency: 0.7102,
    feasibility_rate: 0.525,
    matches_vcg_rate: 0.375,
    n_feasible: 21,
    n_matches_vcg: 15,
    parse_failures: 13,
    efficiency_threshold: 0.9,
    feasibility_threshold: 0.9,
    feasibility_floor: 0.5,
  },
  // BOTH-present shape: the real exp006 dir ships a summary.md alongside the
  // summary.json. This synthetic md carries a verdict that tones the OTHER way
  // (YES) so the no-clobber contract is load-bearing: the structured flat
  // headline (NO, bad/red) must survive and the markdown verdict must NOT flip
  // it green. The full prose still renders in its own card below.
  summary_md:
    "# exp006 — semi-synthetic mechanism-DESIGN summary\n\n" +
    "**Verdict: YES** — adversarial markdown that would tone green if it won.\n\n" +
    "## Headline metrics\n\n" +
    "- designer mean efficiency: 0.710\n- feasibility_rate: 52.5%\n",
  per_round: null,
  trials: null,
  headline: {
    verdict: "NO",
    tone: "bad",
    kind: "flat",
  },
};

// ─── Research page (GET /api/research) — tier-grouped index ──────────
// Covers all three tiers: a synthetic experiment WITH a bridge and a YES
// verdict; a synthetic experiment with a NO verdict + empty bridge; a
// semi_synthetic experiment (exp006) with a bridge; an applied design-only
// entry (no results, null verdict, no bridge); plus an untiered dir.
export const RESEARCH_FIXTURE: ResearchResponse = {
  available: true,
  tiers: [
    {
      tier: "synthetic",
      label: "Synthetic",
      description:
        "Classical games with known equilibria — success is cleanly measurable.",
      experiments: [
        {
          id: "exp003_vickrey_rediscovery",
          title: "exp003 vickrey rediscovery",
          has_results_dir: true,
          has_summary_json: false,
          has_summary_md: true,
          has_per_round: false,
          has_trials: true,
          n_results_files: 3,
          verdict: { text: "Verdict: YES", tone: "ok" },
          bridge: [
            {
              iteration_id: "iter-2026-05-27-028",
              metric: "truthful_bid_fraction",
              value: 1.0,
              trials: 50,
            },
          ],
        },
        {
          // A NO verdict with NO bridge yet — exercises the red chip + the
          // "not yet bridged into the loop" empty-bridge state.
          id: "exp001_repeated_pd",
          title: "exp001 repeated pd",
          has_results_dir: true,
          has_summary_json: true,
          has_summary_md: false,
          has_per_round: true,
          has_trials: false,
          n_results_files: 7,
          verdict: {
            text: "EXPLOITED by all_d: opponent mean payoff 2.50 vs LLM 0.75",
            tone: "bad",
          },
          bridge: [],
        },
      ],
    },
    {
      tier: "semi_synthetic",
      label: "Semi-synthetic",
      description:
        "LLM-as-designer scenarios scored against a benchmark (e.g. VCG).",
      experiments: [
        {
          id: "exp006_mechanism_design",
          title: "exp006 mechanism design",
          has_results_dir: true,
          has_summary_json: true,
          has_summary_md: true,
          has_per_round: false,
          has_trials: true,
          n_results_files: 3,
          verdict: { text: "NO", tone: "bad" },
          bridge: [
            {
              iteration_id: "iter-2026-06-05-006",
              metric: "designer_mean_efficiency",
              value: 0.71,
              trials: 40,
            },
          ],
        },
      ],
    },
    {
      tier: "applied",
      label: "Applied",
      description:
        "Design-only paper forecasting — CFTC-gated, not run (no live trading).",
      experiments: [
        {
          // Design-only: results dir present but EMPTY (.gitkeep only — the
          // real on-disk state), so no summary, null verdict, no bridge.
          id: "exp007_polymarket",
          title: "exp007 polymarket",
          has_results_dir: true,
          has_summary_json: false,
          has_summary_md: false,
          has_per_round: false,
          has_trials: false,
          n_results_files: 0,
          verdict: null,
          bridge: [],
        },
      ],
    },
  ],
  untiered: [
    {
      id: "exp002_loop_v0_robustness",
      title: "exp002 loop v0 robustness",
      has_results_dir: false,
      has_summary_json: false,
      has_summary_md: false,
      has_per_round: false,
      has_trials: false,
      n_results_files: 0,
      verdict: null,
      bridge: [],
    },
  ],
};

export const RESEARCH_UNAVAILABLE: ResearchResponse = {
  available: false,
  reason: "experiments dir absent",
  tiers: [],
  untiered: [],
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
