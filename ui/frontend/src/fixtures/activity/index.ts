// Activity-graph fixtures (the /graph page + ActivityGraph suites). Mirrors
// what backend/activity.py emits flattening build_chain trees. The old
// monitor / single-slot active-run fixtures died with the /activity page and
// its suites in UI simplification S3.
import type { ActivityGraphResponse } from "../../types/activity";

export const GRAPH_FIXTURE: ActivityGraphResponse = {
  available: true,
  task_count: 2,
  generated_at: "2026-06-05T00:40:00Z",
  nodes: [
    {
      id: "root-1",
      kind: "dispatch",
      label: "summarize_paper",
      task_id: "seq-1",
      request_id: "root-1",
      status: "active",
    },
    {
      id: "call-a",
      kind: "call",
      label: "summarize_paper/llm",
      task_id: "seq-1",
      request_id: "call-a",
      status: "ok",
    },
    {
      // Synthesized tool node — no real request_id, must NOT deep-link.
      id: "call-a::get_payoff_matrix::2",
      kind: "tool",
      label: "get_payoff_matrix",
      task_id: "seq-1",
      request_id: null,
      status: "ok",
    },
    {
      id: "root-2",
      kind: "dispatch",
      label: "play_pd_match",
      task_id: "seq-2",
      request_id: "root-2",
      status: "ok",
    },
  ],
  edges: [
    { id: "root-1->call-a", source: "root-1", target: "call-a" },
    {
      id: "call-a->call-a::get_payoff_matrix::2",
      source: "call-a",
      target: "call-a::get_payoff_matrix::2",
    },
  ],
};

export const GRAPH_FIXTURE_UNAVAILABLE: ActivityGraphResponse = {
  available: false,
  reason: "orchestrator.jsonl absent",
  nodes: [],
  edges: [],
  generated_at: "2026-06-05T00:40:00Z",
};
