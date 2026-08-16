// VALIDATE-AGAINST-REAL-DATA: every top-level route must render in jsdom
// without a single console.error / console.warn — the cheap stand-in for
// "renders without browser console errors" (no headless browser exists here).
// This catches React key warnings, act() warnings, and outright crashes that
// the per-component tests, rendering one happy-path fixture at a time, miss.
//
// The data fed here is the LIVE on-disk state (snapshotted 2026-06-09), not a
// hand-tuned happy path:
//   - coordinator_cycles.jsonl: 13 real rows, ALL topic_source="arxiv_pick",
//     agent="coordinator"; TWO rows carry an `errored` outcome (RuntimeError:
//     boom) that MUST render as an explicit red row; several rows carry an
//     EMPTY outcomes:[] (planned-but-not-executed); ZERO carry a
//     dispatched_iteration_id. The shapes below are verbatim real rows.
//   - loop_memory.jsonl: the ONE row currently carrying retrieval.relevance
//     (relevance 1.0, low_confidence:false) — a novel/survives verdict that is
//     NOT low-evidence-flagged (correct: on-domain). novelty/critique also carry
//     low_confidence:false (present in the real row). Plus a human_cli row and a
//     loop_memory_probe row for the seed.source spread (33/15/1 live).
//   - the human-todo queue: sources absent on disk -> empty queue (the calm
//     state); the registry poll returns no live runs.
//
// Each route fetches through the api/http (+ api/activity, api/experiments)
// helpers and the telemetry hook; those modules are mocked to hand back the
// real data, so the render path under test is the production one.
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  CoordinatorCycle,
  IterationRecord,
  TelemetrySample,
  VllmSample,
} from "../src/types/schemas";
import type {
  ActivityGraphResponse,
  MonitorResponse,
} from "../src/types/activity";
import type { ResearchResponse } from "../src/types/experiments";

