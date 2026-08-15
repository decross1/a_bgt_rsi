// FORWARD-COMPAT (announced-contract) PIN: every top-level route must render
// in jsdom without a single console.error / console.warn when the data carries
// the ADDITIVE contract changes the primary session announced 2026-06-09
// (join contract from 0fdb671 FROZEN — no renames, additions only):
//   - critique.verdict gains "undecidable" (fail-closed; never promotes), plus
//     optional siblings verdict_overridden_from / override_reason /
//     skeptic_verdict (each string|null).
//   - novelty gains OPTIONAL novelty_axes — an OBJECT inside novelty:
//     { phenomenon: known|novel, substrate: studied_llm|unstudied_llm|na,
//       predicted_direction: matches|deviates|silent }. Legacy novelty.class
//     remains (derived).
//   - retrieval.relevance keeps {relevance, low_confidence, reason} and gains
//     OPTIONAL anchor_cosine / curated_overlap / neighbor_spread (float|null),
//     category (off_domain|thin|no_sharp_match|empty|ok), rule_fired
//     (string|null).
// The rows below are INLINE literals (NOT fixtures — shapes unconfirmed until
// the primary's close-out; types/schemas.ts deliberately untouched), cast
// through `unknown` since IterationRecord/CoordinatorCycle do not yet carry
// the new fields. Mixed with normal legacy rows, plus one deliberately
// UNKNOWN-enum row per surface (never-announced verdict/class/category/source
// values + extra unknown keys) — the handoff's bar is "current renders survive
// new rows containing unknown fields/enum values", not just the announced set.
//
// Idiom mirrors tests/test_validate_routes_console.tsx: api modules mocked to
// hand the rows back through the production fetchers; console.error AND
// console.warn spied per route and asserted not-called.
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  Bubble,
  CoordinatorCycle,
  HealthSignal,
  IterationRecord,
  SurfacedFinding,
  TelemetrySample,
} from "../src/types/schemas";
import type {
  ActivityGraphResponse,
  MonitorResponse,
} from "../src/types/activity";
import type { ResearchResponse } from "../src/types/experiments";

