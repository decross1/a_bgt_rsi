// REVALIDATION (B3c, 2026-06-09 evening close-out) — the LIVE data vs the NEW
// additive contract shapes, after the primary session's close-out landed
// (docs/ui_validation_handoff.md "2026-06-09 evening additions").
//
// Three slices, each against the REAL artifacts (never fabricated):
//   1. nemoclaw_agent rows — count the live in-sandbox-agent iterations and
//      pin the two known rows (iter-2026-06-09-003/-004, pasted VERBATIM below
//      minus heavy payloads) rendering through ResolvedIterationsList with the
//      violet provenance badge, the red redteam chip, and NO low-evidence flag
//      (both are on-domain, relevance.low_confidence:false).
//   2. NEW-shape live rows — undecidable verdicts / novelty.novelty_axes /
//      relevance.category. At validation time (2026-06-09 ~21:00 UTC) ZERO
//      live rows carry any of them (verdict census: survives/falsified only;
//      relevance keys census: {relevance, low_confidence, reason} only), so
//      the conditional render-loops are empty TODAY; the enum/key drift pins
//      below still bite on every run, and any future live row that does carry
//      the new shapes gets auto-validated by the loops. The synthetic-shape
//      contract is already pinned by test_undecidable_verdict /
//      test_novelty_axes_chip / test_forwardcompat_iterations_list — this
//      file deliberately re-validates only what is LIVE.
//   3. Findings/bubbles honesty — memory/surfaced_findings.jsonl and
//      memory/coordinator_bubbles.jsonl. Verified out-of-band at validation
//      time: neither file exists and the live backend (:8700) returns
//      {"findings":[]} / {"bubbles":[]}. The tests branch on the REAL file
//      state: absent → the honest empty state must hold (no fabricated rows);
//      present → the panels must render the real rows. Either way the panel
//      reflects the artifact, never an invention.
import {
  cleanup,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ResolvedIterationsList from "../src/components/ResolvedIterationsList";
import NoveltyAxesChip from "../src/components/NoveltyAxesChip";
import SurfacedFindingsPanel from "../src/components/SurfacedFindingsPanel";
import BubblesPanel from "../src/components/BubblesPanel";
import type {
  Bubble,
  IterationRecord,
  SurfacedFinding,
} from "../src/types/schemas";

// Resolve the primary repo root from this test file's location, mirroring
// test_validate_iterations.tsx (and the backend's hardcoded _PRIMARY_REPO):
// tests/ -> frontend -> ui -> ui-session -> worktrees -> .claude -> repo root.
const REPO_ROOT = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../../../../..",
);

function loadJsonl<T>(path: string): T[] {
  return readFileSync(path, "utf8")
    .split("\n")
    .filter((l) => l.trim().length > 0)
    .map((l) => JSON.parse(l) as T);
}

// Honest absent-vs-present read for the findings/bubbles channels: a missing
// file (ENOENT) is the REAL "the loop has surfaced nothing yet" state and
// returns null (≠ [], which would be "file exists but is empty"); any OTHER
// read failure rethrows — a permission error must not masquerade as the clean
// empty state. readFileSync-based because the shared tests/node-builtins.d.ts
// shim deliberately declares only the symbols already imported (adding
// existsSync there is a shared-file change, deferred as a followup).
function loadJsonlIfExists<T>(path: string): T[] | null {
  try {
    return loadJsonl<T>(path);
  } catch (e) {
    if ((e as { code?: string }).code === "ENOENT") return null;
    throw e;
  }
}

// The real, gitignored loop memory the backend serves live. A missing file is
// a real failure (this data IS the contract under validation), not a skip.
const REAL = loadJsonl<IterationRecord>(
  resolve(REPO_ROOT, "memory/loop_memory.jsonl"),
);

const NEMOCLAW = REAL.filter((r) => r.seed?.source === "nemoclaw_agent");
const UNDECIDABLE = REAL.filter(
  (r) => r.critique?.verdict === "undecidable",
);
const WITH_AXES = REAL.filter((r) => {
  const axes = r.novelty?.novelty_axes;
  return axes != null && typeof axes === "object" && !Array.isArray(axes);
});
const WITH_CATEGORY = REAL.filter(
  (r) => typeof r.retrieval?.relevance?.category === "string",
);

