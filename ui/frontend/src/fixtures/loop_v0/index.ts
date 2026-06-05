// Hand-rolled fixtures the LOOP_V0 panels build against until the primary
// session has shipped run_state/active_iteration.json,
// memory/loop_memory.jsonl, and journal/iterations/NNN.md. See
// agent/prompts/ui_session.md "Shared contract" for the schemas.
import type {
  ActiveIteration,
  Exp004Summary,
  IterationRecord,
} from "../../types/schemas";

// Uniform case: every tool inherits the orchestrator backend. The
// divergence-only per-tool chip MUST stay hidden here.
export const ACTIVE_FIXTURE: ActiveIteration = {
  iteration_id: "iter-2026-05-26-001",
  topic: "Tit-for-Tat dominance in repeated PD",
  started_at: "2026-05-26T14:00:00Z",
  current_step: "query_chroma",
  step_started_at: "2026-05-26T14:00:08Z",
  latest_narration: "Nara: querying Chroma for prior literature on Tit-for-Tat dominance.",
  orchestrator_backend: "vllm-gemma",
  orchestrator_model: "gemma-4-26b-a4b",
  tool_calls_so_far: [
    {
      tool: "summarize_paper",
      started_at: "2026-05-26T14:00:01Z",
      ended_at: "2026-05-26T14:00:07Z",
      status: "passed",
      backend: "vllm-gemma",
      model: "gemma-4-26b-a4b",
    },
    {
      tool: "query_chroma",
      started_at: "2026-05-26T14:00:08Z",
      status: "in_progress",
      backend: "vllm-gemma",
      model: "gemma-4-26b-a4b",
    },
  ],
};

// Divergence case: orchestrator is on vllm-gemma, but critic_loop_v0's
// SubAgent has been flipped to a separate backend (Phase 3 / Co-Scientist
// insight — D-035). This is the variant the per-tool divergence chip and
// the prominent subagent chip must surface. Used by the divergence-render
// test.
export const ACTIVE_FIXTURE_DIVERGENT: ActiveIteration = {
  iteration_id: "iter-2026-05-27-002",
  topic: "Strategy switching cost in noisy repeated PD",
  started_at: "2026-05-27T18:30:00Z",
  current_step: "critic_loop_v0",
  step_started_at: "2026-05-27T18:30:22Z",
  latest_narration:
    "Nara: handing the hypothesis to the Qwen critic for an independent falsification pass.",
  orchestrator_backend: "vllm-gemma",
  orchestrator_model: "gemma-4-26b-a4b",
  tool_calls_so_far: [
    {
      tool: "hypothesize",
      started_at: "2026-05-27T18:30:01Z",
      ended_at: "2026-05-27T18:30:11Z",
      status: "passed",
      backend: "vllm-gemma",
      model: "gemma-4-26b-a4b",
    },
    {
      tool: "retrieve_literature",
      started_at: "2026-05-27T18:30:11Z",
      ended_at: "2026-05-27T18:30:14Z",
      status: "passed",
      backend: null,
      model: null,
    },
    {
      tool: "novelty_classify",
      started_at: "2026-05-27T18:30:14Z",
      ended_at: "2026-05-27T18:30:21Z",
      status: "passed",
      backend: "vllm-gemma",
      model: "gemma-4-26b-a4b",
    },
    {
      tool: "critic_loop_v0",
      started_at: "2026-05-27T18:30:22Z",
      status: "in_progress",
      backend: "vllm-gemma",
      model: "gemma-4-26b-a4b",
      // The sub-agent is on a different backend than the orchestrator —
      // this is the Phase 3 critic-flip surface.
      subagent_backend: "ollama-coder",
      subagent_model: "qwen3.6-27b-nvfp4-mtp",
    },
  ],
};

export const ITERATIONS_FIXTURE: IterationRecord[] = [
  {
    iteration_id: "iter-2026-05-26-001",
    started_at: "2026-05-26T14:00:00Z",
    ended_at: "2026-05-26T14:02:14Z",
    seed: { topic: "Tit-for-Tat dominance in repeated PD", source: "human" },
    novelty: { class: "rediscovery", top_neighbor_id: "axelrod1984" },
    critique: { verdict: "restated" },
    journal_entry_path: "journal/iterations/001.md",
    nara_summary:
      "Nara: TfT dominance shows up in foundational literature; this is a rediscovery.",
  },
  {
    iteration_id: "iter-2026-05-25-002",
    started_at: "2026-05-25T19:14:00Z",
    ended_at: "2026-05-25T19:16:48Z",
    seed: {
      topic: "Behavioral deviation from Nash in p-beauty contests",
      source: "human",
    },
    novelty: { class: "novel", top_neighbor_id: "nagel1995" },
    critique: { verdict: "survives" },
    journal_entry_path: "journal/iterations/002.md",
    nara_summary:
      "Nara: candidate refinement of level-k convergence rates; worth a real run.",
  },
  {
    iteration_id: "iter-2026-05-24-003",
    started_at: "2026-05-24T11:02:00Z",
    ended_at: "2026-05-24T11:03:31Z",
    seed: { topic: "asdfgh", source: "human" },
    novelty: { class: "nonsense", top_neighbor_id: null },
    critique: { verdict: "malformed" },
    journal_entry_path: "journal/iterations/003.md",
    nara_summary: "Nara: topic is unparseable; skipping further analysis.",
  },
];

