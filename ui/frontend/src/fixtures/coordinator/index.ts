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
  HealthSignal,
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
  label: "coordinator_cycle",
  current_step: "dispatch",
  step_started_at: "2026-06-09T12:00:30Z",
  narration:
    "Chose 'Truthfulness of VCG in combinatorial auctions' (topic_source=coordinator) " +
    "because it's the lowest-coverage game-theory topic in the last 9 iterations; " +
    "dispatching a loop iteration at k=8.",
  started_at: "2026-06-09T12:00:00Z",
};

export const SURFACED_FINDINGS_FIXTURE: SurfacedFinding[] = [
  {
    finding_id: "sf-iter-2026-06-09-003",
    source_iteration_id: "iter-2026-06-09-003",
    title: "Level-k convergence rate in p-beauty contests refines Nagel (1995)",
    claim:
      "Level-k reasoning converges ~1 level/round faster than Nagel (1995) under the measured payoff structure.",
    novelty_class: "novel",
    critic_verdict: "survives",
    why_it_matters:
      "A faster convergence rate would tighten the level-k calibration the loop conditions on.",
    status: "surfaced",
    promoted_at: "2026-06-09T13:20:00Z",
  },
  {
    finding_id: "sf-iter-2026-06-09-001",
    source_iteration_id: "iter-2026-06-09-001",
    title: "VCG elicits truthful bids in the measured combinatorial setting",
    claim:
      "VCG achieves 96.5% truthful bids in the exp004 combinatorial-auction bridge.",
    novelty_class: "rediscovery",
    critic_verdict: "restated",
    why_it_matters:
      "Confirms the VCG-truthfulness bridge that conditions downstream iterations.",
    status: "surfaced",
    promoted_at: "2026-06-09T10:05:00Z",
  },
];

export const BUBBLES_FIXTURE: Bubble[] = [
  {
    timestamp: "2026-06-09T11:35:00Z",
    run_id: "cyc-2026-06-09-002",
    finding_ids: ["sf-iter-2026-06-09-002"],
    note:
      "A novel/survives verdict rested on off-domain retrieval (code-quality topic vs game-theory books) — eyeball before trusting.",
  },
  {
    timestamp: "2026-06-09T11:34:00Z",
    run_id: "cyc-2026-06-09-002",
    finding_ids: [],
    note: "ml-intern returned 0 papers for this topic — external evidence is silent.",
  },
  {
    timestamp: "2026-06-09T10:06:00Z",
    run_id: "cyc-2026-06-09-001",
    finding_ids: ["sf-iter-2026-06-09-001"],
    note: "Promoted 1 finding to surfaced_findings this cycle.",
  },
];

// Degraded-but-not-broken health signals (run_state/health_signals.jsonl) — the
// two the EMIT layer derives per cycle. Both severity "degraded" → rendered
// amber, never red: the route/worker ran, the output was just thin.
export const HEALTH_SIGNALS_FIXTURE: HealthSignal[] = [
  {
    signal: "ml_intern_zero_papers",
    severity: "degraded",
    timestamp: "2026-06-09T11:34:00Z",
    run_id: "cyc-2026-06-09-002",
    iteration_id: "iter-2026-06-09-002",
    papers_stored: 0,
    detail:
      "ml_intern ran but stored 0 papers; the external-search layer was blind — any verdict this iteration rests on LOCAL literature only.",
  },
  {
    signal: "qwen_degraded_empty_content",
    severity: "degraded",
    timestamp: "2026-06-09T11:33:00Z",
    run_id: "cyc-2026-06-09-002",
    iteration_id: "iter-2026-06-09-002",
    empty_calls: 2,
    total_calls: 3,
    detail:
      "Qwen returned empty content on 2/3 calls this iteration (route up but unusable). The independent skeptic is DEGRADED, not down.",
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
      relevance: {
        relevance: 0.81,
        low_confidence: false,
        reason: "on-domain: strong neighbor overlap with the game-theory corpus",
      },
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
      relevance: {
        relevance: 0.04,
        low_confidence: true,
        reason:
          "off-domain: code-quality topic retrieved against game-theory books (max overlap 0.043)",
      },
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
      relevance: {
        relevance: 0.74,
        low_confidence: false,
        reason: "on-domain: p-beauty-contest neighbors well-matched",
      },
    },
    novelty: { class: "novel", top_neighbor_id: "nagel1995" },
    critique: { verdict: "survives" },
    journal_entry_path: "journal/iterations/008.md",
    nara_summary:
      "Nara: candidate refinement of level-k convergence rates; well-supported by on-topic retrieval.",
  },
];

