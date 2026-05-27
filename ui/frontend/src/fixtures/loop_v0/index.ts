// Hand-rolled fixtures the LOOP_V0 panels build against until the primary
// session has shipped run_state/active_iteration.json,
// memory/loop_memory.jsonl, and journal/iterations/NNN.md. See
// agent/prompts/ui_session.md "Shared contract" for the schemas.
import type {
  ActiveIteration,
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

export const JOURNAL_FIXTURE_001 = `# Iteration iter-2026-05-26-001

- **Topic**: Tit-for-Tat dominance in repeated PD
- **Novelty**: rediscovery
- **Critique**: restated

## Hypothesis

TfT remains the most robust strategy in noisy repeated PD.
`;