// ── The two REAL nemoclaw_agent rows, pasted verbatim from loop_memory.jsonl
// (2026-06-09). Heavy payloads the list renderer never touches are elided:
// retrieval.neighbors (10 chunks each), narration_log, nara_summary,
// hypothesis.all_candidates. Every field the row render path DOES read —
// seed, relevance, novelty, critique, redteam, gate_status, meta_review,
// ended_at — is the exact live value, so these pins survive even if the live
// file accretes past them.
const ITER_003: IterationRecord = {
  iteration_id: "iter-2026-06-09-003",
  started_at: "2026-06-09T17:32:19.131312Z",
  ended_at: "2026-06-09T17:33:23.466379Z",
  seed: {
    topic:
      "Do LLM agents in repeated stag hunt converge to the payoff-dominant or risk-dominant equilibrium, and does opponent-history transparency shift selection?",
    source: "nemoclaw_agent",
  },
  retrieval: {
    k: 10,
    relevance: {
      relevance: 1.0,
      low_confidence: false,
      reason:
        "on-domain retrieval: mean top-3 lexical overlap 0.126 >= 0.05, max cosine 0.684.",
    },
  },
  novelty: {
    class: "novel",
    rationale:
      "While the retrieved literature (doc_id='evolutionary-game-theory_compress-chunk-195') defines the Stag Hunt game and the tradeoff between efficiency and risk, the specific hypothesis regarding the impact of information transparency (history masking) on the convergence of LLM agents is not addressed in the provided neighbors.",
    top_neighbor_id: "evolutionary-game-theory_compress-chunk-195",
    low_confidence: false,
  },
  critique: {
    verdict: "survives",
    rationale:
      "The retrieved literature discusses the theoretical properties of Stag Hunt games (payoff vs. risk dominance, doc [3]) and the role of history in coordination (doc [4]), but contains no specific empirical or theoretical findings regarding LLM agents' convergence patterns under varying levels of history transparency. The hypothesis remains an untested claim within the provided context.",
    contradicting_paper_id: null,
    low_confidence: false,
  },
  redteam: {
    verdict: "fatal_flaw",
    critique:
      "The hypothesis fails to account for the endogeneity problem: if the agent shifts to risk-dominance (defecting) due to transparency, it creates the very 'defecting-type' history it uses to justify the shift, making it impossible to isolate the causal mechanism. Additionally, 'perceived probability' is a psychological construct that lacks a formal mathematical mapping to LLM token prediction probabilities, making the mechanism untestable as stated.",
    suggested_revision:
      "In iterated prisoner's dilemma simulations, increasing the window of visible opponent history for LLM agents correlates with a statistically significant decrease in the frequency of 'Stag' (cooperative) moves, even when the underlying opponent population remains constant.",
    confidence: 0.85,
    retries_used: 2,
  },
  meta_review: {
    conditioning_bullets: [
      "Prioritize hypotheses linking high truthfulness/equilibrium adherence in VCG or Cournot models to cognitive load or bounded rationality constraints.",
      "Maintain the focus on semantic entropy as a mechanism for optimizing code quality and accelerating convergence to high-quality equilibria.",
      "Avoid purely descriptive reporting of experimental outcomes (e.g., efficiency scores) without a mechanistic explanation for the observed behavior.",
      "Leverage the validated pattern that LLM agents exhibit high truthfulness in combinatorial auctions (96.5%) to explore the boundary between incentive compatibility and computational complexity.",
    ],
    rows_considered: 8,
  },
  gate_status: "pending",
  journal_entry_path: "journal/iterations/066.md",
  model_version: "vllm/vllm-openai:v0.21.0/gemma-4-26b-a4b",
};

