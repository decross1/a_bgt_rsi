// PAGE A fixtures. The graph fixture mirrors what backend/activity.py
// emits flattening build_chain trees; the monitor fixture includes the
// synthetic_inference block (with its `synthetic: true` marker) so the
// component tests can assert the not-measured marker renders.
import type {
  ActivityGraphResponse,
  MonitorResponse,
} from "../../types/activity";

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

export const MONITOR_FIXTURE: MonitorResponse = {
  available: true,
  telemetry_available: true,
  generated_at: "2026-06-05T00:40:00Z",
  last_activity_at: "2026-05-23T05:16:14.0Z",
  active: [
    {
      task_id: "seq-1",
      task_type: "summarize_paper",
      status: "running",
      worker_pid: 4242,
      timestamp: "2026-05-23T05:15:43.5Z",
      stage: "worker_invocation",
      detail: "spawning worker process for 2605.21448 (timeout 60s)",
      cpu_pct: 12.5,
      rss_mb: 660.2,
    },
  ],
  recent: [
    {
      task_id: "seq-1",
      task_type: "summarize_paper",
      status: "running",
      worker_pid: 4242,
      timestamp: "2026-05-23T05:15:43.5Z",
      stage: "worker_invocation",
      detail: "spawning worker process for 2605.21448 (timeout 60s)",
      cpu_pct: 12.5,
      rss_mb: 660.2,
    },
    {
      task_id: "seq-2",
      task_type: "play_pd_match",
      status: "passed",
      worker_pid: 4343,
      timestamp: "2026-05-23T05:16:14.0Z",
      stage: "orchestrator_receipt",
      detail: "worker returned summary (747 chars)",
      cpu_pct: null,
      rss_mb: null,
    },
  ],
  synthetic_inference: {
    synthetic: true,
    source: "fixture",
    needs: "worker_activity.jsonl (primary-session)",
    note: "decode-step / tokens-generated / ETA are NOT measured — placeholder.",
    workers: [
      {
        task_id: "seq-1",
        decode_step: 312,
        tokens_generated: 312,
        tokens_target: 512,
        eta_s: 4.7,
        tok_per_s: 42.0,
      },
    ],
  },
};

export const MONITOR_FIXTURE_UNAVAILABLE: MonitorResponse = {
  available: false,
  reason: "orchestrator.jsonl absent",
  active: [],
  recent: [],
  synthetic_inference: MONITOR_FIXTURE.synthetic_inference,
  generated_at: "2026-06-05T00:40:00Z",
};

// Idle: monitor is available but no workers are in flight. recent[] carries
// the just-finished task so `last_activity_at` drives the idle empty-state's
// "last activity … ago".
export const MONITOR_FIXTURE_IDLE: MonitorResponse = {
  available: true,
  telemetry_available: true,
  generated_at: "2026-06-05T00:40:00Z",
  last_activity_at: "2026-05-23T05:16:14.0Z",
  active: [],
  recent: [
    {
      task_id: "seq-2",
      task_type: "play_pd_match",
      status: "passed",
      worker_pid: 4343,
      timestamp: "2026-05-23T05:16:14.0Z",
      stage: "orchestrator_receipt",
      detail: "worker returned summary (747 chars)",
      cpu_pct: null,
      rss_mb: null,
    },
  ],
  synthetic_inference: MONITOR_FIXTURE.synthetic_inference,
};
