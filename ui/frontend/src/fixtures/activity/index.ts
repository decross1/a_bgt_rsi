// PAGE A fixtures. The graph fixture mirrors what backend/activity.py
// emits flattening build_chain trees; the monitor fixture includes the
// synthetic_inference block (with its `synthetic: true` marker) so the
// component tests can assert the not-measured marker renders.
import type {
  ActiveRun,
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

// Live calls: monitor available, NO active workers and (with initialIteration
// null) no loop iteration — but the call log shows recent wrapper activity
// (e.g. a raw experiment driver calling nara.run_iteration directly). The hero
// must light up via the live-calls banner rather than read "idle".
export const MONITOR_FIXTURE_LIVE_CALLS: MonitorResponse = {
  available: true,
  telemetry_available: true,
  generated_at: "2026-06-05T22:57:10Z",
  last_activity_at: "2026-05-23T05:16:14.0Z",
  active: [],
  recent: [],
  live_calls: {
    active: true,
    count: 53,
    window_s: 15,
    calls_per_s: 3.53,
    last_call_at: "2026-06-05T22:57:06.4Z",
    caller_tags: [{ tag: "nara.run_iteration", count: 53 }],
    model: "fake-model",
  },
  synthetic_inference: MONITOR_FIXTURE.synthetic_inference,
};

// REAL inference internals: worker_activity.jsonl had recent rows, so the
// monitor's synthetic_inference is `synthetic: false` and carries measured
// per-worker tok/s + tokens. The SyntheticInferencePanel must render this
// WITHOUT the amber synthetic marker (the flag is load-bearing).
export const MONITOR_FIXTURE_REAL_INFERENCE: MonitorResponse = {
  available: true,
  telemetry_available: true,
  generated_at: "2026-06-08T06:11:30Z",
  last_activity_at: "2026-06-08T06:11:28.6Z",
  active: [],
  recent: [],
  synthetic_inference: {
    synthetic: false,
    source: "worker_activity.jsonl",
    workers: [
      {
        task_id: "t/a",
        run_id: "exp-9",
        tokens_generated: 220,
        tokens_target: 512,
        tok_per_s: 44.0,
        eta_s: 6.6,
      },
    ],
  },
};

// REAL inference internals with a null eta_s — the producer writes eta_s=null
// when tok_per_s is 0 (no rate to divide by). The live panel must render a bare
// dash (no trailing "s", not "n/as") for that worker while staying synthetic:false.
export const MONITOR_FIXTURE_REAL_INFERENCE_NULL_ETA: MonitorResponse = {
  available: true,
  telemetry_available: true,
  generated_at: "2026-06-08T06:12:00Z",
  last_activity_at: "2026-06-08T06:11:58.0Z",
  active: [],
  recent: [],
  synthetic_inference: {
    synthetic: false,
    source: "worker_activity.jsonl",
    workers: [
      {
        task_id: "t/z",
        run_id: "exp-0",
        tokens_generated: 0,
        tokens_target: 512,
        tok_per_s: 0,
        eta_s: null,
      },
    ],
  },
};

// run_state/active_run.json — a run in flight (experiment kind). Drives the
// ActiveRunCard hero + folds into the idle gate / status strip.
export const ACTIVE_RUN_FIXTURE: ActiveRun = {
  run_id: "exp-2026-06-08-001",
  kind: "experiment",
  label: "exp003 paraphrase probe",
  started_at: "2026-06-08T06:00:00Z",
  current_step: "retrieve_literature",
  step_started_at: "2026-06-08T06:01:00Z",
  progress: { done: 3, total: 10, unit: "papers" },
  narration: "scoring candidate seeds against the Slice-2 threshold",
  model: "gemma-4-26b-a4b",
  n_err: 0,
  // An unknown key a later run-driver revision may add — passed through.
  sandbox_id: "sbx-42",
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