const ITER_004: IterationRecord = {
  iteration_id: "iter-2026-06-09-004",
  started_at: "2026-06-09T18:07:03.943411Z",
  ended_at: "2026-06-09T18:08:00.102834Z",
  seed: {
    topic:
      "Increased opponent-history transparency shifts LLM agents from payoff-dominance to risk-dominance by increasing the perceived probability of defecting-type opponents.",
    source: "nemoclaw_agent",
  },
  retrieval: {
    k: 10,
    relevance: {
      relevance: 1.0,
      low_confidence: false,
      reason:
        "on-domain retrieval: mean top-3 lexical overlap 0.175 >= 0.05, max cosine 0.621.",
    },
  },
  novelty: {
    class: "novel",
    rationale:
      "While the neighbors discuss risk dominance (doc_9), history-based learning (doc_7), and LLM agents (doc_3), none address the specific causal mechanism proposed: that increased transparency of opponent history specifically drives LLM agents from payoff-dominance to risk-dominance via updated beliefs about opponent types. The hypothesis connects these distinct concepts into a specific behavioral prediction for LLMs that is not present in the retrieved literature.",
    top_neighbor_id: null,
    low_confidence: false,
  },
  critique: {
    verdict: "survives",
    rationale:
      "The retrieved literature provides the necessary components for the hypothesis: the concept of risk dominance (doc_id='evolutionary-game-theory_compress-chunk-196'), the role of observing opponent history (doc_id='young_1993-chunk-14'), and the existence of different agent types (doc_id='osborne_rubinstein-chunk-1506'). However, no specific study in the provided set directly tests or contradicts the causal link between increased transparency and the specific shift from payoff-dominance to risk-dominance in LLM agents.",
    contradicting_paper_id: null,
    low_confidence: false,
  },
  redteam: {
    verdict: "fatal_flaw",
    critique:
      "The hypothesis is logically incoherent: it claims a reduction in epistemic uncertainty via a mechanism (history disclosure) that it simultaneously defines as being stochastically independent of the target variable (opponent type). If the history is independent, no uncertainty reduction occurs, making the causal link impossible.",
    suggested_revision:
      "Reducing epistemic uncertainty regarding opponent types via history disclosure—where the history is correlated with the opponent's strategy—triggers a shift from payoff-dominance to risk-dominance in LLM agents in Stag Hunt-style games.",
    confidence: 1.0,
    retries_used: 2,
  },
  meta_review: {
    conditioning_bullets: [
      "Maintain the focus on the intersection of bounded rationality and mechanism design, specifically how cognitive load or computational complexity forces truthful reporting or equilibrium deviations.",
      "Continue exploring the use of semantic entropy as a metric for optimizing agent convergence and code quality.",
      "Leverage the observation that transparency in opponent history shifts agent behavior from payoff-dominance to risk-dominance via Bayesian-like updating.",
      "Avoid hypotheses that merely report experimental results (e.g., efficiency scores) without proposing a causal mechanism or theoretical driver.",
    ],
    rows_considered: 8,
  },
  gate_status: "pending",
  journal_entry_path: "journal/iterations/067.md",
  model_version: "vllm/vllm-openai:v0.21.0/gemma-4-26b-a4b",
};

