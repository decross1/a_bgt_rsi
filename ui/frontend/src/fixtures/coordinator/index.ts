// Autonomy-observability fixtures the coordinator panels + downstream
// component tests build against until the primary session (EMIT) has shipped
// run_state/coordinator_cycles.jsonl, run_state/active_run.json,
// memory/surfaced_findings.jsonl, and memory/coordinator_bubbles.jsonl.
// See ui_autonomy_observability_plan.md §"Data contracts".
//
// Design intent baked into these fixtures (so the views can be tested against
// the real failure modes, not happy paths):
//   - COORDINATOR_CYCLES_FIXTURE has a FAILED dispatch (status "errored" + a
//     real error string) — the "absence is legible" headline case.
//   - topic_source spans "coordinator" + "arxiv_pick" (provenance badge).
//   - ITERATIONS_COORD_FIXTURE carries the false-novel bug: novel/survives on
//     low/thin retrieval relevance — the low-evidence badge driver.
import type {
  Bubble,
  CoordinatorActiveRun,
  CoordinatorCycle,
  IterationRecord,
  SurfacedFinding,
} from "../../types/schemas";

// Two cycles. Cycle 1 is a clean coordinator-chosen dispatch that promoted a
// finding and raised a bubble. Cycle 2 is the FAILED-dispatch case: an
// off-domain arxiv-picked topic whose dispatch errored on a schema-enum gap —
// it MUST still render as an explicit (red) row, never a silent gap.
export const COORDINATOR_CYCLES_FIXTURE: CoordinatorCycle[] = [
  {
    timestamp: "2026-06-09T11:30:00Z",
    run_id: "cyc-2026-06-09-002",
    agent: "coordinator",
    topic: "Off-domain: code-quality heuristics for PR review",
    topic_source: "arxiv_pick",
    plan: [
      { action: "assess_memory", args: { rows_considered: 12 } },
      { action: "pick_topic", args: { source: "arxiv_pick" } },
      { action: "run_loop_iteration", args: { k: 8 } },
      { action: "promote_findings", args: {} },
    ],
    outcomes: [
      { action: "assess_memory", status: "passed" },
      { action: "pick_topic", status: "passed" },
      // The headline failed-dispatch: errored + a real error string.
      {
        action: "run_loop_iteration",
        status: "errored",
        error:
          "ValueError: 'code_quality' is not a valid SeedSource — run_loop_iteration aborted before any iteration row was written.",
      },
      { action: "promote_findings", status: "skipped" },
    ],
    dispatched_iteration_id: "iter-2026-06-09-002",
    promoted_finding_ids: [],
    bubble_run_ids: ["cyc-2026-06-09-002"],
  },
  {
    timestamp: "2026-06-09T10:00:00Z",
    run_id: "cyc-2026-06-09-001",
    agent: "coordinator",
    topic: "Truthfulness of VCG in combinatorial auctions",
    topic_source: "coordinator",
    plan: [
      { action: "assess_memory", args: { rows_considered: 9 } },
      { action: "pick_topic", args: { source: "coordinator" } },
      { action: "run_loop_iteration", args: { k: 8 } },
      { action: "promote_findings", args: {} },
      { action: "bubble_up", args: {} },
    ],
    outcomes: [
      { action: "assess_memory", status: "passed" },
      { action: "pick_topic", status: "passed" },
      { action: "run_loop_iteration", status: "passed" },
      { action: "promote_findings", status: "passed" },
      { action: "bubble_up", status: "passed" },
    ],
    dispatched_iteration_id: "iter-2026-06-09-001",
    promoted_finding_ids: ["find-2026-06-09-001"],
    bubble_run_ids: ["cyc-2026-06-09-001"],
  },
];

// Live cycle, mid-dispatch. Narration carries the chosen topic + why so the
// active panel can say what stage and why (not just "running").
export const ACTIVE_RUN_FIXTURE: CoordinatorActiveRun = {
  kind: "coordinator",
  run_id: "cyc-2026-06-09-003",
  current_step: "dispatch",
  narration:
    "Chose 'Truthfulness of VCG in combinatorial auctions' (topic_source=coordinator) " +
    "because it's the lowest-coverage game-theory topic in the last 9 iterations; " +
    "dispatching a loop iteration at k=8.",
  topic: "Truthfulness of VCG in combinatorial auctions",
  topic_source: "coordinator",
  started_at: "2026-06-09T12:00:00Z",
};