// ─── ANNOUNCED-CONTRACT DATA (inline literals, additive over 0fdb671) ───────
//
// vi.hoisted so the rows are visible to the hoisted vi.mock factories AND the
// assertions, exactly like the test_validate_routes_console.tsx neighbor.
const D = vi.hoisted(() => {
  const FC_ITERATIONS = [
    // (a) The FULL announced contract in one row: undecidable verdict with all
    // three override siblings populated, novelty_axes object, and all five new
    // relevance siblings carrying values.
    {
      iteration_id: "iter-2026-06-09-101",
      started_at: "2026-06-09T09:00:00.000000Z",
      ended_at: "2026-06-09T09:02:10.000000Z",
      seed: { topic: "skeptic-gated semantic entropy probe", source: "coordinator" },
      retrieval: {
        k: 10,
        relevance: {
          relevance: 0.31,
          low_confidence: true,
          reason: "no sharp match: max cosine 0.41 under anchor band.",
          anchor_cosine: 0.41,
          curated_overlap: 0.0,
          neighbor_spread: 0.18,
          category: "no_sharp_match",
          rule_fired: "R3_no_sharp_match",
        },
      },
      novelty: {
        class: "novel",
        top_neighbor_id: "2606.01234",
        low_confidence: false,
        novelty_axes: {
          phenomenon: "novel",
          substrate: "unstudied_llm",
          predicted_direction: "silent",
        },
      },
      critique: {
        verdict: "undecidable",
        low_confidence: true,
        verdict_overridden_from: "survives",
        override_reason: "skeptic gate fail-closed: evidence insufficient to promote",
        skeptic_verdict: "refuted",
      },
      journal_entry_path: "journal/iterations/101.md",
      nara_summary: "Nara: skeptic gate held the verdict at undecidable.",
    },
    // (b) The announced contract with every nullable sibling NULL and the
    // benign enum arms: category "ok", axes known/na/matches. An undecidable
    // verdict can arrive with no override having happened.
    {
      iteration_id: "iter-2026-06-09-102",
      started_at: "2026-06-09T09:10:00.000000Z",
      ended_at: "2026-06-09T09:11:45.000000Z",
      seed: { topic: "level-k convergence under noise", source: "human_cli" },
      retrieval: {
        k: 10,
        relevance: {
          relevance: 1.0,
          low_confidence: false,
          reason: "on-domain retrieval: mean top-3 lexical overlap 0.208.",
          anchor_cosine: null,
          curated_overlap: null,
          neighbor_spread: null,
          category: "ok",
          rule_fired: null,
        },
      },
      novelty: {
        class: "rediscovery",
        top_neighbor_id: "nagel1995",
        low_confidence: false,
        novelty_axes: {
          phenomenon: "known",
          substrate: "na",
          predicted_direction: "matches",
        },
      },
      critique: {
        verdict: "undecidable",
        low_confidence: false,
        verdict_overridden_from: null,
        override_reason: null,
        skeptic_verdict: null,
      },
      journal_entry_path: "journal/iterations/102.md",
    },
    // (c) BEYOND the announcement: unknown enum values everywhere + unknown
    // extra keys — including prototype-colliding strings ("toString"), the
    // classic own-key-lookup trap. The render must degrade quietly, not crash.
    {
      iteration_id: "iter-2026-06-09-103",
      started_at: "2026-06-09T09:20:00.000000Z",
      ended_at: "2026-06-09T09:21:00.000000Z",
      seed: { topic: "future seed channel", source: "skeptic_replay" },
      retrieval: {
        k: 10,
        relevance: {
          relevance: 0.5,
          low_confidence: false,
          reason: "x",
          category: "totally_new_bucket",
          rule_fired: "toString",
        },
      },
      novelty: {
        class: "post_hoc_check",
        novelty_axes: { phenomenon: "toString", substrate: "qpu", predicted_direction: "unknown" },
      },
      critique: { verdict: "escalated_to_human", skeptic_verdict: "toString" },
      journal_entry_path: "journal/iterations/103.md",
      skeptic_audit: { rounds: 2, transcript_path: "x.md" },
    },
    // (d) A plain legacy row (pre-announcement shape) — the mix the handoff
    // asks for: new rows land BESIDE old ones in the same append-only file.
    {
      iteration_id: "iter-2026-06-07-015",
      started_at: "2026-06-07T14:00:00.000000Z",
      ended_at: "2026-06-07T14:02:00.000000Z",
      seed: { topic: "self-probe of loop memory", source: "loop_memory_probe" },
      novelty: { class: "unclear" },
      critique: { verdict: "malformed" },
      journal_entry_path: "journal/iterations/015.md",
    },
  ] as unknown as IterationRecord[];

  // Cycles: the announced changes live on iteration records, but cycle rows
  // are the SAME append-only producer — pin that a cycle carrying unknown
  // extra keys, an unknown topic_source, and an extra key on an outcome
  // renders beside the normal errored / executed / planned-empty trio.
  const FC_CYCLES = [
    {
      timestamp: "2026-06-09T09:30:00.000000Z",
      run_id: "coordinator_fc000001",
      agent: "coordinator",
      topic: "forward-compat cycle",
      topic_source: "skeptic_replay",
      status: "executed",
      plan: [{ action: "run_loop_iteration", args: { topic: "fc" } }],
      outcomes: [
        {
          action: "run_loop_iteration",
          status: "passed",
          skeptic_verdict: "pass",
          dispatched_iteration_id: "iter-2026-06-09-101",
        },
      ],
      promoted_finding_ids: [],
      bubble_run_ids: [],
      schema_rev: 2,
      dispatch_meta: { retries: 0 },
    },
    {
      timestamp: "2026-06-09T07:19:25.392025Z",
      run_id: "coordinator_27629ba6",
      agent: "coordinator",
      topic: "FASE: Fast Adaptive Semantic Entropy for Code Quality",
      topic_source: "arxiv_pick",
      status: "executed",
      plan: [{ action: "noop", args: { reason: "x" } }],
      outcomes: [{ action: "noop", status: "errored", error: "RuntimeError: boom" }],
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
      plan: [{ action: "run_loop_iteration", args: { topic: "noisy PD" } }],
      outcomes: [],
      promoted_finding_ids: [],
      bubble_run_ids: ["coordinator_df4eecc8"],
    },
  ] as unknown as CoordinatorCycle[];

  const EMPTY_FINDINGS = [] as SurfacedFinding[];
  const EMPTY_BUBBLES = [] as Bubble[];
  const EMPTY_HEALTH = [] as HealthSignal[];

  // Minimal-but-real /api/research body so Experiments walks its happy path
  // around the coordinator-cycles section under test.
  const RESEARCH = {
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
            verdict: { text: "EXPLOITED by all_d", tone: "bad" },
            bridge: [
              {
                iteration_id: "iter-2026-06-09-101",
                metric: "truthful_fraction",
                value: 0.965,
              },
            ],
          },
        ],
      },
    ],
    untiered: [],
  } as ResearchResponse;

  const telemetrySamples = (): TelemetrySample[] => {
    const s = {
      timestamp: new Date().toISOString(),
      gpu: { util_pct: 10, mem_used_mb: null, mem_total_mb: null, temp_c: 41, power_w: 5.5 },
      host: { cpu_pct: 10, mem_used_mb: 5000, cpu_temp_c: 44, load_avg: [1, 1, 1] },
      vllm: {
        running_requests: 1,
        waiting_requests: 0,
        gpu_cache_usage_pct: 12,
        gpu_prefix_cache_hit_rate: 0.8,
        tokens_per_sec_decode: 42,
        mtp_acceptance_rate: 0.6,
        mtp_draft_tokens: 100,
        mtp_accepted_tokens: 60,
      },
      vllm_qwen: null,
      processes: [],
      read_errors: null,
    } as unknown as TelemetrySample;
    return [s, { ...s, timestamp: new Date().toISOString() }];
  };

  const MONITOR = {
    available: true,
    telemetry_available: true,
    active: [],
    recent: [],
    last_activity_at: "2026-06-09T09:30:00.000000Z",
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
    generated_at: "2026-06-09T09:31:00.000000Z",
  } as MonitorResponse;

  const GRAPH = {
    available: true,
    nodes: [],
    edges: [],
    task_count: 0,
    detail: "overview",
    generated_at: "2026-06-09T09:31:00.000000Z",
  } as ActivityGraphResponse;

  return {
    FC_ITERATIONS,
    FC_CYCLES,
    EMPTY_FINDINGS,
    EMPTY_BUBBLES,
    EMPTY_HEALTH,
    RESEARCH,
    MONITOR,
    GRAPH,
    telemetrySamples,
  };
});