// ─── REAL DATA (verbatim shapes from the live on-disk files) ───────────────
//
// Wrapped in vi.hoisted so the data is available BOTH to the vi.mock factories
// (which vitest hoists above the module body) and to the test assertions. This
// is the vitest-sanctioned way to share fixtures with a hoisted mock factory —
// the test_dashboard.tsx neighbor uses `await import(fixtureModule)` inside the
// factory; we keep the real data inline (it is verbatim on-disk rows, not a
// shared fixture module this session owns) and hoist it the same height.
const D = vi.hoisted(() => {
  // Three verbatim rows from run_state/coordinator_cycles.jsonl spanning the
  // live variety: (a) an `errored` row (noop -> "RuntimeError: boom"); (b) an
  // `executed` row, all outcomes passed; (c) a `planned` row with outcomes:[]
  // (empty — no per-action outcomes). All arxiv_pick, all agent=coordinator,
  // none with dispatched_iteration_id — exactly the live distribution.
  const REAL_CYCLES = [
    {
      timestamp: "2026-06-09T07:19:25.392025Z",
      run_id: "coordinator_27629ba6",
      agent: "coordinator",
      topic: "FASE: Fast Adaptive Semantic Entropy for Code Quality",
      topic_source: "arxiv_pick",
      status: "executed",
      plan: [{ action: "noop", args: { reason: "x" } }],
      outcomes: [
        { action: "noop", status: "errored", error: "RuntimeError: boom" },
      ],
      promoted_finding_ids: [],
      bubble_run_ids: [],
    },
    {
      timestamp: "2026-06-09T07:17:53.389914Z",
      run_id: "coordinator_1a11f5e9",
      agent: "coordinator",
      topic: "noisy PD",
      topic_source: "arxiv_pick",
      status: "executed",
      plan: [
        { action: "run_loop_iteration", args: { topic: "noisy PD" } },
        { action: "promote_findings", args: { max_candidates: 2 } },
        { action: "noop", args: { reason: "done" } },
      ],
      outcomes: [
        { action: "run_loop_iteration", status: "passed" },
        { action: "promote_findings", status: "passed" },
        { action: "noop", status: "passed" },
      ],
      promoted_finding_ids: [],
      bubble_run_ids: [],
    },
    {
      timestamp: "2026-06-09T07:17:53.375723Z",
      run_id: "coordinator_df4eecc8",
      agent: "coordinator",
      topic: "noisy PD",
      topic_source: "arxiv_pick",
      status: "planned",
      plan: [
        { action: "run_loop_iteration", args: { topic: "noisy PD" } },
        {
          action: "bubble_up",
          args: { finding_ids: ["sf-iter-2026-06-05-099"], note: "look" },
        },
      ],
      // The live "planned but not executed" shape: an empty outcomes array. The
      // Activity failed-dispatch derivation and the cycle card must both tolerate
      // it without a crash or a spurious row.
      outcomes: [],
      promoted_finding_ids: [],
      bubble_run_ids: ["coordinator_df4eecc8"],
    },
  ] as CoordinatorCycle[];

  // The ONE live loop_memory.jsonl row carrying retrieval.relevance, trimmed to
  // the fields the UI reads (neighbors elided — the badge keys on relevance +
  // low_confidence, not the neighbor list). novel/survives with low_confidence
  // FALSE everywhere: the low-evidence badge correctly does NOT fire here. Plus
  // a human_cli row and a loop_memory_probe row for the seed.source spread.
  const REAL_ITERATIONS = [
    {
      iteration_id: "iter-2026-06-09-002",
      started_at: "2026-06-09T05:58:00.000000Z",
      ended_at: "2026-06-09T05:59:10.000000Z",
      seed: {
        topic: "FASE: Fast Adaptive Semantic Entropy for Code Quality",
        source: "human_cli",
      },
      retrieval: {
        k: 10,
        relevance: {
          relevance: 1.0,
          low_confidence: false,
          reason:
            "on-domain retrieval: mean top-3 lexical overlap 0.208 >= 0.05, max cosine 0.656.",
        },
      },
      novelty: {
        class: "novel",
        top_neighbor_id: "2606.09800",
        low_confidence: false,
      },
      critique: { verdict: "survives", low_confidence: false },
      journal_entry_path: "journal/iterations/065.md",
      nara_summary:
        "Nara: cross-disciplinary direction; novel and survives on on-domain retrieval.",
    },
    {
      iteration_id: "iter-2026-06-08-031",
      started_at: "2026-06-08T20:10:00.000000Z",
      ended_at: "2026-06-08T20:12:30.000000Z",
      seed: { topic: "p-beauty contest level-k", source: "human_cli" },
      novelty: { class: "rediscovery", top_neighbor_id: "nagel1995" },
      critique: { verdict: "restated" },
      journal_entry_path: "journal/iterations/031.md",
      nara_summary: "Nara: rediscovery of level-k convergence.",
    },
    {
      iteration_id: "iter-2026-06-07-015",
      started_at: "2026-06-07T14:00:00.000000Z",
      ended_at: "2026-06-07T14:02:00.000000Z",
      seed: { topic: "self-probe of loop memory", source: "loop_memory_probe" },
      novelty: { class: "unclear" },
      critique: { verdict: "malformed" },
      journal_entry_path: "journal/iterations/015.md",
    },
  ] as IterationRecord[];

  // A faithful /api/research snapshot: 3 tiers (synthetic / semi_synthetic /
  // applied) + 2 untiered, the live tier ids, with a real bad-verdict and a
  // design-only applied entry. Enough variety to walk every Experiments branch.
  const REAL_RESEARCH = {
    available: true,
    tiers: [
      {
        tier: "synthetic",
        label: "Synthetic",
        description: "Fully synthetic sandboxes.",
        experiments: [
          {
            id: "exp001_repeated_pd",
            title: "exp001 repeated pd",
            has_results_dir: true,
            has_summary_json: true,
            has_summary_md: false,
            has_per_round: true,
            has_trials: false,
            n_results_files: 8,
            verdict: {
              text: "EXPLOITED by all_d: opponent mean payoff 2.08 vs LLM 0.88",
              tone: "bad",
            },
            bridge: [],
          },
        ],
      },
      {
        tier: "semi_synthetic",
        label: "Semi-synthetic",
        description: "Semi-synthetic sandboxes.",
        experiments: [
          {
            id: "exp004_combinatorial_auction",
            title: "exp004 combinatorial auction",
            has_results_dir: true,
            has_summary_json: true,
            has_summary_md: false,
            has_per_round: false,
            has_trials: false,
            n_results_files: 3,
            verdict: { text: "VCG truthful_fraction 0.965", tone: "ok" },
            bridge: [
              {
                iteration_id: "iter-2026-06-05-040",
                metric: "truthful_fraction",
                value: 0.965,
              },
            ],
          },
        ],
      },
      {
        tier: "applied",
        label: "Applied",
        description: "Applied / real-world (CFTC-gated, design-only).",
        experiments: [
          {
            id: "exp007_polymarket",
            title: "exp007 polymarket",
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
      },
    ],
    untiered: [
      {
        id: "exp_misc_a",
        title: "exp misc a",
        has_results_dir: true,
        has_summary_json: false,
        has_summary_md: true,
        has_per_round: false,
        has_trials: false,
        n_results_files: 1,
        verdict: { text: "see summary.md", tone: "warn" },
        bridge: [],
      },
      {
        id: "exp_misc_b",
        title: "exp misc b",
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
  } as ResearchResponse;

  // Telemetry: two samples carrying a vllm block (Gemma up). Mirrors the live
  // stream the Dashboard hero + strip + panels consume.
  const vllmSample = (): VllmSample => ({
    running_requests: 1,
    waiting_requests: 0,
    gpu_cache_usage_pct: 12,
    gpu_prefix_cache_hit_rate: 0.8,
    tokens_per_sec_decode: 42,
    mtp_acceptance_rate: 0.6,
    mtp_draft_tokens: 100,
    mtp_accepted_tokens: 60,
  });
  const telemetrySamples = (): TelemetrySample[] => {
    const s = {
      timestamp: new Date().toISOString(),
      gpu: {
        util_pct: 10,
        mem_used_mb: null,
        mem_total_mb: null,
        temp_c: 41,
        power_w: 5.5,
      },
      host: {
        cpu_pct: 10,
        mem_used_mb: 5000,
        cpu_temp_c: 44,
        load_avg: [1, 1, 1],
      },
      vllm: vllmSample(),
      vllm_qwen: null,
      processes: [],
      read_errors: null,
    } as unknown as TelemetrySample;
    return [s, { ...s, timestamp: new Date().toISOString() }];
  };

  // The live activity monitor: available, nothing in flight (idle), with the
  // synthetic-inference fixture block the panel always carries.
  const REAL_MONITOR = {
    available: true,
    telemetry_available: true,
    active: [],
    recent: [],
    last_activity_at: "2026-06-09T07:19:25.392025Z",
    live_calls: {
      active: false,
      count: 0,
      window_s: 60,
      calls_per_s: null,
      last_call_at: null,
      caller_tags: [],
      model: null,
    },
    synthetic_inference: {
      synthetic: true,
      source: "fixture",
      needs: "worker_activity.jsonl",
      note: "synthetic placeholder",
      workers: [],
    },
    generated_at: "2026-06-09T07:20:00.000000Z",
  } as MonitorResponse;

  const REAL_GRAPH = {
    available: true,
    nodes: [],
    edges: [],
    task_count: 0,
    detail: "overview",
    generated_at: "2026-06-09T07:20:00.000000Z",
  } as ActivityGraphResponse;

  return {
    REAL_CYCLES,
    REAL_ITERATIONS,
    REAL_RESEARCH,
    REAL_MONITOR,
    REAL_GRAPH,
    telemetrySamples,
  };
});

// ─── module mocks: hand the real data back through the production fetchers ──

vi.mock("../src/hooks/useTelemetryStream", () => ({
  useTelemetryStream: () => ({
    samples: D.telemetrySamples(),
    latest: D.telemetrySamples()[1],
    connected: true,
  }),
}));

vi.mock("../src/api/http", () => ({
  getHealth: vi.fn().mockResolvedValue({
    ok: true,
    hostname: "spark",
    telemetry_last_seen: new Date().toISOString(),
    version: "test",
  }),
  getIterations: vi.fn().mockResolvedValue({ iterations: D.REAL_ITERATIONS }),
  getJournalEntry: vi.fn().mockResolvedValue({
    iteration_id: "iter-2026-06-09-002",
    path: "journal/iterations/065.md",
    content: "# Journal\n\nbody",
  }),
  // Live served-model probe (2026-08-16): the card titles read from this,
  // never from a constant.
  getServedModels: vi.fn().mockResolvedValue({
    gemma: { url: "http://localhost:8000", model: "gemma-4-26b-a4b", error: null },
    qwen: { url: "http://localhost:8001", model: "qwen3.6-27b-nvfp4-mtp", error: null },
  }),
  getWorkloadHint: vi.fn().mockResolvedValue({ regime: "idle" }),
  // Coordinator loop: real cycles (the one surviving coordinator endpoint).
  getCoordinatorCycles: vi.fn().mockResolvedValue({ cycles: D.REAL_CYCLES }),
  // HUMAN TODO sources mostly absent on disk -> empty queue (the calm state).
  getHumanTodo: vi.fn().mockResolvedValue({ items: [], counts: {} }),
  startIteration: vi.fn().mockResolvedValue({ pid: 1 }),
  // S1 additions: the NowBoard registry poll (Pulse mounts it live), and the
  // /ladder page's endpoint pair (204-null ledger -> ideas.md fallback body).
  getActiveRuns: vi.fn().mockResolvedValue({ runs: [], skipped: 0 }),
  getLadder: vi.fn().mockResolvedValue(null),
  // The lab's queue (Pulse's secondary zone): a cold checkout answers with
  // gaps and empty ledger lists — the honest "nothing queued" render.
  getLabTodo: vi.fn().mockResolvedValue({
    agent_gaps: [],
    human_gaps: [],
    owed: [],
    agenda: [],
    refine_candidates: [],
    generated_at: "2026-08-15T12:00:00Z",
  }),
  getIdeas: vi
    .fn()
    .mockResolvedValue({ markdown: "# Ideas\n\n## Live work\n\n(none)\n" }),
}));

vi.mock("../src/api/activity", () => ({
  getActivityGraph: vi.fn().mockResolvedValue(D.REAL_GRAPH),
  getActivityMonitor: vi.fn().mockResolvedValue(D.REAL_MONITOR),
}));

vi.mock("../src/api/experiments", () => ({
  getResearch: vi.fn().mockResolvedValue(D.REAL_RESEARCH),
  getExperimentDetail: vi.fn().mockResolvedValue(null),
}));

// Imported AFTER the mocks are declared (vi.mock is hoisted, so the routes
// pick up the mocked modules).
import Cycles from "../src/routes/Cycles";
import Experiments from "../src/routes/Experiments";
import Graph from "../src/routes/Graph";
import Ladder from "../src/routes/Ladder";
import Pulse from "../src/routes/Pulse";
import DossierIndex from "../src/routes/DossierIndex";

// Spy on console.error / console.warn around a render + a full async flush.
// We render inside a MemoryRouter (Experiments uses <Link>); a route that does
// not need it is unaffected. After the polls resolve, NEITHER spy may have
// fired — a key warning, an act() warning, or a thrown render all surface here.
async function renderRouteQuietly(node: React.ReactElement) {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  render(<MemoryRouter>{node}</MemoryRouter>);
  // Let every mocked fetch + its setState settle so async state updates happen
  // inside React's act() scope (an un-awaited update is exactly the warning we
  // are hunting). A trivially-true assertion drives waitFor through the queue.
  await waitFor(() => expect(true).toBe(true));
  // A second tick: panels that fire a follow-up fetch after their first
  // setState (e.g. a poll that schedules the next) flush here too.
  await waitFor(() => expect(true).toBe(true));
  const calls = {
    error: errSpy.mock.calls.map((c) => String(c[0])),
    warn: warnSpy.mock.calls.map((c) => String(c[0])),
  };
  errSpy.mockRestore();
  warnSpy.mockRestore();
  return calls;
}

describe("routes render against real data without console errors", () => {
  beforeEach(() => {
    vi.useRealTimers();
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("Cycles: 13-style real cycles incl. errored + empty-outcomes rows", async () => {
    const { error, warn } = await renderRouteQuietly(
      <Cycles pollMs={1_000_000} />,
    );
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("Experiments: real /api/research + real coordinator cycles", async () => {
    const { error, warn } = await renderRouteQuietly(<Experiments />);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("Graph (S3 thin page): real empty graph renders console-clean", async () => {
    const { error, warn } = await renderRouteQuietly(<Graph />);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("Pulse (S1 home): hero + now-card + owe strip + cycle line + model cards", async () => {
    const { error, warn } = await renderRouteQuietly(<Pulse />);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("Ladder (S1): 204-null ledger -> honest empty + ideas.md fallback", async () => {
    const { error, warn } = await renderRouteQuietly(<Ladder />);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("DossierIndex (S2): empty queue + real iterations render console-clean", async () => {
    const { error, warn } = await renderRouteQuietly(<DossierIndex />);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });
});