// Console spy — the jsdom stand-in for "renders without console errors"
// (the test_validate_iterations / test_validate_panels_empty idiom).
function spyConsole() {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  return { errSpy, warnSpy };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("live census — nemoclaw_agent provenance rows", () => {
  it("the two known in-sandbox iterations are present (baseline 2; accretion-safe)", () => {
    // At validation time (2026-06-09 ~21:00 UTC) the census is EXACTLY the
    // baseline two — the in-sandbox agent had NOT yet appended new rows
    // (reported upstream as a data-side gap, not a render bug). The bound is
    // >= so the pin survives the rows the agent is expected to add.
    expect(NEMOCLAW.length).toBeGreaterThanOrEqual(2);
    const ids = NEMOCLAW.map((r) => r.iteration_id);
    expect(ids).toContain("iter-2026-06-09-003");
    expect(ids).toContain("iter-2026-06-09-004");
  });

  it("EVERY live nemoclaw row renders through the list with the violet badge and no console errors", () => {
    const { errSpy, warnSpy } = spyConsole();
    render(<ResolvedIterationsList initial={NEMOCLAW.slice(0, 10)} />);
    const badges = screen.getAllByTestId("source-badge");
    expect(badges.length).toBe(Math.min(NEMOCLAW.length, 10));
    for (const b of badges) {
      expect(b).toHaveTextContent("nemoclaw");
      expect(b.className).toContain("bg-violet-950");
      expect(b.getAttribute("title")).toBe("nemoclaw_agent");
    }
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});

describe("pinned REAL nemoclaw rows — full row render contract", () => {
  it("iter-2026-06-09-003: violet provenance, novel/survives chips, red redteam chip, NO low-evidence flag", () => {
    const { errSpy, warnSpy } = spyConsole();
    render(<ResolvedIterationsList initial={[ITER_003]} />);
    const row = within(
      screen.getByLabelText("load journal iter-2026-06-09-003"),
    );

    // Provenance: the headline β signal — the sandboxed agent chose this thesis.
    const source = row.getByTestId("source-badge");
    expect(source).toHaveTextContent("nemoclaw");
    expect(source.className).toContain("bg-violet-950");

    // Novelty + verdict chips with their emerald tones.
    expect(row.getByText("novel").className).toContain("text-emerald-400");
    expect(row.getByText("survives").className).toContain(
      "text-emerald-400",
    );

    // Loop v1 chips: red-team fatal_flaw with 2 revision retries (red), gate pending (sky).
    const redteam = row.getByTestId("redteam-chip");
    expect(redteam).toHaveTextContent("redteam fatal_flaw · 2 retries");
    expect(redteam.className).toContain("text-red-400");
    expect(row.getByText("pending").className).toContain("text-sky-300");

    // On-domain retrieval (relevance 1.0, low_confidence:false) → NO flag.
    expect(row.queryByTestId("low-evidence-badge")).toBeNull();

    // Conditioning bullets (meta_review) render as the "conditioned by" block.
    expect(
      row.getByTestId("conditioning-iter-2026-06-09-003"),
    ).toBeInTheDocument();

    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("iter-2026-06-09-004: same contract holds on the second live in-sandbox row", () => {
    const { errSpy, warnSpy } = spyConsole();
    render(<ResolvedIterationsList initial={[ITER_004]} />);
    const row = within(
      screen.getByLabelText("load journal iter-2026-06-09-004"),
    );
    expect(row.getByTestId("source-badge").className).toContain(
      "bg-violet-950",
    );
    expect(row.getByText("novel")).toBeInTheDocument();
    expect(row.getByText("survives")).toBeInTheDocument();
    expect(row.getByTestId("redteam-chip")).toHaveTextContent(
      "redteam fatal_flaw · 2 retries",
    );
    expect(row.queryByTestId("low-evidence-badge")).toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});

describe("live NEW-shape rows — undecidable / novelty_axes / relevance.category", () => {
  it("no live enum value drifts outside the close-out contract (frozen + additive only)", () => {
    // The 0fdb671 join contract is frozen, additive only — these are the FULL
    // value sets the close-out enumerates. A live row outside them is producer
    // drift this validation exists to catch loudly (inviolate rule 4: never
    // silently coerced).
    const KNOWN_VERDICTS = new Set([
      "survives",
      "restated",
      "falsified",
      "malformed",
      "undecidable",
    ]);
    const KNOWN_NOVELTY = new Set([
      "novel",
      "rediscovery",
      "unclear",
      "nonsense",
    ]);
    const KNOWN_RELEVANCE_KEYS = new Set([
      "relevance",
      "low_confidence",
      "reason",
      "anchor_cosine",
      "curated_overlap",
      "neighbor_spread",
      "category",
      "rule_fired",
    ]);
    for (const r of REAL) {
      const verdict = r.critique?.verdict;
      if (typeof verdict === "string") {
        expect(KNOWN_VERDICTS.has(verdict), `verdict "${verdict}"`).toBe(true);
      }
      const cls = r.novelty?.class;
      if (typeof cls === "string") {
        expect(KNOWN_NOVELTY.has(cls), `novelty class "${cls}"`).toBe(true);
      }
      const rel = r.retrieval?.relevance;
      if (rel != null && typeof rel === "object" && !Array.isArray(rel)) {
        for (const k of Object.keys(rel)) {
          expect(KNOWN_RELEVANCE_KEYS.has(k), `relevance key "${k}"`).toBe(
            true,
          );
        }
      }
    }
  });

  it("every live undecidable row (zero at validation time) renders the quiet-grey chip", () => {
    // Empty TODAY (live verdict census: survives/falsified only). When the
    // critic starts emitting "undecidable" on live rows, each lands here and
    // must take the DELIBERATE quiet tone (bg-zinc-800/40), not red/amber.
    for (const r of UNDECIDABLE) {
      const { errSpy } = spyConsole();
      render(<ResolvedIterationsList initial={[r]} />);
      // Scoped to the row: "undecidable" is also a filter-<option> label now
      // that the verdict is filterable (WF-B), so a screen-level getByText
      // would be ambiguous.
      const chip = within(
        screen.getByLabelText(`load journal ${r.iteration_id}`),
      ).getByText("undecidable");
      expect(chip.className).toContain("bg-zinc-800/40");
      expect(errSpy).not.toHaveBeenCalled();
      cleanup();
      vi.restoreAllMocks();
    }
  });

  it("every live novelty_axes row (zero at validation time) renders cleanly in the list AND through NoveltyAxesChip", () => {
    // The list mounts the axes THROUGH NoveltyAxesChip (wired by the WF-B
    // integrator) — the chip renders the three axes as plain strings; the raw
    // OBJECT still never reaches a React child (forward-compat pin (b)).
    for (const r of WITH_AXES) {
      const { errSpy } = spyConsole();
      render(<ResolvedIterationsList initial={[r]} />);
      expect(document.body.textContent).not.toContain("[object Object]");
      render(<NoveltyAxesChip axes={r.novelty?.novelty_axes} />);
      expect(screen.getByTestId("novelty-axes-chip")).toHaveTextContent(
        /^axes: /,
      );
      expect(errSpy).not.toHaveBeenCalled();
      cleanup();
      vi.restoreAllMocks();
    }
  });

  it("every live relevance.category row (zero at validation time) renders without leaking the diagnostics", () => {
    for (const r of WITH_CATEGORY) {
      const { errSpy } = spyConsole();
      render(<ResolvedIterationsList initial={[r]} />);
      expect(
        screen.getByLabelText(`load journal ${r.iteration_id}`),
      ).toBeInTheDocument();
      expect(document.body.textContent).not.toContain("[object Object]");
      expect(errSpy).not.toHaveBeenCalled();
      cleanup();
      vi.restoreAllMocks();
    }
  });
});

describe("findings/bubbles honesty — panels reflect the REAL artifact state", () => {
  // Branch on the live file state so the test asserts the truth either way:
  // absent → the honest empty state holds (verified live 2026-06-09: neither
  // file exists; :8700 /api/coordinator/findings → {"findings":[]} and
  // /api/coordinator/bubbles → {"bubbles":[]}); present → the panels render
  // the real rows. Never a fabricated row in either direction.
  const findingsPath = resolve(REPO_ROOT, "memory/surfaced_findings.jsonl");
  const bubblesPath = resolve(REPO_ROOT, "memory/coordinator_bubbles.jsonl");

  it("SurfacedFindingsPanel matches memory/surfaced_findings.jsonl (empty state or real rows)", () => {
    const { errSpy, warnSpy } = spyConsole();
    const rows = loadJsonlIfExists<SurfacedFinding>(findingsPath);
    if (rows !== null && rows.length > 0) {
      render(<SurfacedFindingsPanel initial={rows} />);
      const panel = within(screen.getByTestId("surfaced-findings-panel"));
      expect(panel.queryByTestId("findings-empty")).toBeNull();
      expect(panel.getAllByTestId(/^finding-/).length).toBe(rows.length);
      for (const f of rows) {
        if (typeof f.finding_id === "string" && f.finding_id) {
          expect(panel.getByTestId(`finding-${f.finding_id}`)).toBeTruthy();
        }
      }
    } else {
      render(<SurfacedFindingsPanel initial={[]} />);
      const panel = within(screen.getByTestId("surfaced-findings-panel"));
      expect(panel.getByTestId("findings-empty")).toBeInTheDocument();
      expect(panel.queryByTestId(/^finding-/)).toBeNull();
    }
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("BubblesPanel matches memory/coordinator_bubbles.jsonl (empty state or real rows)", () => {
    const { errSpy, warnSpy } = spyConsole();
    const rows = loadJsonlIfExists<Bubble>(bubblesPath);
    if (rows !== null && rows.length > 0) {
      render(<BubblesPanel initial={rows} />);
      const panel = within(screen.getByTestId("bubbles-panel"));
      expect(panel.queryByTestId("bubbles-empty")).toBeNull();
      expect(panel.getAllByTestId(/^bubble-/).length).toBe(rows.length);
    } else {
      render(<BubblesPanel initial={[]} />);
      const panel = within(screen.getByTestId("bubbles-panel"));
      expect(panel.getByTestId("bubbles-empty")).toBeInTheDocument();
      expect(panel.queryByTestId(/^bubble-/)).toBeNull();
    }
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});