// ─── module mocks: hand the announced-contract rows back through the
// production fetchers (same surface as test_validate_routes_console.tsx) ─────

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
  getState: vi.fn().mockResolvedValue({ current_day: "2026-06-09" }),
  getIterations: vi.fn().mockResolvedValue({ iterations: D.FC_ITERATIONS }),
  getJournalEntry: vi.fn().mockResolvedValue({
    iteration_id: "iter-2026-06-09-101",
    path: "journal/iterations/101.md",
    content: "# Journal\n\nbody",
  }),
  getActiveIteration: vi.fn().mockResolvedValue(null),
  getBaseline: vi.fn().mockResolvedValue({ rows: [] }),
  getWorkloadHint: vi.fn().mockResolvedValue({ regime: "idle" }),
  getCoordinatorCycles: vi.fn().mockResolvedValue({ cycles: D.FC_CYCLES }),
  getCoordinatorActive: vi.fn().mockResolvedValue(null),
  getSurfacedFindings: vi.fn().mockResolvedValue({ findings: D.EMPTY_FINDINGS }),
  getBubbles: vi.fn().mockResolvedValue({ bubbles: D.EMPTY_BUBBLES }),
  getHealthSignals: vi
    .fn()
    .mockResolvedValue({ health_signals: D.EMPTY_HEALTH }),
  // HUMAN TODO endpoint: quiet empty-queue default.
  getHumanTodo: vi.fn().mockResolvedValue({ items: [], counts: {} }),
  // InFlightRollup feed (FE5): Dashboard polls getProcesses in the HERO effect.
  getProcesses: vi.fn().mockResolvedValue({ processes: [] }),
  startIteration: vi.fn().mockResolvedValue({ pid: 1 }),
  // S1 additions: the NowBoard registry poll (Pulse mounts it live) and the
  // /ladder endpoint pair — the ladder payload below carries an UNKNOWN
  // status + an unknown extra key + an out-of-enum kill code shape, per this
  // file's bar: current renders survive rows with unknown fields/values.
  getActiveRuns: vi.fn().mockResolvedValue({ runs: [], skipped: 0 }),
  getLadder: vi.fn().mockResolvedValue({
    clusters: [
      {
        cluster_id: "cl-fc-001",
        stem: "forward-compat cluster",
        status: "quarantined", // never-announced status value
        evidence_level: "L7", // beyond the known rungs
        origin: "future_channel",
        member_count: 1,
        last_event_ts: "2026-08-15T00:00:00Z",
        kill_reason: null,
        reopening_condition: null,
        open_agenda_count: 0,
        future_key: { nested: "object" },
      },
      {
        cluster_id: "cl-fc-002",
        stem: "killed with unknown code",
        status: "killed",
        evidence_level: "L1",
        origin: "consolidation",
        member_count: 2,
        last_event_ts: "2026-08-14T00:00:00Z",
        kill_reason: { code: "toString", detail: "prototype-colliding code" },
        reopening_condition: { requires: "new_evidence" },
        open_agenda_count: 0,
      },
    ],
    histogram: { L0: 0, L1: 0, L2: 0, L3: 0, L4: 0, L5: 0, L7: 1 },
    counts: { open: 0, surfaced: 0, killed: 1 },
    agenda: [{ topic: "fc topic", source: "toString", cluster_id: "cl-fc-001" }],
    next_owed: { L0: "x", L1: "x", L2: "x", L3: "x", L4: "x", L5: "x" },
    unknown_top_level: true,
  }),
  getIdeas: vi.fn().mockResolvedValue({ markdown: "# Ideas\n" }),
}));