// 2026-06-09 evening additions (close-out: docs/ui_validation_handoff.md) — the
// additive observability fields the EMIT side now produces. A SEPARATE export:
// ITERATIONS_COORD_FIXTURE's exact 3-row composition is pinned by existing
// tests (red-flag percentages, badge counts) and must not change. Three rows:
//   (i)   the skeptic-refuted UNDECIDABLE: critique verdict "undecidable" with
//         verdict_overridden_from/override_reason/skeptic_verdict (EMIT:
//         workers/critic_loop_v0.py `_maybe_run_skeptic`, NARA_SKEPTIC=1).
//   (ii)  novelty_axes populated (EMIT: workers/novelty_classify.py) on an
//         otherwise clean novel/survives row.
//   (iii) the FULL new relevance diagnostic block — category "off_domain",
//         rule_fired "R1", low_confidence true — plus the novelty-side
//         low-confidence override (novel -> unclear, axes preserved).
export const ITERATIONS_OBSERVABILITY_FIXTURE: IterationRecord[] = [
  {
    iteration_id: "iter-2026-06-09-101",
    started_at: "2026-06-09T17:00:00Z",
    ended_at: "2026-06-09T17:02:40Z",
    seed: {
      topic: "History masking shifts Stag Hunt convergence in LLM agents",
      source: "nemoclaw_agent",
    },
    retrieval: {
      k: 8,
      relevance: {
        relevance: 0.92,
        low_confidence: false,
        reason:
          "on-domain retrieval: mean top-3 lexical overlap 0.126 >= 0.05, max cosine 0.684.",
        anchor_cosine: 0.71,
        curated_overlap: 0.118,
        neighbor_spread: 0.092,
        category: "ok",
        rule_fired: null,
      },
    },
    novelty: {
      class: "novel",
      rationale:
        "No retrieved neighbor links history transparency to Stag Hunt convergence in LLM agents.",
      top_neighbor_id: "evolutionary-game-theory_compress-chunk-195",
      low_confidence: false,
      novelty_axes: {
        phenomenon: "novel",
        substrate: "unstudied_llm",
        predicted_direction: "silent",
      },
    },
    critique: {
      verdict: "undecidable",
      rationale:
        "The provided corpus contains no contradiction, but an independent skeptic retrieval surfaced a directly opposing convergence result.",
      contradicting_paper_id: null,
      low_confidence: false,
      verdict_overridden_from: "survives",
      override_reason:
        "skeptic attack_verdict='refuted': independent retrieval found Young (1993) chunk contradicting the predicted risk-dominance shift.",
      skeptic_verdict: "refuted",
    },
    journal_entry_path: "journal/iterations/009.md",
    nara_summary:
      "Nara: survives the shared-neighbor critic, but the independent skeptic refuted it — verdict downgraded to undecidable (fails closed).",
  },
  {
    iteration_id: "iter-2026-06-09-102",
    started_at: "2026-06-09T17:10:00Z",
    ended_at: "2026-06-09T17:12:15Z",
    seed: {
      topic: "Transparency drives LLM agents from payoff- to risk-dominance",
      source: "coordinator",
    },
    retrieval: {
      k: 8,
      relevance: {
        relevance: 0.88,
        low_confidence: false,
        reason:
          "on-domain retrieval: mean top-3 lexical overlap 0.175 >= 0.05, max cosine 0.621.",
        anchor_cosine: 0.66,
        curated_overlap: 0.131,
        neighbor_spread: 0.114,
        category: "ok",
        rule_fired: null,
      },
    },
    novelty: {
      class: "novel",
      rationale:
        "Neighbors cover risk dominance and history-based learning separately; the causal link for LLM agents is unaddressed.",
      top_neighbor_id: "young_1993-chunk-14",
      low_confidence: false,
      novelty_axes: {
        phenomenon: "known",
        substrate: "unstudied_llm",
        predicted_direction: "matches",
      },
    },
    critique: { verdict: "survives", low_confidence: false },
    journal_entry_path: "journal/iterations/010.md",
    nara_summary:
      "Nara: a known phenomenon on an unstudied LLM substrate — novel by axes, survives critique on on-domain retrieval.",
  },
  {
    iteration_id: "iter-2026-06-09-103",
    started_at: "2026-06-09T17:20:00Z",
    ended_at: "2026-06-09T17:22:50Z",
    seed: {
      topic: "Off-domain: semantic-entropy gating for CI pipelines",
      source: "arxiv_pick",
    },
    retrieval: {
      k: 8,
      relevance: {
        relevance: 0.05,
        low_confidence: true,
        reason:
          "off-domain retrieval: hypothesis shares almost no vocabulary with its neighbors (mean top-3 lexical overlap 0.043 < 0.05; max cosine 0.612). 'No contradiction in an irrelevant corpus' is not 'survives'.",
        anchor_cosine: 0.34,
        curated_overlap: 0.012,
        neighbor_spread: 0.027,
        category: "off_domain",
        rule_fired: "R1",
      },
    },
    novelty: {
      class: "unclear",
      rationale:
        "No neighbor addresses semantic-entropy gating — but the corpus is game theory; the omission is not evidence of novelty.",
      top_neighbor_id: null,
      low_confidence: true,
      novelty_axes: {
        phenomenon: "novel",
        substrate: "unstudied_llm",
        predicted_direction: "silent",
      },
      verdict_overridden_from: "novel",
      override_reason:
        "low-confidence retrieval (off-domain retrieval: hypothesis shares almost no vocabulary with its neighbors); 'novel' downgraded to 'unclear' — an omission in an off-topic corpus is not novelty",
    },
    critique: {
      verdict: "survives",
      rationale:
        "The retrieved game-theory literature contains nothing about CI pipelines, so nothing contradicts the hypothesis.",
      contradicting_paper_id: null,
      low_confidence: true,
    },
    journal_entry_path: "journal/iterations/011.md",
    nara_summary:
      "Nara: no close neighbor found, but retrieval was off-domain (R1) — the novelty verdict was overridden to unclear.",
  },
];