export const SURFACED_FINDINGS_FIXTURE: SurfacedFinding[] = [
  {
    finding_id: "find-2026-06-09-002",
    iteration_id: "iter-2026-06-09-003",
    agent: "nara",
    text:
      "Level-k convergence rate in p-beauty contests refines Nagel (1995); candidate worth a real run.",
    timestamp: "2026-06-09T13:20:00Z",
  },
  {
    finding_id: "find-2026-06-09-001",
    iteration_id: "iter-2026-06-09-001",
    agent: "coordinator",
    text:
      "VCG elicits truthful bids in the measured combinatorial setting (exp004 bridge: 96.5% truthful).",
    timestamp: "2026-06-09T10:05:00Z",
  },
];

export const BUBBLES_FIXTURE: Bubble[] = [
  {
    bubble_id: "bub-2026-06-09-001",
    run_id: "cyc-2026-06-09-002",
    agent: "coordinator",
    text:
      "A novel/survives verdict rested on off-domain retrieval (code-quality topic vs game-theory books) — eyeball before trusting.",
    severity: "raise",
    timestamp: "2026-06-09T11:35:00Z",
  },
  {
    bubble_id: "bub-2026-06-09-002",
    run_id: "cyc-2026-06-09-002",
    agent: "coordinator",
    text: "ml-intern returned 0 papers for this topic — external evidence is silent.",
    severity: "warn",
    timestamp: "2026-06-09T11:34:00Z",
  },
  {
    bubble_id: "bub-2026-06-09-003",
    run_id: "cyc-2026-06-09-001",
    agent: "nara",
    text: "Promoted 1 finding to surfaced_findings this cycle.",
    severity: "info",
    timestamp: "2026-06-09T10:06:00Z",
  },
];

// Iteration rows for the Dashboard's Recent Iterations + low-evidence badge +
// red-flags strip tests. Three rows:
//   (i)   coordinator-triggered, healthy evidence (seed.source "coordinator").
//   (ii)  the FALSE-NOVEL bug: novel/survives but retrieval.relevance.flag
//         "low" — drives the low-evidence badge + suspected-false-novel count.
//   (iii) a clean human row (seed.source "human") for contrast.
export const ITERATIONS_COORD_FIXTURE: IterationRecord[] = [
  {
    iteration_id: "iter-2026-06-09-001",
    started_at: "2026-06-09T10:00:30Z",
    ended_at: "2026-06-09T10:03:10Z",
    seed: {
      topic: "Truthfulness of VCG in combinatorial auctions",
      source: "coordinator",
    },
    retrieval: {
      k: 8,
      relevance: { score: 0.81, flag: "ok", topical_match: 0.79 },
    },
    novelty: { class: "rediscovery", top_neighbor_id: "vickrey1961" },
    critique: { verdict: "restated" },
    journal_entry_path: "journal/iterations/006.md",
    nara_summary:
      "Nara: VCG truthfulness is foundational; this iteration is a rediscovery on-topic.",
  },
  {
    // The headline 2026-06-09 false-novel: novel/survives resting on thin,
    // off-domain retrieval. The verdict says "new", the evidence says "don't
    // trust it" — the low-evidence badge exists for exactly this row.
    iteration_id: "iter-2026-06-09-002",
    started_at: "2026-06-09T11:30:30Z",
    ended_at: "2026-06-09T11:33:48Z",
    seed: {
      topic: "Off-domain: code-quality heuristics for PR review",
      source: "coordinator",
    },
    retrieval: {
      k: 8,
      relevance: { score: 0.18, flag: "low", topical_match: 0.12 },
    },
    novelty: { class: "novel", top_neighbor_id: "axelrod1984" },
    critique: { verdict: "survives" },
    journal_entry_path: "journal/iterations/007.md",
    nara_summary:
      "Nara: no close neighbor found — appears novel and survives critique. (Retrieval was off-domain.)",
  },
  {
    iteration_id: "iter-2026-06-08-009",
    started_at: "2026-06-08T16:10:00Z",
    ended_at: "2026-06-08T16:12:55Z",
    seed: {
      topic: "Behavioral deviation from Nash in p-beauty contests",
      source: "human",
    },
    retrieval: {
      k: 8,
      relevance: { score: 0.74, flag: "ok", topical_match: 0.71 },
    },
    novelty: { class: "novel", top_neighbor_id: "nagel1995" },
    critique: { verdict: "survives" },
    journal_entry_path: "journal/iterations/008.md",
    nara_summary:
      "Nara: candidate refinement of level-k convergence rates; well-supported by on-topic retrieval.",
  },
];