vi.mock("../src/api/activity", () => ({
  getActivityGraph: vi.fn().mockResolvedValue(D.GRAPH),
  getActivityMonitor: vi.fn().mockResolvedValue(D.MONITOR),
  getActiveRun: vi.fn().mockResolvedValue(null),
}));

vi.mock("../src/api/experiments", () => ({
  getResearch: vi.fn().mockResolvedValue(D.RESEARCH),
  getExperiments: vi.fn().mockResolvedValue({ available: true, experiments: [] }),
  getExperimentDetail: vi.fn().mockResolvedValue(null),
}));

// Imported AFTER the mocks are declared (vi.mock is hoisted).
import Dashboard from "../src/routes/Dashboard";
import Activity from "../src/routes/Activity";
import Experiments from "../src/routes/Experiments";
import Coordinator from "../src/routes/Coordinator";
import Ladder from "../src/routes/Ladder";
import Pulse from "../src/routes/Pulse";
import DossierIndex from "../src/routes/DossierIndex";

// Spy on console.error / console.warn around a render + a full async flush —
// the cheap jsdom stand-in for "no browser console errors". Two waitFor ticks
// let every mocked fetch + any follow-up setState settle inside act().
async function renderRouteQuietly(node: React.ReactElement) {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  render(<MemoryRouter>{node}</MemoryRouter>);
  await waitFor(() => expect(true).toBe(true));
  await waitFor(() => expect(true).toBe(true));
  const calls = {
    error: errSpy.mock.calls.map((c) => String(c[0])),
    warn: warnSpy.mock.calls.map((c) => String(c[0])),
  };
  errSpy.mockRestore();
  warnSpy.mockRestore();
  return calls;
}

describe("routes survive the announced additive contract (undecidable / novelty_axes / relevance siblings)", () => {
  beforeEach(() => {
    vi.useRealTimers();
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("Dashboard: undecidable + override siblings + novelty_axes + 5 relevance siblings, mixed with legacy rows", async () => {
    const { error, warn } = await renderRouteQuietly(<Dashboard />);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("Coordinator: cycles carrying unknown topic_source / extra keys beside the normal trio", async () => {
    const { error, warn } = await renderRouteQuietly(
      <Coordinator pollMs={1_000_000} />,
    );
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("Activity: forward-compat cycles (errored row still derives; extra outcome keys ignored)", async () => {
    const { error, warn } = await renderRouteQuietly(<Activity />);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("Experiments: research index + forward-compat coordinator cycles", async () => {
    const { error, warn } = await renderRouteQuietly(<Experiments />);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("Pulse (S1 home): forward-compat cycles + empty registry, console-clean", async () => {
    const { error, warn } = await renderRouteQuietly(<Pulse />);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("Ladder (S1): unknown status/rung/kill-code shapes degrade quietly", async () => {
    const { error, warn } = await renderRouteQuietly(<Ladder />);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("DossierIndex (S2): forward-compat iteration rows render console-clean in the picker", async () => {
    const { error, warn } = await renderRouteQuietly(<DossierIndex />);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });
});