// Loop v1 rows: carry meta_review.conditioning_bullets, a redteam block,
// and gate_status. Row 1 is a clean pass (proceed / 0 retries / valid);
// row 2 exercises the highlight paths (fatal_flaw, retries_used > 0,
// needs_revision gate) the panel must call out.
export const ITERATIONS_FIXTURE_V1: IterationRecord[] = [
  {
    iteration_id: "iter-2026-06-04-001",
    started_at: "2026-06-04T09:00:00Z",
    ended_at: "2026-06-04T09:03:10Z",
    seed: { topic: "Truthfulness of VCG in combinatorial auctions", source: "human" },
    novelty: { class: "rediscovery", top_neighbor_id: "vickrey1961" },
    critique: { verdict: "restated" },
    meta_review: {
      conditioning_bullets: [
        "Prior iter-2026-05-26-001 found TfT dominance is a rediscovery.",
        "exp004 showed VCG elicits 96.5% truthful bids — lean on that bridge.",
      ],
      rows_considered: 3,
    },
    redteam: { verdict: "proceed", retries_used: 0, confidence: 0.82 },
    gate_status: "valid",
    journal_entry_path: "journal/iterations/004.md",
    nara_summary:
      "Nara: VCG truthfulness is foundational; this iteration is a rediscovery.",
  },
  {
    iteration_id: "iter-2026-06-04-002",
    started_at: "2026-06-04T10:00:00Z",
    ended_at: "2026-06-04T10:05:42Z",
    seed: {
      topic: "Sequential second-price beats VCG on revenue",
      source: "human",
    },
    novelty: { class: "novel", top_neighbor_id: "krishna2009" },
    critique: { verdict: "falsified" },
    meta_review: {
      conditioning_bullets: [
        "exp004 mean_revenue: VCG 63.7 vs sequential 61.1 — revenue claim is shaky.",
      ],
      rows_considered: 4,
    },
    redteam: {
      verdict: "fatal_flaw",
      critique: "Revenue ranking reversed under the measured efficiencies.",
      retries_used: 2,
      confidence: 0.91,
    },
    gate_status: "needs_revision",
    journal_entry_path: "journal/iterations/005.md",
    nara_summary:
      "Nara: the revenue-superiority claim does not hold against exp004's numbers.",
  },
];

// Active record carrying Loop v1 blocks in flight (meta_review computed at
// start; redteam mid-loop with a retry; gate pending). Drives the active
// panel's v1-render test.
export const ACTIVE_FIXTURE_V1: ActiveIteration = {
  iteration_id: "iter-2026-06-04-003",
  topic: "Efficiency loss in first-price combinatorial auctions",
  started_at: "2026-06-04T11:00:00Z",
  current_step: "critic_loop_v0",
  step_started_at: "2026-06-04T11:00:30Z",
  latest_narration:
    "Nara: running the red-team critic on the efficiency-loss hypothesis.",
  orchestrator_backend: "vllm-gemma",
  orchestrator_model: "gemma-4-26b-a4b",
  meta_review: {
    conditioning_bullets: [
      "exp004 first_price efficiency 99.9% — efficiency-loss premise may be weak.",
    ],
    rows_considered: 5,
  },
  redteam: { verdict: "fatal_flaw", retries_used: 1, confidence: 0.78 },
  gate_status: "pending",
  tool_calls_so_far: [
    {
      tool: "hypothesize",
      started_at: "2026-06-04T11:00:01Z",
      ended_at: "2026-06-04T11:00:12Z",
      status: "passed",
      backend: "vllm-gemma",
      model: "gemma-4-26b-a4b",
    },
    {
      tool: "critic_loop_v0",
      started_at: "2026-06-04T11:00:30Z",
      status: "in_progress",
      backend: "vllm-gemma",
      model: "gemma-4-26b-a4b",
    },
  ],
};

export const EXP004_FIXTURE: Exp004Summary = {
  available: true,
  n_trials: 150,
  per_mechanism: [
    {
      mechanism: "first_price",
      truthful_fraction: 0.965,
      mean_efficiency: 0.9988418692882004,
      mean_revenue: 82.93,
      parse_failure_rate: 0.0,
      verdict: "YES",
    },
    {
      mechanism: "sequential_second_price",
      truthful_fraction: 0.965,
      mean_efficiency: 0.977107591738275,
      mean_revenue: 61.137,
      parse_failure_rate: 0.0,
      verdict: "YES",
    },
    {
      mechanism: "vcg",
      truthful_fraction: 0.965,
      mean_efficiency: 0.9988418692882004,
      mean_revenue: 63.65886666666667,
      parse_failure_rate: 0.0,
      verdict: "YES",
    },
  ],
};

export const EXP004_FIXTURE_EMPTY: Exp004Summary = {
  available: false,
  per_mechanism: [],
  n_trials: null,
};

export const JOURNAL_FIXTURE_001 = `# Iteration iter-2026-05-26-001

- **Topic**: Tit-for-Tat dominance in repeated PD
- **Novelty**: rediscovery
- **Critique**: restated

## Hypothesis

TfT remains the most robust strategy in noisy repeated PD.
`;
