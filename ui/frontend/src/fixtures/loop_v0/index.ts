// Hand-rolled fixtures the LOOP_V0 panels build against until the primary
// session has shipped run_state/active_iteration.json,
// memory/loop_memory.jsonl, and journal/iterations/NNN.md. See
// agent/prompts/ui_session.md "Shared contract" for the schemas.
import type {
  ActiveIteration,
  IterationRecord,
} from "../../types/schemas";

export const ACTIVE_FIXTURE: ActiveIteration = {
  iteration_id: "iter-2026-05-26-001",
  topic: "Tit-for-Tat dominance in repeated PD",
  started_at: "2026-05-26T14:00:00Z",
  current_step: "query_chroma",
  step_started_at: "2026-05-26T14:00:08Z",
  latest_narration: "Nara: querying Chroma for prior literature on Tit-for-Tat dominance.",
  tool_calls_so_far: [
    {
      tool: "summarize_paper",
      started_at: "2026-05-26T14:00:01Z",
      ended_at: "2026-05-26T14:00:07Z",
      status: "passed",
    },
    {
      tool: "query_chroma",
      started_at: "2026-05-26T14:00:08Z",
      status: "in_progress",
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
